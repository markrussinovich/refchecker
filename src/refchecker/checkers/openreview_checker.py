#!/usr/bin/env python3
"""
OpenReview API Client for Reference Verification

This module provides functionality to verify references from OpenReview papers.
OpenReview is a platform for open peer review in machine learning conferences
like ICLR, NeurIPS, ICML, etc.

Usage:
    from openreview_checker import OpenReviewReferenceChecker
    
    # Initialize the checker
    checker = OpenReviewReferenceChecker()
    
    # Verify a reference
    reference = {
        'title': 'Title of the paper',
        'authors': ['Author 1', 'Author 2'],
        'year': 2024,
        'url': 'https://openreview.net/forum?id=ZG3RaNIsO8',
        'raw_text': 'Full citation text'
    }
    
    verified_data, errors, url = checker.verify_reference(reference)
"""

import requests
import time
import logging
import re
import json
from typing import Dict, List, Tuple, Optional, Any, Union
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from refchecker.utils.text_utils import (
    normalize_text, clean_title_basic, is_name_match, 
    calculate_title_similarity, compare_authors, 
    clean_title_for_search, are_venues_substantially_different,
    is_year_substantially_different, strip_latex_commands,
    compare_titles_with_latex_cleaning
)

# Set up logging
logger = logging.getLogger(__name__)

