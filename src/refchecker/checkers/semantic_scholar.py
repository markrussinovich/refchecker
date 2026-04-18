#!/usr/bin/env python3
"""
Semantic Scholar API Client for Reference Verification

This module provides functionality to verify non-arXiv references using the Semantic Scholar API.
It can check if a reference's metadata (authors, year, title) matches what's in the Semantic Scholar database.

Usage:
    from semantic_scholar import NonArxivReferenceChecker
    
    # Initialize the checker
    checker = NonArxivReferenceChecker(api_key="your_api_key")  # API key is optional
    
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

import requests
import time
import logging
import re
import html
from typing import Dict, List, Tuple, Optional, Any, Union
from refchecker.utils.doi_utils import extract_doi_from_url, is_valid_doi_format
from refchecker.utils.url_utils import construct_semantic_scholar_url
from refchecker.utils.text_utils import normalize_text, clean_title_basic, find_best_match, is_name_match, are_venues_substantially_different, calculate_title_similarity, compare_authors, clean_title_for_search, strip_latex_commands, compare_titles_with_latex_cleaning
from refchecker.utils.error_utils import format_title_mismatch
from refchecker.utils.arxiv_rate_limiter import ArXivRateLimiter, arxiv_cached_get
from refchecker.config.settings import get_config

# Set up logging
logger = logging.getLogger(__name__)

# Get configuration
config = get_config()
SIMILARITY_THRESHOLD = config["text_processing"]["similarity_threshold"]

class NonArxivReferenceChecker:
    """
    A class to verify non-arXiv references using the Semantic Scholar API
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Semantic Scholar API client
        
        Args:
            api_key: Optional API key for Semantic Scholar (increases rate limits)
        """
        self.base_url = "https://api.semanticscholar.org/graph/v1"
        self.headers = {
            "Accept": "application/json"
        }
        
        if api_key:
            self.headers["x-api-key"] = api_key
        
        # Use a persistent session for connection reuse (TCP/TLS pooling)
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        
        # Rate limiting parameters
        self.request_delay = 1.0  # Initial delay between requests (seconds)
        self.max_retries = 3  # Reduced from 5 to limit timeout accumulation
        self.backoff_factor = 1.5  # Reduced from 2 for faster retries
        
        # Track API failures for Enhanced Hybrid Checker
        self._api_failed = False
        self._failure_reason = None
        
        # ArXiv rate limiter for version checks
        self.arxiv_rate_limiter = ArXivRateLimiter.get_instance()
        self.arxiv_abs_url = "https://arxiv.org/abs"
        self.arxiv_timeout = 30
    
    def search_paper(self, query: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Search for papers matching the query

        Args:
            query: Search query (title, authors, etc.)
            year: Publication year to filter by

        Returns:
            List of paper data dictionaries
        """
        from refchecker.utils.cache_utils import cached_api_response, cache_api_response
        cache_q = f"{query}|{year}"
        hit = cached_api_response(getattr(self, 'cache_dir', None), 'semantic_scholar', 'search_paper', cache_q)
        if hit is not None:
            return hit
        result = self._search_paper_uncached(query, year)
        cache_api_response(getattr(self, 'cache_dir', None), 'semantic_scholar', 'search_paper', cache_q, result)
        return result

    def _search_paper_uncached(self, query: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        """
        endpoint = f"{self.base_url}/paper/search"
        
        # Build query parameters
        params = {
            "query": query,
            "limit": 10,
            "fields": "title,authors,year,externalIds,url,abstract,openAccessPdf,isOpenAccess,venue,publicationVenue,journal",
            "sort": "relevance"  # Ensure consistent ordering
        }
        
        # Reduce retries for ArXiv ID searches to avoid unnecessary API calls when mismatch is likely
        max_retries_for_this_query = 2 if "arXiv:" in query else self.max_retries
        
        # Make the request with retries and backoff
        for attempt in range(max_retries_for_this_query):
            try:
                response = self._session.get(endpoint, params=params, timeout=30)
                
                # Check for rate limiting
                if response.status_code == 429:
                    wait_time = self.request_delay * (self.backoff_factor ** attempt)
                    logger.debug(f"Rate limit exceeded. Increasing delay and retrying...")
                    time.sleep(wait_time)
                    continue
                
                # Check for other errors
                response.raise_for_status()
                
                # Parse the response
                data = response.json()
                return data.get('data', [])
                
            except requests.exceptions.RequestException as e:
                wait_time = self.request_delay * (self.backoff_factor ** attempt)
                logger.warning(f"Request failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
        
        # If we get here, all retries failed
        logger.debug(f"Failed to search for paper after {self.max_retries} attempts")
        self._api_failed = True
        self._failure_reason = "rate_limited_or_timeout"
        return []
    
    def get_paper_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        from refchecker.utils.cache_utils import cached_api_response, cache_api_response
        hit = cached_api_response(getattr(self, 'cache_dir', None), 'semantic_scholar', 'get_by_doi', doi)
        if hit is not None:
            return hit
        result = self._get_paper_by_doi_uncached(doi)
        cache_api_response(getattr(self, 'cache_dir', None), 'semantic_scholar', 'get_by_doi', doi, result)
        return result

    def _get_paper_by_doi_uncached(self, doi: str) -> Optional[Dict[str, Any]]:
        endpoint = f"{self.base_url}/paper/DOI:{doi}"
        
        params = {
            "fields": "title,authors,year,externalIds,url,abstract,openAccessPdf,isOpenAccess,venue,publicationVenue,journal"
        }
        
        # Make the request with retries and backoff
        for attempt in range(self.max_retries):
            try:
                response = self._session.get(endpoint, params=params, timeout=30)
                
                # Check for rate limiting
                if response.status_code == 429:
                    wait_time = self.request_delay * (self.backoff_factor ** attempt)
                    logger.debug(f"Rate limit exceeded. Increasing delay and retrying...")
                    time.sleep(wait_time)
                    continue
                
                # If not found, return None
                if response.status_code == 404:
                    logger.debug(f"Paper with DOI {doi} not found")
                    return None
                
                # Check for other errors
                response.raise_for_status()
                
                # Parse the response
                return response.json()
                
            except requests.exceptions.RequestException as e:
                wait_time = self.request_delay * (self.backoff_factor ** attempt)
                logger.warning(f"Request failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
        
        # If we get here, all retries failed
        logger.error(f"Failed to get paper by DOI after {self.max_retries} attempts")
        self._api_failed = True
        self._failure_reason = "rate_limited_or_timeout"
        return None

    def get_paper_by_arxiv_id(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        from refchecker.utils.cache_utils import cached_api_response, cache_api_response
        clean_id = re.sub(r'v\d+$', '', arxiv_id.strip().rstrip('.'))
        hit = cached_api_response(getattr(self, 'cache_dir', None), 'semantic_scholar', 'get_by_arxiv', clean_id)
        if hit is not None:
            return hit
        result = self._get_paper_by_arxiv_id_uncached(clean_id)
        cache_api_response(getattr(self, 'cache_dir', None), 'semantic_scholar', 'get_by_arxiv', clean_id, result)
        return result

    def _get_paper_by_arxiv_id_uncached(self, clean_id: str) -> Optional[Dict[str, Any]]:
        endpoint = f"{self.base_url}/paper/ARXIV:{clean_id}"
        params = {
            "fields": "title,authors,year,externalIds,url,abstract,openAccessPdf,isOpenAccess,venue,publicationVenue,journal"
        }

        for attempt in range(2):  # Only 2 attempts for fast-path
            try:
                response = self._session.get(endpoint, params=params, timeout=15)
                if response.status_code == 200:
                    logger.debug(f"Direct ArXiv ID lookup succeeded for {clean_id}")
                    return response.json()
                if response.status_code == 404:
                    return None
                if response.status_code == 429:
                    time.sleep(self.request_delay * (self.backoff_factor ** attempt))
                    continue
                return None
            except requests.exceptions.RequestException:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                return None
        return None

    def match_paper_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        from refchecker.utils.cache_utils import cached_api_response, cache_api_response
        hit = cached_api_response(getattr(self, 'cache_dir', None), 'semantic_scholar', 'match_title', title)
        if hit is not None:
            return hit
        result = self._match_paper_by_title_uncached(title)
        cache_api_response(getattr(self, 'cache_dir', None), 'semantic_scholar', 'match_title', title, result)
        return result

    def _match_paper_by_title_uncached(self, title: str) -> Optional[Dict[str, Any]]:
        endpoint = f"{self.base_url}/paper/search/match"
        params = {
            "query": title,
            "fields": "title,authors,year,externalIds,url,abstract,openAccessPdf,isOpenAccess,venue,publicationVenue,journal"
        }

        for attempt in range(2):  # Only 2 attempts for fast-path
            try:
                response = self._session.get(endpoint, params=params, timeout=15)
                if response.status_code == 200:
                    data = response.json().get('data', [])
                    if data:
                        logger.debug(f"Title match succeeded for: {title[:60]}")
                        return data[0]
                    return None
                if response.status_code in (404, 400):
                    return None
                if response.status_code == 429:
                    time.sleep(self.request_delay * (self.backoff_factor ** attempt))
                    continue
                return None
            except requests.exceptions.RequestException:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                return None
        return None

    def get_venue_from_paper_data(self, paper_data: Dict[str, Any]) -> Optional[str]:
        """
        Extract venue from paper data dictionary.
        
        Checks multiple fields since Semantic Scholar returns venue info 
        in different fields depending on publication type.
        
        Args:
            paper_data: Paper data dictionary from Semantic Scholar
            
        Returns:
            Venue string or None if not found
        """
        if not paper_data:
            return None
            
        paper_venue = None
        
        # First try the simple 'venue' field (string)
        if paper_data.get('venue'):
            paper_venue = paper_data.get('venue')
        
        # If no venue, try publicationVenue object
        if not paper_venue and paper_data.get('publicationVenue'):
            pub_venue = paper_data.get('publicationVenue')
            if isinstance(pub_venue, dict):
                paper_venue = pub_venue.get('name', '')
            elif isinstance(pub_venue, str):
                paper_venue = pub_venue
        
        # If still no venue, try journal object
        if not paper_venue and paper_data.get('journal'):
            journal = paper_data.get('journal')
            if isinstance(journal, dict):
                paper_venue = journal.get('name', '')
            elif isinstance(journal, str):
                paper_venue = journal
        
        # Ensure paper_venue is a string
        if paper_venue and not isinstance(paper_venue, str):
            paper_venue = str(paper_venue)
        
        return paper_venue if paper_venue else None
    
    def _extract_arxiv_id_and_version(self, reference: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract ArXiv ID and version from a reference.
        
        Args:
            reference: Reference dictionary containing url, raw_text, etc.
            
        Returns:
            Tuple of (arxiv_id_without_version, version_string_or_None)
            For example: ("2301.12345", "v2") or ("2301.12345", None)
        """
        # Patterns to extract arXiv IDs with versions
        arxiv_id_patterns = [
            r'arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5})(v\d+)?',
            r'arxiv\.org/pdf/([0-9]{4}\.[0-9]{4,5})(v\d+)?',
            r'arxiv\.org/abs/([a-z-]+/[0-9]{7})(v\d+)?',
            r'arxiv\.org/pdf/([a-z-]+/[0-9]{7})(v\d+)?',
            r'arXiv:([0-9]{4}\.[0-9]{4,5})(v\d+)?',
            r'arXiv:([a-z-]+/[0-9]{7})(v\d+)?',
        ]
        
        sources = [
            reference.get('url', ''),
            reference.get('cited_url', ''),
            reference.get('raw_text', ''),
            reference.get('venue', ''),
            reference.get('journal', ''),
        ]
        
        for source in sources:
            if not source:
                continue
            
            for pattern in arxiv_id_patterns:
                match = re.search(pattern, source, re.IGNORECASE)
                if match:
                    arxiv_id = match.group(1)
                    version = match.group(2) if len(match.groups()) > 1 else None
                    return arxiv_id, version
        
        return None, None
    
    def _get_latest_arxiv_version_number(self, arxiv_id: str) -> Optional[int]:
        """
        Get the latest version number for an ArXiv paper.
        
        Args:
            arxiv_id: ArXiv ID without version
            
        Returns:
            Latest version number as integer, or None if couldn't determine
        """
        url = f"{self.arxiv_abs_url}/{arxiv_id}"
        
        text = arxiv_cached_get(url, timeout=self.arxiv_timeout)
        if text is None:
            return None
        
        versions = re.findall(r'\[v(\d+)\]', text)
        if versions:
            return max(int(v) for v in versions)
        return None
    
    def _fetch_arxiv_version_metadata(self, arxiv_id: str, version_num: int) -> Optional[Dict[str, Any]]:
        """
        Fetch metadata for a specific ArXiv version using HTML scraping.
        
        Args:
            arxiv_id: ArXiv ID without version
            version_num: Version number to fetch (1, 2, 3, etc.)
            
        Returns:
            Dictionary with version metadata or None if version doesn't exist
        """
        version_str = f"v{version_num}"
        url = f"{self.arxiv_abs_url}/{arxiv_id}{version_str}"

        logger.debug(f"Checking ArXiv version: {url}")
        html_content = arxiv_cached_get(url, timeout=self.arxiv_timeout)
        if html_content is None:
            return None

        # Parse meta tags for metadata
        title_match = re.search(r'<meta name="citation_title" content="(.*?)"', html_content)
        title = html.unescape(title_match.group(1)).strip() if title_match else ""

        authors = []
        for auth in re.findall(r'<meta name="citation_author" content="(.*?)"', html_content):
            authors.append({'name': html.unescape(auth).strip()})

        date_match = re.search(r'<meta name="citation_date" content="(.*?)"', html_content)
        year = None
        if date_match:
            ym = re.search(r'^(\d{4})', date_match.group(1))
            if ym:
                year = int(ym.group(1))

        return {
            'version': version_str,
            'version_num': version_num,
            'title': title,
            'authors': authors,
            'year': year,
            'url': url,
        }
    
    def _check_arxiv_version_update(self, reference: Dict[str, Any], paper_data: Dict[str, Any], arxiv_id: str, errors: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """
        Check if a reference is citing an older version of an ArXiv paper that has been updated.
        If the reference matches a historical version, converts errors to warnings with version annotation.
        
        Args:
            reference: The original reference dictionary
            paper_data: The verified paper data from Semantic Scholar (latest version)
            arxiv_id: The ArXiv ID from the paper
            errors: The current list of errors found against the latest version
            
        Returns:
            Tuple of (modified_errors_or_warnings, matched_version_num)
            - If reference matches a historical version: returns (warnings_with_version_suffix, matched_version)
            - Otherwise: returns (original_errors, None)
        """
        # Extract cited version from reference
        _, cited_version = self._extract_arxiv_id_and_version(reference)
        
        # Get the latest version number
        latest_version_num = self._get_latest_arxiv_version_number(arxiv_id)
        
        if not latest_version_num or latest_version_num <= 1:
            # Only one version exists or couldn't determine
            return errors, None
        
        # Check if reference explicitly cites a specific older version
        cited_version_num = None
        if cited_version:
            match = re.match(r'v(\d+)', cited_version)
            if match:
                cited_version_num = int(match.group(1))
        
        # If a specific older version is cited in the URL, convert errors to warnings
        if cited_version_num and cited_version_num < latest_version_num:
            version_suffix = f" (v{cited_version_num} vs v{latest_version_num} update)"
            warnings = self._convert_errors_to_version_warnings(errors, version_suffix)
            return warnings, cited_version_num
        
        # If no explicit version or no errors to check, return original
        if not errors:
            return errors, None
        
        # Check if reference metadata matches a historical version
        cited_title = reference.get('title', '').strip()
        
        if not cited_title:
            return errors, None
        
        from refchecker.utils.text_utils import compare_titles_with_latex_cleaning, compare_authors
        
        cited_authors = reference.get('authors', [])

        def _version_match_score(version_data):
            """Compute a combined (title, author) match score for a version."""
            version_title = version_data.get('title', '').strip()
            if not version_title:
                return -1.0
            title_score = compare_titles_with_latex_cleaning(cited_title, version_title)
            if title_score < SIMILARITY_THRESHOLD:
                return -1.0

            # When the reference has authors, factor in author match quality.
            # Author matching produces a boolean; we boost the title score by
            # a small amount when authors match so that among versions with
            # identical titles, the one whose author list matches wins.
            if cited_authors:
                version_authors = [
                    a.get('name', str(a)) if isinstance(a, dict) else str(a)
                    for a in version_data.get('authors', [])
                ]
                if version_authors:
                    authors_match, _ = compare_authors(cited_authors, version_authors)
                    if authors_match:
                        return title_score + 0.01  # boost
            return title_score

        # Find the BEST matching version by comparing title + authors
        best_match_version = None
        best_match_score = 0.0
        
        # Check latest version first
        latest_version_data = self._fetch_arxiv_version_metadata(arxiv_id, latest_version_num)
        if latest_version_data:
            latest_score = _version_match_score(latest_version_data)
            if latest_score > 0:
                best_match_version = latest_version_num
                best_match_score = latest_score
        
        # Check historical versions to find if any is a BETTER match
        for version_num in range(1, latest_version_num):
            version_data = self._fetch_arxiv_version_metadata(arxiv_id, version_num)
            if not version_data:
                continue
            
            version_score = _version_match_score(version_data)
            
            # If this version is a better match than current best
            if version_score > best_match_score:
                best_match_version = version_num
                best_match_score = version_score
        
        # If best match is a historical version (not latest), convert errors to warnings
        if best_match_version is not None and best_match_version < latest_version_num:
            logger.debug(f"Reference best matches ArXiv v{best_match_version} (score: {best_match_score:.3f}, latest is v{latest_version_num})")
            version_suffix = f" (v{best_match_version} vs v{latest_version_num} update)"
            warnings = self._convert_errors_to_version_warnings(errors, version_suffix)
            return warnings, best_match_version
        
        return errors, None
    
    def _convert_errors_to_version_warnings(self, errors: List[Dict[str, Any]], version_suffix: str) -> List[Dict[str, Any]]:
        """
        Convert error dictionaries to warning dictionaries with version suffix.
        
        Args:
            errors: List of error dictionaries
            version_suffix: Version suffix to append (e.g., " (v1 vs v3 update)")
            
        Returns:
            List of warning dictionaries with version annotation
        """
        warnings = []
        for error in errors:
            error_type = error.get('error_type', '')
            
            # Skip info_type entries (suggestions) - keep them as-is
            if 'info_type' in error:
                warnings.append(error)
                continue
            
            # Skip entries that are already warnings
            if 'warning_type' in error:
                # Just append the version suffix
                warning = error.copy()
                warning['warning_type'] = error['warning_type'] + version_suffix
                warnings.append(warning)
                continue
            
            # Convert error to warning with version suffix
            warning = {
                'warning_type': error_type + version_suffix,
                'warning_details': error.get('error_details', ''),
            }
            
            # Preserve correction hints
            for key in ['ref_title_correct', 'ref_authors_correct', 'ref_year_correct', 
                       'ref_venue_correct', 'ref_doi_correct', 'ref_url_correct']:
                if key in error:
                    warning[key] = error[key]
            
            warnings.append(warning)
        
        return warnings
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a non-arXiv reference using Semantic Scholar
        
        Args:
            reference: Reference data dictionary
            
        Returns:
            Tuple of (verified_data, errors, url)
            - verified_data: Paper data from Semantic Scholar or None if not found
            - errors: List of error dictionaries
            - url: URL of the paper if found, None otherwise
        """
        # Reset API failure tracking for this verification attempt
        self._api_failed = False
        self._failure_reason = None
        
        paper_data = None
        errors = []
        
        # Extract reference data
        title = reference.get('title', '')
        authors = reference.get('authors', [])
        year = reference.get('year', 0)
        url = reference.get('url', '')
        raw_text = reference.get('raw_text', '')
        
        # First, check if we have a Semantic Scholar URL (API format)
        if url and 'api.semanticscholar.org/CorpusID:' in url:
            # Extract CorpusID from API URL
            corpus_match = re.search(r'CorpusID:(\d+)', url)
            if corpus_match:
                corpus_id = corpus_match.group(1)
                # Try to get the paper directly by CorpusID
                endpoint = f"{self.base_url}/paper/CorpusId:{corpus_id}"
                params = {"fields": "title,authors,year,externalIds,url,abstract,openAccessPdf,isOpenAccess,venue,publicationVenue,journal"}
                
                for attempt in range(self.max_retries):
                    try:
                        response = self._session.get(endpoint, params=params, timeout=30)
                        
                        if response.status_code == 429:
                            wait_time = self.request_delay * (self.backoff_factor ** attempt)
                            logger.debug(f"Rate limit exceeded. Retrying in {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                        
                        if response.status_code == 200:
                            paper_data = response.json()
                            logger.debug(f"Found paper by Semantic Scholar CorpusID: {corpus_id}")
                            break
                        elif response.status_code == 404:
                            logger.debug(f"Paper not found for CorpusID: {corpus_id}")
                            break
                        else:
                            logger.warning(f"Unexpected status code {response.status_code} for CorpusID: {corpus_id}")
                            break
                            
                    except requests.RequestException as e:
                        logger.warning(f"Request failed for CorpusID {corpus_id}: {e}")
                        if attempt == self.max_retries - 1:
                            break
                        else:
                            time.sleep(self.request_delay * (self.backoff_factor ** attempt))
        
        # Initialize DOI variable for later use
        doi = None
        if 'doi' in reference and reference['doi']:
            doi = reference['doi']
        elif url:
            doi = extract_doi_from_url(url)
        
        # Reject truncated/partial DOIs (e.g., "10.1016/j")
        if doi and not is_valid_doi_format(doi):
            logger.debug(f"Rejecting invalid DOI format: {doi}")
            doi = None
        
        # If we don't have paper data yet, try DOI
        if not paper_data and doi:
            # Try to get the paper by DOI
            paper_data = self.get_paper_by_doi(doi)
            
            if paper_data:
                logger.debug(f"Found paper by DOI: {doi}")
            else:
                logger.debug(f"Could not find paper with DOI: {doi}")
        
        # If we have an ArXiv ID (from URL, venue text, or raw_text), try direct
        # ArXiv ID lookup before title match. ArXiv IDs are authoritative
        # identifiers and more reliable than title matching, which can return
        # corrupt/duplicate Semantic Scholar entries.
        found_title = ''
        arxiv_id_mismatch_detected = False
        arxiv_id = None
        if not paper_data:
            arxiv_id, _ = self._extract_arxiv_id_and_version(reference)
            if arxiv_id:
                logger.debug(f"Trying direct ArXiv ID lookup before title match: {arxiv_id}")
                direct_result = self.get_paper_by_arxiv_id(arxiv_id)
                if direct_result:
                    result_title = direct_result.get('title', '').strip()
                    cited_title = title.strip() if title else ''
                    if cited_title and result_title:
                        title_similarity = compare_titles_with_latex_cleaning(cited_title, result_title)
                        if title_similarity >= SIMILARITY_THRESHOLD:
                            paper_data = direct_result
                            found_title = result_title
                            logger.debug(f"Found paper by direct ArXiv ID lookup: {arxiv_id} (similarity {title_similarity:.2f})")
                        else:
                            arxiv_id_mismatch_detected = True
                            # Do NOT set paper_data here — the ArXiv ID
                            # points to a completely different paper.  Let
                            # the title-based search below find the actual
                            # cited paper (if it exists).
                            logger.debug(f"Direct ArXiv ID lookup found mismatch: cited '{cited_title[:50]}' vs actual '{result_title[:50]}' — skipping, will try title search")
                    else:
                        paper_data = direct_result
                        found_title = result_title

        # If we couldn't get the paper by ArXiv ID or DOI, try finding by title
        if not paper_data and title:
            # Clean up the title for search using centralized utility function
            cleaned_title = clean_title_for_search(title)

            # Try exact title match endpoint first — faster than relevance search.
            # If it finds a match (even partial), use it and skip the search.
            # Only fall through to the slower search if match returns nothing.
            match_result = self.match_paper_by_title(cleaned_title)
            if match_result:
                match_title = match_result.get('title', '')
                match_score = calculate_title_similarity(
                    normalize_text(cleaned_title),
                    normalize_text(match_title),
                )
                if match_score >= SIMILARITY_THRESHOLD:
                    paper_data = match_result
                    found_title = match_title
                    logger.debug(f"Found paper by title match with similarity {match_score:.2f}: {cleaned_title}")
                else:
                    logger.debug(f"Title match returned low-score result ({match_score:.2f}), skipping search")

            # Fall back to relevance search ONLY if match endpoint returned nothing
            if not paper_data and not match_result:
                search_results = self.search_paper(cleaned_title, year)

                if search_results:
                    best_match, best_score = find_best_match(search_results, cleaned_title, year, authors)

                    # Consider it a match if similarity is above threshold
                    if best_match and best_score >= SIMILARITY_THRESHOLD:
                        paper_data = best_match
                        found_title = best_match['title']
                        logger.debug(f"Found paper by title search with similarity {best_score:.2f}: {cleaned_title}")
                    else:
                        logger.debug(f"No good match found for title: {cleaned_title}")
                else:
                    logger.debug(f"No papers found for title: {cleaned_title}")

            # Author-based fallback: when title search fails, try searching by
            # first author + key title words. Handles arXiv papers that changed
            # titles between versions.
            if not paper_data and authors and len(authors) > 0 and title:
                first_author = authors[0]
                if len(first_author) > 3 and first_author.lower() not in ('et al', 'et al.', 'others'):
                    # Build a combined query: first author + a few distinctive title words
                    title_words = [w for w in clean_title_for_search(title).split() if len(w) > 3][:4]
                    author_query = f"{first_author} {' '.join(title_words)}"
                    logger.debug(f"Trying author-based S2 search: '{author_query}'")
                    search_results = self.search_paper(author_query, year)
                    if search_results:
                        best_match, best_score = find_best_match(search_results, cleaned_title, year, authors)
                        # Use a lower threshold since the title may have changed
                        if best_match and best_score >= 0.5:
                            paper_data = best_match
                            found_title = best_match['title']
                            logger.debug(f"Found paper by author-based search with score {best_score:.2f}")
                        else:
                            logger.debug(f"Author-based search best score {best_score:.2f} below threshold")
        
        # If we still couldn't find the paper, try ArXiv search/API fallbacks
        # (direct ArXiv ID lookup was already tried above before title match)
        if not paper_data and arxiv_id:
            if arxiv_id:
                logger.debug(f"Trying ArXiv search fallback for: {arxiv_id}")
                search_results = self.search_paper(f"arXiv:{arxiv_id}")
            
                if search_results:
                    # For ArXiv searches, check if the found paper matches the cited title
                    for result in search_results:
                        external_ids = result.get('externalIds', {})
                        if external_ids and external_ids.get('ArXiv') == arxiv_id:
                            # Found the paper by ArXiv ID, but check if title matches cited title
                            result_title = result.get('title', '').strip()
                            cited_title = title.strip()
                        
                            if cited_title and result_title:
                                title_similarity = compare_titles_with_latex_cleaning(cited_title, result_title)
                                logger.debug(f"Semantic Scholar ArXiv search title similarity: {title_similarity:.3f}")
                                logger.debug(f"Cited title: '{cited_title}'")
                                logger.debug(f"Found title: '{result_title}'")
                            
                                if title_similarity >= SIMILARITY_THRESHOLD:
                                    paper_data = result
                                    found_title = result['title']
                                    logger.debug(f"Found matching paper by ArXiv ID: {arxiv_id}")
                                else:
                                    logger.debug(f"ArXiv ID points to different paper (similarity: {title_similarity:.3f})")
                                    arxiv_id_mismatch_detected = True
                            else:
                                # If no title to compare, accept the paper (fallback)
                                paper_data = result
                                found_title = result['title']
                                logger.debug(f"Found paper by ArXiv ID (no title comparison): {arxiv_id}")
                            break
                
                # If still not found after ArXiv ID search, try ArXiv API directly
                if not paper_data:
                    logger.debug(f"Paper not found in Semantic Scholar by ArXiv ID, trying ArXiv API directly for: {arxiv_id}")
                    arxiv_paper = self._get_paper_from_arxiv_api(arxiv_id)
                    if arxiv_paper:
                        # Verify that the ArXiv paper matches the cited reference title
                        arxiv_title = arxiv_paper.get('title', '').strip()
                        cited_title = title.strip()
                        
                        logger.debug(f"DEBUG: ArXiv paper found, comparing titles...")
                        logger.debug(f"DEBUG: cited_title='{cited_title}', arxiv_title='{arxiv_title}'")
                        
                        if cited_title and arxiv_title:
                            title_similarity = compare_titles_with_latex_cleaning(cited_title, arxiv_title)
                            logger.debug(f"ArXiv API title similarity: {title_similarity:.3f}")
                            logger.debug(f"Cited title: '{cited_title}'")
                            logger.debug(f"ArXiv title: '{arxiv_title}'")
                            
                            # Only accept the ArXiv paper if the titles match sufficiently
                            if title_similarity >= SIMILARITY_THRESHOLD:
                                paper_data = arxiv_paper
                                found_title = arxiv_paper['title']
                                logger.debug(f"Found matching paper in ArXiv API: {arxiv_id}")
                            else:
                                logger.debug(f"ArXiv paper title doesn't match cited title (similarity: {title_similarity:.3f})")
                                arxiv_id_mismatch_detected = True
                                logger.debug(f"DEBUG: Set arxiv_id_mismatch_detected = {arxiv_id_mismatch_detected}")
                        else:
                            # If we don't have a title to compare, don't use the ArXiv paper
                            logger.debug(f"Cannot verify ArXiv paper without title comparison")
                            logger.debug(f"DEBUG: No title comparison possible, cited_title='{cited_title}', arxiv_title='{arxiv_title}'")
                    else:
                        logger.debug(f"Paper not found in ArXiv API: {arxiv_id}")
        
        # Check for ArXiv ID mismatch before doing raw text search
        if not paper_data and url and 'arxiv.org/abs/' in url:
            # Extract ArXiv ID to check if it would cause a mismatch
            arxiv_match = re.search(r'arxiv\.org/abs/([^\s/?#]+)', url)
            if arxiv_match:
                check_arxiv_id = arxiv_match.group(1)
                # Quick check if ArXiv ID would point to wrong paper
                try:
                    arxiv_paper_check = self._get_paper_from_arxiv_api(check_arxiv_id)
                    if arxiv_paper_check:
                        arxiv_title_check = arxiv_paper_check.get('title', '').strip()
                        cited_title_check = title.strip()
                        if cited_title_check and arxiv_title_check:
                            title_similarity_check = compare_titles_with_latex_cleaning(cited_title_check, arxiv_title_check)
                            if title_similarity_check < SIMILARITY_THRESHOLD:
                                logger.debug(f"Detected ArXiv ID mismatch before raw text search - skipping unnecessary searches")
                                arxiv_id_mismatch_detected = True
                except Exception as e:
                    logger.debug(f"Error checking ArXiv ID mismatch: {e}")
        
        # If we still couldn't find the paper, try searching by the raw text
        # BUT skip this if we detected an ArXiv ID mismatch (no point in more searches)
        if not paper_data and raw_text and not arxiv_id_mismatch_detected:
            logger.debug(f"Proceeding with raw text search (arxiv_id_mismatch_detected={arxiv_id_mismatch_detected})")
        elif not paper_data and raw_text and arxiv_id_mismatch_detected:
            logger.debug(f"Skipping raw text search due to ArXiv ID mismatch detected")
        
        if not paper_data and raw_text and not arxiv_id_mismatch_detected:
            # Extract and normalize a reasonable search query from the raw text
            search_query = raw_text.replace('\n', ' ').strip()
            
            # Skip absurdly long raw_text - it's likely malformed LLM output or
            # full paper text rather than a citation string
            if len(search_query) > 500:
                logger.debug(f"Skipping raw text search: text too long ({len(search_query)} chars)")
                search_query = None
            
            if search_query:
                # Truncate to a reasonable length for API queries
                search_query = search_query[:300]
                normalized_raw_query = normalize_text(search_query).lower().strip()
            
            # Search for the paper using normalized query
            search_results = self.search_paper(normalized_raw_query) if search_query else []
            
            if search_results:
                # Take the first result as a best guess
                best_match, best_score = find_best_match(search_results, cleaned_title, year, authors)
                
                # Consider it a match if similarity is above threshold
                if best_match and best_score >= SIMILARITY_THRESHOLD:
                    paper_data = best_match
                    found_title = best_match['title']
                    logger.debug(f"Found paper by raw text search")
                else:
                    logger.debug(f"No good match found for raw text search: {search_query}")
            else:
                logger.debug(f"No papers found for raw text search")
        
        # If we couldn't find the paper, check if API failed or genuinely not found
        if not paper_data:
            logger.debug(f"Could not find matching paper for reference: {title}")
            logger.debug(f"Tried: DOI search, title search, ArXiv ID search, ArXiv API fallback, raw text search")
            
            # If API failed during search, return error indicating retryable failure
            if self._api_failed:
                return None, [{"error_type": "api_failure", "error_details": f"Semantic Scholar API failed: {self._failure_reason}"}], None
            else:
                # Paper genuinely not found in database
                return None, [], None
        
        # Check title using similarity function to handle formatting differences
        title_similarity = compare_titles_with_latex_cleaning(title, found_title) if found_title else 0.0
        if found_title and title_similarity < SIMILARITY_THRESHOLD:
            # Clean the title for display (remove LaTeX commands like {LLM}s -> LLMs)
            clean_cited_title = strip_latex_commands(title)
            errors.append({
                'error_type': 'title',
                'error_details': format_title_mismatch(clean_cited_title, found_title),
                'ref_title_correct': paper_data.get('title', '')
            })
        
        # Verify authors
        if authors and paper_data.get('authors'):
            authors_match, author_error = compare_authors(authors, paper_data.get('authors', []))
            
            if not authors_match:
                # Check if we have an exact ArXiv ID match - if so, be more lenient with author mismatches
                # since they might be due to incomplete data in Semantic Scholar
                arxiv_id_match = False
                if url and 'arxiv.org/abs/' in url:
                    arxiv_match = re.search(r'arxiv\.org/abs/([^\s/?#]+)', url)
                    if arxiv_match:
                        cited_arxiv_id = arxiv_match.group(1)
                        external_ids = paper_data.get('externalIds', {})
                        found_arxiv_id = external_ids.get('ArXiv')
                        arxiv_id_match = (cited_arxiv_id == found_arxiv_id)
                
                # If ArXiv IDs match exactly, treat author mismatch as warning (likely incomplete data)
                if arxiv_id_match:
                    errors.append({
                        'warning_type': 'author',
                        'warning_details': f"{author_error}",
                        'ref_authors_correct': ', '.join([author.get('name', '') for author in paper_data.get('authors', [])])
                    })
                else:
                    # No ArXiv ID match, treat as error
                    errors.append({
                        'error_type': 'author',
                        'error_details': author_error,
                        'ref_authors_correct': ', '.join([author.get('name', '') for author in paper_data.get('authors', [])])
                    })
        
        # Verify year using flexible validation
        paper_year = paper_data.get('year')
        # Check if we have an exact ArXiv ID match for additional context
        arxiv_id_match = False
        if url and 'arxiv.org/abs/' in url:
            arxiv_match = re.search(r'arxiv\.org/abs/([^\s/?#]+)', url)
            if arxiv_match:
                cited_arxiv_id = arxiv_match.group(1)
                external_ids = paper_data.get('externalIds', {})
                found_arxiv_id = external_ids.get('ArXiv')
                arxiv_id_match = (cited_arxiv_id == found_arxiv_id)
        
        from refchecker.utils.error_utils import validate_year
        year_warning = validate_year(
            cited_year=year,
            paper_year=paper_year,
            use_flexible_validation=True,
            context={'arxiv_match': arxiv_id_match}
        )
        if year_warning:
            errors.append(year_warning)
        
        # Verify venue
        cited_venue = reference.get('journal', '') or reference.get('venue', '')
        
        # Extract venue from paper_data - check multiple fields since Semantic Scholar
        # returns venue info in different fields depending on publication type
        paper_venue = None
        
        # First try the simple 'venue' field (string)
        if paper_data.get('venue'):
            paper_venue = paper_data.get('venue')
        
        # If no venue, try publicationVenue object
        if not paper_venue and paper_data.get('publicationVenue'):
            pub_venue = paper_data.get('publicationVenue')
            if isinstance(pub_venue, dict):
                paper_venue = pub_venue.get('name', '')
            elif isinstance(pub_venue, str):
                paper_venue = pub_venue
        
        # If still no venue, try journal object
        if not paper_venue and paper_data.get('journal'):
            journal = paper_data.get('journal')
            if isinstance(journal, dict):
                paper_venue = journal.get('name', '')
            elif isinstance(journal, str):
                paper_venue = journal
        
        # Ensure paper_venue is a string
        if paper_venue and not isinstance(paper_venue, str):
            paper_venue = str(paper_venue)
        
        # Check venue mismatches
        if cited_venue and paper_venue:
            # Use the utility function to check if venues are substantially different
            if are_venues_substantially_different(cited_venue, paper_venue):
                from refchecker.utils.error_utils import create_venue_warning
                errors.append(create_venue_warning(cited_venue, paper_venue))
        elif not cited_venue and paper_venue:
            # Reference has no venue but paper has one — skip generic/preprint
            # server venues (arXiv, CoRR) since they're not meaningful venues.
            pv = paper_venue.lower().strip()
            if (pv and
                pv not in ('arxiv', 'arxiv.org', 'preprint', 'corr', '') and
                not pv.startswith('arxiv') and
                not pv.startswith('corr')):
                errors.append({
                    'error_type': 'venue',
                    'error_details': f"Venue missing: should include '{paper_venue}'",
                    'ref_venue_correct': paper_venue
                })

        # Always check for missing arXiv URLs when paper has arXiv ID
        external_ids = paper_data.get('externalIds', {})
        arxiv_id = external_ids.get('ArXiv') if external_ids else None
        
        if arxiv_id:
            # For arXiv papers, check if reference includes the arXiv URL
            arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
            
            # Check if the reference already includes this ArXiv URL or equivalent DOI
            reference_url = reference.get('url', '')
            
            # Check for direct arXiv URL match
            has_arxiv_url = arxiv_url in reference_url
            
            # Also check for arXiv DOI URL (e.g., https://doi.org/10.48550/arxiv.2505.11595)
            arxiv_doi_url = f"https://doi.org/10.48550/arxiv.{arxiv_id}"
            has_arxiv_doi = arxiv_doi_url.lower() in reference_url.lower()
            
            if not (has_arxiv_url or has_arxiv_doi):
                errors.append({
                    'info_type': 'url',
                    'info_details': f"Reference could include arXiv URL: {arxiv_url}",
                    'ref_url_correct': arxiv_url
                })
            
            # Check for ArXiv version updates - if reference matches an older version,
            # convert errors to warnings with version annotation (like ArXiv citation checker)
            errors, matched_version = self._check_arxiv_version_update(reference, paper_data, arxiv_id, errors)

        # Verify DOI
        paper_doi = None
        external_ids = paper_data.get('externalIds', {})
        if external_ids and 'DOI' in external_ids:
            paper_doi = external_ids['DOI']
            
            # Compare DOIs using the proper comparison function
            from refchecker.utils.doi_utils import compare_dois, validate_doi_resolves
            if doi and paper_doi and not compare_dois(doi, paper_doi):
                from refchecker.utils.error_utils import format_doi_mismatch
                # If cited DOI resolves, it's likely a valid alternate DOI (e.g., arXiv vs conference)
                # Treat as warning instead of error
                if validate_doi_resolves(doi):
                    errors.append({
                        'warning_type': 'doi',
                        'warning_details': format_doi_mismatch(doi, paper_doi),
                        'ref_doi_correct': paper_doi
                    })
                else:
                    errors.append({
                        'error_type': 'doi',
                        'error_details': format_doi_mismatch(doi, paper_doi),
                        'ref_doi_correct': paper_doi
                    })
        
        # Extract URL from paper data - prioritize arXiv URLs when available
        paper_url = None
        
        logger.debug(f"Semantic Scholar - Extracting URL from paper data: {list(paper_data.keys())}")
        
        # Return the Semantic Scholar URL that was actually used for verification
        # First priority: Semantic Scholar URL using paperId (SHA hash, works in web URLs)
        if paper_data.get('paperId'):
            paper_url = construct_semantic_scholar_url(paper_data['paperId'])
            logger.debug(f"Using Semantic Scholar URL for verification: {paper_url}")
        
        # Second priority: DOI URL (if this was verified through DOI)
        elif external_ids.get('DOI'):
            from refchecker.utils.doi_utils import construct_doi_url
            paper_url = construct_doi_url(external_ids['DOI'])
            logger.debug(f"Using DOI URL for verification: {paper_url}")
        
        # Third priority: open access PDF
        elif paper_data.get('openAccessPdf') and paper_data['openAccessPdf'].get('url'):
            paper_url = paper_data['openAccessPdf']['url']
            logger.debug(f"Using open access PDF URL: {paper_url}")
        
        # Fourth priority: general URL field
        elif paper_data.get('url'):
            paper_url = paper_data['url']
            logger.debug(f"Using general paper URL: {paper_url}")
        
        # Last resort: arXiv URL (only if no other verification source was available)
        elif external_ids.get('ArXiv'):
            arxiv_id = external_ids['ArXiv']
            paper_url = f"https://arxiv.org/abs/{arxiv_id}"
            logger.debug(f"Using arXiv URL as fallback: {paper_url}")
        
        if not paper_url:
            logger.debug(f"No URL found in paper data - available fields: {list(paper_data.keys())}")
            logger.debug(f"Paper data sample: {str(paper_data)[:200]}...")
        
        return paper_data, errors, paper_url
    
    def _get_paper_from_arxiv_api(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        """
        Get paper metadata directly from ArXiv API for very recent papers not yet in Semantic Scholar.
        
        Args:
            arxiv_id: ArXiv ID (e.g., "2507.08846")
            
        Returns:
            Paper data dictionary in Semantic Scholar format, or None if not found
        """
        try:
            import xml.etree.ElementTree as ET
            
            arxiv_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
            logger.debug(f"Querying ArXiv API: {arxiv_url}")
            
            response = requests.get(arxiv_url, timeout=30)
            response.raise_for_status()
            
            # Parse XML response
            root = ET.fromstring(response.text)
            
            # Check if any entries were found
            entries = root.findall('{http://www.w3.org/2005/Atom}entry')
            if not entries:
                logger.debug(f"No entries found for ArXiv ID: {arxiv_id}")
                return None
            
            entry = entries[0]  # Take the first entry
            
            # Extract title
            title_elem = entry.find('{http://www.w3.org/2005/Atom}title')
            title = title_elem.text.strip() if title_elem is not None else ""
            
            # Extract authors
            authors = []
            for author_elem in entry.findall('{http://www.w3.org/2005/Atom}author'):
                name_elem = author_elem.find('{http://www.w3.org/2005/Atom}name')
                if name_elem is not None:
                    authors.append({"name": name_elem.text.strip()})
            
            # Extract published date
            published_elem = entry.find('{http://www.w3.org/2005/Atom}published')
            year = None
            if published_elem is not None:
                published_date = published_elem.text
                try:
                    year = int(published_date[:4])
                except (ValueError, IndexError):
                    pass
            
            # Create Semantic Scholar-compatible data structure
            paper_data = {
                'title': title,
                'authors': authors,
                'year': year,
                'externalIds': {'ArXiv': arxiv_id},
                'url': f"https://arxiv.org/abs/{arxiv_id}",
                'venue': 'arXiv',
                'isOpenAccess': True,
                'openAccessPdf': {'url': f"https://arxiv.org/pdf/{arxiv_id}.pdf"}
            }
            
            logger.debug(f"Successfully retrieved ArXiv paper: {title}")
            return paper_data
            
        except Exception as e:
            logger.debug(f"Failed to get paper from ArXiv API: {str(e)}")
            return None

if __name__ == "__main__":
    # Example usage
    checker = NonArxivReferenceChecker()
    
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
