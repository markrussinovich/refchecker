import logging
from typing import Dict, List, Tuple, Optional, Any
from .semantic_scholar import NonArxivReferenceChecker
from .google_scholar import GoogleScholarReferenceChecker

logger = logging.getLogger(__name__)

class HybridReferenceChecker:
    """
    Hybrid reference checker that tries local database first, then Semantic Scholar API, then falls back to Google Scholar.
    This class is used for non-arXiv reference verification with intelligent source prioritization.
    """
    def __init__(self, semantic_scholar_api_key: Optional[str] = None, db_path: Optional[str] = None):
        self.semantic_scholar = NonArxivReferenceChecker(api_key=semantic_scholar_api_key)
        self.google_scholar = GoogleScholarReferenceChecker(semantic_scholar_api_key=semantic_scholar_api_key, db_path=db_path)
        
        # Initialize local database checker if available
        self.local_db = None
        if db_path:
            try:
                from .local_semantic_scholar import LocalNonArxivReferenceChecker
                self.local_db = LocalNonArxivReferenceChecker(db_path=db_path)
                logger.info(f"HybridReferenceChecker: Local database enabled at {db_path}")
            except Exception as e:
                logger.warning(f"HybridReferenceChecker: Failed to initialize local database: {e}")
                self.local_db = None

    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a non-arXiv reference using local database first, then Semantic Scholar API, then Google Scholar.

        Args:
            reference: Reference data dictionary

        Returns:
            Tuple of (verified_data, errors, url)
        """
        # Try local database first (fastest)
        if self.local_db:
            try:
                verified_data, errors, url = self.local_db.verify_reference(reference)
                # If local database found a match, return immediately
                if verified_data is not None:
                    logger.debug(f"HybridReferenceChecker: Found in local database")
                    return verified_data, errors, url
            except Exception as e:
                logger.warning(f"Local database failed: {e}")

        # Try Semantic Scholar API second
        try:
            verified_data, errors, url = self.semantic_scholar.verify_reference(reference)
            # If Semantic Scholar found a match or errors, return
            if verified_data is not None or errors:
                logger.debug(f"HybridReferenceChecker: Found in Semantic Scholar API")
                return verified_data, errors, url
        except Exception as e:
            logger.warning(f"Semantic Scholar API failed: {e}")

        # Fallback to Google Scholar (slowest, most unreliable)
        try:
            logger.debug(f"HybridReferenceChecker: Falling back to Google Scholar")
            verified_data, errors, url = self.google_scholar.verify_reference(reference)
            return verified_data, errors, url
        except Exception as e:
            logger.error(f"Google Scholar fallback also failed: {e}")
            return None, [{
                'error_type': 'unverified',
                'error_details': f'Could not verify reference using local database, Semantic Scholar, or Google Scholar: {e}'
            }], None

    def normalize_paper_title(self, title: str) -> str:
        """
        Normalize paper title for comparison (delegates to Semantic Scholar checker)
        """
        return self.semantic_scholar.normalize_paper_title(title)

    def compare_authors(self, cited_authors: List[str], correct_authors: List[Any]) -> Tuple[bool, str]:
        """
        Compare author lists (delegates to Semantic Scholar checker)
        """
        return self.semantic_scholar.compare_authors(cited_authors, correct_authors) 