class OpenReviewReferenceChecker:
    """
    A class to verify references using OpenReview
    """
    
    def __init__(self, request_delay: float = 1.0):
        """
        Initialize the OpenReview client
        
        Args:
            request_delay: Delay between requests to be respectful to OpenReview servers
        """
        self.base_url = "https://openreview.net"
        self.api_url = "https://api.openreview.net"
        self.request_delay = request_delay
        self.last_request_time = 0
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'RefChecker/1.0 (Academic Reference Verification)',
            'Accept': 'application/json, text/html',
            'Accept-Language': 'en-US,en;q=0.9'
        })
    
    def is_openreview_url(self, url: str) -> bool:
        """
        Check if URL is from OpenReview
        
        Args:
            url: URL to check
            
        Returns:
            True if it's an OpenReview URL
        """
        return bool(url and 'openreview.net' in url.lower())
    
    def is_openreview_reference(self, reference: Dict[str, Any]) -> bool:
        """
        Determine if this reference is from OpenReview based on URL patterns
        
        Args:
            reference: Reference dictionary to check
            
        Returns:
            True if reference appears to be from OpenReview
        """
        # Check various URL fields for OpenReview URLs
        url_fields = ['url', 'openreview_url', 'link', 'venue_url']
        for field in url_fields:
            url = reference.get(field, '')
            if url and self.is_openreview_url(url):
                return True
        
        # Check raw text for OpenReview URLs  
        raw_text = reference.get('raw_text', '')
        if raw_text and 'openreview.net' in raw_text.lower():
            return True
            
        return False
    
    def extract_paper_id(self, url: str) -> Optional[str]:
        """
        Extract paper ID from OpenReview URL
        
        Args:
            url: OpenReview URL
            
        Returns:
            Paper ID if found, None otherwise
        """
        if not self.is_openreview_url(url):
            return None
        
        # Handle different OpenReview URL formats:
        # https://openreview.net/forum?id=ZG3RaNIsO8
        # https://openreview.net/pdf?id=ZG3RaNIsO8
        # https://openreview.net/forum?id=ZG3RaNIsO8&noteId=...
        
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        
        if 'id' in query_params:
            return query_params['id'][0]
        
        # Also check path-based URLs (if they exist)
        path_match = re.search(r'/(?:forum|pdf|notes)/([A-Za-z0-9_-]+)', parsed.path)
        if path_match:
            return path_match.group(1)
        
        return None
    
    def _respectful_request(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make a respectful HTTP request with rate limiting"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.request_delay:
            time.sleep(self.request_delay - time_since_last)
        
        try:
            logger.debug(f"Making request to: {url}")
            response = self.session.get(url, timeout=15, **kwargs)
            self.last_request_time = time.time()
            logger.debug(f"Request successful: {response.status_code}")
            return response
        except requests.exceptions.RequestException as e:
            logger.debug(f"Request failed for {url}: {type(e).__name__}: {e}")
            return None
    
    def get_paper_metadata(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """
        Get paper metadata from OpenReview
        
        Args:
            paper_id: OpenReview paper ID
            
        Returns:
            Paper metadata dictionary or None if not found
        """
        # Try API endpoint first
        api_url = f"{self.api_url}/notes?id={paper_id}"
        response = self._respectful_request(api_url)
        
        if response and response.status_code == 200:
            try:
                data = response.json()
                if 'notes' in data and data['notes']:
                    note = data['notes'][0]
                    return self._parse_api_response(note)
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug(f"Failed to parse API response: {e}")
        
        # Fall back to web scraping
        forum_url = f"{self.base_url}/forum?id={paper_id}"
        response = self._respectful_request(forum_url)
        
        if not response or response.status_code != 200:
            return None
        
        return self._parse_web_page(response.text, forum_url)
    
    def _parse_api_response(self, note: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse OpenReview API response to extract metadata
        
        Args:
            note: Note data from API response
            
        Returns:
            Parsed metadata dictionary
        """
        content = note.get('content', {})
        
        # Extract basic metadata
        metadata = {
            'id': note.get('id'),
            'title': content.get('title', '').strip(),
            'authors': [],
            'year': None,
            'venue': None,
            'abstract': content.get('abstract', '').strip(),
            'keywords': content.get('keywords', []),
            'pdf_url': content.get('pdf'),
            'forum_url': f"{self.base_url}/forum?id={note.get('id')}",
            'source': 'openreview_api'
        }
        
        # Parse authors
        authors_raw = content.get('authors', [])
        if isinstance(authors_raw, list):
            metadata['authors'] = [author.strip() for author in authors_raw if author.strip()]
        elif isinstance(authors_raw, str):
            # Sometimes authors are in a single string
            metadata['authors'] = [author.strip() for author in authors_raw.split(',') if author.strip()]
        
        # Extract year from various sources
        # Check creation time
        if 'cdate' in note:
            try:
                import datetime
                timestamp = note['cdate'] / 1000.0  # Convert from milliseconds
                year = datetime.datetime.fromtimestamp(timestamp).year
                metadata['year'] = year
            except (ValueError, TypeError):
                pass
        
        # Check if venue/conference info is available
        venue_info = content.get('venue', '')
        if venue_info:
            metadata['venue'] = venue_info.strip()
        
        # Try to extract venue from forum context or submission info
        if not metadata['venue']:
            # Common venues for OpenReview
            forum_path = note.get('forum', '')
            if 'ICLR' in str(content) or 'iclr' in forum_path.lower():
                metadata['venue'] = 'ICLR'
            elif 'NeurIPS' in str(content) or 'neurips' in forum_path.lower():
                metadata['venue'] = 'NeurIPS'
            elif 'ICML' in str(content) or 'icml' in forum_path.lower():
                metadata['venue'] = 'ICML'
        
        return metadata
    
    def _parse_web_page(self, html: str, url: str) -> Dict[str, Any]:
        """
        Parse OpenReview web page to extract metadata
        
        Args:
            html: HTML content of the page
            url: Original URL
            
        Returns:
            Parsed metadata dictionary
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract paper ID from URL
        paper_id = self.extract_paper_id(url)
        
        metadata = {
            'id': paper_id,
            'title': '',
            'authors': [],
            'year': None,
            'venue': None,
            'abstract': '',
            'keywords': [],
            'forum_url': url,
            'source': 'openreview_web'
        }
        
        # Extract title
        title_elem = soup.find('h2', {'class': 'citation_title'}) or soup.find('h1')
        if title_elem:
            metadata['title'] = title_elem.get_text().strip()
        
        # Try to find title in meta tags
        if not metadata['title']:
            meta_title = soup.find('meta', {'property': 'og:title'}) or soup.find('meta', {'name': 'title'})
            if meta_title and meta_title.get('content'):
                metadata['title'] = meta_title['content'].strip()
        
        # Extract authors from meta tags (most reliable for OpenReview)
        author_metas = soup.find_all('meta', {'name': 'citation_author'})
        if author_metas:
            metadata['authors'] = [meta.get('content', '').strip() for meta in author_metas if meta.get('content', '').strip()]
        
        # Fallback: try to find authors in HTML structure
        if not metadata['authors']:
            authors_section = soup.find('div', {'class': 'authors'}) or soup.find('span', {'class': 'authors'})
            if authors_section:
                # Extract author names from links or text
                author_links = authors_section.find_all('a')
                if author_links:
                    metadata['authors'] = [link.get_text().strip() for link in author_links]
                else:
                    # Parse comma-separated authors
                    authors_text = authors_section.get_text().strip()
                    metadata['authors'] = [author.strip() for author in authors_text.split(',') if author.strip()]
        
        # Extract year from various sources
        year_pattern = r'\b(20\d{2})\b'
        
        # Check date/year elements
        date_elem = soup.find('span', {'class': 'date'}) or soup.find('time')
        if date_elem:
            year_match = re.search(year_pattern, date_elem.get_text())
            if year_match:
                metadata['year'] = int(year_match.group(1))
        
        # Check meta tags for date
        if not metadata['year']:
            meta_date = soup.find('meta', {'name': 'citation_date'}) or soup.find('meta', {'name': 'date'})
            if meta_date and meta_date.get('content'):
                year_match = re.search(year_pattern, meta_date['content'])
                if year_match:
                    metadata['year'] = int(year_match.group(1))
        
        # Extract abstract
        abstract_elem = soup.find('div', {'class': 'abstract'}) or soup.find('section', {'class': 'abstract'})
        if abstract_elem:
            metadata['abstract'] = abstract_elem.get_text().strip()
        
        # Extract venue information from meta tags (most reliable for OpenReview)
        venue_meta = soup.find('meta', {'name': 'citation_conference_title'})
        if venue_meta and venue_meta.get('content'):
            venue_full = venue_meta['content'].strip()
            # Convert long conference names to common abbreviations
            if 'International Conference on Learning Representations' in venue_full:
                # Extract year if present
                year_match = re.search(r'\b(20\d{2})\b', venue_full)
                if year_match:
                    metadata['venue'] = f'ICLR {year_match.group(1)}'
                else:
                    metadata['venue'] = 'ICLR'
            elif 'Neural Information Processing Systems' in venue_full or 'NeurIPS' in venue_full:
                year_match = re.search(r'\b(20\d{2})\b', venue_full)
                if year_match:
                    metadata['venue'] = f'NeurIPS {year_match.group(1)}'
                else:
                    metadata['venue'] = 'NeurIPS'
            else:
                metadata['venue'] = venue_full
        
        # Fallback: try HTML structure  
        if not metadata['venue']:
            venue_elem = soup.find('div', {'class': 'venue'}) or soup.find('span', {'class': 'venue'})
            if venue_elem:
                metadata['venue'] = venue_elem.get_text().strip()
        
        # Final fallback: try to determine venue from page context or URL
        if not metadata['venue']:
            page_text = soup.get_text().lower()
            if 'iclr' in page_text or 'iclr' in url.lower():
                if '2024' in page_text:
                    metadata['venue'] = 'ICLR 2024'
                else:
                    metadata['venue'] = 'ICLR'
            elif 'neurips' in page_text or 'neurips' in url.lower():
                metadata['venue'] = 'NeurIPS'
            elif 'icml' in page_text or 'icml' in url.lower():
                metadata['venue'] = 'ICML'
        
        # Extract keywords if available
        keywords_elem = soup.find('div', {'class': 'keywords'})
        if keywords_elem:
            keywords_text = keywords_elem.get_text()
            metadata['keywords'] = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]
        
        return metadata
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a reference against OpenReview
        
        Args:
            reference: Reference dictionary with title, authors, year, url, etc.
            
        Returns:
            Tuple of (verified_data, errors, paper_url) where:
            - verified_data: Dict with verified OpenReview paper data or None
            - errors: List of error/warning dictionaries
            - paper_url: The OpenReview URL
        """
        logger.debug(f"Verifying OpenReview reference: {reference.get('title', 'Untitled')}")
        
        # Extract OpenReview URL from reference
        openreview_url = None
        for url_key in ['url', 'openreview_url', 'link']:
            if url_key in reference and reference[url_key]:
                url = reference[url_key].strip()
                if self.is_openreview_url(url):
                    openreview_url = url
                    break
        
        if not openreview_url:
            logger.debug("No OpenReview URL found in reference")
            return None, [], None
        
        # Extract paper ID
        paper_id = self.extract_paper_id(openreview_url)
        if not paper_id:
            return None, [{"error_type": "unverified", "error_details": "Could not extract paper ID from OpenReview URL"}], openreview_url
        
        # Get paper metadata
        paper_data = self.get_paper_metadata(paper_id)
        if not paper_data:
            return None, [{"error_type": "unverified", "error_details": "Paper not found on OpenReview"}], openreview_url
        
        logger.debug(f"Found OpenReview paper: {paper_data.get('title', 'Untitled')}")
        
        # Verify the reference against the paper data
        errors = []
        
        # Check title match
        cited_title = reference.get('title', '').strip()
        paper_title = paper_data.get('title', '').strip()
        
        if cited_title and paper_title:
            similarity = compare_titles_with_latex_cleaning(cited_title, paper_title)
            if similarity < 0.7:  # Using a reasonable threshold
                from refchecker.utils.error_utils import format_title_mismatch
                # Clean the cited title for display (remove LaTeX commands like {LLM}s -> LLMs)
                clean_cited_title = strip_latex_commands(cited_title)
                details = format_title_mismatch(clean_cited_title, paper_title) + f" (similarity: {similarity:.2f})"
                errors.append({
                    "warning_type": "title",
                    "warning_details": details
                })
        
        # Check authors
        cited_authors = reference.get('authors', [])
        paper_authors = paper_data.get('authors', [])
        
        if cited_authors and paper_authors:
            # Convert to list format if needed
            if isinstance(cited_authors, str):
                cited_authors = [author.strip() for author in cited_authors.split(',')]
            if isinstance(paper_authors, str):
                paper_authors = [author.strip() for author in paper_authors.split(',')]
            
            # Use the existing author comparison function
            match, error_msg = compare_authors(cited_authors, paper_authors)
            if not match and error_msg:
                errors.append({
                    "warning_type": "author",
                    "warning_details": error_msg
                })
        
        # Check year
        cited_year = reference.get('year')
        paper_year = paper_data.get('year')
        
        if cited_year and paper_year:
            try:
                cited_year_int = int(cited_year)
                paper_year_int = int(paper_year)
                
                is_different, year_message = is_year_substantially_different(cited_year_int, paper_year_int)
                if is_different and year_message:
                    from refchecker.utils.error_utils import format_year_mismatch
                    errors.append({
                        "warning_type": "year",
                        "warning_details": format_year_mismatch(cited_year_int, paper_year_int)
                    })
            except (ValueError, TypeError):
                pass  # Skip year validation if conversion fails
        
        # Check venue if provided in reference
        cited_venue = reference.get('venue', '').strip()
        paper_venue = paper_data.get('venue', '').strip()
        
        if cited_venue and paper_venue:
            if are_venues_substantially_different(cited_venue, paper_venue):
                from refchecker.utils.error_utils import format_venue_mismatch
                errors.append({
                    "warning_type": "venue",
                    "warning_details": format_venue_mismatch(cited_venue, paper_venue)
                })
        
        # Create verified data structure
        verified_data = {
            'title': paper_data.get('title', cited_title),
            'authors': paper_data.get('authors', cited_authors),
            'year': paper_data.get('year', cited_year),
            'venue': paper_data.get('venue', cited_venue),
            'url': openreview_url,
            'abstract': paper_data.get('abstract', ''),
            'keywords': paper_data.get('keywords', []),
            'openreview_metadata': paper_data,
            'verification_source': 'OpenReview'
        }
        
        logger.debug(f"OpenReview verification completed for: {openreview_url}")
        return verified_data, errors, openreview_url
    
    def verify_by_search(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a reference by searching OpenReview (when no URL is provided)
        
        Args:
            reference: Reference dictionary with title, authors, year, etc.
            
        Returns:
            Tuple of (verified_data, errors, paper_url) where:
            - verified_data: Dict with verified OpenReview paper data or None
            - errors: List of error/warning dictionaries  
            - paper_url: The OpenReview URL if found
        """
        logger.debug(f"Searching OpenReview for reference: {reference.get('title', 'Untitled')}")
        
        title = reference.get('title', '').strip()
        authors = reference.get('authors', [])
        year = reference.get('year')
        venue = reference.get('venue', '').strip()
        
        if not title:
            return None, [], None
        
        # Check if venue suggests this might be on OpenReview
        if not self._is_likely_openreview_venue(venue):
            logger.debug(f"Venue '{venue}' doesn't suggest OpenReview, skipping search")
            return None, [], None
        
        # Search for matching papers
        search_results = self.search_paper(title, authors, year)
        
        if not search_results:
            logger.debug("No matching papers found on OpenReview")
            return None, [], None
        
        # Use the best match (first result, as they're sorted by relevance)
        best_match = search_results[0]
        paper_url = best_match.get('forum_url')
        
        logger.debug(f"Found OpenReview match: {best_match.get('title', 'Untitled')}")
        
        # Verify the reference against the found paper
        errors = []
        
        # Check title match
        cited_title = reference.get('title', '').strip()
        paper_title = best_match.get('title', '').strip()
        
        if cited_title and paper_title:
            similarity = compare_titles_with_latex_cleaning(cited_title, paper_title)
            if similarity < 0.8:  # Slightly higher threshold for search results
                from refchecker.utils.error_utils import format_title_mismatch
                # Clean the cited title for display (remove LaTeX commands like {LLM}s -> LLMs)
                clean_cited_title = strip_latex_commands(cited_title)
                details = format_title_mismatch(clean_cited_title, paper_title) + f" (similarity: {similarity:.2f})"
                errors.append({
                    "warning_type": "title",
                    "warning_details": details
                })
        
        # Check authors
        cited_authors = reference.get('authors', [])
        paper_authors = best_match.get('authors', [])
        
        if cited_authors and paper_authors:
            # Convert to list format if needed
            if isinstance(cited_authors, str):
                cited_authors = [author.strip() for author in cited_authors.split(',')]
            if isinstance(paper_authors, str):
                paper_authors = [author.strip() for author in paper_authors.split(',')]
            
            # Use the existing author comparison function
            match, error_msg = compare_authors(cited_authors, paper_authors)
            if not match and error_msg:
                errors.append({
                    "warning_type": "author", 
                    "warning_details": error_msg
                })
        
        # Check year
        cited_year = reference.get('year')
        paper_year = best_match.get('year')
        
        if cited_year and paper_year:
            try:
                cited_year_int = int(cited_year)
                paper_year_int = int(paper_year)
                
                is_different, year_message = is_year_substantially_different(cited_year_int, paper_year_int)
                if is_different and year_message:
                    from refchecker.utils.error_utils import format_year_mismatch
                    errors.append({
                        "warning_type": "year",
                        "warning_details": format_year_mismatch(cited_year_int, paper_year_int)
                    })
            except (ValueError, TypeError):
                pass  # Skip year validation if conversion fails
        
        # Check venue if provided in reference
        cited_venue = reference.get('venue', '').strip()
        paper_venue = best_match.get('venue', '').strip()
        
        if cited_venue and paper_venue:
            if are_venues_substantially_different(cited_venue, paper_venue):
                from refchecker.utils.error_utils import format_venue_mismatch
                errors.append({
                    "warning_type": "venue",
                    "warning_details": format_venue_mismatch(cited_venue, paper_venue)
                })
        
        # Create verified data structure
        verified_data = {
            'title': best_match.get('title', cited_title),
            'authors': best_match.get('authors', cited_authors),
            'year': best_match.get('year', cited_year),
            'venue': best_match.get('venue', cited_venue),
            'url': paper_url,
            'abstract': best_match.get('abstract', ''),
            'keywords': best_match.get('keywords', []),
            'openreview_metadata': best_match,
            'verification_source': 'OpenReview (search)'
        }
        
        logger.debug(f"OpenReview search verification completed for: {paper_url}")
        return verified_data, errors, paper_url
    
    def _is_likely_openreview_venue(self, venue: str) -> bool:
        """
        Check if a venue suggests the paper might be on OpenReview
        
        Args:
            venue: Venue string from reference
            
        Returns:
            True if venue suggests OpenReview
        """
        if not venue:
            return False
        
        venue_lower = venue.lower()
        
        # Common venues that use OpenReview
        openreview_venues = [
            'iclr', 'international conference on learning representations',
            'neurips', 'neural information processing systems', 'nips',
            'icml', 'international conference on machine learning',
            'iclr workshop', 'neurips workshop', 'icml workshop',
            'aaai', 'ijcai', 'aistats'
        ]
        
        for or_venue in openreview_venues:
            if or_venue in venue_lower:
                return True
        
        return False
    
    def search_paper(self, title: str, authors: List[str] = None, year: int = None) -> List[Dict[str, Any]]:
        """
        Search for papers on OpenReview by title, authors, and/or year
        
        Args:
            title: Paper title to search for
            authors: List of author names (optional)
            year: Publication year (optional)
            
        Returns:
            List of matching paper metadata dictionaries
        """
        if not title or not title.strip():
            return []
            
        logger.debug(f"Searching OpenReview for: {title}")
        
        # Clean title for search
        search_title = clean_title_for_search(title)
        
        # Try API search first
        results = self._search_via_api(search_title, authors, year)
        if results:
            return results
        
        # If API search fails, try web search as fallback
        return self._search_via_web(search_title, authors, year)
    
    def _search_via_api(self, title: str, authors: List[str] = None, year: int = None) -> List[Dict[str, Any]]:
        """
        Search using OpenReview API
        
        Args:
            title: Clean title to search for
            authors: List of author names (optional)
            year: Publication year (optional)
            
        Returns:
            List of matching paper dictionaries
        """
        try:
            # The OpenReview API requires specific parameters
            # We'll search by content.title or content.venue (for venue-based search)
            search_params = {
                'limit': 20,  # Limit results to avoid overwhelming the API
                'details': 'directReplies'  # Get basic details
            }
            
            # Try searching by venue first if year suggests recent conferences
            if year and year >= 2017:  # OpenReview started around 2017
                venues_by_year = {
                    2025: ['ICLR 2025'],
                    2024: ['ICLR 2024', 'NeurIPS 2024', 'ICML 2024'],
                    2023: ['ICLR 2023', 'NeurIPS 2023', 'ICML 2023'],
                    2022: ['ICLR 2022', 'NeurIPS 2022', 'ICML 2022'],
                    2021: ['ICLR 2021', 'NeurIPS 2021', 'ICML 2021'],
                    2020: ['ICLR 2020', 'NeurIPS 2020', 'ICML 2020'],
                    2019: ['ICLR 2019', 'NeurIPS 2019', 'ICML 2019'],
                    2018: ['ICLR 2018', 'NeurIPS 2018', 'ICML 2018'],
                    2017: ['ICLR 2017']
                }
                
                possible_venues = venues_by_year.get(year, [])
                
                results = []
                for venue in possible_venues:
                    # Search by venue and then filter by title
                    venue_params = search_params.copy()
                    venue_params['content.venue'] = venue
                    
                    api_url = f"{self.api_url}/notes"
                    response = self._respectful_request(api_url, params=venue_params)
                    
                    if response and response.status_code == 200:
                        try:
                            data = response.json()
                            if 'notes' in data and data['notes']:
                                for note in data['notes']:
                                    try:
                                        metadata = self._parse_api_response(note)
                                        if metadata and self._is_good_match(metadata, title, authors, year):
                                            results.append(metadata)
                                            if len(results) >= 5:  # Limit results
                                                break
                                    except Exception as e:
                                        logger.debug(f"Error parsing note: {e}")
                                        continue
                                
                                if results:
                                    break  # Found results, no need to search other venues
                                    
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.debug(f"Failed to parse venue search response: {e}")
                            continue
                    else:
                        logger.debug(f"Venue search failed for {venue}: {response.status_code if response else 'No response'}")
                
                if results:
                    logger.debug(f"OpenReview API search found {len(results)} matches via venue search")
                    return results
            
            # If venue search didn't work, try other approaches
            # OpenReview API is quite restrictive, so we might need to fall back to web scraping
            logger.debug("OpenReview API venue search returned no results, trying web search")
            return []
            
        except Exception as e:
            logger.debug(f"OpenReview API search error: {e}")
            return []
    
    def _search_via_web(self, title: str, authors: List[str] = None, year: int = None) -> List[Dict[str, Any]]:
        """
        Search using OpenReview web interface (fallback)
        
        Args:
            title: Clean title to search for
            authors: List of author names (optional)
            year: Publication year (optional)
            
        Returns:
            List of matching paper dictionaries
        """
        try:
            # Build search URL
            search_query = title.replace(' ', '+')
            search_url = f"{self.base_url}/search?term={search_query}"
            
            response = self._respectful_request(search_url)
            if not response or response.status_code != 200:
                return []
            
            # Parse search results page
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for paper links in search results
            # OpenReview search results typically contain links to forum pages
            results = []
            
            # Find links that look like OpenReview paper URLs
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if '/forum?id=' in href:
                    paper_id = self.extract_paper_id(href)
                    if paper_id:
                        # Get full metadata for this paper
                        metadata = self.get_paper_metadata(paper_id)
                        if metadata and self._is_good_match(metadata, title, authors, year):
                            results.append(metadata)
                            if len(results) >= 5:  # Limit results
                                break
            
            logger.debug(f"OpenReview web search found {len(results)} matches")
            return results
            
        except Exception as e:
            logger.debug(f"OpenReview web search error: {e}")
            return []
    
    def _is_good_match(self, metadata: Dict[str, Any], search_title: str, authors: List[str] = None, year: int = None) -> bool:
        """
        Check if the found paper is a good match for the search criteria
        
        Args:
            metadata: Paper metadata from OpenReview
            search_title: Title we're searching for
            authors: Authors we're looking for (optional)
            year: Year we're looking for (optional)
            
        Returns:
            True if it's a good match
        """
        paper_title = metadata.get('title', '')
        if not paper_title:
            return False
        
        # Check title similarity
        title_similarity = calculate_title_similarity(search_title, paper_title)
        if title_similarity < 0.7:  # Require at least 70% similarity
            return False
        
        # Check year if provided
        if year:
            paper_year = metadata.get('year')
            if paper_year and abs(int(paper_year) - year) > 1:  # Allow 1 year difference
                return False
        
        # Check authors if provided
        if authors and len(authors) > 0:
            paper_authors = metadata.get('authors', [])
            if paper_authors:
                # Check if at least one author matches
                author_match = False
                for search_author in authors[:2]:  # Check first 2 authors
                    for paper_author in paper_authors[:3]:  # Check first 3 paper authors
                        if is_name_match(search_author, paper_author):
                            author_match = True
                            break
                    if author_match:
                        break
                
                if not author_match:
                    return False
        
        return True

    def search_by_title(self, title: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Search OpenReview for papers by title using the working search API.
        
        Args:
            title: Paper title to search for
            max_results: Maximum number of results to return
            
        Returns:
            List of paper data dictionaries
        """
        try:
            # Use OpenReview's search API with term parameter (this works!)
            params = {
                'term': title,
                'limit': max_results
            }
            
            response = self._respectful_request(f"{self.api_url}/notes/search", params=params)
            if not response or response.status_code != 200:
                logger.debug(f"OpenReview search API failed with status {response.status_code if response else 'None'}")
                return []
            
            data = response.json()
            papers = []
            
            for note in data.get('notes', []):
                # Filter to exact or close title matches
                note_title = note.get('content', {}).get('title', '')
                if self._is_title_match(title, note_title):
                    paper_data = self._parse_api_response(note)
                    if paper_data:
                        papers.append(paper_data)
            
            logger.debug(f"OpenReview search found {len(papers)} matching papers for '{title}'")
            return papers
            
        except Exception as e:
            logger.error(f"Error searching OpenReview by title '{title}': {e}")
            return []

    def _is_title_match(self, search_title: str, found_title: str, threshold: float = 0.8) -> bool:
        """
        Check if two titles match closely enough.
        
        Args:
            search_title: Title we're searching for
            found_title: Title found in search results
            threshold: Similarity threshold (0.0 to 1.0)
            
        Returns:
            True if titles match closely enough
        """
        if not search_title or not found_title:
            return False
        
        # Exact match
        if search_title.lower().strip() == found_title.lower().strip():
            return True
        
        # Check if one contains the other (for cases where one is longer)
        search_clean = search_title.lower().strip()
        found_clean = found_title.lower().strip()
        
        if search_clean in found_clean or found_clean in search_clean:
            return True
        
        # Use similarity calculation from text_utils
        try:
            from refchecker.utils.text_utils import calculate_title_similarity
            similarity = calculate_title_similarity(search_title, found_title)
            return similarity >= threshold
        except ImportError:
            # Fallback to simple word matching
            search_words = set(search_clean.split())
            found_words = set(found_clean.split())
            
            if not search_words or not found_words:
                return False
            
            intersection = search_words.intersection(found_words)
            union = search_words.union(found_words)
            
            jaccard_similarity = len(intersection) / len(union) if union else 0
            return jaccard_similarity >= threshold

    def verify_reference_by_search(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a reference by searching OpenReview (for papers without URLs).
        
        Args:
            reference: Reference data dictionary
            
        Returns:
            Tuple of (verified_data, errors_and_warnings, debug_info)
        """
        title = reference.get('title', '').strip()
        if not title:
            return None, [], "No title provided for search"
        
        # Search for the paper
        search_results = self.search_by_title(title)
        
        if not search_results:
            return None, [], f"No papers found on OpenReview for title: {title}"
        
        # Take the best match (first result, as search is already filtered)
        best_match = search_results[0]
        
        # Use the existing verify_reference method with the found URL
        forum_url = best_match.get('forum_url')
        if forum_url:
            # Create a reference with the OpenReview URL for verification
            reference_with_url = reference.copy()
            reference_with_url['url'] = forum_url
            
            return self.verify_reference(reference_with_url)
        
        # If no URL, return the metadata as verification
        return best_match, [], f"Found on OpenReview: {best_match.get('title')}"