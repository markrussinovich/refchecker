#!/usr/bin/env python3
"""
PDF Paper Checker - Validates citations by extracting and analyzing PDF content
"""

import re
import io
import logging
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urlparse

import requests
import pdfplumber
from pypdf import PdfReader
from fuzzywuzzy import fuzz
from bs4 import BeautifulSoup

from refchecker.utils.text_utils import normalize_text, calculate_title_similarity

logger = logging.getLogger(__name__)


class PDFPaperChecker:
    """
    Checker that downloads and analyzes PDF documents to validate citations
    """
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def can_check_reference(self, reference: Dict[str, Any]) -> bool:
        """
        Check if this reference can be validated by PDF analysis
        
        Args:
            reference: Reference dictionary containing url and other metadata
            
        Returns:
            True if reference has URL that likely points to a PDF
        """
        url = reference.get('url', '').strip()
        if not url:
            return False
        
        # Check if URL ends with .pdf
        if url.lower().endswith('.pdf'):
            return True
        
        # Check if URL path suggests PDF content
        pdf_indicators = ['/pdf/', '/document/', '/download/', '/file/', '/resource/']
        if any(indicator in url.lower() for indicator in pdf_indicators):
            return True
        
        # Check if URL is from domains that commonly serve PDFs directly
        domain = urlparse(url).netloc.lower()
        pdf_domains = [
            '.gov', '.edu', '.org',  # Common institutional domains
            'researchgate.net', 'academia.edu', 'arxiv.org',  # Academic platforms
            'oecd.org', 'who.int', 'unesco.org',  # International organizations
            'aecea.ca'  # Specific domain from the user's example
        ]
        
        if any(domain.endswith(pdf_domain) or pdf_domain in domain for pdf_domain in pdf_domains):
            return True
        
        return False
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a reference by downloading and analyzing PDF content
        
        Args:
            reference: Reference dictionary with title, authors, year, url, etc.
            
        Returns:
            Tuple of (verified_data, errors, url) where:
            - verified_data: Dict with verified data if PDF validates citation, None otherwise
            - errors: List of error dictionaries
            - url: The URL that was checked
        """
        logger.debug(f"Verifying PDF reference: {reference.get('title', 'Untitled')}")
        
        url = reference.get('url', '').strip()
        if not url:
            return None, [{"error_type": "unverified", "error_details": "no URL provided"}], None
        
        try:
            # First try to download directly as PDF
            pdf_content = self._download_pdf(url)
            
            # If direct download fails, try to find PDF links in the page
            if not pdf_content:
                pdf_url = self._find_pdf_url_in_page(url)
                if pdf_url:
                    logger.debug(f"Found PDF link in page: {pdf_url}")
                    pdf_content = self._download_pdf(pdf_url)
                    url = pdf_url  # Update URL to the actual PDF URL
            
            if not pdf_content:
                return None, [{"error_type": "unverified", "error_details": "could not download PDF content"}], url
            
            # Extract text and metadata from PDF
            pdf_data = self._extract_pdf_data(pdf_content)
            if not pdf_data:
                return None, [{"error_type": "unverified", "error_details": "could not extract PDF content"}], url
            
            # Validate citation against PDF content
            is_valid, errors = self._validate_citation(reference, pdf_data)
            
            if is_valid:
                # Create verified data preserving original venue if provided
                venue = reference.get('journal') or reference.get('venue') or reference.get('booktitle') or 'PDF Document'
                
                verified_data = {
                    'title': reference.get('title', ''),
                    'authors': reference.get('authors', []),
                    'year': reference.get('year'),
                    'venue': venue,
                    'url': url,
                    'pdf_metadata': {
                        'extracted_title': pdf_data.get('title'),
                        'extracted_authors': pdf_data.get('authors'),
                        'extracted_text_preview': pdf_data.get('text', '')[:200] + '...' if pdf_data.get('text') else '',
                        'pdf_pages': pdf_data.get('page_count'),
                        'extraction_method': pdf_data.get('extraction_method')
                    }
                }
                logger.debug(f"PDF reference verified: {url}")
                return verified_data, errors, url
            else:
                return None, errors, url
                
        except Exception as e:
            logger.error(f"Error verifying PDF reference {url}: {e}")
            return None, [{"error_type": "unverified", "error_details": "PDF processing error"}], url
    
    def _download_pdf(self, url: str, timeout: int = 30) -> Optional[bytes]:
        """
        Download PDF content from URL
        
        Args:
            url: URL to download from
            timeout: Request timeout in seconds
            
        Returns:
            PDF content as bytes, or None if download failed
        """
        try:
            logger.debug(f"Downloading PDF from: {url}")
            
            response = self.session.get(url, timeout=timeout, stream=True)
            response.raise_for_status()
            
            # Check if content is actually a PDF
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' not in content_type and not url.lower().endswith('.pdf'):
                # Sometimes PDFs are served with generic content types, so we'll try anyway
                logger.debug(f"Content-Type '{content_type}' doesn't indicate PDF, but proceeding anyway")
            
            # Download content
            content = response.content
            
            # Basic PDF validation - check for PDF header
            if content.startswith(b'%PDF-'):
                logger.debug(f"Successfully downloaded PDF ({len(content)} bytes)")
                return content
            else:
                logger.debug("Downloaded content doesn't appear to be a valid PDF")
                return None
                
        except Exception as e:
            logger.error(f"Failed to download PDF from {url}: {e}")
            return None
    
    def _find_pdf_url_in_page(self, url: str) -> Optional[str]:
        """
        Look for PDF download links in a web page
        
        Args:
            url: URL of the web page to search
            
        Returns:
            URL of PDF document if found, None otherwise
        """
        try:
            logger.debug(f"Searching for PDF links in page: {url}")
            
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            # Check if the response itself is a PDF (after redirects)
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' in content_type or response.content.startswith(b'%PDF-'):
                logger.debug("Page redirected directly to PDF")
                return response.url
            
            # Parse HTML to look for PDF links
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for links that might be PDFs
            pdf_links = []
            
            # Find all links
            for link in soup.find_all('a', href=True):
                href = link.get('href')
                link_text = link.get_text().lower().strip()
                
                # Check if link ends with .pdf
                if href and href.lower().endswith('.pdf'):
                    pdf_links.append(href)
                    continue
                
                # Check if link text suggests PDF
                if any(indicator in link_text for indicator in ['pdf', 'download', 'document', 'report', 'policy']):
                    pdf_links.append(href)
                    continue
                
                # Check if link has PDF-related attributes
                if link.get('type', '').lower() == 'application/pdf':
                    pdf_links.append(href)
                    continue
            
            # Look for PDF links in other elements
            for element in soup.find_all(attrs={'href': True}):
                href = element.get('href')
                if href and href.lower().endswith('.pdf'):
                    pdf_links.append(href)
            
            # Convert relative URLs to absolute
            from urllib.parse import urljoin
            absolute_pdf_links = []
            for link in pdf_links:
                if link:
                    absolute_url = urljoin(url, link)
                    absolute_pdf_links.append(absolute_url)
            
            # Remove duplicates
            absolute_pdf_links = list(set(absolute_pdf_links))
            
            if absolute_pdf_links:
                logger.debug(f"Found {len(absolute_pdf_links)} potential PDF links")
                # Return the first PDF link found
                return absolute_pdf_links[0]
            
            logger.debug("No PDF links found in page")
            return None
            
        except Exception as e:
            logger.error(f"Error searching for PDF links in {url}: {e}")
            return None
    
    def _extract_pdf_data(self, pdf_content: bytes) -> Optional[Dict[str, Any]]:
        """
        Extract text and metadata from PDF content
        
        Args:
            pdf_content: PDF file content as bytes
            
        Returns:
            Dictionary with extracted data including text, title, authors, etc.
        """
        pdf_data = {
            'text': '',
            'title': '',
            'authors': [],
            'page_count': 0,
            'extraction_method': 'none'
        }
        
        # Try multiple extraction methods
        try:
            # Method 1: Try pdfplumber (usually better for text extraction)
            pdf_data = self._extract_with_pdfplumber(pdf_content, pdf_data)
            if pdf_data['text']:
                pdf_data['extraction_method'] = 'pdfplumber'
                return pdf_data
        except Exception as e:
            logger.debug(f"pdfplumber extraction failed: {e}")
        
        try:
            # Method 2: Try pypdf (fallback)
            pdf_data = self._extract_with_pypdf(pdf_content, pdf_data)
            if pdf_data['text']:
                pdf_data['extraction_method'] = 'pypdf'
                return pdf_data
        except Exception as e:
            logger.debug(f"pypdf extraction failed: {e}")
        
        logger.debug("All PDF extraction methods failed")
        return None
    
    def _extract_with_pdfplumber(self, pdf_content: bytes, pdf_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract PDF data using pdfplumber"""
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            pdf_data['page_count'] = len(pdf.pages)
            
            # Extract text from first few pages (usually contains title/author info)
            text_parts = []
            for i, page in enumerate(pdf.pages[:5]):  # First 5 pages should be enough
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            
            pdf_data['text'] = '\n'.join(text_parts)
            
            # Try to extract title and author from first page
            if pdf.pages:
                first_page_text = pdf.pages[0].extract_text() or ''
                pdf_data['title'], pdf_data['authors'] = self._parse_title_and_authors(first_page_text)
        
        return pdf_data
    
    def _extract_with_pypdf(self, pdf_content: bytes, pdf_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract PDF data using pypdf"""
        reader = PdfReader(io.BytesIO(pdf_content))
        pdf_data['page_count'] = len(reader.pages)
        
        # Extract metadata
        if reader.metadata:
            if '/Title' in reader.metadata:
                pdf_data['title'] = str(reader.metadata['/Title'])
            if '/Author' in reader.metadata:
                pdf_data['authors'] = [str(reader.metadata['/Author'])]
        
        # Extract text from first few pages
        text_parts = []
        for i, page in enumerate(reader.pages[:5]):  # First 5 pages
            try:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            except Exception as e:
                logger.debug(f"Failed to extract text from page {i}: {e}")
                continue
        
        pdf_data['text'] = '\n'.join(text_parts)
        
        # If no metadata title/author, try to parse from text
        if not pdf_data['title'] and text_parts:
            title, authors = self._parse_title_and_authors(text_parts[0])
            if title and not pdf_data['title']:
                pdf_data['title'] = title
            if authors and not pdf_data['authors']:
                pdf_data['authors'] = authors
        
        return pdf_data
    
    def _parse_title_and_authors(self, text: str) -> Tuple[str, List[str]]:
        """
        Parse title and authors from PDF text
        
        Args:
            text: Text from first page of PDF
            
        Returns:
            Tuple of (title, authors_list)
        """
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        if not lines:
            return '', []
        
        # The title is often the first meaningful line (after removing headers/footers)
        title = ''
        authors = []
        
        # Look for the title - usually first non-header line
        for i, line in enumerate(lines):
            # Skip obvious header/footer content
            if len(line) < 10 or any(skip in line.lower() for skip in ['page', 'doi:', 'http', 'www.', '@']):
                continue
            
            # Title is usually longer and on its own line
            if len(line) > 20 and not any(sep in line for sep in [',', ';']) and not line.endswith('.'):
                title = line
                
                # Authors often follow the title - look for patterns
                for j in range(i + 1, min(i + 5, len(lines))):
                    author_line = lines[j]
                    
                    # Author lines often contain commas, "and", or institutional affiliations
                    if any(indicator in author_line.lower() for indicator in [',', ' and ', 'university', 'college', 'institute']):
                        # Clean up author line
                        author_text = re.sub(r'[0-9*†‡§¶#]', '', author_line)  # Remove superscript markers
                        if ',' in author_text:
                            authors.extend([name.strip() for name in author_text.split(',') if name.strip()])
                        else:
                            authors.append(author_text.strip())
                        break
                break
        
        return title, authors
    
    def _validate_citation(self, reference: Dict[str, Any], pdf_data: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Validate citation against extracted PDF data
        
        Args:
            reference: The citation being checked
            pdf_data: Extracted data from PDF
            
        Returns:
            Tuple of (is_valid, errors_list)
        """
        errors = []
        
        # Check title match
        cited_title = reference.get('title', '').strip()
        extracted_title = pdf_data.get('title', '').strip()
        pdf_text = pdf_data.get('text', '').lower()
        
        title_match = False
        
        if cited_title and extracted_title:
            # Compare titles directly
            similarity = calculate_title_similarity(cited_title, extracted_title)
            if similarity > 0.8:  # 80% similarity threshold
                title_match = True
        
        if not title_match and cited_title and pdf_text:
            # Check if cited title appears in PDF text
            cited_title_normalized = normalize_text(cited_title)
            if cited_title_normalized.lower() in pdf_text:
                title_match = True
        
        if not title_match:
            errors.append({
                "error_type": "unverified",
                "error_details": "title not found in PDF content"
            })
        
        # Check author match (more lenient since PDF author extraction is difficult)
        cited_authors = reference.get('authors', [])
        extracted_authors = pdf_data.get('authors', [])
        
        author_match = False
        
        if cited_authors and extracted_authors:
            # Check if any cited author appears in extracted authors
            for cited_author in cited_authors:
                for extracted_author in extracted_authors:
                    if self._authors_match(cited_author, extracted_author):
                        author_match = True
                        break
                if author_match:
                    break
        
        if not author_match and cited_authors and pdf_text:
            # Check if any cited author appears in PDF text
            for cited_author in cited_authors:
                author_normalized = normalize_text(cited_author)
                if author_normalized.lower() in pdf_text:
                    author_match = True
                    break
        
        # For PDF validation, we're more lenient with author matching since extraction is unreliable
        if not author_match and cited_authors:
            errors.append({
                "warning_type": "author",
                "warning_details": "authors not clearly identified in PDF content"
            })
        
        # A reference is valid if we found the title (author matching is optional due to extraction difficulties)
        is_valid = title_match
        
        return is_valid, errors
    
    def _authors_match(self, author1: str, author2: str) -> bool:
        """Check if two author names likely refer to the same person"""
        author1_norm = normalize_text(author1).lower()
        author2_norm = normalize_text(author2).lower()
        
        # Exact match
        if author1_norm == author2_norm:
            return True
        
        # Check similarity
        similarity = fuzz.ratio(author1_norm, author2_norm)
        if similarity > 85:  # 85% similarity threshold
            return True
        
        # Check if one name is contained in the other (handles "J. Smith" vs "John Smith")
        words1 = set(author1_norm.split())
        words2 = set(author2_norm.split())
        
        if words1.intersection(words2):
            return True
        
        return False