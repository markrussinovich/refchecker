#!/usr/bin/env python3
"""
Local Semantic Scholar Database Client for Reference Verification

This module provides functionality to verify non-arXiv references using a local Semantic Scholar database.
It can check if a reference's metadata (authors, year, title) matches what's in the local database.

Usage:
    from local_semantic_scholar import LocalNonArxivReferenceChecker
    
    # Initialize the checker
    checker = LocalNonArxivReferenceChecker(db_path="semantic_scholar_db/semantic_scholar.db")
    
    # Verify a reference
    reference = {
        'title': 'Title of the paper',
        'authors': ['Author 1', 'Author 2'],
        'year': 2020,
        'url': 'https://example.com/paper',
        'raw_text': 'Full citation text'
    }
    
    verified_data, errors = checker.verify_reference(reference)
"""

import json
import logging
import re
import sqlite3
import time
from typing import Dict, List, Tuple, Optional, Any, Union

# Import utility functions
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from refchecker.utils.doi_utils import extract_doi_from_url, compare_dois, construct_doi_url
from refchecker.utils.error_utils import create_author_error, create_doi_error, create_venue_warning, format_title_mismatch
from refchecker.utils.text_utils import normalize_author_name, normalize_paper_title, is_name_match, compare_authors, calculate_title_similarity, compare_titles_with_latex_cleaning, strip_latex_commands, are_venues_substantially_different
from refchecker.utils.url_utils import extract_arxiv_id_from_url, get_best_available_url, construct_semantic_scholar_url
from refchecker.utils.db_utils import process_semantic_scholar_result, process_semantic_scholar_results
from refchecker.config.settings import get_config
from refchecker.checkers.arxiv_citation import ArXivCitationChecker
from refchecker.database.local_database_updater import repair_local_database_schema

# Set up logging
logger = logging.getLogger(__name__)

# Get configuration
config = get_config()
SIMILARITY_THRESHOLD = config["text_processing"]["similarity_threshold"]
_ARXIV_VERSION_SENSITIVE_TYPES = frozenset({"title", "author", "year"})

def log_query_debug(query: str, params: list, execution_time: float, result_count: int, strategy: str, db_label: str = ''):
    """Log database query details in debug mode"""
    label_prefix = f"[{db_label}] " if db_label else ''
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"{label_prefix}DB Query Strategy: {strategy}")
        logger.debug(f"{label_prefix}DB Query: {query}")
        logger.debug(f"{label_prefix}DB Params: {params}")
        logger.debug(f"{label_prefix}DB Execution Time: {execution_time:.3f}s")
        logger.debug(f"{label_prefix}DB Result Count: {result_count}")
    else:
        # Always log strategy and result count for INFO level
        logger.debug(f"{label_prefix}DB Query [{strategy}]: {result_count} results in {execution_time:.3f}s")

