#!/usr/bin/env python3
"""
URL Utilities for Reference Checking

This module provides utilities for URL construction, validation, and manipulation
related to academic references.
"""

import re
from typing import Optional
from .doi_utils import normalize_doi


def construct_doi_url(doi: str) -> str:
    """
    Construct a proper DOI URL from a DOI string.
    
    Args:
        doi: DOI string
        
    Returns:
        Full DOI URL
    """
    if not doi:
        return ""
    
    # Normalize the DOI first
    normalized_doi = normalize_doi(doi)
    
    # Construct URL
    return f"https://doi.org/{normalized_doi}"


def extract_arxiv_id_from_url(url: str) -> Optional[str]:
    """
    Extract ArXiv ID from an ArXiv URL or text containing ArXiv reference.
    
    This is the common function that handles all ArXiv ID extraction patterns:
    - URLs: https://arxiv.org/abs/1234.5678, https://arxiv.org/pdf/1234.5678.pdf, https://arxiv.org/html/1234.5678
    - Text references: arXiv:1234.5678, arXiv preprint arXiv:1234.5678
    - Version handling: removes version numbers (v1, v2, etc.)
    
    Args:
        url: ArXiv URL or text containing ArXiv reference
        
    Returns:
        ArXiv ID (without version) if found, None otherwise
    """
    if not url or not isinstance(url, str):
        return None
    
    # Pattern 1: arXiv: format (e.g., "arXiv:1610.10099" or "arXiv preprint arXiv:1610.10099")
    arxiv_text_match = re.search(r'arXiv:(\d{4}\.\d{4,5})', url, re.IGNORECASE)
    if arxiv_text_match:
        arxiv_id = arxiv_text_match.group(1)
        # Remove version number if present
        return re.sub(r'v\d+$', '', arxiv_id)
    
    # Pattern 2: arxiv.org URLs (abs, pdf, html)
    # Handle URLs with version numbers and various formats
    arxiv_url_match = re.search(r'arxiv\.org/(?:abs|pdf|html)/([^\s/?#]+?)(?:\.pdf|v\d+)?(?:[?\#]|$)', url, re.IGNORECASE)
    if arxiv_url_match:
        arxiv_id = arxiv_url_match.group(1)
        # Remove version number if present
        return re.sub(r'v\d+$', '', arxiv_id)
    
    # Pattern 3: Fallback for simpler URL patterns
    fallback_match = re.search(r'arxiv\.org/(?:abs|pdf|html)/([^/?#]+)', url, re.IGNORECASE)
    if fallback_match:
        arxiv_id = fallback_match.group(1).replace('.pdf', '')
        # Remove version number if present
        return re.sub(r'v\d+$', '', arxiv_id)
    
    return None


def construct_arxiv_url(arxiv_id: str, url_type: str = "abs") -> str:
    """
    Construct an ArXiv URL from an ArXiv ID.
    
    Args:
        arxiv_id: ArXiv identifier
        url_type: Type of URL ('abs' for abstract, 'pdf' for PDF)
        
    Returns:
        Full ArXiv URL
    """
    if not arxiv_id:
        return ""
    
    # Remove version number if present for consistency
    clean_id = arxiv_id.replace('v1', '').replace('v2', '').replace('v3', '')
    
    if url_type == "pdf":
        return f"https://arxiv.org/pdf/{clean_id}.pdf"
    else:
        return f"https://arxiv.org/abs/{clean_id}"


def construct_semantic_scholar_url(paper_id: str) -> str:
    """
    Construct a Semantic Scholar URL from a paper ID.
    
    Args:
        paper_id: Semantic Scholar paper ID (SHA hash, NOT CorpusId)
                  The paperId is the 40-character hex hash that works in web URLs.
                  CorpusId (numeric) does NOT work in web URLs.
        
    Returns:
        Full Semantic Scholar URL
    """
    if not paper_id:
        return ""
    
    return f"https://www.semanticscholar.org/paper/{paper_id}"


def construct_openalex_url(work_id: str) -> str:
    """
    Construct an OpenAlex URL from a work ID.
    
    Args:
        work_id: OpenAlex work identifier
        
    Returns:
        Full OpenAlex URL
    """
    if not work_id:
        return ""
    
    # Remove prefix if present
    clean_id = work_id.replace('https://openalex.org/', '')
    
    return f"https://openalex.org/{clean_id}"


def construct_pubmed_url(pmid: str) -> str:
    """
    Construct a PubMed URL from a PMID.
    
    Args:
        pmid: PubMed identifier
        
    Returns:
        Full PubMed URL
    """
    if not pmid:
        return ""
    
    # Remove PMID prefix if present
    clean_pmid = pmid.replace('PMID:', '').strip()
    
    return f"https://pubmed.ncbi.nlm.nih.gov/{clean_pmid}/"


