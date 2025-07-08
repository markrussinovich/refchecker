#!/usr/bin/env python3
"""
Google Scholar API Client for Reference Verification

This module provides functionality to verify non-arXiv references using the Google Scholar API.
It can check if a reference's metadata (authors, year, title) matches what's in the Google Scholar database.

Usage:
    from google_scholar import GoogleScholarReferenceChecker
    
    # Initialize the checker
    checker = GoogleScholarReferenceChecker()
    
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

import time
import logging
import re
import random
from typing import Dict, List, Tuple, Optional, Any, Union
from scholarly import scholarly, ProxyGenerator
from .semantic_scholar import NonArxivReferenceChecker
from .local_semantic_scholar import LocalNonArxivReferenceChecker

# Set up logging
logger = logging.getLogger(__name__)

class GoogleScholarReferenceChecker:
    """
    A class to verify non-arXiv references using the Google Scholar API
    """
    
    def __init__(self, semantic_scholar_api_key=None, db_path=None):
        """
        Initialize the Google Scholar API client
        
        Args:
            semantic_scholar_api_key: Optional API key for Semantic Scholar fallback
            db_path: Optional path to local Semantic Scholar database for offline fallback
        """
        # Rate limiting parameters - optimized for better performance
        self.request_delay = 2.0  # Reduced initial delay between requests (seconds)
        self.max_retries = 2  # Reduced max retries
        self.backoff_factor = 2  # Reduced exponential backoff factor
        
        # Setup proxy generator for scholarly
        self.setup_scholarly()
        
        # Initialize fallback checker - prefer local database if available
        if db_path:
            logger.info(f"Google Scholar will use local database fallback at {db_path}")
            self.semantic_scholar = LocalNonArxivReferenceChecker(db_path=db_path)
        else:
            logger.info("Google Scholar will use online Semantic Scholar API as fallback")
            self.semantic_scholar = NonArxivReferenceChecker(api_key=semantic_scholar_api_key)
        
    def setup_scholarly(self):
        """
        Set up the scholarly library with proxies and user agent rotation
        """
        try:
            # Create a ProxyGenerator object
            pg = ProxyGenerator()
            
            # Use free proxies
            success = pg.FreeProxies()
            if not success:
                # If free proxies fail, try Tor
                success = pg.Tor_External(tor_sock_port=9050, tor_control_port=9051)
            
            # Set up proxy rotation
            scholarly.use_proxy(pg)
            
            # Configure scholarly with optimized timeout
            scholarly.set_timeout(15)
            
            logger.info("Scholarly setup complete with proxy rotation")
        except Exception as e:
            logger.warning(f"Failed to set up scholarly proxies: {str(e)}")
    
    def search_paper(self, query: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Search for papers matching the query
        
        Args:
            query: Search query (title, authors, etc.)
            year: Publication year to filter by
            
        Returns:
            List of paper data dictionaries
        """
        # Build query string
        search_query = query
        if year:
            search_query = f"{query} year:{year}"
        
        # Add some randomization to the delay to avoid detection patterns
        initial_delay = self.request_delay + random.uniform(0.5, 1.5)
        time.sleep(initial_delay)
        
        # Make the request with retries and backoff
        for attempt in range(self.max_retries):
            try:
                # Search for the paper
                search_results = []
                search_query_gen = scholarly.search_pubs(search_query)
                
                # Get the first 3 results (reduced from 5 to minimize requests)
                for _ in range(3):
                    try:
                        result = next(search_query_gen)
                        search_results.append(result)
                        # Add small delay between fetching results
                        time.sleep(random.uniform(0.5, 1.0))
                    except StopIteration:
                        break
                
                # If we got results, add a delay before returning to avoid rapid successive requests
                if search_results:
                    time.sleep(random.uniform(1, 2))
                    return search_results
                
            except Exception as e:
                wait_time = self.request_delay * (self.backoff_factor ** attempt) + random.uniform(0.5, 2.0)
                logger.warning(f"Request failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                
                # Try to reset the scholarly setup on failure
                if attempt > 0:
                    try:
                        self.setup_scholarly()
                    except Exception as setup_error:
                        logger.warning(f"Failed to reset scholarly: {str(setup_error)}")
        
        # If we get here, all retries failed
        logger.error(f"Failed to search for paper after {self.max_retries} attempts")
        return []
    
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
        
        # Remove line breaks and extra spaces
        name = re.sub(r'\s+', ' ', name.replace('\n', ' ')).strip()
        
        # Remove special characters
        name = re.sub(r'[^\w\s]', '', name)
        
        return name.lower()
    
    def compare_authors(self, cited_authors: List[str], correct_authors: List[str]) -> Tuple[bool, str]:
        """
        Compare author lists to check if they match
        
        Args:
            cited_authors: List of author names as cited
            correct_authors: List of author data from Google Scholar
            
        Returns:
            Tuple of (match_result, error_message)
        """
        # Normalize names for comparison
        normalized_cited = [self.normalize_author_name(name) for name in cited_authors]
        normalized_correct = [self.normalize_author_name(name) for name in correct_authors]
        
        # If the cited list is much shorter, it might be using "et al."
        # In this case, just check the authors that are listed
        if len(normalized_cited) < len(normalized_correct) and len(normalized_cited) <= 3:
            # Only compare the first few authors
            normalized_correct = normalized_correct[:len(normalized_cited)]
        
        # Compare first author (most important)
        if normalized_cited and normalized_correct:
            if not self.is_name_match(normalized_cited[0], normalized_correct[0]):
                return False, f"First author mismatch: '{cited_authors[0]}' vs '{correct_authors[0]}'"
        
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
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Verify a non-arXiv reference using Google Scholar with fallback to Semantic Scholar
        
        Args:
            reference: Reference data dictionary
            
        Returns:
            Tuple of (verified_data, errors)
            - verified_data: Paper data from Google Scholar or None if not found
            - errors: List of error dictionaries
        """
        errors = []
        
        # Extract reference data
        title = reference.get('title', '')
        authors = reference.get('authors', [])
        year = reference.get('year', 0)
        url = reference.get('url', '')
        raw_text = reference.get('raw_text', '')
        
        try:
            # First try with Google Scholar
            if title:
                # Clean up the title
                clean_title = title.replace('\n', ' ').strip()
                clean_title = re.sub(r'\s+', ' ', clean_title)
                
                # Search for the paper
                search_results = self.search_paper(clean_title, year)
                
                if search_results:
                    # Find the best match
                    best_match = None
                    for result in search_results:
                        result_title = result.get('bib', {}).get('title', '')
                        
                        # Simple string matching for now
                        # Could be improved with more sophisticated matching
                        if clean_title.lower() in result_title.lower() or result_title.lower() in clean_title.lower():
                            best_match = result
                            break
                    
                    if best_match:
                        paper_data = best_match
                        logger.debug(f"Found paper by title in Google Scholar: {clean_title}")
                        
                        # Verify authors
                        if authors and 'author' in paper_data.get('bib', {}):
                            scholar_authors = paper_data['bib']['author']
                            authors_match, author_error = self.compare_authors(authors, scholar_authors)
                            
                            if not authors_match:
                                errors.append({
                                    'error_type': 'author',
                                    'error_details': author_error,
                                    'ref_authors_correct': ', '.join(scholar_authors)
                                })
                        
                        # Verify year
                        paper_year = paper_data.get('bib', {}).get('pub_year')
                        if year and paper_year and year != int(paper_year):
                            errors.append({
                                'warning_type': 'year',
                                'warning_details': f"Year mismatch: cited as {year} but actually {paper_year}",
                                'ref_year_correct': paper_year
                            })
                        
                        return paper_data, errors
            
            # If Google Scholar failed or found no results, fall back to Semantic Scholar
            logger.info(f"Falling back to Semantic Scholar for: {title}")
            verified_data, semantic_errors = self.semantic_scholar.verify_reference(reference)
            
            if verified_data:
                logger.info(f"Found paper in Semantic Scholar: {title}")
                return verified_data, semantic_errors
            
            # If both failed, return empty results
            logger.warning(f"Could not verify reference in either Google Scholar or Semantic Scholar: {title}")
            return None, []
            
        except Exception as e:
            logger.error(f"Error during verification: {str(e)}")
            
            # Try Semantic Scholar as fallback
            try:
                logger.info(f"Falling back to Semantic Scholar after error: {title}")
                return self.semantic_scholar.verify_reference(reference)
            except Exception as semantic_error:
                logger.error(f"Semantic Scholar fallback also failed: {str(semantic_error)}")
                return None, []

if __name__ == "__main__":
    # Set up logging for standalone usage
    logging.basicConfig(level=logging.INFO)
    
    # Example usage
    checker = GoogleScholarReferenceChecker()
    
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
        print(f"Found paper: {verified_data.get('bib', {}).get('title')}")
        
        if errors:
            print("Errors found:")
            for error in errors:
                print(f"  - {error['error_type']}: {error['error_details']}")
        else:
            print("No errors found")
    else:
        print("Could not find matching paper")
