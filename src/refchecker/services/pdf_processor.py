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