#!/usr/bin/env python3
"""
Bulk Download Semantic Scholar Dataset Snapshots and Load into SQLite.
"""

import argparse
import gzip
import json
import logging
import os
import requests
import sqlite3
import sys
import time
from datetime import datetime
from tenacity import retry, wait_exponential, retry_if_exception_type, stop_after_attempt
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

class BaseDownloader:
    def __init__(self, output_dir, api_key=None):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.session = requests.Session()
        
        # Configure session with proper timeouts and retries
        self.session.timeout = 60
        
        if api_key:
            self.session.headers.update({"x-api-key": api_key})
            logger.info("Using API key for authentication")
        else:
            logger.info("Using public API (no API key)")
            
        # Add user agent
        self.session.headers.update({
            "User-Agent": "SemanticScholarDatasetDownloader/1.0"
        })
        
        self.db_path = os.path.join(output_dir, "semantic_scholar.db")
        self.conn = self._init_db()
        self._configure_sqlite()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        return conn

    def _configure_sqlite(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA wal_autocheckpoint=1000;")  # auto-checkpoint every 1000 frames
        cur.execute("PRAGMA temp_store=MEMORY;")
        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.execute("PRAGMA optimize;")
            self.conn.close()
        self.session.close()

class DatasetDownloader(BaseDownloader):
    BASE = "https://api.semanticscholar.org/datasets/v1"

    @retry(wait=wait_exponential(multiplier=1, max=30),
           retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout)),
           stop=stop_after_attempt(3))
    def _get_with_retry(self, path, **kwargs):
        return self._get(path, **kwargs)
    
    def _get(self, path, **kwargs):
        url = f"{self.BASE}{path}"
        
        # Add timeout if not specified
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 60  # 60 second timeout
            
        logger.info(f"Making API request to: {path}")
        start_time = time.time()
        
        resp = self.session.get(url, **kwargs)
        
        request_time = time.time() - start_time
        logger.info(f"API request completed in {request_time:.1f}s: {resp.status_code}")
        
        # Don't retry on authentication errors - fail immediately
        if resp.status_code == 401:
            resp.raise_for_status()
        
        # Handle rate limiting
        if resp.status_code == 429:
            # Log all headers for debugging
            logger.warning(f"Rate limited! Response headers: {dict(resp.headers)}")
            
            # Check for Retry-After header
            retry_after_header = resp.headers.get('Retry-After')
            if retry_after_header:
                retry_after = int(retry_after_header)
                logger.warning(f"API provided Retry-After: {retry_after} seconds")
            else:
                # For 1 RPS rate limit, waiting 2 seconds should be sufficient
                retry_after = 2
                logger.warning(f"No Retry-After header, using default: {retry_after} seconds")
            
            logger.warning(f"Rate limited by API, waiting {retry_after} seconds...")
            time.sleep(retry_after)
            return self._get(path, **kwargs)  # Retry once after waiting
        
        resp.raise_for_status()
        return resp
    
    def get_latest_release_id(self) -> str:
        """
        Fetch the latest release ID. Uses the 'latest' shortcut,
        which returns a JSON object: {"release_id": "...", ...}
        """
        data = self._get_with_retry("/release/latest").json()
        # API returns "release_id" (snake_case) per S2ORC example :contentReference[oaicite:3]{index=3}
        return data.get("release_id")    
    
    def list_releases(self):
        data = self._get_with_retry("/release").json()
        return data.get("releases", [])

    def list_versions(self, release_id, dataset="papers"):
        data = self._get_with_retry(f"/release/{release_id}/dataset/{dataset}/versions").json()
        return data.get("versions", [])

    def list_files(self, release_id: str, dataset: str = "papers") -> list[dict]:
        """
        List all files for a given release and dataset.
        The endpoint returns {"files": [...]} for a specific dataset :contentReference[oaicite:4]{index=4}.
        """
        logger.info(f"Requesting file list for release {release_id}, dataset {dataset}...")
        
        try:
            response = self._get(f"/release/{release_id}/dataset/{dataset}")
            
            if response.status_code == 401:
                logger.error("Authentication required! The file listing endpoint requires a valid API key.")
                logger.error("Please provide an API key using --api-key parameter.")
                logger.error("You can get an API key from: https://www.semanticscholar.org/product/api")
                raise requests.exceptions.HTTPError(f"401 Unauthorized: API key required for dataset file listing")
            
            data = response.json()
            files = data.get("files", [])
            
            # Convert URL-based files to structured format
            structured_files = []
            for file_item in files:
                if isinstance(file_item, str):
                    # File is a URL string - extract filename and create structure
                    import urllib.parse
                    parsed_url = urllib.parse.urlparse(file_item)
                    filename = parsed_url.path.split('/')[-1]
                    
                    structured_files.append({
                        'path': filename,
                        'url': file_item,
                        'size': 0  # Size not available from URL format
                    })
                elif isinstance(file_item, dict):
                    # File is already structured
                    structured_files.append(file_item)
                    
            logger.info(f"Successfully retrieved {len(structured_files)} files from API")
            return structured_files
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout while fetching file list for release {release_id}")
            raise
        except requests.exceptions.HTTPError as e:
            if "401" in str(e):
                # Already handled above
                raise
            logger.error(f"HTTP error while fetching file list: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed while fetching file list: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error while fetching file list: {e}")
            raise

    @retry(wait=wait_exponential(multiplier=1, max=60),
           retry=retry_if_exception_type(requests.exceptions.RequestException))
    def download_file(self, file_meta):
        url = file_meta["url"]
        local_path = os.path.join(self.output_dir, file_meta["path"])
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        # Get file size for progress tracking
        file_size = file_meta.get("size", 0)
        file_name = file_meta["path"]
        
        headers = {}
        # Use conditional request if we have Last-Modified stored
        if os.path.exists(local_path + ".meta"):
            last_mod = open(local_path + ".meta").read().strip()
            headers["If-Modified-Since"] = last_mod
        
        logger.info(f"Downloading {file_name} ({self._format_size(file_size)})")
        start_time = time.time()
        
        resp = self.session.get(url, headers=headers, stream=True)
        if resp.status_code == 304:
            logger.info(f"{file_meta['path']} not modified, skipping.")
            return file_meta["path"], False
        resp.raise_for_status()
        
        # Get actual content length from response headers if available
        content_length = int(resp.headers.get('Content-Length', file_size or 0))
        
        # Save file with progress tracking
        downloaded = 0
        with open(local_path, "wb") as f_out:
            for chunk in resp.iter_content(8192):
                f_out.write(chunk)
                downloaded += len(chunk)
        
        download_time = time.time() - start_time
        download_speed = downloaded / download_time if download_time > 0 else 0
        
        logger.info(f"Downloaded {file_name}: {self._format_size(downloaded)} in {download_time:.1f}s "
                   f"({self._format_size(download_speed)}/s)")
        
        # Save new Last-Modified
        last_mod = resp.headers.get("Last-Modified", datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT"))
        with open(local_path + ".meta", "w") as m:
            m.write(last_mod)
        return file_meta["path"], True

    def run(self, max_workers: int = 4, dataset: str = "papers"):
        start_time = time.time()
        
        try:
            # 1. Get the single latest release ID
            logger.info("Fetching latest release information...")
            latest_release = self.get_latest_release_id()
            logger.info(f"Using latest release: {latest_release}")

            # Add delay to respect 1 RPS rate limit
            logger.info("Waiting 1 second to respect API rate limit...")
            time.sleep(1.1)  # Wait slightly more than 1 second for 1 RPS

            # 2. List files for that release
            logger.info(f"Fetching file list for {dataset} dataset...")
            files = self.list_files(latest_release, dataset=dataset)
            
            # Calculate total size and show file breakdown
            total_size = sum(f.get("size", 0) for f in files)
            logger.info(f"Found {len(files)} files in release {latest_release}")
            logger.info(f"Total download size: {self._format_size(total_size)}")
            
            # Show file breakdown
            logger.info("Files to download:")
            for i, file_meta in enumerate(files[:10]):  # Show first 10 files
                size_str = self._format_size(file_meta.get("size", 0))
                logger.info(f"  {i+1:2d}. {file_meta['path']} ({size_str})")
            if len(files) > 10:
                logger.info(f"  ... and {len(files) - 10} more files")

            # 3. Parallel download & process
            logger.info(f"Starting download with {max_workers} workers...")
            downloaded_count = 0
            processed_count = 0
            skipped_count = 0
            total_downloaded_size = 0
            total_files = len(files)
            
            with ThreadPoolExecutor(max_workers=max_workers) as exe:
                futures = {exe.submit(self.download_file, f): f for f in files}
                
                with tqdm(total=len(futures), desc="Overall Progress", unit="files") as pbar:
                    for fut in as_completed(futures):
                        try:
                            path, updated = fut.result()
                            current_file_num = downloaded_count + skipped_count + 1
                            
                            # Always process files (whether newly downloaded or existing)
                            if updated:
                                downloaded_count += 1
                                file_size = os.path.getsize(os.path.join(self.output_dir, path))
                                total_downloaded_size += file_size
                                logger.info(f"Downloaded file {current_file_num}/{total_files}: {path}")
                            else:
                                skipped_count += 1
                                logger.info(f"Skipped download of file {current_file_num}/{total_files} (not modified): {path}")
                            
                            # Process the file (whether downloaded or skipped)
                            logger.info(f"Processing file {current_file_num}/{total_files}: {path}")
                            process_start = time.time()
                            records_processed = self._process_file(path, dataset)
                            process_time = time.time() - process_start
                            
                            processed_count += 1
                            logger.info(f"Processed file {current_file_num}/{total_files} ({path}): {records_processed} records in {process_time:.1f}s")
                            
                            pbar.update(1)
                            pbar.set_postfix({
                                'Downloaded': downloaded_count,
                                'Processed': processed_count, 
                                'Skipped': skipped_count
                            })
                            
                        except Exception as e:
                            logger.error(f"Error processing file: {e}")
                            pbar.update(1)
            
            # Final statistics
            total_time = time.time() - start_time
            avg_speed = total_downloaded_size / total_time if total_time > 0 else 0
            
            logger.info("=" * 60)
            logger.info("DOWNLOAD COMPLETE - SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Total files found: {len(files)}")
            logger.info(f"Files downloaded: {downloaded_count}")
            logger.info(f"Files processed: {processed_count}")
            logger.info(f"Files skipped: {skipped_count}")
            logger.info(f"Total data downloaded: {self._format_size(total_downloaded_size)}")
            logger.info(f"Total time: {total_time:.1f}s")
            logger.info(f"Average speed: {self._format_size(avg_speed)}/s")
            logger.info(f"Database location: {self.db_path}")
            
            # Show database statistics
            try:
                self._show_database_stats()
            except Exception as e:
                logger.warning(f"Could not generate database statistics: {e}")
            
            logger.info("=" * 60)
            
        except requests.exceptions.HTTPError as e:
            if "401" in str(e):
                logger.error("")
                logger.error("=" * 60)
                logger.error("AUTHENTICATION ERROR")
                logger.error("=" * 60)
                logger.error("The Semantic Scholar datasets API requires authentication.")
                logger.error("Please obtain an API key from:")
                logger.error("  https://www.semanticscholar.org/product/api")
                logger.error("")
                logger.error("Then run the script with:")
                logger.error(f"  python {sys.argv[0]} --api-key YOUR_API_KEY")
                logger.error("=" * 60)
                raise SystemExit(1)
            else:
                raise

    def _format_size(self, size_bytes):
        """Format file size in human readable format."""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        
        while size >= 1024.0 and i < len(size_names) - 1:
            size /= 1024.0
            i += 1
        
        return f"{size:.1f} {size_names[i]}"

    def _show_database_stats(self):
        """Show statistics about the created database."""
        cur = self.conn.cursor()
        
        # Get list of tables
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cur.fetchall()]
        
        if not tables:
            logger.info("Database statistics: No tables created")
            return
        
        logger.info("Database statistics:")
        total_records = 0
        
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            total_records += count
            logger.info(f"  {table}: {count:,} records")
        
        logger.info(f"  Total records: {total_records:,}")
        
        # Get database file size
        if os.path.exists(self.db_path):
            db_size = os.path.getsize(self.db_path)
            logger.info(f"  Database size: {self._format_size(db_size)}")

    def _process_file(self, relative_path, dataset):
        full = os.path.join(self.output_dir, relative_path)
        # Use dataset name for table name instead of filename
        import re
        table = re.sub(r'[^a-zA-Z0-9_]', '_', dataset)
        # Ensure table name starts with letter or underscore
        if table[0].isdigit():
            table = f"table_{table}"
        
        logger.info(f"Creating/updating table: {table}")
        
        # Create comprehensive table schema based on Semantic Scholar structure
        cur = self.conn.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                paperId TEXT PRIMARY KEY,
                corpusId INTEGER,
                title TEXT,
                abstract TEXT,
                venue TEXT,
                publicationVenueId TEXT,
                year INTEGER,
                referenceCount INTEGER,
                citationCount INTEGER,
                influentialCitationCount INTEGER,
                isOpenAccess BOOLEAN,
                publicationDate TEXT,
                url TEXT,
                
                -- External IDs (flattened)
                externalIds_MAG TEXT,
                externalIds_CorpusId TEXT,
                externalIds_ACL TEXT,
                externalIds_PubMed TEXT,
                externalIds_DOI TEXT,
                externalIds_PubMedCentral TEXT,
                externalIds_DBLP TEXT,
                externalIds_ArXiv TEXT,
                
                -- Journal info (flattened)
                journal_name TEXT,
                journal_pages TEXT,
                journal_volume TEXT,
                
                -- Lists stored as JSON for complex queries
                authors TEXT,  -- JSON array
                s2FieldsOfStudy TEXT,  -- JSON array
                publicationTypes TEXT,  -- JSON array
                
                -- Full JSON for complete data access
                json_data TEXT
            )
        """)
        
        # Create indexes for common query patterns
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_year ON {table}(year)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_title ON {table}(title)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_venue ON {table}(venue)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_citationCount ON {table}(citationCount)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_doi ON {table}(externalIds_DOI)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_arxiv ON {table}(externalIds_ArXiv)")
        
        # Stream & insert with progress tracking
        records_processed = 0
        batch_count = 0
        
        with gzip.open(full, "rt", encoding="utf-8") as fin:
            batch = []
            for line_num, line in enumerate(fin, 1):
                try:
                    obj = json.loads(line)
                    
                    # Extract scalar fields
                    paper_id = obj.get("paperId") or obj.get("corpusid")
                    corpus_id = obj.get("corpusid")
                    title = obj.get("title", "")
                    abstract = obj.get("abstract", "")
                    venue = obj.get("venue", "")
                    publication_venue_id = obj.get("publicationvenueid")
                    year = obj.get("year")
                    reference_count = obj.get("referencecount")
                    citation_count = obj.get("citationcount")
                    influential_citation_count = obj.get("influentialcitationcount")
                    is_open_access = obj.get("isopenaccess")
                    publication_date = obj.get("publicationdate")
                    url = obj.get("url", "")
                    
                    # Extract external IDs
                    external_ids = obj.get("externalids", {}) or {}
                    external_mag = external_ids.get("MAG")
                    external_corpus_id = external_ids.get("CorpusId")
                    external_acl = external_ids.get("ACL")
                    external_pubmed = external_ids.get("PubMed")
                    external_doi = external_ids.get("DOI")
                    external_pmc = external_ids.get("PubMedCentral")
                    external_dblp = external_ids.get("DBLP")
                    external_arxiv = external_ids.get("ArXiv")
                    
                    # Extract journal info
                    journal = obj.get("journal", {}) or {}
                    journal_name = journal.get("name", "")
                    journal_pages = journal.get("pages")
                    journal_volume = journal.get("volume")
                    
                    # Store complex fields as JSON
                    authors_json = json.dumps(obj.get("authors", []))
                    s2_fields_json = json.dumps(obj.get("s2fieldsofstudy", []))
                    pub_types_json = json.dumps(obj.get("publicationtypes", []))
                    
                    # Full JSON for complete access
                    full_json = json.dumps(obj)
                    
                    batch.append((
                        paper_id, corpus_id, title, abstract, venue, publication_venue_id,
                        year, reference_count, citation_count, influential_citation_count,
                        is_open_access, publication_date, url,
                        external_mag, external_corpus_id, external_acl, external_pubmed,
                        external_doi, external_pmc, external_dblp, external_arxiv,
                        journal_name, journal_pages, journal_volume,
                        authors_json, s2_fields_json, pub_types_json, full_json
                    ))
                    records_processed += 1
                    
                    if len(batch) >= 1000:
                        cur.executemany(f"""
                            INSERT OR REPLACE INTO {table} VALUES (
                                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?
                            )
                        """, batch)
                        batch.clear()
                        batch_count += 1
                        
                        # Log progress every 10 batches (10k records)
                        if batch_count % 10 == 0:
                            logger.info(f"  Processed {records_processed:,} records from {relative_path}")
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping invalid JSON on line {line_num} in {relative_path}: {e}")
                except Exception as e:
                    logger.error(f"Error processing line {line_num} in {relative_path}: {e}")
            
            # Insert remaining batch
            if batch:
                cur.executemany(f"""
                    INSERT OR REPLACE INTO {table} VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?
                    )
                """, batch)
        
        self.conn.commit()
        logger.info(f"  Completed processing {relative_path}: {records_processed:,} total records")
        return records_processed

def main():
    parser = argparse.ArgumentParser(description="Download and process Semantic Scholar dataset")
    parser.add_argument("--output-dir", default="semantic_scholar_db", 
                       help="Output directory for downloaded files and database")
    parser.add_argument("--dataset", default="papers", 
                       help="Dataset to download (default: papers)")
    parser.add_argument("--api-key", help="Semantic Scholar API key (optional)")
    parser.add_argument("--workers", type=int, default=4, 
                       help="Number of parallel download workers")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("SEMANTIC SCHOLAR DATASET DOWNLOADER")
    logger.info("=" * 60)
    logger.info(f"Output directory: {args.output_dir}")
    logger.info(f"Dataset: {args.dataset}")
    logger.info(f"Workers: {args.workers}")
    logger.info(f"API key: {'Yes' if args.api_key else 'No (using public API)'}")
    logger.info("=" * 60)

    downloader = DatasetDownloader(output_dir=args.output_dir, api_key=args.api_key)
    try:
        downloader.run(max_workers=args.workers, dataset=args.dataset)
        logger.info("Process completed successfully!")
    except KeyboardInterrupt:
        logger.info("Download interrupted by user")
    except Exception as e:
        logger.error(f"Download failed: {e}")
        raise
    finally:
        logger.info("Cleaning up...")
        downloader.close()

if __name__ == "__main__":
    main()
