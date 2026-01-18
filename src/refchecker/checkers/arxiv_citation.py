#!/usr/bin/env python3
"""
ArXiv Citation Checker - Authoritative Source for ArXiv Papers

This module provides functionality to verify ArXiv papers by fetching the official
BibTeX citation directly from ArXiv. This is used as the authoritative metadata source
for papers found on ArXiv, as it reflects the author-submitted metadata.

Key features:
- Fetches official BibTeX from https://arxiv.org/bibtex/{arxiv_id}
- Always uses the latest version metadata (strips version suffixes)
- Logs warnings when cited version differs from latest version
- Parses BibTeX to extract normalized metadata matching refchecker schema

Usage:
    from refchecker.checkers.arxiv_citation import ArXivCitationChecker
    
    checker = ArXivCitationChecker()
    
    reference = {
        'title': 'Attention Is All You Need',
        'authors': ['Ashish Vaswani', 'Noam Shazeer'],
        'year': 2017,
        'url': 'https://arxiv.org/abs/1706.03762v5',
    }
    
    verified_data, errors, url = checker.verify_reference(reference)
"""

import re
import logging
import requests
from typing import Dict, List, Tuple, Optional, Any

import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import convert_to_unicode

from refchecker.utils.arxiv_rate_limiter import ArXivRateLimiter
from refchecker.utils.text_utils import (
    normalize_text,
    compare_authors,
    compare_titles_with_latex_cleaning,
    strip_latex_commands,
)
from refchecker.utils.error_utils import format_title_mismatch, validate_year
from refchecker.config.settings import get_config

logger = logging.getLogger(__name__)

# Get configuration
config = get_config()
SIMILARITY_THRESHOLD = config["text_processing"]["similarity_threshold"]


