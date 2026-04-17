"""
Reference checker implementations for different sources
"""

from .semantic_scholar import NonArxivReferenceChecker
from .local_semantic_scholar import LocalNonArxivReferenceChecker
from .enhanced_hybrid_checker import EnhancedHybridReferenceChecker
from .openalex import OpenAlexReferenceChecker
from .crossref import CrossRefReferenceChecker
from .arxiv_citation import ArXivCitationChecker
from .acl_anthology import ACLAnthologyReferenceChecker

__all__ = [
    "NonArxivReferenceChecker",
    "LocalNonArxivReferenceChecker",
    "EnhancedHybridReferenceChecker",
    "OpenAlexReferenceChecker", 
    "CrossRefReferenceChecker",
    "ArXivCitationChecker",
    "ACLAnthologyReferenceChecker",
]