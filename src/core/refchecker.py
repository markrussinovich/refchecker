#!/usr/bin/env python3
"""
ArXiv Reference Checker

This script:
1. Obtains ArXiv metadata from the last year
2. Extracts references from the bibliography (both arXiv and non-arXiv references)
3. Verifies if the references are accurate (author list, year, links)
4. Creates a dataset of incorrect references

For arXiv references, it uses the arXiv API to verify metadata.
For non-arXiv references, it uses the Semantic Scholar API to verify metadata.

Usage:
    python refchecker.py [--max-papers N] [--days N] [--category CATEGORY] [--paper PAPER_SPEC] [--semantic-scholar-api-key KEY] [--db-path PATH]

Options:
    --max-papers N                Maximum number of papers to process (default: 50)
    --days N                      Number of days to look back (default: 365)
    --category CATEGORY           ArXiv category to filter by (e.g., cs.AI, math.CO)
    --debug                       Run in debug mode with verbose logging
    --paper PAPER_SPEC            Validate a specific paper by:
                                    - ArXiv ID (e.g., 1234.5678)
                                    - ArXiv URL (e.g., https://arxiv.org/abs/1234.5678)
                                    - Local PDF file path (e.g., /path/to/paper.pdf)
                                    - Local LaTeX file path (e.g., /path/to/paper.tex)
    --semantic-scholar-api-key KEY API key for Semantic Scholar (optional, increases rate limits)
    --db-path PATH                Path to local Semantic Scholar database (automatically enables local DB mode)
    --help                        Show this help message
"""

import arxiv
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import datetime
import time
import logging
import os
from urllib.parse import urlparse, parse_qs
import csv
from tqdm import tqdm
import PyPDF2
import pdfplumber
import tempfile
import io
import argparse
import sys
import json
import random
from checkers.semantic_scholar import NonArxivReferenceChecker
from checkers.local_semantic_scholar import LocalNonArxivReferenceChecker
from checkers.google_scholar import GoogleScholarReferenceChecker
from utils.text_utils import (clean_author_name, clean_title, normalize_text, 
                       extract_arxiv_id_from_url, clean_conference_markers_from_title,
                       remove_year_from_title)
from utils.author_utils import compare_authors, levenshtein_distance, extract_authors_list
from checkers.hybrid_reference_checker import HybridReferenceChecker
from config.settings import get_config
from llm.base import ReferenceExtractor, create_llm_provider