class ArXivCitationChecker:
    """
    Reference checker that uses ArXiv's official BibTeX export as the authoritative source.
    
    This checker fetches the official BibTeX citation from ArXiv for papers identified
    by their ArXiv ID. It uses the latest version's metadata as the authoritative source
    and logs warnings when the cited version differs from the latest.
    """
    
    def __init__(self, timeout: int = 30):
        """
        Initialize the ArXiv Citation Checker.
        
        Args:
            timeout: HTTP request timeout in seconds
        """
        self.base_url = "https://arxiv.org/bibtex"
        self.abs_url = "https://arxiv.org/abs"
        self.timeout = timeout
        self.rate_limiter = ArXivRateLimiter.get_instance()
        
        # Pattern to extract arXiv IDs from various URL formats
        self.arxiv_id_patterns = [
            # Standard arxiv.org URLs
            r'arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5})(v\d+)?',
            r'arxiv\.org/pdf/([0-9]{4}\.[0-9]{4,5})(v\d+)?',
            # Old format with category
            r'arxiv\.org/abs/([a-z-]+/[0-9]{7})(v\d+)?',
            r'arxiv\.org/pdf/([a-z-]+/[0-9]{7})(v\d+)?',
            # arXiv: prefix in text
            r'arXiv:([0-9]{4}\.[0-9]{4,5})(v\d+)?',
            r'arXiv:([a-z-]+/[0-9]{7})(v\d+)?',
            # export.arxiv.org URLs
            r'export\.arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5})(v\d+)?',
            r'export\.arxiv\.org/pdf/([0-9]{4}\.[0-9]{4,5})(v\d+)?',
        ]
    
    def extract_arxiv_id(self, reference: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract ArXiv ID from a reference, returning both the base ID and version.
        
        Args:
            reference: Reference dictionary containing url, raw_text, etc.
            
        Returns:
            Tuple of (arxiv_id_without_version, version_string_or_None)
            For example: ("2301.12345", "v2") or ("2301.12345", None)
        """
        # Sources to check for ArXiv ID
        sources = [
            reference.get('url', ''),
            reference.get('cited_url', ''),
            reference.get('raw_text', ''),
            reference.get('eprint', ''),  # BibTeX field
        ]
        
        for source in sources:
            if not source:
                continue
            
            for pattern in self.arxiv_id_patterns:
                match = re.search(pattern, source, re.IGNORECASE)
                if match:
                    arxiv_id = match.group(1)
                    version = match.group(2) if len(match.groups()) > 1 else None
                    logger.debug(f"Extracted ArXiv ID: {arxiv_id}, version: {version}")
                    return arxiv_id, version
        
        return None, None
    
    def fetch_bibtex(self, arxiv_id: str) -> Optional[str]:
        """
        Fetch the official BibTeX citation from ArXiv.
        
        This always fetches the latest version's BibTeX (ArXiv default behavior).
        
        Args:
            arxiv_id: ArXiv ID without version suffix (e.g., "2301.12345")
            
        Returns:
            BibTeX string or None if fetch failed
        """
        url = f"{self.base_url}/{arxiv_id}"
        
        # Wait for rate limit
        self.rate_limiter.wait()
        
        try:
            logger.debug(f"Fetching ArXiv BibTeX from: {url}")
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            bibtex_content = response.text.strip()
            
            # Validate it looks like BibTeX
            if bibtex_content and bibtex_content.startswith('@'):
                logger.debug(f"Successfully fetched BibTeX for ArXiv paper {arxiv_id}")
                return bibtex_content
            else:
                logger.debug(f"Invalid BibTeX response for ArXiv paper {arxiv_id}")
                return None
                
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout fetching ArXiv BibTeX for {arxiv_id}")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch ArXiv BibTeX for {arxiv_id}: {e}")
            return None
    
    def parse_bibtex(self, bibtex_str: str) -> Optional[Dict[str, Any]]:
        """
        Parse BibTeX string and extract metadata in refchecker schema format.
        
        Args:
            bibtex_str: BibTeX content string
            
        Returns:
            Dictionary with parsed metadata or None if parsing failed
        """
        try:
            # Configure parser
            parser = BibTexParser(common_strings=True)
            parser.customization = convert_to_unicode
            
            # Parse BibTeX
            bib_database = bibtexparser.loads(bibtex_str, parser=parser)
            
            if not bib_database.entries:
                logger.debug("No entries found in BibTeX")
                return None
            
            entry = bib_database.entries[0]
            
            # Extract and normalize fields
            title = entry.get('title', '')
            # Clean title - remove braces used for capitalization protection
            title = re.sub(r'\{([^}]*)\}', r'\1', title)
            title = title.strip()
            
            # Extract authors
            authors_str = entry.get('author', '')
            authors = self._parse_authors(authors_str)
            
            # Extract year - prefer year from eprint ID (original submission) over BibTeX year (latest revision)
            arxiv_id = entry.get('eprint', '')
            year = self._extract_year_from_eprint(arxiv_id)
            
            # Fall back to BibTeX year field if eprint year extraction fails
            if not year and entry.get('year'):
                try:
                    year = int(entry['year'])
                except ValueError:
                    pass
            
            # Build result in refchecker schema format
            result = {
                'title': title,
                'authors': [{'name': author} for author in authors],
                'year': year,
                'venue': 'arXiv',
                'externalIds': {
                    'ArXiv': arxiv_id,
                },
                'url': f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
                'isOpenAccess': True,
                'openAccessPdf': {
                    'url': f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None
                },
                # Store original bibtex for reference
                '_bibtex_entry': entry,
                '_source': 'ArXiv BibTeX Reference',
                '_source_url': f"https://arxiv.org/bibtex/{arxiv_id}" if arxiv_id else None,
            }
            
            # Add DOI if present (some ArXiv papers have DOIs)
            if entry.get('doi'):
                result['externalIds']['DOI'] = entry['doi']
            
            logger.debug(f"Parsed ArXiv BibTeX: title='{title[:50]}...', authors={len(authors)}, year={year}")
            return result
            
        except Exception as e:
            logger.warning(f"Failed to parse BibTeX: {e}")
            return None
    
    def _parse_authors(self, authors_str: str) -> List[str]:
        """
        Parse BibTeX author string into list of author names.
        
        BibTeX format: "Last1, First1 and Last2, First2 and ..."
        
        Args:
            authors_str: BibTeX author field value
            
        Returns:
            List of author names in "First Last" format
        """
        if not authors_str:
            return []
        
        authors = []
        
        # Split by " and " (BibTeX convention)
        author_parts = re.split(r'\s+and\s+', authors_str)
        
        for part in author_parts:
            part = part.strip()
            if not part:
                continue
            
            # Handle "Last, First" format
            if ',' in part:
                parts = part.split(',', 1)
                if len(parts) == 2:
                    last = parts[0].strip()
                    first = parts[1].strip()
                    # Convert to "First Last" format
                    name = f"{first} {last}".strip()
                else:
                    name = part
            else:
                # Already in "First Last" format
                name = part
            
            # Clean up the name
            name = re.sub(r'\s+', ' ', name)  # Normalize whitespace
            name = re.sub(r'\{([^}]*)\}', r'\1', name)  # Remove braces
            
            if name:
                authors.append(name)
        
        return authors
    
    def _extract_year_from_eprint(self, eprint: str) -> Optional[int]:
        """
        Extract year from ArXiv eprint ID.
        
        New format (YYMM.NNNNN): First two digits are year
        Old format (cat-name/YYMMNNN): Digits after slash, first two are year
        
        Args:
            eprint: ArXiv eprint ID
            
        Returns:
            Year as integer or None
        """
        if not eprint:
            return None
        
        # New format: 2301.12345
        match = re.match(r'^(\d{2})\d{2}\.\d{4,5}', eprint)
        if match:
            yy = int(match.group(1))
            # ArXiv started in 1991, new format started in 2007
            if yy >= 7:
                return 2000 + yy
            else:
                # Very early 2000s papers (unlikely in new format)
                return 2000 + yy
        
        # Old format: hep-th/9901001
        match = re.match(r'^[a-z-]+/(\d{2})\d+', eprint)
        if match:
            yy = int(match.group(1))
            if yy >= 91:  # ArXiv started in 1991
                return 1900 + yy
            else:
                return 2000 + yy
        
        return None
    
    def get_latest_version_info(self, arxiv_id: str) -> Optional[str]:
        """
        Get the latest version number for an ArXiv paper.
        
        Note: This requires fetching the abstract page, so it's optional.
        For now, we rely on the BibTeX always returning latest version metadata.
        
        Args:
            arxiv_id: ArXiv ID without version
            
        Returns:
            Latest version string (e.g., "v3") or None if couldn't determine
        """
        # The BibTeX endpoint always returns the latest version's metadata,
        # so we don't need to explicitly fetch version info
        return None
    
    def is_arxiv_reference(self, reference: Dict[str, Any]) -> bool:
        """
        Check if a reference is an ArXiv paper.
        
        Args:
            reference: Reference dictionary
            
        Returns:
            True if reference appears to be an ArXiv paper
        """
        arxiv_id, _ = self.extract_arxiv_id(reference)
        return arxiv_id is not None
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a reference using ArXiv's official BibTeX as authoritative source.
        
        This method:
        1. Extracts the ArXiv ID from the reference
        2. Fetches the official BibTeX from ArXiv (always latest version)
        3. Parses the BibTeX to get authoritative metadata
        4. Compares cited metadata against authoritative source
        5. Logs warnings for version mismatches
        
        Args:
            reference: Reference dictionary with title, authors, year, url, etc.
            
        Returns:
            Tuple of (verified_data, errors, url)
            - verified_data: Authoritative paper metadata from ArXiv or None
            - errors: List of error/warning dictionaries
            - url: ArXiv URL for the paper
        """
        errors = []
        
        # Extract ArXiv ID
        arxiv_id, cited_version = self.extract_arxiv_id(reference)
        
        if not arxiv_id:
            logger.debug("ArXivCitationChecker: No ArXiv ID found in reference")
            return None, [], None
        
        logger.debug(f"ArXivCitationChecker: Verifying ArXiv paper {arxiv_id}")
        
        # Fetch authoritative BibTeX
        bibtex_content = self.fetch_bibtex(arxiv_id)
        
        if not bibtex_content:
            logger.debug(f"ArXivCitationChecker: Could not fetch BibTeX for {arxiv_id}")
            return None, [{"error_type": "api_failure", "error_details": f"Could not fetch ArXiv BibTeX for {arxiv_id}"}], None
        
        # Parse BibTeX
        verified_data = self.parse_bibtex(bibtex_content)
        
        if not verified_data:
            logger.debug(f"ArXivCitationChecker: Could not parse BibTeX for {arxiv_id}")
            return None, [], None
        
        # Log version mismatch warning if cited version differs from latest
        if cited_version:
            # ArXiv BibTeX always returns latest version metadata
            # We don't know the actual latest version number without additional API call,
            # but we can warn that a specific version was cited
            errors.append({
                'warning_type': 'version',
                'warning_details': f"Reference cites ArXiv version {cited_version}, verified against latest version metadata",
            })
            logger.debug(f"ArXivCitationChecker: Cited version {cited_version} for {arxiv_id}")
        
        # Compare title
        cited_title = reference.get('title', '').strip()
        authoritative_title = verified_data.get('title', '').strip()
        
        if cited_title and authoritative_title:
            title_similarity = compare_titles_with_latex_cleaning(cited_title, authoritative_title)
            
            if title_similarity < SIMILARITY_THRESHOLD:
                clean_cited_title = strip_latex_commands(cited_title)
                errors.append({
                    'error_type': 'title',
                    'error_details': format_title_mismatch(clean_cited_title, authoritative_title),
                    'ref_title_correct': authoritative_title
                })
        
        # Compare authors
        cited_authors = reference.get('authors', [])
        if cited_authors:
            authoritative_authors = verified_data.get('authors', [])
            authors_match, author_error = compare_authors(cited_authors, authoritative_authors)
            
            if not authors_match:
                correct_author_names = ', '.join([a.get('name', '') for a in authoritative_authors])
                errors.append({
                    'error_type': 'author',
                    'error_details': author_error,
                    'ref_authors_correct': correct_author_names
                })
        
        # Compare year
        cited_year = reference.get('year')
        authoritative_year = verified_data.get('year')
        
        year_warning = validate_year(
            cited_year=cited_year,
            paper_year=authoritative_year,
            use_flexible_validation=True,
            context={'arxiv_match': True}
        )
        if year_warning:
            errors.append(year_warning)
        
        # Build URL
        paper_url = f"https://arxiv.org/abs/{arxiv_id}"
        
        logger.debug(f"ArXivCitationChecker: Verified {arxiv_id} with {len(errors)} errors/warnings")
        
        return verified_data, errors, paper_url
