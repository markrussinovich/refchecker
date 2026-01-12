#!/usr/bin/env python3
"""
OpenAlex API Client for Reference Verification

This module provides functionality to verify non-arXiv references using the OpenAlex API.
It can check if a reference's metadata (authors, year, title) matches what's in the OpenAlex database.

OpenAlex is a comprehensive database of scholarly papers, authors, venues, institutions, and concepts.
It provides free access to over 240 million research outputs with excellent coverage across all disciplines.

Usage:
    from openalex import OpenAlexReferenceChecker
    
    # Initialize the checker
    checker = OpenAlexReferenceChecker(email="your@email.com")  # Email for polite pool
    
    # Verify a reference
    reference = {
        'title': 'Title of the paper',
        'authors': ['Author 1', 'Author 2'],
        'year': 2020,
        'url': 'https://example.com/paper',
        'raw_text': 'Full citation text'
    }
    
    verified_data, errors, url = checker.verify_reference(reference)
"""

import requests
import time
import logging
import re
from typing import Dict, List, Tuple, Optional, Any, Union
from urllib.parse import quote_plus
from refchecker.utils.text_utils import normalize_text, clean_title_basic, find_best_match, is_name_match, compare_authors, clean_title_for_search
from refchecker.utils.error_utils import format_year_mismatch, format_doi_mismatch
from refchecker.config.settings import get_config

# Set up logging
logger = logging.getLogger(__name__)

# Get configuration
config = get_config()
SIMILARITY_THRESHOLD = config["text_processing"]["similarity_threshold"]