class LocalNonArxivReferenceChecker:
    """
    A class to verify non-arXiv references using a local paper metadata database
    """
    
    def __init__(
        self,
        db_path: str = "semantic_scholar_db/semantic_scholar.db",
        database_label: str = "Semantic Scholar",
        database_key: str = "local_s2",
    ):
        """
        Initialize the local Semantic Scholar database client
        
        Args:
            db_path: Path to the SQLite database
        
        Raises:
            FileNotFoundError: If the database file does not exist
            ValueError: If the database is missing the required 'papers' table
        """
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Local reference database not found: {db_path}")
        # If db_path is a directory, auto-detect the .db file inside it
        if os.path.isdir(db_path):
            db_files = sorted(
                [f for f in os.listdir(db_path) if f.endswith('.db')],
                key=lambda f: os.path.getmtime(os.path.join(db_path, f)),
                reverse=True,
            )
            if not db_files:
                raise FileNotFoundError(
                    f"No .db files found in directory {db_path}. "
                    f"Provide the path to a specific .db file."
                )
            db_path = os.path.join(db_path, db_files[0])
            logger.info(f"Auto-detected database file: {db_path}")
        self.db_path = db_path
        self.database_label = database_label
        self.database_key = database_key
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        # Validate that the required 'papers' table exists
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='papers'"
        )
        if cursor.fetchone() is None:
            self.conn.close()
            raise ValueError(
                f"Database at {db_path} is missing the required 'papers' table. "
                f"Ensure the configured path points to a valid local RefChecker database."
            )
        try:
            repair_report = repair_local_database_schema(self.db_path, conn=self.conn)
            if repair_report['added_columns'] or repair_report['added_indexes']:
                logger.info(
                    "Repaired local database schema for %s: columns=%s indexes=%s",
                    self.db_path,
                    ', '.join(repair_report['added_columns']) or 'none',
                    ', '.join(repair_report['added_indexes']) or 'none',
                )
        except Exception as exc:
            logger.warning("Failed to repair local database schema for %s: %s", self.db_path, exc)
        # Optimise for read-heavy workloads (reference lookups are read-only)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-64000")   # 64 MB page cache
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self._arxiv_citation_checker: Optional[ArXivCitationChecker] = None
        self._log_prefix = f"Local DB [{self.database_label}]"

    def _get_arxiv_citation_checker(self) -> ArXivCitationChecker:
        if self._arxiv_citation_checker is None:
            self._arxiv_citation_checker = ArXivCitationChecker()
        return self._arxiv_citation_checker

    def _has_exact_author_reorder(
        self,
        reference: Dict[str, Any],
        verified_authors: List[Dict[str, Any]],
    ) -> bool:
        cited_authors = [author.strip() for author in reference.get('authors', []) if isinstance(author, str) and author.strip()]
        verified_author_names = []
        for author in verified_authors:
            if isinstance(author, dict):
                author_name = author.get('name', '')
            else:
                author_name = str(author)
            author_name = author_name.strip()
            if author_name:
                verified_author_names.append(author_name)

        return bool(
            cited_authors
            and verified_author_names
            and cited_authors != verified_author_names
            and sorted(cited_authors) == sorted(verified_author_names)
        )

    def _downgrade_inferred_arxiv_version_mismatches(
        self,
        reference: Dict[str, Any],
        inferred_arxiv_id: Optional[str],
        verified_authors: List[Dict[str, Any]],
        errors: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not inferred_arxiv_id or not errors:
            return errors

        has_version_sensitive_issue = any(
            error.get('error_type') in _ARXIV_VERSION_SENSITIVE_TYPES
            or error.get('warning_type') in _ARXIV_VERSION_SENSITIVE_TYPES
            for error in errors
        )
        if not has_version_sensitive_issue:
            return errors

        logger.debug(
            f"{self._log_prefix}: Running inferred arXiv version check for matched paper %s",
            inferred_arxiv_id,
        )

        arxiv_reference = dict(reference)
        arxiv_reference['url'] = f"https://arxiv.org/abs/{inferred_arxiv_id}"

        try:
            _, arxiv_issues, matched_url = self._get_arxiv_citation_checker().verify_reference(arxiv_reference)
        except Exception as exc:
            logger.debug(f"{self._log_prefix}: Inferred arXiv check failed for %s: %s", inferred_arxiv_id, exc)
            return errors
        if not matched_url or f"/abs/{inferred_arxiv_id}" not in matched_url:
            return errors

        exact_author_reorder = self._has_exact_author_reorder(reference, verified_authors)
        version_warnings = {}
        for issue in arxiv_issues:
            warning_type = issue.get('warning_type')
            if not warning_type or ' update)' not in warning_type:
                continue
            base_warning_type = warning_type.split(' (', 1)[0]
            if base_warning_type in _ARXIV_VERSION_SENSITIVE_TYPES:
                version_warnings[base_warning_type] = issue

        clean_authoritative_match = not arxiv_issues
        if not version_warnings and not (clean_authoritative_match and exact_author_reorder):
            return errors

        downgraded_errors = []
        downgraded_any = False
        for error in errors:
            issue_type = error.get('error_type') or error.get('warning_type')
            if issue_type not in _ARXIV_VERSION_SENSITIVE_TYPES:
                downgraded_errors.append(error)
                continue

            replacement = version_warnings.get(issue_type)
            if replacement:
                downgraded_errors.append(replacement)
                downgraded_any = True
            elif clean_authoritative_match and exact_author_reorder and issue_type == 'author':
                downgraded_any = True
            else:
                downgraded_errors.append(error)

        if downgraded_any:
            logger.debug(
                f"{self._log_prefix}: Reconciled inferred arXiv metadata mismatches for %s using %s",
                inferred_arxiv_id,
                matched_url,
            )
            return downgraded_errors

        return errors

    def _get_verified_paper_arxiv_id(self, paper_data: Dict[str, Any]) -> Optional[str]:
        """Return the best arXiv ID we can confidently infer for the matched paper."""
        external_ids = paper_data.get('externalIds', {}) or {}
        paper_arxiv_id = external_ids.get('ArXiv')
        if paper_arxiv_id:
            return paper_arxiv_id

        for url_key in ('source_url', 'url'):
            candidate_url = paper_data.get(url_key, '')
            candidate_arxiv_id = extract_arxiv_id_from_url(candidate_url)
            if candidate_arxiv_id:
                return candidate_arxiv_id

        return None

    def _missing_arxiv_metadata_is_authoritative(self) -> bool:
        """Whether this source can reliably disprove a cited arXiv URL by omission.

        Returns ``False`` for all databases.  Even Semantic Scholar has
        incomplete arXiv coverage (e.g. the Gemini paper 2312.11805 is
        indexed in S2 but without an arXiv mapping), so a missing arXiv ID
        is not reliable evidence that the reference's arXiv URL is wrong.
        """
        return False
    
    # DOI extraction now handled by utility function
    
    # Title normalization now handled by utility function
    
    # Author name normalization now handled by utility function
    
    # Author comparison now handled by utility function
    
    # Name matching now handled by utility function
    
    def get_paper_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        Get paper data by DOI from the local database
        
        Args:
            doi: DOI of the paper
            
        Returns:
            Paper data dictionary or None if not found
        """
        # Reject truncated/partial DOIs (e.g., "10.1016/j")
        if not doi or len(doi.split('/', 1)[-1]) < 2:
            return None

        cursor = self.conn.cursor()
        
        # Query the database for the paper with the given DOI using the column-based schema
        query = '''
        SELECT * FROM papers
        WHERE externalIds_DOI = ?
        '''
        params = (doi,)
        
        start_time = time.time()
        cursor.execute(query, params)
        row = cursor.fetchone()
        execution_time = time.time() - start_time
        
        result_count = 1 if row else 0
        log_query_debug(query, list(params), execution_time, result_count, "DOI lookup", self.database_label)
        
        if not row:
            return None
        
        # Convert row to dictionary and process using utility function
        paper_data = process_semantic_scholar_result(dict(row))
        
        return paper_data
    
    def get_paper_by_arxiv_id(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        """
        Get paper data by arXiv ID from the local database
        
        Args:
            arxiv_id: arXiv ID of the paper
            
        Returns:
            Paper data dictionary or None if not found
        """
        cursor = self.conn.cursor()
        
        # Query the database for the paper with the given arXiv ID using the column-based schema
        query = '''
        SELECT * FROM papers
        WHERE externalIds_ArXiv = ?
        '''
        params = (arxiv_id,)
        
        start_time = time.time()
        cursor.execute(query, params)
        row = cursor.fetchone()
        execution_time = time.time() - start_time
        
        result_count = 1 if row else 0
        log_query_debug(query, list(params), execution_time, result_count, "arXiv ID lookup", self.database_label)
        
        if not row:
            return None
        
        # Convert row to dictionary and process using utility function
        paper_data = process_semantic_scholar_result(dict(row))
        
        return paper_data
    
    def search_papers_by_title(self, title: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Search for papers by title in the local database with optimized performance
        
        Args:
            title: Paper title
            year: Publication year (optional)
            
        Returns:
            List of paper data dictionaries
        """
        cursor = self.conn.cursor()
        
        # Clean up the title for searching
        title_cleaned = title.replace('%', '').strip()
        title_lower = title_cleaned.lower()
        title_normalized = normalize_paper_title(title_cleaned)
        
        results = []
        
        # Strategy 1: Try normalized title match first (fastest and most accurate)
        try:
            cursor.execute("PRAGMA table_info(papers)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'normalized_paper_title' in columns and title_normalized:
                query = "SELECT * FROM papers WHERE normalized_paper_title = ?"
                params = [title_normalized]
                    
                start_time = time.time()
                cursor.execute(query, params)
                results.extend([dict(row) for row in cursor.fetchall()])
                execution_time = time.time() - start_time
                
                log_query_debug(query, params, execution_time, len(results), "normalized title match", self.database_label)
                
                if results:
                    logger.debug(f"Found {len(results)} results using normalized title match")
                    return process_semantic_scholar_results(results)
                
                # Strategy 1b: The checker's normalize_paper_title() strips
                # prefixes like "Taichi:", "D-nerf:", etc. but the DB stores
                # the full normalized title. Try DB-style normalization
                # (lowercase + strip non-alphanumeric, no prefix removal).
                db_style_normalized = re.sub(r'[^a-z0-9]', '', title_lower)
                if db_style_normalized and db_style_normalized != title_normalized:
                    start_time = time.time()
                    cursor.execute(query, [db_style_normalized])
                    results.extend([dict(row) for row in cursor.fetchall()])
                    execution_time = time.time() - start_time
                    
                    log_query_debug(query, [db_style_normalized], execution_time, len(results), "DB-style normalized title match", self.database_label)
                    
                    if results:
                        logger.debug(f"Found {len(results)} results using DB-style normalized title match")
                        return process_semantic_scholar_results(results)

                # Strategy 1c: Existing local DBs may contain normalized titles
                # produced from API HTML/math markup, e.g. OpenAlex stores
                # ``<i>l</i><sub>2</sub>`` as ``ilisub2sub``.  Use a narrow
                # token-substring fallback so Unicode/math titles like ``ℓ2``
                # can still find those rows without a broad table scan.
                significant_tokens = [
                    re.sub(r'[^a-z0-9]', '', token)
                    for token in title_lower.split()
                ]
                significant_tokens = [
                    token for token in significant_tokens
                    if len(token) >= 4 and token not in {'with', 'from', 'into', 'using'}
                ]
                if len(significant_tokens) >= 3:
                    token_clauses = ' AND '.join(
                        'normalized_paper_title LIKE ?'
                        for _ in significant_tokens[:5]
                    )
                    query = f"SELECT * FROM papers WHERE {token_clauses} LIMIT 25"
                    params = [f"%{token}%" for token in significant_tokens[:5]]
                    start_time = time.time()
                    cursor.execute(query, params)
                    results.extend([dict(row) for row in cursor.fetchall()])
                    execution_time = time.time() - start_time

                    log_query_debug(query, params, execution_time, len(results), "markup-tolerant token title match", self.database_label)

                    if results:
                        logger.debug(f"Found {len(results)} results using markup-tolerant token title match")
                        return process_semantic_scholar_results(results)
        except Exception as e:
            logger.warning(f"Error in normalized title search: {e}")
        
        return process_semantic_scholar_results(results)
    
    # Result processing now handled by utility function
    
    def find_best_match(self, title: str, authors: List[str], year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Find the best matching paper in the local database
        
        Args:
            title: Paper title
            authors: List of author names
            year: Publication year (optional)
            
        Returns:
            Best matching paper data dictionary or None if not found
        """
        logger.debug(f"{self._log_prefix}: Finding best match for title: '{title}', authors: {authors}, year: {year}")
        
        # Search by title
        title_results = self.search_papers_by_title(title, year)
        
        logger.debug(f"{self._log_prefix}: Title search returned {len(title_results)} results")
        
        if title_results:
            # Find the best match by title similarity with stable sorting
            scored_results = []
            
            for result in title_results:
                result_title = result.get('title', '')
                
                # Calculate similarity score using utility function
                score = calculate_title_similarity(title, result_title)
                
                # Check author match
                if authors and result.get('authors'):
                    # Compare first author
                    first_author = normalize_author_name(authors[0])
                    result_first_author = normalize_author_name(result['authors'][0].get('name', ''))
                    
                    if is_name_match(first_author, result_first_author):
                        score += 0.2
                
                # Check year match
                if year and result.get('year') == year:
                    score += 0.1
                
                logger.debug(f"{self._log_prefix}: Candidate match score {score:.2f} for '{result_title}'")
                
                scored_results.append((score, result))
            
            # Sort by score (descending), then by title for stable ordering when scores are equal
            scored_results.sort(key=lambda x: (-x[0], x[1].get('title', '')))
            
            if scored_results:
                best_score, best_match = scored_results[0]
            
            # If we found a good match, return it
            if best_score >= SIMILARITY_THRESHOLD:
                logger.debug(f"{self._log_prefix}: Found good title match with score {best_score:.2f}")
                return best_match
            else:
                logger.debug(f"{self._log_prefix}: Best title match score {best_score:.2f} below threshold ({SIMILARITY_THRESHOLD})")
        
        logger.debug(f"{self._log_prefix}: No good match found")
        return None
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a non-arXiv reference using the local database
        
        Args:
            reference: Reference data dictionary
            
        Returns:
            Tuple of (verified_data, errors, url)
            - verified_data: Paper data from the database or None if not found
            - errors: List of error dictionaries
            - url: URL of the paper if found, None otherwise
        """
        errors = []
        
        # Extract reference data
        title = reference.get('title', '')
        authors = reference.get('authors', [])
        year = reference.get('year', 0)
        url = reference.get('url', '')
        raw_text = reference.get('raw_text', '')
        
        logger.debug(f"{self._log_prefix}: Verifying reference - Title: '{title}', Authors: {authors}, Year: {year}")
        
        # Extract identifiers from the reference
        doi = None
        arxiv_id = None
        
        if 'doi' in reference and reference['doi']:
            doi = reference['doi']
        elif url:
            # Check if it's an arXiv URL first
            arxiv_id = extract_arxiv_id_from_url(url)
            if not arxiv_id:
                # If not arXiv, try extracting DOI
                doi = extract_doi_from_url(url)
        
        # Reject truncated/partial DOIs (e.g., "10.1016/j")
        from refchecker.utils.doi_utils import is_valid_doi_format
        if doi and not is_valid_doi_format(doi):
            logger.debug(f"{self._log_prefix}: Rejecting invalid DOI format: {doi}")
            doi = None
        
        paper_data = None
        arxiv_tried = False
        
        # If the reference has an arXiv URL, try arXiv ID first and validate
        # the title matches.  If the title doesn't match the arXiv result,
        # the URL is wrong — fall back to title/DOI lookup so we find the
        # real paper and can flag the incorrect arXiv URL.
        if arxiv_id:
            arxiv_tried = True
            logger.debug(f"{self._log_prefix}: Searching by arXiv ID first: {arxiv_id}")
            arxiv_paper = self.get_paper_by_arxiv_id(arxiv_id)
            
            if arxiv_paper:
                arxiv_title = arxiv_paper.get('title', '')
                if title and arxiv_title:
                    title_sim = compare_titles_with_latex_cleaning(title, arxiv_title)
                    if title_sim >= SIMILARITY_THRESHOLD:
                        logger.debug(f"ArXiv ID lookup matched title (similarity={title_sim:.2f}), using arXiv result")
                        paper_data = arxiv_paper
                    else:
                        logger.debug(f"ArXiv ID lookup title mismatch (similarity={title_sim:.2f}): "
                                     f"cited '{title}' vs arXiv '{arxiv_title}' — falling back to title/DOI lookup")
                else:
                    # No title to compare — accept the arXiv result
                    logger.debug(f"Found paper by arXiv ID (no title to cross-check)")
                    paper_data = arxiv_paper
            else:
                logger.debug(f"Could not find paper with arXiv ID: {arxiv_id}")
        
        # Try title/author search (primary fallback, or first if no arXiv URL)
        if not paper_data and (title or authors):
            logger.debug(f"{self._log_prefix}: Searching by title/authors - Title: '{title}', Authors: {authors}, Year: {year}")
            paper_data = self.find_best_match(title, authors, year)
            
            if paper_data:
                logger.debug(f"Found paper by title/author search")
            else:
                logger.debug(f"Could not find matching paper by title/authors")
        
        # Try DOI if title search didn't find it
        if not paper_data and doi:
            logger.debug(f"{self._log_prefix}: Searching by DOI: {doi}")
            doi_paper = self.get_paper_by_doi(doi)
            
            if doi_paper:
                # ArXiv-style DOIs (10.48550/arxiv.XXXX) are redirector DOIs
                # that can match an unrelated paper in the DB.  Validate the
                # title before accepting the result — same guard we already
                # apply to ArXiv-ID lookups above.  Regular DOIs are
                # authoritative, so we keep the result even on title mismatch
                # (the downstream code will flag it as a title error).
                is_arxiv_doi = doi.lower().startswith('10.48550/arxiv')
                doi_title = doi_paper.get('title', '')
                if is_arxiv_doi and title and doi_title:
                    title_sim = compare_titles_with_latex_cleaning(title, doi_title)
                    if title_sim >= SIMILARITY_THRESHOLD:
                        logger.debug(f"ArXiv DOI lookup matched title (similarity={title_sim:.2f}), using DOI result")
                        paper_data = doi_paper
                    else:
                        logger.debug(f"ArXiv DOI lookup title mismatch (similarity={title_sim:.2f}): "
                                     f"cited '{title}' vs DOI '{doi_title}' — ignoring DOI result")
                else:
                    paper_data = doi_paper
                    logger.debug(f"Found paper by DOI: {doi}")
            else:
                logger.debug(f"Could not find paper with DOI: {doi}")
        
        # Try arXiv ID as last resort (only if we haven't tried it above)
        if not paper_data and arxiv_id and not arxiv_tried:
            logger.debug(f"{self._log_prefix}: Searching by arXiv ID: {arxiv_id}")
            paper_data = self.get_paper_by_arxiv_id(arxiv_id)
            
            if paper_data:
                logger.debug(f"Found paper by arXiv ID: {arxiv_id}")
            else:
                logger.debug(f"Could not find paper with arXiv ID: {arxiv_id}")
        
        # If we couldn't find the paper, return no errors (can't verify)
        if not paper_data:
            logger.debug(f"{self._log_prefix}: No matching paper found - cannot verify reference")
            return None, [], None
        
        logger.debug(f"{self._log_prefix}: Found matching paper - Title: '{paper_data.get('title', '')}', Year: {paper_data.get('year', '')}")
        
        # Check title mismatch using similarity function
        found_title = paper_data.get('title', '')
        if title and found_title:
            title_similarity = compare_titles_with_latex_cleaning(title, found_title)
            if title_similarity < SIMILARITY_THRESHOLD:
                clean_cited_title = strip_latex_commands(title)
                errors.append({
                    'error_type': 'title',
                    'error_details': format_title_mismatch(clean_cited_title, found_title),
                    'ref_title_correct': found_title
                })
        
        # Verify authors
        if authors and paper_data.get('authors'):
            authors_match, author_error = compare_authors(authors, paper_data.get('authors', []))
            
            if not authors_match:
                logger.debug(f"{self._log_prefix}: Author mismatch - {author_error}")
                errors.append(create_author_error(author_error, paper_data.get('authors', [])))
        
        # Verify year (with tolerance)
        paper_year = paper_data.get('year')
        # Get year tolerance from config (default to 1 if not available)
        year_tolerance = 1  # Default tolerance
        try:
            from refchecker.config.settings import get_config
            config = get_config()
            year_tolerance = config.get('text_processing', {}).get('year_tolerance', 1)
        except (ImportError, Exception):
            pass  # Use default if config not available
        
        from refchecker.utils.error_utils import validate_year
        year_warning = validate_year(
            cited_year=year,
            paper_year=paper_year,
            year_tolerance=year_tolerance
        )
        if year_warning:
            logger.debug(f"{self._log_prefix}: Year issue - {year_warning.get('warning_details', '')}")
            errors.append(year_warning)
        
        # Verify DOI
        paper_doi = None
        external_ids = paper_data.get('externalIds', {})
        if external_ids and 'DOI' in external_ids:
            paper_doi = external_ids['DOI']
            
            # Compare DOIs using utility function
            if doi and paper_doi and not compare_dois(doi, paper_doi):
                logger.debug(f"{self._log_prefix}: DOI mismatch - cited: {doi}, actual: {paper_doi}")
                doi_error = create_doi_error(doi, paper_doi)
                if doi_error:  # Only add if there's actually a mismatch after cleaning
                    errors.append(doi_error)
        
        # Verify venue
        cited_venue = reference.get('journal', '') or reference.get('venue', '')
        paper_venue = paper_data.get('venue', '')
        
        if cited_venue and paper_venue:
            if are_venues_substantially_different(cited_venue, paper_venue):
                errors.append(create_venue_warning(cited_venue, paper_venue))
        elif not cited_venue and paper_venue:
            # Reference has no venue but paper has one
            # Skip generic/empty venues like 'arxiv'
            paper_venue_lower = paper_venue.lower().strip()
            if (paper_venue_lower and 
                paper_venue_lower not in ['arxiv', 'arxiv.org', 'preprint', '', 'corr'] and
                not paper_venue_lower.startswith('arxiv') and
                not paper_venue_lower.startswith('corr')):
                errors.append({
                    'error_type': 'venue',
                    'error_details': f"Venue missing: should include '{paper_venue}'",
                    'ref_venue_correct': paper_venue
                })
        
        # Check for incorrect arXiv URL: if the reference has an arXiv URL,
        # verify it matches the paper we found (which was resolved by title).
        external_ids = paper_data.get('externalIds', {})
        paper_arxiv_id = self._get_verified_paper_arxiv_id(paper_data)
        correct_author_names = ', '.join(
            author.get('name', str(author)) if isinstance(author, dict) else str(author)
            for author in paper_data.get('authors', [])
        )
        if arxiv_id:
            # Reference has an arXiv URL — cross-check against the found paper
            if paper_arxiv_id and arxiv_id.lower() != paper_arxiv_id.lower():
                correct_arxiv_url = f"https://arxiv.org/abs/{paper_arxiv_id}"
                logger.debug(f"{self._log_prefix}: ArXiv ID mismatch - cited: {arxiv_id}, actual: {paper_arxiv_id}")
                errors.append({
                    'error_type': 'arxiv_id',
                    'error_details': f"Incorrect ArXiv ID: cited {arxiv_id} should be {paper_arxiv_id}",
                    'ref_url_correct': correct_arxiv_url,
                    'ref_title_correct': paper_data.get('title', ''),
                    'ref_authors_correct': correct_author_names,
                })
            elif not paper_arxiv_id and self._missing_arxiv_metadata_is_authoritative():
                # S2 records are authoritative enough that a missing ArXiv ID
                # is strong evidence the cited ArXiv URL is spurious.
                logger.debug(f"{self._log_prefix}: Reference cites arXiv ID {arxiv_id} but matched paper has no ArXiv ID")
                errors.append({
                    'error_type': 'arxiv_id',
                    'error_details': f"Incorrect ArXiv ID: paper '{paper_data.get('title', '')}' does not have ArXiv ID {arxiv_id}",
                    'ref_title_correct': paper_data.get('title', ''),
                    'ref_authors_correct': correct_author_names,
                })
            elif not paper_arxiv_id:
                logger.debug(
                    f"{self._log_prefix}: Matched %s record lacks authoritative arXiv metadata; skipping missing-ID error",
                    self.database_label,
                )
        elif paper_arxiv_id:
            # No arXiv URL in reference but paper has one — suggest it
            arxiv_url = f"https://arxiv.org/abs/{paper_arxiv_id}"
            reference_url = reference.get('url', '')
            has_arxiv_url = arxiv_url in reference_url if reference_url else False
            arxiv_doi_url = f"https://doi.org/10.48550/arxiv.{paper_arxiv_id}"
            has_arxiv_doi = arxiv_doi_url.lower() in reference_url.lower() if reference_url else False
            if not (has_arxiv_url or has_arxiv_doi):
                errors.append({
                    'info_type': 'url',
                    'info_details': f"Reference could include arXiv URL: {arxiv_url}",
                    'ref_url_correct': arxiv_url
                })

            errors = self._downgrade_inferred_arxiv_version_mismatches(
                reference,
                paper_arxiv_id,
                paper_data.get('authors', []),
                errors,
            )
        
        if errors:
            logger.debug(f"{self._log_prefix}: Found {len(errors)} errors in reference verification")
        else:
            logger.debug(f"{self._log_prefix}: Reference verification passed - no errors found")
        
        # Return the best available source URL for the matched local record.
        external_ids = paper_data.get('externalIds', {})
        
        # Prefer the source URL stored in non-S2 local databases when available.
        if paper_data.get('source_url'):
            paper_url = paper_data['source_url']
            logger.debug(f"Using stored source URL for verification: {paper_url}")
        # First try to get the Semantic Scholar URL using paperId
        elif paper_data.get('paperId'):
            paper_url = construct_semantic_scholar_url(paper_data['paperId'])
            logger.debug(f"Using Semantic Scholar URL for verification: {paper_url}")
        else:
            # Fallback to best available URL if Semantic Scholar URL not available
            open_access_pdf = paper_data.get('openAccessPdf')
            paper_url = get_best_available_url(external_ids, open_access_pdf, paper_data.get('paperId'))
            if paper_url:
                logger.debug(f"Using fallback URL: {paper_url}")
        
        if isinstance(paper_data, dict):
            paper_data.setdefault('_matched_database', self.database_label)
            paper_data.setdefault('_matched_checker', self.database_key)
        return paper_data, errors, paper_url
    
    def close(self):
        """Close the database connection"""
        self.conn.close()

if __name__ == "__main__":
    # Example usage
    import sys
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Check if database path is provided
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = "semantic_scholar_db/semantic_scholar.db"
    
    # Initialize the checker
    checker = LocalNonArxivReferenceChecker(db_path=db_path)
    
    # Example reference
    reference = {
        'title': 'Attention is All You Need',
        'authors': ['Ashish Vaswani', 'Noam Shazeer'],
        'year': 2017,
        'url': 'https://example.com/paper',
        'raw_text': 'Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., ... & Polosukhin, I. (2017). Attention is all you need. Advances in neural information processing systems, 30.'
    }
    
    # Verify the reference
    verified_data, errors = checker.verify_reference(reference)
    
    if verified_data:
        print(f"Found paper: {verified_data.get('title')}")
        
        if errors:
            print("Errors found:")
            for error in errors:
                print(f"  - {error['error_type']}: {error['error_details']}")
        else:
            print("No errors found")
    else:
        print("Could not find matching paper")
    
    # Close the database connection
    checker.close()
