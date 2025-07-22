#!/usr/bin/env python3
"""
Semantic Scholar API Client for Reference Verification

This module provides functionality to verify non-arXiv references using the Semantic Scholar API.
It can check if a reference's metadata (authors, year, title) matches what's in the Semantic Scholar database.

Usage:
    from semantic_scholar import NonArxivReferenceChecker
    
    # Initialize the checker
    checker = NonArxivReferenceChecker(api_key="your_api_key")  # API key is optional
    
    # Verify a reference
    reference = {
        'title': 'Title of the paper',
        'authors': ['Author 1', 'Author 2'],
        'year': 2020,
        'url': 'https://example.com/paper',
        'raw_text': 'Full citation text'
    }
    
    verified_data, errors = checker.verify_reference(reference)
"""

import requests
import time
import logging
import re
from typing import Dict, List, Tuple, Optional, Any, Union
from utils.text_utils import normalize_text, clean_title_basic, find_best_match, is_name_match

# Set up logging
logger = logging.getLogger(__name__)

class NonArxivReferenceChecker:
    """
    A class to verify non-arXiv references using the Semantic Scholar API
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Semantic Scholar API client
        
        Args:
            api_key: Optional API key for Semantic Scholar (increases rate limits)
        """
        self.base_url = "https://api.semanticscholar.org/graph/v1"
        self.headers = {
            "Accept": "application/json"
        }
        
        if api_key:
            self.headers["x-api-key"] = api_key
        
        # Rate limiting parameters
        self.request_delay = 1.0  # Initial delay between requests (seconds)
        self.max_retries = 5
        self.backoff_factor = 2  # Exponential backoff factor
    
    def search_paper(self, query: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Search for papers matching the query
        
        Args:
            query: Search query (title, authors, etc.)
            year: Publication year to filter by
            
        Returns:
            List of paper data dictionaries
        """
        endpoint = f"{self.base_url}/paper/search"
        
        # Build query parameters
        params = {
            "query": query,
            "limit": 10,
            "fields": "title,authors,year,externalIds,url,abstract,openAccessPdf,isOpenAccess,venue,journal"
        }
        
        # Make the request with retries and backoff
        for attempt in range(self.max_retries):
            try:
                response = requests.get(endpoint, headers=self.headers, params=params)
                
                # Check for rate limiting
                if response.status_code == 429:
                    wait_time = self.request_delay * (self.backoff_factor ** attempt)
                    logger.debug(f"Rate limit exceeded. Increasing delay and retrying...")
                    time.sleep(wait_time)
                    continue
                
                # Check for other errors
                response.raise_for_status()
                
                # Parse the response
                data = response.json()
                return data.get('data', [])
                
            except requests.exceptions.RequestException as e:
                wait_time = self.request_delay * (self.backoff_factor ** attempt)
                logger.warning(f"Request failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
        
        # If we get here, all retries failed
        logger.debug(f"Failed to search for paper after {self.max_retries} attempts")
        return []
    
    def get_paper_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        Get paper data by DOI
        
        Args:
            doi: DOI of the paper
            
        Returns:
            Paper data dictionary or None if not found
        """
        endpoint = f"{self.base_url}/paper/DOI:{doi}"
        
        params = {
            "fields": "title,authors,year,externalIds,url,abstract,openAccessPdf,isOpenAccess,venue,journal"
        }
        
        # Make the request with retries and backoff
        for attempt in range(self.max_retries):
            try:
                response = requests.get(endpoint, headers=self.headers, params=params)
                
                # Check for rate limiting
                if response.status_code == 429:
                    wait_time = self.request_delay * (self.backoff_factor ** attempt)
                    logger.debug(f"Rate limit exceeded. Increasing delay and retrying...")
                    time.sleep(wait_time)
                    continue
                
                # If not found, return None
                if response.status_code == 404:
                    logger.warning(f"Paper with DOI {doi} not found")
                    return None
                
                # Check for other errors
                response.raise_for_status()
                
                # Parse the response
                return response.json()
                
            except requests.exceptions.RequestException as e:
                wait_time = self.request_delay * (self.backoff_factor ** attempt)
                logger.warning(f"Request failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
        
        # If we get here, all retries failed
        logger.error(f"Failed to get paper by DOI after {self.max_retries} attempts")
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
        
        # Check if it's a DOI URL
        if 'doi.org' in url:
            # Extract the DOI part after doi.org/
            match = re.search(r'doi\.org/([^/\s]+)', url)
            if match:
                return match.group(1)
        
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
    
    def compare_authors(self, cited_authors: List[str], correct_authors: List[Dict[str, str]]) -> Tuple[bool, str]:
        """
        Compare author lists to check if they match
        
        Args:
            cited_authors: List of author names as cited
            correct_authors: List of author data from Semantic Scholar
            
        Returns:
            Tuple of (match_result, error_message)
        """
        # Extract author names from Semantic Scholar data
        correct_names = [author.get('name', '') for author in correct_authors]
        
        # Normalize names for comparison
        normalized_cited = [self.normalize_author_name(name) for name in cited_authors]
        normalized_correct = [self.normalize_author_name(name) for name in correct_names]
        
        # If the cited list is much shorter, it might be using "et al."
        # In this case, just check the authors that are listed
        if len(normalized_cited) < len(normalized_correct) and len(normalized_cited) <= 3:
            # Only compare the first few authors
            normalized_correct = normalized_correct[:len(normalized_cited)]
        
        # Compare first author (most important) using the improved utility function
        if normalized_cited and normalized_correct:
            if not is_name_match(normalized_cited[0], normalized_correct[0]):
                return False, f"First author mismatch: '{cited_authors[0]}' vs '{correct_names[0]}'"
        
        return True, "Authors match"
    
    def is_name_match(self, name1: str, name2: str) -> bool:
        """
        Check if two author names match, allowing for variations
        
        Args:
            name1: First author name
            name2: Second author name
            
        Returns:
            True if names match, False otherwise
        """
        # If one is a substring of the other, consider it a match
        if name1 in name2 or name2 in name1:
            return True
        
        # Split into parts (first name, last name, etc.)
        parts1 = name1.split()
        parts2 = name2.split()
        
        # If either name has only one part, compare directly
        if len(parts1) == 1 or len(parts2) == 1:
            return parts1[-1] == parts2[-1]  # Compare last parts (last names)
        
        # Compare last names (last parts)
        if parts1[-1] != parts2[-1]:
            return False
        
        # Compare first initials
        if parts1[0][0] != parts2[0][0]:
            return False
        
        return True
    
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a non-arXiv reference using Semantic Scholar
        
        Args:
            reference: Reference data dictionary
            
        Returns:
            Tuple of (verified_data, errors, url)
            - verified_data: Paper data from Semantic Scholar or None if not found
            - errors: List of error dictionaries
            - url: URL of the paper if found, None otherwise
        """
        errors = []
        
        # Extract reference data
        title = reference.get('title', '')
        authors = reference.get('authors', [])
        year = reference.get('year', 0)
        url = reference.get('url', '')
        raw_text = reference.get('raw_text', '')
        
        # If we have a DOI, try to get the paper directly
        doi = None
        if 'doi' in reference and reference['doi']:
            doi = reference['doi']
        elif url:
            doi = self.extract_doi_from_url(url)
        
        paper_data = None
        
        if doi:
            # Try to get the paper by DOI
            paper_data = self.get_paper_by_doi(doi)
            
            if paper_data:
                logger.info(f"Found paper by DOI: {doi}")
            else:
                logger.warning(f"Could not find paper with DOI: {doi}")
        
        # If we couldn't get the paper by DOI, try searching by title
        found_title = ''
        if not paper_data and title:
            # Clean up the title
            cleaned_title = clean_title_basic(title)
            
            # Search for the paper
            search_results = self.search_paper(cleaned_title, year)
            
            if search_results:
                best_match, best_score = find_best_match(search_results, cleaned_title, year)
                
                # Consider it a match if similarity is above threshold (0.8)
                if best_match and best_score >= 0.8:
                    paper_data = best_match
                    found_title = best_match['title']
                    logger.debug(f"Found paper by title with similarity {best_score:.2f}: {cleaned_title}")
                else:
                    logger.debug(f"No good match found for title: {cleaned_title}")
            else:
                logger.debug(f"No papers found for title: {cleaned_title}")
        
        # If we still couldn't find the paper, try searching by the raw text
        if not paper_data and raw_text:
            # Extract a reasonable search query from the raw text
            # This is a simple approach - could be improved
            search_query = raw_text.replace('\n', ' ').strip()
            
            # Search for the paper
            search_results = self.search_paper(search_query)
            
            if search_results:
                # Take the first result as a best guess
                paper_data = search_results[0]
                logger.debug(f"Found paper by raw text search")
            else:
                logger.debug(f"No papers found for raw text search")
        
        # If we couldn't find the paper, return no errors (can't verify)
        if not paper_data:
            logger.debug(f"Could not find matching paper for reference")
            return None, [], None
        
        # Check title for exact case insensitive match between found_title and paper title
        if found_title and title.lower() != clean_title_basic(found_title.lower()):
            errors.append({
                'error_type': 'title',
                'error_details': f"Title mismatch: cited as '{title}' but actually '{found_title}'",
                'ref_title_correct': paper_data.get('title', '')
            })
        
        # Verify authors
        if authors:
            authors_match, author_error = self.compare_authors(authors, paper_data.get('authors', []))
            
            if not authors_match:
                errors.append({
                    'error_type': 'author',
                    'error_details': author_error,
                    'ref_authors_correct': ', '.join([author.get('name', '') for author in paper_data.get('authors', [])])
                })
        
        # Verify year
        paper_year = paper_data.get('year')
        if year and paper_year and year != paper_year:
            errors.append({
                'warning_type': 'year',
                'warning_details': f"Year mismatch: cited as {year} but actually {paper_year}",
                'ref_year_correct': paper_year
            })
        
        # Verify venue
        cited_venue = reference.get('journal', '') or reference.get('venue', '')
        paper_venue = paper_data.get('venue') or paper_data.get('journal')
        
        if cited_venue and paper_venue:
            # Normalize venues for comparison - remove year prefixes and normalize case/punctuation
            def normalize_venue(venue):
                # Remove year prefixes (e.g., "2012 Brazilian Symposium" -> "Brazilian Symposium")
                venue_clean = re.sub(r'^\d{4}\s+', '', venue.strip())
                # Remove ordinal numbers (e.g., "XVIII Workshop" -> "Workshop") 
                venue_clean = re.sub(r'\b(XVIII|XVII|XVI|XV|XIV|XIII|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I|\d+(?:st|nd|rd|th))\s+', '', venue_clean)
                # Remove acronyms in parentheses (e.g., "ACM Transactions on Computer Systems (TOCS)" -> "ACM Transactions on Computer Systems")
                venue_clean = re.sub(r'\s*\([A-Z0-9&]+\)\s*', ' ', venue_clean)
                # Remove "Proceedings of" prefixes
                venue_clean = re.sub(r'^proceedings\s+of\s+(the\s+)?', '', venue_clean, flags=re.IGNORECASE)
                # Normalize case and punctuation
                venue_clean = venue_clean.lower()
                # Remove extra punctuation and normalize spaces
                venue_clean = re.sub(r'[^\w\s]', ' ', venue_clean)
                venue_clean = re.sub(r'\s+', ' ', venue_clean).strip()
                return venue_clean
            
            cited_normalized = normalize_venue(cited_venue)
            paper_normalized = normalize_venue(paper_venue)
            
            # Check if venues are substantially different (not just minor variations)
            def venues_substantially_different(venue1, venue2):
                # If one venue is a subset of the other with high overlap, consider them the same
                words1 = set(venue1.split())
                words2 = set(venue2.split())
                
                # Calculate Jaccard similarity (intersection over union)
                intersection = len(words1.intersection(words2))
                union = len(words1.union(words2))
                
                if union == 0:
                    return venue1 != venue2
                
                jaccard_similarity = intersection / union
                
                # If venues have high word overlap (80%+), consider them the same
                # This handles cases like "ACM SIGACT-SIGMOD" vs "ACM SIGACT-SIGMOD-SIGART"
                return jaccard_similarity < 0.8
            
            if cited_normalized != paper_normalized and venues_substantially_different(cited_normalized, paper_normalized):
                errors.append({
                    'warning_type': 'venue',
                    'warning_details': f"Venue mismatch: cited as '{cited_venue}' but actually '{paper_venue}'",
                    'ref_venue_correct': paper_venue
                })
        elif not cited_venue and paper_venue:
            # Original reference has the venue in raw text but not parsed correctly
            raw_text = reference.get('raw_text', '')
            if raw_text and '#' in raw_text:
                # Check if venue might be in the raw text format (author#title#venue#year#url)
                parts = raw_text.split('#')
                if len(parts) >= 3 and parts[2].strip():
                    # Venue is present in raw text but missing from parsed reference
                    errors.append({
                        'warning_type': 'venue',
                        'warning_details': f"Venue missing: should include '{paper_venue}'",
                        'ref_venue_correct': paper_venue
                    })

        # Verify DOI
        paper_doi = None
        external_ids = paper_data.get('externalIds', {})
        if external_ids and 'DOI' in external_ids:
            paper_doi = external_ids['DOI']
            
            # Compare DOIs, but strip hash fragments for comparison
            cited_doi_clean = doi.split('#')[0] if doi else ''
            paper_doi_clean = paper_doi.split('#')[0] if paper_doi else ''
            
            if cited_doi_clean and paper_doi_clean and cited_doi_clean.lower() != paper_doi_clean.lower():
                errors.append({
                    'error_type': 'doi',
                    'error_details': f"DOI mismatch: cited as {doi} but actually {paper_doi}",
                    'ref_doi_correct': paper_doi
                })
        
        # Extract URL from paper data - prioritize PDF URLs over Semantic Scholar page URLs
        paper_url = paper_data.get('url', None)
        
        logger.debug(f"Semantic Scholar - Extracting URL from paper data: {list(paper_data.keys())}")
        
        # First, check for open access PDF (most useful for users)
        open_access_pdf = paper_data.get('openAccessPdf')
        if open_access_pdf and open_access_pdf.get('url'):
            paper_url = open_access_pdf['url']
            logger.debug(f"Found open access PDF URL: {paper_url}")
        
        # Fallback to general URL field (typically Semantic Scholar page)
        if not paper_url:
            paper_url = paper_data.get('url')
            if paper_url:
                logger.debug(f"Found paper URL: {paper_url}")
        
        # Also check externalIds for DOI URL
        if not paper_url:
            external_ids = paper_data.get('externalIds', {})
            if external_ids.get('DOI'):
                paper_url = f"https://doi.org/{external_ids['DOI']}"
                logger.debug(f"Generated DOI URL: {paper_url}")
        
        if not paper_url:
            logger.debug(f"No URL found in paper data - available fields: {list(paper_data.keys())}")
            logger.debug(f"Paper data sample: {str(paper_data)[:200]}...")
        
        return paper_data, errors, paper_url

if __name__ == "__main__":
    # Example usage
    checker = NonArxivReferenceChecker()
    
    # Example reference
    reference = {
        'title': 'Attention is All You Need',
        'authors': ['Ashish Vaswani', 'Noam Shazeer'],
        'year': 2017,
        'url': 'https://example.com/paper',
        'raw_text': 'Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., ... & Polosukhin, I. (2017). Attention is all you need. Advances in neural information processing systems, 30.'
    }
    
    # Verify the reference
    verified_data, errors = checker.verify_reference(reference)
    
    if verified_data:
        print(f"Found paper: {verified_data.get('title')}")
        
        if errors:
            print("Errors found:")
            for error in errors:
                print(f"  - {error['error_type']}: {error['error_details']}")
        else:
            print("No errors found")
    else:
        print("Could not find matching paper")