def setup_logging(debug_mode=False, level=logging.DEBUG):
    """Set up logging configuration"""
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_file = os.path.join(log_dir, f"arxiv_reference_checker_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    
    # Configure root logger to control all child loggers
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove any existing handlers from root logger
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create formatters
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Add file handler with DEBUG level
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # Add console handler with INFO or DEBUG level based on debug_mode
    console_handler = logging.StreamHandler(stream=sys.stdout)
    if debug_mode:
        console_handler.setLevel(logging.DEBUG)
    else:
        console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # Get logger for this module
    logger = logging.getLogger(__name__)
    
    return logger

# Initialize logger (default to INFO for console)
logger = setup_logging(debug_mode=False)

class ArxivReferenceChecker:
    def __init__(self, days_back=365, category=None, semantic_scholar_api_key=None, db_path=None, use_google_scholar=True, output_file="reference_errors.txt", llm_config=None, skip_google_scholar_for_single_paper=False):
        # Initialize the reference checker for non-arXiv references
        # Priority: db_path > semantic_scholar API > google_scholar (reversed priority for better performance)
        self.db_path = db_path
        self.verification_output_file = output_file
        self.skip_google_scholar_for_single_paper = skip_google_scholar_for_single_paper
        
        if db_path:
            logger.info(f"Using local Semantic Scholar database at {db_path} (completely offline mode)")
            self.non_arxiv_checker = LocalNonArxivReferenceChecker(db_path=db_path)
            # Force offline mode - don't use Google Scholar which has online fallbacks
            use_google_scholar = False
            self.service_order = "Local Semantic Scholar Database (offline)"
        elif use_google_scholar and not skip_google_scholar_for_single_paper:
            logger.info("Using Semantic Scholar API as primary source with Google Scholar as fallback")
            # Create a hybrid checker that prioritizes Semantic Scholar
            self.non_arxiv_checker = HybridReferenceChecker(semantic_scholar_api_key)
            self.service_order = "Semantic Scholar API → Google Scholar"
        else:
            logger.info("Using Semantic Scholar API as primary source")
            self.non_arxiv_checker = NonArxivReferenceChecker(semantic_scholar_api_key)
            self.service_order = "Semantic Scholar API"
        
        # Store the original checkers for potential switching during single paper mode
        # Only create hybrid checker if we might need it
        if not db_path and use_google_scholar:
            self.hybrid_checker = HybridReferenceChecker(semantic_scholar_api_key) if not skip_google_scholar_for_single_paper else None
        else:
            self.hybrid_checker = None
        self.semantic_only_checker = NonArxivReferenceChecker(semantic_scholar_api_key) if not db_path else None
        
        # Initialize errors list
        self.errors = []
        
        # Track if we're processing a single paper (for output optimization)
        self.single_paper_mode = False
        self.current_paper_info = None
        
        # Report service order for arXiv lookups
        if not db_path:
            logger.info(f"Service order for arXiv verification: Local DB → Intelligent API Switching (Semantic Scholar ↔ arXiv)")
        else:
            logger.info(f"Service order for arXiv verification: Local DB only (offline mode)")
        
        # Report service order for non-arXiv lookups
        if not db_path:
            logger.info(f"Service order for reference verification: {self.service_order}")
        self.client = arxiv.Client(
            page_size=100,
            delay_seconds=3,  # Rate limiting to avoid overloading the API
            num_retries=5
        )
        self.days_back = days_back
        self.category = category
        
        # Create output directory
        self.output_dir = "output"
        
        # Initialize LLM-based reference extraction
        self.config = get_config()
        self.llm_config_override = llm_config
        self.llm_extractor = self._initialize_llm_extractor()
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        
        # Initialize consolidated error storage
        self.errors = []
        
        # Create or clear output file and write headers
        with open(self.verification_output_file, 'w', encoding='utf-8') as f:
            f.write("REFERENCE VERIFICATION ERRORS\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Service order used: {self.service_order}\n\n")
    
    def _initialize_llm_extractor(self):
        """Initialize LLM-based reference extraction if enabled"""
        # Check if LLM is explicitly disabled
        if self.llm_config_override and self.llm_config_override.get('disabled'):
            logger.info("LLM-based reference extraction disabled via command line")
            return None
            
        # Check if LLM is enabled via command line override or config
        llm_enabled = (self.llm_config_override is not None) or self.config.get("llm", {}).get("enabled", False)
        
        if not llm_enabled:
            return None
        
        # Use command line overrides if provided, otherwise use config
        if self.llm_config_override:
            provider_name = self.llm_config_override['provider']
            provider_config = self.config["llm"].get(provider_name, {}).copy()
            
            # Override with command line parameters
            if self.llm_config_override.get('model'):
                provider_config['model'] = self.llm_config_override['model']
            if self.llm_config_override.get('api_key'):
                provider_config['api_key'] = self.llm_config_override['api_key']
            if self.llm_config_override.get('endpoint'):
                provider_config['endpoint'] = self.llm_config_override['endpoint']
        else:
            provider_name = self.config["llm"]["provider"]
            provider_config = self.config["llm"].get(provider_name, {})
        
        # Create LLM provider
        llm_provider = create_llm_provider(provider_name, provider_config)
        if not llm_provider:
            logger.warning(f"Failed to create LLM provider: {provider_name}")
            return None
        
        # Create reference extractor with fallback
        fallback_enabled = self.config["llm"].get("fallback_enabled", True)
        extractor = ReferenceExtractor(
            llm_provider=llm_provider,
            fallback_enabled=fallback_enabled
        )
        
        logger.info(f"LLM-based reference extraction enabled using {provider_name}")
        return extractor
    
    def batch_prefetch_arxiv_references(self, bibliography):
        """Pre-fetch all ArXiv references in batches to improve performance"""
        if not bibliography:
            return
            
        # Initialize cache if not exists
        if not hasattr(self, '_metadata_cache'):
            self._metadata_cache = {}
        
        # Collect all ArXiv IDs that need to be fetched
        arxiv_ids_to_fetch = []
        for reference in bibliography:
            if reference.get('type') == 'arxiv':
                arxiv_id = self.extract_arxiv_id_from_url(reference.get('url', ''))
                if arxiv_id and arxiv_id not in self._metadata_cache:
                    arxiv_ids_to_fetch.append(arxiv_id)
        
        if not arxiv_ids_to_fetch:
            return
            
        logger.info(f"Pre-fetching {len(arxiv_ids_to_fetch)} ArXiv references in batches...")
        
        # Process in batches to avoid overwhelming the APIs
        batch_size = 10
        for i in range(0, len(arxiv_ids_to_fetch), batch_size):
            batch = arxiv_ids_to_fetch[i:i+batch_size]
            logger.debug(f"Processing batch {i//batch_size + 1}/{(len(arxiv_ids_to_fetch) + batch_size - 1)//batch_size}")
            
            # Try to batch fetch from arXiv API (supports multiple IDs)
            try:
                batch_results = self.batch_fetch_from_arxiv(batch)
                for arxiv_id, metadata in batch_results.items():
                    self._metadata_cache[arxiv_id] = metadata
            except Exception as e:
                logger.warning(f"Batch fetch failed, falling back to individual fetches: {e}")
                # Fallback to individual fetches for this batch
                for arxiv_id in batch:
                    try:
                        metadata = self.get_paper_metadata(arxiv_id)
                        if metadata:
                            self._metadata_cache[arxiv_id] = metadata
                    except Exception as e:
                        logger.debug(f"Failed to fetch {arxiv_id}: {e}")
                        
        logger.info(f"Pre-fetched {len(self._metadata_cache)} ArXiv references")
    
    def batch_fetch_from_arxiv(self, arxiv_ids):
        """Fetch multiple ArXiv papers in a single API call"""
        if not arxiv_ids:
            return {}
            
        # ArXiv API supports multiple IDs in a single request
        id_list = ','.join(arxiv_ids)
        search_query = f"id_list={id_list}"
        
        url = f"https://export.arxiv.org/api/query?{search_query}&max_results={len(arxiv_ids)}"
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse the XML response
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.text)
            
            results = {}
            for entry in root.findall('.//{http://www.w3.org/2005/Atom}entry'):
                # Extract metadata from each entry
                metadata = self.parse_arxiv_entry(entry)
                if metadata and metadata.get('arxiv_id'):
                    results[metadata['arxiv_id']] = metadata
                    
            return results
            
        except Exception as e:
            logger.warning(f"Batch ArXiv fetch failed: {e}")
            return {}
    
    def parse_arxiv_entry(self, entry):
        """Parse a single ArXiv entry from XML response"""
        try:
            # Find the namespace
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            
            # Extract basic information
            title_elem = entry.find('.//atom:title', ns)
            title = title_elem.text.strip() if title_elem is not None else ''
            
            # Extract ArXiv ID from the id field
            id_elem = entry.find('.//atom:id', ns)
            if id_elem is not None:
                arxiv_url = id_elem.text.strip()
                arxiv_id = arxiv_url.split('/')[-1]  # Extract ID from URL
            else:
                return None
            
            # Extract authors
            authors = []
            for author in entry.findall('.//atom:author', ns):
                name_elem = author.find('.//atom:name', ns)
                if name_elem is not None:
                    authors.append(name_elem.text.strip())
            
            # Extract year from published date
            published_elem = entry.find('.//atom:published', ns)
            year = ''
            if published_elem is not None:
                published_date = published_elem.text.strip()
                year = published_date[:4]  # Extract year
            
            # Extract abstract
            summary_elem = entry.find('.//atom:summary', ns)
            abstract = summary_elem.text.strip() if summary_elem is not None else ''
            
            return {
                'arxiv_id': arxiv_id,
                'title': title,
                'authors': authors,
                'year': year,
                'abstract': abstract,
                'url': arxiv_url
            }
            
        except Exception as e:
            logger.debug(f"Failed to parse ArXiv entry: {e}")
            return None
    
    def get_papers_from_last_year(self, max_results=100):
        """
        Fetch papers from the specified time period from ArXiv
        """
        # Calculate date range
        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=self.days_back)
        
        # Format dates for ArXiv query
        date_query = f"submittedDate:[{start_date.strftime('%Y%m%d')}000000 TO {end_date.strftime('%Y%m%d')}235959]"
        
        # Add category filter if specified
        query = date_query
        if self.category:
            query = f"cat:{self.category} AND {query}"
        
        logger.info(f"Fetching papers from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        if self.category:
            logger.info(f"Filtering by category: {self.category}")
        
        # Create search query
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )
        
        # Fetch results
        results = list(self.client.results(search))
        logger.info(f"Retrieved {len(results)} papers")
        return results
    
    def extract_arxiv_id_from_url(self, url):
        """
        Extract ArXiv ID from a URL
        """
        if not url:
            return None

        # Remove version string from end if present (e.g., 'v1')
        url = re.sub(r'v\d+$', '', url)
            
        # Parse URL
        parsed_url = urlparse(url)
        
        # Check if it's an arxiv.org URL
        if 'arxiv.org' in parsed_url.netloc:
            # Extract ID from path
            path = parsed_url.path.strip('/')
            
            # Handle different URL formats
            if path.startswith('abs/'):
                return path.replace('abs/', '')
            elif path.startswith('pdf/'):
                return path.replace('pdf/', '').replace('.pdf', '')
            elif '/abs/' in path:
                return path.split('/abs/')[1]
            elif '/pdf/' in path:
                return path.split('/pdf/')[1].replace('.pdf', '')
            else:
                return path
        
        return None
    
    def get_paper_metadata(self, arxiv_id):
        """
        Get metadata for a paper using its ArXiv ID with intelligent API switching.
        Priority: Local DB > Semantic Scholar API > arXiv API, with fallback switching.
        """
        # First, try to get the paper from local Semantic Scholar database
        logger.info(f"Attempting to fetch {arxiv_id} from local database first")
        local_result = self.get_arxiv_paper_from_local_db(arxiv_id)
        
        if local_result:
            logger.info(f"Successfully found {arxiv_id} in local database")
            return local_result
        
        # Check cache before making API calls
        if hasattr(self, '_metadata_cache') and arxiv_id in self._metadata_cache:
            logger.info(f"Successfully found {arxiv_id} in cache")
            return self._metadata_cache[arxiv_id]
        
        # If not found in local database and we have a local DB, we're done
        if self.db_path:
            logger.warning(f"Paper {arxiv_id} not found in local database")
            return None
        
        # If no local database, try both APIs with intelligent switching
        logger.info(f"Paper {arxiv_id} not found in local database, trying online APIs with intelligent switching")
        return self.get_paper_metadata_with_api_switching(arxiv_id)
    
    def get_paper_metadata_with_api_switching(self, arxiv_id):
        """
        Get paper metadata with intelligent API switching between Semantic Scholar and arXiv APIs
        
        Args:
            arxiv_id: arXiv ID of the paper
            
        Returns:
            Paper object or None if not found
        """
        # Track API performance for this session
        if not hasattr(self, '_api_performance'):
            self._api_performance = {
                'semantic_scholar': {'success': 0, 'rate_limited': 0, 'failed': 0},
                'arxiv': {'success': 0, 'rate_limited': 0, 'failed': 0}
            }
        
        # Try Semantic Scholar API first (faster)
        logger.info(f"Trying Semantic Scholar API for {arxiv_id}")
        semantic_result = self.get_paper_metadata_from_semantic_scholar(arxiv_id)
        
        if semantic_result:
            self._api_performance['semantic_scholar']['success'] += 1
            logger.info(f"Successfully fetched {arxiv_id} from Semantic Scholar API")
            return semantic_result
        
        # If Semantic Scholar failed, try arXiv API
        logger.info(f"Semantic Scholar API failed for {arxiv_id}, trying arXiv API")
        arxiv_result = self.get_paper_metadata_from_arxiv(arxiv_id)
        
        if arxiv_result:
            self._api_performance['arxiv']['success'] += 1
            logger.info(f"Successfully fetched {arxiv_id} from arXiv API")
            return arxiv_result
        
        # If both failed, try reverse order (sometimes one API works when the other doesn't)
        logger.info(f"Both APIs failed for {arxiv_id}, trying reverse order")
        
        # Try arXiv API first this time
        arxiv_result = self.get_paper_metadata_from_arxiv(arxiv_id)
        if arxiv_result:
            self._api_performance['arxiv']['success'] += 1
            logger.info(f"Successfully fetched {arxiv_id} from arXiv API (reverse order)")
            return arxiv_result
        
        # Try Semantic Scholar API again
        semantic_result = self.get_paper_metadata_from_semantic_scholar(arxiv_id)
        if semantic_result:
            self._api_performance['semantic_scholar']['success'] += 1
            logger.info(f"Successfully fetched {arxiv_id} from Semantic Scholar API (reverse order)")
            return semantic_result
        
        # Both APIs failed
        logger.error(f"Paper {arxiv_id} not found in any source")
        return None
    
    def get_paper_metadata_from_semantic_scholar(self, arxiv_id):
        """
        Get paper metadata from Semantic Scholar API
        
        Args:
            arxiv_id: arXiv ID of the paper
            
        Returns:
            MockArxivPaper object or None if not found
        """
        try:
            import requests
            
            url = f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
            params = {
                'fields': 'title,authors,year,externalIds,abstract,url'
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Create a mock arXiv paper object from Semantic Scholar data
                class MockArxivPaper:
                    def __init__(self, data, arxiv_id):
                        self.title = data.get('title', 'Unknown Title')
                        
                        # Create a proper published object with year attribute
                        class MockPublished:
                            def __init__(self, year):
                                self.year = year
                        
                        self.published = MockPublished(data.get('year', 0))
                        
                        # Convert authors to the format expected by the rest of the code
                        authors_data = data.get('authors', [])
                        self.authors = []
                        for author in authors_data:
                            class MockAuthor:
                                def __init__(self, name):
                                    self.name = name
                                def __str__(self):
                                    return self.name
                                def __repr__(self):
                                    return f"MockAuthor('{self.name}')"
                            self.authors.append(MockAuthor(author.get('name', 'Unknown Author')))
                        
                        self.arxiv_id = arxiv_id
                        self.external_ids = data.get('externalIds', {})
                        self.abstract = data.get('abstract', '')
                        self.url = data.get('url', '')
                        
                        # Add pdf_url for compatibility with the rest of the code
                        self.pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                    
                    def get_short_id(self):
                        return self.arxiv_id
                    
                    def __str__(self):
                        return f"MockArxivPaper('{self.title}', {len(self.authors)} authors, {self.published.year})"
                    
                    def __repr__(self):
                        return self.__str__()
                
                return MockArxivPaper(data, arxiv_id)
                
            elif response.status_code == 429:
                self._api_performance['semantic_scholar']['rate_limited'] += 1
                logger.warning(f"Rate limited by Semantic Scholar API for {arxiv_id}")
                return None
            else:
                self._api_performance['semantic_scholar']['failed'] += 1
                logger.warning(f"Semantic Scholar API returned status {response.status_code} for {arxiv_id}")
                return None
                
        except requests.exceptions.RequestException as e:
            self._api_performance['semantic_scholar']['failed'] += 1
            logger.warning(f"Error fetching from Semantic Scholar API for {arxiv_id}: {str(e)}")
            return None
        except Exception as e:
            self._api_performance['semantic_scholar']['failed'] += 1
            logger.warning(f"Unexpected error fetching from Semantic Scholar API for {arxiv_id}: {str(e)}")
            return None
    
    def get_paper_metadata_from_arxiv(self, arxiv_id):
        """
        Get paper metadata from arXiv API
        
        Args:
            arxiv_id: arXiv ID of the paper
            
        Returns:
            ArXiv paper object or None if not found
        """
        try:
            search = arxiv.Search(id_list=[arxiv_id])
            results = list(self.client.results(search))
            
            if results:
                return results[0]
            else:
                self._api_performance['arxiv']['failed'] += 1
                logger.warning(f"Paper {arxiv_id} not found in arXiv API")
                return None
                
        except Exception as e:
            self._api_performance['arxiv']['failed'] += 1
            logger.error(f"Error fetching metadata from arXiv API for {arxiv_id}: {str(e)}")
            return None
    
    def _create_local_file_paper(self, file_path):
        """
        Create a paper object for local PDF, LaTeX, or text files
        
        Args:
            file_path: Path to the local file
            
        Returns:
            Paper object compatible with ArXiv paper interface
        """
        class LocalFilePaper:
            def __init__(self, path):
                self.file_path = path
                self.is_latex = path.lower().endswith('.tex')
                self.is_text_refs = path.lower().endswith('.txt')
                
                # Extract filename without extension for title
                filename = os.path.splitext(os.path.basename(path))[0]
                self.title = filename.replace('_', ' ').title()
                    
                self.authors = []  # Empty list for compatibility
                self.pdf_url = None
                
                class PublishedDate:
                    def __init__(self):
                        self.year = datetime.datetime.now().year
                
                self.published = PublishedDate()
                
            def get_short_id(self):
                filename = os.path.splitext(os.path.basename(self.file_path))[0]
                return f"local_{filename}"
        
        return LocalFilePaper(file_path)

    def get_api_performance_summary(self):
        """
        Get a summary of API performance for this session
        
        Returns:
            Dict with performance statistics
        """
        if not hasattr(self, '_api_performance'):
            return {'message': 'No API calls made yet'}
        
        total_semantic = sum(self._api_performance['semantic_scholar'].values())
        total_arxiv = sum(self._api_performance['arxiv'].values())
        
        summary = {
            'semantic_scholar': {
                'total_calls': total_semantic,
                'success_rate': (self._api_performance['semantic_scholar']['success'] / total_semantic * 100) if total_semantic > 0 else 0,
                'rate_limited': self._api_performance['semantic_scholar']['rate_limited'],
                'failed': self._api_performance['semantic_scholar']['failed'],
                'successful': self._api_performance['semantic_scholar']['success']
            },
            'arxiv': {
                'total_calls': total_arxiv,
                'success_rate': (self._api_performance['arxiv']['success'] / total_arxiv * 100) if total_arxiv > 0 else 0,
                'rate_limited': self._api_performance['arxiv']['rate_limited'],
                'failed': self._api_performance['arxiv']['failed'],
                'successful': self._api_performance['arxiv']['success']
            }
        }
        
        return summary
    
    def download_pdf(self, paper):
        """Download the PDF of a paper and return the content as bytes."""
        # Check if this is a local file
        if hasattr(paper, 'file_path') and paper.file_path:
            logger.info(f"Reading local file: {paper.file_path}")
            try:
                with open(paper.file_path, 'rb') as f:
                    return io.BytesIO(f.read())
            except Exception as e:
                logger.error(f"Failed to read local file {paper.file_path}: {e}")
                return None
        
        # Check if paper.pdf_url is available
        if paper.pdf_url:
            pdf_url = paper.pdf_url
            logger.info(f"Using provided PDF URL: {pdf_url}")
        else:
            # Construct the PDF URL manually from the paper ID
            pdf_url = f"https://arxiv.org/pdf/{paper.get_short_id()}.pdf"
            logger.info(f"PDF URL was None, constructed manually: {pdf_url}")
        
        logger.info(f"Downloading PDF from {pdf_url}")
        
        try:
            response = requests.get(pdf_url, timeout=30)
            response.raise_for_status()
            return io.BytesIO(response.content)
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download PDF for {paper.get_short_id()}: {e}")
            return None

    def extract_text_from_latex(self, latex_file_path):
        """
        Extract text from a LaTeX file
        
        Args:
            latex_file_path: Path to the LaTeX file
            
        Returns:
            String containing the LaTeX file content
        """
        try:
            logger.info(f"Reading LaTeX file: {latex_file_path}")
            with open(latex_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.info(f"Successfully read LaTeX file with {len(content)} characters")
            return content
        except UnicodeDecodeError:
            # Try with latin-1 encoding if utf-8 fails
            try:
                logger.warning(f"UTF-8 encoding failed for {latex_file_path}, trying latin-1")
                with open(latex_file_path, 'r', encoding='latin-1') as f:
                    content = f.read()
                logger.info(f"Successfully read LaTeX file with latin-1 encoding")
                return content
            except Exception as e:
                logger.error(f"Failed to read LaTeX file {latex_file_path} with latin-1: {e}")
                return None
        except Exception as e:
            logger.error(f"Failed to read LaTeX file {latex_file_path}: {e}")
            return None

    def extract_text_from_pdf(self, pdf_content):
        """
        Extract text from a PDF content (BytesIO object)
        """
        if not pdf_content:
            return None
            
        try:
            # Try with PyPDF2 first
            text = ""
            pdf_content.seek(0)  # Reset file pointer
            pdf_reader = PyPDF2.PdfReader(pdf_content)
            
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text += page.extract_text() + "\n"
            
            return text
        except Exception as e:
            logger.error(f"Error extracting text with PyPDF2: {str(e)}")
            
            try:
                # Try with pdfplumber as a fallback
                pdf_content.seek(0)  # Reset file pointer
                with pdfplumber.open(pdf_content) as pdf:
                    text = ""
                    for page in pdf.pages:
                        text += page.extract_text() + "\n"
                    return text
            except Exception as e2:
                logger.error(f"Error extracting text with pdfplumber: {str(e2)}")
                return None
    
    def find_bibliography_section(self, text):
        """
        Find the bibliography section in the text
        """
        if not text:
            logger.warning("No text provided to find_bibliography_section")
            return None
        
        # Log a sample of the text for debugging
        text_sample = text[:500] + "..." if len(text) > 500 else text
        logger.debug(f"Text sample: {text_sample}")
        
        # Common section titles for bibliography
        section_patterns = [
            r'(?i)references\s*\n',
            r'(?i)bibliography\s*\n',
            r'(?i)works cited\s*\n',
            r'(?i)literature cited\s*\n',
            r'(?i)references\s*$',  # End of document
            r'(?i)\[\s*references\s*\]',  # [References]
            r'(?i)^\s*references\s*$',  # References as a standalone line
            r'(?i)^\s*bibliography\s*$',  # Bibliography as a standalone line
            r'(?i)^\s*\d+\.\s*references\s*$',  # Numbered section: 7. References
            r'(?i)references\s*and\s*citations',  # References and Citations
            r'(?i)cited\s*references',  # Cited References
            r'(?i)reference\s*list',  # Reference List
            r'(?i)references\s*cited',  # References Cited
            r'(?i)sources\s*cited',  # Sources Cited
            r'(?i)sources',  # Sources
            r'(?i)references\s*and\s*notes',  # References and Notes
            r'\\begin\{thebibliography\}',  # LaTeX bibliography environment
            r'\\bibliography\{[^}]+\}',  # BibTeX \bibliography{} command
        ]
        
        # Try to find the bibliography section
        bibliography_text = None
        
        for pattern in section_patterns:
            matches = list(re.finditer(pattern, text))
            if matches:
                # Get the last match (in case there are multiple sections with similar names)
                match = matches[-1]
                start_pos = match.end()
                
                logger.debug(f"Found bibliography section with pattern: {pattern}")
                logger.debug(f"Match: {match.group(0)}")
                
                # Find the next section heading or end of document
                # Look for common section endings that come after references
                next_section_patterns = [
                    r'\n\s*[A-Z]\s+[A-Z][A-Za-z\s]*\n',  # A APPENDIX, B RESULTS, etc.
                    r'\n\s*\d+\.\s+[A-Z][A-Za-z\s]*\n',  # Numbered section: 8. Appendix
                    r'\n\s*Appendix\s+[A-Z]',  # Appendix A
                    r'\n\s*\[\s*[A-Za-z\s]+\s*\]',  # [Next Section]
                    r'\n\s*[A-Z][A-Za-z\s]*\n\s*[A-Z][A-Za-z\s]*\n',  # Two consecutive capitalized lines
                    r'\\end\{thebibliography\}',  # LaTeX bibliography environment end
                    r'\\end\{document\}',  # LaTeX document end
                ]
                
                end_pos = len(text)  # Default to end of document
                
                for next_pattern in next_section_patterns:
                    next_match = re.search(next_pattern, text[start_pos:])
                    if next_match:
                        section_end = start_pos + next_match.start()
                        # Only use this end position if it's reasonable (not too close to start)
                        if section_end > start_pos + 100 and section_end < end_pos:
                            end_pos = section_end
                            logger.debug(f"Found section end with pattern: {next_pattern}")
                            logger.debug(f"Section end at position: {section_end}")
                
                bibliography_text = text[start_pos:end_pos]
                
                # Check if we have a reasonable amount of text
                if len(bibliography_text.strip()) < 50:
                    logger.warning(f"Bibliography section seems too short ({len(bibliography_text)} chars), trying another pattern")
                    continue
                
                logger.debug(f"Bibliography section length: {len(bibliography_text)} chars")
                logger.debug(f"Bibliography sample: {bibliography_text[:200]}...")
                
                break
        
        if bibliography_text is None:
            logger.warning("Could not find bibliography section with standard patterns")
            
            # Last resort: look for patterns that might indicate references
            reference_indicators = [
                r'\[\d+\]',  # [1], [2], etc.
                r'\d+\.\s+[A-Z]',  # 1. Author
                r'[A-Z][a-z]+,\s+[A-Z]\.',  # Smith, J.
            ]
            
            for indicator in reference_indicators:
                matches = list(re.finditer(indicator, text))
                if len(matches) > 5:  # If we find multiple matches, it might be a reference section
                    # Find the first match
                    first_match = matches[0]
                    # Look for the beginning of the line
                    line_start = text.rfind('\n', 0, first_match.start())
                    if line_start == -1:
                        line_start = 0
                    else:
                        line_start += 1  # Skip the newline
                    
                    # Take from there to the end
                    bibliography_text = text[line_start:]
                    logger.info(f"Found potential bibliography section using indicator: {indicator}")
                    break
        
        return bibliography_text
    
    def clean_author_name(self, author):
        """
        Clean up an individual author name by fixing common formatting issues.
        
        Args:
            author: The author name string to clean
            
        Returns:
            Cleaned author name string or None if the author should be skipped
        """
        # Skip URLs
        if re.match(r'^https?://', author):
            return None
            
        # Normalize whitespace
        author = re.sub(r'\s+', ' ', author.strip())
        
        # Remove "and" prefix/suffix, trailing commas
        author = re.sub(r'^and\s+', '', author)
        author = re.sub(r'\s+and$', '', author)
        author = re.sub(r',\s*$', '', author)
        
        # Handle "et al" - skip it
        if author.lower() == 'et al' or 'et al.' in author.lower():
            return None
        
        # Handle special case for "Firstname Initial. Lastname"
        name_with_initial_match = re.match(r'^([A-Z][a-z]+)\s+([A-Z])\.?\s+([A-Z][a-z]+)$', author)
        if name_with_initial_match:
            firstname = name_with_initial_match.group(1)
            initial = name_with_initial_match.group(2)
            lastname = name_with_initial_match.group(3)
            author = f"{firstname} {initial}. {lastname}"
        
        # Fix hyphenated names (e.g., "Herbert-V oss" -> "Herbert-Voss")
        author = re.sub(r'-\s+([A-Z])', r'-\1', author)
        
        # Ensure period after single-letter initial if missing
        author = re.sub(r'(\s[A-Z])(\s|$)', r'\1.\2', author)
        
        # Ensure consistent spacing around periods in initials
        author = re.sub(r'\.([A-Z])', r'. \1', author)
        
        # Fix double initials without proper spacing (e.g., "V.V" -> "V. V.")
        author = re.sub(r'([A-Z])\.([A-Z])(?!\w)', r'\1. \2.', author)
        
        # Fix initials with weird spacing (e.g., "V V" -> "V. V.")
        author = re.sub(r'(\s[A-Z])\s+([A-Z](?:\s|$))', r'\1. \2.', author)
        
        if author and not re.match(r'^https?://', author):
            return author
        
        return None
    
    def extract_authors_list(self, authors_text):
        """
        Extract a list of authors from text.
        Handles various formats including names with initials.
        
        Args:
            authors_text: Text containing only the author names
            
        Returns:
            List of author names
        """
        # Check if the text is a URL
        if re.match(r'^https?://', authors_text):
            # This is a URL, not an author list
            return [{"is_url_reference": True}]
        
        # Normalize whitespace and fix line breaks in names
        authors_text = re.sub(r'\s+', ' ', authors_text).strip()
        
        # Handle cases like "Vinyals & Kaiser" -> "Vinyals, Kaiser"
        authors_text = re.sub(r'([A-Za-z]+)\s*&\s*([A-Za-z]+)', r'\1, \2', authors_text)
        
        # Fix common hyphenation issues from line breaks (e.g., "Fredrik- son" -> "Fredrikson")
        authors_text = re.sub(r'([a-z])- ([a-z])', r'\1\2', authors_text, flags=re.IGNORECASE)
        
        # Normalize spacing around periods
        authors_text = re.sub(r'([A-Z])\s+\.\s+', r'\1. ', authors_text)
        
        # Fix issues with spaces between initials (e.g., "V . Le" -> "V. Le")
        authors_text = re.sub(r'([A-Z])\s+\.\s*([A-Z])', r'\1. \2', authors_text)
        authors_text = re.sub(r'([A-Z])\s+\.\s*([a-z])', r'\1. \2', authors_text)
        
        # Check if we potentially have a full reference instead of just authors
        # Look for patterns that indicate this might include the title
        # Be more specific: look for period followed by what looks like a title (multiple words, starting with capital)
        # This should match title patterns but not author name patterns like "J. Zico"
        title_pattern = r'\.\s+([A-Z]\w+(?:\s+\w+){2,})'  # Capital word followed by at least 2 more words
        if re.search(title_pattern, authors_text) and ',' in authors_text:
            # This appears to be a complete reference, not just authors
            # Only take the part before the title
            match = re.search(title_pattern, authors_text)
            if match:
                title_start = match.start()
                authors_text = authors_text[:title_start].strip()
        
        # Check if the author list follows the pattern: "Author1, Author2, and Author3"
        # This is the most common format in academic citations
        
        # First, handle the case where "and" appears before the last author
        and_parts = re.split(r'\s+and\s+', authors_text, 1)
        
        if len(and_parts) > 1:
            # We have a list with "and" (e.g., "Author1, Author2, and Author3")
            main_list = and_parts[0].strip()
            last_author = and_parts[1].strip()
            
            # Split the main list by commas
            authors = [a.strip() for a in main_list.split(',') if a.strip()]
            
            # Add the last author
            if last_author:
                authors.append(last_author)
        else:
            # No "and" found, just split by commas
            authors = [a.strip() for a in authors_text.split(',') if a.strip()]
        
        # Clean up each author name
        cleaned_authors = []
        for author in authors:
            cleaned_author = self.clean_author_name(author)
            if cleaned_author:
                cleaned_authors.append(cleaned_author)
        
        return cleaned_authors
    
    def clean_title(self, title):
        """
        Clean up a title by fixing hyphenation and other formatting issues.
        
        Args:
            title: The title string to clean
            
        Returns:
            Cleaned title string
        """
        if not title:
            return ""
            
        # Fix hyphenation due to line breaks (remove hyphens at end of words)
        title = re.sub(r'([a-z])- ([a-z])', r'\1\2', title, flags=re.IGNORECASE)
        
        # Additional hyphenation patterns that might appear in academic papers
        title = re.sub(r'([a-z])-\n([a-z])', r'\1\2', title, flags=re.IGNORECASE) # Hyphen with newline
        title = re.sub(r'([a-z])-$([a-z])', r'\1\2', title, flags=re.IGNORECASE)  # Hyphen at line end
        
        # Normalize whitespace
        title = re.sub(r'\s+', ' ', title).strip()
        
        # Replace common words that sometimes get split across library/document names
        title = re.sub(r'(?i)ll ms\b', 'llms', title)  # Fix "ll ms" to "llms"
        
        # Remove URLs and DOIs from titles
        title = self.remove_urls_from_title(title)
        
        title = self.remove_year_from_title(title)
        title = self.clean_conference_markers_from_title(title)
        return title
    
    def remove_urls_from_title(self, title):
        """
        Remove URLs and DOIs from titles.
        
        Args:
            title: The title string to clean
            
        Returns:
            Title string with URLs and DOIs removed
        """
        if not title:
            return ""
        
        # Remove DOI URLs
        title = re.sub(r'\s*https?://doi\.org/[^\s]+', '', title, flags=re.IGNORECASE)
        
        # Remove other URLs
        title = re.sub(r'\s*https?://[^\s]+', '', title, flags=re.IGNORECASE)
        
        # Remove arXiv IDs that might be in titles
        title = re.sub(r'\s*arXiv:\d+\.\d+(?:v\d+)?', '', title, flags=re.IGNORECASE)
        
        # Clean up any trailing punctuation and whitespace
        title = re.sub(r'\s*[.,;:]+\s*$', '', title)
        title = title.strip()
        
        return title
    
    def clean_conference_markers_from_title(self, title):
        """
        Remove conference markers like "In Conference Name" from titles.
        
        Args:
            title: The title string to clean
                
        Returns:
            Cleaned title string without conference markers
        """
        # Common conference markers to remove
        conference_patterns = [
            r'\s+In\s+(?:Advances|Proceedings|Conference|Journal).*$',
            r'\s+In\s+NIPS.*$',
            r'\s+In\s+NeurIPS.*$',
            r'\s+In\s+ICLR.*$',
            r'\s+In\s+ICML.*$',
            r'\s+In\s+ACL.*$',
            r'\s+In\s+EMNLP.*$',
        ]
        
        # Try each pattern
        for pattern in conference_patterns:
            title = re.sub(pattern, '', title, flags=re.IGNORECASE)
        
        return title.strip()
    
    def remove_year_from_title(self, title):
        """
        Remove year (e.g., '2023', '2021') from the beginning or end of a title.
        
        Args:
            title: The title to clean
            
        Returns:
            Title with year removed if it was at the beginning or end
        """
        if not title:
            return ""
        
        # Pattern for year at the beginning (e.g., "2024. Title")
        year_match = re.search(r'^(19|20)\d{2}\.?\s*', title)
        if year_match:
            # Remove the year from the beginning
            title = title[year_match.end():].strip()
        
        # Pattern for year format with comma (e.g., ", 2023")
        year_match = re.search(r',\s*(19|20)\d{2}\.?$', title)
        if year_match:
            # Remove the year and any trailing comma
            title = title[:year_match.start()].strip()
            return title
        
        # Pattern for year at the end without comma (e.g., "2023" or "2023.")
        year_match = re.search(r'\s+(19|20)\d{2}\.?$', title)
        if year_match:
            # Remove the year at the end
            title = title[:year_match.start()].strip()
            return title
        
        # Remove duplicate years in parentheses like "(2023)" if it appears after a year
        title = re.sub(r'\.\s*\((19|20)\d{2}\)', '.', title)
        
        return title
    
    def extract_authors_title_from_academic_format(self, ref_text):
        """
        Improved function to extract authors and title from academic paper reference format.
        Handles various formats including cases with periods in author names.
        
        Args:
            ref_text: The reference text to parse
            
        Returns:
            Tuple of (authors list, title) or None if extraction failed
        """
        # First, normalize the text - replace newlines with spaces
        cleaned_ref = re.sub(r'\s+', ' ', ref_text).strip()
        
        # Fix common hyphenation issues from line breaks BEFORE pattern matching
        # This handles cases like "Fredrik- son" -> "Fredrikson"
        cleaned_ref = re.sub(r'([a-z])- ([a-z])', r'\1\2', cleaned_ref, flags=re.IGNORECASE)
        
        # Remove any leading reference numbers like [1]
        cleaned_ref = re.sub(r'^\s*\[\d+\]\s*', '', cleaned_ref)
        
        # Handle specific problematic cases from the bibliography
        # Case 1: Legal cases like "[1]1976. Tarasoff v. Regents of University of California - 17 Cal.3d 425"
        legal_case_match = re.search(r'^(\d{4})\.\s+([^.]+?)\s+https?://', cleaned_ref)
        if legal_case_match:
            year = legal_case_match.group(1)
            title = legal_case_match.group(2).strip()
            return [year], title
            
        # Case 2: References with year at start like "1976. Title"
        year_start_match = re.search(r'^(\d{4})\.\s+([^.]+?)(?:\.\s+https?://|\.\s*$)', cleaned_ref)
        if year_start_match:
            year = year_start_match.group(1)
            title = year_start_match.group(2).strip()
            return [year], title
        
        # Case 3: Legal cases with reference number and year like "[1]1976. Title"
        legal_case_with_ref_match = re.search(r'^\[\d+\](\d{4})\.\s+([^.]+?)(?:\.\s+https?://|\.\s*$)', cleaned_ref)
        if legal_case_with_ref_match:
            year = legal_case_with_ref_match.group(1)
            title = legal_case_with_ref_match.group(2).strip()
            return [year], title
        
        # Normalize spacing around periods
        cleaned_ref = re.sub(r'([A-Z])\s+\.\s+', r'\1. ', cleaned_ref)
        cleaned_ref = re.sub(r'([A-Z])\s+\.([A-Za-z])', r'\1. \2', cleaned_ref)

        # Check if this is a URL-based reference (common in some papers)
        if re.match(r'^https?://', cleaned_ref):
            # This is likely a URL reference, not a standard academic citation
            url_match = re.search(r'(https?://[^\s]+)', cleaned_ref)
            if url_match:
                # Extract the URL
                url = url_match.group(1).strip()
                
                # For URL references, extract any remaining text as title
                remaining_text = cleaned_ref.replace(url, '').strip()
                # Remove trailing periods and clean up
                remaining_text = re.sub(r'^\s*[.\s]*|[.\s]*$', '', remaining_text)
                
                # Return a special marker to indicate this is a URL reference
                return [{"is_url_reference": True}], remaining_text if remaining_text else url
        
        # Also check if the reference contains only a URL (possibly with some ID)
        if re.search(r'^https?://[^\s]+(?:\s+[A-Za-z0-9\-]+)*\s*\.?\s*$', cleaned_ref):
            # This is likely just a URL with maybe some ID
            url_match = re.search(r'(https?://[^\s]+)', cleaned_ref)
            if url_match:
                url = url_match.group(1).strip()
                remaining_text = cleaned_ref.replace(url, '').strip()
                # Remove trailing periods and clean up
                remaining_text = re.sub(r'^\s*[.\s]*|[.\s]*$', '', remaining_text)
                
                return [{"is_url_reference": True}], remaining_text if remaining_text else url
            
        # Special case for authors with last names that end right before title
        # Handle patterns like "... and Quoc V. Le. Multi-task ..." 
        # Be more careful to avoid splitting names like "Le" from "Quoc V. Le"
        
        # Handle references with year between authors and title
        # Pattern: "Authors. YEAR. Title: Subtitle. URL" - for cases like the Hashimoto reference
        year_between_authors_title_match = re.search(r'(.*?)\.\s+(19|20)\d{2}\.\s+([^:]+:[^.]*?)\.\s+(https?://[^\s]+)', cleaned_ref)
        if year_between_authors_title_match:
            authors_text = year_between_authors_title_match.group(1).strip()
            title = year_between_authors_title_match.group(3).strip()
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)
            
            if authors and title:
                return authors, title
        
        # First try: Look for arXiv format specifically - most reliable
        arxiv_specific_match = re.search(r'(.*?)\.\s+([A-Z][^.]{1,100}?[.!?]?)\s+arXiv\s+preprint\s+arXiv:', cleaned_ref)
        if arxiv_specific_match:
            authors_text = arxiv_specific_match.group(1).strip()
            title = arxiv_specific_match.group(2).strip()
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)
            
            if authors and title:
                return authors, title
        
        # Try to find the pattern for references with years at the end
        # Pattern: "Authors. Title, YEAR." - but NOT "Authors. Title. Journal, Volume:Pages, YEAR." 
        # and NOT "Authors. Title. In Conference, pages X-Y, YEAR."
        # Make sure we don't match references that have journal volume info or conference proceedings
        year_at_end_match = re.search(r'(.*?)\.\s+([^.]+?),\s+(19|20)\d{2}\.?\s*$', cleaned_ref)
        if year_at_end_match:
            # Check if the "title" contains patterns that indicate this is actually venue/journal info
            potential_title = year_at_end_match.group(2).strip()
            authors_and_title = year_at_end_match.group(1).strip()
            
            # Skip if the "title" looks like journal volume info: "Journal Name , Volume:Pages"
            if re.search(r'.+\s*,\s*\d+(\(\d+\))?:\d+', potential_title):
                pass  # Skip this pattern
            # Skip if the "title" looks like conference proceedings: "In Conference", "InConference", or "In Conference, pages X-Y"
            elif re.match(r'^In[A-Z]', potential_title) or potential_title.startswith('In '):
                pass  # Skip this pattern - it's clearly a venue/conference name
            # Skip if the authors+title part contains obvious venue indicators that suggest wrong parsing
            elif re.search(r'\.\s+(In\s+.*|Proceedings\s+of|Conference\s+on)\s*$', authors_and_title):
                pass  # Skip this pattern
            else:
                # This looks like a legitimate "Authors. Title, Year." pattern
                authors_text = authors_and_title
                title = potential_title
                
                # Extract authors
                authors = self.extract_authors_list(authors_text)
                
                # Clean the title
                title = self.clean_title(title)
                
                if authors and title:
                    return authors, title
        
        # Try pattern for references where title ends with period and year is at end
        # Pattern: "Authors. Title. YEAR." 
        year_at_end_with_period_match = re.search(r'(.*?)\.\s+([^.]+?)\.\s+(19|20)\d{2}\.?\s*$', cleaned_ref)
        if year_at_end_with_period_match:
            authors_text = year_at_end_with_period_match.group(1).strip()
            title = year_at_end_with_period_match.group(2).strip()
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)
            
            if authors and title:
                return authors, title
        
        # Second try: Look for patterns with common academic reference formats
        # Pattern 1: Authors ending with initials and common last names before title
        author_name_patterns = [
            # Pattern for "... and FirstName LastInitial. LastName. Title."
            r'(.*\s+and\s+[A-Z][a-z]+\s+[A-Z]\.\s+[A-Z][a-z]{1,10})\.\s+(.*?)(?:\.\s+(?:In|CoRR|arXiv|Journal|Proceedings))',
            # Pattern for "... and FirstName LastName. Title."
            r'(.*\s+and\s+[A-Z][a-z]+\s+[A-Z][a-z]+)\.\s+(.*?)(?:\.\s+(?:In|CoRR|arXiv|Journal|Proceedings))',
        ]
        
        for pattern in author_name_patterns:
            author_name_at_title_match = re.search(pattern, cleaned_ref)
            if author_name_at_title_match:
                authors_text = author_name_at_title_match.group(1).strip()
                title = author_name_at_title_match.group(2).strip()
                
                # Extract authors
                authors = self.extract_authors_list(authors_text)
                
                # Clean the title
                title = self.clean_title(title)
                
                if authors and title:
                    return authors, title
        
        # Special cases: check for common patterns where the title is incorrectly extracted
        # Check for arXiv preprint format that might confuse the parser
        arxiv_preprint_match = re.search(r'(.*?)\.\s+(.*?[.!?]?)\s+arXiv\s+preprint\s+arXiv:', cleaned_ref)
        if arxiv_preprint_match:
            authors_text = arxiv_preprint_match.group(1).strip()
            title = arxiv_preprint_match.group(2).strip()
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)
            
            if authors and title:
                return authors, title
        
        # Handle conference proceedings format with improved pattern matching
        # Handle both "In Conference" and cases where "In" is attached to conference name like "InInternational"
        # Be more careful about author name parsing - look for full name patterns
        conference_match = re.search(r'(.*?(?:\s+[A-Z][a-z]*\.?\s*)*)\.\s+([^.]+?)\.\s+In(?:\s+|(?=[A-Z]))(.*?)(?:,|\s+\(|\s+\d{4})', cleaned_ref)
        if conference_match:
            authors_text = conference_match.group(1).strip()
            title = conference_match.group(2).strip()
            
            # Additional check: if the title starts with what looks like a last name, 
            # it's probably part of the author list that got misplaced
            if re.match(r'^[A-Z][a-z]+\.?\s+', title):
                # Try a different approach - look for common author ending patterns
                author_ending_patterns = [
                    r'(.*?\s+and\s+[A-Z][a-z]+\s+[A-Z]\.?\s+[A-Z][a-z]+)\.\s+([^.]+?)\.\s+In(?:\s+|(?=[A-Z]))',
                    r'(.*?\s+[A-Z][a-z]+\s+[A-Z]\.?\s+[A-Z][a-z]+)\.\s+([^.]+?)\.\s+In(?:\s+|(?=[A-Z]))',
                ]
                
                for pattern in author_ending_patterns:
                    alt_match = re.search(pattern, cleaned_ref)
                    if alt_match:
                        authors_text = alt_match.group(1).strip()
                        title = alt_match.group(2).strip()
                        break
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)
            
            if authors and title:
                return authors, title

        # Handle specific problematic cases from the bibliography
        # Case 3: Alexander Street Press references with incomplete titles
        alexander_street_match = re.search(r'Alexander Street Press \(Ed\.\)\.\s+(\d{4})\.\s+([^.]+?)(?:\.\s+Alexander Street Press|\.\s*$)', cleaned_ref)
        if alexander_street_match:
            year = alexander_street_match.group(1)
            title = alexander_street_match.group(2).strip()
            return ["Alexander Street Press (Ed.)"], title
            
        # Case 4: References with incomplete author names like "Alan S." and "Tara F."
        incomplete_author_match = re.search(r'([A-Z][a-z]+ [A-Z]\.)\s+(\d{4})\.\s+([^.]+?)(?:\.\s+[A-Z][a-z]+|\.\s*$)', cleaned_ref)
        if incomplete_author_match:
            author = incomplete_author_match.group(1).strip()
            year = incomplete_author_match.group(2)
            title = incomplete_author_match.group(3).strip()
            return [author], title
            
        # Case 5: References with complete author lists but incomplete titles
        complete_author_incomplete_title_match = re.search(r'([^.]+?)\.\s+(\d{4})\.\s+([^.]+?)(?:\.\s+[A-Z][a-z]+|\.\s*$)', cleaned_ref)
        if complete_author_incomplete_title_match:
            authors_text = complete_author_incomplete_title_match.group(1).strip()
            year = complete_author_incomplete_title_match.group(2)
            title = complete_author_incomplete_title_match.group(3).strip()
            authors = self.extract_authors_list(authors_text)
            if authors and title:
                return authors, title

        # Handle CoRR format specifically - very common in CS papers
        # Pattern: "Authors. Title. CoRR abs/ID, YEAR." - handle titles with question marks
        corr_match = re.search(r'(.*?)\.\s+([^?]+\?)\s*CoRR\s+abs/([^,\s]+)\s*,?\s+(19|20)\d{2}', cleaned_ref)
        if not corr_match:
            # Fallback pattern for titles without question marks
            corr_match = re.search(r'(.*?)\.\s+([^.]+?)\.\s+CoRR\s+abs/([^,\s]+)\s*,?\s+(19|20)\d{2}', cleaned_ref)
        
        if corr_match:
            authors_text = corr_match.group(1).strip()
            title = corr_match.group(2).strip()
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)

            if authors and title:
                return authors, title
        
        # Handle references with titles that start with colons and URLs at the end
        # Pattern: "Authors. Title: Subtitle. URL" - specifically for cases like "Stanford Alpaca: An Instruction-following LLaMA model"
        colon_title_url_match = re.search(r'(.*?)\.\s+([^:]+:[^.]*?)\.\s+(https?://[^\s]+)', cleaned_ref)
        if colon_title_url_match:
            authors_text = colon_title_url_match.group(1).strip()
            title = colon_title_url_match.group(2).strip()
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)
            
            if authors and title:
                return authors, title
        
        # Handle journal format with volume:pages - Pattern: "Authors. Title. Journal, Volume:Pages, Year"
        journal_volume_match = re.search(r'(.*?)\.\s+([^.]+?)\.\s+([^,]+)\s*,\s*\d+(\(\d+\))?:\d+[^,]*,\s+(19|20)\d{2}', cleaned_ref)
        if journal_volume_match:
            authors_text = journal_volume_match.group(1).strip()
            title = journal_volume_match.group(2).strip()
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)
            
            if authors and title:
                return authors, title
        
        # Handle journal format with venue information
        # Pattern: "Authors. Title. Journal/Venue info, Year."
        journal_match = re.search(r'(.*?)\.\s+([^.]+?)\.\s+([^,]+),\s+(19|20)\d{2}', cleaned_ref)
        if journal_match:
            authors_text = journal_match.group(1).strip()
            title = journal_match.group(2).strip()
            venue = journal_match.group(3).strip()
            
            # Check if the venue contains volume/page info - this is a good sign that we have the right split
            # Pattern like "Journal Name , Volume:Pages" or "Journal Name, Volume(Issue):Pages"
            if re.search(r'.+\s*,\s*\d+(\(\d+\))?:\d+', venue):
                # This looks like "Journal Name , Volume:Pages" - this is correct
                # Extract authors
                authors = self.extract_authors_list(authors_text)
                
                # Clean the title
                title = self.clean_title(title)
                
                if authors and title:
                    return authors, title
            
            # Check if what we think is the title is actually venue information
            # Common venue patterns that shouldn't be titles: "CoRR abs/...", but not things like "Nature Machine Intelligence"
            venue_indicators_in_title = ['CoRR abs/', 'arXiv:', 'IEEE Transactions', 'ACM Transactions']
            if any(indicator in title for indicator in venue_indicators_in_title):
                # The "title" is likely venue info, this pattern doesn't apply
                return None
            
            # For normal journal references, the extraction should be correct
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)
            
            if authors and title:
                return authors, title
        
        # Handle journal format
        journal_match = re.search(r'(.*?)\.\s+(.*?)\.\s+(?:Journal|Proceedings|IEEE|ACM)', cleaned_ref)
        if journal_match:
            authors_text = journal_match.group(1).strip()
            title = journal_match.group(2).strip()
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)
            
            if authors and title:
                return authors, title
        
        # Pattern to find title after authors in standard academic format
        # Authors. Title. Venue, Year.
        # Improved to handle author names with initials like "J. Zico Kolter"
        # Look for patterns where authors end and title begins
        
        # Strategy: Look for a period that's likely to separate authors from title
        # This should be after a complete author name, not after an initial
        author_title_patterns = [
            # Pattern 1: Look for author lists ending with "and FirstName LastName." followed by title
            r'(.*\s+and\s+[A-Z][a-z]+\s+[A-Z][a-z]+)\.\s+([A-Z][^.]+?)\.\s+',
            # Pattern 2: Look for author lists ending with "FirstName LastName." followed by title  
            r'(.*[A-Z][a-z]+\s+[A-Z][a-z]+)\.\s+([A-Z][^.]+?)\.\s+',
            # Pattern 3: Look for author lists with initials ending with "Initial LastName." followed by title
            r'(.*[A-Z]\.\s+[A-Z][a-z]+)\.\s+([A-Z][^.]+?)\.\s+',
        ]
        
        authors_text = None
        title = None
        
        for pattern in author_title_patterns:
            pattern_match = re.search(pattern, cleaned_ref)
            if pattern_match:
                authors_text = pattern_match.group(1).strip()
                title = pattern_match.group(2).strip()
                break
        
        # If no specific pattern matched, fall back to the original simple pattern but with validation
        if not authors_text or not title:
            simple_pattern = re.search(r'([^\.]+)\.([^\.]+)\.', cleaned_ref)
            if simple_pattern:
                potential_authors = simple_pattern.group(1).strip()
                potential_title = simple_pattern.group(2).strip()
                # Only use this if the potential_title doesn't look like part of author names
                if not re.match(r'^\s*[A-Z][a-z]*(?:\s+[A-Z][a-z]*)*(?:,\s*and\s+)?', potential_title):
                    authors_text = potential_authors
                    title = potential_title
        
        # Fallback: if the reference is just a comma-separated list of names, treat as authors
        if not title and not authors_text:
            # Try to detect a list of names
            if re.match(r'^[A-Z][a-zA-Z\-\.]+(,\s*[A-Z][a-zA-Z\-\.]+)+$', cleaned_ref):
                authors = [a.strip() for a in cleaned_ref.split(',')]
                return authors, ""
        
        if authors_text and title:
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            # Clean the title
            title = self.clean_title(title)
            if authors and title:
                return authors, title
        
        # Final fallback: if the reference is just a list of names, return as authors
        if not title and cleaned_ref and re.match(r'^[A-Z][a-zA-Z\-\.]+(,\s*[A-Z][a-zA-Z\-\.]+)+$', cleaned_ref):
            authors = [a.strip() for a in cleaned_ref.split(',')]
            return authors, ""
        
        # Fallback: if the reference is just a list of author names (with initials, and 'and' before last author), treat as authors
        if not title and not authors_text:
            # Match patterns like 'Tara F. Bishop, Matthew J. Press, Salomeh Keyhani, and Harold Alan Pincus'
            author_list_pattern = r'^(?:[A-Z][a-zA-Z\-]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-zA-Z\-]+)?(?:,\s+)?)+(?:and\s+[A-Z][a-zA-Z\-]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-zA-Z\-]+)?)?$'
            if re.match(author_list_pattern, cleaned_ref.replace(' and ', ', and ')):
                # Split on ', ' and ' and ' for the last author
                authors = re.split(r',\s+|\s+and\s+', cleaned_ref)
                authors = [a.strip() for a in authors if a.strip()]
                return authors, ""
        
        return None
    
    def verify_db_reference(self, source_paper, reference, db_conn):
        """
        Verify a reference using local database with specific query order
        
        Args:
            source_paper: The paper containing the reference
            reference: The reference to verify
            db_conn: Database connection object
                
        Returns:
            List of errors or None if no errors found
        """
        import sqlite3
        import json
        import time
        
        # Get reference fields
        title = reference.get('title', '').strip()
        authors = reference.get('authors', [])
        year = reference.get('year', 0)
        url = reference.get('url', '')
        doi = None
        if 'doi' in reference and reference['doi']:
            doi = reference['doi']
        elif url and 'doi.org' in url:
            doi_match = re.search(r'doi\.org/([^/\s]+)', url)
            if doi_match:
                doi = doi_match.group(1)

        # VALIDATION: Skip empty or invalid searches that could cause hanging queries
        if not title or len(title) < 3:
            logger.debug(f"DB Verification: Skipping empty/short title: '{title}'")
            return [{"error_type": "unverified", "error_details": f'Title too short or empty: "{title}"'}]
        
        logger.debug(f"DB Verification: Starting verification for reference - Title: '{title}', Authors: {authors}, Year: {year}")
        
        cursor = db_conn.cursor()
        paper_data = None
        search_strategy = None
        
        # Strategy 3: Search by normalized paper title
        if title:
            normalized_title = self.non_arxiv_checker.normalize_paper_title(title) if hasattr(self.non_arxiv_checker, 'normalize_paper_title') else title.lower().replace(' ', '').replace('.', '').replace(',', '')
            
            # VALIDATION: Skip empty normalized titles
            if not normalized_title or len(normalized_title) < 3:
                logger.debug(f"DB Verification: Skipping empty/short normalized title: '{normalized_title}'")
                return [{"error_type": "unverified", "error_details": f'Normalized title too short or empty: "{normalized_title}"'}]
            
            logger.debug(f"DB Verification: Trying normalized title search for: '{normalized_title}'")
            
            query = "SELECT * FROM papers WHERE normalized_paper_title = ?"
            params = [normalized_title]
            
            logger.debug(f"DB Query [Normalized title search]: {query}")
            logger.debug(f"DB Params: {params}")

            start_time = time.time()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            execution_time = time.time() - start_time

            logger.debug(f"DB Execution Time: {execution_time:.3f}s")
            logger.debug(f"DB Result Count: {len(rows)}")

            if len(rows) > 1:
                for row in rows:
                    check_paper_data = dict(row)
                    check_paper_data['authors'] = json.loads(check_paper_data['authors'])

                    # check if the authors match
                    if authors:
                        db_authors = [author.get('name', '') for author in check_paper_data['authors']]

                        authors_match, author_error = self.compare_authors(authors, db_authors)
                        if authors_match:
                            paper_data = check_paper_data
                            search_strategy = "Normalized title with author match"
                            break

            elif len(rows) == 1:
                row = rows[0]
                paper_data = dict(row)
                search_strategy = "Normalized title"
        
        # Strategy 4: Search by paper title (exact match)
        if not paper_data and title:
            logger.debug(f"DB Verification: Trying exact title search for: '{title}'")
            query = "SELECT * FROM papers WHERE title = ?"
            params = [title]
            
            logger.debug(f"DB Query [Exact title search]: {query}")
            logger.debug(f"DB Params: {params}")

            start_time = time.time()
            cursor.execute(query, params)
            row = cursor.fetchone()
            execution_time = time.time() - start_time
            
            logger.debug(f"DB Execution Time: {execution_time:.3f}s")
            logger.debug(f"DB Result Count: {1 if row else 0}")
            
            if row:
                paper_data = dict(row)
                search_strategy = "Exact title"
        
        #  Search by DOI        
        if not paper_data and doi and self.is_valid_doi(doi):
            logger.debug(f"DB Verification: Trying DOI search for: {doi}")
            query = "SELECT * FROM papers WHERE externalIds_DOI = ?"
            params = [doi]
            
            start_time = time.time()
            cursor.execute(query, params)
            row = cursor.fetchone()
            execution_time = time.time() - start_time
            
            logger.debug(f"DB Query [DOI search]: {query}")
            logger.debug(f"DB Params: {params}")
            logger.debug(f"DB Execution Time: {execution_time:.3f}s")
            logger.debug(f"DB Result Count: {1 if row else 0}")
            
            if row:
                paper_data = dict(row)
                search_strategy = "DOI"
        
        # Strategy 2: Search by ArXiv ID
        if not paper_data and reference.get('type') == 'arxiv':
            arxiv_id = self.extract_arxiv_id_from_url(reference['url'])
            if arxiv_id:
                logger.debug(f"DB Verification: Trying ArXiv ID search for: {arxiv_id}")
                query = "SELECT * FROM papers WHERE externalIds_ArXiv = ?"
                params = [arxiv_id]
                
                logger.debug(f"DB Query [ArXiv ID search]: {query}")
                logger.debug(f"DB Params: {params}")

                start_time = time.time()
                cursor.execute(query, params)
                row = cursor.fetchone()
                execution_time = time.time() - start_time

                logger.debug(f"DB Execution Time: {execution_time:.3f}s")
                logger.debug(f"DB Result Count: {1 if row else 0}")
                
                if row:
                    paper_data = dict(row)
                    search_strategy = "ArXiv ID"
                
        # If no paper found, return unverified
        if not paper_data:
            logger.debug("DB Verification: No matching paper found in database")
            return [{"error_type": "unverified", "error_details": "Reference could not be found in local database"}]
        
        logger.debug(f"DB Verification: Found paper using {search_strategy} - Title: '{paper_data.get('title', '')}', Year: {paper_data.get('year', '')}")
        
        # Process the paper data
        try:
            # Extract authors from JSON
            if isinstance(paper_data['authors'], str) and len(paper_data['authors']) > 0:
                paper_data['authors'] = json.loads(paper_data['authors'])
            elif not isinstance(paper_data['authors'], list):
                paper_data['authors'] = []
            
            # Reconstruct external IDs from flattened columns
            external_ids = {}
            for key, value in paper_data.items():
                if key.startswith('externalIds_') and value:
                    external_id_type = key.replace('externalIds_', '')
                    external_ids[external_id_type] = value
            paper_data['externalIds'] = external_ids
            
        except Exception as e:
            logger.warning(f"Error processing paper data: {e}")
            return [{"error_type": "unverified", "error_details": "Error processing paper data from database"}]
        
        # Verify the reference
        errors = []

        # verify title
        if title and paper_data.get('title'):
            normalized_title = self.non_arxiv_checker.normalize_paper_title(title) if hasattr(self.non_arxiv_checker, 'normalize_paper_title') else title.lower().replace(' ', '').replace('.', '').replace(',', '')
            db_title = self.non_arxiv_checker.normalize_paper_title(paper_data.get('title'))
            
            if normalized_title != db_title:
                logger.debug(f"DB Verification: Title mismatch - cited: '{title}', actual: '{paper_data.get('title')}'")
                errors.append({
                    'error_type': 'title',
                    'error_details': f"Title mismatch: cited as '{title}' but actually '{paper_data.get('title')}'",
                    'ref_title_correct': paper_data.get('title')
                })
        
        # Verify authors
        if authors and paper_data.get('authors'):
            # Extract author names from database data
            correct_names = [author.get('name', '') for author in paper_data['authors']]
            authors_match, author_error = self.compare_authors(authors, correct_names)
            
            if not authors_match:
                logger.debug(f"DB Verification: Author mismatch - {author_error}")
                errors.append({
                    'error_type': 'author',
                    'error_details': author_error,
                    'ref_authors_correct': ', '.join(correct_names)
                })
        
        # Verify year
        paper_year = paper_data.get('year')
        if year and paper_year and year != paper_year:
            logger.debug(f"DB Verification: Year mismatch - cited: {year}, actual: {paper_year}")
            errors.append({
                'warning_type': 'year',
                'warning_details': f"Year mismatch: cited as {year} but actually {paper_year}",
                'ref_year_correct': paper_year
            })
        
        # Verify DOI
        if doi and external_ids.get('DOI') and doi.lower() != external_ids['DOI'].lower():
            # Check if the cited DOI is a partial match of the actual DOI
            # This handles cases like "10.1111/j.2044-8260." vs "10.1111/J.2044-8260.1997.TB01237.X"
            cited_doi_clean = doi.lower().rstrip('.')
            actual_doi_clean = external_ids['DOI'].lower().rstrip('.')
            
            # If the cited DOI is a prefix of the actual DOI, it's likely a partial citation
            # Only flag as error if it's not a reasonable partial match
            if not actual_doi_clean.startswith(cited_doi_clean):
                logger.debug(f"DB Verification: DOI mismatch - cited: {doi}, actual: {external_ids['DOI']}")
                errors.append({
                    'error_type': 'doi',
                    'error_details': f"DOI mismatch: cited as {doi} but actually {external_ids['DOI']}",
                    'ref_doi_correct': external_ids['DOI']
                })
            else:
                logger.debug(f"DB Verification: DOI partial match - cited: {doi}, actual: {external_ids['DOI']} (acceptable)")

        # Verify ArXiv ID
        if reference.get('type') == 'arxiv':
            ref_arxiv_id = self.extract_arxiv_id_from_url(reference['url'])
            db_arxiv_id = external_ids.get('ArXiv', '')
            
            if ref_arxiv_id and db_arxiv_id and ref_arxiv_id.lower() != db_arxiv_id.lower():
                logger.debug(f"DB Verification: ArXiv ID mismatch - cited: {ref_arxiv_id}, actual: {db_arxiv_id}")
                errors.append({
                    'error_type': 'arxiv',
                    'error_details': f"ArXiv ID mismatch: cited as {ref_arxiv_id} but actually {db_arxiv_id}",
                    'ref_arxiv_correct': db_arxiv_id
                })
        
        if errors:
            logger.debug(f"DB Verification: Found {len(errors)} errors")
        else:
            logger.debug("DB Verification: No errors found")
        
        return errors if errors else None
    
    def verify_reference(self, source_paper, reference):
        """
        Verify if a reference is accurate
        
        Args:
            source_paper: The paper containing the reference
            reference: The reference to verify
                
        Returns:
            List of errors or None if no errors found
        """
        # Check if reference authors contains "URL Reference" marker
        if reference.get('authors') and "URL Reference" in reference.get('authors', []):
            # Skip verification for URL references
            return None
        
        # If database mode is enabled, use database for all references
        if self.db_path:
            # Use the database connection from the non_arxiv_checker
            if hasattr(self.non_arxiv_checker, 'conn'):
                db_conn = self.non_arxiv_checker.conn
                return self.verify_db_reference(source_paper, reference, db_conn)
            else:
                logger.warning("Database path specified but no connection available")
                return [{"error_type": "unverified", "error_details": "Database connection not available"}]
        
        # Check if it's an arXiv reference
        if reference.get('type') == 'arxiv':
            return self.verify_arxiv_reference(source_paper, reference)
        else:
            return self.verify_non_arxiv_reference(source_paper, reference)
    
    def verify_arxiv_reference(self, source_paper, reference):
        """
        Verify if an arXiv reference is accurate
        
        Args:
            source_paper: The paper containing the reference
            reference: The reference to verify
            
        Returns:
            List of errors or None if no errors found
        """
        # Extract ArXiv ID from reference URL
        ref_arxiv_id = self.extract_arxiv_id_from_url(reference['url'])
        
        if not ref_arxiv_id:
            # Mark as unverified instead of no errors
            return [{"error_type": "unverified", "error_details": "Could not extract arXiv ID from URL"}]
        
        # Get correct metadata for the reference
        correct_paper = self.get_paper_metadata(ref_arxiv_id)
        
        if not correct_paper:
            logger.warning(f"Could not fetch metadata for reference {ref_arxiv_id}")
            # Mark as unverified instead of no errors
            return [{"error_type": "unverified", "error_details": f"Could not fetch metadata for ArXiv ID: {ref_arxiv_id}"}]
        
        errors = []
        
        # Check authors
        authors_match, author_error = self.compare_authors(
            reference['authors'], 
            [author.name for author in correct_paper.authors]
        )
        
        if not authors_match:
            errors.append({
                'error_type': 'author',
                'error_details': author_error,
                'ref_authors_correct': ', '.join([author.name for author in correct_paper.authors])
            })
        
        # Check year
        paper_year = correct_paper.published.year
        
        # Only flag year warnings if the difference is significant (more than 1 year)
        # This helps with preprints that may have a different publication year
        if reference['year'] != 0 and abs(reference['year'] - paper_year) > 1:
            errors.append({
                'warning_type': 'year',
                'warning_details': f"Year mismatch: cited as {reference['year']} but actually {paper_year}",
                'ref_year_correct': paper_year
            })
        
        # Check URL
        correct_url = f"https://arxiv.org/abs/{correct_paper.get_short_id()}"
        
        # Extract the base URL (without version) for comparison
        # For example, from "https://arxiv.org/abs/1234.56789v2" to "https://arxiv.org/abs/1234.56789"
        ref_id = self.extract_arxiv_id_from_url(reference['url'])
        correct_id = self.extract_arxiv_id_from_url(correct_url)
        
        # Remove version numbers for comparison
        if ref_id and correct_id:
            ref_id_base = ref_id.split('v')[0] if 'v' in ref_id else ref_id
            correct_id_base = correct_id.split('v')[0] if 'v' in correct_id else correct_id
            
            # Only flag URL errors if the base IDs are different
            # This is more lenient with version numbers, which are often omitted in citations
            if ref_id_base != correct_id_base:
                errors.append({
                    'error_type': 'url',
                    'error_details': f"URL mismatch: cited as {reference['url']} but actually {correct_url}",
                    'ref_url_correct': correct_url
                })
        elif not ref_id:
            errors.append({
                'error_type': 'url',
                'error_details': f"Could not extract arXiv ID from URL: {reference['url']}",
                'ref_url_correct': correct_url
            })
        
        return errors if errors else None

    def verify_non_arxiv_reference(self, source_paper, reference):
        """
        Verify if a non-arXiv reference is accurate using Semantic Scholar
        
        Args:
            source_paper: The paper containing the reference
            reference: The reference to verify
            
        Returns:
            List of errors or None if no errors found
        """
        logger.info(f"Verifying non-arXiv reference: {reference.get('title', 'Untitled')}")
        
        # Use the Semantic Scholar client to verify the reference
        verified_data, errors = self.non_arxiv_checker.verify_reference(reference)
        
        if not verified_data:
            logger.warning(f"Could not verify non-arXiv reference: {reference.get('title', 'Untitled')}")
            logger.warning(f"Raw text: {reference['raw_text']}")
            # Mark as unverified instead of no errors
            return [{"error_type": "unverified", "error_details": "Reference could not be verified"}]
        
        # If no errors were found by the Semantic Scholar client, we're done
        if not errors:
            return None
        
        # Convert the errors to our format
        formatted_errors = []
        
        for error in errors:
            formatted_error = {}
            
            # Handle error_type and warning_type properly
            if 'error_type' in error:
                formatted_error['error_type'] = error['error_type']
                formatted_error['error_details'] = error['error_details']
            elif 'warning_type' in error:
                formatted_error['warning_type'] = error['warning_type']
                formatted_error['warning_details'] = error['warning_details']
            
            # Add correct information based on error type
            if error.get('error_type') == 'author':
                formatted_error['ref_authors_correct'] = error.get('ref_authors_correct', '')
            elif error.get('error_type') == 'year' or error.get('warning_type') == 'year':
                formatted_error['ref_year_correct'] = error.get('ref_year_correct', '')
            elif error.get('error_type') == 'doi':
                formatted_error['ref_url_correct'] = f"https://doi.org/{error.get('ref_doi_correct', '')}"
            
            formatted_errors.append(formatted_error)
        
        return formatted_errors if formatted_errors else None
    
    def add_error_to_dataset(self, source_paper, reference, errors):
        """
        Add an error entry to the consolidated dataset
        """
        for error in errors:
            # Determine if this is an error or warning
            error_type = error.get('error_type') or error.get('warning_type', 'unknown')
            error_details = error.get('error_details') or error.get('warning_details', '')
            
            # Include unverified references in the output
            error_entry = {
                # Source paper metadata
                'source_paper_id': source_paper.get_short_id(),
                'source_title': source_paper.title,
                'source_authors': ', '.join([author.name for author in source_paper.authors]),
                'source_year': source_paper.published.year,
                'source_url': f"https://arxiv.org/abs/{source_paper.get_short_id()}",
                
                # Reference metadata as cited
                'ref_paper_id': self.extract_arxiv_id_from_url(reference['url']),
                'ref_title': reference.get('title', ''),
                'ref_authors_cited': ', '.join(reference['authors']),
                'ref_year_cited': reference['year'],
                'ref_url_cited': reference['url'],
                'ref_raw_text': reference.get('raw_text', ''),
                
                # Error information
                'error_type': error_type,
                'error_details': error_details
            }
            
            # Add correct information based on error type
            if error_type == 'author':
                error_entry['ref_authors_correct'] = error.get('ref_authors_correct', '')
            elif error_type == 'year':
                error_entry['ref_year_correct'] = error.get('ref_year_correct', '')
            elif error_type == 'url':
                error_entry['ref_url_correct'] = error.get('ref_url_correct', '')
            
            # Add standard format using the correct information (only for non-unverified errors)
            if error_type != 'unverified':
                error_entry['ref_standard_format'] = self.format_standard_reference(error)
            else:
                error_entry['ref_standard_format'] = None
            
            # Store error in memory
            self.errors.append(error_entry)
            
            # Write error to file immediately
            self.write_error_to_file(error_entry)
                
    def write_error_to_file(self, error_entry):
        """
        Write a single error entry to the output file
        """
        try:
            with open(self.verification_output_file, 'a', encoding='utf-8') as f:
                # For single paper mode, only write paper info once
                if self.single_paper_mode and self.current_paper_info:
                    # Check if this is the first error for this paper
                    if not hasattr(self, '_paper_info_written'):
                        f.write(f"\nPAPER: {self.current_paper_info['title']}\n")
                        f.write(f"ArXiv ID: {self.current_paper_info['id']}\n")
                        f.write(f"URL: {self.current_paper_info['url']}\n")
                        f.write(f"Authors: {self.current_paper_info['authors']}\n")
                        f.write(f"Year: {self.current_paper_info['year']}\n")
                        f.write("-" * 80 + "\n")
                        self._paper_info_written = True
                else:
                    # Multi-paper mode - write paper info for each error
                    f.write(f"\nPAPER: {error_entry['source_title']}\n")
                    f.write(f"ArXiv ID: {error_entry['source_paper_id']}\n")
                    f.write(f"URL: {error_entry['source_url']}\n")
                    f.write(f"Authors: {error_entry['source_authors']}\n")
                    f.write(f"Year: {error_entry['source_year']}\n")
                    f.write("-" * 80 + "\n")
                
                f.write(f"REFERENCE: {error_entry['ref_title']}\n")
                f.write(f"Type: {error_entry['error_type']}\n")
                f.write(f"Details: {error_entry['error_details']}\n\n")
                
                f.write("AS CITED:\n")
                f.write(f"  Authors: {error_entry['ref_authors_cited']}\n")
                f.write(f"  Year: {error_entry['ref_year_cited']}\n")
                if error_entry['ref_url_cited']:
                    f.write(f"  URL: {error_entry['ref_url_cited']}\n")
                
                # For unverified references, show the raw text as well
                if error_entry['error_type'] == 'unverified':
                    f.write(f"  Raw text: {error_entry.get('ref_raw_text', 'N/A')}\n")
                
                f.write("\n")
                
                # Show correct information if available
                if error_entry['error_type'] != 'unverified' and any([
                    error_entry.get('ref_authors_correct'),
                    error_entry.get('ref_year_correct'),
                    error_entry.get('ref_url_correct')
                ]):
                    f.write("CORRECT INFORMATION:\n")
                    if error_entry.get('ref_authors_correct'):
                        f.write(f"  Authors: {error_entry['ref_authors_correct']}\n")
                    if error_entry.get('ref_year_correct'):
                        f.write(f"  Year: {error_entry['ref_year_correct']}\n")
                    if error_entry.get('ref_url_correct'):
                        f.write(f"  URL: {error_entry['ref_url_correct']}\n")
                    f.write("\n")
                
                # Show standard format if available
                if error_entry.get('ref_standard_format'):
                    f.write("STANDARD FORMAT:\n")
                    f.write(f"  {error_entry['ref_standard_format']}\n")
                    f.write("\n")
                
                f.write("=" * 80 + "\n")
                
        except Exception as e:
            logger.error(f"Error writing to output file: {str(e)}")
    
    def run(self, max_papers=50, debug_mode=False, specific_paper_id=None, local_pdf_path=None):
        """
        Run the reference checking process
        
        Args:
            max_papers: Maximum number of papers to process
            debug_mode: If True, use verbose logging; if False, use pretty printing
            specific_paper_id: If provided, only process this specific paper
            local_pdf_path: If provided, process this local PDF or LaTeX file instead of fetching from ArXiv
        """
        # Reconfigure logger for this run
        global logger
        logger = setup_logging(debug_mode=debug_mode)
        
        logger.info("Starting ArXiv reference checking process")
        
        # Initialize counters for statistics
        self.total_papers_processed = 0
        self.total_references_processed = 0
        self.papers_with_errors = 0
        self.papers_with_warnings = 0
        self.total_errors_found = 0
        self.total_warnings_found = 0
        self.total_arxiv_refs = 0
        self.total_non_arxiv_refs = 0
        self.total_other_refs = 0
        self.total_unverified_refs = 0
        
        try:
            # Get papers to process
            if specific_paper_id:
                # Process a specific paper
                logger.info(f"Processing specific paper with ID: {specific_paper_id}")
                paper = self.get_paper_metadata(specific_paper_id)
                if not paper:
                    logger.error(f"Could not find paper with ID: {specific_paper_id}")
                    return None
                papers = [paper]
                # Set single paper mode
                self.single_paper_mode = True
                
                # Switch to Semantic Scholar-only mode for better performance
                if self.skip_google_scholar_for_single_paper and self.semantic_only_checker:
                    logger.info("Switching to Semantic Scholar-only mode for single paper processing")
                    self.non_arxiv_checker = self.semantic_only_checker
                
                self.current_paper_info = {
                    'title': paper.title,
                    'id': paper.get_short_id(),
                    'url': f"https://arxiv.org/abs/{paper.get_short_id()}",
                    'authors': ', '.join([author.name for author in paper.authors]),
                    'year': paper.published.year
                }
                # Reset paper info written flag
                if hasattr(self, '_paper_info_written'):
                    delattr(self, '_paper_info_written')
            elif local_pdf_path:
                # Process a local PDF or LaTeX file
                logger.info(f"Processing local file: {local_pdf_path}")
                paper = self._create_local_file_paper(local_pdf_path)
                papers = [paper]
                # Set single paper mode
                self.single_paper_mode = True
                
                # Switch to Semantic Scholar-only mode for better performance
                if self.skip_google_scholar_for_single_paper and self.semantic_only_checker:
                    logger.info("Switching to Semantic Scholar-only mode for single paper processing")
                    self.non_arxiv_checker = self.semantic_only_checker
                
                self.current_paper_info = {
                    'title': paper.title,
                    'id': paper.get_short_id(),
                    'url': f"file://{os.path.abspath(local_pdf_path)}",
                    'authors': ', '.join(paper.authors) if paper.authors else 'Unknown',
                    'year': paper.published.year
                }
                # Reset paper info written flag
                if hasattr(self, '_paper_info_written'):
                    delattr(self, '_paper_info_written')
            else:
                # Get papers from the specified time period
                papers = self.get_papers_from_last_year(max_results=max_papers)
                self.single_paper_mode = False
            
            # Process each paper
            if self.single_paper_mode and len(papers) == 1:
                # No progress bar for single paper
                paper_iterator = papers
            else:
                # Show progress bar for multiple papers
                paper_iterator = tqdm(papers, desc="Processing papers")
                
            for paper in paper_iterator:
                paper_id = paper.get_short_id()
                paper_url = f"https://arxiv.org/abs/{paper_id}"
                
                
                # Log paper info
                logger.info(f"Processing paper: {paper.title} ({paper_id})")
                
                # Print paper heading in non-debug mode
                if not debug_mode:
                    print(f"\n📄 Processing: {paper.title}")
                    print(f"   URL: {paper_url}")
                
                try:
                    # Extract bibliography
                    bibliography = self.extract_bibliography(paper, debug_mode)
                    
                    # Update statistics
                    self.total_papers_processed += 1
                    self.total_references_processed += len(bibliography)
                    
                    # Count references by type
                    arxiv_refs = [ref for ref in bibliography if ref.get('type') == 'arxiv']
                    non_arxiv_refs = [ref for ref in bibliography if ref.get('type') == 'non-arxiv']
                    other_refs = [ref for ref in bibliography if ref.get('type') == 'other']
                    
                    self.total_arxiv_refs += len(arxiv_refs)
                    self.total_non_arxiv_refs += len(non_arxiv_refs)
                    self.total_other_refs += len(other_refs)
                    
                    # Track errors for this paper
                    paper_errors = []
                    error_types = {}
                    unverified_count = 0  # Count unverified references
                    
                    # Pre-fetch all ArXiv references in batches for better performance
                    self.batch_prefetch_arxiv_references(bibliography)
                    
                    # Check each reference
                    for i, reference in enumerate(bibliography):
                        ref_id = self.extract_arxiv_id_from_url(reference['url'])
                        
                        # Print reference info in non-debug mode (improved formatting)
                        if not debug_mode:
                            title = reference.get('title', 'Untitled')
                            authors = ', '.join(reference.get('authors', []))
                            year = reference.get('year', '')
                            venue = reference.get('venue', '')
                            print(f"[{i+1}/{len(bibliography)}] {title}")
                            if authors:
                                print(f"       {authors}")
                            if venue:
                                print(f"       {venue}")
                            print(f"       {year}")
                        # --- DEBUG TIMER ---
                        start_time = time.time()
                        errors = self.verify_reference(paper, reference)
                        elapsed = time.time() - start_time
                        if elapsed > 5.0:
                            logger.warning(f"Reference {i+1} took {elapsed:.2f}s to verify: {reference.get('title', 'Untitled')}")
                            logger.warning(f"Raw text: {reference.get('raw_text', '')}")
                        
                        # If errors found, add to dataset and print details
                        if errors:
                            # Check if the reference is just unverified
                            if len(errors) == 1 and (errors[0].get('error_type') == 'unverified' or errors[0].get('warning_type') == 'unverified'):
                                unverified_count += 1
                                self.total_unverified_refs += 1
                                # Add unverified reference to dataset
                                self.add_error_to_dataset(paper, reference, errors)
                                if not debug_mode:
                                    # Show full citation details for unverified references
                                    print(f"      ❓ Could not verify: {reference.get('title', 'Untitled')}")
                                    print(f"         Cited as: {', '.join(reference['authors'])} ({reference['year']})")
                                    if reference['url']:
                                        print(f"         URL: {reference['url']}")
                            else:
                                # Real errors or warnings found
                                self.add_error_to_dataset(paper, reference, errors)
                                paper_errors.extend(errors)
                                
                                # Count errors vs warnings
                                error_count = sum(1 for e in errors if 'error_type' in e and e['error_type'] != 'unverified')
                                warning_count = sum(1 for e in errors if 'warning_type' in e)
                                self.total_errors_found += error_count
                                self.total_warnings_found += warning_count
                                
                                if not debug_mode:
                                    # Always show errors and warnings if they exist
                                    for error in errors:
                                        if 'error_type' in error and error['error_type'] != 'unverified':
                                            print(f"       ❌  {error['error_type']}: {error['error_details']}")
                                        elif 'warning_type' in error:
                                            print(f"       ⚠️  {error['warning_type']}: {error['warning_details']}")
                    if not debug_mode:
                        # Separate actual errors from warnings for paper classification
                        actual_errors = [e for e in paper_errors if 'error_type' in e and e['error_type'] != 'unverified']
                        warnings_only = [e for e in paper_errors if 'warning_type' in e]
                        
                        if actual_errors or warnings_only:
                            summary_parts = []
                            if actual_errors:
                                summary_parts.append(f"{len(actual_errors)} errors")
                                self.papers_with_errors += 1
                            if warnings_only:
                                summary_parts.append(f"{len(warnings_only)} warnings")
                                # Count as paper with warnings if it has warnings (regardless of errors)
                                self.papers_with_warnings += 1
                            print(f"   📊 Paper summary: {', '.join(summary_parts)} found")
                        else:
                            print(f"   📊 Paper summary: No errors found")
                    
                    
                except Exception as e:
                    logger.error(f"Error processing paper {paper_id}: {str(e)}")
                    if not debug_mode:
                        print(f"\n  ❌  Error: Failed to process paper")
                
                # Sleep to avoid overloading the ArXiv API
                sleep_time = random.uniform(1, 3)  # Random sleep between 1-3 seconds
                time.sleep(sleep_time)
            
        except KeyboardInterrupt:
            logger.info("Process interrupted by user.")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during processing: {str(e)}")
            raise
        
        # Print final summary to console
        if not debug_mode:
            print(f"\n" + "="*60)
            print(f"📋 FINAL SUMMARY")
            print(f"="*60)
            print(f"📄 Total papers processed: {self.total_papers_processed}")
            print(f"📚 Total references processed: {self.total_references_processed}")
            print(f"❌ Papers with errors:   {self.papers_with_errors}")
            print(f"         Total errors:   {self.total_errors_found}")
            print(f"⚠️  Papers with warnings: {self.papers_with_warnings}")
            print(f"         Total warnings: {self.total_warnings_found}")
            print(f"❓ References that couldn't be verified: {self.total_unverified_refs}")
            print(f"\n💾 Detailed results saved to: {self.verification_output_file}")
        
        return self.verification_output_file
    
    def format_standard_reference(self, error):
        """
        Format a reference in standard ArXiv format
        
        Args:
            error: Error dictionary containing correct reference information
            
        Returns:
            String in standard ArXiv format
        """
        try:
            # Use correct information if available, otherwise fall back to cited information
            authors = error.get('ref_authors_correct') or error.get('ref_authors_cited', '')
            year = error.get('ref_year_correct') or error.get('ref_year_cited', '')
            title = error.get('ref_title', '')
            url = error.get('ref_url_correct') or error.get('ref_url_cited', '')
            
            # Format in standard academic format
            formatted = ""
            
            if authors:
                # Limit to first 3 authors for readability
                author_list = [a.strip() for a in authors.split(',')]
                if len(author_list) > 3:
                    formatted += ", ".join(author_list[:3]) + " et al."
                else:
                    formatted += authors
                formatted += ". "
            
            if title:
                formatted += f'"{title}". '
            
            if url and 'arxiv.org' in url:
                # Extract ArXiv ID
                arxiv_match = re.search(r'(\d+\.\d+(?:v\d+)?)', url)
                if arxiv_match:
                    arxiv_id = arxiv_match.group(1)
                    formatted += f"arXiv preprint arXiv:{arxiv_id}. "
            
            if year:
                formatted += f"({year})"
            
            return formatted.strip()
            
        except Exception as e:
            logger.error(f"Error formatting standard reference: {str(e)}")
            return ""
    
    def extract_authors_title_fallback(self, ref_text):
        """
        Fallback method to extract authors and title when the main method fails.
        
        Args:
            ref_text: The reference text to parse
            
        Returns:
            Tuple of (authors list, title)
        """
        # Normalize the text
        cleaned_ref = re.sub(r'\s+', ' ', ref_text).strip()
        
        # Remove any reference number
        cleaned_ref = re.sub(r'^\s*\[\d+\]\s*', '', cleaned_ref)
        
        # Check if this is a URL reference
        if re.match(r'^https?://', cleaned_ref):
            url_match = re.search(r'(https?://[^\s]+)', cleaned_ref)
            if url_match:
                url = url_match.group(1).strip()
                return [{"is_url_reference": True}], cleaned_ref.replace(url, '').strip()
        
        # Try to find anything that looks like a title (text between quotes)
        title_match = re.search(r'[""]([^""]+)[""]', cleaned_ref)
        if title_match:
            title = title_match.group(1).strip()
            # If we found a title in quotes, try to extract authors before it
            before_title = cleaned_ref[:title_match.start()].strip()
            # Process authors text
            authors = self.extract_authors_list(before_title)
            
            # Clean the title
            title = self.clean_title(title)
            
            return authors, title
        
        # Look for common patterns that indicate the end of authors and beginning of title
        # This is typically a period followed by a capitalized word
        
        # Check for specific keywords that often appear after title
        title_end_markers = [
            r'\.\s+arXiv',
            r'\.\s+In\s+',
            r'\.\s+CoRR',
            r'\.\s+Proceedings',
            r'\.\s+Journal',
            r'\.\s+IEEE',
            r'\.\s+ACM',
        ]
        
        for marker in title_end_markers:
            match = re.search(marker, cleaned_ref)
            if match:
                # Found a marker, now find the period before it that separates authors and title
                text_before_marker = cleaned_ref[:match.start()]
                period_match = re.search(r'\.', text_before_marker)
                
                if period_match:
                    # We found a period that likely separates authors and title
                    authors_text = cleaned_ref[:period_match.start()].strip()
                    title_text = text_before_marker[period_match.end():].strip()
                    
                    # Extract authors
                    authors = self.extract_authors_list(authors_text)
                    
                    # Clean the title
                    title_text = self.clean_title(title_text)                    
                    return authors, title_text
        
        # Look for pattern with publication indicator (e.g., "CoRR abs/...")
        corr_match = re.search(r'(CoRR\s+abs\/[\d\.]+)', cleaned_ref)
        if corr_match:
            corr_pos = corr_match.start()
            # Now find the periods before this point
            periods_before = [m.start() for m in re.finditer(r'\.', cleaned_ref[:corr_pos])]
            
            if len(periods_before) >= 2:
                # First period likely separates authors from title
                first_period = periods_before[0]
                # Second period likely ends the title
                second_period = periods_before[1]
                
                authors_text = cleaned_ref[:first_period].strip()
                title_text = cleaned_ref[first_period+1:second_period].strip()
                
                # Extract authors
                authors = self.extract_authors_list(authors_text)
                
                # Clean the title
                title_text = self.clean_title(title_text)
                return authors, title_text
        
        # If we get here, try a simple split by the first period
        parts = cleaned_ref.split('.', 1)
        
        if len(parts) > 1:
            authors_text = parts[0].strip()
            title = parts[1].strip()
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)            
            return authors, title
        
        # If nothing else worked, try to find year and use it as a separator
        year_match = re.search(r'\b(19|20)\d{2}\b', cleaned_ref)
        if year_match:
            year_pos = year_match.start()
            # Everything before the year might be authors
            authors_text = cleaned_ref[:year_pos].strip()
            # Everything after could be title
            title = cleaned_ref[year_pos:].strip()
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = self.clean_title(title)
            return authors, title
        
        # If all else fails, return placeholder values
        return ["Unknown Author"], "Untitled Reference"
    
    def parse_references(self, bibliography_text):
        """
        Parse references from bibliography text
        """
        if not bibliography_text:
            logger.warning("No bibliography text provided to parse_references")
            return []
        
        # Log a sample of the bibliography text for debugging
        bib_sample = bibliography_text[:500] + "..." if len(bibliography_text) > 500 else bibliography_text
        logger.debug(f"Bibliography sample: {bib_sample}")

        # Try LLM-based extraction first if available
        if self.llm_extractor:
            try:
                references = self.llm_extractor.extract_references(
                    bibliography_text, 
                    fallback_func=self._parse_references_regex
                )
                if references:
                    logger.info(f"Successfully parsed {len(references)} references")
                    return self._process_llm_extracted_references(references)
            except Exception as e:
                logger.error(f"LLM reference extraction failed: {e}")
        
        # Fallback to regex-based parsing
        return self._parse_references_regex(bibliography_text)
    
    def _parse_references_regex(self, bibliography_text):
        """
        Parse references using regex-based approach (original implementation)
        """
        # --- IMPROVED SPLITTING: handle concatenated references like [3]... [4]... ---
        # First, normalize the bibliography text to ensure proper spacing after reference numbers
        normalized_bib = re.sub(r'(\[\d+\])([A-Za-z])', r'\1 \2', bibliography_text)
        
        
        # Handle the case where the last reference might be incomplete
        # Check if the text ends with a reference number followed by content
        if re.search(r'\[\d+\][^[]*$', normalized_bib):
            # The last reference is incomplete, try to find a better ending
            # Look for the last complete sentence or period
            last_period = normalized_bib.rfind('.')
            if last_period > 0:
                # Find the last reference number before this period
                last_ref_match = re.search(r'\[\d+\][^[]*?\.', normalized_bib[:last_period+1])
                if last_ref_match:
                    # Truncate at the last complete reference
                    normalized_bib = normalized_bib[:last_period+1]
        
        numbered_ref_pattern = r'(\[\d+\])'
        numbered_refs = re.split(numbered_ref_pattern, normalized_bib)
        references = []
        if len(numbered_refs) > 1:
            # Reconstruct references, as split removes the delimiter
            temp = []
            for part in numbered_refs:
                if re.match(r'^\[\d+\]$', part):
                    if temp:
                        references.append(''.join(temp).strip())
                        temp = []
                    temp.append(part)
                else:
                    temp.append(part)
            if temp:
                references.append(''.join(temp).strip())
            # Remove empty or very short entries
            references = [r for r in references if len(r.strip()) > 5]
            # Ensure the last chunk is included if not already
            if numbered_refs[-1].strip() and not any(numbered_refs[-1].strip() in r for r in references):
                references.append(numbered_refs[-1].strip())
        else:
            # Fallback to original logic if not numbered
            # Try different splitting strategies
            splitting_strategies = [
                (r'\[\d+\]', lambda x: [r.strip() for r in x if r.strip()]),
                (r'\n\s*\d+\.\s+', lambda x: x[1:] if not x[0].strip() else x),
                (r'\n\s*\([A-Za-z]+(?:\s+et\s+al\.)?(?:,\s+\d{4})\)\s+', lambda x: x),
                (r'\n\s*\n', lambda x: x),
            ]
            for pattern, processor in splitting_strategies:
                split_refs = re.split(pattern, normalized_bib)
                if len(split_refs) > 1:
                    references = processor(split_refs)
                    logger.debug(f"Split bibliography using pattern: {pattern}")
                    logger.debug(f"Found {len(references)} potential references")
                    break
        if not references:
            references = [line.strip() for line in normalized_bib.split('\n') if line.strip()]
            logger.debug(f"Using line-by-line splitting, found {len(references)} potential references")
        references = [ref.strip() for ref in references if ref.strip()]

        # --- POST-PROCESSING: fix malformed DOIs/URLs and edge cases ---
        def clean_url(url):
            if not url:
                return url
            url = url.strip()
            # Remove trailing punctuation
            url = re.sub(r'[\.,;:]+$', '', url)
            # Fix common malformed DOI/URL
            if url.startswith('https://doi') and not re.match(r'https://doi.org/\S+', url):
                url = ''
            if url == 'https://doi' or url == 'https://doi.org/10.':
                url = ''
            return url
        def clean_doi(doi):
            if not doi or doi == '10.':
                return None
            return doi

        arxiv_refs = []
        non_arxiv_refs = []
        other_refs = []
        arxiv_patterns = [
            r'arxiv\.org/[^\s,\)]+',
            r'arxiv\.org/pdf/\d+\.\d+(?:v\d+)?',
            r'arxiv\.org/abs/\d+\.\d+(?:v\d+)?',
            r'arxiv:\s*(\d+\.\d+(?:v\d+)?)',
            r'arXiv preprint arXiv:(\d+\.\d+(?:v\d+)?)',
            r'CoRR abs/(\d+\.\d+(?:v\d+)?)',
        ]
        doi_patterns = [
            r'doi\.org/([^\s,\)]+)',
            r'doi:([^\s,\)]+)',
            r'DOI:([^\s,\)]+)',
        ]
        url_patterns = [
            r'https?://(?!arxiv\.org)[^\s,\)]+(?:\.(?=\s|$))?',
        ]
        for i, ref in enumerate(references):
            arxiv_id = None
            arxiv_url = None
            for pattern in arxiv_patterns:
                arxiv_match = re.search(pattern, ref, re.IGNORECASE)
                if arxiv_match:
                    if 'arxiv.org' in arxiv_match.group(0).lower():
                        arxiv_url = arxiv_match.group(0)
                        if not arxiv_url.startswith('http'):
                            arxiv_url = 'https://' + arxiv_url
                    else:
                        try:
                            arxiv_id = arxiv_match.group(1)
                            arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
                        except IndexError:
                            arxiv_url = f"https://arxiv.org/abs/{arxiv_match.group(0)}"
                    break
            if arxiv_url:
                # ... existing arxiv extraction logic ...
                ref_without_arxiv_id = ref
                if arxiv_url:
                    arxiv_id_match = re.search(r'\b\d{4}\.\d{4,5}(?:v\d+)?\b', ref)
                    if arxiv_id_match:
                        ref_without_arxiv_id = ref.replace(arxiv_id_match.group(0), '')
                year = None
                end_year_match = re.search(r',\s+((19|20)\d{2})\s*\.?\s*$', ref_without_arxiv_id)
                if end_year_match:
                    year = int(end_year_match.group(1))
                else:
                    year_patterns = [
                        r'(?:preprint|abs/[^,]+),?\s+((19|20)\d{2})',
                        r'(?:CoRR|arXiv),?\s+[^,]*,?\s+((19|20)\d{2})',
                        r'(?:In|Proceedings)[^,]*,?\s+((19|20)\d{2})',
                    ]
                    for pattern in year_patterns:
                        pattern_match = re.search(pattern, ref_without_arxiv_id)
                        if pattern_match:
                            year = int(pattern_match.group(1))
                            break
                    if year is None:
                        all_years = re.findall(r'\b((19|20)\d{2})\b', ref_without_arxiv_id)
                        if all_years:
                            valid_years = []
                            for potential_year, _ in all_years:
                                page_pattern = rf'\d+\([^)]*\):\d*{potential_year}'
                                if not re.search(page_pattern, ref_without_arxiv_id):
                                    valid_years.append(int(potential_year))
                            if valid_years:
                                year = valid_years[-1]
                if year is None:
                    year_match = re.search(r'\b(19|20)\d{2}\b', ref)
                    year = int(year_match.group(0)) if year_match else None
                if year is None and arxiv_url:
                    arxiv_id_match = re.search(r'\b(\d{4})\.\d{4,5}(?:v\d+)?\b', ref)
                    if arxiv_id_match:
                        arxiv_year_month = arxiv_id_match.group(1)
                        if len(arxiv_year_month) == 4 and arxiv_year_month.startswith(('07', '08', '09')):
                            yy = int(arxiv_year_month[:2])
                            if yy >= 7:
                                year = 1992 + yy
                        elif len(arxiv_year_month) == 4 and arxiv_year_month.startswith(tuple(str(x).zfill(2) for x in range(10, 25))):
                            yy = int(arxiv_year_month[:2])
                            year = 2000 + yy
                # Additional year extraction for legal cases and other formats
                if year is None:
                    # Look for year right after reference number like "[1]1976."
                    legal_year_match = re.search(r'^\[\d+\](\d{4})\.', ref)
                    if legal_year_match:
                        year = int(legal_year_match.group(1))
                    else:
                        # Look for year at the beginning after any reference number
                        year_start_match = re.search(r'^.*?(\d{4})\.', ref)
                        if year_start_match:
                            potential_year = int(year_start_match.group(1))
                            # Validate that it's a reasonable year
                            if 1900 <= potential_year <= 2030:
                                year = potential_year
                extracted_data = self.extract_authors_title_from_academic_format(ref)
                if extracted_data:
                    authors, title = extracted_data
                else:
                    authors, title = self.extract_authors_title_fallback(ref)
                title = re.sub(r'\s+', ' ', title).strip() if title else ""
                if not authors and arxiv_url:
                    authors = ["Unknown Author"]
                final_authors = []
                for author in authors:
                    if isinstance(author, dict) and author.get('is_url_reference', False):
                        final_authors = ["URL Reference"]
                        break
                    else:
                        final_authors.append(author)
                if not final_authors:
                    final_authors = ["Unknown Author"]
                structured_ref = {
                    'url': clean_url(arxiv_url),
                    'year': year if year else 0,
                    'authors': final_authors,
                    'title': title,
                    'raw_text': ref,
                    'type': 'arxiv'
                }
                logger.info(f"Extracted arXiv reference: {structured_ref['title']}")
                arxiv_refs.append(structured_ref)
            else:
                doi = None
                url = None
                for pattern in doi_patterns:
                    doi_match = re.search(pattern, ref, re.IGNORECASE)
                    if doi_match:
                        doi = clean_doi(doi_match.group(1))
                        url = f"https://doi.org/{doi}" if doi else ''
                        break
                if not url:
                    for pattern in url_patterns:
                        url_match = re.search(pattern, ref)
                        if url_match:
                            url = clean_url(url_match.group(0))
                            break
                if url or doi:
                    logger.debug(f"Found non-arXiv reference {i+1}: {url or doi}")
                    year = None
                    end_year_match = re.search(r',\s+((19|20)\d{2})\s*\.?\s*$', ref)
                    if end_year_match:
                        year = int(end_year_match.group(1))
                    else:
                        year_patterns = [
                            r'(?:In|Proceedings)[^,]*,?\s+((19|20)\d{2})',
                            r'(?:Journal|IEEE|ACM)[^,]*,?\s+((19|20)\d{2})',
                            r'(?:CoRR|abs/)[^,]*,?\s+((19|20)\d{2})',
                        ]
                        for pattern in year_patterns:
                            pattern_match = re.search(pattern, ref)
                            if pattern_match:
                                year = int(pattern_match.group(1))
                                break
                        if year is None:
                            all_years = re.findall(r'\b((19|20)\d{2})\b', ref)
                            if all_years:
                                valid_years = []
                                for potential_year, _ in all_years:
                                    page_pattern = rf'\d+\([^)]*\):\d*{potential_year}'
                                    if not re.search(page_pattern, ref):
                                        valid_years.append(int(potential_year))
                                if valid_years:
                                    year = valid_years[-1]
                    extracted_data = self.extract_authors_title_from_academic_format(ref)
                    if extracted_data:
                        authors, title = extracted_data
                    else:
                        authors, title = self.extract_authors_title_fallback(ref)
                    title = re.sub(r'\s+', ' ', title).strip() if title else ""
                    is_url_reference = False
                    for author in authors:
                        if isinstance(author, dict) and author.get('is_url_reference', False):
                            is_url_reference = True
                            break
                    if is_url_reference:
                        authors = ["URL Reference"]
                    elif not authors:
                        authors = ["Unknown Author"]
                    structured_ref = {
                        'url': clean_url(url),
                        'doi': clean_doi(doi),
                        'year': year if year else 0,
                        'authors': authors,
                        'title': title,
                        'raw_text': ref,
                        'type': 'non-arxiv'
                    }
                    logger.debug(f"Extracted non-arXiv reference: {structured_ref}")
                    non_arxiv_refs.append(structured_ref)
                else:
                    extracted_data = self.extract_authors_title_from_academic_format(ref)
                    if extracted_data:
                        authors, title = extracted_data
                    else:
                        authors, title = self.extract_authors_title_fallback(ref)
                    title = re.sub(r'\s+', ' ', title).strip() if title else ""
                    year = None
                    end_year_match = re.search(r',\s+((19|20)\d{2})\s*\.?\s*$', ref)
                    if end_year_match:
                        year = int(end_year_match.group(1))
                    else:
                        year_patterns = [
                            r'(?:In|Proceedings)[^,]*,?\s+((19|20)\d{2})',
                            r'(?:Journal|IEEE|ACM)[^,]*,?\s+((19|20)\d{2})',
                            r'(?:CoRR|abs/)[^,]*,?\s+((19|20)\d{2})',
                        ]
                        for pattern in year_patterns:
                            pattern_match = re.search(pattern, ref)
                            if pattern_match:
                                year = int(pattern_match.group(1))
                                break
                        if year is None:
                            all_years = re.findall(r'\b((19|20)\d{2})\b', ref)
                            if all_years:
                                valid_years = []
                                for potential_year, _ in all_years:
                                    page_pattern = rf'\d+\([^)]*\):\d*{potential_year}'
                                    if not re.search(page_pattern, ref):
                                        valid_years.append(int(potential_year))
                                if valid_years:
                                    year = valid_years[-1]
                    is_url_reference = False
                    for author in authors:
                        if isinstance(author, dict) and author.get('is_url_reference', False):
                            is_url_reference = True
                            break
                    if is_url_reference:
                        authors = ["URL Reference"]
                    elif not authors:
                        authors = ["Unknown Author"]
                    structured_ref = {
                        'url': "",
                        'doi': None,
                        'year': year if year else 0,
                        'authors': authors,
                        'title': title,
                        'raw_text': ref,
                        'type': 'other'
                    }
                    logger.info(f"Extracted other reference: {structured_ref['title']}")
                    other_refs.append(structured_ref)
        logger.info(f"Extracted {len(arxiv_refs)} structured references with arxiv links")
        logger.info(f"Extracted {len(non_arxiv_refs)} structured references without arxiv links")
        logger.info(f"Extracted {len(other_refs)} structured references without URLs or DOIs")
        all_refs = arxiv_refs + non_arxiv_refs + other_refs
        return all_refs
    
    def _process_llm_extracted_references(self, references):
        """
        Process references extracted by LLM with simplified formatting assumptions
        """
        processed_refs = []
        
        for ref in references:
            if not ref or len(ref.strip()) < 10:
                continue
                
            # Use LLM-specific structured reference creation
            structured_ref = self._create_structured_llm_references(ref)
            if structured_ref:
                processed_refs.append(structured_ref)
        
        return processed_refs
    
    def _clean_llm_author_text(self, author_text):
        """
        Clean author text by removing 'and' and trailing periods
        """
        if not author_text:
            return []
        
        # First remove 'and' and trailing periods from the entire text
        cleaned_text = author_text.replace(' and ', ', ').rstrip('.')
        
        # Then split by commas
        authors = [a.strip() for a in cleaned_text.split(',') if a.strip()]
        
        # Remove any remaining trailing periods and clean up
        authors = [a.rstrip('.').strip() for a in authors if a.strip()]
        
        return authors

    def _create_structured_llm_references(self, ref_text):
        """
        Create structured reference from LLM-extracted text (assumes well-formatted input)
        """
        # LLM outputs are well-formatted, so we can use simpler parsing
        
        # Check for ArXiv references
        arxiv_patterns = [
            r'arxiv\.org/[^\s,\)]+',
            r'arxiv:\s*(\d+\.\d+(?:v\d+)?)',
            r'arXiv preprint arXiv:(\d+\.\d+(?:v\d+)?)',
        ]
        
        arxiv_url = None
        for pattern in arxiv_patterns:
            arxiv_match = re.search(pattern, ref_text, re.IGNORECASE)
            if arxiv_match:
                if 'arxiv.org' in arxiv_match.group(0).lower():
                    arxiv_url = arxiv_match.group(0)
                    if not arxiv_url.startswith('http'):
                        arxiv_url = 'https://' + arxiv_url
                else:
                    try:
                        arxiv_id = arxiv_match.group(1)
                        arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
                    except IndexError:
                        arxiv_url = f"https://arxiv.org/abs/{arxiv_match.group(0)}"
                break
        
        # Extract DOI - simpler patterns for well-formatted text
        doi_patterns = [
            r'doi\.org/([^\s,\)]+)',
            r'doi:\s*([^\s,\)]+)',
            r'DOI:\s*([^\s,\)]+)',
        ]
        
        doi = None
        url = None
        for pattern in doi_patterns:
            doi_match = re.search(pattern, ref_text, re.IGNORECASE)
            if doi_match:
                doi = doi_match.group(1)
                url = f"https://doi.org/{doi}"
                break
        
        # Extract other URLs if no DOI found
        if not url and not arxiv_url:
            url_match = re.search(r'https?://(?!arxiv\.org)[^\s,\)]+', ref_text)
            if url_match:
                url = url_match.group(0)
        
        # Extract year - LLM output should have clear year formatting
        year = None
        year_match = re.search(r'\b(19|20)\d{2}\b', ref_text)
        if year_match:
            year = int(year_match.group(0))
        
        # For LLM-extracted references, use simple parsing since they're well-formatted
        # LLM now formats as: "Authors # Title # Journal/Venue # Year" or "#Title#Venue#Year#" (no authors)
        
        authors = []
        title = ""
        venue = ""
        
        # Split by hashmarks to find components
        parts = ref_text.split('#')
        parts = [p.strip() for p in parts if p.strip()]  # Clean up whitespace and remove empty parts
        logger.debug(f"Split by hashmarks: {parts}")
        
        # Handle different formats based on number of parts
        if len(parts) == 1:
            # URL-only or simple title
            text = parts[0].strip()
            if text.startswith('http'):
                # This is a URL reference
                arxiv_url = text if 'arxiv' in text.lower() else None
                url = text if not arxiv_url else None
                title = url
                authors = ['URL Reference']
                logger.debug(f"1-part URL format - URL: '{text}'")
            else:
                # Simple title
                title = text
                authors = 'Unknown Author'
                logger.debug(f"1-part title format - Title: '{title}'")
        elif len(parts) == 2:
            # Format: Authors # Title
            author_text = parts[0].strip()
            title = parts[1].strip()
            logger.debug(f"2-part format - Authors: '{author_text}', Title: '{title}'")
            # Parse authors
            authors = self._clean_llm_author_text(author_text)
        elif len(parts) == 3:
            # Format: Authors # Title # Year (most common)
            author_text = parts[0].strip()
            title = parts[1].strip()
            year_part = parts[2].strip()
            logger.debug(f"3-part format - Authors: '{author_text}', Title: '{title}', Year part: '{year_part}'")
            # Parse authors
            authors = self._clean_llm_author_text(author_text)
        elif len(parts) == 4:
            # Format: Authors # Title # Venue # Year
            author_text = parts[0].strip()
            title = parts[1].strip()
            venue = parts[2].strip()
            year_part = parts[3].strip()
            logger.debug(f"4-part format - Authors: '{author_text}', Title: '{title}', Venue: '{venue}', Year part: '{year_part}'")
            
            # Parse authors
            authors = self._clean_llm_author_text(author_text)
        elif len(parts) == 5:
            # Format: Authors # Title # Venue # Pages/Details # Publisher/Year
            author_text = parts[0].strip()
            title = parts[1].strip()
            venue = parts[2].strip()
            pages_details = parts[3].strip()
            year_part = parts[4].strip()
            logger.debug(f"5-part format - Authors: '{author_text}', Title: '{title}', Venue: '{venue}', Pages: '{pages_details}', Year part: '{year_part}'")
            
            # Parse authors
            authors = self._clean_llm_author_text(author_text)
            
            # Combine venue with pages/details for a more complete venue description
            if pages_details:
                venue = f"{venue}, {pages_details}" if venue else pages_details
        else:
            # Fallback for other formats or malformed input
            logger.debug(f"Unexpected format with {len(parts)} parts: {parts}")
            if len(parts) >= 1:
                author_text = parts[0].strip()
                authors = self._clean_llm_author_text(author_text)
            if len(parts) >= 2:
                title = parts[1].strip()
            if len(parts) >= 3:
                venue = parts[2].strip()
            if len(parts) >= 4:
                # For cases with more than 5 parts, combine the last parts as year_part
                year_part = ' '.join(parts[3:]).strip()
        
        # Extract year from year_part if we have one
        if 'year_part' in locals() and year_part:
            year_match = re.search(r'\b(19|20)\d{2}\b', year_part)
            if year_match:
                year = int(year_match.group(0))
            else:
                # Try to extract year from the year_part itself if it's just a year
                if year_part.isdigit() and len(year_part) == 4:
                    year = int(year_part)
        
        # Fallback: if no clear structure, extract what we can
        if not title:
            # Look for quoted titles
            title_match = re.search(r'"([^"]+)"', ref_text)
            if title_match:
                title = title_match.group(1)
            else:
                # Try to find title-like text (capitalized words)
                # Remove URLs, DOIs, years first
                clean_text = re.sub(r'https?://[^\s]+', '', ref_text)
                clean_text = re.sub(r'doi:[^\s]+', '', clean_text)
                clean_text = re.sub(r'arXiv:[^\s]+', '', clean_text)
                clean_text = re.sub(r'\b(19|20)\d{2}\b', '', clean_text)
                
                # Look for capitalized title pattern
                title_match = re.search(r'([A-Z][a-z]+(?:\s+[a-z]+)*(?:\s+[A-Z][a-z]+)*)', clean_text)
                if title_match:
                    title = title_match.group(1)
        
        # Clean up title
        title = re.sub(r'\s+', ' ', title).strip() if title else ""
        title = title.rstrip(',').strip()
        
        # Clean up venue
        venue = re.sub(r'\s+', ' ', venue).strip() if venue else ""
        venue = venue.rstrip(',').strip()
        
        if not authors:
            authors = []  # Allow empty authors for references without author information
        
        # Determine reference type
        ref_type = 'arxiv' if arxiv_url else ('non-arxiv' if (url or doi) else 'other')
        
        return {
            'url': arxiv_url or url or "",
            'doi': doi,
            'year': year or 0,
            'authors': authors,
            'title': title,
            'raw_text': ref_text,
            'type': ref_type
        }

    def _create_structured_reference(self, ref_text):
        """
        Create structured reference from raw text
        """
        # Check for ArXiv references
        arxiv_patterns = [
            r'arxiv\.org/[^\s,\)]+',
            r'arxiv:\s*(\d+\.\d+(?:v\d+)?)',
            r'arXiv preprint arXiv:(\d+\.\d+(?:v\d+)?)',
        ]
        
        arxiv_url = None
        for pattern in arxiv_patterns:
            arxiv_match = re.search(pattern, ref_text, re.IGNORECASE)
            if arxiv_match:
                if 'arxiv.org' in arxiv_match.group(0).lower():
                    arxiv_url = arxiv_match.group(0)
                    if not arxiv_url.startswith('http'):
                        arxiv_url = 'https://' + arxiv_url
                else:
                    try:
                        arxiv_id = arxiv_match.group(1)
                        arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
                    except IndexError:
                        arxiv_url = f"https://arxiv.org/abs/{arxiv_match.group(0)}"
                break
        
        # Extract DOI
        doi_patterns = [
            r'doi\.org/([^\s,\)]+)',
            r'doi:([^\s,\)]+)',
            r'DOI:([^\s,\)]+)',
        ]
        
        doi = None
        url = None
        for pattern in doi_patterns:
            doi_match = re.search(pattern, ref_text, re.IGNORECASE)
            if doi_match:
                doi = doi_match.group(1)
                url = f"https://doi.org/{doi}"
                break
        
        # Extract other URLs if no DOI found
        if not url and not arxiv_url:
            url_match = re.search(r'https?://(?!arxiv\.org)[^\s,\)]+', ref_text)
            if url_match:
                url = url_match.group(0)
        
        # Extract year
        year = None
        year_match = re.search(r'\b(19|20)\d{2}\b', ref_text)
        if year_match:
            year = int(year_match.group(0))
        
        # Extract authors and title
        extracted_data = self.extract_authors_title_from_academic_format(ref_text)
        if extracted_data:
            authors, title = extracted_data
        else:
            authors, title = self.extract_authors_title_fallback(ref_text)
        
        # Clean up
        title = re.sub(r'\s+', ' ', title).strip() if title else ""
        if not authors:
            authors = ["Unknown Author"]
        
        # Determine reference type
        ref_type = 'arxiv' if arxiv_url else ('non-arxiv' if (url or doi) else 'other')
        
        return {
            'url': arxiv_url or url or "",
            'doi': doi,
            'year': year or 0,
            'authors': authors,
            'title': title,
            'raw_text': ref_text,
            'type': ref_type
        }
    
    def extract_bibliography(self, paper, debug_mode=False):
        """
        Extract bibliography from a paper (PDF, LaTeX, or text file)
        
        Args:
            paper: Paper object to extract bibliography from
            debug_mode: If True, save debug files for troubleshooting
        """
        paper_id = paper.get_short_id()
        logger.info(f"Extracting bibliography for paper {paper_id}: {paper.title}")
        
        # Check if this is a text file containing references
        if hasattr(paper, 'is_text_refs') and paper.is_text_refs:
            # Read the text file directly - it should contain references
            logger.info(f"Processing text file containing references: {paper.file_path}")
            try:
                with open(paper.file_path, 'r', encoding='utf-8') as f:
                    bibliography_text = f.read()
                
                # Save the text for debugging
                if debug_mode:
                    debug_dir = "debug"
                    if not os.path.exists(debug_dir):
                        os.makedirs(debug_dir)
                    
                    with open(os.path.join(debug_dir, f"{paper_id}_bibliography.txt"), 'w', encoding='utf-8') as f:
                        f.write(bibliography_text)
                    
                    logger.info(f"Saved reference text to {os.path.join(debug_dir, f'{paper_id}_bibliography.txt')}")
                
                # Parse references directly from the text
                references = self.parse_references(bibliography_text)
                
                # Save the extracted references for debugging
                if debug_mode:
                    with open(os.path.join(debug_dir, f"{paper_id}_references.json"), 'w', encoding='utf-8') as f:
                        json.dump(references, f, indent=2)
                
                logger.info(f"Extracted {len(references)} references from text file")
                
                return references
                
            except Exception as e:
                logger.error(f"Error reading text file {paper.file_path}: {e}")
                return []
        
        # Check if this is a LaTeX file
        elif hasattr(paper, 'is_latex') and paper.is_latex:
            # Extract text from LaTeX file
            text = self.extract_text_from_latex(paper.file_path)
        else:
            # Download the PDF
            pdf_content = self.download_pdf(paper)
            
            if not pdf_content:
                logger.warning(f"Could not download PDF for {paper_id}")
                return []
            
            # Extract text from PDF
            text = self.extract_text_from_pdf(pdf_content)
        
        if not text:
            logger.warning(f"Could not extract text from {'LaTeX' if hasattr(paper, 'is_latex') and paper.is_latex else 'PDF'} for {paper_id}")
            return []
        
        # Save the extracted text for debugging
        if debug_mode:
            debug_dir = "debug"
            if not os.path.exists(debug_dir):
                os.makedirs(debug_dir)
            
            with open(os.path.join(debug_dir, f"{paper_id}_text.txt"), 'w', encoding='utf-8') as f:
                f.write(text)
            
            logger.info(f"Saved extracted text to {os.path.join(debug_dir, f'{paper_id}_text.txt')}")
        
        # Find bibliography section
        bibliography_text = self.find_bibliography_section(text)
        
        if not bibliography_text:
            logger.warning(f"Could not find bibliography section for {paper_id}")
            return []
        
        # Save the bibliography text for debugging
        if debug_mode:
            with open(os.path.join(debug_dir, f"{paper_id}_bibliography.txt"), 'w', encoding='utf-8') as f:
                f.write(bibliography_text)
            
            logger.info(f"Saved bibliography text to {os.path.join(debug_dir, f'{paper_id}_bibliography.txt')}")
        
        # Parse references
        references = self.parse_references(bibliography_text)
        
        # Save the extracted references for debugging
        if debug_mode:
            with open(os.path.join(debug_dir, f"{paper_id}_references.json"), 'w', encoding='utf-8') as f:
                json.dump(references, f, indent=2)
        
        logger.info(f"Extracted {len(references)} references with arxiv links for {paper_id}")
        
        return references
    
    def compare_authors(self, cited_authors, correct_authors):
        """
        Improved function to compare author lists to check if they match
        Allows for first name abbreviations and common parsing issues
        """
        # Clean up author names
        cleaned_cited = []
        for author in cited_authors:
            # Remove reference numbers (e.g., "[1]")
            author = re.sub(r'^\[\d+\]', '', author)
            # Remove line breaks
            author = author.replace('\n', ' ')
            # Remove "et al" if it's the last author
            if author.lower() == 'et al' or 'et al' in author.lower():
                continue
            cleaned_cited.append(author.strip())
        
        # If the cited list has "et al" or similar, it's incomplete
        # In this case, we only check the authors that are listed
        has_et_al = any('et al' in a.lower() for a in cited_authors)
        
        if len(cleaned_cited) < len(correct_authors) and has_et_al:
            # Only compare the authors that are listed
            correct_authors = correct_authors[:len(cleaned_cited)]
        # If the counts still don't match, but it's a reasonable number of authors, don't flag as an error
        # This is common in academic citations where not all authors are listed
        elif len(cleaned_cited) < len(correct_authors):
            # If we have at least 3 authors and they match, consider it good enough
            if len(cleaned_cited) >= 3:
                correct_authors = correct_authors[:len(cleaned_cited)]
        # If we have more cited authors than correct authors, it's likely an error
        # But if the difference is just 1 or 2, and the primary authors match, it might be ok
        elif len(cleaned_cited) > len(correct_authors) and len(correct_authors) >= 3:
            # Check if the first few authors match
            # Continue with comparison but only use the available correct authors
            cleaned_cited = cleaned_cited[:len(correct_authors)]
        
        # If there's a big count mismatch and no "et al", it's likely an error
        if abs(len(cleaned_cited) - len(correct_authors)) > 3 and not has_et_al:
            return False, "Author count mismatch"
        
        # Prepare to check if first authors match
        first_author_match = False
        
        # Compare authors one by one
        for i, (cited, correct) in enumerate(zip(cleaned_cited, correct_authors)):
            # Normalize names for comparison
            # Extract last name (the last word in the name)
            cited_parts = cited.split()
            correct_parts = correct.split()
            
            if not cited_parts or not correct_parts:
                continue  # Skip empty names
            
            # If there's only one part (likely just the last name), use it as is
            if len(cited_parts) == 1:
                cited_last = cited_parts[0].lower()
            else:
                cited_last = cited_parts[-1].lower()

            if len(correct_parts) == 1:
                correct_last = correct_parts[0].lower()
            else:
                correct_last = correct_parts[-1].lower()
            
            # Check last names, ignoring diacritical marks
            cited_last = self.normalize_text(cited_last)
            correct_last = self.normalize_text(correct_last)
            
            # If this is the first author, remember if they match
            if i == 0:
                first_author_match = (cited_last == correct_last)
                if not first_author_match:
                    # If the first author doesn't match, we need to check further
                    return False, f"First author mismatch: '{cited}' vs '{correct}'"
            
            if correct_last != '' and cited_last != correct_last:
                # Check if one is a substring of the other (for hyphenated names or partial matches)
                if cited_last in correct_last or correct_last in cited_last:
                    continue  # Consider it a match
                # Check if the Levenshtein distance is small (for minor typos)
                if self.levenshtein_distance(cited_last, correct_last) <= 2:
                    continue  # Consider it a match
                
                # Special case for first author mismatch
                if i == 0:
                    return False, f"First author mismatch: '{cited}' vs '{correct}'"
                
                # For non-first authors, if we have a good number of authors and the first author matches,
                # be a bit more lenient
                if i > 0 and first_author_match and len(cleaned_cited) >= 3:
                    continue
                
                return False, f"Last name mismatch at position {i+1}: '{cited}' vs '{correct}'"
            
            # If there's only one part (just the last name), skip first name check
            if len(cited_parts) == 1 or len(correct_parts) == 1:
                continue
                
            # Check first name/initial
            cited_first = cited_parts[0].lower()
            correct_first = correct_parts[0].lower()
            
            # Normalize first names
            cited_first = self.normalize_text(cited_first)
            correct_first = self.normalize_text(correct_first)
            
            # Allow first initial instead of full first name
            if cited_first != correct_first:
                # Check if one is an initial of the other
                if cited_first == correct_first[0] or correct_first == cited_first[0]:
                    continue  # Consider it a match
                # Check if one has an initial and the other has the full name
                if (len(cited_first) == 1 and correct_first.startswith(cited_first)) or \
                (len(correct_first) == 1 and cited_first.startswith(correct_first)):
                    continue  # Consider it a match
                # Check if one is a substring of the other
                if cited_first.startswith(correct_first) or correct_first.startswith(cited_first):
                    continue  # Consider it a match
                # Check if the Levenshtein distance is small (for minor typos)
                if self.levenshtein_distance(cited_first, correct_first) <= 2:
                    continue  # Consider it a match
                    
                # Special handling for first author
                if i == 0:
                    return False, f"First author mismatch: '{cited}' vs '{correct}'"
                    
                # For non-first authors, if we have a good number of authors and the first author matches,
                # be a bit more lenient
                if i > 0 and first_author_match and len(cleaned_cited) >= 3:
                    continue
                    
                return False, f"First name mismatch at position {i+1}: '{cited}' vs '{correct}'"
        
        return True, "Authors match"
    
    def levenshtein_distance(self, s1, s2):
        """
        Calculate the Levenshtein distance between two strings.
        This is a measure of the minimum number of single-character edits 
        (insertions, deletions, or substitutions) required to change one string into the other.
        """
        if len(s1) < len(s2):
            return self.levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    def normalize_text(self, text):
        """
        Normalize text by removing diacritical marks and special characters
        """
        if not text:
            return ""
            
        # Replace common special characters with their ASCII equivalents
        replacements = {
            'ä': 'a', 'ö': 'o', 'ü': 'u', 'ß': 'ss',
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
            'â': 'a', 'ê': 'e', 'î': 'i', 'ô': 'o', 'û': 'u',
            'ç': 'c', 'ñ': 'n', 'ø': 'o', 'å': 'a',
            'ë': 'e', 'ï': 'i', 'ÿ': 'y',
            '¨': '', '´': '', '`': '', '^': '', '~': '',
            '–': '-', '—': '-', '−': '-',
            '„': '"', '"': '"', '"': '"', ''': "'", ''': "'",
            '«': '"', '»': '"',
            '¡': '!', '¿': '?',
            '°': 'degrees', '©': '(c)', '®': '(r)', '™': '(tm)',
            '€': 'EUR', '£': 'GBP', '¥': 'JPY', '₹': 'INR',
            '×': 'x', '÷': '/',
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '\u00A0': ' ',  # Non-breaking space
            '\u2013': '-',  # En dash
            '\u2014': '-',  # Em dash
            '\u2018': "'",  # Left single quotation mark
            '\u2019': "'",  # Right single quotation mark
            '\u201C': '"',  # Left double quotation mark
            '\u201D': '"',  # Right double quotation mark
            '\u2026': '...',  # Horizontal ellipsis
            '\u00B7': '.',  # Middle dot
            '\u2022': '.',  # Bullet
}
        
        for char, replacement in replacements.items():
            text = text.replace(char, replacement)
        
        # Remove any remaining diacritical marks
        import unicodedata
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
        
        # Remove special characters
        text = re.sub(r'[^\w\s]', '', text)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text.lower()
    
    def get_arxiv_paper_from_local_db(self, arxiv_id):
        """
        Get arXiv paper metadata from local database as fallback
        
        Args:
            arxiv_id: The arXiv ID to search for
            
        Returns:
            Mock paper object with same interface as arxiv.Result, or None if not found
        """
        if not self.db_path or not hasattr(self, 'non_arxiv_checker'):
            return None
            
        try:
            import sqlite3
            import json
            from datetime import datetime
            
            # Connect to the database
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Search for the paper by arXiv ID
            query = "SELECT * FROM papers WHERE externalIds_ArXiv = ?"
            cursor.execute(query, [arxiv_id])
            row = cursor.fetchone()
            
            if not row:
                conn.close()
                return None
                
            paper_data = dict(row)
            
            # Extract authors from JSON
            if paper_data.get('authors'):
                authors_data = json.loads(paper_data['authors'])
            else:
                authors_data = []
            
            # Create a mock paper object that mimics arxiv.Result interface
            class MockArxivPaper:
                def __init__(self, data, authors_data, arxiv_id):
                    self.title = data.get('title', 'Unknown Title')
                    self.arxiv_id = arxiv_id
                    
                    # Set PDF URL (construct from arXiv ID)
                    self.pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                    
                    # Create mock authors with name attribute
                    class MockAuthor:
                        def __init__(self, name):
                            self.name = name
                        
                        def __str__(self):
                            return self.name
                        
                        def __repr__(self):
                            return f"MockAuthor('{self.name}')"
                    
                    self.authors = [MockAuthor(author.get('name', 'Unknown Author')) for author in authors_data]
                    
                    # Set publication year - try from year field, fallback to current year
                    year = data.get('year', datetime.now().year)
                    
                    # Create mock published attribute
                    class MockPublished:
                        def __init__(self, year):
                            self.year = year
                    
                    self.published = MockPublished(year)
                    
                def get_short_id(self):
                    return self.arxiv_id
            
            mock_paper = MockArxivPaper(paper_data, authors_data, arxiv_id)
            conn.close()
            
            logger.info(f"Found arXiv paper {arxiv_id} in local database as fallback")
            return mock_paper
            
        except Exception as e:
            logger.error(f"Error querying local database for arXiv ID {arxiv_id}: {str(e)}")
            return None

    def is_valid_doi(self, doi):
        """
        Check if a DOI is well-formed (basic check: starts with '10.' and has at least one slash and more than 6 chars)
        """
        if not doi or not isinstance(doi, str):
            return False
        doi = doi.strip()
        # Must start with '10.' and contain at least one '/'
        if not doi.startswith('10.') or '/' not in doi:
            return False
        if len(doi) < 7:
            return False
        # Optionally, check for forbidden trailing chars
        if doi in ('10.', '10'):
            return False
        return True


