"""
Reference checker implementations for different sources
"""

from .semantic_scholar import NonArxivReferenceChecker
from .local_semantic_scholar import LocalNonArxivReferenceChecker
from .enhanced_hybrid_checker import EnhancedHybridReferenceChecker
from .openalex import OpenAlexReferenceChecker
from .crossref import CrossRefReferenceChecker

__all__ = [
    "NonArxivReferenceChecker",
    "LocalNonArxivReferenceChecker",
    "EnhancedHybridReferenceChecker",
    "OpenAlexReferenceChecker", 
    "CrossRefReferenceChecker"
]