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
import time
from typing import Dict, List, Tuple, Optional, Any

logger = logging.getLogger(__name__)

class EnhancedHybridReferenceChecker:
    """
    Enhanced hybrid reference checker with multiple API sources for improved reliability
    """
    
    def __init__(self, semantic_scholar_api_key: Optional[str] = None, 
                 db_path: Optional[str] = None,
                 contact_email: Optional[str] = None,
                 enable_openalex: bool = True,
                 enable_crossref: bool = True,
                 debug_mode: bool = False):
        """
        Initialize the enhanced hybrid reference checker
        
        Args:
            semantic_scholar_api_key: Optional API key for Semantic Scholar
            db_path: Optional path to local Semantic Scholar database
            contact_email: Email for polite pool access to APIs
            enable_openalex: Whether to use OpenAlex API
            enable_crossref: Whether to use CrossRef API
            debug_mode: Whether to enable debug logging
        """
        self.contact_email = contact_email
        self.debug_mode = debug_mode
        
        # Initialize local database checker if available
        self.local_db = None
        if db_path:
            try:
                from .local_semantic_scholar import LocalNonArxivReferenceChecker
                self.local_db = LocalNonArxivReferenceChecker(db_path=db_path)
                logger.debug(f"Enhanced Hybrid: Local database enabled at {db_path}")
            except Exception as e:
                logger.warning(f"Enhanced Hybrid: Failed to initialize local database: {e}")
                self.local_db = None
        
        # Initialize Semantic Scholar API
        try:
            from .semantic_scholar import NonArxivReferenceChecker
            self.semantic_scholar = NonArxivReferenceChecker(api_key=semantic_scholar_api_key)
            logger.debug("Enhanced Hybrid: Semantic Scholar API initialized")
        except Exception as e:
            logger.error(f"Enhanced Hybrid: Failed to initialize Semantic Scholar: {e}")
            self.semantic_scholar = None
        
        # Initialize OpenAlex API
        self.openalex = None
        if enable_openalex:
            try:
                from .openalex import OpenAlexReferenceChecker
                self.openalex = OpenAlexReferenceChecker(email=contact_email)
                logger.debug("Enhanced Hybrid: OpenAlex API initialized")
            except Exception as e:
                logger.warning(f"Enhanced Hybrid: Failed to initialize OpenAlex: {e}")
        
        # Initialize CrossRef API
        self.crossref = None
        if enable_crossref:
            try:
                from .crossref import CrossRefReferenceChecker
                self.crossref = CrossRefReferenceChecker(email=contact_email)
                logger.debug("Enhanced Hybrid: CrossRef API initialized")
            except Exception as e:
                logger.warning(f"Enhanced Hybrid: Failed to initialize CrossRef: {e}")
        
        # Google Scholar removed - using more reliable APIs only
        
        # Track API performance for adaptive selection
        self.api_stats = {
            'local_db': {'success': 0, 'failure': 0, 'avg_time': 0},
            'semantic_scholar': {'success': 0, 'failure': 0, 'avg_time': 0},
            'openalex': {'success': 0, 'failure': 0, 'avg_time': 0},
            'crossref': {'success': 0, 'failure': 0, 'avg_time': 0}
        }
    
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
    
    def _try_api(self, api_name: str, api_instance: Any, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str], bool]:
        """
        Try to verify reference with a specific API and track performance
        
        Returns:
            Tuple of (verified_data, errors, url, success)
        """
        if not api_instance:
            return None, [], None, False
        
        start_time = time.time()
        try:
            verified_data, errors, url = api_instance.verify_reference(reference)
            duration = time.time() - start_time
            
            # Consider it successful if we found data or errors (i.e., we could verify something)
            success = verified_data is not None or len(errors) > 0
            self._update_api_stats(api_name, success, duration)
            
            if success:
                logger.debug(f"Enhanced Hybrid: {api_name} successful in {duration:.2f}s, URL: {url}")
                return verified_data, errors, url, True
            else:
                logger.debug(f"Enhanced Hybrid: {api_name} found no results in {duration:.2f}s")
                return None, [], None, False
                
        except Exception as e:
            duration = time.time() - start_time
            self._update_api_stats(api_name, False, duration)
            logger.warning(f"Enhanced Hybrid: {api_name} failed in {duration:.2f}s: {e}")
            return None, [], None, False
    
    def _should_try_doi_apis_first(self, reference: Dict[str, Any]) -> bool:
        """
        Determine if we should prioritize DOI-based APIs (CrossRef) for this reference
        """
        # Check if reference has DOI information
        has_doi = (reference.get('doi') or 
                  (reference.get('url') and ('doi.org' in reference['url'] or 'doi:' in reference['url'])) or
                  (reference.get('raw_text') and ('doi' in reference['raw_text'].lower())))
        return has_doi
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a non-arXiv reference using multiple APIs in priority order
        
        Args:
            reference: Reference data dictionary
            
        Returns:
            Tuple of (verified_data, errors, url)
        """
        # Strategy 1: Always try local database first (fastest)
        if self.local_db:
            verified_data, errors, url, success = self._try_api('local_db', self.local_db, reference)
            if success:
                return verified_data, errors, url
        
        # Strategy 2: If reference has DOI, prioritize CrossRef
        if self._should_try_doi_apis_first(reference) and self.crossref:
            verified_data, errors, url, success = self._try_api('crossref', self.crossref, reference)
            if success:
                return verified_data, errors, url
        
        # Strategy 3: Try Semantic Scholar API (reliable, good coverage)
        if self.semantic_scholar:
            verified_data, errors, url, success = self._try_api('semantic_scholar', self.semantic_scholar, reference)
            if success:
                return verified_data, errors, url
        
        # Strategy 4: Try OpenAlex API (excellent reliability, replaces Google Scholar)
        if self.openalex:
            verified_data, errors, url, success = self._try_api('openalex', self.openalex, reference)
            if success:
                return verified_data, errors, url
        
        # Strategy 5: Try CrossRef if we haven't already (for non-DOI references)
        if not self._should_try_doi_apis_first(reference) and self.crossref:
            verified_data, errors, url, success = self._try_api('crossref', self.crossref, reference)
            if success:
                return verified_data, errors, url
        
        # If all APIs failed, return unverified
        logger.debug("Enhanced Hybrid: All available APIs failed to verify reference")
        return None, [{
            'error_type': 'unverified',
            'error_details': 'Could not verify reference using any available API'
        }], None
    
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
            # Basic normalization if Semantic Scholar is not available
            import re
            title = re.sub(r'\s+', ' ', title.strip().lower())
            return re.sub(r'[^\w\s]', '', title)
    
    def compare_authors(self, cited_authors: List[str], correct_authors: List[Any]) -> Tuple[bool, str]:
        """
        Compare author lists (delegates to Semantic Scholar checker)
        """
        if self.semantic_scholar:
            return self.semantic_scholar.compare_authors(cited_authors, correct_authors)
        else:
            # Basic comparison if Semantic Scholar is not available
            return True, "Author comparison not available"

# Backward compatibility alias
HybridReferenceChecker = EnhancedHybridReferenceChecker