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
    
    Args:
        doi1: First DOI to compare
        doi2: Second DOI to compare
        
    Returns:
        True if DOIs are equivalent, False otherwise
    """
    if not doi1 or not doi2:
        return False
    
    # Normalize both DOIs (already converted to lowercase)
    norm_doi1 = normalize_doi(doi1)
    norm_doi2 = normalize_doi(doi2)

    # If DOIs are identical, they match
    if norm_doi1 == norm_doi2:
        return True

    # Check if first two components match (publisher.registrant)
    doi1_parts = norm_doi1.split('.')
    doi2_parts = norm_doi2.split('.')

    if len(doi1_parts) >= 2 and len(doi2_parts) >= 2:
        return doi1_parts[0] == doi2_parts[0] and doi1_parts[1].split('/')[0] == doi2_parts[1].split('/')[0]
    
    return norm_doi1 == norm_doi2


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