#!/usr/bin/env python3
"""
Enhanced Hybrid Reference Checker with Multiple API Sources

This module provides an improved hybrid reference checker that intelligently combines
multiple API sources for optimal reliability and performance. It replaces Google Scholar
with more reliable alternatives while maintaining backward compatibility.

New API Integration Priority:
1. Local Semantic Scholar Database (fastest, offline)
2. Semantic Scholar API (reliable, good coverage)  
3. OpenAlex API (excellent reliability, replaces Google Scholar)
4. CrossRef API (best for DOI-based verification)
5. Google Scholar (final fallback, kept for legacy support)

Usage:
    from enhanced_hybrid_checker import EnhancedHybridReferenceChecker
    
    checker = EnhancedHybridReferenceChecker(
        semantic_scholar_api_key="your_key",
        db_path="path/to/db.sqlite",
        contact_email="your@email.com"
    )
    
    verified_data, errors, url = checker.verify_reference(reference)
"""

import logging
import random
import requests
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib import import_module
from typing import Dict, List, Tuple, Optional, Any

from refchecker.utils.database_config import DATABASE_LABELS

logger = logging.getLogger(__name__)

class EnhancedHybridReferenceChecker:
    """
    Enhanced hybrid reference checker with multiple API sources for improved reliability
    """

    def _initialize_checker(self, module_name: str, class_name: str, log_name: str,
                            *args: Any, error_level: str = 'warning', **kwargs: Any) -> Any:
        """Initialize an optional checker and keep logging behavior consistent."""
        try:
            module = import_module(f'.{module_name}', package=__package__)
            checker_class = getattr(module, class_name)
            checker = checker_class(*args, **kwargs)
            logger.debug(f"Enhanced Hybrid: {log_name} initialized")
            return checker
        except Exception as exc:
            log_message = f"Enhanced Hybrid: Failed to initialize {log_name}: {exc}"
            if error_level == 'error':
                logger.error(log_message)
            else:
                logger.warning(log_message)
            return None
    
    def __init__(self, semantic_scholar_api_key: Optional[str] = None,
                 db_path: Optional[str] = None,
                 db_paths: Optional[Dict[str, str]] = None,
                 contact_email: Optional[str] = None,
                 enable_openalex: bool = True,
                 enable_crossref: bool = True,
                 enable_arxiv_citation: bool = True,
                 debug_mode: bool = False,
                 cache_dir: Optional[str] = None):
        """
        Initialize the enhanced hybrid reference checker
        
        Args:
            semantic_scholar_api_key: Optional API key for Semantic Scholar
            db_path: Optional path to local Semantic Scholar database
            contact_email: Email for polite pool access to APIs
            enable_openalex: Whether to use OpenAlex API
            enable_crossref: Whether to use CrossRef API
            enable_arxiv_citation: Whether to use ArXiv Citation checker as authoritative source
            debug_mode: Whether to enable debug logging
        """
        self.contact_email = contact_email
        self.debug_mode = debug_mode
        
        # Initialize ArXiv Citation checker (authoritative source for ArXiv papers)
        self.arxiv_citation = None
        if enable_arxiv_citation:
            self.arxiv_citation = self._initialize_checker(
                'arxiv_citation', 'ArXivCitationChecker', 'ArXiv Citation checker'
            )
        
        # Initialize local database checkers (S2 first, then optional additional DBs)
        resolved_db_paths = dict(db_paths or {})
        if db_path and 's2' not in resolved_db_paths:
            resolved_db_paths['s2'] = db_path
        self.db_paths = resolved_db_paths

        self.local_db = None  # Backward-compat alias for S2 local DB
        self.local_db_checkers: List[Tuple[str, str, Any]] = []
        for db_name in ('s2', 'openalex', 'crossref', 'dblp'):
            db_file = resolved_db_paths.get(db_name)
            if not db_file:
                continue
            checker_key = f'local_{db_name}'
            checker_label = DATABASE_LABELS.get(db_name, db_name.upper())
            checker = self._initialize_checker(
                'local_semantic_scholar',
                'LocalNonArxivReferenceChecker',
                f'local {checker_label} database',
                db_path=db_file,
                database_label=checker_label,
                database_key=checker_key,
                error_level='error',
            )
            if checker is None:
                raise RuntimeError(
                    f"Failed to open local {checker_label} database at {db_file}. "
                    f"Check that the file exists and contains a valid 'papers' table."
                )
            self.local_db_checkers.append((checker_key, checker_label, checker))
            if db_name == 's2':
                self.local_db = checker
            logger.debug(f"Enhanced Hybrid: Local {checker_label} database enabled at {db_file}")
        
        # Initialize Semantic Scholar API
        self.semantic_scholar = self._initialize_checker(
            'semantic_scholar', 'NonArxivReferenceChecker', 'Semantic Scholar API',
            api_key=semantic_scholar_api_key, error_level='error'
        )
        
        # Initialize OpenAlex API
        self.openalex = None
        if enable_openalex:
            self.openalex = self._initialize_checker(
                'openalex', 'OpenAlexReferenceChecker', 'OpenAlex API', email=contact_email
            )
        
        # Initialize CrossRef API
        self.crossref = None
        if enable_crossref:
            self.crossref = self._initialize_checker(
                'crossref', 'CrossRefReferenceChecker', 'CrossRef API', email=contact_email
            )
        
        # Initialize OpenReview checker
        self.openreview = self._initialize_checker(
            'openreview_checker', 'OpenReviewReferenceChecker', 'OpenReview checker'
        )
        
        # Initialize DBLP checker (curated CS bibliography, strong for conferences)
        self.dblp = self._initialize_checker(
            'dblp', 'DBLPReferenceChecker', 'DBLP checker', email=contact_email
        )
        
        # Google Scholar removed - using more reliable APIs only

        # Propagate cache_dir to all sub-checkers for API response caching
        self.cache_dir = cache_dir
        all_local_checkers = [checker for _, _, checker in self.local_db_checkers]
        for checker in (self.arxiv_citation, *all_local_checkers, self.semantic_scholar,
                        self.openalex, self.crossref, self.openreview, self.dblp):
            if checker is not None:
                checker.cache_dir = cache_dir

        # Track API performance for adaptive selection
        self.api_stats = {
            'arxiv_citation': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'semantic_scholar': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'openalex': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'crossref': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'openreview': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            'dblp': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
        }
        for checker_key, _, _ in self.local_db_checkers:
            self.api_stats.setdefault(
                checker_key,
                {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
            )
        
        # Track failed API calls for retry logic - OPTIMIZED CONFIGURATION
        self.retry_base_delay = 1  # Base delay for retrying throttled APIs (seconds)
        self.retry_backoff_factor = 1.5  # Exponential backoff multiplier
        self.max_retry_delay = 20  # Maximum delay cap in seconds
        
        # Per-API concurrency semaphores for bulk mode.
        # Each API independently limits its own concurrent calls, so a 429
        # backoff on one API doesn't block calls to other APIs.
        # local_db has no limit (instant), ArXiv is rate-limited to 1 (3s gap),
        # others allow moderate parallelism.
        self._api_semaphores: Dict[str, threading.Semaphore] = {
            'arxiv_citation': threading.Semaphore(2),   # ArXiv has 3s rate gap
            'semantic_scholar': threading.Semaphore(3),  # moderate parallelism
            'crossref': threading.Semaphore(3),
            'openalex': threading.Semaphore(3),
            'dblp': threading.Semaphore(2),
            'openreview': threading.Semaphore(2),
        }
        for checker_key, _, _ in self.local_db_checkers:
            self._api_semaphores.setdefault(checker_key, threading.Semaphore(100))

        # Cumulative timing accumulators (wall-clock seconds per API, thread-safe)
        self._api_total_time: Dict[str, float] = {k: 0.0 for k in self.api_stats}
        self._api_sem_wait_time: Dict[str, float] = {k: 0.0 for k in self.api_stats}
        self._api_retry_sleep_time: float = 0.0
        self._api_time_lock = threading.Lock()
    
    def _update_api_stats(self, api_name: str, success: bool, duration: float):
        """Update API performance statistics"""
        if api_name in self.api_stats:
            stats = self.api_stats[api_name]
            if success:
                stats['success'] += 1
            else:
                stats['failure'] += 1
            
            # Update average time (simple moving average)
            total_calls = stats['success'] + stats['failure']
            stats['avg_time'] = ((stats['avg_time'] * (total_calls - 1)) + duration) / total_calls

    @staticmethod
    def _append_attempted_api(attempted_apis: List[str], api_name: str) -> None:
        """Track unique checker attempts in first-seen order."""
        if api_name and api_name not in attempted_apis:
            attempted_apis.append(api_name)

    def _format_api_name(self, api_name: str) -> str:
        """Convert internal checker names into user-facing labels."""
        if api_name.startswith('local_'):
            local_key = api_name.replace('local_', '')
            label = DATABASE_LABELS.get(local_key)
            if label:
                return f'local {label} DB'
        return {
            'arxiv_citation': 'ArXiv',
            'semantic_scholar': 'Semantic Scholar',
            'openalex': 'OpenAlex',
            'crossref': 'CrossRef',
            'dblp': 'DBLP',
            'openreview': 'OpenReview',
        }.get(api_name, api_name.replace('_', ' '))

    def _annotate_match_source(
        self,
        verified_data: Optional[Dict[str, Any]],
        api_name: str,
        api_instance: Any,
    ) -> Optional[Dict[str, Any]]:
        """Attach the matched checker/database to the verified payload."""
        if not isinstance(verified_data, dict):
            return verified_data
        local_label = getattr(api_instance, 'database_label', None)
        matched_label = local_label or self._format_api_name(api_name)
        verified_data.setdefault('_matched_checker', api_name)
        verified_data.setdefault('_matched_database', matched_label)
        return verified_data

    def _iter_local_db_checkers(self) -> List[Tuple[str, str, Any]]:
        """Return configured local DB checkers, honoring legacy test setup."""
        if self.local_db_checkers:
            return self.local_db_checkers
        if self.local_db is not None:
            return [('local_s2', 'S2', self.local_db)]
        return []

    def _format_failure_detail(self, api_name: str, failure_type: str,
                               detail: Optional[str] = None) -> str:
        """Create a short, specific checker failure description."""
        api_label = self._format_api_name(api_name)
        cleaned_detail = ' '.join(str(detail).split()) if detail else ''
        if cleaned_detail:
            if cleaned_detail.lower().startswith(api_label.lower()):
                return cleaned_detail
            return f'{api_label}: {cleaned_detail}'

        fallback_details = {
            'timeout': f'{api_label}: request timed out',
            'throttled': f'{api_label}: rate limited or temporarily unavailable',
            'server_error': f'{api_label}: server error',
            'other': f'{api_label}: unexpected checker error',
        }
        return fallback_details.get(failure_type, f'{api_label}: verification failed')

    def _build_unverified_error_details(self, attempted_apis: List[str],
                                        failed_apis: List[Dict[str, Any]]) -> str:
        """Summarize which checkers returned no match versus which failed."""
        failed_api_names = {failed_api['name'] for failed_api in failed_apis}
        negative_attempts = [
            self._format_api_name(api_name)
            for api_name in attempted_apis
            if api_name not in failed_api_names
        ]
        failure_details = [
            failed_api.get('failure_detail') or self._format_failure_detail(
                failed_api['name'],
                failed_api.get('failure_type', 'other'),
            )
            for failed_api in failed_apis
        ]

        if negative_attempts and failure_details:
            return (
                f"Paper not found by any checker; no match in {', '.join(negative_attempts)}; "
                f"checker failures: {'; '.join(failure_details)}"
            )
        if negative_attempts:
            return f"Paper not found by any checker; no match in {', '.join(negative_attempts)}"
        if failure_details:
            return f"All available checkers failed: {'; '.join(failure_details)}"
        return 'Paper not found by any checker'
    
    def _try_api(self, api_name: str, api_instance: Any, reference: Dict[str, Any], is_retry: bool = False) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str], bool, str, str]:
        """
        Try to verify reference with a specific API and track performance.
        
        Uses per-API semaphores so different APIs don't block each other.
        A 429 backoff on Semantic Scholar won't prevent ArXiv or DB lookups.
        
        Returns:
            Tuple of (verified_data, errors, url, success, failure_type, failure_detail)
            failure_type can be: 'none', 'not_found', 'throttled', 'timeout', 'other'
        """
        if not api_instance:
            return None, [], None, False, 'none', ''
        
        # Acquire per-API semaphore (limits concurrent calls to this specific API)
        sem = self._api_semaphores.get(api_name)
        sem_wait_start = time.time()
        if sem is not None:
            sem.acquire()
        sem_wait = time.time() - sem_wait_start
        
        start_time = time.time()
        failure_type = 'none'
        
        try:
            verified_data, errors, url = api_instance.verify_reference(reference)
            duration = time.time() - start_time
            
            # Check if we got API failure errors indicating retryable failure
            api_failure_errors = [err for err in errors if err.get('error_type') == 'api_failure']
            if api_failure_errors:
                # This is a retryable API failure, not a verification result
                self._update_api_stats(api_name, False, duration)
                api_failure_detail = api_failure_errors[0].get('error_details', 'temporary API failure')
                logger.debug(f"Enhanced Hybrid: {api_name} API failed in {duration:.2f}s: {api_failure_detail}")
                return None, [], None, False, 'throttled', self._format_failure_detail(
                    api_name,
                    'throttled',
                    api_failure_detail,
                )  # Treat API failures as throttling for retry logic
            
            # Consider it successful if we found data or verification errors (i.e., we could verify something)
            success = verified_data is not None or len(errors) > 0
            self._update_api_stats(api_name, success, duration)
            
            if success:
                verified_data = self._annotate_match_source(verified_data, api_name, api_instance)
                retry_info = " (retry)" if is_retry else ""
                logger.debug(f"Enhanced Hybrid: {api_name} successful in {duration:.2f}s{retry_info}, URL: {url}")
                return verified_data, errors, url, True, 'none', ''
            else:
                logger.debug(f"Enhanced Hybrid: {api_name} found no results in {duration:.2f}s")
                return None, [], None, False, 'not_found', ''
                
        except requests.exceptions.Timeout as e:
            duration = time.time() - start_time
            self._update_api_stats(api_name, False, duration)
            failure_type = 'timeout'
            logger.debug(f"Enhanced Hybrid: {api_name} timed out in {duration:.2f}s: {e}")
            return None, [], None, False, failure_type, self._format_failure_detail(
                api_name,
                failure_type,
                str(e) or None,
            )
            
        except requests.exceptions.RequestException as e:
            duration = time.time() - start_time
            self._update_api_stats(api_name, False, duration)
            
            # Check if it's a rate limiting or server error that should be retried
            error_str = str(e).lower()
            status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') and e.response else None
            
            if (status_code == 429) or "429" in str(e) or "rate limit" in error_str:
                failure_type = 'throttled'
                self.api_stats[api_name]['throttled'] += 1
                logger.debug(f"Enhanced Hybrid: {api_name} rate limited in {duration:.2f}s: {e}")
            elif (status_code and status_code >= 500) or "500" in str(e) or "502" in str(e) or "503" in str(e) or "server error" in error_str or "service unavailable" in error_str:
                failure_type = 'server_error'
                logger.debug(f"Enhanced Hybrid: {api_name} server error in {duration:.2f}s: {e}")
            else:
                failure_type = 'other'
                logger.debug(f"Enhanced Hybrid: {api_name} failed in {duration:.2f}s: {e}")

            failure_detail = str(e).strip()
            if status_code and str(status_code) not in failure_detail:
                failure_detail = f'HTTP {status_code}: {failure_detail}' if failure_detail else f'HTTP {status_code}'
            return None, [], None, False, failure_type, self._format_failure_detail(
                api_name,
                failure_type,
                failure_detail or None,
            )
            
        except Exception as e:
            duration = time.time() - start_time
            self._update_api_stats(api_name, False, duration)
            failure_type = 'other'
            logger.debug(f"Enhanced Hybrid: {api_name} failed in {duration:.2f}s: {e}")
            return None, [], None, False, failure_type, self._format_failure_detail(
                api_name,
                failure_type,
                str(e) or None,
            )
        finally:
            # Accumulate timing stats
            call_duration = time.time() - start_time
            with self._api_time_lock:
                self._api_total_time[api_name] = self._api_total_time.get(api_name, 0) + call_duration
                self._api_sem_wait_time[api_name] = self._api_sem_wait_time.get(api_name, 0) + sem_wait
            # Release per-API semaphore so other refs can use this API
            if sem is not None:
                sem.release()
    
    def _should_try_doi_apis_first(self, reference: Dict[str, Any]) -> bool:
        """
        Determine if we should prioritize DOI-based APIs (CrossRef) for this reference
        """
        # Check if reference has DOI information
        has_doi = (reference.get('doi') or 
                  (reference.get('url') and ('doi.org' in reference['url'] or 'doi:' in reference['url'])) or
                  (reference.get('raw_text') and ('doi' in reference['raw_text'].lower())))
        return has_doi
    
    def _is_data_complete(self, verified_data: Dict[str, Any], reference: Dict[str, Any]) -> bool:
        """
        Check if the verified data is sufficiently complete for the reference verification
        
        Args:
            verified_data: Paper data returned by API
            reference: Original reference data
            
        Returns:
            True if data is complete enough to use, False if incomplete
        """
        if not verified_data:
            return False
        
        # If the reference has authors, the verified data should also have authors
        cited_authors = reference.get('authors', [])
        found_authors = verified_data.get('authors', [])
        
        # If we cited authors but found none, the data is incomplete
        if cited_authors and not found_authors:
            logger.debug(f"Enhanced Hybrid: Data incomplete - cited authors {cited_authors} but found none")
            return False
        
        return True
    
    def _merge_arxiv_with_semantic_scholar(
        self,
        arxiv_data: Dict[str, Any],
        arxiv_errors: List[Dict[str, Any]],
        arxiv_url: str,
        ss_data: Dict[str, Any],
        ss_errors: List[Dict[str, Any]],
        ss_url: str,
        reference: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Merge ArXiv verification results with Semantic Scholar data.
        
        ArXiv is authoritative for title/author/year, but Semantic Scholar
        provides venue information and additional URLs (DOI, S2 page).
        
        Args:
            arxiv_data: Verified data from ArXiv
            arxiv_errors: Errors/warnings from ArXiv verification
            arxiv_url: ArXiv URL
            ss_data: Data from Semantic Scholar
            ss_errors: Errors from Semantic Scholar (used for venue checking)
            ss_url: Semantic Scholar URL
            reference: Original reference
            
        Returns:
            Tuple of (merged_data, merged_errors)
        """
        merged_data = dict(arxiv_data) if arxiv_data else {}
        merged_errors = list(arxiv_errors) if arxiv_errors else []
        
        if not ss_data:
            return merged_data, merged_errors
        
        # Add Semantic Scholar URL to external IDs
        if 'externalIds' not in merged_data:
            merged_data['externalIds'] = {}
        
        ss_external_ids = ss_data.get('externalIds', {})
        
        # Add S2 paper ID
        if ss_data.get('paperId'):
            merged_data['externalIds']['S2PaperId'] = ss_data['paperId']
        
        # Add DOI if available from Semantic Scholar
        if ss_external_ids.get('DOI') and not merged_data['externalIds'].get('DOI'):
            merged_data['externalIds']['DOI'] = ss_external_ids['DOI']
        
        # Store Semantic Scholar URL
        merged_data['_semantic_scholar_url'] = ss_url
        
        # Check for venue mismatch - if paper was published at a venue but citation only says arXiv
        ss_venue = ss_data.get('venue', '')
        cited_venue = reference.get('venue', reference.get('journal', '')).strip().lower()
        
        # Normalize ArXiv venue names
        is_cited_as_arxiv = (
            not cited_venue or 
            cited_venue in ['arxiv', 'arxiv preprint', 'arxiv.org', 'preprint']
        )
        
        # Check if Semantic Scholar shows a real publication venue
        if ss_venue and is_cited_as_arxiv:
            # Ignore generic/empty venues
            ss_venue_lower = ss_venue.lower().strip()
            is_real_venue = (
                ss_venue_lower and 
                ss_venue_lower not in ['arxiv', 'arxiv.org', 'preprint', ''] and
                not ss_venue_lower.startswith('arxiv')
            )
            
            if is_real_venue:
                # This paper was published at a venue but is only cited as arXiv
                logger.debug(f"Enhanced Hybrid: Paper published at '{ss_venue}' but cited as arXiv")
                merged_errors.append({
                    'warning_type': 'venue',
                    'warning_details': f"Paper was published at venue but cited as arXiv preprint:\n       cited:  arXiv\n       actual: {ss_venue}",
                    'ref_venue_correct': ss_venue
                })
                # Also add the venue to merged data
                merged_data['venue'] = ss_venue
        
        return merged_data, merged_errors

    def _has_major_author_discrepancy(self, errors):
        """Check if errors indicate a major author discrepancy.
        
        A major discrepancy means the DB entry's authors are completely
        different from the cited authors — suggesting a corrupt or wrong
        database entry (e.g., S2 duplicate with fabricated authors).
        
        Returns True only when there's zero overlap between cited and
        actual author last names, indicating the DB matched the wrong paper.
        """
        for error in errors:
            if error.get('error_type') != 'author':
                continue
            details = error.get('error_details', '')
            actual_str = error.get('ref_authors_correct', '')
            if not actual_str or not details:
                continue
            # Only flag if it says "not found in author list" (zero match)
            if 'not found in author list' not in details:
                continue
            # Extract cited author name from the error details
            # Format: "Author 1 mismatch\n       cited:  Name (not found...)\n       actual: ..."
            import re
            cited_match = re.search(r'cited:\s+(.+?)(?:\s+\(not found)', details)
            if not cited_match:
                continue
            cited_name = cited_match.group(1).strip().lower()
            actual_names = actual_str.lower()
            # Extract last names from cited author
            cited_parts = cited_name.split()
            # Check if ANY part of the cited name appears in actual authors
            has_overlap = False
            for part in cited_parts:
                if len(part) > 2 and part in actual_names:
                    has_overlap = True
                    break
            if not has_overlap:
                logger.debug(f"Enhanced Hybrid: Major author discrepancy — cited '{cited_name}' has no overlap with actual '{actual_str}'")
                return True
        return False

    def _verify_arxiv_parallel(self, reference, failed_apis, attempted_apis):
        """Run ArXiv citation + Semantic Scholar API in parallel for ArXiv refs.
        
        Called after local DB was tried and either failed or had discrepancies.
        ArXiv BibTeX is the authoritative source for authors/title.
        S2 API provides venue metadata for merging.
        
        Returns result tuple or None if both failed.
        """
        logger.debug("Enhanced Hybrid: ArXiv reference — running ArXiv citation + Semantic Scholar in parallel")
        
        futures = {}
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="HybridAPI") as pool:
            if self.arxiv_citation:
                self._append_attempted_api(attempted_apis, 'arxiv_citation')
                futures['arxiv_citation'] = pool.submit(
                    self._try_api, 'arxiv_citation', self.arxiv_citation, reference)
            if self.semantic_scholar:
                self._append_attempted_api(attempted_apis, 'semantic_scholar')
                futures['semantic_scholar'] = pool.submit(
                    self._try_api, 'semantic_scholar', self.semantic_scholar, reference)
        
        arxiv_result = None
        ss_result = None
        
        for name, future in futures.items():
            verified_data, errors, url, success, failure_type, failure_detail = future.result()
            if name == 'arxiv_citation':
                if success:
                    arxiv_result = (verified_data, errors, url)
                elif failure_type not in ('none', 'not_found'):
                    failed_apis.append({
                        'name': 'arxiv_citation',
                        'instance': self.arxiv_citation,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
            elif name == 'semantic_scholar':
                if success:
                    ss_result = (verified_data, errors, url)
                elif failure_type not in ('none', 'not_found'):
                    failed_apis.append({
                        'name': 'semantic_scholar',
                        'instance': self.semantic_scholar,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
        
        # Merge results
        if arxiv_result and ss_result:
            ss_data, ss_errors, ss_url = ss_result
            if ss_data:
                ss_venue = self.semantic_scholar.get_venue_from_paper_data(ss_data)
                if ss_venue and 'arxiv' in ss_venue.lower():
                    logger.debug("Enhanced Hybrid: Semantic Scholar only found ArXiv venue, skipping merge")
                    return arxiv_result
            arxiv_data, arxiv_errors, arxiv_url = arxiv_result
            merged_data, merged_errors = self._merge_arxiv_with_semantic_scholar(
                arxiv_data, arxiv_errors, arxiv_url,
                ss_data, ss_errors, ss_url,
                reference)
            return merged_data, merged_errors, arxiv_url
        
        if arxiv_result:
            return arxiv_result
        if ss_result:
            return ss_result
        return None

    def _verify_non_arxiv_parallel(self, reference, failed_apis, attempted_apis, skip_ss: bool = False):
        """Try Semantic Scholar first (highest hit rate), then fallback APIs in parallel.
        
        Returns (result, incomplete_results) where result is a complete
        (verified_data, errors, url) tuple or None, and incomplete_results
        is a dict of {'crossref': ..., 'openalex': ...} for Phase 3 fallback.
        incomplete_results are kept as local variables to avoid thread-safety
        issues when multiple threads share the same checker instance.
        """
        last_crossref_result = None
        last_openalex_result = None
        
        # Try Semantic Scholar first — it succeeds ~92% of the time.
        # Skip SS when the local DB (233M papers) already returned not_found:
        # if it's not in the DB, it's almost certainly not on the SS API either,
        # and the API call just wastes time and rate-limit budget.
        if self.semantic_scholar and not skip_ss:
            self._append_attempted_api(attempted_apis, 'semantic_scholar')
            verified_data, errors, url, success, failure_type, failure_detail = self._try_api('semantic_scholar', self.semantic_scholar, reference)
            if success:
                if self._is_data_complete(verified_data, reference):
                    return (verified_data, errors, url), {}
            elif failure_type not in ('none', 'not_found'):
                failed_apis.append({
                    'name': 'semantic_scholar',
                    'instance': self.semantic_scholar,
                    'failure_type': failure_type,
                    'failure_detail': failure_detail,
                    'active': True,
                })
        
        # SS failed or incomplete — fire remaining APIs in parallel
        fallback_apis = []
        if self.crossref:
            fallback_apis.append(('crossref', self.crossref))
        if self.openalex:
            fallback_apis.append(('openalex', self.openalex))
        if self.dblp:
            fallback_apis.append(('dblp', self.dblp))
        
        if fallback_apis:
            logger.debug(f"Enhanced Hybrid: SS failed, launching {len(fallback_apis)} fallback APIs in parallel")
            futures = {}
            with ThreadPoolExecutor(max_workers=len(fallback_apis), thread_name_prefix="HybridAPI") as pool:
                for api_name, api_instance in fallback_apis:
                    self._append_attempted_api(attempted_apis, api_name)
                    futures[api_name] = pool.submit(
                        self._try_api, api_name, api_instance, reference)
            
            priority = ['crossref', 'openalex', 'dblp']
            for api_name in priority:
                if api_name not in futures:
                    continue
                verified_data, errors, url, success, failure_type, failure_detail = futures[api_name].result()
                if not success and failure_type not in ('none', 'not_found'):
                    api_inst = dict(fallback_apis)[api_name]
                    failed_apis.append({
                        'name': api_name,
                        'instance': api_inst,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
                if success:
                    if self._is_data_complete(verified_data, reference):
                        return (verified_data, errors, url), {}
                    if api_name == 'crossref':
                        last_crossref_result = (verified_data, errors, url)
                    elif api_name == 'openalex':
                        last_openalex_result = (verified_data, errors, url)
        
        # Try OpenReview as a secondary step (not parallelized — rare path)
        if self.openreview:
            if hasattr(self.openreview, 'is_openreview_reference') and self.openreview.is_openreview_reference(reference):
                self._append_attempted_api(attempted_apis, 'openreview')
                verified_data, errors, url, success, failure_type, failure_detail = self._try_api('openreview', self.openreview, reference)
                if success:
                    return (verified_data, errors, url), {}
                if failure_type not in ('none', 'not_found'):
                    failed_apis.append({
                        'name': 'openreview',
                        'instance': self.openreview,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
            elif hasattr(self.openreview, 'verify_reference_by_search'):
                venue = reference.get('venue', reference.get('journal', '')).lower()
                openreview_venues = ['iclr', 'icml', 'neurips', 'nips', 'aaai', 'ijcai',
                    'international conference on learning representations',
                    'international conference on machine learning',
                    'neural information processing systems']
                if any(v in venue for v in openreview_venues):
                    self._append_attempted_api(attempted_apis, 'openreview')
                    verified_data, errors, url, success, failure_type, failure_detail = self._try_openreview_search(reference)
                    if success:
                        return (verified_data, errors, url), {}
                    if failure_type not in ('none', 'not_found'):
                        failed_apis.append({
                            'name': 'openreview',
                            'instance': self.openreview,
                            'failure_type': failure_type,
                            'failure_detail': failure_detail,
                            'active': True,
                        })
        
        # Return None with any incomplete results for Phase 3 fallback
        incomplete = {}
        if last_crossref_result:
            incomplete['crossref'] = last_crossref_result
        if last_openalex_result:
            incomplete['openalex'] = last_openalex_result
        return None, incomplete

    # ------------------------------------------------------------------
    # Post-verification checks (shared by CLI, WebUI, and bulk paths)
    # ------------------------------------------------------------------

    def _check_arxiv_id_mismatch(self, reference: Dict[str, Any],
                                  verified_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Check if the cited ArXiv ID actually points to the cited paper.

        Returns a list of errors (arxiv_id or title type) if there's a
        mismatch, or an empty list if the ID is correct or absent.
        """
        from refchecker.utils.url_utils import extract_arxiv_id_from_url
        from refchecker.utils.text_utils import calculate_title_similarity, compare_authors

        ref_arxiv_id = None
        if reference.get('url') and 'arxiv.org/abs/' in reference['url']:
            ref_arxiv_id = extract_arxiv_id_from_url(reference['url'])
        if not ref_arxiv_id and reference.get('venue'):
            ref_arxiv_id = extract_arxiv_id_from_url(reference['venue'])
        if not ref_arxiv_id:
            return []

        # Look up what the ArXiv ID actually points to
        actual_paper = None
        if self.arxiv_citation:
            try:
                actual_data, _, _ = self.arxiv_citation.verify_reference(
                    {'url': f'https://arxiv.org/abs/{ref_arxiv_id}',
                     'title': '', 'authors': [], 'raw_text': ''}
                )
                if actual_data:
                    actual_paper = actual_data
            except Exception:
                pass

        # Check verified_data for ArXiv ID mismatch
        if verified_data:
            ext = verified_data.get('externalIds', {})
            correct_id = ext.get('ArXiv') or ext.get('arxiv')
            if correct_id and ref_arxiv_id != correct_id:
                return [{'error_type': 'arxiv_id',
                         'error_details': f"Incorrect ArXiv ID: ArXiv ID {ref_arxiv_id} should be {correct_id}"}]

        if not actual_paper:
            return []

        expected_title = reference.get('title', '').strip()
        if not expected_title:
            return []

        actual_title = actual_paper.get('title', '')
        title_sim = calculate_title_similarity(expected_title.lower(), actual_title.lower())

        if title_sim < 0.4:
            # Titles very different — check authors to distinguish wrong ID vs inaccurate title
            expected_authors = reference.get('authors', [])
            actual_authors_raw = actual_paper.get('authors', [])
            actual_author_names = [
                a.get('name', str(a)) if isinstance(a, dict) else str(a)
                for a in actual_authors_raw
            ]
            authors_match = False
            if expected_authors and actual_author_names:
                try:
                    authors_match, _ = compare_authors(expected_authors, actual_author_names)
                except Exception:
                    pass
            if authors_match:
                return [{'error_type': 'title',
                         'error_details': f"Inaccurate title: cited as '{expected_title}' but ArXiv paper is titled '{actual_title}'"}]
            else:
                return [{'error_type': 'arxiv_id',
                         'error_details': f"Incorrect ArXiv ID: ArXiv ID {ref_arxiv_id} points to '{actual_title}'"}]
        return []

    def _try_arxiv_re_verify(self, errors: List[Dict[str, Any]],
                              verified_data: Optional[Dict[str, Any]],
                              reference: Dict[str, Any]) -> Optional[Tuple]:
        """Re-verify against ArXiv when the DB likely matched the wrong paper.

        Triggers when there's an author error with ≤10% overlap (catastrophic
        mismatch). Returns (errors, url, verified_data) on success, or None.
        """
        author_err = next(
            (e for e in errors if (e.get('error_type') or '').lower() == 'author'),
            None,
        )
        if author_err is None:
            return None

        cited_authors = author_err.get('ref_authors_cited', '')
        correct_authors = author_err.get('ref_authors_correct', '')
        if not cited_authors:
            ref_authors = reference.get('authors', [])
            cited_authors = ', '.join(
                a.get('name', a) if isinstance(a, dict) else str(a)
                for a in ref_authors
            ) if isinstance(ref_authors, list) else str(ref_authors)
        if not cited_authors or not correct_authors:
            return None

        from refchecker.core.hallucination_policy import _compute_author_overlap
        overlap = _compute_author_overlap(cited_authors, correct_authors)

        # Trigger re-verification when:
        # 1. Catastrophic mismatch (≤10% overlap — wrong paper matched), OR
        # 2. Cited has slightly MORE authors than the DB entry (1-2 extra)
        #    AND high overlap — S2/DB may have incomplete author data while
        #    ArXiv has the complete list.  Don't trigger for large differences
        #    (≥3 extra) as those indicate fabricated author lists.
        cited_count = len([a for a in cited_authors.split(',') if a.strip()])
        correct_count = len([a for a in correct_authors.split(',') if a.strip()])
        small_count_gap = 0 < (cited_count - correct_count) <= 2

        if overlap is not None and overlap <= 0.1:
            logger.debug(
                "DB match has catastrophic author mismatch (%.0f%% overlap) — "
                "attempting ArXiv re-verification for '%s'",
                overlap * 100, reference.get('title', '')[:60],
            )
        elif small_count_gap and overlap is not None and overlap >= 0.5:
            logger.debug(
                "DB has fewer authors (%d) than cited (%d), overlap %.0f%% — "
                "attempting ArXiv re-verification for '%s'",
                correct_count, cited_count, overlap * 100,
                reference.get('title', '')[:60],
            )
        else:
            return None

        if not self.arxiv_citation:
            return None

        arxiv_id = None
        try:
            arxiv_id, _ = self.arxiv_citation.extract_arxiv_id(reference)
        except Exception:
            pass
        if not arxiv_id and verified_data:
            ext = verified_data.get('externalIds') or {}
            arxiv_id = ext.get('ArXiv') or ext.get('arxiv') or None

        if not arxiv_id:
            return None

        try:
            # Ensure the reference has an ArXiv URL for the citation checker
            re_ref = dict(reference)
            if not re_ref.get('url') or 'arxiv.org' not in re_ref.get('url', ''):
                re_ref['url'] = f'https://arxiv.org/abs/{arxiv_id}'
            arxiv_data, arxiv_errors, arxiv_url = self.arxiv_citation.verify_reference(re_ref)
            if arxiv_data is not None:
                logger.debug("ArXiv re-verification succeeded for %s", arxiv_id)
                return arxiv_errors or [], arxiv_url, arxiv_data
        except Exception as exc:
            logger.debug("ArXiv re-verification failed: %s", exc)

        return None

    def _postprocess_verification(
        self,
        verified_data: Optional[Dict[str, Any]],
        errors: List[Dict[str, Any]],
        url: Optional[str],
        reference: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """Apply post-verification checks shared by all code paths.

        1. ArXiv re-verification for catastrophic author mismatches
        2. Independent ArXiv ID mismatch check
        3. Error formatting

        Called at the end of verify_reference() so CLI, WebUI, and bulk
        all get identical results.
        """
        # 1. ArXiv re-verify when the DB matched the wrong paper
        if errors and verified_data is not None:
            re_result = self._try_arxiv_re_verify(errors, verified_data, reference)
            if re_result is not None:
                errors, url, verified_data = re_result

        # 2. Independent ArXiv ID check — skip when the hybrid checker
        #    already verified the paper with no errors (avoids false
        #    positives from paraphrased titles in the S2 API)
        if errors:  # only when there are existing errors
            already_has_arxiv = any(e.get('error_type') == 'arxiv_id' for e in errors)
            if not already_has_arxiv:
                arxiv_errors = self._check_arxiv_id_mismatch(reference, verified_data)
                if arxiv_errors:
                    errors = (errors or []) + arxiv_errors

        return verified_data, errors or [], url

    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """Verify a reference and apply post-processing checks.

        This is the single entry point used by CLI, WebUI, and bulk paths.
        All verification logic lives here so every mode gets identical results.
        """
        verified_data, errors, url = self._verify_reference_core(reference)

        # Post-process: ArXiv re-verify, independent ArXiv ID check
        verified_data, errors, url = self._postprocess_verification(
            verified_data, errors, url, reference,
        )
        return verified_data, errors, url

    def _verify_reference_core(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """Core verification logic — parallel API calls + retries + fallbacks."""
        # Check if this is a URL-only reference (should skip verification)
        authors = reference.get('authors', [])
        if authors and "URL Reference" in authors:
            logger.debug("Enhanced Hybrid: Skipping verification for URL reference")
            return None, [], reference.get('cited_url') or reference.get('url')
        
        title = reference.get('title', '').strip()
        cited_url = reference.get('cited_url') or reference.get('url')
        if not title and cited_url:
            logger.debug(f"Enhanced Hybrid: Skipping verification for URL-only reference: {cited_url}")
            return None, [], cited_url
        
        failed_apis = []
        attempted_apis = []
        db_not_found = False
        incomplete_data = None
        is_arxiv = self.arxiv_citation and self.arxiv_citation.is_arxiv_reference(reference)
        
        # ── PHASE 1: Parallel API calls ──
        
        if is_arxiv:
            # For ArXiv refs: try local DB first (instant). If result looks
            # clean, use it. If there's a major discrepancy (e.g., wrong
            # authors from a corrupt S2 entry), fall back to ArXiv BibTeX.
            for local_key, _, local_checker in self._iter_local_db_checkers():
                self._append_attempted_api(attempted_apis, local_key)
                verified_data, errors, url, success, failure_type, failure_detail = self._try_api(
                    local_key,
                    local_checker,
                    reference,
                )
                if success:
                    if not self._has_major_author_discrepancy(errors):
                        return verified_data, errors, url
                    logger.debug(
                        "Enhanced Hybrid: %s has major author discrepancy for ArXiv ref, falling back to ArXiv citation",
                        local_key,
                    )
                elif failure_type == 'not_found' and local_key == 'local_s2':
                    db_not_found = True
                elif failure_type not in ('none', 'not_found'):
                    failed_apis.append({
                        'name': local_key,
                        'instance': local_checker,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
            
            # Local DB failed or had discrepancy — use ArXiv citation checker
            result = self._verify_arxiv_parallel(reference, failed_apis, attempted_apis)
            if result is not None:
                verified_data, errors, url = result
                # Check if the ArXiv URL points to a completely different paper.
                # A title *error* (not warning) means the cited title didn't match
                # ANY version of the ArXiv paper at this ID — the URL is wrong.
                # However, version checking may have failed (rate-limiting,
                # timeout) even though the paper IS the same — just with a
                # revised title.  Only short-circuit when the titles are truly
                # unrelated (similarity < 0.5); moderate similarity suggests a
                # title revision that the version checker couldn't confirm.
                has_title_error = any(
                    e.get('error_type') == 'title' for e in errors
                )
                if has_title_error:
                    cited_title = reference.get('title', 'unknown')
                    actual_title = (verified_data or {}).get('title', 'unknown')
                    # Compute similarity to distinguish "completely different
                    # paper" from "same paper, revised title between versions".
                    # Truly different papers score 0.0–0.1; revised titles
                    # score 0.3–0.5+.  Use 0.25 as a conservative cutoff.
                    from refchecker.utils.text_utils import compare_titles_with_latex_cleaning
                    title_sim = compare_titles_with_latex_cleaning(cited_title, actual_title)
                    if title_sim < 0.25:
                        # Titles are truly unrelated — the ArXiv ID points to
                        # a different paper.  Short-circuit to avoid wasting
                        # time on fallback APIs for a likely fabricated ref.
                        arxiv_url = reference.get('cited_url') or reference.get('url', '')
                        logger.debug(
                            f"Enhanced Hybrid: ArXiv URL points to a different paper "
                            f"(cited: '{cited_title}', actual: '{actual_title}', "
                            f"sim={title_sim:.2f}) — returning as unverified"
                        )
                        return None, [
                            {
                                'error_type': 'unverified',
                                'error_details': f'Could not verify: {cited_title}',
                            },
                            {
                                'error_type': 'url',
                                'error_details': f'Cited URL does not reference this paper: {arxiv_url}',
                            },
                        ], arxiv_url
                    else:
                        # Titles share significant overlap — likely the same
                        # paper with a revised title.  Return the ArXiv data
                        # so downstream can evaluate it normally.
                        logger.debug(
                            f"Enhanced Hybrid: ArXiv title mismatch but titles "
                            f"are similar (sim={title_sim:.2f}), treating as "
                            f"version update: '{cited_title}' vs '{actual_title}'"
                        )
                        return result
                else:
                    return result
        else:
            # Non-ArXiv: try local DB first (instant), then parallel remote APIs
            for local_key, _, local_checker in self._iter_local_db_checkers():
                self._append_attempted_api(attempted_apis, local_key)
                verified_data, errors, url, success, failure_type, failure_detail = self._try_api(
                    local_key,
                    local_checker,
                    reference,
                )
                if success:
                    return verified_data, errors, url
                if failure_type not in ('none', 'not_found'):
                    failed_apis.append({
                        'name': local_key,
                        'instance': local_checker,
                        'failure_type': failure_type,
                        'failure_detail': failure_detail,
                        'active': True,
                    })
                elif failure_type == 'not_found' and local_key == 'local_s2':
                    db_not_found = True
            
            # Skip SS API when the 233M-paper local DB returned not_found —
            # if it's not in the DB, it's almost certainly not on SS either.
            result, incomplete_data = self._verify_non_arxiv_parallel(reference, failed_apis, attempted_apis, skip_ss=db_not_found)
            if result is not None:
                return result
        
        # Store incomplete results for Phase 3 fallback (thread-safe: returned
        # as local values from _verify_non_arxiv_parallel, not shared state)
        crossref_result = incomplete_data.get('crossref') if incomplete_data else None
        openalex_result = incomplete_data.get('openalex') if incomplete_data else None
        
        # PHASE 2: If no API succeeded in Phase 1, retry failed APIs.
        # Skip retries when the local DB definitively returned not_found —
        # if a paper isn't in a 233M-paper database, retrying throttled
        # remote APIs is almost certainly wasted time and the main cause
        # of verification timeouts.
        if failed_apis and self.local_db and db_not_found:
            logger.debug(f"Enhanced Hybrid: Skipping Phase 2 retries — local DB (233M papers) returned not_found, retrying remote APIs is unlikely to help")
        elif failed_apis:
            logger.debug(f"Enhanced Hybrid: Phase 1 complete, no success. Retrying {len(failed_apis)} failed APIs")
            
            # Sort failed APIs to prioritize Semantic Scholar retries
            retryable_failures = [
                api for api in failed_apis
                if api.get('failure_type') in ('throttled', 'timeout', 'server_error') and api.get('active', True)
            ]
            semantic_scholar_retries = [api for api in retryable_failures if api['name'] == 'semantic_scholar']
            other_retries = [api for api in retryable_failures if api['name'] != 'semantic_scholar']
            
            # Try other APIs first, then Semantic Scholar with more aggressive retries
            retry_order = other_retries + semantic_scholar_retries
            
            for failed_api in retry_order:
                api_name = failed_api['name']
                api_instance = failed_api['instance']
                failure_type = failed_api['failure_type']

                # Use base delay for first retry of each API
                delay = min(self.retry_base_delay, self.max_retry_delay)
                
                # Add jitter to prevent thundering herd (±25% randomization)
                jitter = delay * 0.25 * (2 * random.random() - 1)
                final_delay = max(0.5, delay + jitter)
                
                logger.debug(f"Enhanced Hybrid: Waiting {final_delay:.1f}s before retrying {api_name} after {failure_type} failure")
                time.sleep(final_delay)
                with self._api_time_lock:
                    self._api_retry_sleep_time += final_delay
                
                logger.debug(f"Enhanced Hybrid: Retrying {api_name}")
                self._append_attempted_api(attempted_apis, api_name)
                verified_data, errors, url, success, retry_failure_type, retry_failure_detail = self._try_api(api_name, api_instance, reference, is_retry=True)
                if success:
                    logger.debug(f"Enhanced Hybrid: {api_name} succeeded on retry after {failure_type} (delay: {final_delay:.1f}s)")
                    return verified_data, errors, url

                failed_api['failure_type'] = retry_failure_type
                failed_api['failure_detail'] = retry_failure_detail
                failed_api['active'] = retry_failure_type not in ('none', 'not_found')
                
                # For Semantic Scholar, try additional retries with increasing delays
                if api_name == 'semantic_scholar' and not success:
                    for retry_attempt in range(2):  # Additional 2 retries for Semantic Scholar
                        retry_delay = delay * (self.retry_backoff_factor ** (retry_attempt + 1))
                        retry_delay = min(retry_delay, self.max_retry_delay)
                        retry_jitter = retry_delay * 0.25 * (2 * random.random() - 1)
                        final_retry_delay = max(1.0, retry_delay + retry_jitter)
                        
                        logger.debug(f"Enhanced Hybrid: Additional Semantic Scholar retry {retry_attempt + 2} after {final_retry_delay:.1f}s")
                        time.sleep(final_retry_delay)
                        with self._api_time_lock:
                            self._api_retry_sleep_time += final_retry_delay
                        
                        self._append_attempted_api(attempted_apis, api_name)
                        verified_data, errors, url, success, retry_failure_type, retry_failure_detail = self._try_api(api_name, api_instance, reference, is_retry=True)
                        if success:
                            logger.debug(f"Enhanced Hybrid: {api_name} succeeded on retry {retry_attempt + 2} (delay: {final_retry_delay:.1f}s)")
                            return verified_data, errors, url

                        failed_api['failure_type'] = retry_failure_type
                        failed_api['failure_detail'] = retry_failure_detail
                        failed_api['active'] = retry_failure_type not in ('none', 'not_found')
        
        # PHASE 3: If all APIs failed or returned incomplete data, use best available incomplete data as fallback
        incomplete_results = [r for r in [crossref_result, openalex_result] if r is not None]
        if incomplete_results:
            # Prefer CrossRef over OpenAlex for incomplete data (usually more reliable)
            best_incomplete = crossref_result if crossref_result else openalex_result
            logger.debug("Enhanced Hybrid: No complete data found, using incomplete data as fallback")
            return best_incomplete
        
        # If all APIs failed, return unverified with source tracking metadata
        active_failures = [api for api in failed_apis if api.get('active', True)]
        failed_count = len(active_failures)
        failed_api_names = {api['name'] for api in active_failures}
        failure_reason = self._build_unverified_error_details(attempted_apis, active_failures)
        sources_checked = len(attempted_apis)
        sources_negative = len([api_name for api_name in attempted_apis if api_name not in failed_api_names])
        
        if failed_count > 0:
            logger.debug(f"Enhanced Hybrid: Verification ended with {failed_count} active checker failures after {sources_checked} attempts")
        else:
            logger.debug("Enhanced Hybrid: All available APIs failed to verify reference")
        
        # PHASE 4: If the reference has a URL, try web page verification as final fallback.
        # This handles non-academic references (websites, datasets, tools) whose
        # cited URL is valid and contains the reference title.
        web_url = reference.get('cited_url') or reference.get('url', '')
        if web_url and web_url.startswith('http'):
            try:
                from refchecker.checkers.webpage_checker import WebPageChecker
                webpage_checker = WebPageChecker()
                wp_data, wp_errors, wp_url = webpage_checker.verify_raw_url_for_unverified_reference(reference)
                if wp_data:
                    logger.debug(f"Enhanced Hybrid: Web page verification succeeded for {web_url}")
                    return wp_data, wp_errors, wp_url
                else:
                    logger.debug(f"Enhanced Hybrid: Web page verification did not confirm reference")
                    # Build error list: include both a URL-specific error and the
                    # underlying unverified error so the user sees *why* it failed.
                    errors_out = []
                    if wp_errors:
                        subreason = wp_errors[0].get('error_details', '')
                        errors_out.append({
                            'error_type': 'unverified',
                            'error_details': failure_reason,
                            'sources_checked': sources_checked,
                            'sources_negative': sources_negative,
                        })
                        # Use specific message based on what went wrong
                        if 'non-existent' in subreason:
                            url_msg = f'Non-existent web page: {web_url}'
                        elif 'URL references paper' in subreason:
                            url_msg = f'Paper not verified but URL references paper: {web_url}'
                        else:
                            url_msg = f'Cited URL does not reference this paper: {web_url}'
                        errors_out.append({
                            'error_type': 'url',
                            'error_details': url_msg,
                        })
                    else:
                        errors_out.append({
                            'error_type': 'unverified',
                            'error_details': failure_reason,
                            'sources_checked': sources_checked,
                            'sources_negative': sources_negative,
                        })
                    return None, errors_out, wp_url
            except Exception as exc:
                logger.debug(f"Enhanced Hybrid: Web page verification failed: {exc}")

        return None, [{
            'error_type': 'unverified',
            'error_details': failure_reason,
            'sources_checked': sources_checked,
            'sources_negative': sources_negative,
        }], None
    
    def _try_openreview_search(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str], bool, str, str]:
        """
        Try to verify reference using OpenReview search
        
        Returns:
            Tuple of (verified_data, errors, url, success, failure_type, failure_detail)
        """
        if not self.openreview:
            return None, [], None, False, 'none', ''
        
        start_time = time.time()
        failure_type = 'none'
        
        try:
            verified_data, errors, url = self.openreview.verify_reference_by_search(reference)
            duration = time.time() - start_time
            
            # Consider it successful if we found data or verification errors
            success = verified_data is not None or len(errors) > 0
            self._update_api_stats('openreview', success, duration)
            
            if success:
                logger.debug(f"Enhanced Hybrid: OpenReview search successful in {duration:.2f}s, URL: {url}")
                return verified_data, errors, url, True, 'none', ''
            else:
                logger.debug(f"Enhanced Hybrid: OpenReview search found no results in {duration:.2f}s")
                return None, [], None, False, 'not_found', ''
                
        except requests.exceptions.Timeout as e:
            duration = time.time() - start_time
            self._update_api_stats('openreview', False, duration)
            failure_type = 'timeout'
            logger.debug(f"Enhanced Hybrid: OpenReview search timed out in {duration:.2f}s: {e}")
            return None, [], None, False, failure_type, self._format_failure_detail(
                'openreview',
                failure_type,
                str(e) or None,
            )
            
        except requests.exceptions.RequestException as e:
            duration = time.time() - start_time
            self._update_api_stats('openreview', False, duration)
            
            # Check if it's a rate limiting error
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code in [429, 503]:
                    failure_type = 'throttled'
                elif e.response.status_code >= 500:
                    failure_type = 'server_error'
                else:
                    failure_type = 'other'
            else:
                failure_type = 'other'
            
            logger.debug(f"Enhanced Hybrid: OpenReview search failed in {duration:.2f}s: {type(e).__name__}: {e}")
            return None, [], None, False, failure_type, self._format_failure_detail(
                'openreview',
                failure_type,
                str(e) or None,
            )
            
        except Exception as e:
            duration = time.time() - start_time
            self._update_api_stats('openreview', False, duration)
            failure_type = 'other'
            logger.debug(f"Enhanced Hybrid: OpenReview search error in {duration:.2f}s: {type(e).__name__}: {e}")
            return None, [], None, False, failure_type, self._format_failure_detail(
                'openreview',
                failure_type,
                str(e) or None,
            )
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics for all APIs
        
        Returns:
            Dictionary with performance statistics
        """
        stats = {}
        for api_name, api_stats in self.api_stats.items():
            total_calls = api_stats['success'] + api_stats['failure']
            if total_calls > 0:
                success_rate = api_stats['success'] / total_calls
                stats[api_name] = {
                    'success_rate': success_rate,
                    'total_calls': total_calls,
                    'avg_time': api_stats['avg_time'],
                    'success_count': api_stats['success'],
                    'failure_count': api_stats['failure']
                }
            else:
                stats[api_name] = {
                    'success_rate': 0,
                    'total_calls': 0,
                    'avg_time': 0,
                    'success_count': 0,
                    'failure_count': 0
                }
        return stats
    
    def log_performance_summary(self):
        """Log a summary of API performance statistics (only if debug mode is enabled)"""
        if not self.debug_mode:
            return
            
        stats = self.get_performance_stats()
        logger.info("Enhanced Hybrid API Performance Summary:")
        for api_name, api_stats in stats.items():
            if api_stats['total_calls'] > 0:
                logger.info(f"  {api_name}: {api_stats['success_rate']:.2%} success rate, "
                           f"{api_stats['total_calls']} calls, {api_stats['avg_time']:.2f}s avg")
            else:
                logger.info(f"  {api_name}: not used")
    
    def normalize_paper_title(self, title: str) -> str:
        """
        Normalize paper title for comparison (delegates to Semantic Scholar checker)
        """
        if self.semantic_scholar:
            return self.semantic_scholar.normalize_paper_title(title)
        else:
            # Use the centralized normalization function from text_utils
            from refchecker.utils.text_utils import normalize_paper_title as normalize_title
            return normalize_title(title)
    
    def compare_authors(self, cited_authors: List[str], correct_authors: List[Any]) -> Tuple[bool, str]:
        """
        Compare author lists (delegates to shared utility)
        """
        from refchecker.utils.text_utils import compare_authors
        return compare_authors(cited_authors, correct_authors)

# Backward compatibility alias
HybridReferenceChecker = EnhancedHybridReferenceChecker
