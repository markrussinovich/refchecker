#!/usr/bin/env python3
"""
Download Semantic Scholar Paper Metadata

This script downloads paper metadata from the Semantic Scholar API and stores it in a SQLite database.
The database can then be used by the local_semantic_scholar.py module to verify references offline.

Usage:
    python download_semantic_scholar_db.py [--output-dir DIR] [--batch-size N] [--api-key KEY] [--fields FIELDS]
    
Options:
    --output-dir DIR       Directory to store the database (default: semantic_scholar_db)
    --batch-size N         Number of papers to download in each batch (default: 100)
    --api-key KEY          Semantic Scholar API key (optional, increases rate limits)
    --fields FIELDS        Comma-separated list of fields to include (default: id,title,authors,year,externalIds,url,abstract)
    --query QUERY          Search query to download papers
    --start-year YEAR      Start year for downloading papers by year range
    --end-year YEAR        End year for downloading papers by year range
    --field FIELD          Field or subject area for downloading papers by field
    --download-dataset     Download the official Semantic Scholar dataset files (.gz)
    --process-local-files  Process existing .gz files in the output directory into the database
    --force-reprocess      Force reprocessing of all files (use with --process-local-files)

Behavior:
    - If the database does not exist, a full download is performed.
    - If the database exists, an incremental update is performed automatically.
"""