class OpenAlexReferenceChecker:
    """
    A class to verify non-arXiv references using the OpenAlex API
    """
    
    def __init__(self, email: Optional[str] = None):
        """
        Initialize the OpenAlex API client
        
        Args:
            email: Optional email for polite pool access (better performance)
        """
        self.base_url = "https://api.openalex.org"
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "RefChecker/1.0.0 (https://github.com/markrussinovich/refchecker)"
        }
        
        # Add email to headers for polite pool access
        if email:
            self.headers["User-Agent"] += f" mailto:{email}"
        
        # Rate limiting parameters - OpenAlex allows 10 requests per second
        self.request_delay = 0.1  # 100ms between requests (10 req/sec)
        self.max_retries = 3
        self.backoff_factor = 2  # Exponential backoff factor
    
    def search_works(self, query: str, year: Optional[int] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Search for works matching the query
        
        Args:
            query: Search query (title, authors, etc.)
            year: Publication year to filter by
            limit: Maximum number of results to return
            
        Returns:
            List of work data dictionaries
        """
        endpoint = f"{self.base_url}/works"
        
        # Build query parameters - OpenAlex uses a flexible search syntax
        params = {
            "search": query,
            "per_page": min(limit, 25),  # OpenAlex max per page is 200, but we limit for performance
            "select": "id,doi,title,display_name,publication_year,authorships,type,open_access,primary_location,locations,referenced_works,ids"
        }
        
        # Add year filter if provided
        if year:
            params["filter"] = f"publication_year:{year}"
        
        # Make the request with retries and backoff
        for attempt in range(self.max_retries):
            try:            
                response = requests.get(endpoint, headers=self.headers, params=params, timeout=30)
                
                # Check for rate limiting (OpenAlex returns 429 for rate limits)
                if response.status_code == 429:
                    wait_time = self.request_delay * (self.backoff_factor ** attempt) + 1
                    logger.debug(f"OpenAlex rate limit exceeded. Retrying in {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
                    continue
                
                # Check for other errors
                response.raise_for_status()
                
                # Parse the response
                data = response.json()
                results = data.get('results', [])
                
                logger.debug(f"OpenAlex search returned {len(results)} results for query: {query[:50]}...")
                return results
                
            except requests.exceptions.RequestException as e:
                wait_time = self.request_delay * (self.backoff_factor ** attempt) + 1
                logger.debug(f"OpenAlex request failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
        
        # If we get here, all retries failed
        logger.debug(f"Failed to search OpenAlex after {self.max_retries} attempts")
        return []
    
    def get_work_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        Get work data by DOI
        
        Args:
            doi: DOI of the work
            
        Returns:
            Work data dictionary or None if not found
        """
        # Clean DOI - remove any prefixes
        clean_doi = doi
        if doi.startswith('doi:'):
            clean_doi = doi[4:]
        if doi.startswith('https://doi.org/'):
            clean_doi = doi[16:]
        if doi.startswith('http://doi.org/'):
            clean_doi = doi[15:]
        
        endpoint = f"{self.base_url}/works/doi:{clean_doi}"
        
        params = {
            "select": "id,doi,title,display_name,publication_year,authorships,type,open_access,primary_location,locations,referenced_works,ids"
        }
        
        # Make the request with retries and backoff
        for attempt in range(self.max_retries):
            try:
                # Add delay to respect rate limits
                time.sleep(self.request_delay)
                
                response = requests.get(endpoint, headers=self.headers, params=params, timeout=30)
                
                # Check for rate limiting
                if response.status_code == 429:
                    wait_time = self.request_delay * (self.backoff_factor ** attempt) + 1
                    logger.debug(f"OpenAlex rate limit exceeded. Retrying in {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
                    continue
                
                # If not found, return None
                if response.status_code == 404:
                    logger.debug(f"Work with DOI {doi} not found in OpenAlex")
                    return None
                
                # Check for other errors
                response.raise_for_status()
                
                # Parse the response
                work_data = response.json()
                logger.debug(f"Found work by DOI in OpenAlex: {doi}")
                return work_data
                
            except requests.exceptions.RequestException as e:
                wait_time = self.request_delay * (self.backoff_factor ** attempt) + 1
                logger.debug(f"OpenAlex request failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
        
        # If we get here, all retries failed
        logger.error(f"Failed to get work by DOI from OpenAlex after {self.max_retries} attempts")
        return None
    
    def extract_doi_from_url(self, url: str) -> Optional[str]:
        """
        Extract DOI from a URL
        
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
        
        # Check if it's a DOI URL
        doi_patterns = [
            r'doi\.org/([^/\s\?#]+(?:/[^/\s\?#]+)*)',  # Full DOI pattern
            r'doi:([^/\s\?#]+(?:/[^/\s\?#]+)*)',       # doi: prefix
        ]
        
        for pattern in doi_patterns:
            match = re.search(pattern, url)
            if match:
                doi_candidate = match.group(1)
                # DOIs must start with "10." and have at least one slash
                if doi_candidate.startswith('10.') and '/' in doi_candidate and len(doi_candidate) > 6:
                    return doi_candidate
        
        return None
    
    def normalize_author_name(self, name: str) -> str:
        """
        Normalize author name for comparison
        
        Args:
            name: Author name
            
        Returns:
            Normalized name
        """
        # Remove reference numbers (e.g., "[1]")
        name = re.sub(r'^\[\d+\]', '', name)
        
        # Use common normalization function
        return normalize_text(name)
    
    def compare_authors(self, cited_authors: List[str], openalex_authors: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Compare author lists to check if they match (delegates to shared utility)
        
        Args:
            cited_authors: List of author names as cited
            openalex_authors: List of authorship data from OpenAlex
            
        Returns:
            Tuple of (match_result, error_message)
        """
        # Extract author names from OpenAlex data for the shared utility
        author_dicts = []
        for authorship in openalex_authors:
            author = authorship.get('author', {})
            display_name = author.get('display_name', '')
            if display_name:
                author_dicts.append({'name': display_name})
        
        return compare_authors(cited_authors, author_dicts)
    
    def is_name_match(self, name1: str, name2: str) -> bool:
        """
        Check if two author names match, allowing for variations
        
        Args:
            name1: First author name (normalized)
            name2: Second author name (normalized)
            
        Returns:
            True if names match, False otherwise
        """
        # Exact match
        if name1 == name2:
            return True
        
        # If one is a substring of the other, consider it a match
        if name1 in name2 or name2 in name1:
            return True
        
        # Split into parts (first name, last name, etc.)
        parts1 = name1.split()
        parts2 = name2.split()
        
        if not parts1 or not parts2:
            return False
        
        # If either name has only one part, compare directly
        if len(parts1) == 1 or len(parts2) == 1:
            return parts1[-1] == parts2[-1]  # Compare last parts (last names)
        
        # Compare last names (last parts)
        if parts1[-1] != parts2[-1]:
            return False
        
        # Compare first initials
        if len(parts1[0]) > 0 and len(parts2[0]) > 0 and parts1[0][0] != parts2[0][0]:
            return False
        
        return True
    
    def extract_url_from_work(self, work_data: Dict[str, Any]) -> Optional[str]:
        """
        Extract the best URL from OpenAlex work data
        
        Args:
            work_data: Work data from OpenAlex
            
        Returns:
            Best available URL or None
        """
        # Priority order: Open access PDF, primary location, DOI
        
        # Check for open access PDF
        open_access = work_data.get('open_access', {})
        if open_access.get('is_oa') and open_access.get('oa_url'):
            logger.debug(f"Found open access URL: {open_access['oa_url']}")
            return open_access['oa_url']
        
        # Check primary location
        primary_location = work_data.get('primary_location', {})
        if primary_location:
            # Try landing page URL first
            if primary_location.get('landing_page_url'):
                logger.debug(f"Found primary location URL: {primary_location['landing_page_url']}")
                return primary_location['landing_page_url']
            
            # Try PDF URL
            if primary_location.get('pdf_url'):
                logger.debug(f"Found primary location PDF: {primary_location['pdf_url']}")
                return primary_location['pdf_url']
        
        # Check other locations for PDFs
        locations = work_data.get('locations', [])
        for location in locations:
            if location.get('pdf_url'):
                logger.debug(f"Found PDF in location: {location['pdf_url']}")
                return location['pdf_url']
            if location.get('landing_page_url'):
                logger.debug(f"Found landing page in location: {location['landing_page_url']}")
                return location['landing_page_url']
        
        # Fall back to DOI URL
        doi = work_data.get('doi')
        if doi:
            from refchecker.utils.doi_utils import construct_doi_url
            doi_url = construct_doi_url(doi)
            logger.debug(f"Generated DOI URL: {doi_url}")
            return doi_url
        
        # Check ids for other identifiers
        ids = work_data.get('ids', {})
        if ids.get('doi'):
            from refchecker.utils.doi_utils import construct_doi_url
            doi_url = construct_doi_url(ids['doi'])
            logger.debug(f"Generated DOI URL from ids: {doi_url}")
            return doi_url
        
        logger.debug("No URL found in OpenAlex work data")
        return None
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a non-arXiv reference using OpenAlex
        
        Args:
            reference: Reference data dictionary
            
        Returns:
            Tuple of (verified_data, errors, url)
            - verified_data: Work data from OpenAlex or None if not found
            - errors: List of error dictionaries
            - url: URL of the work if found, None otherwise
        """
        errors = []
        
        # Extract reference data
        title = reference.get('title', '') or ''
        authors = reference.get('authors', [])
        year = reference.get('year', 0)
        url = reference.get('url', '')
        raw_text = reference.get('raw_text', '')
        
        # If we have a DOI, try to get the work directly
        doi = None
        if 'doi' in reference and reference['doi']:
            doi = reference['doi']
        elif url:
            doi = self.extract_doi_from_url(url)
        
        work_data = None
        
        if doi:
            # Try to get the work by DOI
            work_data = self.get_work_by_doi(doi)
            
            if work_data:
                logger.debug(f"Found work by DOI in OpenAlex: {doi}")
            else:
                logger.debug(f"Could not find work with DOI in OpenAlex: {doi}")
        
        # If we couldn't get the work by DOI, try searching by title
        if not work_data and title:
            # Clean up the title for search using centralized utility function
            cleaned_title = clean_title_for_search(title)
            
            # Search for the work
            search_results = self.search_works(cleaned_title, year)
            
            if search_results:
                best_match, best_score = find_best_match(search_results, cleaned_title, year, authors)
                
                # Use match if score is good enough
                if best_match and best_score >= SIMILARITY_THRESHOLD:
                    work_data = best_match
                    logger.debug(f"Found work by title in OpenAlex with score {best_score:.2f}: {cleaned_title}")
                else:
                    logger.debug(f"No good title match found in OpenAlex (best score: {best_score:.2f})")
            else:
                logger.debug(f"No works found for title in OpenAlex: {cleaned_title}")
        
        # If we still couldn't find the work, return no verification
        if not work_data:
            logger.debug("Could not find matching work in OpenAlex")
            return None, [], None
        
        # Verify authors
        if authors:
            authorships = work_data.get('authorships', [])
            authors_match, author_error = self.compare_authors(authors, authorships)
            
            if not authors_match:
                # Extract correct author names for error reporting
                correct_author_names = []
                for authorship in authorships:
                    author = authorship.get('author', {})
                    display_name = author.get('display_name', '')
                    if display_name:
                        correct_author_names.append(display_name)
                
                errors.append({
                    'error_type': 'author',
                    'error_details': author_error,
                    'ref_authors_correct': ', '.join(correct_author_names)
                })
        
        # Verify year
        work_year = work_data.get('publication_year')
        if year and work_year and year != work_year:
            errors.append({
                'warning_type': 'year',
                'warning_details': format_year_mismatch(year, work_year),
                'ref_year_correct': work_year
            })
        
        # Verify DOI
        work_doi = work_data.get('doi')
        if not work_doi and work_data.get('ids', {}).get('doi'):
            work_doi = work_data['ids']['doi']
        
        if doi and work_doi:
            # Compare DOIs using the proper comparison function
            from refchecker.utils.doi_utils import compare_dois, validate_doi_resolves
            if not compare_dois(doi, work_doi):
                # If cited DOI resolves, it's likely a valid alternate DOI (e.g., arXiv vs conference)
                # Treat as warning instead of error
                if validate_doi_resolves(doi):
                    errors.append({
                        'warning_type': 'doi',
                        'warning_details': format_doi_mismatch(doi, work_doi),
                        'ref_doi_correct': work_doi
                    })
                else:
                    errors.append({
                        'error_type': 'doi',
                        'error_details': format_doi_mismatch(doi, work_doi),
                        'ref_doi_correct': work_doi
                    })
        
        # Extract URL from work data
        work_url = self.extract_url_from_work(work_data)
        
        return work_data, errors, work_url

if __name__ == "__main__":
    # Example usage
    checker = OpenAlexReferenceChecker(email="test@example.com")
    
    # Example reference
    reference = {
        'title': 'Attention is All You Need',
        'authors': ['Ashish Vaswani', 'Noam Shazeer'],
        'year': 2017,
        'url': 'https://example.com/paper',
        'raw_text': 'Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., ... & Polosukhin, I. (2017). Attention is all you need. Advances in neural information processing systems, 30.'
    }
    
    # Verify the reference
    verified_data, errors, url = checker.verify_reference(reference)
    
    if verified_data:
        print(f"Found work: {verified_data.get('title') or verified_data.get('display_name')}")
        print(f"URL: {url}")
        
        if errors:
            print("Errors found:")
            for error in errors:
                error_type = error.get('error_type') or error.get('warning_type')
                print(f"  - {error_type}: {error.get('error_details') or error.get('warning_details')}")
        else:
            print("No errors found")
    else:
        print("Could not find matching work")