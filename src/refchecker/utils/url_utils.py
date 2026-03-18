#!/usr/bin/env python3
"""
URL Utilities for Reference Checking

This module provides utilities for URL construction, validation, and manipulation
related to academic references.
"""

import logging
import ipaddress
import re
import socket
from typing import List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from .doi_utils import normalize_doi

logger = logging.getLogger(__name__)

_PDF_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    'Accept': 'application/pdf,application/octet-stream;q=0.9,text/html;q=0.8,*/*;q=0.5',
    'Accept-Language': 'en-US,en;q=0.9',
}

_BLOCKED_HOSTS = {
    'localhost',
    'metadata',
    'metadata.google.internal',
}
_BLOCKED_HOST_SUFFIXES = (
    '.internal',
    '.local',
    '.localhost',
)
_MAX_REDIRECTS = 5


def _ensure_public_ip(ip_text: str) -> None:
    ip_obj = ipaddress.ip_address(ip_text)
    if not ip_obj.is_global:
        raise ValueError(f"Refusing to fetch non-public address: {ip_text}")


def validate_remote_fetch_url(url: str) -> str:
    """Validate that a URL points to a public HTTP(S) endpoint before fetching it."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or '').lower()
    if scheme not in {'http', 'https'}:
        raise ValueError("Only HTTP(S) URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")

    hostname = (parsed.hostname or '').rstrip('.').lower()
    if not hostname:
        raise ValueError("URL is missing a hostname")
    if hostname in _BLOCKED_HOSTS or hostname.endswith(_BLOCKED_HOST_SUFFIXES):
        raise ValueError(f"Refusing to fetch blocked host: {hostname}")

    try:
        ip_obj = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            addresses = {
                info[4][0]
                for info in socket.getaddrinfo(
                    hostname,
                    parsed.port or (443 if scheme == 'https' else 80),
                    type=socket.SOCK_STREAM,
                )
            }
        except socket.gaierror as exc:
            raise ValueError(f"Could not resolve host: {hostname}") from exc

        if not addresses:
            raise ValueError(f"Could not resolve host: {hostname}")
        for address in addresses:
            _ensure_public_ip(address)
    else:
        _ensure_public_ip(str(ip_obj))

    return url


def _is_redirect_response(status_code: int) -> bool:
    return status_code in {301, 302, 303, 307, 308}


def _build_pdf_candidate_urls(url: str) -> List[str]:
    """Build a list of candidate PDF download URLs for a given URL."""
    candidates = [url]
    if 'openreview.net/forum' in url:
        parsed = urlparse(url)
        paper_id = parse_qs(parsed.query).get('id', [None])[0]
        if paper_id:
            candidates.insert(0, f"https://openreview.net/pdf?id={paper_id}")
    return candidates


def download_pdf_bytes(url: str, timeout: int = 60) -> bytes:
    """Download a PDF from *url* with browser-like headers.

    Tries candidate URLs (e.g. OpenReview forum → pdf) in order and returns
    the raw PDF bytes on the first success.  Raises on failure.
    """
    headers = dict(_PDF_HEADERS)
    if 'openreview.net' in url.lower():
        headers['Referer'] = 'https://openreview.net/'

    candidates = _build_pdf_candidate_urls(url)

    last_exc: Optional[Exception] = None
    for candidate_url in dict.fromkeys(candidates):
        try:
            current_url = candidate_url
            with requests.Session() as session:
                for _ in range(_MAX_REDIRECTS + 1):
                    validate_remote_fetch_url(current_url)
                    response = session.get(
                        current_url,
                        timeout=timeout,
                        headers=headers,
                        allow_redirects=False,
                    )
                    if _is_redirect_response(response.status_code):
                        location = response.headers.get('location')
                        if not location:
                            response.raise_for_status()
                        current_url = urljoin(current_url, location)
                        continue
                    break
                else:
                    raise requests.exceptions.TooManyRedirects(f"Too many redirects for URL: {candidate_url}")

            response.raise_for_status()

            content_type = response.headers.get('content-type', '').lower()
            if 'application/pdf' not in content_type and not current_url.lower().endswith('.pdf'):
                logger.warning(f"URL might not be a PDF. Content-Type: {content_type}")

            return response.content
        except (requests.exceptions.RequestException, ValueError) as exc:
            last_exc = exc
            logger.error(f"Failed to download PDF from URL {candidate_url}: {exc}")

    raise last_exc  # type: ignore[misc]


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