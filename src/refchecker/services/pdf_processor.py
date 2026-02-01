#!/usr/bin/env python3
"""
PDF Processing Service for ArXiv Reference Checker
Extracted from core.refchecker to improve modularity
"""

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class Paper:
    """Represents a paper with metadata"""
    title: str
    authors: list
    abstract: str = ""
    year: Optional[int] = None
    venue: str = ""
    url: str = ""
    doi: str = ""
    arxiv_id: str = ""
    pdf_path: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert paper to dictionary format"""
        return {
            'title': self.title,
            'authors': self.authors,
            'abstract': self.abstract,
            'year': self.year,
            'venue': self.venue,
            'url': self.url,
            'doi': self.doi,
            'arxiv_id': self.arxiv_id,
            'pdf_path': self.pdf_path
        }

class PDFProcessor:
    """Service for processing PDF files and extracting text"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.cache = {}
        
    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Extract text from PDF file
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Extracted text content
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        # Check cache first
        if pdf_path in self.cache:
            logger.debug(f"Using cached text for {pdf_path}")
            return self.cache[pdf_path]
        
        try:
            import pypdf
            
            with open(pdf_path, 'rb') as file:
                pdf_reader = pypdf.PdfReader(file)
                text = ""
                failed_pages = []
                
                for page_num in range(len(pdf_reader.pages)):
                    try:
                        page = pdf_reader.pages[page_num]
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                    except TypeError as e:
                        # Handle pypdf errors like "NumberObject is not iterable"
                        # which can occur with malformed PDF pages
                        failed_pages.append(page_num + 1)  # 1-indexed for logging
                        logger.warning(f"Skipping page {page_num + 1} due to PDF parsing error: {e}")
                        continue
                    except Exception as e:
                        failed_pages.append(page_num + 1)
                        logger.warning(f"Error extracting text from page {page_num + 1}: {e}")
                        continue
                
                if failed_pages:
                    logger.warning(f"Failed to extract text from {len(failed_pages)} pages: {failed_pages[:10]}{'...' if len(failed_pages) > 10 else ''}")
                
                if not text.strip():
                    raise ValueError(f"No text could be extracted from any pages of {pdf_path}")
                
                # Cache the result
                self.cache[pdf_path] = text
                logger.debug(f"Extracted {len(text)} characters from {pdf_path}")
                return text
                
        except ImportError:
            logger.error("pypdf not installed. Install with: pip install pypdf")
            raise
        except Exception as e:
            logger.error(f"Error extracting text from PDF {pdf_path}: {e}")
            raise
    
    def create_local_file_paper(self, file_path: str, metadata: Optional[Dict[str, Any]] = None) -> Paper:
        """
        Create a Paper object from a local file
        
        Args:
            file_path: Path to the file
            metadata: Optional metadata dictionary
            
        Returns:
            Paper object
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Extract text if it's a PDF
        text_content = ""
        if file_path.lower().endswith('.pdf'):
            try:
                text_content = self.extract_text_from_pdf(file_path)
            except Exception as e:
                logger.warning(f"Could not extract text from {file_path}: {e}")
        
        # Use metadata if provided, otherwise extract from filename
        if metadata:
            title = metadata.get('title', os.path.basename(file_path))
            authors = metadata.get('authors', [])
            abstract = metadata.get('abstract', '')
            year = metadata.get('year')
            venue = metadata.get('venue', '')
            url = metadata.get('url', '')
            doi = metadata.get('doi', '')
            arxiv_id = metadata.get('arxiv_id', '')
        else:
            # Basic extraction from filename
            title = os.path.splitext(os.path.basename(file_path))[0]
            authors = []
            abstract = text_content[:500] if text_content else ""  # First 500 chars as abstract
            year = None
            venue = ""
            url = ""
            doi = ""
            arxiv_id = ""
        
        return Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            year=year,
            venue=venue,
            url=url,
            doi=doi,
            arxiv_id=arxiv_id,
            pdf_path=file_path
        )
    
    def extract_bibliography_from_text(self, text: str) -> str:
        """
        Extract bibliography section from text
        
        Args:
            text: Full text content
            
        Returns:
            Bibliography section text
        """
        if not text:
            return ""
        
        # Common bibliography section headers
        bib_headers = [
            r'\n\s*REFERENCES\s*\n',
            r'\n\s*References\s*\n',
            r'\n\s*BIBLIOGRAPHY\s*\n',
            r'\n\s*Bibliography\s*\n',
            r'\n\s*WORKS CITED\s*\n',
            r'\n\s*Works Cited\s*\n'
        ]
        
        import re
        
        # Find bibliography section
        for header in bib_headers:
            match = re.search(header, text, re.IGNORECASE)
            if match:
                # Extract from bibliography header
                bib_start = match.end()
                full_bib_text = text[bib_start:].strip()
                
                # Find the end of the bibliography section by looking for common section headers
                # that typically follow references
                end_markers = [
                    r'\n\s*APPENDIX\s*[A-Z]?\s*\n',
                    r'\n\s*Appendix\s*[A-Z]?\s*\n',
                    r'\n\s*[A-Z]\s+[A-Z]{2,}.*\n',  # Pattern like "A LRE Dataset", "B ADDITIONAL RESULTS"
                    r'\n\s*[A-Z]\.\d+\s+.*\n',  # Pattern like "A.1 Dataset Details"
                    r'\nTable\s+\d+:.*\n[A-Z]\s+[A-Z]',  # Table followed by appendix section like "Table 7: ...\nA LRE"
                    r'\n\s*SUPPLEMENTARY\s+MATERIAL\s*\n',
                    r'\n\s*Supplementary\s+Material\s*\n',  
                    r'\n\s*SUPPLEMENTAL\s+MATERIAL\s*\n',
                    r'\n\s*Supplemental\s+Material\s*\n',
                    r'\n\s*ACKNOWLEDGMENTS?\s*\n',
                    r'\n\s*Acknowledgments?\s*\n',
                    r'\n\s*AUTHOR\s+CONTRIBUTIONS?\s*\n',
                    r'\n\s*Author\s+Contributions?\s*\n',
                    r'\n\s*FUNDING\s*\n',
                    r'\n\s*Funding\s*\n',
                    r'\n\s*ETHICS\s+STATEMENT\s*\n',
                    r'\n\s*Ethics\s+Statement\s*\n',
                    r'\n\s*CONFLICT\s+OF\s+INTEREST\s*\n',
                    r'\n\s*Conflict\s+of\s+Interest\s*\n',
                    r'\n\s*DATA\s+AVAILABILITY\s*\n',
                    r'\n\s*Data\s+Availability\s*\n'
                ]
                
                bib_text = full_bib_text
                bib_end = len(full_bib_text)
                
                # Look for section markers that indicate end of bibliography
                for end_marker in end_markers:
                    end_match = re.search(end_marker, full_bib_text, re.IGNORECASE)
                    if end_match and end_match.start() < bib_end:
                        bib_end = end_match.start()
                
                # If we found an end marker, truncate there
                if bib_end < len(full_bib_text):
                    bib_text = full_bib_text[:bib_end].strip()
                    logger.debug(f"Bibliography section truncated at position {bib_end}")
                
                # Also try to detect bibliography end by finding the last numbered reference
                # Look for the highest numbered reference in the text
                ref_numbers = re.findall(r'\[(\d+)\]', bib_text)
                if ref_numbers:
                    max_ref_num = max(int(num) for num in ref_numbers)
                    logger.debug(f"Found references up to [{max_ref_num}]")
                    
                    # Look for the end of the last numbered reference
                    last_ref_pattern = rf'\[{max_ref_num}\][^[]*?(?=\n\s*[A-Z]{{2,}}|\n\s*\w+\s*\n\s*[A-Z]|\Z)'
                    last_ref_match = re.search(last_ref_pattern, bib_text, re.DOTALL)
                    if last_ref_match:
                        potential_end = last_ref_match.end()
                        # Only use this if it's before our section marker end
                        if potential_end < bib_end:
                            bib_text = bib_text[:potential_end].strip()
                            logger.debug(f"Bibliography truncated after reference [{max_ref_num}]")
                
                # Final fallback: limit to reasonable length
                if len(bib_text) > 50000:  # Limit to ~50KB
                    bib_text = bib_text[:50000]
                    logger.debug("Bibliography section truncated to 50KB limit")
                
                logger.debug(f"Found bibliography section: {len(bib_text)} characters")
                return bib_text
        
        logger.warning("No bibliography section found in text")
        return ""
    
    def clear_cache(self):
        """Clear the text extraction cache"""
        self.cache.clear()
        logger.debug("PDF text cache cleared")
    
    def extract_title_from_pdf(self, pdf_path: str) -> Optional[str]:
        """
        Extract the title from a PDF file.
        
        First tries PDF metadata, then falls back to heuristic extraction
        from the first page text.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Extracted title or None if not found
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        try:
            import pypdf
            
            with open(pdf_path, 'rb') as file:
                pdf_reader = pypdf.PdfReader(file)
                
                # Try PDF metadata first
                metadata = pdf_reader.metadata
                if metadata:
                    title = metadata.get('/Title')
                    if title and isinstance(title, str) and len(title.strip()) > 3:
                        # Clean up the title
                        title = title.strip()
                        # Skip if it looks like a filename
                        if not title.endswith(('.pdf', '.tex', '.dvi')) and title.lower() != 'untitled':
                            logger.debug(f"Found title in PDF metadata: {title}")
                            return title
                
                # Fall back to extracting from first page text
                if len(pdf_reader.pages) > 0:
                    try:
                        first_page_text = pdf_reader.pages[0].extract_text()
                        if first_page_text:
                            title = self._extract_title_from_text(first_page_text)
                            if title:
                                logger.debug(f"Extracted title from first page: {title}")
                                return title
                    except Exception as e:
                        logger.warning(f"Error extracting title from first page: {e}")
                
                return None
                
        except ImportError:
            logger.error("pypdf not installed. Install with: pip install pypdf")
            raise
        except Exception as e:
            logger.warning(f"Error extracting title from PDF {pdf_path}: {e}")
            return None
    
    def _extract_title_from_text(self, text: str) -> Optional[str]:
        """
        Heuristically extract paper title from text (typically first page).
        
        Academic papers typically have the title as one of the first prominent
        text blocks, often followed by author names.
        
        Args:
            text: Text from first page of PDF
            
        Returns:
            Extracted title or None
        """
        if not text:
            return None
        
        import re
        
        # Split into lines and clean
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        if not lines:
            return None
        
        # Skip common header elements (conference names, page numbers, etc.)
        header_patterns = [
            r'^(proceedings|conference|journal|workshop|symposium)',
            r'^(vol\.|volume|issue|no\.|number)',
            r'^\d{1,4}\s*$',  # Page numbers
            r'^(preprint|arxiv|draft)',
            r'^(ieee|acm|springer|elsevier)',
            r'^[a-z]+\s+\d{4}$',  # "January 2024" etc
        ]
        
        # Author indicators that typically follow the title
        author_indicators = [
            r'^[A-Z][a-z]+\s+[A-Z][a-z]+(\s*,|\s+and\s+)',  # "John Smith," or "John Smith and"
            r'^[A-Z]\.\s*[A-Z][a-z]+',  # "J. Smith"
            r'^[\w\s,]+@[\w\.-]+',  # Email addresses
            r'^(university|department|institute|school|college)',
            r'^\d+\s+[A-Z]',  # Addresses like "123 Main St"
        ]
        
        # Find potential title lines
        title_candidates = []
        for i, line in enumerate(lines[:15]):  # Only look at first 15 lines
            # Skip empty or very short lines
            if len(line) < 10:
                continue
            
            # Skip lines matching header patterns
            is_header = any(re.search(pat, line, re.IGNORECASE) for pat in header_patterns)
            if is_header:
                continue
            
            # Check if this looks like the start of author section
            is_author_section = any(re.search(pat, line, re.IGNORECASE) for pat in author_indicators)
            if is_author_section:
                break  # Stop - we've passed the title
            
            # Good candidate: reasonable length, not too long
            if 15 <= len(line) <= 300:
                title_candidates.append(line)
                
                # If next line looks like authors, we found the title
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if any(re.search(pat, next_line, re.IGNORECASE) for pat in author_indicators):
                        break
        
        if not title_candidates:
            return None
        
        # Take the first good candidate, or combine first few if they seem related
        title = title_candidates[0]
        
        # Sometimes titles span multiple lines - check if next line continues
        if len(title_candidates) > 1:
            second = title_candidates[1]
            # If second line is short and starts with lowercase or continues sentence
            if len(second) < 80 and (second[0].islower() or title.endswith(':')):
                title = title + ' ' + second
        
        # Clean up the title
        title = re.sub(r'\s+', ' ', title).strip()
        
        # Remove common artifacts
        title = re.sub(r'^\d+\s*', '', title)  # Leading numbers
        title = re.sub(r'\s*\*+\s*$', '', title)  # Trailing asterisks
        
        # Validate: title should have reasonable characteristics
        if len(title) < 15 or len(title) > 350:
            return None
        
        # Should have some letters (not just numbers/symbols)
        if not re.search(r'[a-zA-Z]{3,}', title):
            return None
        
        return title