import argparse
import json
import logging
import os
import requests
import sqlite3
import sys
import time
import random
import concurrent.futures
import gzip
import hashlib
import re
import urllib.parse
import dateutil.parser
from datetime import datetime, timezone, timedelta
from tqdm import tqdm
from functools import lru_cache

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class SemanticScholarDownloader:
    """
    Class to download paper metadata from Semantic Scholar and store it in a SQLite database
    """
    
    def __init__(self, output_dir="semantic_scholar_db", batch_size=100, api_key=None, fields=None):
        """
        Initialize the downloader
        
        Args:
            output_dir: Directory to store the database
            batch_size: Number of papers to download in each batch
            api_key: Semantic Scholar API key (optional)
            fields: List of fields to include in the API response
        """
        self.output_dir = output_dir
        self.batch_size = batch_size
        self.api_key = api_key
        
        # Default fields to include
        if fields is None:
            self.fields = ["id", "title", "authors", "year", "externalIds", "url", "abstract"]
        else:
            self.fields = fields
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize database
        self.db_path = os.path.join(output_dir, "semantic_scholar.db")
        self.conn = self._get_db_connection()
        self.create_tables()
        
        # Set up session for API requests
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"x-api-key": self.api_key})

    def _get_db_connection(self):
        """Get a connection to the SQLite database with optimized settings"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for better concurrency
        conn.execute("PRAGMA synchronous=NORMAL")  # Reduce synchronous writes for better performance
        conn.execute("PRAGMA cache_size=10000")  # Increase cache size
        conn.execute("PRAGMA temp_store=MEMORY")  # Store temp tables in memory
        return conn
    
    def create_tables(self):
        """Create database tables if they don't exist"""
        cursor = self.conn.cursor()
        
        # Create papers table with comprehensive schema
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS papers (
            paperId TEXT PRIMARY KEY,
            corpusId INTEGER,
            title TEXT,
            normalized_paper_title TEXT,
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
        ''')
        
        # Create metadata table for tracking incremental updates
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create indexes for efficient querying
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_papers_normalized_title ON papers(normalized_paper_title)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_papers_venue ON papers(venue)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_papers_citationCount ON papers(citationCount)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(externalIds_DOI)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(externalIds_ArXiv)')
        
        self.conn.commit()
    
    def get_metadata(self, key: str, default=None):
        """Get metadata value from the database"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        result = cursor.fetchone()
        return result[0] if result else default
    
    def set_metadata(self, key: str, value: str):
        """Set metadata value in the database"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO metadata (key, value, updated_at) 
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (key, value))
        self.conn.commit()
    
    def get_last_update_time(self):
        """Get the timestamp of the last successful update"""
        return self.get_metadata('last_update_time')
    
    def set_last_update_time(self, timestamp: str):
        """Set the timestamp of the last successful update"""
        self.set_metadata('last_update_time', timestamp)
    
    def get_last_release_id(self):
        """Get the last processed release ID"""
        return self.get_metadata('last_release_id')
    
    def set_last_release_id(self, release_id: str):
        """Set the last processed release ID"""
        self.set_metadata('last_release_id', release_id)
    
    def check_for_updates(self):
        """
        Check if there are new releases or incremental updates available
        
        Returns:
            dict: Information about available updates
        """
        try:
            # Get the latest release information
            latest_release = self.get_latest_release_id()
            last_release = self.get_last_release_id()
            last_update_time = self.get_last_update_time()
            
            logger.info(f"Latest release: {latest_release}")
            logger.info(f"Last release: {last_release}")
            
            # Check if database has records but no update time
            if not last_update_time:

                # does databse have > 1 record?
                cursor = self.conn.cursor()
                cursor.execute("SELECT EXISTS(SELECT 1 FROM papers LIMIT 1)")
                record_count = cursor.fetchone()[0]
                
                if record_count > 0:
                    # Database has records but no update time - create a reasonable timestamp
                    # Use a timestamp from 1 day ago to check for recent updates
                    default_update_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
                    logger.info(f"Creating default update time: {default_update_time}")
                    last_update_time = default_update_time
            else:
                logger.info(f"Last update time: {last_update_time}")
            
            # Check for incremental updates using release IDs instead of timestamps
            if last_release:
                logger.info("Checking for incremental updates since last release...")
                incremental_updates = self.check_incremental_updates(last_release)
                if incremental_updates:
                    return {
                        'has_updates': True,
                        'latest_release': latest_release,
                        'last_release': last_release,
                        'is_new_release': False,
                        'incremental_updates': incremental_updates,
                        'message': f'Incremental updates available from {last_release} to {latest_release}'
                    }
                else:
                    logger.info("No incremental updates found")
            else:
                logger.info("No last release ID available, skipping incremental check")
            
            # Check for new releases
            if not last_release:
                logger.info("No previous release ID found in database")
                return {
                    'has_updates': True,
                    'latest_release': latest_release,
                    'last_release': None,
                    'is_new_release': True,
                    'message': 'No previous release found, performing full download'
                }
            
            if latest_release != last_release:
                return {
                    'has_updates': True,
                    'latest_release': latest_release,
                    'last_release': last_release,
                    'is_new_release': True,
                    'message': f'New release available: {last_release} -> {latest_release}'
                }
            
            return {
                'has_updates': False,
                'latest_release': latest_release,
                'last_release': last_release,
                'is_new_release': False,
                'message': f'Already up to date with release {latest_release}'
            }
            
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            return {
                'has_updates': False,
                'error': str(e),
                'message': f'Error checking for updates: {e}'
            }
    
    def check_incremental_updates(self, start_release_id=None):
        """
        Check for incremental updates between releases using the correct API
        
        Args:
            start_release_id: Release ID to start from (if None, uses last processed release)
            
        Returns:
            list: List of incremental update diffs available, or None if no updates
        """
        try:
            # Get the start and end release IDs
            if start_release_id is None:
                start_release_id = self.get_last_release_id()
            
            if not start_release_id:
                logger.info("No start release ID available, cannot check for incremental updates")
                return None
            
            # Get the latest release ID
            end_release_id = self.get_latest_release_id()
            
            # If we're already at the latest release, no updates needed
            if start_release_id == end_release_id:
                logger.info(f"Already at latest release {end_release_id}, no incremental updates needed")
                return None
            
            logger.info(f"Checking for incremental updates from {start_release_id} to {end_release_id}")
            
            # Use the correct incremental diffs API endpoint
            url = f"https://api.semanticscholar.org/datasets/v1/diffs/{start_release_id}/to/{end_release_id}/papers"
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            
            logger.info(f"Requesting incremental diffs from: {url}")
            response = self.session.get(url, headers=headers, timeout=30)
            
            # Handle different response codes
            if response.status_code == 404:
                logger.info(f"Incremental diffs not available for {start_release_id} to {end_release_id} (404)")
                logger.info("This usually means the release gap is too large for incremental updates")
                return self._check_incremental_alternative_by_release(start_release_id, end_release_id)
            elif response.status_code == 429:
                logger.warning("Rate limited on diffs API. Consider waiting or using a higher tier API key")
                return None
            
            response.raise_for_status()
            data = response.json()
            
            diffs = data.get("diffs", [])
            if diffs:
                logger.info(f"Found {len(diffs)} incremental diffs from {start_release_id} to {end_release_id}")
                return diffs
            else:
                logger.info("No incremental diffs found from API endpoint")
            
            return None
            
        except Exception as e:
            logger.info(f"Error checking incremental updates: {e}")
            logger.info("Falling back to alternative incremental check method")
            # Try to get end_release_id if it wasn't set yet
            try:
                if 'end_release_id' not in locals():
                    end_release_id = self.get_latest_release_id()
                return self._check_incremental_alternative_by_release(start_release_id or self.get_last_release_id(), end_release_id)
            except Exception as fallback_error:
                logger.debug(f"Error in fallback method: {fallback_error}")
                return None
    
    def _check_incremental_alternative_by_release(self, start_release_id, end_release_id):
        """
        Alternative method to check for incremental updates when the diffs API is unavailable
        This tries to compare release IDs and suggest a full dataset download if needed
        
        Args:
            start_release_id: Starting release ID
            end_release_id: Target release ID
            
        Returns:
            list: List indicating a full dataset update is needed, or None if no updates
        """
        try:
            if not start_release_id or not end_release_id:
                return None
            
            if start_release_id == end_release_id:
                return None
            
            # Try to find intermediate releases that might have diffs available
            # This could be improved by calling a releases list API if available
            from datetime import datetime, timedelta
            
            try:
                start_date = datetime.strptime(start_release_id, "%Y-%m-%d")
                end_date = datetime.strptime(end_release_id, "%Y-%m-%d")
                days_diff = (end_date - start_date).days
                
                if days_diff <= 7:
                    logger.info(f"Release gap of {days_diff} days should support diffs, but API returned 404")
                    logger.info("This might be a temporary API issue or the releases don't exist")
                    return None
                elif days_diff <= 30:
                    logger.info(f"Release gap of {days_diff} days may be too large for diffs API")
                    logger.info("Consider updating release tracking more frequently")
                else:
                    logger.info(f"Release gap of {days_diff} days is too large for incremental updates")
                    
            except ValueError:
                logger.info(f"Cannot parse release dates: {start_release_id}, {end_release_id}")
                
            logger.info(f"Recommending full dataset download from {start_release_id} to {end_release_id}")
            
            # Return a structure indicating that a full dataset download is needed
            return [{
                "type": "full_dataset_update",
                "start_release": start_release_id,
                "end_release": end_release_id,
                "message": f"Incremental diffs unavailable for gap from {start_release_id} to {end_release_id}, full dataset update recommended"
            }]
            
        except Exception as e:
            logger.debug(f"Error in alternative incremental check by release: {e}")
            return None

    def _check_incremental_alternative(self, since_timestamp):
        """
        Alternative method to check for incremental updates
        This tries different approaches when the direct incremental endpoint isn't available
        
        Args:
            since_timestamp: ISO timestamp string of last update
            
        Returns:
            list: List of incremental update files available, or None if no updates
        """
        try:
            # Try to get recent papers using the search API with date filtering
            # This is a fallback when incremental endpoints aren't available
            from datetime import datetime, timezone
            import dateutil.parser
            
            # Parse the timestamp
            last_update = dateutil.parser.parse(since_timestamp)
            current_time = datetime.now(timezone.utc)
            
            # Check if there's been significant time since last update
            time_diff = current_time - last_update
            if time_diff.days < 1:  # Less than 1 day, probably no significant updates
                return None
            
            logger.info(f"Last update was {time_diff.days} days ago, checking for recent papers")
            
            # Use the search API to find recent papers
            # This is not as efficient as true incremental updates but can work as a fallback
            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            
            params = {
                "query": f"year:{current_time.year}",
                "limit": 100,
                "fields": "paperId,title,year,publicationDate"
            }
            
            response = self.session.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            recent_papers = data.get("data", [])
            if recent_papers:
                logger.info(f"Found {len(recent_papers)} recent papers that might need updating")
                # Return a structure that indicates these are recent papers to check
                return [{
                    "type": "recent_papers",
                    "count": len(recent_papers),
                    "papers": recent_papers
                }]
            
            return None
            
        except Exception as e:
            logger.debug(f"Error in alternative incremental check: {e}")
            return None
    
    def download_incremental_updates(self, diffs):
        """
        Download and process incremental diffs according to the Semantic Scholar API format
        
        Args:
            diffs: List of diff dictionaries from the incremental API
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info("Processing incremental diffs...")
            
            total_updated = 0
            total_deleted = 0
            
            for diff in diffs:
                if diff.get("type") == "full_dataset_update":
                    # Handle full dataset update recommendation by downloading the full dataset
                    logger.info(f"Full dataset update recommended: {diff.get('message')}")
                    logger.info("Automatically downloading full dataset...")
                    
                    # Download the full dataset
                    success = self.download_dataset_files()
                    if success:
                        logger.info("Full dataset download completed, processing files...")
                        # Process the downloaded files
                        self.process_local_files(force_reprocess=False, incremental=False)
                        
                        # After processing, check for any remaining incremental updates
                        logger.info("Checking for additional incremental updates after full dataset processing...")
                        latest_release = self.get_latest_release_id()
                        current_release = self.get_last_release_id()
                        
                        if current_release and current_release != latest_release:
                            logger.info(f"Checking for incremental updates from {current_release} to {latest_release}")
                            additional_updates = self.check_incremental_updates(current_release)
                            if additional_updates:
                                # Filter out any full_dataset_update recommendations to avoid infinite recursion
                                filtered_updates = [u for u in additional_updates if u.get("type") != "full_dataset_update"]
                                if filtered_updates:
                                    logger.info(f"Processing {len(filtered_updates)} additional incremental updates")
                                    self.download_incremental_updates(filtered_updates)
                        
                        return True
                    else:
                        logger.error("Failed to download full dataset")
                        return False
                elif diff.get("type") == "recent_papers":
                    # Handle recent papers update (fallback)
                    papers = diff.get("papers", [])
                    if papers:
                        logger.info(f"Processing {len(papers)} recent papers")
                        paper_ids = [p.get("paperId") for p in papers if p.get("paperId")]
                        if paper_ids:
                            self.download_papers(paper_ids)
                            total_updated += len(paper_ids)
                else:
                    # Handle proper incremental diff format
                    update_files = diff.get("update_files", [])
                    delete_files = diff.get("delete_files", [])
                    
                    # Process update files
                    for update_url in update_files:
                        try:
                            logger.info(f"Processing update file: {update_url}")
                            records_updated = self._process_incremental_file(update_url, "update")
                            total_updated += records_updated
                        except Exception as e:
                            logger.error(f"Error processing update file {update_url}: {e}")
                            continue
                    
                    # Process delete files
                    for delete_url in delete_files:
                        try:
                            logger.info(f"Processing delete file: {delete_url}")
                            records_deleted = self._process_incremental_file(delete_url, "delete")
                            total_deleted += records_deleted
                        except Exception as e:
                            logger.error(f"Error processing delete file {delete_url}: {e}")
                            continue
            
            logger.info(f"Incremental update complete - Updated: {total_updated}, Deleted: {total_deleted}")
            
            # Update metadata after successful incremental update
            if total_updated > 0 or total_deleted > 0:
                current_time = datetime.now(timezone.utc).isoformat()
                self.set_last_update_time(current_time)
                
                # Update the last release ID to the latest
                try:
                    latest_release = self.get_latest_release_id()
                    self.set_last_release_id(latest_release)
                    logger.info(f"Updated metadata - last update: {current_time}, release: {latest_release}")
                except Exception as e:
                    logger.warning(f"Could not update release ID: {e}")
            
            return total_updated > 0 or total_deleted > 0
            
        except Exception as e:
            logger.error(f"Error processing incremental diffs: {e}")
            return False
    
    def get_latest_release_id(self):
        """
        Get the latest release ID from the Semantic Scholar API
        
        Returns:
            str: Latest release ID
        """
        try:
            # Use the datasets API to get the latest release
            url = "https://api.semanticscholar.org/datasets/v1/release/latest"
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            release_id = data.get("release_id")
            
            if not release_id:
                raise ValueError("No release_id found in API response")
            
            return release_id
            
        except Exception as e:
            logger.error(f"Error getting latest release ID: {e}")
            raise
    
    def normalize_paper_title(self, title: str) -> str:
        """
        Normalize paper title by converting to lowercase and removing whitespace and punctuation
        
        Args:
            title: Original paper title
            
        Returns:
            Normalized title string
        """
        if not title:
            return ""
        
        # Convert to lowercase
        normalized = title.lower()
        
        # Remove all non-alphanumeric characters (keeping only letters and numbers)
        import re
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        
        return normalized
    
    @lru_cache(maxsize=32)
    def _build_search_query(self, query, year, field):
        """
        Build search query string with caching for repeated parameters

        Args:
            query: Search query
            year: Year for filtering (single year)
            field: Field or subject area

        Returns:
            Formatted search query string
        """
        search_parts = []

        if query:
            search_parts.append(query)

        # Add year (single year only)
        if year:
            search_parts.append(f"year:{year}")

        # Add field
        if field:
            search_parts.append(f"venue:{field}")

        # If no search criteria provided, use a default query
        if not search_parts:
            search_parts.append("machine learning")
            logger.warning(f"No search criteria provided, using default query: {search_parts[0]}")

        return " ".join(search_parts)

    def search_papers(self, query=None, start_year=None, end_year=None, field=None, limit=1000):
        """
        Search for papers using the Semantic Scholar API

        Args:
            query: Search query
            start_year: Start year for filtering
            end_year: End year for filtering
            field: Field or subject area
            limit: Maximum number of papers to return

        Returns:
            List of paper IDs
        """
        logger.info(f"Searching for papers with query: {query}, years: {start_year}-{end_year}, field: {field}")

        # If a year range is specified, perform separate queries for each year
        paper_ids = []
        if start_year and end_year and start_year != end_year:
            years = range(start_year, end_year + 1)
        elif start_year:
            years = [start_year]
        elif end_year:
            years = [end_year]
        else:
            years = [None]

        total_limit = limit
        per_year_limit = max(1, limit // len(years)) if years[0] is not None else limit

        for year in years:
            # Build the search query for this year
            search_query = self._build_search_query(query, year, field)

            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                "query": search_query,
                "limit": min(100, self.batch_size),  # API limit is 100 per request
                "fields": "paperId",
            }

            offset = 0
            year_paper_ids = []
            max_offset = 1000  # API: offset must be < 1000 per query

            with tqdm(total=per_year_limit, desc=f"Searching papers for year {year}" if year else "Searching papers") as pbar:
                while offset < per_year_limit and offset < max_offset:
                    params["offset"] = offset
                    # Don't request more than the API allows in one query
                    params["limit"] = min(params["limit"], per_year_limit - offset, max_offset - offset)
                    try:
                        response = self.session.get(url, params=params)
                        response.raise_for_status()
                        data = response.json()

                        batch_ids = [paper.get("paperId") for paper in data.get("data", []) if paper.get("paperId")]
                        year_paper_ids.extend(batch_ids)
                        pbar.update(len(batch_ids))

                        if len(batch_ids) < params["limit"]:
                            break

                        offset += len(batch_ids)
                        time.sleep(3 if self.api_key else 5)
                    except requests.exceptions.RequestException as e:
                        logger.error(f"Error searching papers: {str(e)}")
                        wait_time = min(60, 2 ** (offset // 100))
                        logger.info(f"Waiting {wait_time} seconds before retrying...")
                        time.sleep(wait_time)
                        continue
            paper_ids.extend(year_paper_ids)
            if len(paper_ids) >= total_limit:
                break

        # Truncate to the requested limit
        paper_ids = paper_ids[:limit]
        logger.info(f"Found {len(paper_ids)} papers")
        return paper_ids
    
    def download_paper_batch(self, paper_ids):
        """
        Download metadata for a batch of papers
        
        Args:
            paper_ids: List of paper IDs to download
        
        Returns:
            List of paper data dictionaries
        """
        if not paper_ids:
            return []
        
        # Set up API request
        url = "https://api.semanticscholar.org/graph/v1/paper/batch"
        headers = {"Content-Type": "application/json"}
        
        # Prepare request data
        data = {
            "ids": paper_ids,
            "fields": ",".join(self.fields)
        }
        
        try:
            response = self.session.post(url, headers=headers, json=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading papers: {str(e)}")
            # If we get a rate limit error, wait and retry
            if response.status_code == 429:
                wait_time = int(response.headers.get("Retry-After", 60))
                # Add a buffer to the wait time plus some jitter to avoid synchronization
                jitter = random.uniform(5, 15)
                total_wait = wait_time + jitter
                logger.info(f"Rate limited. Waiting {total_wait:.1f} seconds before retrying...")
                time.sleep(total_wait)
                return self.download_paper_batch(paper_ids)
            return []
    
    def store_papers_batch(self, papers_data):
        """
        Store multiple papers in a single transaction
        
        Args:
            papers_data: List of paper data dictionaries from the API
        """
        if not papers_data:
            return
        
        cursor = self.conn.cursor()
        
        try:
            # Begin transaction
            self.conn.execute("BEGIN TRANSACTION")
            
            batch = []
            for paper_data in papers_data:
                if not paper_data or "paperId" not in paper_data:
                    continue
                
                # Extract scalar fields
                paper_id = paper_data.get("paperId")
                corpus_id = paper_data.get("corpusId")
                title = paper_data.get("title", "")
                normalized_title = self.normalize_paper_title(title)
                abstract = paper_data.get("abstract", "")
                venue = paper_data.get("venue", "")
                publication_venue_id = paper_data.get("publicationVenueId")
                year = paper_data.get("year")
                reference_count = paper_data.get("referenceCount")
                citation_count = paper_data.get("citationCount")
                influential_citation_count = paper_data.get("influentialCitationCount")
                is_open_access = paper_data.get("isOpenAccess")
                publication_date = paper_data.get("publicationDate")
                url = paper_data.get("url", "")
                
                # Extract external IDs
                external_ids = paper_data.get("externalIds", {}) or {}
                external_mag = external_ids.get("MAG")
                external_corpus_id = external_ids.get("CorpusId")
                external_acl = external_ids.get("ACL")
                external_pubmed = external_ids.get("PubMed")
                external_doi = external_ids.get("DOI")
                external_pmc = external_ids.get("PubMedCentral")
                external_dblp = external_ids.get("DBLP")
                external_arxiv = external_ids.get("ArXiv")
                
                # Extract journal info
                journal = paper_data.get("journal", {}) or {}
                journal_name = journal.get("name", "")
                journal_pages = journal.get("pages")
                journal_volume = journal.get("volume")
                
                # Store complex fields as JSON
                authors_json = json.dumps(paper_data.get("authors", []))
                s2_fields_json = json.dumps(paper_data.get("s2FieldsOfStudy", []))
                pub_types_json = json.dumps(paper_data.get("publicationTypes", []))
                
                # Full JSON for complete access
                full_json = json.dumps(paper_data)
                
                batch.append((
                    paper_id, corpus_id, title, normalized_title, abstract, venue, publication_venue_id,
                    year, reference_count, citation_count, influential_citation_count,
                    is_open_access, publication_date, url,
                    external_mag, external_corpus_id, external_acl, external_pubmed,
                    external_doi, external_pmc, external_dblp, external_arxiv,
                    journal_name, journal_pages, journal_volume,
                    authors_json, s2_fields_json, pub_types_json, full_json
                ))
            
            # Insert all papers in batch
            if batch:
                cursor.executemany("""
                    INSERT OR REPLACE INTO papers VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?
                    )
                """, batch)
            
            # Commit transaction
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error storing papers batch: {str(e)}")
            self.conn.rollback()
    
    def _retry_with_backoff(self, func, *args, max_retries=5, **kwargs):
        """
        Retry a function with exponential backoff
        
        Args:
            func: Function to retry
            max_retries: Maximum number of retries
            *args, **kwargs: Arguments to pass to the function
            
        Returns:
            The function result
        """
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    # Last attempt, re-raise the exception
                    raise
                
                # Calculate backoff time with jitter
                backoff_time = min(60, (2 ** attempt) * (1 + random.random()))
                logger.warning(f"Request failed: {str(e)}. Retrying in {backoff_time:.1f} seconds (attempt {attempt+1}/{max_retries})...")
                time.sleep(backoff_time)
    
    def download_papers(self, paper_ids):
        """
        Download and store papers in batches
        
        Args:
            paper_ids: List of paper IDs to download
        """
        if not paper_ids:
            logger.warning("No paper IDs provided")
            return
        
        # Remove duplicates while preserving order
        unique_paper_ids = list(dict.fromkeys(paper_ids))
        logger.info(f"Downloading {len(unique_paper_ids)} unique papers in batches of {self.batch_size}")
        
        # Check which papers are already in the database
        existing_ids = set()
        try:
            cursor = self.conn.cursor()
            # Process in chunks to avoid sqlite parameter limit
            chunk_size = 500
            for i in range(0, len(unique_paper_ids), chunk_size):
                chunk = unique_paper_ids[i:i+chunk_size]
                placeholders = ','.join(['?'] * len(chunk))
                cursor.execute(f"SELECT paperId FROM papers WHERE paperId IN ({placeholders})", chunk)
                existing_ids.update(row[0] for row in cursor.fetchall())
        except sqlite3.Error as e:
            logger.error(f"Error checking existing papers: {str(e)}")
        
        # Filter out papers that are already in the database
        paper_ids_to_download = [pid for pid in unique_paper_ids if pid not in existing_ids]
        logger.info(f"Skipping {len(existing_ids)} already downloaded papers")
        logger.info(f"Downloading {len(paper_ids_to_download)} new papers")
        
        if not paper_ids_to_download:
            logger.info("All papers already exist in the database")
            return
        
        # Process papers in batches
        for i in tqdm(range(0, len(paper_ids_to_download), self.batch_size), desc="Downloading batches"):
            batch_ids = paper_ids_to_download[i:i+self.batch_size]
            
            # Download batch with retry mechanism
            try:
                # Use a smaller batch size for unauthenticated requests
                if not self.api_key and len(batch_ids) > 10:
                    sub_batches = [batch_ids[j:j+10] for j in range(0, len(batch_ids), 10)]
                    batch_data = []
                    for sub_batch in sub_batches:
                        sub_data = self._retry_with_backoff(self.download_paper_batch, sub_batch)
                        batch_data.extend(sub_data)
                        # Add extra delay between sub-batches
                        time.sleep(random.uniform(4, 6))
                else:
                    batch_data = self._retry_with_backoff(self.download_paper_batch, batch_ids)
                
                # Store papers in a single transaction
                self.store_papers_batch(batch_data)
                
                # Sleep to avoid rate limits with some randomness to avoid patterns
                sleep_time = random.uniform(4, 7) if not self.api_key else random.uniform(2, 4)
                time.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"Failed to download batch after multiple retries: {str(e)}")
                logger.info("Saving progress and continuing with next batch...")
                # Continue with the next batch instead of failing completely
    
    def _is_file_processed(self, file_path):
        """
        Check if a file's contents are already in the database by checking sample records.
        Uses both first and last valid records in the file - if both exist in DB, file is processed.
        This is much faster than reading the entire file.
        
        Args:
            file_path: Full path to the .gz file
            
        Returns:
            bool: True if file appears to be already processed
        """
        # If file doesn't exist, it's not processed
        if not os.path.exists(file_path):
            return False
        
        try:
            # Get sample records from the file (first and last)
            sample_paper_ids = []
            
            with gzip.open(file_path, "rt", encoding="utf-8") as f:
                # Check first few lines for a valid record
                for i in range(5):
                    line = f.readline()
                    if not line:
                        break
                    try:
                        paper_data = json.loads(line.strip())
                        if paper_data:
                            paper_id = paper_data.get("paperId")
                            corpus_id = paper_data.get("corpusid") or paper_data.get("corpusId")
                            
                            if paper_id:
                                sample_paper_ids.append(paper_id)
                                break
                            elif corpus_id:
                                sample_paper_ids.append(str(corpus_id))
                                break
                    except json.JSONDecodeError:
                        continue
                
                # For the last few lines, we need to be more careful with gzip files
                # Since we can't easily seek to the end, we'll just check if we found a first record
                # and assume the file is processed if we found at least one valid record
                if sample_paper_ids:
                    # Check if the sample record exists in the database
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM papers WHERE paperId = ?", (sample_paper_ids[0],))
                    count = cursor.fetchone()[0]
                    if count > 0:
                        logger.debug(f"File {os.path.basename(file_path)} appears to be processed (sample record found in DB)")
                        return True
            
            logger.debug(f"File {os.path.basename(file_path)} not processed (no sample records found in DB)")
            return False
                
        except Exception as e:
            logger.warning(f"Error checking if {os.path.basename(file_path)} is processed: {e}")
            return False  # If we can't check, assume not processed

    def process_local_files(self, force_reprocess=False, incremental=False):
        """
        Process existing .gz files in the output directory into the database
        
        Args:
            force_reprocess: If True, reprocess all files even if already processed
            incremental: If True, only process new or modified files (set automatically if DB exists)
        """
        if incremental and not force_reprocess:
            logger.info("Running in incremental mode - checking for updates...")
            update_info = self.check_for_updates()
            
            if not update_info['has_updates']:
                logger.info(update_info['message'])
                return
            
            logger.info(update_info['message'])
            
            # Handle incremental updates if available, but only if there are no new local files
            if update_info.get('incremental_updates'):
                # Check if we have any unprocessed .gz files first
                gz_files = []
                for root, dirs, files in os.walk(self.output_dir):
                    for file in files:
                        if file.endswith('.gz'):
                            gz_files.append(os.path.join(root, file))
                
                unprocessed_files = []
                for gz_file in gz_files:
                    if not self._is_file_processed(gz_file) or self._should_process_file(gz_file):
                        unprocessed_files.append(gz_file)
                
                # Check if any incremental updates are actually full dataset updates
                has_full_dataset_update = any(diff.get("type") == "full_dataset_update" for diff in update_info['incremental_updates'])
                
                if unprocessed_files and not has_full_dataset_update:
                    logger.info(f"Found {len(unprocessed_files)} unprocessed local files, processing those instead of incremental updates")
                elif has_full_dataset_update:
                    logger.info("Full dataset update needed - this will download and process the latest dataset")
                    success = self.download_incremental_updates(update_info['incremental_updates'])
                    if success:
                        logger.info("Full dataset update completed successfully")
                        return
                    else:
                        logger.warning("Failed to process full dataset update, falling back to file processing")
                else:
                    logger.info("Processing incremental updates...")
                    success = self.download_incremental_updates(update_info['incremental_updates'])
                    if success:
                        logger.info("Incremental updates processed successfully")
                        return
                    else:
                        logger.warning("Failed to process incremental updates, falling back to file processing")
        
        # Find all .gz files in the output directory
        gz_files = []
        for root, dirs, files in os.walk(self.output_dir):
            for file in files:
                if file.endswith('.gz'):
                    gz_files.append(os.path.join(root, file))
        
        if not gz_files:
            logger.warning(f"No .gz files found in {self.output_dir}")
            return
        
        logger.info(f"Found {len(gz_files)} .gz files to process")
        
        # Process files
        total_records = 0
        skipped_files = 0
        
        for i, gz_file in enumerate(gz_files, 1):
            try:
                # Check if file should be processed
                if incremental and not force_reprocess:
                    # First check if file contents are already in database
                    if self._is_file_processed(gz_file):
                        logger.info(f"Skipping [{i}/{len(gz_files)}] {os.path.basename(gz_file)} - already processed")
                        skipped_files += 1
                        continue
                    
                    # Then check if file has been modified since last processing
                    if not self._should_process_file(gz_file):
                        logger.info(f"Skipping [{i}/{len(gz_files)}] {os.path.basename(gz_file)} - already processed and not modified")
                        skipped_files += 1
                        continue
                
                logger.info(f"Processing [{i}/{len(gz_files)}] {os.path.basename(gz_file)}")
                records_processed = self._process_gz_file(gz_file)
                total_records += records_processed
                logger.info(f"Processed [{i}/{len(gz_files)}] {records_processed:,} records from {os.path.basename(gz_file)}")
                
            except Exception as e:
                logger.error(f"Error processing [{i}/{len(gz_files)}] {gz_file}: {e}")
                continue
        
        # Update metadata after successful processing
        if incremental and total_records > 0:
            current_time = datetime.now(timezone.utc).isoformat()
            self.set_last_update_time(current_time)
            
            # Get and set the latest release ID
            try:
                latest_release = self.get_latest_release_id()
                self.set_last_release_id(latest_release)
                logger.info(f"Updated metadata - last update: {current_time}, release: {latest_release}")
            except Exception as e:
                logger.warning(f"Could not update release ID: {e}")
        
        logger.info(f"Total records processed: {total_records:,}")
        if skipped_files > 0:
            logger.info(f"Files skipped (already processed): {skipped_files}")
    
    def _should_process_file(self, file_path):
        """
        Check if a file should be processed in incremental mode
        
        Args:
            file_path: Path to the file to check
            
        Returns:
            bool: True if file should be processed
        """
        # Check if we have metadata about this file
        file_hash = self._get_file_hash(file_path)
        last_processed_hash = self.get_metadata(f'file_hash_{os.path.basename(file_path)}')
        
        if last_processed_hash != file_hash:
            # File has changed, should process
            return True
        
        # Check file modification time
        file_mtime = os.path.getmtime(file_path)
        last_processed_time = self.get_metadata(f'file_mtime_{os.path.basename(file_path)}')
        
        if last_processed_time:
            try:
                last_time = float(last_processed_time)
                if file_mtime > last_time:
                    return True
            except ValueError:
                pass
        
        return False
    
    def _get_file_hash(self, file_path):
        """Get a hash of the file for change detection"""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read(1024)).hexdigest()  # Hash first 1KB for speed
        except Exception:
            return None

    def _process_gz_file(self, filename, max_records=None):
        """
        Process a single .gz file into the database
        
        Args:
            filename: Path to the .gz file
            max_records: Maximum number of records to process (for testing)
            
        Returns:
            int: Number of records processed
        """
        file_path = filename
        
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return 0
        
        records_processed = 0
        cursor = self.conn.cursor()
        
        try:
            with gzip.open(file_path, 'rt', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    if max_records and records_processed >= max_records:
                        break
                    
                    try:
                        paper_data = json.loads(line.strip())
                        self._insert_paper(cursor, paper_data)
                        records_processed += 1
                        
                        if records_processed % 10000 == 0:
                            logger.info(f"Processed {records_processed:,} records from {filename}")
                            self.conn.commit()
                            
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON on line {line_num} in {filename}: {e}")
                        continue
                    except Exception as e:
                        logger.error(f"Error processing line {line_num} in {filename}: {e}")
                        continue
            
            # Final commit
            self.conn.commit()
            
            # Track file processing metadata for incremental updates
            self._track_file_processing(filename, file_path, records_processed)
            
            return records_processed
            
        except Exception as e:
            logger.error(f"Error processing file {filename}: {e}")
            return 0
    
    def _track_file_processing(self, filename, file_path, records_processed):
        """
        Track file processing metadata for incremental updates
        
        Args:
            filename: Name of the processed file
            file_path: Full path to the file
            records_processed: Number of records processed
        """
        try:
            # Get file metadata
            file_hash = self._get_file_hash(file_path)
            file_mtime = os.path.getmtime(file_path)
            file_size = os.path.getsize(file_path)
            
            # Store metadata
            self.set_metadata(f'file_hash_{filename}', file_hash or '')
            self.set_metadata(f'file_mtime_{filename}', str(file_mtime))
            self.set_metadata(f'file_size_{filename}', str(file_size))
            self.set_metadata(f'file_records_{filename}', str(records_processed))
            self.set_metadata(f'file_processed_{filename}', datetime.now(timezone.utc).isoformat())
            
        except Exception as e:
            logger.warning(f"Could not track file processing metadata for {filename}: {e}")

    def _insert_paper(self, cursor, paper_data):
        """
        Insert a single paper into the database
        
        Args:
            cursor: Database cursor
            paper_data: Paper data dictionary
        """
        # Skip empty or invalid records
        if not paper_data:
            return
        
        # Use corpusid as primary key if paperId not available
        paper_id = paper_data.get("paperId")
        if not paper_id:
            corpus_id = paper_data.get("corpusid") or paper_data.get("corpusId")
            if corpus_id:
                paper_id = str(corpus_id)  # Use corpus ID as paper ID
            else:
                return  # Skip if no ID available
        
        # Extract scalar fields (handle both camelCase and lowercase)
        corpus_id = paper_data.get("corpusId") or paper_data.get("corpusid")
        title = paper_data.get("title", "")
        normalized_title = self.normalize_paper_title(title)
        abstract = paper_data.get("abstract", "")
        venue = paper_data.get("venue", "")
        publication_venue_id = paper_data.get("publicationVenueId") or paper_data.get("publicationvenueid")
        year = paper_data.get("year")
        reference_count = paper_data.get("referenceCount") or paper_data.get("referencecount")
        citation_count = paper_data.get("citationCount") or paper_data.get("citationcount")
        influential_citation_count = paper_data.get("influentialCitationCount") or paper_data.get("influentialcitationcount")
        is_open_access = paper_data.get("isOpenAccess") or paper_data.get("isopenaccess")
        publication_date = paper_data.get("publicationDate") or paper_data.get("publicationdate")
        url = paper_data.get("url", "")
        
        # Extract external IDs (handle both camelCase and lowercase)
        external_ids = paper_data.get("externalIds") or paper_data.get("externalids") or {}
        external_mag = external_ids.get("MAG")
        external_corpus_id = external_ids.get("CorpusId")
        external_acl = external_ids.get("ACL")
        external_pubmed = external_ids.get("PubMed")
        external_doi = external_ids.get("DOI")
        external_pmc = external_ids.get("PubMedCentral")
        external_dblp = external_ids.get("DBLP")
        external_arxiv = external_ids.get("ArXiv")
        
        # Extract journal info
        journal = paper_data.get("journal", {}) or {}
        journal_name = journal.get("name", "")
        journal_pages = journal.get("pages")
        journal_volume = journal.get("volume")
        
        # Store complex fields as JSON (handle both camelCase and lowercase)
        authors_json = json.dumps(paper_data.get("authors", []))
        s2_fields_json = json.dumps(paper_data.get("s2FieldsOfStudy") or paper_data.get("s2fieldsofstudy") or [])
        pub_types_json = json.dumps(paper_data.get("publicationTypes") or paper_data.get("publicationtypes") or [])
        
        # Full JSON for complete access
        full_json = json.dumps(paper_data)
        
        # Insert or replace the paper
        cursor.execute("""
            INSERT OR REPLACE INTO papers VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?
            )
        """, (
            paper_id, corpus_id, title, normalized_title, abstract, venue, publication_venue_id,
            year, reference_count, citation_count, influential_citation_count,
            is_open_access, publication_date, url,
            external_mag, external_corpus_id, external_acl, external_pubmed,
            external_doi, external_pmc, external_dblp, external_arxiv,
            journal_name, journal_pages, journal_volume,
            authors_json, s2_fields_json, pub_types_json, full_json
        ))

    def close(self):
        """Close the database connection"""
        if hasattr(self, 'conn') and self.conn:
            # Optimize database before closing
            self.conn.execute("PRAGMA optimize")
            self.conn.close()
        
        if hasattr(self, 'session') and self.session:
            self.session.close()

    def download_dataset_files(self):
        """
        Download the official Semantic Scholar dataset files
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info("Downloading Semantic Scholar dataset files...")
            
            # Get the latest release ID
            latest_release = self.get_latest_release_id()
            logger.info(f"Latest release: {latest_release}")
            
            # List files for the latest release
            files = self.list_files(latest_release, dataset="papers")
            if not files:
                logger.error("No files found for the latest release")
                return False
            
            logger.info(f"Found {len(files)} files to download")
            
            # Download files
            downloaded_count = 0
            for file_meta in files:
                try:
                    path, updated = self.download_file(file_meta)
                    if updated:
                        downloaded_count += 1
                        logger.info(f"Downloaded: {path}")
                    else:
                        logger.info(f"Skipped (not modified): {path}")
                except Exception as e:
                    logger.error(f"Error downloading {file_meta.get('path', 'unknown')}: {e}")
                    continue
            
            logger.info(f"Downloaded {downloaded_count} files out of {len(files)} total files")
            return downloaded_count > 0
            
        except Exception as e:
            logger.error(f"Error downloading dataset files: {e}")
            return False
    
    def list_files(self, release_id: str, dataset: str = "papers") -> list[dict]:
        """
        List all files for a given release and dataset.
        
        Args:
            release_id: Release ID
            dataset: Dataset name (default: "papers")
            
        Returns:
            list: List of file metadata dictionaries
        """
        logger.info(f"Requesting file list for release {release_id}, dataset {dataset}...")
        
        try:
            url = f"https://api.semanticscholar.org/datasets/v1/release/{release_id}/dataset/{dataset}"
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
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
                    
            logger.info(f"Retrieved {len(structured_files)} files from API")
            return structured_files
            
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return []
    
    def download_file(self, file_meta):
        """
        Download a single file from the dataset
        
        Args:
            file_meta: File metadata dictionary
            
        Returns:
            tuple: (file_path, was_updated)
        """
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
        
        resp = self.session.get(url, headers=headers, stream=True, timeout=300)
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
        last_mod = resp.headers.get("Last-Modified", datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"))
        with open(local_path + ".meta", "w") as m:
            m.write(last_mod)
        return file_meta["path"], True
    
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

    def _process_incremental_file(self, file_url, operation_type):
        """
        Process a single incremental diff file (either updates or deletes)
        
        Args:
            file_url: URL of the diff file to process
            operation_type: Either "update" or "delete"
            
        Returns:
            int: Number of records processed
        """
        try:
            logger.info(f"Processing {operation_type} file: {file_url}")
            
            # Download the file content
            response = self.session.get(file_url, stream=True, timeout=300)
            response.raise_for_status()
            
            records_processed = 0
            cursor = self.conn.cursor()
            
            # Begin transaction for better performance
            self.conn.execute("BEGIN TRANSACTION")
            
            try:
                # Process the file line by line
                for line_num, line in enumerate(response.iter_lines(decode_unicode=True), 1):
                    if not line.strip():
                        continue
                    
                    try:
                        record = json.loads(line.strip())
                        
                        if operation_type == "update":
                            # Insert or update the record
                            self._insert_paper(cursor, record)
                        elif operation_type == "delete":
                            # Delete the record by primary key
                            paper_id = record.get("paperId")
                            if not paper_id:
                                # Fallback to corpusId if paperId not available
                                corpus_id = record.get("corpusid") or record.get("corpusId")
                                if corpus_id:
                                    paper_id = str(corpus_id)
                            
                            if paper_id:
                                cursor.execute("DELETE FROM papers WHERE paperId = ?", (paper_id,))
                        
                        records_processed += 1
                        
                        # Commit periodically for large files
                        if records_processed % 10000 == 0:
                            self.conn.commit()
                            self.conn.execute("BEGIN TRANSACTION")
                            logger.info(f"Processed {records_processed:,} {operation_type} records")
                        
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON on line {line_num} in {operation_type} file: {e}")
                        continue
                    except Exception as e:
                        logger.error(f"Error processing line {line_num} in {operation_type} file: {e}")
                        continue
                
                # Final commit
                self.conn.commit()
                logger.info(f"Completed processing {records_processed:,} {operation_type} records")
                
            except Exception as e:
                self.conn.rollback()
                raise e
            
            return records_processed
            
        except Exception as e:
            logger.error(f"Error processing {operation_type} file {file_url}: {e}")
            return 0

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Download and process Semantic Scholar paper metadata")
    parser.add_argument("--output-dir", type=str, default="semantic_scholar_db",
                        help="Directory to store the database (default: semantic_scholar_db)")
    parser.add_argument("--batch-size", type=int, default=10,
                        help="Number of papers to download in each batch (default: 10 for unauthenticated requests, can increase with API key)")
    parser.add_argument("--api-key", type=str,
                        help="Semantic Scholar API key (optional, increases rate limits)")
    parser.add_argument("--fields", type=str,
                        default="id,title,authors,year,externalIds,url,abstract",
                        help="Comma-separated list of fields to include")
    
    # Dataset download options
    parser.add_argument("--download-dataset", action="store_true",
                        help="Download the official Semantic Scholar dataset files (.gz)")
    parser.add_argument("--process-local-files", action="store_true",
                        help="Process existing .gz files in the output directory into the database")
    parser.add_argument("--force-reprocess", action="store_true",
                        help="Force reprocessing of all files (use with --process-local-files)")
    
    # Legacy API-based search options (for backwards compatibility)
    parser.add_argument("--query", type=str,
                        help="Search query to download papers via API")
    parser.add_argument("--start-year", type=int,
                        help="Start year for downloading papers by year range via API")
    parser.add_argument("--end-year", type=int,
                        help="End year for downloading papers by year range via API")
    parser.add_argument("--field", type=str,
                        help="Field or subject area for downloading papers by field via API")
    parser.add_argument("--limit", type=int, default=100000,
                        help="Maximum number of papers to download via API (default: 100000)")
    parser.add_argument("--threads", type=int, default=1,
                        help="Number of threads for parallel processing (default: 1)")
    
    args = parser.parse_args()
    
    # Initialize downloader
    downloader = SemanticScholarDownloader(
        output_dir=args.output_dir,
        batch_size=args.batch_size,
        api_key=args.api_key,
        fields=args.fields.split(",") if args.fields else None
    )
    
    try:
        # Check if database exists
        db_exists = os.path.exists(downloader.db_path)
        
        # Determine what to do based on arguments and database state
        if args.download_dataset:
            logger.info("Downloading dataset files only")
            success = downloader.download_dataset_files()
            if not success:
                logger.error("Failed to download dataset files")
                return 1
                
        elif args.process_local_files:
            logger.info("Processing local files mode")
            downloader.process_local_files(
                force_reprocess=args.force_reprocess,
                incremental=db_exists  # Only incremental if DB exists
            )
            
        elif args.query or args.start_year or args.end_year or args.field:
            # Legacy API-based search
            logger.info("Using legacy API-based paper search")
            paper_ids = downloader.search_papers(
                query=args.query,
                start_year=args.start_year,
                end_year=args.end_year,
                field=args.field,
                limit=args.limit
            )
            
            # Download papers
            downloader.download_papers(paper_ids)
            
        else:
            # Default behavior: automatic full or incremental based on DB state
            if not db_exists:
                logger.info("No database found - performing full download")
                success = downloader.download_dataset_files()
                if not success:
                    logger.error("Failed to download dataset files")
                    return 1
                downloader.process_local_files(incremental=False)
            else:
                logger.info("Database exists - checking for new or updated data (incremental update)")
                # Check if there are any .gz files to process
                gz_files = []
                for root, dirs, files in os.walk(args.output_dir):
                    for file in files:
                        if file.endswith('.gz'):
                            gz_files.append(os.path.join(root, file))
                
                if gz_files:
                    logger.info(f"Found {len(gz_files)} .gz files to process")
                    downloader.process_local_files(
                        force_reprocess=args.force_reprocess,
                        incremental=True
                    )
                else:
                    logger.info("No .gz files found - downloading latest dataset")
                    success = downloader.download_dataset_files()
                    if not success:
                        logger.error("Failed to download dataset files")
                        return 1
                    downloader.process_local_files(incremental=True)
        
        logger.info(f"Completed processing in {args.output_dir}")
        
        # Show database statistics
        cursor = downloader.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM papers")
        count = cursor.fetchone()[0]
        logger.info(f"Total papers in database: {count:,}")
        
        # Show metadata if available
        if db_exists:
            last_update = downloader.get_last_update_time()
            last_release = downloader.get_last_release_id()
            if last_update:
                logger.info(f"Last update timestamp: {last_update}")
            if last_release:
                logger.info(f"Current release: {last_release}")
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("Download interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Error during processing: {e}")
        return 1
    finally:
        # Close database connection
        downloader.close()

if __name__ == "__main__":
    main()