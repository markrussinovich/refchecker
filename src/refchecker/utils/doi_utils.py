#!/usr/bin/env python3
"""
DOI Utilities for Reference Checking

This module provides utilities for DOI handling, extraction, and validation.
"""

import re
from typing import Optional


def extract_doi_from_url(url: str) -> Optional[str]:
    """
    Extract DOI from a URL using comprehensive pattern matching.
    
    Args:
        url: URL that might contain a DOI
        
    Returns:
        Extracted DOI or None if not found
    """
    if not url:
        return None
    
    # Only extract DOIs from actual DOI URLs, not from other domains
    # This prevents false positives from URLs like aclanthology.org
    if 'doi.org' not in url and 'doi:' not in url:
        return None
    
    # DOI patterns ordered by specificity and reliability
    doi_patterns = [
        r'doi\.org/([^/\s\?#]+(?:/[^/\s\?#]+)*)',  # Full DOI pattern from doi.org
        r'doi:([^/\s\?#]+(?:/[^/\s\?#]+)*)',       # doi: prefix format
    ]
    
    for pattern in doi_patterns:
        match = re.search(pattern, url)
        if match:
            doi_candidate = match.group(1)
            # DOIs must start with "10." and have at least one slash
            if doi_candidate.startswith('10.') and '/' in doi_candidate and len(doi_candidate) > 6:
                return doi_candidate
    
    return None


def normalize_doi(doi: str) -> str:
    """
    Normalize a DOI by removing common prefixes, cleaning whitespace, and converting to lowercase.
    
    DOI suffixes are case-insensitive according to the DOI specification, so we normalize 
    to lowercase to ensure consistent URL generation across all checkers.
    
    Args:
        doi: DOI string to normalize
        
    Returns:
        Normalized DOI string in lowercase
    """
    if not doi:
        return ""
    
    # Remove common URL prefixes
    normalized = doi.replace('https://doi.org/', '').replace('http://doi.org/', '')
    normalized = normalized.replace('doi:', '')
    
    # Remove hash fragments and query parameters
    normalized = normalized.split('#')[0].split('?')[0]
    
    # Clean whitespace and trailing punctuation
    normalized = normalized.strip()
    
    # Remove trailing punctuation that might be included in extraction
    normalized = normalized.rstrip('.,;:)')
    
    # Convert to lowercase for consistency (DOI suffixes are case-insensitive)
    return normalized.lower()


def is_valid_doi_format(doi: str) -> bool:
    """
    Check if a string matches the basic DOI format.
    
    Args:
        doi: String to validate as DOI
        
    Returns:
        True if the string matches DOI format, False otherwise
    """
    if not doi:
        return False
    
    # Basic DOI format: starts with "10." followed by at least one slash
    doi_format_pattern = r'^10\.\d+/.+'
    return bool(re.match(doi_format_pattern, doi))


def compare_dois(doi1: str, doi2: str) -> bool:
    """
    Compare two DOIs for equality, handling different formats and prefixes.
    
    This function performs exact matching after normalization, with support
    for partial DOI citations where a shorter DOI is a valid prefix of a longer one.
    
    Args:
        doi1: First DOI to compare
        doi2: Second DOI to compare
        
    Returns:
        True if DOIs are equivalent, False otherwise
    """
    if not doi1 or not doi2:
        return False
    
    # Normalize both DOIs (handles prefixes, case, punctuation)
    norm_doi1 = normalize_doi(doi1)
    norm_doi2 = normalize_doi(doi2)

    # First try exact match
    if norm_doi1 == norm_doi2:
        return True
    
    # Handle partial DOI citations - if one DOI is a prefix of the other, consider it a match
    # This handles cases like "10.1007" being cited instead of the full "10.1007/s10458-025-09691-y"
    if len(norm_doi1) != len(norm_doi2):
        shorter_doi = norm_doi1 if len(norm_doi1) < len(norm_doi2) else norm_doi2
        longer_doi = norm_doi2 if len(norm_doi1) < len(norm_doi2) else norm_doi1
        
        # Only consider it a valid partial match if:
        # 1. The shorter DOI is at least 7 characters (e.g., "10.1007")
        # 2. The longer DOI starts with the shorter DOI
        # 3. The next character in the longer DOI is '/' or '.' (valid DOI separators)
        if (len(shorter_doi) >= 7 and 
            longer_doi.startswith(shorter_doi) and 
            len(longer_doi) > len(shorter_doi) and
            longer_doi[len(shorter_doi)] in ['/', '.']):
            return True
    
    return False


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


def validate_doi_resolves(doi: str, timeout: float = 5.0) -> bool:
    """
    Validate that a DOI resolves by checking if doi.org returns a redirect.
    
    This is useful for determining if a DOI is valid, even if it's different
    from what a verification source has stored (e.g., arXiv DOI vs conference DOI).
    
    Args:
        doi: DOI string to validate
        timeout: Request timeout in seconds
        
    Returns:
        True if DOI resolves (returns 302/301/200), False otherwise
    """
    if not doi or not is_valid_doi_format(normalize_doi(doi)):
        return False
    
    try:
        import requests
        url = construct_doi_url(doi)
        # Use HEAD request first (faster), fall back to GET if needed
        response = requests.head(url, allow_redirects=False, timeout=timeout)
        # DOI.org returns 302 for valid DOIs that redirect to the paper
        # Some may return 301 (permanent redirect) or 200 (direct response)
        return response.status_code in (200, 301, 302, 303, 307, 308)
    except Exception:
        # On any error (timeout, connection error, etc.), assume DOI might be valid
        # to avoid false negatives due to network issues
        return True