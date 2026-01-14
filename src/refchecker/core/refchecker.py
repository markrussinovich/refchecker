#!/usr/bin/env python3
"""
ArXiv Reference Checker

This script validates references in academic papers by:
1. Extracting references from the bibliography (both arXiv and non-arXiv references)
2. Verifying if the references are accurate (author list, year, links)
3. Creating a detailed report of incorrect references

For arXiv references, it uses the arXiv API to verify metadata.
For non-arXiv references, it uses the local Semantic Scholar database for verification.

Usage:
    python run_refchecker.py --paper PAPER_SPEC [--db-path PATH] [--output-file [PATH]] [--debug]

Options:
    --paper PAPER_SPEC            Validate a specific paper by:
                                    - ArXiv ID (e.g., 1234.5678)
                                    - ArXiv URL (e.g., https://arxiv.org/abs/1234.5678)
                                    - Local PDF file path (e.g., /path/to/paper.pdf)
                                    - Local LaTeX file path (e.g., /path/to/paper.tex)
    --db-path PATH                Path to local Semantic Scholar database (recommended for offline verification)
    --output-file [PATH]          Path to output file for reference discrepancies (default: reference_errors.txt if flag provided, no file if not provided)
    --debug                       Run in debug mode with verbose logging
    --semantic-scholar-api-key KEY API key for Semantic Scholar (optional, increases rate limits).
                                    Can also be set via SEMANTIC_SCHOLAR_API_KEY environment variable
    --help                        Show this help message
"""

import arxiv
import pandas as pd
import requests
import re
import datetime
import time
import logging
import os
from urllib.parse import urlparse
from tqdm import tqdm
import pypdf
import pdfplumber
import io
import argparse
import sys
import json
import random
from refchecker.checkers.local_semantic_scholar import LocalNonArxivReferenceChecker
from refchecker.utils.text_utils import (clean_author_name, clean_title, clean_title_basic,
                       normalize_text as common_normalize_text,
                       detect_latex_bibliography_format, extract_latex_references, 
                       detect_standard_acm_natbib_format, strip_latex_commands, 
                       format_corrected_reference, is_name_match, enhanced_name_match,
                       calculate_title_similarity, normalize_arxiv_url, deduplicate_urls,
                       compare_authors)
from refchecker.utils.url_utils import extract_arxiv_id_from_url
from refchecker.utils.config_validator import ConfigValidator
from refchecker.services.pdf_processor import PDFProcessor
from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
from refchecker.core.parallel_processor import ParallelReferenceProcessor  
from refchecker.core.db_connection_pool import ThreadSafeLocalChecker

# Import version
from refchecker.__version__ import __version__
from refchecker.llm.base import create_llm_provider, ReferenceExtractor

def get_llm_api_key_interactive(provider: str) -> str:
    """
    Get API key for LLM provider, checking environment variables first,
    then prompting interactively if not found.
    
    Args:
        provider: LLM provider name (openai, anthropic, google, azure, vllm)
    
    Returns:
        API key string or None if not available
    """
    # Define environment variable names for each provider
    env_vars = {
        'openai': ['REFCHECKER_OPENAI_API_KEY', 'OPENAI_API_KEY'],
        'anthropic': ['REFCHECKER_ANTHROPIC_API_KEY', 'ANTHROPIC_API_KEY'],
        'google': ['REFCHECKER_GOOGLE_API_KEY', 'GOOGLE_API_KEY'],
        'azure': ['REFCHECKER_AZURE_API_KEY', 'AZURE_OPENAI_API_KEY'],
        'vllm': []  # vLLM doesn't need API key
    }
    
    # vLLM doesn't need an API key
    if provider == 'vllm':
        return None
    
    # Check environment variables first
    for env_var in env_vars.get(provider, []):
        api_key = os.getenv(env_var)
        if api_key:
            logging.debug(f"Using {provider} API key from environment variable {env_var}")
            return api_key
    
    # If not found in environment, prompt interactively
    import getpass
    
    provider_names = {
        'openai': 'OpenAI',
        'anthropic': 'Anthropic',
        'google': 'Google',
        'azure': 'Azure OpenAI'
    }
    
    provider_display = provider_names.get(provider, provider.capitalize())
    
    print(f"\n{provider_display} API key not found in environment variables.")
    print(f"Checked environment variables: {', '.join(env_vars.get(provider, []))}")
    print(f"Please enter your {provider_display} API key (input will be hidden):")
    
    try:
        api_key = getpass.getpass("API key: ").strip()
        if api_key:
            return api_key
        else:
            print("No API key provided.")
            return None
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        return None