def main():
    """Main function to parse arguments and run the reference checker"""
    parser = argparse.ArgumentParser(description="ArXiv Reference Checker - Validate references in ArXiv papers")
    parser.add_argument("--max-papers", type=int, default=50,
                        help="Maximum number of papers to process (default: 50)")
    parser.add_argument("--days", type=int, default=365,
                        help="Number of days to look back (default: 365)")
    parser.add_argument("--category", type=str,
                        help="ArXiv category to filter by (e.g., cs.AI, math.CO)")
    parser.add_argument("--debug", action="store_true",
                        help="Run in debug mode with verbose logging")
    parser.add_argument("--paper", type=str,
                        help="Validate a specific paper by ArXiv ID, URL, local PDF file path, local LaTeX file path, or local text file containing references")
    parser.add_argument("--semantic-scholar-api-key", type=str,
                        help="API key for Semantic Scholar (optional, increases rate limits)")
    parser.add_argument("--db-path", type=str,
                        help="Path to local Semantic Scholar database (automatically enables local DB mode)")
    
    # LLM configuration arguments
    parser.add_argument("--llm-provider", type=str, choices=["openai", "anthropic", "google", "azure"],
                        help="Enable LLM with specified provider (openai, anthropic, google, azure)")
    parser.add_argument("--llm-model", type=str,
                        help="LLM model to use (overrides default for the provider)")
    parser.add_argument("--llm-key", type=str,
                        help="API key for the LLM provider (uses environment variable if not provided)")
    parser.add_argument("--llm-endpoint", type=str,
                        help="Endpoint for the LLM provider (overrides default endpoint)")
    parser.add_argument("--skip-google-scholar-single", action="store_true",
                        help="Skip Google Scholar fallback when processing single papers for better performance")
    
    args = parser.parse_args()
    
    # Set up logging based on debug mode
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    # Process paper argument - can be ArXiv ID, URL, or local PDF/LaTeX file
    paper_id = None
    local_pdf_path = None
    
    if args.paper:
        if args.paper.lower().endswith('.pdf'):
            # This is a local PDF file
            if not os.path.exists(args.paper):
                print(f"Error: Local PDF file does not exist: {args.paper}")
                return 1
            local_pdf_path = args.paper
        elif args.paper.lower().endswith('.tex'):
            # This is a local LaTeX file
            if not os.path.exists(args.paper):
                print(f"Error: Local LaTeX file does not exist: {args.paper}")
                return 1
            local_pdf_path = args.paper  # We'll use the same variable but handle it differently
        elif args.paper.lower().endswith('.txt'):
            # This is a local text file containing references
            if not os.path.exists(args.paper):
                print(f"Error: Local text file does not exist: {args.paper}")
                return 1
            local_pdf_path = args.paper  # We'll use the same variable but handle it differently
        elif args.paper.startswith('http'):
            # Extract arXiv ID from URL
            paper_id = extract_arxiv_id_from_url(args.paper)
            if not paper_id:
                print(f"Error: Could not extract arXiv ID from URL: {args.paper}")
                return 1
        else:
            # Assume it's an ArXiv ID
            paper_id = args.paper
    
    # Process LLM configuration overrides
    llm_config = None
    if args.llm_provider:
        llm_config = {
            'provider': args.llm_provider,
            'model': args.llm_model,
            'api_key': args.llm_key,
            'endpoint': args.llm_endpoint
        }
    
    try:
        # Initialize the reference checker
        checker = ArxivReferenceChecker(
            days_back=args.days,
            category=args.category,
            semantic_scholar_api_key=args.semantic_scholar_api_key,
            db_path=args.db_path,
            llm_config=llm_config,
            skip_google_scholar_for_single_paper=args.skip_google_scholar_single
        )
        
        # Run the checker
        output_file = checker.run(
            max_papers=args.max_papers,
            debug_mode=args.debug,
            specific_paper_id=paper_id,
            local_pdf_path=local_pdf_path
        )
            
    except KeyboardInterrupt:
        print("\n✗ Process interrupted by user.")
        return 1
    except Exception as e:
        print(f"\n✗ Error during processing: {str(e)}")
        logger.error(f"Unexpected error: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
