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
            import PyPDF2
            
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    text += page.extract_text() + "\n"
                
                # Cache the result
                self.cache[pdf_path] = text
                logger.debug(f"Extracted {len(text)} characters from {pdf_path}")
                return text
                
        except ImportError:
            logger.error("PyPDF2 not installed. Install with: pip install PyPDF2")
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
                # Extract from bibliography header to end of text
                bib_start = match.end()
                bib_text = text[bib_start:].strip()
                
                # Optionally limit to reasonable length
                if len(bib_text) > 50000:  # Limit to ~50KB
                    bib_text = bib_text[:50000]
                
                logger.debug(f"Found bibliography section: {len(bib_text)} characters")
                return bib_text
        
        logger.warning("No bibliography section found in text")
        return ""
    
    def clear_cache(self):
        """Clear the text extraction cache"""
        self.cache.clear()
        logger.debug("PDF text cache cleared")