def setup_logging(debug_mode=False, level=None):
    """Set up logging configuration"""
    # Configure root logger to control all child loggers
    root_logger = logging.getLogger()
    # Set level based on debug_mode if not explicitly provided
    if level is None:
        level = logging.DEBUG if debug_mode else logging.INFO
    root_logger.setLevel(level)
    
    # Remove any existing handlers from root logger
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create formatters
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Only add file handler if debug mode is enabled
    if debug_mode:
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        log_file = os.path.join(log_dir, f"arxiv_reference_checker_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
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
    
    # Suppress ArXiv library logging to stdout
    arxiv_logger = logging.getLogger('arxiv')
    arxiv_logger.setLevel(logging.WARNING)  # Only show warnings and errors
    
    # Get logger for this module
    logger = logging.getLogger(__name__)
    
    return logger

# Initialize logger (default to INFO for console)
logger = setup_logging(debug_mode=False)

class ArxivReferenceChecker:
    def __init__(self, semantic_scholar_api_key=None, db_path=None, output_file=None, 
                 llm_config=None, debug_mode=False, enable_parallel=True, max_workers=4):
        # Initialize the reference checker for non-arXiv references
        self.fatal_error = False            
        self.db_path = db_path
        self.verification_output_file = output_file
        
        if db_path:
            logger.info(f"Using local Semantic Scholar database at {db_path} (completely offline mode)")
            if enable_parallel:
                logger.debug("Using thread-safe database checker for parallel processing")
                self.non_arxiv_checker = ThreadSafeLocalChecker(db_path=db_path)
            else:
                self.non_arxiv_checker = LocalNonArxivReferenceChecker(db_path=db_path)
            self.service_order = "Local Semantic Scholar Database (offline)"
        else:
            logger.debug("Using enhanced hybrid checker with multiple API sources")
            # Create an enhanced hybrid checker with multiple reliable APIs
            self.non_arxiv_checker = EnhancedHybridReferenceChecker(
                semantic_scholar_api_key=semantic_scholar_api_key,
                db_path=None,  # No local DB in this branch
                contact_email=None,  # Could be added as parameter
                enable_openalex=True,  # Enable OpenAlex as reliable fallback
                enable_crossref=True,   # Enable CrossRef for DOI verification
                debug_mode=debug_mode  # Pass debug mode for conditional logging
            )
            self.service_order = "Semantic Scholar API → OpenAlex → CrossRef"
        
        # debug mode
        self.debug_mode = debug_mode
        
        # Initialize extraction flags
        self.used_regex_extraction = False
        self.used_unreliable_extraction = False
        
        # Parallel processing configuration
        self.enable_parallel = enable_parallel
        self.max_workers = max_workers
        
        # Log parallel configuration
        if self.enable_parallel:
            logger.debug(f"Parallel processing enabled with {self.max_workers} workers")
        else:
            logger.info("Sequential processing mode enabled")
        
        # Initialize errors list
        self.errors = []
        
        # Track if we're processing a single paper (for output optimization)
        self.single_paper_mode = False
        self.current_paper_info = None
        
        # Report service order for arXiv lookups
        if not db_path:
            logger.debug(f"Service order for arXiv verification: Local DB → Intelligent API Switching (Semantic Scholar ↔ arXiv)")
        else:
            logger.debug(f"Service order for arXiv verification: Local DB only (offline mode)")
        
        # Report service order for non-arXiv lookups
        if not db_path:
            logger.debug(f"Service order for reference verification: {self.service_order}")
        self.client = arxiv.Client(
            page_size=100,
            delay_seconds=3,  # Rate limiting to avoid overloading the API
            num_retries=5
        )
        
        # Create output directory
        if self.debug_mode: 
            self.output_dir = "output"
            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir)
                
        # Initialize LLM-based reference extraction
        try:
            from config.settings import get_config
            self.config = get_config()
        except ImportError:
            self.config = {}
        self.llm_config_override = llm_config
        self.llm_extractor = self._initialize_llm_extractor()
        
        # if we were supposed to create an llm extractor but failed, we should not continue
        if self.llm_enabled and not self.llm_extractor:
            logger.error("LLM-based reference extraction is required but could not be initialized. Exiting.")
            self.fatal_error = True
            return

        # Initialize new services
        self.pdf_processor = PDFProcessor(self.config.get('processing', {}))
        self.config_validator = ConfigValidator()
        
        # Initialize metadata cache for improved performance
        self._metadata_cache = {}
        
        # Initialize consolidated error storage
        self.errors = []
    
    def _initialize_llm_extractor(self):
        """Initialize LLM-based reference extraction if enabled"""
        # Check if LLM is explicitly disabled
        if self.llm_config_override and self.llm_config_override.get('disabled'):
            logger.info("LLM-based reference extraction disabled via command line")
            return None
            
        # Check if LLM is enabled via command line override or config
        self.llm_enabled = (self.llm_config_override is not None) or self.config.get("llm", {}).get("enabled", False)
        
        if not self.llm_enabled:
            return None
        
        # Use command line overrides if provided, otherwise use config
        if self.llm_config_override:
            provider_name = self.llm_config_override['provider']
            provider_config = self.config.get("llm", {}).get(provider_name, {}).copy()
            
            # Override with command line parameters
            if self.llm_config_override.get('model'):
                provider_config['model'] = self.llm_config_override['model']
            if self.llm_config_override.get('api_key'):
                provider_config['api_key'] = self.llm_config_override['api_key']
            if self.llm_config_override.get('endpoint'):
                provider_config['endpoint'] = self.llm_config_override['endpoint']
                
            # Update global LLM config with parallel processing overrides
            if 'parallel_chunks' in self.llm_config_override:
                self.config.setdefault("llm", {})['parallel_chunks'] = self.llm_config_override['parallel_chunks']
            if 'max_chunk_workers' in self.llm_config_override:
                self.config.setdefault("llm", {})['max_chunk_workers'] = self.llm_config_override['max_chunk_workers']
        else:
            llm_config = self.config.get("llm", {})
            provider_name = llm_config.get("provider")
            if not provider_name:
                logger.error("No LLM provider specified in configuration")
                return None
            provider_config = llm_config.get(provider_name, {})
        
        # Create LLM provider
        llm_provider = create_llm_provider(provider_name, provider_config)
        if not llm_provider:
            logger.warning(f"Failed to create LLM provider: {provider_name}")
            return None
        
        # When LLM is explicitly requested, disable fallback to make failures terminal
        fallback_enabled = False
        extractor = ReferenceExtractor(
            llm_provider=llm_provider,
            fallback_enabled=fallback_enabled
        )
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
            
        logger.debug(f"Pre-fetching {len(arxiv_ids_to_fetch)} ArXiv references in batches...")
        
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
                        
        logger.debug(f"Pre-fetched {len(self._metadata_cache)} ArXiv references")
    
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
        
    def extract_arxiv_id_from_url(self, url):
        """
        Extract ArXiv ID from a URL or text containing ArXiv reference.
        Uses the common extraction function from refchecker.utils.url_utils.
        """
        return extract_arxiv_id_from_url(url)
    
    def get_paper_metadata(self, arxiv_id):
        """
        Get metadata for a paper using its ArXiv ID with intelligent API switching.
        Priority: Local DB > Semantic Scholar API > arXiv API, with fallback switching.
        """
        # First, try to get the paper from local Semantic Scholar database
        logger.debug(f"Attempting to fetch {arxiv_id} from local database first")
        local_result = self.get_arxiv_paper_from_local_db(arxiv_id)
        
        if local_result:
            logger.debug(f"Successfully found {arxiv_id} in local database")
            return local_result
        
        # Check cache before making API calls
        if hasattr(self, '_metadata_cache') and arxiv_id in self._metadata_cache:
            logger.debug(f"Successfully found {arxiv_id} in cache")
            return self._metadata_cache[arxiv_id]
        
        # If not found in local database but we have a local DB, try ArXiv API as fallback
        if self.db_path:
            logger.debug(f"Paper {arxiv_id} not found in local database, trying ArXiv API fallback")
            return self.get_paper_metadata_with_api_switching(arxiv_id)
        
        # If no local database, try both APIs with intelligent switching
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

        # Try arXiv API
        logger.debug(f"Semantic Scholar API failed for {arxiv_id}, trying arXiv API")
        arxiv_result = self.get_paper_metadata_from_arxiv(arxiv_id)
        
        if arxiv_result:
            self._api_performance['arxiv']['success'] += 1
            logger.debug(f"Successfully fetched {arxiv_id} from arXiv API")
            return arxiv_result
        
        # Try Semantic Scholar API 
        logger.debug(f"Trying Semantic Scholar API for {arxiv_id}")
        semantic_result = self.get_paper_metadata_from_semantic_scholar(arxiv_id)
        
        if semantic_result:
            self._api_performance['semantic_scholar']['success'] += 1
            logger.debug(f"Successfully fetched {arxiv_id} from Semantic Scholar API")
            return semantic_result
        
        # If both failed, try reverse order (sometimes one API works when the other doesn't)
        logger.debug(f"Both APIs failed for {arxiv_id}, trying reverse order")
        
        # Try arXiv API first this time
        arxiv_result = self.get_paper_metadata_from_arxiv(arxiv_id)
        if arxiv_result:
            self._api_performance['arxiv']['success'] += 1
            logger.debug(f"Successfully fetched {arxiv_id} from arXiv API (reverse order)")
            return arxiv_result
        
        # Try Semantic Scholar API again
        semantic_result = self.get_paper_metadata_from_semantic_scholar(arxiv_id)
        if semantic_result:
            self._api_performance['semantic_scholar']['success'] += 1
            logger.debug(f"Successfully fetched {arxiv_id} from Semantic Scholar API (reverse order)")
            return semantic_result
        
        # Both APIs failed
        logger.debug(f"Paper {arxiv_id} not found in any source")
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
                logger.debug(f"Rate limited by Semantic Scholar API for {arxiv_id}")
                return None
            else:
                self._api_performance['semantic_scholar']['failed'] += 1
                logger.debug(f"Semantic Scholar API returned status {response.status_code} for {arxiv_id}")
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
                logger.debug(f"Paper {arxiv_id} not found in arXiv API")
                return None
                
        except Exception as e:
            self._api_performance['arxiv']['failed'] += 1
            logger.error(f"Error fetching metadata from arXiv API for {arxiv_id}: {str(e)}")
            return None
    
    def _create_local_file_paper(self, file_path):
        """
        Create a paper object for local PDF, LaTeX, or text files, or PDF URLs
        
        Args:
            file_path: Path to the local file or URL to a PDF
            
        Returns:
            Paper object compatible with ArXiv paper interface
        """
        class LocalFilePaper:
            def __init__(self, path, is_url=False):
                self.file_path = path
                self.is_url = is_url
                self.is_latex = path.lower().endswith('.tex')
                self.is_text_refs = path.lower().endswith('.txt')
                self.is_bibtex = path.lower().endswith('.bib')
                
                if is_url:
                    # Extract meaningful title from URL
                    url_path = urlparse(path).path
                    filename = os.path.splitext(os.path.basename(url_path))[0]
                    
                    # Handle repository URLs that end with generic names like "content"
                    if not filename or filename.lower() in ['content', 'download', 'pdf']:
                        # Try to extract from the domain and path
                        parsed = urlparse(path)
                        if 'repository' in parsed.netloc:
                            domain_parts = parsed.netloc.split('.')
                            # Find the institution name (usually the second part in repository.institution.edu)
                            if len(domain_parts) >= 2 and domain_parts[0] == 'repository':
                                institution = domain_parts[1] if domain_parts[1] else 'Repository'
                            else:
                                institution = domain_parts[0] if domain_parts else 'Repository'
                            self.title = f"{institution.upper()} Repository PDF"
                        else:
                            self.title = "Downloaded PDF"
                    else:
                        self.title = filename.replace('_', ' ').title()
                else:
                    # Extract filename without extension for title
                    filename = os.path.splitext(os.path.basename(path))[0]
                    self.title = filename.replace('_', ' ').title()
                    
                self.authors = []  # Empty list for compatibility
                self.pdf_url = path if is_url else None
                
                class PublishedDate:
                    def __init__(self):
                        self.year = datetime.datetime.now().year
                
                self.published = PublishedDate()
                
            def get_short_id(self):
                if self.is_url:
                    url_path = urlparse(self.file_path).path
                    basename = os.path.basename(url_path)
                    
                    # Special handling for arXiv URLs - preserve the full arXiv ID
                    if 'arxiv.org' in self.file_path:
                        # For arXiv URLs, the entire basename is the arXiv ID (no file extension)
                        filename = basename
                    else:
                        # For other URLs, use normal extension removal
                        filename = os.path.splitext(basename)[0]
                    
                    if not filename:
                        filename = "downloaded_pdf"
                    return f"url_{filename}"
                else:
                    filename = os.path.splitext(os.path.basename(self.file_path))[0]
                    return f"local_{filename}"
        
        # Check if it's a URL
        is_url = file_path.startswith('http')
        return LocalFilePaper(file_path, is_url=is_url)

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
    
    def log_hybrid_checker_performance_stats(self):
        """
        Log performance statistics from the EnhancedHybridReferenceChecker
        """
        if hasattr(self.non_arxiv_checker, 'log_performance_summary'):
            logger.info("Enhanced Hybrid Checker Performance Summary:")
            self.non_arxiv_checker.log_performance_summary()
        
        # Note: No separate backup hybrid checker anymore since main checker is the hybrid one
    
    def get_comprehensive_performance_stats(self):
        """
        Get comprehensive performance stats including hybrid checker data
        
        Returns:
            Dict with complete performance statistics
        """
        stats = {
            'api_performance': self.get_api_performance_summary(),
            'hybrid_checker_stats': {}
        }
        
        # Get stats from main non-arxiv checker if it's an EnhancedHybridReferenceChecker
        if hasattr(self.non_arxiv_checker, 'get_performance_stats'):
            stats['hybrid_checker_stats']['main'] = self.non_arxiv_checker.get_performance_stats()
        
        # Note: No separate backup hybrid checker needed - main checker is now the hybrid one
        
        return stats
    
    def download_pdf(self, paper):
        """Download the PDF of a paper and return the content as bytes."""
        # Check if this is a local file or URL
        if hasattr(paper, 'file_path') and paper.file_path:
            if hasattr(paper, 'is_url') and paper.is_url:
                # This is a URL, download it
                logger.info(f"Downloading PDF from URL: {paper.file_path}")
                return self.download_pdf_from_url(paper.file_path)
            else:
                # This is a local file
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
            logger.debug(f"Using provided PDF URL: {pdf_url}")
        else:
            # Construct the PDF URL manually from the paper ID
            pdf_url = f"https://arxiv.org/pdf/{paper.get_short_id()}.pdf"
            logger.debug(f"PDF URL was None, constructed manually: {pdf_url}")
        
        logger.info(f"Downloading PDF from {pdf_url}")
        
        try:
            response = requests.get(pdf_url, timeout=30)
            response.raise_for_status()
            return io.BytesIO(response.content)
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download PDF for {paper.get_short_id()}: {e}")
            return None

    def download_pdf_from_url(self, url):
        """Download a PDF from a direct URL and return the content as bytes."""       
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Check if the response is actually a PDF
            content_type = response.headers.get('content-type', '').lower()
            if 'application/pdf' not in content_type and not url.lower().endswith('.pdf'):
                logger.warning(f"URL might not be a PDF. Content-Type: {content_type}")
            
            return io.BytesIO(response.content)
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download PDF from URL {url}: {e}")
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
                logger.info(f"Read LaTeX file with latin-1 encoding")
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
            # Try with pypdf first
            text = ""
            pdf_content.seek(0)  # Reset file pointer
            pdf_reader = pypdf.PdfReader(pdf_content)
            
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text += page.extract_text() + "\n"
            
            return text
        except Exception as e:
            logger.error(f"Error extracting text with pypdf: {str(e)}")
            
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
            # Patterns for numbered sections with potential spacing issues from PDF extraction
            r'(?i)\d+\s*ref\s*er\s*ences\s*\n',  # "12 Refer ences" with spaces
            r'(?i)\d+\s*references\s*\n',  # "12References" or "12 References"
            r'(?i)^\s*\d+\.\s*references\s*$',  # Numbered section: "7. References"
            r'(?i)\d+\s+references\s*\.',  # "9 References." format used in Georgia Tech paper
            # Standard reference patterns
            r'(?i)references\s*\n',
            r'(?i)bibliography\s*\n',
            r'(?i)works cited\s*\n',
            r'(?i)literature cited\s*\n',
            r'(?i)references\s*$',  # End of document
            r'(?i)\[\s*references\s*\]',  # [References]
            r'(?i)^\s*references\s*$',  # References as a standalone line
            r'(?i)^\s*bibliography\s*$',  # Bibliography as a standalone line
            r'(?i)references\s*and\s*citations',  # References and Citations
            r'(?i)cited\s*references',  # Cited References
            r'(?i)reference\s*list',  # Reference List
            r'(?i)references\s*cited',  # References Cited
            r'(?i)sources\s*cited',  # Sources Cited
            r'(?i)references\s*and\s*notes',  # References and Notes
            r'\\begin\{thebibliography\}',  # LaTeX bibliography environment
            r'\\bibliography\{[^}]+\}',  # BibTeX \bibliography{} command
            # Roman numeral patterns
            r'(?i)^\s*[IVX]+\.\s*references\s*$',  # "IX. References"
            r'(?i)^\s*[IVX]+\s*references\s*$',   # "IX References"
            # Generic patterns that might match false positives - put at end
            r'(?i)^\s*sources\s*$',  # Sources as section header only
        ]
        
        # Try to find the bibliography section
        bibliography_text = None
        
        # Collect all potential matches from all patterns
        all_matches = []
        for pattern in section_patterns:
            matches = list(re.finditer(pattern, text))
            for match in matches:
                all_matches.append((pattern, match))
        
        if all_matches:
            # Find the match that has [1] following it (indicating start of references)
            best_match = None
            best_pattern = None
            
            for pattern, match in all_matches:
                test_start = match.end()
                # Look for [1] within reasonable distance after the match
                test_text = text[test_start:test_start + 100]
                if '[1]' in test_text:
                    best_match = match
                    best_pattern = pattern
                    break
            
            # If no match has [1] following it, fall back to the last match
            if not best_match:
                best_pattern, best_match = all_matches[-1]
            
            match = best_match
            start_pos = match.end()
            
            logger.debug(f"Found bibliography section with pattern: {best_pattern}")
            logger.debug(f"Match: {match.group(0)}")
            
            # Find the next section heading or end of document
            # Look for common section endings that come after references
            next_section_patterns = [
                # HIGHEST PRIORITY: Table/Data patterns that immediately follow references
                r'\n\s*(?:Relation|Table|Figure)\s*#?\s*(?:Samples|[0-9]+[:\.]?)\s+.*\n',  # "Relation # Samples", "Table 1:", "Figure 1:"
                r'\n\s*[A-Za-z\s]+\s+#\s+[A-Za-z\s]+\s+[A-Za-z\s]+\s+[A-Za-z\s]+\n',  # Structured table headers like "Relation # Samples Context Templates Query Templates"
                # HIGH PRIORITY: Appendix patterns that appear at the end of bibliography
                # General pattern for single letter appendix sections - must come FIRST to catch earliest occurrence
                r'\n\s*[A-Z]\s+(?:[A-Z]{2,}|[A-Z][a-z]+)(?:\s+(?:[A-Z]{2,}|[A-Z][a-z]+))*\s*\n',  # "A LRE Dataset", "A Theoretical Analysis", "B Implementation Details"
                # Specific patterns (kept for backwards compatibility but won't be reached in most cases)
                r'\n\s*[A-Z]\s+Evaluation\s+Details\s*\n',  # Specific "C Evaluation Details"
                # Note: Removed problematic pattern that was matching page numbers in bibliography
                r'\n\s*\d+\.\d+\s+[A-Z][A-Za-z\s]+\n',  # "3.1 Subsection Title"
                # High priority: Common supplementary material patterns
                r'\n\s*SUPPLEMENTARY\s+MATERIAL\s*\n',
                r'\n\s*Supplementary\s+Material\s*\n',  
                r'\n\s*SUPPLEMENTAL\s+MATERIAL\s*\n',
                r'\n\s*Supplemental\s+Material\s*\n',
                r'\n\s*APPENDIX\s*[A-Z]?\s*\n',
                r'\n\s*Appendix\s*[A-Z]?\s*\n',
                r'\n\s*ACKNOWLEDGMENTS?\s*\n',
                r'\n\s*Acknowledgments?\s*\n',
                r'\n\s*AUTHOR\s+CONTRIBUTIONS?\s*\n',
                r'\n\s*Author\s+Contributions?\s*\n',
                r'\n\s*DATA\s+AVAILABILITY\s*\n',
                r'\n\s*Data\s+Availability\s*\n',
                r'\n\s*CODE\s+AVAILABILITY\s*\n',
                r'\n\s*Code\s+Availability\s*\n',
                r'\n\s*SUPPORTING\s+INFORMATION\s*\n',
                r'\n\s*Supporting\s+Information\s*\n',
                r'\n\s*SUPPLEMENTARY\s+INFORMATION\s*\n',
                r'\n\s*Supplementary\s+Information\s*\n',
                r'\n\s*ETHICS\s+STATEMENT\s*\n',
                r'\n\s*Ethics\s+Statement\s*\n',
                r'\n\s*COMPETING\s+INTERESTS\s*\n',
                r'\n\s*Competing\s+Interests\s*\n',
                r'\n\s*FUNDING\s+INFORMATION\s*\n',
                r'\n\s*Funding\s+Information\s*\n',
                # Pattern for "A Additional...", "B Supplementary...", etc.
                r'\n\s*[A-Z]\s+(?:Additional|Supplementary|Appendix|Extended|Extra|Further)\b[A-Za-z\s\-]*',
                # Pattern for appendix sections like "A Proofs for Section 2", "B Details", etc.
                r'\n\s*[A-Z]\s+(?:Proofs?|Details?|Derivations?|Calculations?|Algorithms?|Examples?|Experiments?|Implementation|Results?)\b[A-Za-z\s\-\d]*',
                # Original patterns
                r'\n\s*[A-Z]\s+[A-Z][A-Za-z\s]*\n',  # A APPENDIX, B RESULTS, etc.
                r'\nA\.\s+Related\s+Work\n',  # Exact match for "A. Related Work"
                r'\n\s*[A-Z]\.\s+(?:ADDITIONAL|SUPPLEMENTARY|CONCLUSION|DISCUSSION|APPENDIX|NOTATION|PROOF|ALGORITHM|ACKNOWLEDGMENT|FUNDING|AUTHOR|CONFLICT|ETHICS|EXPERIMENTAL|THEORETICAL|IMPLEMENTATION|COMPARISON|EVALUATION|RESULTS|ANALYSIS|METHODOLOGY|INTRODUCTION|BACKGROUND|LITERATURE|SURVEY|REVIEW|FUTURE|LIMITATION|CONTRIBUTION|INNOVATION|TECHNICAL|DETAILED|COMPLETE|EXTENDED)\b',  # Other section patterns
                r'\n\s*[A-Z]\.\s+Implementation\s+Details',  # Specific pattern for "A. Implementation Details"
                # More specific pattern for numbered sections - only match section headers, not bibliography entries
                # Look for common section headers like "8. Appendix", "9. Conclusion" but not "8. Smith, J."
                r'\n\s*\d+\.\s+(?:APPENDIX|CONCLUSION|SUPPLEMENTARY|ADDITIONAL|NOTATION|PROOF|ALGORITHM|ACKNOWLEDGMENT|FUNDING|AUTHOR|CONFLICT|ETHICS|DATA|CODE|SUPPORTING|COMPETING|AVAILABILITY|INFORMATION|STATEMENT|CONTRIBUTIONS?)\b[A-Za-z\s]*\n',
                r'\n\s*Appendix\s+[A-Z]',  # Appendix A
                # More restrictive pattern for bracketed sections - only match actual section headers
                # like [APPENDIX], [CONCLUSIONS] but not reference metadata like [Online], [cs], [PDF]
                r'\n\s*\[\s*(?:APPENDIX|CONCLUSIONS?|ACKNOWLEDGMENTS?|SUPPLEMENTARY|ADDITIONAL|NOTATION|PROOF|ALGORITHM)\s*\]',
                # Pattern for consecutive capitalized lines that are clearly section headers (short and uppercase)
                r'\n\s*[A-Z]{3,}\s*\n\s*[A-Z]{3,}\s*\n',  # All caps sections like "APPENDIX\nALGORITHM"
                r'\\end\{thebibliography\}',  # LaTeX bibliography environment end
                r'\\end\{document\}',  # LaTeX document end
            ]
            
            end_pos = len(text)  # Default to end of document
            
            for i, next_pattern in enumerate(next_section_patterns, 1):
                next_match = re.search(next_pattern, text[start_pos:])
                if next_match:
                    section_end = start_pos + next_match.start()
                    logger.debug(f"PATTERN {i} MATCHED: {next_pattern}")
                    logger.debug(f"MATCHED TEXT: {repr(next_match.group(0))}")
                    logger.debug(f"CONTEXT: {repr(text[section_end-30:section_end+30])}")
                    
                    # For table/data patterns, make sure we don't cut off mid-reference
                    # Look backwards to find the end of the previous complete reference
                    if i <= 2:  # First two patterns are table/data patterns
                        # Look backwards from the match to find the end of the last reference
                        # References typically end with a period, year, or arXiv ID
                        search_back = 500  # Look back up to 500 chars
                        search_start = max(start_pos, section_end - search_back)
                        text_before = text[search_start:section_end]
                        
                        # Look for patterns that indicate end of a reference
                        ref_end_patterns = [
                            r'arXiv:\d+\.\d+[v\d]*\.\s*',  # arXiv ID with period
                            r'Preprint[,\.]?\s*arXiv:\d+\.\d+[v\d]*\.\s*',  # Preprint with arXiv ID
                            r'20\d{2}[.\n]\s*',  # Year (2000-2099) with period or newline
                            r'[A-Za-z]+\.\s*$',  # Word ending with period
                        ]
                        
                        best_end = section_end
                        for pattern in ref_end_patterns:
                            matches = list(re.finditer(pattern, text_before, re.MULTILINE))
                            if matches:
                                # Get the last match (closest to section_end)
                                last_match = matches[-1]
                                potential_end = search_start + last_match.end()
                                logger.debug(f"Found reference end pattern: {pattern} at position {potential_end}")
                                best_end = potential_end
                                break
                        
                        section_end = best_end
                        logger.debug(f"Adjusted end position to: {section_end}")
                    
                    # Only use this end position if it's reasonable (not too close to start)
                    if section_end > start_pos + 100 and section_end < end_pos:
                        end_pos = section_end
                        logger.debug(f"ACCEPTED: End position set to {section_end}")
                        break
                    else:
                        logger.debug(f"REJECTED: section_end={section_end}, start_pos={start_pos}, current_end={end_pos}")
            
            bibliography_text = text[start_pos:end_pos]
            logger.debug(f"FINAL BIBLIOGRAPHY: start_pos={start_pos}, end_pos={end_pos}, length={len(bibliography_text)}")
            
            # Check if we have a reasonable amount of text
            if len(bibliography_text.strip()) < 50:
                logger.warning(f"Bibliography section seems too short ({len(bibliography_text)} chars)")
            
            logger.debug(f"Bibliography section length: {len(bibliography_text)} chars")
            logger.debug(f"Bibliography sample: {bibliography_text[:200]}...")
        
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
            
            # Split the main list by commas, handling initials properly
            from refchecker.utils.text_utils import parse_authors_with_initials
            authors = parse_authors_with_initials(main_list)
            
            # Add the last author
            if last_author:
                authors.append(last_author)
        else:
            # No "and" found, use smart comma parsing for initials
            from refchecker.utils.text_utils import parse_authors_with_initials
            authors = parse_authors_with_initials(authors_text)
        
        # Clean up each author name
        cleaned_authors = []
        for author in authors:
            cleaned_author = clean_author_name(author)
            if cleaned_author:
                cleaned_authors.append(cleaned_author)
        
        return cleaned_authors
    
    
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
            title = clean_title_basic(legal_case_match.group(2))
            return [year], title
            
        # Case 2: References with year at start like "2022. Title AuthorName1, AuthorName2, AuthorName3 2022"
        # Look for pattern: YEAR. Title followed by authors ending with the same year
        year_title_authors_match = re.search(r'^(\d{4})\.\s+(.+?)\s+([A-Z][a-z]+.*?)\s+\1\s*$', cleaned_ref)
        if year_title_authors_match:
            year = year_title_authors_match.group(1)
            potential_title = year_title_authors_match.group(2).strip()
            potential_authors = year_title_authors_match.group(3).strip()
            
            # Check if potential_authors looks like a list of authors (contains comma-separated names)
            # and potential_title looks like a title (longer, has multiple words)
            if ',' in potential_authors and len(potential_title.split()) > 3:
                # Extract authors from the authors text
                authors = self.extract_authors_list(potential_authors)
                return authors, clean_title_basic(potential_title)
        
        # Case 2b: References with year at start like "2021. Title Author1, Author2, Author3"
        # More flexible pattern to handle various formats
        year_start_match = re.search(r'^(\d{4})\.\s+(.+?)(?:\s+([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)*[A-Z][a-z]+(?:,\s*[A-Z][a-z]+(?:\s+[A-Z]\.?\s*)*[A-Z][a-z]+)*(?:\s+and\s+[A-Z][a-z]+(?:\s+[A-Z]\.?\s*)*[A-Z][a-z]+)?)\s*(?:\d{4})?\s*$)', cleaned_ref)
        if year_start_match:
            year = year_start_match.group(1)
            title = year_start_match.group(2).strip()
            authors_text = year_start_match.group(3) if year_start_match.group(3) else None
            
            if authors_text:
                # Extract authors from the authors text
                authors = self.extract_authors_list(authors_text)
                return authors, clean_title_basic(title)
            else:
                # If we can't extract authors, fall back to using year as author
                return [year], clean_title_basic(title)
        
        # Case 2c: Simple year at start like "1976. Title"
        simple_year_start_match = re.search(r'^(\d{4})\.\s+([^.]+?)(?:\.\s+https?://|\.\s*$)', cleaned_ref)
        if simple_year_start_match:
            year = simple_year_start_match.group(1)
            title = clean_title_basic(simple_year_start_match.group(2))
            return [year], title
        
        # Case 3: Legal cases with reference number and year like "[1]1976. Title"
        legal_case_with_ref_match = re.search(r'^\[\d+\](\d{4})\.\s+([^.]+?)(?:\.\s+https?://|\.\s*$)', cleaned_ref)
        if legal_case_with_ref_match:
            year = legal_case_with_ref_match.group(1)
            title = clean_title_basic(legal_case_with_ref_match.group(2))
            return [year], title
        
        # Normalize spacing around periods
        cleaned_ref = re.sub(r'([A-Z])\s+\.\s+', r'\1. ', cleaned_ref)
        cleaned_ref = re.sub(r'([A-Z])\s+\.([A-Za-z])', r'\1. \2', cleaned_ref)

        # Check if this is a URL-based reference (common in some papers)
        if re.search(r'https?://', cleaned_ref):
            # This is likely a URL reference, not a standard academic citation
            # Handle multi-line URLs by removing newlines and reconstructing
            url_pattern = r'(https?://[^\s]*(?:\n[^\s\[\]]*)*)'
            url_match = re.search(url_pattern, cleaned_ref)
            if url_match:
                # Extract and reconstruct the URL
                raw_url = url_match.group(1).strip()
                # Remove newlines and spaces within the URL
                url = re.sub(r'\s+', '', raw_url)
                
                # For URL references, extract any remaining text as title
                remaining_text = cleaned_ref.replace(raw_url, '').strip()
                # Remove trailing periods and clean up
                remaining_text = re.sub(r'^\s*[.\s]*|[.\s]*$', '', remaining_text)
                
                # Return a special marker to indicate this is a URL reference
                return [{"is_url_reference": True}], remaining_text if remaining_text else url
        
        # Also check if the reference contains only a URL (possibly with some ID)
        if re.search(r'^https?://', cleaned_ref) and not re.search(r'[A-Z][a-z]+ [A-Z][a-z]+', cleaned_ref):
            # This is likely just a URL with maybe some ID
            url_pattern = r'(https?://[^\s]*(?:\n[^\s\[\]]*)*)'
            url_match = re.search(url_pattern, cleaned_ref)
            if url_match:
                raw_url = url_match.group(1).strip()
                url = re.sub(r'\s+', '', raw_url)
                remaining_text = cleaned_ref.replace(raw_url, '').strip()
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
            title = clean_title(title)
            
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
            title = clean_title(title)
            
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
                title = clean_title(title)
                
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
            title = clean_title(title)
            
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
                title = clean_title(title)
                
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
            title = clean_title(title)
            
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
            title = clean_title(title)
            
            if authors and title:
                return authors, title

        # Handle specific problematic cases from the bibliography
        # Case 3: Alexander Street Press references with incomplete titles
        alexander_street_match = re.search(r'Alexander Street Press \(Ed\.\)\.\s+(\d{4})\.\s+([^.]+?)(?:\.\s+Alexander Street Press|\.\s*$)', cleaned_ref)
        if alexander_street_match:
            year = alexander_street_match.group(1)
            title = clean_title_basic(alexander_street_match.group(2))
            return ["Alexander Street Press (Ed.)"], title
            
        # Case 4: References with incomplete author names like "Alan S." and "Tara F."
        incomplete_author_match = re.search(r'([A-Z][a-z]+ [A-Z]\.)\s+(\d{4})\.\s+([^.]+?)(?:\.\s+[A-Z][a-z]+|\.\s*$)', cleaned_ref)
        if incomplete_author_match:
            author = incomplete_author_match.group(1).strip()
            year = incomplete_author_match.group(2)
            title = clean_title_basic(incomplete_author_match.group(3))
            return [author], title
            
        # Case 5: References with complete author lists but incomplete titles
        complete_author_incomplete_title_match = re.search(r'([^.]+?)\.\s+(\d{4})\.\s+([^.]+?)(?:\.\s+[A-Z][a-z]+|\.\s*$)', cleaned_ref)
        if complete_author_incomplete_title_match:
            authors_text = complete_author_incomplete_title_match.group(1).strip()
            year = complete_author_incomplete_title_match.group(2)
            title = clean_title_basic(complete_author_incomplete_title_match.group(3))
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
            title = clean_title(title)

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
            title = clean_title(title)
            
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
            title = clean_title(title)
            
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
                title = clean_title(title)
                
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
            title = clean_title(title)
            
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
            title = clean_title(title)
            
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
                from refchecker.utils.text_utils import parse_authors_with_initials
                authors = parse_authors_with_initials(cleaned_ref)
                return authors, ""
        
        if authors_text and title:
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            # Clean the title
            title = clean_title(title)
            if authors and title:
                return authors, title
        
        # Final fallback: if the reference is just a list of names, return as authors
        if not title and cleaned_ref and re.match(r'^[A-Z][a-zA-Z\-\.]+(,\s*[A-Z][a-zA-Z\-\.]+)+$', cleaned_ref):
            from refchecker.utils.text_utils import parse_authors_with_initials
            authors = parse_authors_with_initials(cleaned_ref)
            return authors, ""
        
        # Fallback: if the reference is just a list of author names (with initials, and 'and' before last author), treat as authors
        if not title and not authors_text:
            # Match patterns like 'Tara F. Bishop, Matthew J. Press, Salomeh Keyhani, and Harold Alan Pincus'
            author_list_pattern = r'^(?:[A-Z][a-zA-Z\-]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-zA-Z\-]+)?(?:,\s+)?)+(?:and\s+[A-Z][a-zA-Z\-]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-zA-Z\-]+)?)?$'
            if re.match(author_list_pattern, cleaned_ref.replace(' and ', ', and ')):
                # Split on ', ' and ' and ' for the last author
                authors = re.split(r',\s+|\s+and\s+', cleaned_ref)
                cleaned_authors = []
                for a in authors:
                    a = a.strip()
                    # Remove leading "and" from author names (handles cases like "and Krishnamoorthy, S")
                    a = re.sub(r'^and\s+', '', a)
                    if a:
                        cleaned_authors.append(a)
                authors = cleaned_authors
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
                doi = doi_match.group(1).split('#')[0]  # Strip URL fragments

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

                        authors_match, author_error = compare_authors(authors, db_authors)
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
                from refchecker.utils.error_utils import format_title_mismatch
                # Clean the title for display (remove LaTeX commands like {LLM}s -> LLMs)
                clean_cited_title = strip_latex_commands(title)
                logger.debug(f"DB Verification: Title mismatch - cited: '{title}', actual: '{paper_data.get('title')}'")
                errors.append({
                    'error_type': 'title',
                    'error_details': format_title_mismatch(clean_cited_title, paper_data.get('title')),
                    'ref_title_correct': paper_data.get('title')
                })
        
        # Verify authors
        if authors and paper_data.get('authors'):
            # Extract author names from database data
            correct_names = [author.get('name', '') for author in paper_data['authors']]
            authors_match, author_error = compare_authors(authors, correct_names)
            
            if not authors_match:
                logger.debug(f"DB Verification: Author mismatch - {author_error}")
                errors.append({
                    'error_type': 'author',
                    'error_details': author_error,
                    'ref_authors_correct': ', '.join(correct_names)
                })
        
        # Verify year (with tolerance)
        paper_year = paper_data.get('year')
        # Get year tolerance from config (default to 1 if not available)
        year_tolerance = 1  # Default tolerance
        try:
            from config.settings import get_config
            config = get_config()
            year_tolerance = config.get('text_processing', {}).get('year_tolerance', 1)
        except (ImportError, Exception):
            pass  # Use default if config not available
        
        from refchecker.utils.error_utils import validate_year
        year_warning = validate_year(
            cited_year=year,
            paper_year=paper_year,
            year_tolerance=year_tolerance
        )
        if year_warning:
            logger.debug(f"DB Verification: Year issue - {year_warning.get('warning_details', '')}")
            errors.append(year_warning)
        
        # Verify DOI
        if doi and external_ids.get('DOI'):
            from refchecker.utils.doi_utils import compare_dois, normalize_doi
            
            # Use proper DOI comparison first
            if not compare_dois(doi, external_ids['DOI']):
                # Check if the cited DOI is a partial match of the actual DOI
                # This handles cases like "10.1111/j.2044-8260." vs "10.1111/J.2044-8260.1997.TB01237.X"
                cited_doi_normalized = normalize_doi(doi)
                actual_doi_normalized = normalize_doi(external_ids['DOI'])
                
                # If the cited DOI is a prefix of the actual DOI, it's likely a partial citation
                # Only flag as error if it's not a reasonable partial match
                if not actual_doi_normalized.startswith(cited_doi_normalized.rstrip('.')):
                    logger.debug(f"DB Verification: DOI mismatch - cited: {doi}, actual: {external_ids['DOI']}")
                    from refchecker.utils.error_utils import format_doi_mismatch
                    from refchecker.utils.doi_utils import validate_doi_resolves
                    # If cited DOI resolves, it's likely a valid alternate DOI (e.g., arXiv vs conference)
                    # Treat as warning instead of error
                    if validate_doi_resolves(doi):
                        errors.append({
                            'warning_type': 'doi',
                            'warning_details': format_doi_mismatch(doi, external_ids['DOI']),
                            'ref_doi_correct': external_ids['DOI']
                        })
                    else:
                        errors.append({
                            'error_type': 'doi',
                            'error_details': format_doi_mismatch(doi, external_ids['DOI']),
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
            Tuple of (errors, url, verified_data) where:
            - errors: List of errors or None if no errors found
            - url: URL of the paper if found, None otherwise
            - verified_data: The verified paper data from the verification service, None if not found
        """
        # Check if reference authors contains "URL Reference" marker
        if reference.get('authors') and "URL Reference" in reference.get('authors', []):
            # Skip verification for URL references
            return None, None, None
        
        # Route all references through the same non-arxiv path for consistent verification
        
        # If database mode is enabled, use database for non-ArXiv references
        if self.db_path:
            # Check if we have a database checker (either original or thread-safe)
            if hasattr(self.non_arxiv_checker, 'conn') or hasattr(self.non_arxiv_checker, 'connection_pool'):
                # Use the local database checker's verify_reference method which returns URLs
                verified_data, errors, paper_url = self.non_arxiv_checker.verify_reference(reference)
                logger.debug(f"Database mode: Initial paper_url from database checker: {paper_url}")
                
                if not verified_data:
                    # Mark as unverified but check URL for more specific reason or verification
                    if reference.get('url', '').strip():
                        # Use raw URL verifier to check if it can be verified or get specific reason
                        url_verified_data, url_errors, url_checked = self.verify_raw_url_reference(reference)
                        if url_verified_data:
                            # URL verification succeeded - return as verified
                            logger.debug(f"Database mode: URL verification succeeded for unverified reference")
                            return None, url_checked, url_verified_data
                        else:
                            # URL verification failed - use specific error reason
                            url_error_details = url_errors[0].get('error_details', 'Reference could not be verified in database') if url_errors else 'Reference could not be verified in database'
                            return [{"error_type": "unverified", "error_details": url_error_details}], paper_url, None
                    else:
                        return [{"error_type": "unverified", "error_details": "Reference could not be verified in database"}], paper_url, None
                
                # Convert database errors to our format
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
                    elif 'info_type' in error:
                        formatted_error['info_type'] = error['info_type']
                        formatted_error['info_details'] = error['info_details']
                    
                    # Add correct information based on error type
                    if error.get('error_type') == 'author':
                        formatted_error['ref_authors_correct'] = error.get('ref_authors_correct', '')
                    elif error.get('error_type') == 'year' or error.get('warning_type') == 'year':
                        formatted_error['ref_year_correct'] = error.get('ref_year_correct', '')
                    elif error.get('error_type') == 'doi':
                        from refchecker.utils.doi_utils import construct_doi_url
                        formatted_error['ref_url_correct'] = construct_doi_url(error.get('ref_doi_correct', ''))
                    elif error.get('info_type') == 'url':
                        formatted_error['ref_url_correct'] = error.get('ref_url_correct', '')
                    
                    formatted_errors.append(formatted_error)
                
                # Check for ArXiv ID mismatch in database mode as well
                arxiv_errors = self.check_independent_arxiv_id_mismatch(reference, verified_data)
                logger.debug(f"Database mode: ArXiv ID mismatch check for '{reference.get('title', 'Unknown')}': {len(arxiv_errors) if arxiv_errors else 0} errors found")
                if arxiv_errors:
                    logger.debug("Database mode: ArXiv ID mismatch detected - replacing other errors with ArXiv ID error only")
                    logger.debug(f"Original paper_url before ArXiv ID mismatch fix: {paper_url}")
                    
                    # For ArXiv ID mismatch, we need to find the CORRECT paper (not the wrong one from ArXiv ID)
                    # The verified_data contains the wrong paper's data, so we need to search by title/authors
                    correct_paper_data = None
                    correct_paper_url = None
                    try:
                        title = reference.get('title', '').strip()
                        authors = reference.get('authors', [])
                        year = reference.get('year')
                        
                        if title or authors:
                            logger.debug(f"Database mode: Searching for correct paper by title/authors for ArXiv ID mismatch")
                            # Use the database checker to find the correct paper by title/authors
                            correct_paper_data = self.non_arxiv_checker.find_best_match(title, authors, year)
                            
                            if correct_paper_data:
                                logger.debug(f"Database mode: Found correct paper: '{correct_paper_data.get('title', '')}'")
                                # Use the CORRECT paper's Semantic Scholar URL
                                if correct_paper_data.get('paperId'):
                                    correct_paper_url = f"https://www.semanticscholar.org/paper/{correct_paper_data['paperId']}"
                                    paper_url = correct_paper_url  # Update the main URL
                                    logger.debug(f"Database mode: Using correct paper's Semantic Scholar URL for ArXiv ID mismatch: {paper_url}")
                                else:
                                    logger.debug("Database mode: Correct paper found but no paperId available")
                            else:
                                logger.debug("Database mode: Could not find correct paper by title/authors")
                    except Exception as e:
                        logger.debug(f"Database mode: Error finding correct paper for ArXiv ID mismatch: {e}")
                    
                    # Build formatted errors with correct URL
                    formatted_errors = []
                    for error in arxiv_errors:
                        formatted_error = {
                            'error_type': error['error_type'],
                            'error_details': error['error_details']
                        }
                        # Add the correct URL if we found the correct paper
                        if correct_paper_url:
                            formatted_error['ref_url_correct'] = correct_paper_url
                        elif error.get('ref_url_correct'):
                            formatted_error['ref_url_correct'] = error['ref_url_correct']
                        formatted_errors.append(formatted_error)
                    
                    # Fallback to wrong paper's URL if we couldn't find the correct one
                    if not correct_paper_data and verified_data and verified_data.get('paperId'):
                        paper_url = f"https://www.semanticscholar.org/paper/{verified_data['paperId']}"
                        logger.debug(f"Database mode: Fallback to wrong paper's Semantic Scholar URL: {paper_url}")
                    elif not correct_paper_data:
                        logger.debug(f"Database mode: No paperId available for Semantic Scholar URL construction. verified_data keys: {list(verified_data.keys()) if verified_data else 'None'}")
                
                return formatted_errors if formatted_errors else None, paper_url, verified_data
            else:
                logger.warning("Database path specified but no connection available")
                return [{"error_type": "unverified", "error_details": "Database connection not available"}], None, None
        
        # For non-database mode, use the standard reference verification
        errors, paper_url, verified_data = self.verify_reference_standard(source_paper, reference)
        
        # If standard verification failed and the reference has a URL, try raw URL verification
        if errors and verified_data is None:
            # Check if there's an unverified error
            unverified_errors = [e for e in errors if e.get('error_type') == 'unverified']
            if unverified_errors and reference.get('url', '').strip():
                # Use raw URL verifier to check if it can be verified or get specific reason
                url_verified_data, url_errors, url_checked = self.verify_raw_url_reference(reference)
                if url_verified_data:
                    # URL verification succeeded - return as verified
                    logger.debug(f"Non-database mode: URL verification succeeded for unverified reference")
                    return None, url_checked, url_verified_data
                else:
                    # URL verification failed - use specific error reason
                    url_error_details = url_errors[0].get('error_details', 'Reference could not be verified') if url_errors else 'Reference could not be verified'
                    # Update the unverified error with the specific reason
                    for error in errors:
                        if error.get('error_type') == 'unverified':
                            error['error_details'] = url_error_details
                            break
        
        return errors, paper_url, verified_data
    

    def verify_github_reference(self, reference):
        """
        Verify if a reference is a GitHub repository reference
        
        Args:
            reference: The reference to verify
            
        Returns:
            Tuple of (errors, url, verified_data) if this is a GitHub reference,
            None if this is not a GitHub reference
        """
        # Check if this is a GitHub repository reference
        github_url = None
        if reference.get('url') and 'github.com' in reference['url']:
            github_url = reference['url']
        elif reference.get('venue') and 'github.com' in reference.get('venue', ''):
            # Sometimes GitHub URLs are in the venue field
            venue_parts = reference['venue'].split()
            for part in venue_parts:
                if 'github.com' in part:
                    github_url = part
                    break
        
        if not github_url:
            return None  # Not a GitHub reference
        
        logger.debug(f"Detected GitHub URL, using GitHub verification: {github_url}")
        
        # Import and use GitHub checker
        from refchecker.checkers.github_checker import GitHubChecker
        github_checker = GitHubChecker()
        verified_data, errors, paper_url = github_checker.verify_reference(reference)
        
        if verified_data:
            logger.debug(f"GitHub verification successful for: {reference.get('title', 'Untitled')}")
            # Convert errors to our format if needed
            formatted_errors = []
            for error in errors:
                formatted_error = {}
                
                # Handle error_type, warning_type, and info_type properly
                if 'error_type' in error:
                    formatted_error['error_type'] = error['error_type']
                    formatted_error['error_details'] = error['error_details']
                elif 'warning_type' in error:
                    formatted_error['warning_type'] = error['warning_type']
                    formatted_error['warning_details'] = error['warning_details']
                elif 'info_type' in error:
                    formatted_error['info_type'] = error['info_type']
                    formatted_error['info_details'] = error['info_details']
                
                # Add correct information based on error type
                if error.get('warning_type') == 'year':
                    formatted_error['ref_year_correct'] = error.get('ref_year_correct', '')
                elif error.get('info_type') == 'url':
                    formatted_error['ref_url_correct'] = error.get('ref_url_correct', '')
                
                formatted_errors.append(formatted_error)
            
            return formatted_errors if formatted_errors else None, paper_url, verified_data
        else:
            logger.debug(f"GitHub verification failed for: {reference.get('title', 'Untitled')}")
            # Return GitHub verification errors
            formatted_errors = []
            for error in errors:
                formatted_error = {}
                if 'error_type' in error:
                    formatted_error['error_type'] = error['error_type']
                    formatted_error['error_details'] = error['error_details']
                formatted_errors.append(formatted_error)
            return formatted_errors if formatted_errors else [{"error_type": "unverified", "error_details": "GitHub repository could not be verified"}], paper_url, None

    def verify_webpage_reference(self, reference):
        """
        Verify if a reference is a web page reference
        
        Args:
            reference: The reference to verify
            
        Returns:
            Tuple of (errors, url, verified_data) if this is a web page reference,
            None if this is not a web page reference
        """
        # Check if this is a web page reference
        web_url = reference.get('url', '').strip()
        if not web_url:
            return None  # No URL to check
        
        # Import and use web page checker
        from refchecker.checkers.webpage_checker import WebPageChecker
        webpage_checker = WebPageChecker()
        
        if not webpage_checker.is_web_page_url(web_url):
            return None  # Not a web page reference
        
        logger.debug(f"Detected web page URL, using web page verification: {web_url}")
        
        verified_data, errors, page_url = webpage_checker.verify_reference(reference)
        
        if verified_data:
            logger.debug(f"Web page verification successful for: {reference.get('title', 'Untitled')}")
            # Convert errors to our format if needed
            formatted_errors = []
            for error in errors:
                formatted_error = {}
                
                # Handle error_type, warning_type, and info_type properly
                if 'error_type' in error:
                    formatted_error['error_type'] = error['error_type']
                    formatted_error['error_details'] = error['error_details']
                elif 'warning_type' in error:
                    formatted_error['warning_type'] = error['warning_type']
                    formatted_error['warning_details'] = error['warning_details']
                elif 'info_type' in error:
                    formatted_error['info_type'] = error['info_type']
                    formatted_error['info_details'] = error['info_details']
                
                formatted_errors.append(formatted_error)
            
            return formatted_errors if formatted_errors else None, page_url, verified_data
        else:
            logger.debug(f"Web page verification failed for: {reference.get('title', 'Untitled')}")
            # Return web page verification errors
            formatted_errors = []
            for error in errors:
                formatted_error = {}
                if 'error_type' in error:
                    formatted_error['error_type'] = error['error_type']
                    formatted_error['error_details'] = error['error_details']
                formatted_errors.append(formatted_error)
            return formatted_errors if formatted_errors else [{"error_type": "unverified", "error_details": "Web page could not be verified"}], page_url, None

    def verify_raw_url_reference(self, reference):
        """
        Verify a raw URL from an unverified reference - can return verified data if appropriate
        
        Args:
            reference: The reference to verify (already determined to be unverified by paper validators)
            
        Returns:
            Tuple of (verified_data, errors, url) where:
            - verified_data: Dict with verified data if URL should be considered verified, None otherwise
            - errors: List of error dictionaries
            - url: The URL that was checked
        """
        logger.debug(f"Checking raw URL for unverified reference: {reference.get('title', 'Untitled')}")
        
        # Extract URL from reference
        web_url = reference.get('url', '').strip()
        if not web_url:
            return None, [{"error_type": "unverified", "error_details": "Reference could not be verified"}], None
        
        # First try PDF paper checker if URL appears to be a PDF
        from refchecker.checkers.pdf_paper_checker import PDFPaperChecker
        pdf_checker = PDFPaperChecker()
        
        if pdf_checker.can_check_reference(reference):
            logger.debug(f"URL appears to be PDF, trying PDF verification: {web_url}")
            try:
                verified_data, errors, url = pdf_checker.verify_reference(reference)
                if verified_data:
                    logger.debug(f"PDF verification successful for: {reference.get('title', 'Untitled')}")
                    return verified_data, errors, url
                else:
                    logger.debug(f"PDF verification failed, falling back to web page verification")
            except Exception as e:
                logger.error(f"Error in PDF verification: {e}")
                logger.debug(f"PDF verification error, falling back to web page verification")
        
        # Fall back to web page checker
        from refchecker.checkers.pdf_paper_checker import PDFPaperChecker
        pdf_checker = PDFPaperChecker()
        
        if pdf_checker.can_check_reference(reference):
            logger.debug(f"URL appears to be PDF, trying PDF verification: {web_url}")
            try:
                verified_data, errors, url = pdf_checker.verify_reference(reference)
                if verified_data:
                    logger.debug(f"PDF verification successful for: {reference.get('title', 'Untitled')}")
                    return verified_data, errors, url
                else:
                    logger.debug(f"PDF verification failed, falling back to web page verification")
            except Exception as e:
                logger.error(f"Error in PDF verification: {e}")
                logger.debug(f"PDF verification error, falling back to web page verification")
        
        # Fall back to web page checker
        from refchecker.checkers.webpage_checker import WebPageChecker
        webpage_checker = WebPageChecker()
        
        try:
            verified_data, errors, url = webpage_checker.verify_raw_url_for_unverified_reference(reference)
            logger.debug(f"Raw URL verification result: verified_data={verified_data is not None}, errors={len(errors)}, url={url}")
            return verified_data, errors, url
        except Exception as e:
            logger.error(f"Error checking raw URL: {e}")
            return None, [{"error_type": "unverified", "error_details": "Reference could not be verified"}], web_url

    def verify_reference_standard(self, source_paper, reference):
        """
        Verify if a reference is accurate using GitHub, Semantic Scholar, or other checkers
        
        Args:
            source_paper: The paper containing the reference
            reference: The reference to verify
            
        Returns:
            Tuple of (errors, url, verified_data) where:
            - errors: List of errors or None if no errors found
            - url: URL of the paper if found, None otherwise
            - verified_data: The verified paper data from the verification service, None if not found
        """
        logger.debug(f"Verifying non-arXiv reference: {reference.get('title', 'Untitled')}")
        
        # First, check if this is a GitHub repository reference
        github_result = self.verify_github_reference(reference)
        if github_result:
            return github_result
        
        # Use the Semantic Scholar client to verify the reference
        verified_data, errors, paper_url = self.non_arxiv_checker.verify_reference(reference)
        
        logger.debug(f"Non-arXiv verification result: verified_data={verified_data is not None}, errors={len(errors) if errors else 0}, paper_url={paper_url}")
        
        # ALWAYS check for ArXiv ID mismatch first, regardless of verification status
        arxiv_errors = self.check_independent_arxiv_id_mismatch(reference, verified_data)
        
        if not verified_data:
            logger.debug(f"Could not verify non-arXiv reference: {reference.get('title', 'Untitled')}")
            logger.debug(f"Raw text: {reference['raw_text']}")
            
            # If there's also an ArXiv ID mismatch, report both errors
            if arxiv_errors:
                logger.debug("ArXiv ID mismatch detected with unverified paper")
                combined_errors = [
                    {"error_type": "unverified", "error_details": "Reference could not be verified"},
                    *arxiv_errors
                ]
                return combined_errors, paper_url, verified_data
            else:
                # Only unverified error
                return [{"error_type": "unverified", "error_details": "Reference could not be verified"}], paper_url, verified_data
        
        # verified_data exists, check if there's an ArXiv ID mismatch
        if arxiv_errors:
            logger.debug("ArXiv ID mismatch detected with verified paper")
            
            # Check if the verified paper has any displayable URLs after ArXiv ID filtering
            has_displayable_verified_url = False
            if verified_data:
                external_ids = verified_data.get('externalIds', {})
                # Check for non-ArXiv URLs that would be displayed
                if (external_ids.get('DOI') or 
                    external_ids.get('CorpusId') or 
                    (verified_data.get('url') and 'arxiv.org' not in verified_data.get('url', ''))):
                    has_displayable_verified_url = True
            
            if has_displayable_verified_url:
                # Paper has other verification URLs to display, combine ArXiv ID error with original verification errors
                combined_errors = (errors or []) + arxiv_errors
                errors = combined_errors
                logger.debug("ArXiv ID mismatch error for verified paper with displayable URLs")
            else:
                # Paper only has ArXiv URLs which will be filtered out, treat as unverified
                logger.debug("Verified paper has only ArXiv URLs - treating as unverified due to ArXiv ID mismatch")
                combined_errors = [
                    {"error_type": "unverified", "error_details": "Reference could not be verified"},
                    *arxiv_errors
                ]
                errors = combined_errors
            
            # Don't use the wrong paper's URL - return None to indicate no valid URL
            paper_url = None
            logger.debug("Setting paper_url to None due to ArXiv ID mismatch")
        elif errors:
            # Only keep other errors if there's no ArXiv ID mismatch
            logger.debug("No ArXiv ID mismatch, keeping original verification errors")
            pass
        
        # If no errors were found by the Semantic Scholar client, we're done
        if not errors:
            return None, paper_url, verified_data
        
        # Convert the errors to our format
        formatted_errors = []
        
        logger.debug(f"DEBUG: Converting {len(errors)} errors to formatted errors")
        for i, error in enumerate(errors):
            logger.debug(f"DEBUG: Error {i}: {error}")
            formatted_error = {}
            
            # Handle error_type, warning_type, and info_type properly
            if 'error_type' in error:
                formatted_error['error_type'] = error['error_type']
                formatted_error['error_details'] = error['error_details']
            elif 'warning_type' in error:
                formatted_error['warning_type'] = error['warning_type']
                formatted_error['warning_details'] = error['warning_details']
            elif 'info_type' in error:
                formatted_error['info_type'] = error['info_type']
                formatted_error['info_details'] = error['info_details']
            
            # Add correct information based on error type
            if error.get('error_type') == 'author':
                formatted_error['ref_authors_correct'] = error.get('ref_authors_correct', '')
            elif error.get('error_type') == 'year' or error.get('warning_type') == 'year':
                formatted_error['ref_year_correct'] = error.get('ref_year_correct', '')
            elif error.get('error_type') == 'doi':
                from refchecker.utils.doi_utils import construct_doi_url
                formatted_error['ref_url_correct'] = construct_doi_url(error.get('ref_doi_correct', ''))
            
            formatted_errors.append(formatted_error)
        
        logger.debug(f"DEBUG: Returning {len(formatted_errors)} formatted errors: {formatted_errors}")
        return formatted_errors if formatted_errors else None, paper_url, verified_data
    
    def check_independent_arxiv_id_mismatch(self, reference, verified_data):
        """
        Check for ArXiv ID mismatch by comparing the cited paper's metadata 
        with what the ArXiv ID actually points to, independent of verification success.
        
        Args:
            reference: The reference dictionary
            verified_data: The verified paper data (may be None)
            
        Returns:
            List of errors if ArXiv ID points to wrong paper, empty list otherwise
        """
        # Extract ArXiv ID from URL or venue field
        ref_arxiv_id = None
        
        # Check for ArXiv ID in URL
        if reference.get('url') and 'arxiv.org/abs/' in reference['url']:
            ref_arxiv_id = self.extract_arxiv_id_from_url(reference['url'])
        
        # Check for ArXiv ID in venue field (e.g., "arXiv preprint arXiv:1234.5678")
        if not ref_arxiv_id and reference.get('venue'):
            venue_text = reference['venue']
            ref_arxiv_id = self.extract_arxiv_id_from_url(venue_text)
        
        if not ref_arxiv_id:
            return []  # No ArXiv ID to check
        
        # Get what the ArXiv ID actually points to
        actual_arxiv_paper = self.get_paper_metadata(ref_arxiv_id)
        
        # If we have verified data, check for ArXiv ID mismatch
        if verified_data:
            # Check if verified data has an ArXiv ID
            correct_arxiv_id = None
            if verified_data.get('externalIds', {}).get('ArXiv'):
                correct_arxiv_id = verified_data['externalIds']['ArXiv']
            elif verified_data.get('arxivId'):
                correct_arxiv_id = verified_data['arxivId']
            
            if correct_arxiv_id and ref_arxiv_id != correct_arxiv_id:
                # Direct ArXiv ID mismatch - the paper was verified but has different ArXiv ID
                return [{
                    'error_type': 'arxiv_id',
                    'error_details': f"Incorrect ArXiv ID: ArXiv ID {ref_arxiv_id} should be {correct_arxiv_id}"
                }]
            elif correct_arxiv_id is None and not actual_arxiv_paper:
                # Verified paper has no ArXiv ID and cited ArXiv ID doesn't exist
                return [{
                    'error_type': 'arxiv_id',
                    'error_details': f"Invalid ArXiv ID: ArXiv ID {ref_arxiv_id} does not exist"
                }]
        
        # If the cited ArXiv ID doesn't exist and we have no verified data
        if not actual_arxiv_paper:
            logger.debug(f"Could not fetch ArXiv paper metadata for ID: {ref_arxiv_id}")
            if not verified_data:
                # No verified data and invalid ArXiv ID - return error only if this is the primary verification method
                # For references with invalid ArXiv IDs, we should still allow title/author verification to proceed
                # Only return the invalid ArXiv ID error here if the reference appears to be purely ArXiv-based
                if not reference.get('title') and not reference.get('authors'):
                    return [{
                        'error_type': 'arxiv_id',
                        'error_details': f"Invalid ArXiv ID: ArXiv ID {ref_arxiv_id} does not exist"
                    }]
                else:
                    # Let verification proceed, we'll report the invalid ArXiv ID later if verification succeeds
                    return []
            else:
                # We have verified data but the cited ArXiv ID doesn't exist - report as error
                return [{
                    'error_type': 'arxiv_id',
                    'error_details': f"Invalid ArXiv ID: ArXiv ID {ref_arxiv_id} does not exist"
                }]
        
        # Get the expected paper metadata from the reference
        expected_title = reference.get('title', '').strip()
        expected_authors = reference.get('authors', [])
        
        if not expected_title:
            return []  # Can't check without expected title
        
        # Compare expected vs actual
        actual_title = actual_arxiv_paper.title.strip()
        actual_authors = getattr(actual_arxiv_paper, 'authors', [])
        
        # Calculate title similarity
        title_similarity = calculate_title_similarity(expected_title.lower(), actual_title.lower())
        
        logger.debug(f"ArXiv ID {ref_arxiv_id} independent check:")
        logger.debug(f"  Expected title: '{expected_title}'")
        logger.debug(f"  Actual ArXiv title: '{actual_title}'")
        logger.debug(f"  Title similarity: {title_similarity:.3f}")
        
        # If titles are very different (less than 40% similarity), flag as ArXiv ID error
        if title_similarity < 0.4:
            # For ArXiv ID mismatch, we don't provide a correct URL here
            # The correct URL should be determined by finding the right paper by title/authors
            return [{
                'error_type': 'arxiv_id',
                'error_details': f"Incorrect ArXiv ID: ArXiv ID {ref_arxiv_id} points to '{actual_title}'"
            }]
        
        return []

    def check_arxiv_id_mismatch(self, reference, verified_data, ref_arxiv_id):
        """
        Check if an ArXiv ID in the reference points to a different paper than the verified data.
        
        Args:
            reference: The reference with an ArXiv ID
            verified_data: The verified paper data from Semantic Scholar
            ref_arxiv_id: The ArXiv ID found in the reference
            
        Returns:
            List of errors if ArXiv ID points to wrong paper, empty list otherwise
        """
        if not verified_data or not ref_arxiv_id:
            return []
        
        # Get metadata for the ArXiv paper from the ID
        arxiv_paper = self.get_paper_metadata(ref_arxiv_id)
        if not arxiv_paper:
            logger.debug(f"Could not fetch ArXiv paper metadata for ID: {ref_arxiv_id}")
            return []
        
        # Compare the ArXiv paper with the verified paper data
        # Check if they represent different papers by comparing titles and authors
        arxiv_title = arxiv_paper.title.strip()
        verified_title = verified_data.get('title', '').strip()
        
        # Calculate title similarity
        title_similarity = calculate_title_similarity(arxiv_title.lower(), verified_title.lower())
        
        logger.debug(f"ArXiv ID {ref_arxiv_id} title similarity: {title_similarity:.3f}")
        logger.debug(f"ArXiv paper title: '{arxiv_title}'")
        logger.debug(f"Verified paper title: '{verified_title}'")
        
        # If titles are very different (less than 40% similarity), flag as ArXiv ID error
        if title_similarity < 0.4:
            # Try to find the correct ArXiv URL for the actual paper
            correct_arxiv_url = self.find_correct_arxiv_url(verified_data)
            correct_url = correct_arxiv_url if correct_arxiv_url else verified_data.get('url', '')
            
            return [{
                'error_type': 'arxiv_id',
                'error_details': f"ArXiv ID points to different paper: cited ArXiv ID {ref_arxiv_id} points to '{arxiv_title}' but reference is actually '{verified_title}'",
                'ref_url_correct': correct_url
            }]
        
        return []

    def check_arxiv_url_mismatch(self, reference, verified_data):
        """
        Legacy function - now redirects to check_arxiv_id_mismatch
        
        Args:
            reference: The reference with an ArXiv URL
            verified_data: The verified paper data from Semantic Scholar
            
        Returns:
            List of errors if ArXiv URL points to wrong paper, empty list otherwise
        """
        if not verified_data or not reference.get('url'):
            return []
        
        # Extract ArXiv ID from the reference URL
        ref_arxiv_id = self.extract_arxiv_id_from_url(reference['url'])
        if not ref_arxiv_id:
            return []
            
        return self.check_arxiv_id_mismatch(reference, verified_data, ref_arxiv_id)
    
    def find_correct_arxiv_url(self, verified_data):
        """
        Try to find the correct ArXiv URL for a paper based on verified data.
        
        Args:
            verified_data: The verified paper data from Semantic Scholar
            
        Returns:
            ArXiv URL string if found, None otherwise
        """
        if not verified_data:
            return None
        
        # Check if the verified paper has external IDs that include ArXiv
        external_ids = verified_data.get('externalIds', {})
        if external_ids and 'ArXiv' in external_ids:
            arxiv_id = external_ids['ArXiv']
            return f"https://arxiv.org/abs/{arxiv_id}"
        
        # Check if any of the URLs in the paper data point to ArXiv
        paper_url = verified_data.get('url', '')
        if paper_url and 'arxiv.org' in paper_url:
            return paper_url
        
        # Check openAccessPdf for ArXiv links
        open_access_pdf = verified_data.get('openAccessPdf')
        if open_access_pdf and open_access_pdf.get('url'):
            pdf_url = open_access_pdf['url']
            if 'arxiv.org' in pdf_url:
                # Convert PDF URL to abs URL
                if '/pdf/' in pdf_url:
                    return pdf_url.replace('/pdf/', '/abs/').replace('.pdf', '')
                return pdf_url
        
        return None
    
    
    def add_error_to_dataset(self, source_paper, reference, errors, reference_url=None, verified_data=None):
        """
        Add an error entry to the consolidated dataset
        
        Args:
            source_paper: The source paper object
            reference: The reference object
            errors: List of error dictionaries
            reference_url: URL of the verified paper (from verification service)
            verified_data: The verified data from the verification service (for corrected formatting)
        """
        if not errors:
            return
            
        # Consolidate all errors for this reference into a single entry
        if len(errors) > 1:
            # Multiple errors - consolidate them
            error_types = []
            error_details = []
            consolidated_entry = None
            
            for error in errors:
                error_type = error.get('error_type') or error.get('warning_type', 'unknown')
                error_detail = error.get('error_details') or error.get('warning_details', '')
                error_types.append(error_type)
                error_details.append(error_detail)
                
                # Use the first error as the base for consolidated entry
                if consolidated_entry is None:
                    consolidated_entry = {
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
                        
                        # Store original reference for formatting corrections
                        'original_reference': reference
                    }
                
                # Collect correct information from all errors
                if error.get('ref_authors_correct'):
                    consolidated_entry['ref_authors_correct'] = error['ref_authors_correct']
                if error.get('ref_year_correct'):
                    consolidated_entry['ref_year_correct'] = error['ref_year_correct']
                if error.get('ref_title_correct'):
                    consolidated_entry['ref_title_correct'] = error['ref_title_correct']
                if error.get('ref_url_correct'):
                    consolidated_entry['ref_url_correct'] = error['ref_url_correct']
                if error.get('ref_venue_correct'):
                    consolidated_entry['ref_venue_correct'] = error['ref_venue_correct']
            
            # Set consolidated error information
            consolidated_entry['error_type'] = 'multiple'
            consolidated_entry['error_details'] = '\n'.join([f"- {detail}" for detail in error_details])
            
            # Add verified URL if available
            if reference_url:
                consolidated_entry['ref_verified_url'] = reference_url
            
            # Generate corrected reference using all available corrections
            corrected_data = self._extract_corrected_data_from_error(consolidated_entry, verified_data)
            
            # Generate all three formats for user convenience
            from refchecker.utils.text_utils import format_corrected_plaintext, format_corrected_bibtex, format_corrected_bibitem
            plaintext_format = format_corrected_plaintext(reference, corrected_data, consolidated_entry)
            bibtex_format = format_corrected_bibtex(reference, corrected_data, consolidated_entry)
            bibitem_format = format_corrected_bibitem(reference, corrected_data, consolidated_entry)
            
            if plaintext_format:
                consolidated_entry['ref_corrected_plaintext'] = plaintext_format
            if bibtex_format:
                consolidated_entry['ref_corrected_bibtex'] = bibtex_format
            if bibitem_format:
                consolidated_entry['ref_corrected_bibitem'] = bibitem_format
            
            # Store the consolidated entry (write to file at end of run)
            self.errors.append(consolidated_entry)
            
        else:
            # Single error - handle as before
            error = errors[0]
            error_type = error.get('error_type') or error.get('warning_type') or error.get('info_type', 'unknown')
            error_details = error.get('error_details') or error.get('warning_details') or error.get('info_details', '')
            
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
                'error_details': error_details,
                
                # Store original reference for formatting corrections
                'original_reference': reference
            }
            
            # Add correct information based on error type
            if error_type == 'author':
                error_entry['ref_authors_correct'] = error.get('ref_authors_correct', '')
            elif error_type == 'year':
                error_entry['ref_year_correct'] = error.get('ref_year_correct', '')
            elif error_type == 'title':
                error_entry['ref_title_correct'] = error.get('ref_title_correct', '')
            elif error_type == 'url':
                error_entry['ref_url_correct'] = error.get('ref_url_correct', '')
            elif error_type == 'arxiv_id':
                error_entry['ref_url_correct'] = error.get('ref_url_correct', '')
            elif error_type == 'venue':
                error_entry['ref_venue_correct'] = error.get('ref_venue_correct', '')
            
            # Add verified URL if available (from verification service)
            if reference_url:
                error_entry['ref_verified_url'] = reference_url
            
            # Add standard format using the correct information (only for non-unverified errors)
            if error_type != 'unverified':
                error_entry['ref_standard_format'] = self.format_standard_reference(error)
                
                # Generate corrected reference in all formats for user convenience
                corrected_data = self._extract_corrected_data_from_error(error, verified_data)
                
                # Generate all three formats
                from refchecker.utils.text_utils import format_corrected_plaintext, format_corrected_bibtex, format_corrected_bibitem
                plaintext_format = format_corrected_plaintext(reference, corrected_data, error_entry)
                bibtex_format = format_corrected_bibtex(reference, corrected_data, error_entry)
                bibitem_format = format_corrected_bibitem(reference, corrected_data, error_entry)
                
                if plaintext_format:
                    error_entry['ref_corrected_plaintext'] = plaintext_format
                if bibtex_format:
                    error_entry['ref_corrected_bibtex'] = bibtex_format
                if bibitem_format:
                    error_entry['ref_corrected_bibitem'] = bibitem_format
            else:
                error_entry['ref_standard_format'] = None
            
            # Store error in memory (write to file at end of run)
            self.errors.append(error_entry)
                
    def write_all_errors_to_file(self):
        """
        Write all accumulated errors to the output file at the end of the run
        """
        if not self.verification_output_file:
            logger.debug("No output file specified, skipping error file write")
            return
            
        if not self.errors:
            logger.debug("No errors to write to output file")
            return
            
        try:
            with open(self.verification_output_file, 'w', encoding='utf-8', errors='replace') as f:
                f.write("REFERENCE VERIFICATION ERRORS\n")
                
                # Track paper info to avoid duplicates in single paper mode
                paper_info_written = False
                
                for error_entry in self.errors:
                    # For single paper mode, only write paper info once
                    if self.single_paper_mode and self.current_paper_info:
                        # Check if this is the first error for this paper
                        if not paper_info_written:
                            f.write(f"\nPAPER: {self.current_paper_info['title']}\n")
                            f.write(f"ArXiv ID: {self.current_paper_info['id']}\n")
                            f.write(f"URL: {self.current_paper_info['url']}\n")
                            f.write(f"Authors: {self.current_paper_info['authors']}\n")
                            f.write(f"Year: {self.current_paper_info['year']}\n")
                            f.write("-" * 80 + "\n")
                            paper_info_written = True
                    else:
                        # Multi-paper mode - write paper info for each error
                        f.write(f"\nPAPER: {error_entry['source_title']}\n")
                        f.write(f"ArXiv ID: {error_entry['source_paper_id']}\n")
                        f.write(f"URL: {error_entry['source_url']}\n")
                        f.write(f"Authors: {error_entry['source_authors']}\n")
                        f.write(f"Year: {error_entry['source_year']}\n")
                        f.write("-" * 80 + "\n")
                    
                    f.write(f"REFERENCE: {error_entry['ref_title']}\n")
                    
                    # Add emoji based on error type
                    error_type = error_entry['error_type']
                    if error_type == 'unverified':
                        emoji = "❓"
                    elif error_type in ['year', 'venue']:  # Warning types
                        emoji = "⚠️"
                    elif error_type == 'url':  # Info type (ArXiv URL suggestion)
                        emoji = "ℹ️"
                    else:  # Error types (title, author, doi, multiple, etc.)
                        emoji = "❌"
                    
                    f.write(f"Type: {emoji} {error_entry['error_type']}\n")
                    f.write(f"Details: {error_entry['error_details']}\n\n")
                    
                    # Show raw text of the original reference
                    if error_entry.get('ref_raw_text'):
                        f.write("RAW REFERENCE TEXT:\n")
                        f.write(f"{error_entry['ref_raw_text']}\n\n")
                    
                    # Show verified URL if available (even for unverified references)
                    if error_entry.get('ref_verified_url'):
                        f.write("VERIFIED URL:\n")
                        f.write(f"  {error_entry['ref_verified_url']}\n")
                        f.write("\n")
                    
                    # Show corrected reference in all formats if available
                    formats_written = False
                    
                    # Plain text format
                    if error_entry.get('ref_corrected_plaintext'):
                        f.write("CORRECTED REFERENCE (Plain Text):\n")
                        f.write(f"{error_entry['ref_corrected_plaintext']}\n\n")
                        formats_written = True
                    
                    # BibTeX format
                    if error_entry.get('ref_corrected_bibtex'):
                        f.write("CORRECTED REFERENCE (BibTeX):\n")
                        f.write(f"{error_entry['ref_corrected_bibtex']}\n\n")
                        formats_written = True
                    
                    # Bibitem/LaTeX format  
                    if error_entry.get('ref_corrected_bibitem'):
                        f.write("CORRECTED REFERENCE (LaTeX/Biblatex):\n")
                        f.write(f"{error_entry['ref_corrected_bibitem']}\n\n")
                        formats_written = True
                    
                    # Fallback to legacy format if no new formats available
                    if not formats_written and error_entry.get('ref_corrected_format'):
                        f.write("CORRECTED REFERENCE:\n")
                        f.write(f"{error_entry['ref_corrected_format']}\n\n")
                    
                    f.write("=" * 80 + "\n")
                    
        except Exception as e:
            logger.error(f"Failed to write errors to file: {e}")
            # Continue without failing the entire process
    
    def _extract_corrected_data_from_error(self, error, verified_data):
        """
        Extract corrected data from error object and verified data
        
        Args:
            error: Error dictionary containing correction information
            verified_data: Verified data from the verification service
            
        Returns:
            Dictionary with corrected data fields
        """
        corrected_data = {}
        
        # Extract corrected information from error object
        # Always try to get title - either the corrected one or from verified_data
        if error.get('ref_title_correct'):
            corrected_data['title'] = error['ref_title_correct']
        elif verified_data and verified_data.get('title'):
            corrected_data['title'] = verified_data['title']
            
        if error.get('ref_authors_correct'):
            corrected_data['authors'] = error['ref_authors_correct']
        elif verified_data and verified_data.get('authors'):
            # Format authors from verified data
            if isinstance(verified_data['authors'], list):
                if verified_data['authors'] and isinstance(verified_data['authors'][0], dict):
                    # Semantic Scholar format: [{'name': 'Author Name'}, ...]
                    author_names = [author.get('name', '') for author in verified_data['authors']]
                    corrected_data['authors'] = ', '.join(author_names)
                else:
                    # Simple list of names
                    corrected_data['authors'] = ', '.join(verified_data['authors'])
            else:
                corrected_data['authors'] = str(verified_data['authors'])
                
        if error.get('ref_year_correct'):
            corrected_data['year'] = error['ref_year_correct']
        elif verified_data and verified_data.get('year'):
            corrected_data['year'] = verified_data['year']
            
        if error.get('ref_url_correct'):
            corrected_data['url'] = error['ref_url_correct']
        elif verified_data and verified_data.get('url'):
            corrected_data['url'] = verified_data['url']
            
        # Add venue information
        if error.get('ref_venue_correct'):
            corrected_data['venue'] = error['ref_venue_correct']
        elif verified_data:
            if verified_data.get('venue'):
                corrected_data['venue'] = verified_data['venue']
            elif verified_data.get('journal'):
                corrected_data['journal'] = verified_data['journal']
        
        # Add DOI if available from verified data
        if verified_data:
            external_ids = verified_data.get('externalIds', {})
            if external_ids and external_ids.get('DOI'):
                corrected_data['doi'] = external_ids['DOI']
                
        return corrected_data
    
    def run(self, debug_mode=False, specific_paper_id=None, local_pdf_path=None):
        """
        Run the reference checking process
        
        Args:
            debug_mode: If True, use verbose logging; if False, use pretty printing
            specific_paper_id: If provided, only process this specific paper
            local_pdf_path: If provided, process this local PDF or LaTeX file instead of fetching from ArXiv
        """
        # Reconfigure logger for this run
        global logger
        logger = setup_logging(debug_mode=debug_mode)
        
        logger.debug("Starting ArXiv reference checking process")
        
        # Initialize counters for statistics
        self.total_papers_processed = 0
        self.total_references_processed = 0
        self.papers_with_errors = 0
        self.papers_with_warnings = 0
        self.papers_with_info = 0
        self.total_errors_found = 0
        self.total_warnings_found = 0
        self.total_info_found = 0
        self.total_arxiv_refs = 0
        self.total_non_arxiv_refs = 0
        self.total_other_refs = 0
        self.total_unverified_refs = 0
        self.used_regex_extraction = False
        self.used_unreliable_extraction = False  # Only set for fallback regex parsing, not BibTeX
        
        try:
            # Get papers to process
            if specific_paper_id:
                # Process a specific paper
                logger.debug(f"Processing specific paper with ID: {specific_paper_id}")
                paper = self.get_paper_metadata(specific_paper_id)
                if not paper:
                    logger.error(f"Could not find paper with ID: {specific_paper_id}")
                    return None
                papers = [paper]
                # Set single paper mode
                self.single_paper_mode = True
                               
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
                # Determine file type for logging
                file_ext = os.path.splitext(local_pdf_path)[1].lower()
                if file_ext == '.pdf':
                    file_type = "PDF"
                elif file_ext == '.tex':
                    file_type = "LaTeX file"
                elif file_ext == '.bib':
                    file_type = "BibTeX file"
                elif file_ext == '.txt':
                    file_type = "text file"
                else:
                    file_type = "file"
                logger.debug(f"Processing {file_type}: {local_pdf_path}")
                paper = self._create_local_file_paper(local_pdf_path)
                papers = [paper]
                # Set single paper mode
                self.single_paper_mode = True
                                
                # Determine appropriate URL for display
                if local_pdf_path.startswith('http'):
                    display_url = local_pdf_path  # Use original URL for HTTP(S) links
                else:
                    display_url = f"file://{os.path.abspath(local_pdf_path)}"  # Use file:// for local files
                
                self.current_paper_info = {
                    'title': paper.title,
                    'id': paper.get_short_id(),
                    'url': display_url,
                    'authors': ', '.join(paper.authors) if paper.authors else 'Unknown',
                    'year': paper.published.year
                }
                # Reset paper info written flag
                if hasattr(self, '_paper_info_written'):
                    delattr(self, '_paper_info_written')
            
            # Process each paper
            if self.single_paper_mode and len(papers) == 1:
                # No progress bar for single paper
                paper_iterator = papers
            else:
                # Show progress bar for multiple papers
                paper_iterator = tqdm(papers, desc="Processing papers")
                
            for paper in paper_iterator:
                paper_id = paper.get_short_id()
                
                # Set appropriate URL based on paper type
                if hasattr(paper, 'file_path') and not paper_id.startswith('local_') and not paper_id.startswith('url_'):
                    # Regular ArXiv paper
                    paper_url = f"https://arxiv.org/abs/{paper_id}"
                elif hasattr(paper, 'file_path'):
                    # Local file or URL - use the current_paper_info URL if available
                    paper_url = self.current_paper_info.get('url', f"file://{os.path.abspath(paper.file_path)}")
                else:
                    # Fallback to ArXiv URL
                    paper_url = f"https://arxiv.org/abs/{paper_id}"
                
                
                # Log paper info
                logger.debug(f"Processing paper: {getattr(paper, 'title', 'No title')} ({paper_id})")
                
                # Print paper heading in non-debug mode
                # Try to get a meaningful title
                paper_title = getattr(paper, 'title', None)
                clean_arxiv_id = paper_id.replace('url_', '') if paper_id.startswith('url_') else paper_id
                
                # If we have a good title (not just the arXiv ID), use it
                if paper_title and paper_title.strip() and paper_title != paper_id and paper_title != clean_arxiv_id and len(paper_title) > 10:
                    print(f"\n📄 Processing: {paper_title}")
                    print(f"   ArXiv ID: {clean_arxiv_id}")
                else:
                    # Try to fetch the title directly from arXiv API as fallback
                    title_found = False
                    try:
                        import arxiv
                        logger.debug(f"Attempting to fetch title for arXiv ID: {clean_arxiv_id}")
                        client = arxiv.Client()
                        search = arxiv.Search(id_list=[clean_arxiv_id])
                        arxiv_paper = next(client.results(search))
                        if arxiv_paper and arxiv_paper.title and len(arxiv_paper.title.strip()) > 10:
                            print(f"\n📄 Processing: {arxiv_paper.title}")
                            print(f"   ArXiv ID: {clean_arxiv_id}")
                            title_found = True
                    except Exception as e:
                        logger.debug(f"Could not fetch title from arXiv API: {e}")
                    
                    if not title_found:
                        print(f"\n📄 Processing: ArXiv Paper {clean_arxiv_id}")
                
                print(f"   {paper_url}")
                
                try:
                    # Extract bibliography
                    bibliography = self.extract_bibliography(paper, debug_mode)
                    
                    # Apply deduplication to all bibliography sources (not just LLM-extracted)
                    if len(bibliography) > 1:  # Only deduplicate if we have multiple references
                        original_count = len(bibliography)
                        bibliography = self._deduplicate_bibliography_entries(bibliography)
                        if len(bibliography) < original_count:
                            logger.debug(f"Deduplicated {original_count} references to {len(bibliography)} unique references")
                                        
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
                    
                    # Check references (parallel or sequential based on configuration)
                    if self.enable_parallel and len(bibliography) > 1:
                        self._verify_references_parallel(paper, bibliography, paper_errors, error_types, unverified_count, debug_mode)
                    else:
                        self._verify_references_sequential(paper, bibliography, paper_errors, error_types, unverified_count, debug_mode)
                    
                    if not debug_mode:
                        # Separate actual errors from warnings for paper classification
                        actual_errors = [e for e in paper_errors if 'error_type' in e and e['error_type'] != 'unverified']
                        warnings_only = [e for e in paper_errors if 'warning_type' in e]
                        info_only = [e for e in paper_errors if 'info_type' in e]
                        
                        if self.single_paper_mode:
                            # Single paper mode - show simple summary
                            if actual_errors or warnings_only or info_only:
                                summary_parts = []
                                if actual_errors:
                                    summary_parts.append(f"{len(actual_errors)} errors")
                                if warnings_only:
                                    summary_parts.append(f"{len(warnings_only)} warnings")
                                if info_only:
                                    summary_parts.append(f"{len(info_only)} information")
                        else:
                            # Multi-paper mode - track paper statistics
                            if actual_errors or warnings_only or info_only:
                                summary_parts = []
                                if actual_errors:
                                    summary_parts.append(f"{len(actual_errors)} errors")
                                    self.papers_with_errors += 1
                                if warnings_only:
                                    summary_parts.append(f"{len(warnings_only)} warnings")
                                    # Count as paper with warnings if it has warnings (regardless of errors)
                                    self.papers_with_warnings += 1
                                if info_only:
                                    summary_parts.append(f"{len(info_only)} information")
                                    # Count as paper with info if it has info messages (regardless of errors/warnings)
                                    self.papers_with_info += 1

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
        finally:
            # Cleanup database connections if using thread-safe checker
            self._cleanup_resources()
            
            # If fatal error occurred, remove the output file to avoid confusion
            if self.fatal_error and self.verification_output_file:
                try:
                    if os.path.exists(self.verification_output_file):
                        os.remove(self.verification_output_file)
                        logger.debug(f"Removed output file due to fatal error: {self.verification_output_file}")
                except Exception as e:
                    logger.warning(f"Could not remove output file: {e}")
        
        # Print final summary to console (only if no fatal error occurred)
        if not debug_mode and not self.fatal_error:
            if self.single_paper_mode:
                # Single paper mode - show simplified summary
                print(f"\n" + "="*60)
                print(f"📋 SUMMARY")
                print(f"="*60)
                print(f"📚 Total references processed: {self.total_references_processed}")
                if self.total_errors_found > 0:
                    print(f"❌ Total errors: {self.total_errors_found}")
                if self.total_warnings_found > 0:
                    print(f"⚠️  Total warnings: {self.total_warnings_found}")
                if self.total_info_found > 0:
                    print(f"ℹ️  Total information: {self.total_info_found}")
                if self.total_unverified_refs > 0:
                    print(f"❓ References that couldn't be verified: {self.total_unverified_refs}")
                if self.total_errors_found == 0 and self.total_warnings_found == 0 and self.total_info_found == 0 and self.total_unverified_refs == 0:
                    print(f"✅ All references verified successfully!")
                
                # Show warning if unreliable extraction was used and there are many errors
                if self.used_unreliable_extraction and self.total_errors_found > 5:
                    print(f"\n⚠️  Results might be affected by incorrect reference extraction. Consider using LLM extraction, which is more robust.")
                
                if self.verification_output_file:
                    print(f"\n💾 Detailed results saved to: {self.verification_output_file}")
            else:
                # Multi-paper mode - show full summary
                print(f"\n" + "="*60)
                print(f"📋 FINAL SUMMARY")
                print(f"="*60)
                print(f"📄 Total papers processed: {self.total_papers_processed}")
                print(f"📚 Total references processed: {self.total_references_processed}")
                print(f"❌ Papers with errors:   {self.papers_with_errors}")
                print(f"         Total errors:   {self.total_errors_found}")
                print(f"⚠️  Papers with warnings: {self.papers_with_warnings}")
                print(f"         Total warnings: {self.total_warnings_found}")
                print(f"ℹ️  Papers with information: {self.papers_with_info}")
                print(f"         Total information: {self.total_info_found}")
                print(f"❓ References that couldn't be verified: {self.total_unverified_refs}")
                
                # Show warning if unreliable extraction was used and there are many errors
                if self.used_unreliable_extraction and self.total_errors_found > 5:
                    print(f"\n⚠️  Results might be affected by incorrect reference extraction. Consider using LLM extraction, which is more robust.")
                
                if self.verification_output_file:
                    print(f"\n💾 Detailed results saved to: {self.verification_output_file}")
        
        # Write all accumulated errors to file at the end of the run
        self.write_all_errors_to_file()
        
        # Log performance statistics at the end (debug mode only)
        if self.debug_mode:
            logger.info("Processing complete. API Performance Summary:")
            self.log_hybrid_checker_performance_stats()
        
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
                from refchecker.utils.text_utils import parse_authors_with_initials
                author_list = parse_authors_with_initials(authors)
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
            title = clean_title(title)
            
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
                    title_text = clean_title(title_text)                    
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
                title_text = clean_title(title_text)
                return authors, title_text
        
        # If we get here, try a simple split by the first period
        parts = cleaned_ref.split('.', 1)
        
        if len(parts) > 1:
            authors_text = parts[0].strip()
            title = parts[1].strip()
            
            # Extract authors
            authors = self.extract_authors_list(authors_text)
            
            # Clean the title
            title = clean_title(title)            
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
            title = clean_title(title)
            return authors, title
        
        # If all else fails, return placeholder values
        return ["Unknown Author"], "Untitled Reference"
    
    def _is_likely_reference(self, text):
        """
        Check if a numbered item is likely a bibliographic reference
        and not section headers, figure captions, etc.
        
        Args:
            text: The text to check (including the [N] number)
            
        Returns:
            bool: True if it looks like a reference, False otherwise
        """
        # Remove the reference number for analysis
        content = re.sub(r'^\[\d+\]\s*', '', text).strip()
        
        # If too short, probably not a reference
        if len(content) < 20:
            return False
            
        # Check for clear non-reference patterns
        non_reference_patterns = [
            r'^[A-Z\s]+$',  # All caps (section headers like "PROMPT FOR MEDGPT")
            r'^[A-Z][a-z]*\s+[a-z][a-z\s]*$',  # Title case section headers
            r'^(Computation|Prompt|Example|Figure|Table|Algorithm)\s+',  # Common section prefixes
            r'^[A-Za-z\s]+:$',  # Section headers ending with colon
            r'^\d+\.\d+\s+[A-Z]',  # Subsection numbers like "3.1 Title"
        ]
        
        for pattern in non_reference_patterns:
            if re.match(pattern, content):
                return False
        
        # Check for positive reference indicators
        reference_indicators = [
            r'\b(19|20)\d{2}\b',  # Years
            r'\bet\s+al\.?\b',    # "et al."
            r'\bvol\.?\s*\d+\b',  # Volume numbers
            r'\bpp\.?\s*\d+',     # Page numbers
            r'\bdoi[:.]',         # DOI
            r'https?://',         # URLs
            r'\barXiv\b',         # arXiv preprints
            r'\bProc\.?\s+of\b',  # "Proceedings of"
            r'\bJ\.\s+[A-Z]',     # Journal abbreviations like "J. Med"
            r'[A-Z][a-z]+,\s*[A-Z]',  # Author names like "Smith, J"
        ]
        
        # Count positive indicators
        indicator_count = sum(1 for pattern in reference_indicators if re.search(pattern, content))
        
        # If it has multiple reference indicators, likely a reference
        if indicator_count >= 2:
            return True
        
        # If it has at least one indicator and reasonable length, probably a reference
        if indicator_count >= 1 and len(content) > 50:
            return True
            
        # If no clear indicators but contains author-like patterns and reasonable length
        author_patterns = [
            r'[A-Z][a-z]+,\s*[A-Z]',  # "Smith, J"
            r'[A-Z]\.\s*[A-Z][a-z]+',  # "J. Smith"
        ]
        
        has_author_pattern = any(re.search(pattern, content) for pattern in author_patterns)
        if has_author_pattern and len(content) > 30:
            return True
            
        # Default to False for safety
        return False

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

        # Check if this is a standard ACM/natbib format first
        if detect_standard_acm_natbib_format(bibliography_text):
            logger.info("Detected standard ACM/natbib format, using regex-based parsing")
            self.used_regex_extraction = True
            # Note: ACM/natbib parsing is also quite robust for standard formats
            return self._parse_standard_acm_natbib_references(bibliography_text)
        
        # Check if this is BibTeX format
        from refchecker.utils.bibtex_parser import detect_bibtex_format
        if detect_bibtex_format(bibliography_text):
            logger.info("Detected BibTeX format, using BibTeX parser")
            self.used_regex_extraction = True
            # Note: BibTeX parsing is robust, so we don't set used_unreliable_extraction
            return self._parse_bibtex_references(bibliography_text)
        
        # Check if this is biblatex format  
        from refchecker.utils.biblatex_parser import detect_biblatex_format
        if detect_biblatex_format(bibliography_text):
            logger.debug("Detected biblatex format")
            self.used_regex_extraction = True
            # Note: biblatex parsing is also robust, so we don't set used_unreliable_extraction
            biblatex_refs = self._parse_biblatex_references(bibliography_text)
            
            # If biblatex parsing returned empty results (due to quality validation),
            # fallback to LLM if available
            if not biblatex_refs and self.llm_extractor:
                logger.debug("Biblatex is incompatible with parser")
                try:
                    references = self.llm_extractor.extract_references(bibliography_text)
                    if references:
                        logger.debug(f"LLM fallback extracted {len(references)} references")
                        return self._process_llm_extracted_references(references)
                    else:
                        logger.warning("LLM fallback also returned no results")
                        return []
                except Exception as e:
                    logger.error(f"LLM fallback failed: {e}")
                    return []
            if len(biblatex_refs) > 0:
                logger.debug("Using biblatex file")
                return biblatex_refs
        
        # For non-standard formats, try LLM-based extraction if available
        if self.llm_extractor:
            try:
                logger.info("Non-standard bibliography format detected, using LLM-based extraction")
                references = self.llm_extractor.extract_references(bibliography_text)
                if references:
                    logger.debug(f"Parsed {len(references)} references")
                    return self._process_llm_extracted_references(references)
                else:
                    # LLM was specified but failed - this is terminal
                    logger.error("LLM reference extraction returned no results. Terminating.")
                    self.fatal_error = True
                    return []
            except Exception as e:
                logger.error(f"LLM reference extraction failed: {e}")
                self.fatal_error = True
                return []
        
        # Fallback to regex-based parsing only if LLM was not specified
        logger.info("No LLM available, falling back to regex-based parsing")
        self.used_regex_extraction = True
        self.used_unreliable_extraction = True  # This is the unreliable fallback parsing
        return self._parse_references_regex(bibliography_text)
    
    def _parse_standard_acm_natbib_references(self, bibliography_text):
        """
        Parse references using regex for standard ACM/natbib format (both ACM Reference Format and simple natbib)
        """
        references = []
        
        # Detect which format we're dealing with
        is_acm_format = re.search(r'\\bibfield\{author\}\{.*?\\bibinfo\{person\}', bibliography_text)
        
        # Pattern to extract \bibitem entries with the complete content
        bibitem_pattern = r'\\bibitem\[([^\]]*)\]\s*%?\s*\n?\s*\{([^}]+)\}\s*(.*?)(?=\\bibitem|\\end\{thebibliography\}|$)'
        
        matches = re.finditer(bibitem_pattern, bibliography_text, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            label = match.group(1)
            key = match.group(2)
            content = match.group(3).strip()
            
            ref = {
                'raw_text': f"\\bibitem[{label}]{{{key}}}\n{content}",
                'title': '',
                'authors': [],
                'year': None,
                'journal': '',
                'venue': '',
                'url': '',
                'doi': '',
                'arxiv_id': '',
                'bibitem_key': key,
                'bibitem_label': label
            }
            
            if is_acm_format:
                # Parse ACM Reference Format
                self._parse_acm_reference_format(ref, content)
            else:
                # Parse simple natbib format
                self._parse_simple_natbib_format(ref, content, label)
            
            # Only add if we have essential information
            if ref['title'] or ref['authors']:
                references.append(ref)
        
        format_name = "ACM Reference Format" if is_acm_format else "simple natbib format"
        logger.debug(f"Parsed {len(references)} references using {format_name}")
        return references
    
    def _parse_acm_reference_format(self, ref, content):
        """Parse ACM Reference Format with \bibfield and \bibinfo commands"""
        # Extract year from \bibinfo{year}{YYYY}
        year_match = re.search(r'\\bibinfo\{year\}\{(\d{4})\}', content)
        if year_match:
            ref['year'] = int(year_match.group(1))
        
        # Extract authors from \bibfield{author}{\bibinfo{person}{Name1}, \bibinfo{person}{Name2}, ...}
        author_field_match = re.search(r'\\bibfield\{author\}\{(.*?)\}(?:\s*\\bibinfo\{year\}|\s*\\newblock|$)', content, re.DOTALL)
        if author_field_match:
            author_content = author_field_match.group(1)
            # Find all \bibinfo{person}{Name} entries using balanced brace extraction
            from refchecker.utils.text_utils import extract_bibinfo_person_content
            person_matches = extract_bibinfo_person_content(author_content)
            if person_matches:
                authors = []
                for person in person_matches:
                    # Clean the author name and remove any remaining LaTeX commands
                    clean_name = strip_latex_commands(person).strip()
                    # Remove leading "and" that might be left over
                    clean_name = re.sub(r'^and\s+', '', clean_name)
                    if clean_name and clean_name not in ['and', '{and}']:
                        authors.append(clean_name)
                ref['authors'] = authors
        
        # Import balanced brace extraction function
        from refchecker.utils.text_utils import extract_bibinfo_field_content
        
        # Extract title from \bibinfo{title}{Title} using balanced brace extraction
        title_content = extract_bibinfo_field_content(content, 'title')
        if title_content:
            title = strip_latex_commands(title_content).strip()
            ref['title'] = title
        
        # Extract venue/journal from various fields using balanced brace extraction
        venue_field_types = ['booktitle', 'journal', 'series', 'note']
        
        for field_type in venue_field_types:
            venue_content = extract_bibinfo_field_content(content, field_type)
            if venue_content:
                venue = strip_latex_commands(venue_content).strip()
                if venue:
                    ref['venue'] = venue
                    ref['journal'] = venue  # For compatibility
                    break
        
        # Extract DOI using balanced brace extraction
        doi_content = extract_bibinfo_field_content(content, 'doi')
        if doi_content:
            ref['doi'] = doi_content.strip()
        
        # Extract ArXiv ID from \showeprint[arxiv]{ID}
        arxiv_match = re.search(r'\\showeprint\[arxiv\]\{([^}]+)\}', content)
        if arxiv_match:
            ref['arxiv_id'] = arxiv_match.group(1).strip()
        
        # Extract URL
        url_match = re.search(r'\\bibinfo\{url\}\{([^}]+)\}', content)
        if url_match:
            ref['url'] = url_match.group(1).strip()
    
    def _parse_simple_natbib_format(self, ref, content, label):
        """Parse simple natbib format with plain text content"""
        # Extract year from label like "Author(2023)" or from content
        year_match = re.search(r'\((\d{4})\)', label)
        if year_match:
            ref['year'] = int(year_match.group(1))
        else:
            # Try to find year in content
            year_match = re.search(r'\b(19|20)\d{2}\b', content)
            if year_match:
                ref['year'] = int(year_match.group())
        
        # Split content by \newblock to get different parts
        parts = re.split(r'\\newblock\s*', content)
        
        if len(parts) >= 1:
            # First part (before first \newblock) is usually authors
            author_part = parts[0].strip()
            if author_part:
                # Clean author part and extract authors
                author_part_clean = strip_latex_commands(author_part).strip()
                if author_part_clean and not author_part_clean.startswith('\\'):
                    # Parse author names using the robust author parsing function
                    from refchecker.utils.text_utils import parse_authors_with_initials
                    author_names = parse_authors_with_initials(author_part_clean)
                    
                    # Clean up author names
                    authors = []
                    for name in author_names:
                        name = name.strip()
                        # Remove leading "and" from author names
                        name = re.sub(r'^and\s+', '', name)
                        if name and len(name) > 2 and name not in ['et~al', 'et al', 'et~al.']:
                            # Remove trailing dots
                            name = name.rstrip('.')
                            authors.append(name)
                    if authors:
                        ref['authors'] = authors
        
        if len(parts) >= 2:
            # Second part is usually title
            title_part = parts[1].strip()
            if title_part:
                title_clean = strip_latex_commands(title_part).strip()
                # Remove trailing periods and clean up
                title_clean = title_clean.rstrip('.,')
                if title_clean:
                    ref['title'] = title_clean
        
        if len(parts) >= 3:
            # Third part is usually venue/journal
            venue_part = parts[2].strip()
            if venue_part:
                venue_clean = strip_latex_commands(venue_part).strip()
                # Remove trailing periods and clean up
                venue_clean = venue_clean.rstrip('.,')
                if venue_clean:
                    ref['venue'] = venue_clean
                    ref['journal'] = venue_clean  # For compatibility
        
        # Extract DOI from \doi{...} commands
        doi_match = re.search(r'\\doi\{([^}]+)\}', content)
        if doi_match:
            ref['doi'] = doi_match.group(1).strip()
        
        # Extract URL from \url{...} commands
        url_match = re.search(r'\\url\{([^}]+)\}', content)
        if url_match:
            ref['url'] = url_match.group(1).strip()

    def _parse_references_regex(self, bibliography_text):
        """
        Parse references using regex-based approach (original implementation)
        """
        self.used_regex_extraction = True
        
        # Check if this is BibTeX format first
        from refchecker.utils.bibtex_parser import detect_bibtex_format
        if detect_bibtex_format(bibliography_text):
            logger.debug("Detected BibTeX format, using BibTeX-specific parsing")
            # BibTeX parsing is robust, so we don't set used_unreliable_extraction
            return self._parse_bibtex_references(bibliography_text)
        
        # Check if this is biblatex format
        from refchecker.utils.biblatex_parser import detect_biblatex_format  
        if detect_biblatex_format(bibliography_text):
            logger.debug("Detected biblatex format, using biblatex-specific parsing")
            # biblatex parsing is also robust, so we don't set used_unreliable_extraction
            biblatex_refs = self._parse_biblatex_references(bibliography_text)
            
            # If biblatex parsing returned empty results (due to quality validation),
            # we'll continue with the unreliable fallback regex parsing
            if not biblatex_refs:
                logger.debug("Biblatex parser returned no results due to quality validation, falling back to regex parsing")
                print(f"⚠️  Biblatex parser found no valid references (failed quality validation) - falling back to regex parsing")
            else:
                return biblatex_refs
        
        # If we reach here, we're using the unreliable fallback regex parsing
        self.used_unreliable_extraction = True
        
        # --- IMPROVED SPLITTING: handle concatenated references like [3]... [4]... ---
        # First, normalize the bibliography text to handle multi-line references
        # This fixes the issue where years appear as separate lines
        normalized_bib = re.sub(r'\s+', ' ', bibliography_text).strip()
        
        # Ensure proper spacing after reference numbers - more comprehensive fix
        normalized_bib = re.sub(r'(\[\d+\])([A-Za-z])', r'\1 \2', normalized_bib)
        # Also handle cases where numbers directly follow reference numbers
        normalized_bib = re.sub(r'(\[\d+\])(\d)', r'\1 \2', normalized_bib)
        
        
        # Handle the case where the last reference might be incomplete
        # Check if the text ends with a reference number followed by content
        if re.search(r'\[\d+\][^[]*$', normalized_bib):
            # The last reference is incomplete, try to find a better ending
            # Look for the last complete sentence or period, but avoid truncating file extensions
            last_period = normalized_bib.rfind('.')
            if last_period > 0:
                # Check if this period is part of a file extension
                text_after_period = normalized_bib[last_period+1:last_period+5]  # Check next 4 chars
                if not re.match(r'^[a-zA-Z]{2,4}$', text_after_period):
                    # Find the last reference number before this period
                    last_ref_match = re.search(r'\[\d+\][^[]*?\.', normalized_bib[:last_period+1])
                    if last_ref_match:
                        # Truncate at the last complete reference
                        normalized_bib = normalized_bib[:last_period+1]
        
        numbered_ref_pattern = r'(\[\d+\])'
        numbered_refs = re.split(numbered_ref_pattern, normalized_bib)
        references = []
        
        # Only process as numbered references if we actually have numbered patterns in the text
        has_numbered_refs = bool(re.search(r'\[\d+\]', normalized_bib))
        
        if len(numbered_refs) > 1 and has_numbered_refs:
            # Reconstruct references, as split removes the delimiter
            temp = []
            for part in numbered_refs:
                if re.match(r'^\[\d+\]$', part):
                    if temp:
                        joined_ref = ''.join(temp).strip()
                        references.append(joined_ref)
                        temp = []
                    temp.append(part)
                else:
                    temp.append(part)
            if temp:
                joined_ref = ''.join(temp).strip()
                references.append(joined_ref)
            # Remove empty or very short entries, but be less aggressive to preserve order
            references = [r for r in references if len(r.strip()) > 10 and not re.match(r'^\[\d+\]$', r.strip())]
            # Ensure the last chunk is included if not already
            if numbered_refs[-1].strip() and not any(numbered_refs[-1].strip() in r for r in references):
                references.append(numbered_refs[-1].strip())
            # Additional defense: filter out numbered items that are clearly not references
            validated_references = []
            for ref in references:
                if self._is_likely_reference(ref):
                    validated_references.append(ref)
                else:
                    logger.debug(f"Filtered out non-reference item: {ref[:100]}...")
            
            logger.debug(f"Before validation: {len(references)} references")
            logger.debug(f"After validation: {len(validated_references)} references")
            references = validated_references
            logger.debug(f"Found {len(references)} numbered references")
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
            
            # If no splitting strategy worked, try author-year format detection
            if not references:
                logger.debug("Attempting author-year format detection...")
                
                # For author-year format, use original bibliography_text (with newlines intact)
                # Enhanced pattern to detect author-year format
                # Look for year endings followed by new reference starts
                # Pattern: year (like 2024.) followed by newline and capital letter start
                year_boundary_pattern = r'(?<=\d{4}\.)\n(?=[A-Z])'
                split_refs = re.split(year_boundary_pattern, bibliography_text.strip())
                logger.debug(f"Year boundary pattern split resulted in {len(split_refs)} parts")
                
                if len(split_refs) > 1:
                    references = [ref.strip() for ref in split_refs if ref.strip() and len(ref.strip()) > 20]
                    logger.debug(f"Found {len(references)} potential references with year boundary pattern")
                else:
                    # Fallback: simpler pattern - split on newlines followed by any capital letter
                    simple_pattern = r'\n(?=[A-Z])'
                    split_refs = re.split(simple_pattern, bibliography_text.strip())
                    logger.debug(f"Simple pattern split resulted in {len(split_refs)} parts")
                    
                    if len(split_refs) > 1:
                        references = [ref.strip() for ref in split_refs if ref.strip() and len(ref.strip()) > 20]
                        logger.debug(f"Found {len(references)} potential references with simple pattern")
        if not references:
            references = [line.strip() for line in normalized_bib.split('\n') if line.strip()]
            logger.debug(f"Using line-by-line splitting, found {len(references)} potential references")
        references = [ref.strip() for ref in references if ref.strip()]

        # --- POST-PROCESSING: fix malformed DOIs/URLs and edge cases ---
        def clean_url(url):
            if not url:
                return url
            url = url.strip()
            # Remove trailing punctuation, but preserve file extensions
            # Only remove trailing punctuation if it's not part of a file extension
            if not re.search(r'\.[a-zA-Z]{2,4}$', url):
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
            # Strip URL fragments (everything after #) from DOI
            doi = doi.split('#')[0]
            # Clean DOI: remove asterisk contamination (e.g., "10.1088/123*http://..." -> "10.1088/123")
            if '*' in doi:
                doi = doi.split('*')[0]
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
            r'CoRR\s*,?\s*abs[:/](\d+\.\d+(?:v\d+)?)',  # Fixed to handle "CoRR , abs/1409.0473" format
        ]
        doi_patterns = [
            r'doi\.org/([^\s,\)]+)',
            r'doi:([^\s,\)]+)',
            r'DOI:([^\s,\)]+)',
        ]
        url_patterns = [
            r'https?://(?!arxiv\.org)[^\s,\)]+',
        ]
        for i, ref in enumerate(references):
            logger.debug(f"Processing reference {i+1}: {ref[:100]}...")
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
                title = clean_title(title) if title else ""
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
                logger.debug(f"Extracted arXiv reference {i+1}: {structured_ref['title']}")
                arxiv_refs.append(structured_ref)
            else:
                doi = None
                url = None
                for pattern in doi_patterns:
                    doi_match = re.search(pattern, ref, re.IGNORECASE)
                    if doi_match:
                        doi = clean_doi(doi_match.group(1))
                        if doi:
                            from refchecker.utils.doi_utils import construct_doi_url
                            url = construct_doi_url(doi)
                        else:
                            url = ''
                        break
                if not url:
                    for pattern in url_patterns:
                        url_match = re.search(pattern, ref)
                        if url_match:
                            raw_url = url_match.group(0)
                            url = clean_url(raw_url)
                            break
                    
                    # Handle multi-line URLs specifically
                    if not url and re.search(r'https?://', ref):
                        # Try to reconstruct multi-line URLs
                        url_start_match = re.search(r'https?://[^\s\n]*', ref)
                        if url_start_match:
                            url_start = url_start_match.group(0)
                            # Look for continuation on the next line(s)
                            remaining_ref = ref[url_start_match.end():].strip()
                            # Remove leading whitespace and reference numbers
                            remaining_ref = re.sub(r'^\s*\[\d+\]?\s*', '', remaining_ref)
                            
                            # Check if the remaining part looks like a URL continuation
                            # (alphanumeric characters, hyphens, slashes, etc.)
                            if re.match(r'^[a-zA-Z0-9\-_/.=?&%\n\s]+\s*\.?\s*$', remaining_ref):
                                # Combine the URL parts, removing newlines and spaces
                                # Don't strip dots from URLs as they might be file extensions
                                url_continuation = re.sub(r'\s+', '', remaining_ref.strip())
                                # Only remove trailing dot if it's not part of a file extension
                                if url_continuation.endswith('.') and not re.search(r'\.[a-zA-Z]{2,4}\.?$', url_continuation):
                                    url_continuation = url_continuation.rstrip('.')
                                url = url_start + url_continuation
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
                    title = clean_title(title) if title else ""
                    is_url_reference = False
                    for author in authors:
                        if isinstance(author, dict) and author.get('is_url_reference', False):
                            is_url_reference = True
                            break
                    if is_url_reference:
                        authors = ["URL Reference"]
                        # For URL references, use the cleaned URL as title if title looks like URL fragment
                        if title and (len(title) < 10 or re.match(r'^[a-zA-Z0-9\-_/.=?&%\s]+$', title)):
                            title = clean_url(url) if url else title
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
                    title = clean_title(title) if title else ""
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
                        # For URL references in other category, keep original title since no URL available
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
                    logger.debug(f"Extracted other reference {i+1}: {structured_ref['title']}")
                    other_refs.append(structured_ref)
        logger.debug(f"Extracted {len(arxiv_refs)} structured references with arxiv links")
        logger.debug(f"Extracted {len(non_arxiv_refs)} structured references without arxiv links")
        logger.debug(f"Extracted {len(other_refs)} structured references without URLs or DOIs")
        all_refs = arxiv_refs + non_arxiv_refs + other_refs
        return all_refs
    
    def _parse_bibtex_references(self, bibliography_text):
        """
        Parse BibTeX formatted references like @inproceedings{...}, @article{...}, etc.
        
        Args:
            bibliography_text: String containing BibTeX entries
            
        Returns:
            List of structured reference dictionaries
        """
        # Use the dedicated BibTeX parser
        from refchecker.utils.bibtex_parser import parse_bibtex_references
        
        # Extract references using the BibTeX parser
        references = parse_bibtex_references(bibliography_text)
        
        logger.debug(f"Extracted {len(references)} BibTeX references using dedicated parser")
        return references
    
    def _parse_biblatex_references(self, bibliography_text):
        """
        Parse biblatex formatted references like [1] Author. "Title". In: Venue. Year.
        
        Args:
            bibliography_text: String containing biblatex .bbl entries
            
        Returns:
            List of structured reference dictionaries
        """
        # Use the dedicated biblatex parser
        from refchecker.utils.biblatex_parser import parse_biblatex_references
        
        # Extract references using the biblatex parser
        references = parse_biblatex_references(bibliography_text)
        
        logger.debug(f"Extracted {len(references)} biblatex references using dedicated parser")
        return references
    
    def _process_llm_extracted_references(self, references):
        """
        Process references extracted by LLM with simplified formatting assumptions
        """
        # Remove duplicates from LLM-extracted references using enhanced segment-based matching
        unique_references = self._deduplicate_references_with_segment_matching(references)
        
        logger.debug(f"Deduplicated {len(references)} references to {len(unique_references)} unique references")
        
        processed_refs = []
        
        for ref in unique_references:
            # Handle case where ref might be a dict or other object
            if isinstance(ref, dict):
                # Convert dict to string representation or extract relevant field
                ref_text = str(ref)
            elif isinstance(ref, str):
                ref_text = ref
            else:
                # Skip non-string, non-dict objects
                continue
                
            if not ref_text or len(ref_text.strip()) < 10:
                continue
                
            # Use LLM-specific structured reference creation
            structured_ref = self._create_structured_llm_references(ref_text)
            if structured_ref:
                processed_refs.append(structured_ref)
        
        return processed_refs
    
    def _deduplicate_references_with_segment_matching(self, references):
        """
        Enhanced deduplication using segment-based matching to handle chunk boundary issues.
        
        Treats references as duplicates if:
        1. Title segments match exactly (case-insensitive)
        2. Either author segments match exactly OR one author segment is a substring of the other
           (handles cases where chunking cuts through author lists)
        """
        unique_references = []
        seen_segments = []
        
        for ref in references:
            # Convert to string for comparison
            ref_str = str(ref) if not isinstance(ref, str) else ref
            
            # Skip very short references
            if not ref_str or len(ref_str.strip()) < 10:
                continue
                
            # Parse segments from reference (format: authors # title # venue # year)
            segments = self._parse_reference_segments(ref_str)
            
            # Check if this reference is a duplicate of any previously seen reference
            is_duplicate = False
            for seen_ref, seen_segments_data in seen_segments:
                if self._are_references_duplicates(segments, seen_segments_data):
                    logger.debug(f"Duplicate detected: '{ref_str[:80]}...' matches '{seen_ref[:80]}...'")
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_references.append(ref)
                seen_segments.append((ref_str, segments))
        
        return unique_references
    
    def _parse_reference_segments(self, ref_str):
        """Parse reference into segments, normalizing for comparison"""
        # Strip trailing # and normalize
        clean_ref = ref_str.strip().rstrip('#').strip()
        
        # Split by # to get segments
        segments = [seg.strip().lower() for seg in clean_ref.split('#') if seg.strip()]
        
        return {
            'author': segments[0] if len(segments) > 0 else '',
            'title': segments[1] if len(segments) > 1 else '',
            'venue': segments[2] if len(segments) > 2 else '',
            'year': segments[3] if len(segments) > 3 else '',
            'raw_segments': segments
        }
    
    def _are_references_duplicates(self, seg1, seg2):
        """
        Check if two reference segments represent the same reference.
        
        Enhanced logic:
        - If titles match exactly, they are considered duplicates (primary criterion)
        - Special handling for author chunk boundary issues by checking substring/overlap
        """
        # Title must match exactly (case-insensitive) - primary criterion
        if not seg1['title'] or not seg2['title']:
            # If either has no title, can't reliably determine if duplicate
            return False
            
        # If titles match exactly (case-insensitive), consider them duplicates
        # This handles the case where the same paper appears multiple times with different capitalization
        if seg1['title'].lower() == seg2['title'].lower():
            return True
            
        # Special case: Check if one title is an arXiv identifier and the other is a real title
        # from the same paper (handles LLM extraction inconsistencies)
        if self._is_arxiv_identifier_title_mismatch(seg1, seg2):
            return True
        
        # Alternative: Check if we have exact author match with different titles
        # (This is less common but handles cases where title extraction varies)
        author1 = seg1['author']
        author2 = seg2['author']
        
        if author1 and author2 and author1.lower() == author2.lower():
            # Same authors - check if one title is substring of other or significant similarity
            title1 = seg1['title'].lower()
            title2 = seg2['title'].lower()
            
            if (title1 in title2 or title2 in title1):
                return True
        
        return False
    
    def _deduplicate_bibliography_entries(self, bibliography):
        """
        Deduplicate bibliography entries using title and author comparison.
        
        This works with structured reference dictionaries from BibTeX/LaTeX parsing,
        as opposed to _deduplicate_references_with_segment_matching which works with raw text.
        
        Args:
            bibliography: List of reference dictionaries with 'title', 'authors', etc.
            
        Returns:
            List of unique reference dictionaries
        """
        if len(bibliography) <= 1:
            return bibliography
            
        unique_refs = []
        seen_titles = set()
        
        for ref in bibliography:
            title = ref.get('title', '').strip()
            if not title:
                # Keep references without titles (they can't be deduplicated)
                unique_refs.append(ref)
                continue
                
            # Normalize title for comparison (case-insensitive, basic cleanup)
            normalized_title = title.lower().strip()
            
            # Check if we've seen this title before (case-insensitive)
            if normalized_title in seen_titles:
                logger.debug(f"Skipping duplicate reference: '{title}'")
            else:
                unique_refs.append(ref)
                seen_titles.add(normalized_title)
                
        return unique_refs
    
    def _is_arxiv_identifier_title_mismatch(self, seg1, seg2):
        """
        Check if one reference has an arXiv identifier as title while the other has a real title,
        but they're actually the same paper (detected by similar authors and venues).
        """
        import re
        
        # Check if either title looks like an arXiv identifier
        arxiv_pattern = r'arxiv\s*preprint\s*arxiv:\d{4}\.\d{4,5}'
        
        title1_is_arxiv = bool(re.search(arxiv_pattern, seg1['title'], re.IGNORECASE))
        title2_is_arxiv = bool(re.search(arxiv_pattern, seg2['title'], re.IGNORECASE))
        
        # We need exactly one to be arXiv identifier and one to be real title
        if title1_is_arxiv == title2_is_arxiv:
            return False
            
        # Check if venues are similar (both should mention the same arXiv ID)
        venue1 = seg1.get('venue', '').lower()
        venue2 = seg2.get('venue', '').lower()
        
        # Extract arXiv ID from venues
        arxiv_id_pattern = r'arxiv:\d{4}\.\d{4,5}'
        arxiv_ids_1 = re.findall(arxiv_id_pattern, venue1, re.IGNORECASE)
        arxiv_ids_2 = re.findall(arxiv_id_pattern, venue2, re.IGNORECASE)
        
        # If both venues mention the same arXiv ID, likely the same paper
        if arxiv_ids_1 and arxiv_ids_2 and arxiv_ids_1[0] == arxiv_ids_2[0]:
            return True
            
        # Also check if authors have significant overlap (at least 50% of the shorter author list)
        from refchecker.utils.text_utils import parse_authors_with_initials
        
        if '*' in seg1['author']:
            author1_parts = seg1['author'].split('*')
        else:
            author1_parts = parse_authors_with_initials(seg1['author'])
            
        if '*' in seg2['author']:
            author2_parts = seg2['author'].split('*')
        else:
            author2_parts = parse_authors_with_initials(seg2['author'])
        
        # Clean and normalize author names
        author1_clean = {a.strip().lower() for a in author1_parts if a.strip() and a.strip() not in ['et al', 'others']}
        author2_clean = {a.strip().lower() for a in author2_parts if a.strip() and a.strip() not in ['et al', 'others']}
        
        if not author1_clean or not author2_clean:
            return False
            
        # Calculate overlap
        overlap = len(author1_clean.intersection(author2_clean))
        min_authors = min(len(author1_clean), len(author2_clean))
        
        # If significant author overlap (>= 50%) and one title is arXiv identifier, consider duplicate
        if min_authors > 0 and overlap / min_authors >= 0.5:
            return True
            
        return False

    def _check_author_overlap(self, author1, author2):
        """
        Check if two author strings have significant overlap, indicating they're 
        likely the same author list with one being truncated due to chunking.
        """
        # Split into individual author names
        authors1 = [name.strip().lower() for name in author1.replace(',', ' ').split() if name.strip()]
        authors2 = [name.strip().lower() for name in author2.replace(',', ' ').split() if name.strip()]
        
        # If either list is too short, require exact match
        if len(authors1) < 3 or len(authors2) < 3:
            return False
        
        # Calculate overlap
        set1 = set(authors1)
        set2 = set(authors2)
        
        overlap = len(set1.intersection(set2))
        min_length = min(len(set1), len(set2))
        
        # Require at least 50% overlap and at least 2 matching names
        overlap_ratio = overlap / min_length if min_length > 0 else 0
        
        return overlap >= 2 and overlap_ratio >= 0.5
    
    def _clean_llm_author_text(self, author_text):
        """
        Clean author text and parse authors properly
        """
        if not author_text:
            return []
        
        # Check if the author_text uses asterisk delimiter (new format)
        if '*' in author_text:
            # Split on asterisks to get individual author entries
            raw_authors = [author.strip() for author in author_text.split('*') if author.strip()]
            
            parsed_authors = []
            for author in raw_authors:
                # Clean up the author entry and strip LaTeX commands
                from refchecker.utils.text_utils import strip_latex_commands
                author_cleaned = strip_latex_commands(author.rstrip('.'))
                
                # Skip special indicators like "others", "et al", etc.
                if author_cleaned.lower() in ['others', 'et al', 'et al.', 'and others', 'etc.', '...']:
                    # Add "et al" as a standard indicator and stop processing more authors
                    if parsed_authors:  # Only add if we have at least one real author
                        parsed_authors.append("et al")
                    break
                
                # Parse single author entry - could be BibTeX "Surname, Given" or regular "Given Surname"
                parsed_author = self._parse_single_author_entry(author_cleaned)
                if parsed_author:
                    parsed_authors.append(parsed_author)
            
            return parsed_authors
        else:
            # Fallback to original logic for backward compatibility
            from refchecker.utils.text_utils import parse_authors_with_initials
            
            cleaned_text = author_text.rstrip('.')
            authors = parse_authors_with_initials(cleaned_text)
            authors = [a.rstrip('.').strip() for a in authors if a.strip()]
            
            # Handle "others" and similar indicators in fallback logic too
            from refchecker.utils.text_utils import strip_latex_commands
            processed_authors = []
            for author in authors:
                # Apply LaTeX cleaning to each author
                author_clean = strip_latex_commands(author)
                if author_clean.lower() in ['others', 'et al', 'et al.', 'and others', 'etc.', '...']:
                    if processed_authors:  # Only add if we have at least one real author
                        processed_authors.append("et al")
                    break
                processed_authors.append(author_clean)
            
            return processed_authors

    def _parse_single_author_entry(self, author_text):
        """
        Parse a single author entry that may be in various formats:
        - BibTeX format: "Surname, Given" -> "Given Surname"  
        - Regular format: "Given Surname" -> "Given Surname"
        - Handle edge cases like all-caps surnames, compound names, etc.
        """
        if not author_text or not author_text.strip():
            return None
            
        author_text = author_text.strip()
        
        # Check if this looks like BibTeX format "Surname, Given"
        if ',' in author_text and author_text.count(',') == 1:
            parts = author_text.split(',', 1)
            surname_part = parts[0].strip()
            given_part = parts[1].strip()
            
            # Enhanced detection for BibTeX format
            if self._is_bibtex_surname_given_format(surname_part, given_part):
                return f"{given_part} {surname_part}"
        
        # Not BibTeX format, return as-is (already "Given Surname" format or single name)
        return author_text
    
    def _is_bibtex_surname_given_format(self, surname_part, given_part):
        """
        Determine if "surname_part, given_part" represents BibTeX "Surname, Given" format
        vs just a regular list of names that happen to have a comma
        """
        # Both parts must be non-empty
        if not surname_part or not given_part:
            return False
        
        # Length checks - very short parts are likely initials or abbreviations
        if len(surname_part) < 2 or len(given_part) < 1:
            return False
            
        # Check if surname_part looks like a surname:
        # 1. Starts with capital letter OR starts with lowercase prefix (like "de", "van", "von")
        # 2. Not just initials (has some lowercase letters OR is all-caps like "VS") 
        # 3. Doesn't end with period (not an initial)
        
        # Check for compound surnames with lowercase prefixes
        compound_prefixes = ['de', 'van', 'von', 'del', 'da', 'du', 'le', 'la', 'el']
        starts_with_prefix = any(surname_part.lower().startswith(prefix + ' ') for prefix in compound_prefixes)
        
        surname_valid = (
            (surname_part[0].isupper() or starts_with_prefix) and
            not surname_part.endswith('.') and
            (any(c.islower() for c in surname_part) or  # Has lowercase letters
             surname_part.isupper() or                   # All caps (like "VS")
             ' ' in surname_part)                        # Compound name (like "de Melo")
        )
        
        # Check if given_part looks like a given name:
        # 1. Starts with capital letter
        # 2. Could be full name, all-caps abbreviation, or name with middle initial
        given_valid = (
            given_part[0].isupper() and
            (any(c.islower() for c in given_part) or    # Has lowercase letters  
             given_part.isupper() or                     # All caps (like "VS")
             ' ' in given_part)                          # Has space (like "Celso M")
        )
        
        return surname_valid and given_valid

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
        # Note: DOIs can contain parentheses, so we shouldn't exclude them
        doi_patterns = [
            r'doi\.org/([^\s,]+)',
            r'doi:\s*([^\s,]+)',
            r'DOI:\s*([^\s,]+)',
        ]
        
        doi = None
        url = None
        for pattern in doi_patterns:
            doi_match = re.search(pattern, ref_text, re.IGNORECASE)
            if doi_match:
                doi = doi_match.group(1).split('#')[0]  # Strip URL fragments
                
                # Clean DOI: remove asterisk contamination (e.g., "10.1088/123*http://..." -> "10.1088/123")
                if '*' in doi:
                    doi = doi.split('*')[0]
                
                from refchecker.utils.doi_utils import construct_doi_url
                url = construct_doi_url(doi)
                break
        
        # Extract other URLs if no DOI found
        if not url and not arxiv_url:
            url_match = re.search(r'https?://(?!arxiv\.org)[^\s,]+', ref_text)
            if url_match:
                from refchecker.utils.url_utils import clean_url_punctuation
                url = clean_url_punctuation(url_match.group(0))
        
        # Extract year - will be determined from structured parts below
        year = None
        
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
                title = clean_title_basic(text)
                authors = ['Unknown Author']
                logger.debug(f"1-part title format - Title: '{title}'")
        elif len(parts) == 2:
            # Format: Authors # Title
            author_text = parts[0].strip()
            title = clean_title_basic(parts[1].strip())
            logger.debug(f"2-part format - Authors: '{author_text}', Title: '{title}'")
            # Parse authors
            authors = self._clean_llm_author_text(author_text)
        elif len(parts) == 3:
            # Format: Authors # Title # Year (most common)
            author_text = parts[0].strip()
            title = clean_title_basic(parts[1].strip())
            year_part = parts[2].strip()
            logger.debug(f"3-part format - Authors: '{author_text}', Title: '{title}', Year part: '{year_part}'")
            # Parse authors
            authors = self._clean_llm_author_text(author_text)
        elif len(parts) == 4:
            # Format could be: Authors # Title # Venue # Year
            # OR: Authors # Title # Year # URL (when venue is empty)
            author_text = parts[0].strip()
            title = clean_title_basic(parts[1].strip())
            third_part = parts[2].strip()
            fourth_part = parts[3].strip()
            
            # Check if third part looks like a year (4 digits starting with 19 or 20)
            if re.match(r'^(19|20)\d{2}$', third_part):
                # Format: Authors # Title # Year # URL
                venue = ""
                year_part = third_part
                # Check if fourth part is a URL
                if fourth_part.startswith('http'):
                    url = fourth_part if 'arxiv' not in fourth_part.lower() else None
                    arxiv_url = fourth_part if 'arxiv' in fourth_part.lower() else arxiv_url
                else:
                    year_part = fourth_part  # In case fourth part is also a year
                logger.debug(f"4-part format (Year in 3rd) - Authors: '{author_text}', Title: '{title}', Year: '{year_part}', URL: '{fourth_part}'")
            else:
                # Standard format: Authors # Title # Venue # Year
                venue = third_part
                year_part = fourth_part
                logger.debug(f"4-part format (Venue/Year) - Authors: '{author_text}', Title: '{title}', Venue: '{venue}', Year part: '{year_part}'")
            
            # Parse authors
            authors = self._clean_llm_author_text(author_text)
        elif len(parts) == 5:
            # Format: Authors # Title # Venue # Year # URL (standard LLM format)
            author_text = parts[0].strip()
            title = clean_title_basic(parts[1].strip())
            venue = parts[2].strip()
            year_part = parts[3].strip()
            url_part = parts[4].strip()
            logger.debug(f"5-part format - Authors: '{author_text}', Title: '{title}', Venue: '{venue}', Year: '{year_part}', URL: '{url_part}'")
            
            # Parse authors
            authors = self._clean_llm_author_text(author_text)
            
            # Process URL part
            if url_part.startswith('http'):
                if 'arxiv' in url_part.lower():
                    arxiv_url = url_part
                else:
                    from refchecker.utils.url_utils import clean_url_punctuation
                    url = clean_url_punctuation(url_part)
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
                year_part = parts[3].strip()
            if len(parts) >= 5:
                # Handle URL in 5th position
                url_part = parts[4].strip()
                if url_part.startswith('http'):
                    if 'arxiv' in url_part.lower():
                        arxiv_url = url_part
                    else:
                        from refchecker.utils.url_utils import clean_url_punctuation
                        url = clean_url_punctuation(url_part)
            if len(parts) > 5:
                # For cases with more than 5 parts, combine the remaining parts as additional info
                additional_info = ' '.join(parts[5:]).strip()
                logger.debug(f"Additional parts beyond standard 5-part format: {additional_info}")
        
        # Extract year from year_part if we have one
        if 'year_part' in locals() and year_part:
            # First try to extract a 4-digit year from year_part
            year_match = re.search(r'\b(19|20)\d{2}\b', year_part)
            if year_match:
                year = int(year_match.group(0))
            else:
                # Try to extract year from the year_part itself if it's just a year
                if year_part.isdigit() and len(year_part) == 4:
                    year = int(year_part)
        
        # If no year found from structured parts, fall back to regex search of entire text
        # but exclude URLs to avoid picking up years from ArXiv IDs like 1911.01547
        if not year:
            # Remove URLs before searching for years
            text_without_urls = re.sub(r'https?://[^\s]+', '', ref_text)
            text_without_urls = re.sub(r'arxiv:[^\s]+', '', text_without_urls, flags=re.IGNORECASE)
            year_match = re.search(r'\b(19|20)\d{2}\b', text_without_urls)
            if year_match:
                year = int(year_match.group(0))
        
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
        title = clean_title(title) if title else ""
        title = title.rstrip(',').strip()
        
        # Clean up venue
        # Clean up venue - if venue is just a year, null it
        if venue and venue.isdigit() and len(venue) == 4 and venue.startswith(('19', '20')):
            venue = ""
        else:            
            venue = re.sub(r'\s+', ' ', venue).strip() if venue else ""
            venue = venue.rstrip(',').strip()
        
        if not authors:
            authors = []  # Allow empty authors for references without author information
        
        # Determine reference type
        ref_type = 'arxiv' if arxiv_url else ('non-arxiv' if (url or doi) else 'other')
        
        # If we have an ArXiv URL but suspicious year (like 1911 from ArXiv ID), try to get correct year from ArXiv API
        if arxiv_url and year and (year < 1990 or str(year) in arxiv_url):
            arxiv_id_match = re.search(r'(\d{4}\.\d{4,5})', arxiv_url)
            if arxiv_id_match:
                arxiv_id = arxiv_id_match.group(1)
                try:
                    import arxiv
                    search = arxiv.Search(id_list=[arxiv_id])
                    paper = next(iter(search.results()), None)
                    if paper and paper.published:
                        correct_year = paper.published.year
                        logger.debug(f"Corrected year from ArXiv API: {year} -> {correct_year} for {arxiv_id}")
                        year = correct_year
                except Exception as e:
                    logger.debug(f"Could not fetch ArXiv year for {arxiv_id}: {e}")
        
        return {
            'url': arxiv_url or url or "",
            'doi': doi,
            'year': year or 0,
            'authors': authors,
            'venue': venue,
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
                doi = doi_match.group(1).split('#')[0]  # Strip URL fragments
                
                # Clean DOI: remove asterisk contamination (e.g., "10.1088/123*http://..." -> "10.1088/123")
                if '*' in doi:
                    doi = doi.split('*')[0]
                
                from refchecker.utils.doi_utils import construct_doi_url
                url = construct_doi_url(doi)
                break
        
        # Extract other URLs if no DOI found
        if not url and not arxiv_url:
            url_match = re.search(r'https?://(?!arxiv\.org)[^\s,\)]+', ref_text)
            if url_match:
                from refchecker.utils.url_utils import clean_url_punctuation
                url = clean_url_punctuation(url_match.group(0))
        
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
        title = clean_title(title) if title else ""
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
        logger.debug(f"Extracting bibliography for paper {paper_id}: {paper.title}")
        
        # Check if we can get BibTeX content for this paper (ArXiv or other sources)
        from refchecker.utils.arxiv_utils import get_bibtex_content
        bibtex_content = get_bibtex_content(paper)
        if bibtex_content:
            logger.debug(f"Found BibTeX content for {paper_id}, using structured bibliography")
            
            # Save BibTeX for debugging
            if debug_mode:
                debug_dir = "debug"
                if not os.path.exists(debug_dir):
                    os.makedirs(debug_dir)
                try:
                    with open(os.path.join(debug_dir, f"{paper_id}_bibliography.txt"), 'w', encoding='utf-8', errors='replace') as f:
                        f.write(bibtex_content)
                    logger.info(f"Saved BibTeX content to {os.path.join(debug_dir, f'{paper_id}_bibliography.txt')}")
                except Exception as e:
                    logger.warning(f"Could not save debug BibTeX file for {paper_id}: {e}")
            
            # Check if this is LaTeX thebibliography format (e.g., from .bbl files)
            if '\\begin{thebibliography}' in bibtex_content and '\\bibitem' in bibtex_content:
                logger.info(f"Detected LaTeX thebibliography format, using extract_latex_references")
                # Use None for file_path since this is content from .bbl files
                references = extract_latex_references(bibtex_content, None)
                
                # Validate the parsed references and fallback to LLM if needed
                from refchecker.utils.text_utils import validate_parsed_references
                validation = validate_parsed_references(references)
                
                if not validation['is_valid']:
                    logger.debug(f"LaTeX parsing validation failed (quality: {validation['quality_score']:.2f})")
                    logger.debug(f"Issues detected: {len(validation['issues'])} problems")
                    for issue in validation['issues'][:5]:  # Log first 5 issues
                        logger.debug(f"  - {issue}")
                    
                    # Try LLM fallback if available
                    if self.llm_extractor:
                        logger.info("Falling back to LLM-based extraction due to unsupported LaTeX format")
                        try:
                            llm_references = self.llm_extractor.extract_references(bibtex_content)
                            if llm_references:
                                # Process LLM results first to get structured references
                                processed_llm_refs = self._process_llm_extracted_references(llm_references)
                                # Then validate the processed results
                                llm_validation = validate_parsed_references(processed_llm_refs)
                                if llm_validation['quality_score'] > validation['quality_score']:
                                    logger.debug(f"LLM extraction successful (quality: {llm_validation['quality_score']:.2f})")
                                    references = processed_llm_refs
                                else:
                                    logger.debug("LLM extraction didn't improve quality, keeping original results")
                            else:
                                logger.warning("LLM extraction returned no results")
                        except Exception as e:
                            logger.error(f"LLM fallback failed: {e}")
                    else:
                        logger.warning("No LLM available for fallback, using original parsing results")
                else:
                    logger.debug(f"LaTeX parsing validation passed (quality: {validation['quality_score']:.2f})")
            else:
                # Parse BibTeX using the standard flow (LLM or regex based on config)
                references = self.parse_references(bibtex_content)
            
            # Save extracted references for debugging
            if debug_mode:
                try:
                    with open(os.path.join(debug_dir, f"{paper_id}_references.json"), 'w', encoding='utf-8', errors='replace') as f:
                        json.dump(references, f, indent=2)
                except Exception as e:
                    logger.warning(f"Could not save debug references file for {paper_id}: {e}")
            
            if references:
                logger.debug(f"Extracted {len(references)} references")
                return references
        
        # Check if this is a text file containing references
        if hasattr(paper, 'is_text_refs') and paper.is_text_refs:
            # Read the text file directly - it should contain references
            logger.debug(f"Processing text file containing references: {paper.file_path}")
            try:
                with open(paper.file_path, 'r', encoding='utf-8') as f:
                    bibliography_text = f.read()
                
                # Save the text for debugging
                if debug_mode:
                    debug_dir = "debug"
                    if not os.path.exists(debug_dir):
                        os.makedirs(debug_dir)
                    
                    try:
                        with open(os.path.join(debug_dir, f"{paper_id}_bibliography.txt"), 'w', encoding='utf-8', errors='replace') as f:
                            f.write(bibliography_text)
                        logger.info(f"Saved reference text to {os.path.join(debug_dir, f'{paper_id}_bibliography.txt')}")
                    except Exception as e:
                        logger.warning(f"Could not save debug bibliography file for {paper_id}: {e}")
                
                # Parse references directly from the text
                references = self.parse_references(bibliography_text)
                
                # Save the extracted references for debugging
                if debug_mode:
                    try:
                        with open(os.path.join(debug_dir, f"{paper_id}_references.json"), 'w', encoding='utf-8', errors='replace') as f:
                            json.dump(references, f, indent=2)
                    except Exception as e:
                        logger.warning(f"Could not save debug references file for {paper_id}: {e}")
                
                logger.debug(f"Extracted {len(references)} references from text file")                
                return references
                
            except Exception as e:
                logger.error(f"Error reading text file {paper.file_path}: {e}")
                return []
        
        # Check if this is a LaTeX file
        elif hasattr(paper, 'is_latex') and paper.is_latex:
            # Extract text from LaTeX file
            text = self.extract_text_from_latex(paper.file_path)
            
            # Try programmatic LaTeX extraction first
            latex_format = detect_latex_bibliography_format(text)
            if latex_format['is_latex']:
                logger.info(f"Detected LaTeX bibliography format: {latex_format['format_type']}")
                latex_references = extract_latex_references(text, paper.file_path)
                
                if latex_references:
                    logger.info(f"Extracted {len(latex_references)} references using LaTeX parser")
                    return latex_references
        
        # Check if this is a BibTeX file
        elif hasattr(paper, 'is_bibtex') and paper.is_bibtex:
            try:
                # Read BibTeX file content
                with open(paper.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    bib_content = f.read()
                
                logger.info(f"Processing BibTeX file: {paper.file_path}")
                
                # Use programmatic BibTeX extraction
                bibtex_references = extract_latex_references(bib_content, paper.file_path)
                
                if bibtex_references:
                    logger.debug(f"Extracted {len(bibtex_references)} references from BibTeX file")
                    return bibtex_references
                else:
                    logger.warning(f"No references found in BibTeX file: {paper.file_path}")
                    return []
                    
            except Exception as e:
                logger.error(f"Error reading BibTeX file {paper.file_path}: {e}")
                return []
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
            
            try:
                with open(os.path.join(debug_dir, f"{paper_id}_text.txt"), 'w', encoding='utf-8', errors='replace') as f:
                    f.write(text)
                logger.info(f"Saved extracted text to {os.path.join(debug_dir, f'{paper_id}_text.txt')}")
            except Exception as e:
                logger.warning(f"Could not save debug text file for {paper_id}: {e}")
                # Continue processing even if debug file writing fails
        
        # Find bibliography section
        bibliography_text = self.find_bibliography_section(text)
        
        if not bibliography_text:
            logger.warning(f"Could not find bibliography section for {paper_id}")
            return []
        
        # Save the bibliography text for debugging
        if debug_mode:
            try:
                with open(os.path.join(debug_dir, f"{paper_id}_bibliography.txt"), 'w', encoding='utf-8', errors='replace') as f:
                    f.write(bibliography_text)
                logger.info(f"Saved bibliography text to {os.path.join(debug_dir, f'{paper_id}_bibliography.txt')}")
            except Exception as e:
                logger.warning(f"Could not save debug bibliography file for {paper_id}: {e}")
        
        # Parse references
        references = self.parse_references(bibliography_text)
        
        # Save the extracted references for debugging
        if debug_mode:
            try:
                with open(os.path.join(debug_dir, f"{paper_id}_references.json"), 'w', encoding='utf-8', errors='replace') as f:
                    json.dump(references, f, indent=2)
            except Exception as e:
                logger.warning(f"Could not save debug references file for {paper_id}: {e}")
        
        logger.debug(f"Extracted {len(references)} references with arxiv links for {paper_id}")
        
        return references
    
    
    def normalize_text(self, text):
        """
        Normalize text by removing diacritical marks and special characters.
        This is a wrapper method for backward compatibility with tests.
        """
        return common_normalize_text(text)
    
    def get_arxiv_paper_from_local_db(self, arxiv_id):
        """
        Get arXiv paper metadata from local database 
        
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
            
            logger.debug(f"Found arXiv paper {arxiv_id} in local database")
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
    
    def compare_authors(self, authors1, authors2):
        """
        Compare authors using the text_utils compare_authors function.
        
        Args:
            authors1: First list of authors
            authors2: Second list of authors
            
        Returns:
            Tuple of (match_result, error_message)
        """
        return compare_authors(authors1, authors2)
    
    def _verify_references_sequential(self, paper, bibliography, paper_errors, error_types, unverified_count, debug_mode):
        """
        Sequential reference verification (original implementation)
        
        Args:
            paper: The source paper
            bibliography: List of references to verify
            paper_errors: List to append errors to
            error_types: Dictionary to track error types
            unverified_count: Counter for unverified references
            debug_mode: Whether debug mode is enabled
        """
        for i, reference in enumerate(bibliography):
            ref_id = self.extract_arxiv_id_from_url(reference['url'])
            
            # Print reference info in non-debug mode (improved formatting)
            raw_title = reference.get('title', 'Untitled')
            # Clean LaTeX commands from title for display
            from refchecker.utils.text_utils import strip_latex_commands
            title = strip_latex_commands(raw_title)
            from refchecker.utils.text_utils import format_authors_for_display
            authors = format_authors_for_display(reference.get('authors', []))
            year = reference.get('year', '')
            venue = reference.get('venue', '') or reference.get('journal', '')
            url = reference.get('url', '')
            doi = reference.get('doi', '')
            # Extract actual reference number from raw text for accurate display
            raw_text = reference.get('raw_text', '')
            match = re.match(r'\[(\d+)\]', raw_text)
            ref_num = match.group(1) if match else str(i + 1)
            print(f"[{ref_num}/{len(bibliography)}] {title}")
            if authors:
                print(f"       {authors}")
            if venue:
                print(f"       {venue}")
            if year:
                print(f"       {year}")
            if doi:
                print(f"       {doi}")
            # --- DEBUG TIMER ---
            start_time = time.time()
            errors, reference_url, verified_data = self.verify_reference(paper, reference)

            # Show cited URL if available
            if url:
                print(f"       {url}")
            
            # Get the appropriate verified URL using shared logic
            verified_url_to_show = self._get_verified_url(verified_data, reference_url, errors)
            
            # Show the verified URL with appropriate label
            print("")
            if verified_url_to_show:
                print(f"       Verified URL: {verified_url_to_show}")
            
            # Show correct ArXiv URL if available from verified data and different from cited
            if verified_data:
                external_ids = verified_data.get('externalIds', {})
                if external_ids.get('ArXiv'):
                    correct_arxiv_url = f"https://arxiv.org/abs/{external_ids['ArXiv']}"
                    # Only show if it's different from the cited URL
                    if correct_arxiv_url != url:
                        print(f"       Correct ArXiv URL: {correct_arxiv_url}")
            
            # Show additional external ID URLs if available and different
            if verified_data:
                external_ids = verified_data.get('externalIds', {})
                
                # Show DOI URL if available and different from what's already shown
                if external_ids.get('DOI'):
                    from refchecker.utils.doi_utils import construct_doi_url
                    doi_url = construct_doi_url(external_ids['DOI'])
                    if doi_url != verified_url_to_show and doi_url != url:
                        print(f"       DOI URL: {doi_url}")
                
                # Show any other URL from verified data if different
                if verified_data.get('url') and verified_data['url'] != verified_url_to_show and verified_data['url'] != url:
                    print(f"       {verified_data['url']}")
            elapsed = time.time() - start_time
            if elapsed > 5.0:
                logger.debug(f"Reference {i+1} took {elapsed:.2f}s to verify: {reference.get('title', 'Untitled')}")
                logger.debug(f"Raw text: {reference.get('raw_text', '')}")
            
            self._process_reference_result(paper, reference, errors, reference_url, 
                                         paper_errors, unverified_count, debug_mode, verified_data=verified_data)
    
    def _verify_references_parallel(self, paper, bibliography, paper_errors, error_types, unverified_count, debug_mode):
        """
        Parallel reference verification using ParallelReferenceProcessor
        
        Args:
            paper: The source paper
            bibliography: List of references to verify
            paper_errors: List to append errors to
            error_types: Dictionary to track error types  
            unverified_count: Counter for unverified references
            debug_mode: Whether debug mode is enabled
        """
        # Create parallel processor
        processor = ParallelReferenceProcessor(
            base_checker=self,
            max_workers=self.max_workers,
            enable_progress=not debug_mode
        )
        
        # Set up result callback to handle each completed reference  
        def result_callback(result):
            self._process_reference_result(paper, result.reference, result.errors, result.url,
                                         paper_errors, unverified_count, debug_mode, print_output=False, verified_data=result.verified_data)
        
        # Run parallel verification
        processor.verify_references_parallel(paper, bibliography, result_callback)
    
    def _process_reference_result(self, paper, reference, errors, reference_url, 
                                paper_errors, unverified_count, debug_mode, print_output=True, verified_data=None):
        """
        Process the result of reference verification (shared by both sequential and parallel)
        
        Args:
            paper: The source paper
            reference: The reference that was verified
            errors: List of errors found (or None)
            reference_url: URL of the reference if found
            paper_errors: List to append errors to
            unverified_count: Counter for unverified references (passed by reference)
            debug_mode: Whether debug mode is enabled
            print_output: Whether to print output (False for parallel mode to avoid duplication)
        """
        # If errors found, add to dataset and optionally print details
        if errors:
            # Check if there's an unverified error among the errors
            has_unverified_error = any(e.get('error_type') == 'unverified' or e.get('warning_type') == 'unverified' or e.get('info_type') == 'unverified' for e in errors)
            
            if has_unverified_error:
                self.total_unverified_refs += 1
                self._display_unverified_error_with_subreason(reference, reference_url, errors, debug_mode, print_output)
            
            # Add to dataset and handle all errors
            self.add_error_to_dataset(paper, reference, errors, reference_url, verified_data)
            paper_errors.extend(errors)
            
            # Count errors vs warnings vs info
            error_count = sum(1 for e in errors if 'error_type' in e and e['error_type'] != 'unverified')
            warning_count = sum(1 for e in errors if 'warning_type' in e)
            info_count = sum(1 for e in errors if 'info_type' in e)
            self.total_errors_found += error_count
            self.total_warnings_found += warning_count
            self.total_info_found += info_count
            
            # Display all non-unverified errors and warnings
            self._display_non_unverified_errors(errors, debug_mode, print_output)
    
    def _has_arxiv_id_error(self, errors):
        """Check if there's an ArXiv ID error in the error list"""
        if not errors:
            return False
        return any(error.get('error_type') == 'arxiv_id' for error in errors)
    
    def _get_verified_url(self, verified_data, reference_url, errors):
        """Get the appropriate verified URL based on priority and ArXiv ID validation"""
        # If we have verified data, we should show a verified URL even if there's an ArXiv ID error
        # The ArXiv ID error is a separate issue from successful paper verification
        
        # First priority: Non-ArXiv URLs from verified_data (direct from API, most reliable)
        if verified_data and verified_data.get('url') and 'arxiv.org' not in verified_data['url']:
            return verified_data['url']
        
        # Second priority: Semantic Scholar URL from paperId (if no direct URL available)
        if verified_data and verified_data.get('paperId'):
            return f"https://www.semanticscholar.org/paper/{verified_data['paperId']}"
        
        # Third priority: DOI URL from verified data (more reliable than potentially wrong ArXiv URLs)
        if verified_data and verified_data.get('externalIds', {}).get('DOI'):
            from refchecker.utils.doi_utils import construct_doi_url
            return construct_doi_url(verified_data['externalIds']['DOI'])
        
        # Fourth priority: ArXiv URL from verified data (but only if there's no ArXiv ID error)
        if verified_data and verified_data.get('externalIds', {}).get('ArXiv'):
            # Only show ArXiv URL as verified URL if there's no ArXiv ID mismatch
            if not self._has_arxiv_id_error(errors):
                from refchecker.utils.url_utils import construct_arxiv_url
                correct_arxiv_id = verified_data['externalIds']['ArXiv']
                return construct_arxiv_url(correct_arxiv_id)
        
        # Fifth priority: Other URLs from verified_data
        if verified_data and verified_data.get('url'):
            return verified_data['url']
        
        # Last resort: Use the URL returned by the verification process (but be cautious with ArXiv URLs)
        if reference_url:
            return self._validate_reference_url(reference_url, verified_data)
            
        return None
    
    def _validate_reference_url(self, reference_url, verified_data):
        """Validate and potentially replace reference URL based on ArXiv ID matching"""
        # If it's an ArXiv URL and we have verified data, only use it if the ArXiv ID matches
        if 'arxiv.org' in reference_url and verified_data:
            external_ids = verified_data.get('externalIds', {})
            if external_ids.get('ArXiv'):
                # Extract ArXiv ID from the URL using shared utility
                from refchecker.utils.url_utils import extract_arxiv_id_from_url
                url_arxiv_id = extract_arxiv_id_from_url(reference_url)
                if url_arxiv_id:
                    correct_arxiv_id = external_ids['ArXiv']
                    # Only use the URL if the ArXiv IDs match
                    if url_arxiv_id == correct_arxiv_id:
                        return reference_url
                    # If they don't match, prefer the Semantic Scholar URL or DOI
                    else:
                        return self._get_fallback_url(external_ids)
                else:
                    # If we can't extract ArXiv ID, be safe and use verified data
                    return self._get_fallback_url(external_ids)
            else:
                # No verified ArXiv ID, so the URL might be wrong
                return reference_url
        else:
            # Non-ArXiv URL, probably safe to use
            return reference_url
    
    def _get_fallback_url(self, external_ids, verified_data=None):
        """Get fallback URL from external IDs (Semantic Scholar or DOI)"""
        # Prefer paperId for Semantic Scholar URLs
        if verified_data and verified_data.get('paperId'):
            return f"https://www.semanticscholar.org/paper/{verified_data['paperId']}"
        elif external_ids.get('DOI'):
            from refchecker.utils.doi_utils import construct_doi_url
            return construct_doi_url(external_ids['DOI'])
        return None
    
    def _format_year_string(self, year):
        """Format year for display, handling missing or invalid years"""
        if year and year != 0:
            return str(year)
        return "year unknown"
    

    def _display_unverified_error_with_subreason(self, reference, reference_url, errors, debug_mode, print_output):
        """Display the unverified error message with citation details and subreason"""
        if not debug_mode and print_output:
            print(f"      ❓ Could not verify: {reference.get('title', 'Untitled')}")
            
            # Extract and display the subreason from unverified errors
            unverified_errors = [e for e in errors if e.get('error_type') == 'unverified']
            if unverified_errors:
                error_details = unverified_errors[0].get('error_details', '')
                if error_details:
                    subreason = self._categorize_unverified_reason(error_details)
                    print(f"         Subreason: {subreason}")

    def _categorize_unverified_reason(self, error_details):
        """Categorize the unverified error into checker error or not found"""
        error_details_lower = error_details.lower()
        
        # New specific URL-based unverified reasons
        if error_details_lower == "non-existent web page":
            return "Non-existent web page"
        elif error_details_lower == "paper not found and url doesn't reference it":
            return "Paper not found and URL doesn't reference it"
        elif error_details_lower == "paper not verified but url references paper":
            return "Paper not verified but URL references paper"
        
        # Checker/API errors
        api_error_patterns = [
            'api error', 'rate limit', 'http error', 'network error', 
            'could not fetch', 'connection', 'timeout', 'server error',
            'could not verify reference using any available api',
            'database connection not available'
        ]
        
        # Not found patterns  
        not_found_patterns = [
            'not found', 'could not be found', 'repository not found',
            'web page not found', '404', 'invalid', 'too short or empty'
        ]
        
        # Processing errors
        processing_error_patterns = [
            'error processing', 'error parsing', 'unexpected error'
        ]
        
        for pattern in api_error_patterns:
            if pattern in error_details_lower:
                return "Checker had an error"
                
        for pattern in not_found_patterns:
            if pattern in error_details_lower:
                return "Paper not found by any checker"
                
        for pattern in processing_error_patterns:
            if pattern in error_details_lower:
                return "Checker had an error"
        
        # Default fallback
        return "Paper not found by any checker"
    
    def _display_non_unverified_errors(self, errors, debug_mode, print_output):
        """Display all non-unverified errors and warnings"""
        if not debug_mode and print_output:
            for error in errors:
                if error.get('error_type') != 'unverified' and error.get('warning_type') != 'unverified' and error.get('info_type') != 'unverified':
                    error_type = error.get('error_type') or error.get('warning_type') or error.get('info_type')
                    error_details = error.get('error_details') or error.get('warning_details') or error.get('info_details', 'Unknown error')
                    
                    from refchecker.utils.error_utils import print_labeled_multiline

                    if error_type == 'arxiv_id':
                        print(f"      ❌ {error_details}")
                    elif 'error_type' in error:
                        print_labeled_multiline("❌ Error", error_details)
                    elif 'warning_type' in error:
                        print_labeled_multiline("⚠️  Warning", error_details)
                    else:
                        print_labeled_multiline("ℹ️  Information", error_details)

    def _output_reference_errors(self, reference, errors, url):
        """
        Output method for parallel processor to use (maintains consistent formatting)
        
        Args:
            reference: The reference being processed
            errors: List of errors found
            url: URL of the reference if found
        """
        # This method is called by the parallel processor to maintain output format
        # The actual processing is handled by _process_reference_result
        pass
    
    def _cleanup_resources(self):
        """Clean up database connections and other resources"""
        try:
            if hasattr(self.non_arxiv_checker, 'close'):
                self.non_arxiv_checker.close()
                # No logging - cleanup happens automatically
        except Exception as e:
            # Silent cleanup - errors are expected with SQLite threading
            pass


def main():
    """Main function to parse arguments and run the reference checker"""
    print(f"Refchecker v{__version__} - Validate references in academic papers")
    print(f"By Mark Russinovich and various agentic AI assistants")

    parser = argparse.ArgumentParser(description="Academic paper references checker")
    parser.add_argument("--debug", action="store_true",
                        help="Run in debug mode with verbose logging")
    parser.add_argument("--paper", type=str,
                        help="Validate a specific paper by ArXiv ID, URL, local PDF file path, local LaTeX file path, local text file containing references, or local BibTeX file")
    parser.add_argument("--semantic-scholar-api-key", type=str,
                        help="API key for Semantic Scholar (optional, increases rate limits). Can also be set via SEMANTIC_SCHOLAR_API_KEY environment variable")
    parser.add_argument("--db-path", type=str,
                        help="Path to local Semantic Scholar database (automatically enables local DB mode)")
    parser.add_argument("--output-file", nargs='?', const='reference_errors.txt', type=str,
                        help="Path to output file for reference discrepancies (default: reference_errors.txt if flag provided, no file if not provided)")
    
    # LLM configuration arguments
    parser.add_argument("--llm-provider", type=str, choices=["openai", "anthropic", "google", "azure", "vllm"],
                        help="Enable LLM with specified provider (openai, anthropic, google, azure, vllm)")
    parser.add_argument("--llm-model", type=str,
                        help="LLM model to use (overrides default for the provider)")
    parser.add_argument("--llm-endpoint", type=str,
                        help="Endpoint for the LLM provider (overrides default endpoint)")
    parser.add_argument("--llm-parallel-chunks", action="store_true", default=None,
                        help="Enable parallel processing of LLM chunks (default: enabled)")
    parser.add_argument("--llm-no-parallel-chunks", action="store_true",
                        help="Disable parallel processing of LLM chunks")
    parser.add_argument("--llm-max-chunk-workers", type=int,
                        help="Maximum number of workers for parallel LLM chunk processing (default: 4)")
    parser.add_argument("--disable-parallel", action="store_true",
                        help="Disable parallel processing and run sequentially")
    parser.add_argument("--max-workers", type=int, default=6,
                        help="Maximum number of worker threads for parallel processing (default: 6)")

    args = parser.parse_args()
    
    # Process paper argument - can be ArXiv ID, URL, or local PDF/LaTeX file
    paper_id = None
    local_pdf_path = None
    
    if args.paper:
        if args.paper.startswith('http'):
            # Check if it's a PDF URL first
            if (args.paper.lower().endswith('.pdf') or 
                'pdf' in args.paper.lower() or
                '/content' in args.paper or  # Repository URLs often end with /content
                'bitstreams' in args.paper or  # DSpace repository URLs
                args.paper.endswith('/download')):  # Common download endpoint
                # This is a PDF URL - we'll download it and process as a local PDF
                local_pdf_path = args.paper  # Store the URL, we'll handle download later
            else:
                # Try to extract arXiv ID from URL
                paper_id = extract_arxiv_id_from_url(args.paper)
                if not paper_id:
                    print(f"Error: Could not extract arXiv ID from URL: {args.paper}")
                    return 1
        elif os.path.exists(args.paper):
            # This is a local file - check if it exists first, then determine type
            local_pdf_path = args.paper
            if not (args.paper.lower().endswith('.pdf') or 
                   args.paper.lower().endswith('.tex') or 
                   args.paper.lower().endswith('.txt') or 
                   args.paper.lower().endswith('.bib')):
                print(f"Error: Unsupported file type. Supported formats: .pdf, .tex, .txt, .bib")
                return 1
        else:
            # Assume it's an online paper ID (ArXiv ID, DOI, etc.)
            paper_id = args.paper
    
    # Process LLM configuration overrides
    llm_config = None
    if args.llm_provider:
        # Get API key interactively if needed for LLM provider
        api_key = get_llm_api_key_interactive(args.llm_provider)
        if api_key is None and args.llm_provider != 'vllm':
            print(f"Error: API key is required for {args.llm_provider} provider.")
            return 1
        
        llm_config = {
            'provider': args.llm_provider,
            'model': args.llm_model,
            'api_key': api_key,
            'endpoint': args.llm_endpoint
        }
        
        # Handle parallel chunk processing arguments
        if args.llm_parallel_chunks is not None:
            llm_config['parallel_chunks'] = True
        elif args.llm_no_parallel_chunks:
            llm_config['parallel_chunks'] = False
            
        if args.llm_max_chunk_workers is not None:
            llm_config['max_chunk_workers'] = args.llm_max_chunk_workers
    
    # Get Semantic Scholar API key from command line or environment variable
    semantic_scholar_api_key = args.semantic_scholar_api_key or os.getenv('SEMANTIC_SCHOLAR_API_KEY')
    
    try:
        # Initialize the reference checker
        checker = ArxivReferenceChecker(
            semantic_scholar_api_key=semantic_scholar_api_key,
            db_path=args.db_path,
            output_file=args.output_file,
            llm_config=llm_config,
            debug_mode=args.debug,
            enable_parallel=not args.disable_parallel,
            max_workers=args.max_workers
        )
        
        if checker.fatal_error:
            return 1
        
        # Run the checker
        checker.run(
            debug_mode=args.debug,
            specific_paper_id=paper_id,
            local_pdf_path=local_pdf_path
        )
        
        # Check for fatal errors that occurred during runtime
        if checker.fatal_error:
            return 1
            
    except KeyboardInterrupt:
        print("\n✗ Process interrupted by user.")
        return 1
    except Exception as e:
        print(f"\n✗ Error during processing: {str(e)}")
        logger.error(f"Unexpected error: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