def get_best_available_url(external_ids: dict, open_access_pdf: Optional[str] = None, paper_id: Optional[str] = None) -> Optional[str]:
    """
    Get the best available URL from a paper's external IDs and open access information.
    Priority: Open Access PDF > DOI > ArXiv > Semantic Scholar > OpenAlex > PubMed
    
    Args:
        external_ids: Dictionary of external identifiers
        open_access_pdf: Open access PDF URL if available
        paper_id: Semantic Scholar paperId (SHA hash) if available
        
    Returns:
        Best available URL or None if no valid URL found
    """
    # Priority 1: Open access PDF
    if open_access_pdf:
        return open_access_pdf
    
    # Priority 2: DOI URL
    if external_ids.get('DOI'):
        return construct_doi_url(external_ids['DOI'])
    
    # Priority 3: ArXiv URL
    if external_ids.get('ArXiv'):
        return construct_arxiv_url(external_ids['ArXiv'])
    
    # Priority 4: Semantic Scholar URL (using paperId, not CorpusId)
    if paper_id:
        return construct_semantic_scholar_url(paper_id)
    
    # Priority 5: OpenAlex URL
    if external_ids.get('OpenAlex'):
        return construct_openalex_url(external_ids['OpenAlex'])
    
    # Priority 6: PubMed URL
    if external_ids.get('PubMed'):
        return construct_pubmed_url(external_ids['PubMed'])
    
    return None


def validate_url_format(url: str) -> bool:
    """
    Basic validation of URL format.
    
    Args:
        url: URL to validate
        
    Returns:
        True if URL appears to be valid, False otherwise
    """
    if not url:
        return False
    
    # Basic URL format check
    return url.startswith(('http://', 'https://')) and '.' in url


def clean_url(url: str) -> str:
    """
    Clean a URL by removing common issues like extra spaces, fragments, malformed LaTeX, etc.
    
    This function handles:
    - Whitespace trimming
    - Malformed LaTeX URL wrappers like \\url{https://...}
    - Markdown-style links like [text](url)
    - Trailing punctuation from academic references
    - DOI URL query parameter cleanup
    
    Args:
        url: URL to clean
        
    Returns:
        Cleaned URL
    """
    if not url:
        return ""
    
    # Remove leading/trailing whitespace
    url = url.strip()
    
    # Handle malformed URLs that contain \url{} wrappers within the URL text
    # e.g., "https://\url{https://www.example.com/}" -> "https://www.example.com/"
    import re
    url_pattern = r'https?://\\url\{(https?://[^}]+)\}'
    url_match = re.search(url_pattern, url)
    if url_match:
        url = url_match.group(1)
    
    # Handle markdown-style links like [text](url) or [url](url)
    # e.g., "[https://example.com](https://example.com)" -> "https://example.com"
    markdown_pattern = r'\[([^\]]*)\]\((https?://[^)]+)\)'
    markdown_match = re.search(markdown_pattern, url)
    if markdown_match:
        # Use the URL from parentheses
        url = markdown_match.group(2)
    
    # Remove trailing punctuation that's commonly part of sentence structure
    # but preserve legitimate URL characters
    url = url.rstrip('.,;!?)')
    
    # Note: Preserving query parameters for all URLs now
    # Previously this function removed query parameters for non-DOI URLs,
    # but this was causing issues with OpenReview and other URLs that need their parameters
    # Only remove query parameters for DOI URLs where they're typically not needed
    if '?' in url and 'doi.org' in url:
        base_url, params = url.split('?', 1)
        url = base_url
    
    return url


def clean_url_punctuation(url: str) -> str:
    """
    Clean trailing punctuation from URLs that often gets included during extraction.
    
    This function removes trailing punctuation that commonly gets extracted with URLs
    from academic references (periods, commas, semicolons, etc.) while preserving
    legitimate URL characters including query parameters.
    
    Args:
        url: URL string that may have trailing punctuation
        
    Returns:
        Cleaned URL with trailing punctuation removed
    """
    if not url:
        return ""
    
    # Remove leading/trailing whitespace
    url = url.strip()
    
    # Handle malformed URLs that contain \\url{} wrappers within the URL text
    # e.g., "https://\\url{https://www.example.com/}" -> "https://www.example.com/"
    import re
    url_pattern = r'https?://\\url\{(https?://[^}]+)\}'
    url_match = re.search(url_pattern, url)
    if url_match:
        url = url_match.group(1)
    
    # Handle markdown-style links like [text](url) or [url](url)
    # e.g., "[https://example.com](https://example.com)" -> "https://example.com"
    markdown_pattern = r'\[([^\]]*)\]\((https?://[^)]+)\)'
    markdown_match = re.search(markdown_pattern, url)
    if markdown_match:
        # Use the URL from parentheses
        url = markdown_match.group(2)
    
    # Remove trailing punctuation that's commonly part of sentence structure
    # but preserve legitimate URL characters
    url = url.rstrip('.,;!?)')
    
    return url