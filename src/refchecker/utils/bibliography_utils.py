#!/usr/bin/env python3
"""
Bibliography extraction and parsing utilities.

This module provides utilities for extracting and parsing bibliographies from
academic papers in various formats (LaTeX, BibTeX, PDF text, etc.).
"""

import re
import logging
import os

logger = logging.getLogger(__name__)


def extract_text_from_latex(latex_file_path):
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
            logger.error(f"Failed to read LaTeX file {latex_file_path}: {e}")
            return None
    except Exception as e:
        logger.error(f"Failed to read LaTeX file {latex_file_path}: {e}")
        return None


def find_bibliography_section(text):
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
    ]
    
    bibliography_start = None
    matched_pattern = None
    
    for pattern in section_patterns:
        matches = re.search(pattern, text, re.MULTILINE)
        if matches:
            bibliography_start = matches.end()
            matched_pattern = pattern
            logger.debug(f"Bibliography section found using pattern: {pattern}")
            break
    
    if bibliography_start is None:
        logger.debug("No bibliography section header found, trying end-of-document approach")
        # Try to find bibliography at the end of the document without explicit headers
        lines = text.split('\n')
        for i in range(len(lines) - 1, max(0, len(lines) - 100), -1):  # Check last 100 lines
            line = lines[i].strip()
            if re.match(r'^\[\d+\]', line) or re.match(r'^\d+\.', line):
                # Found what looks like reference entries
                bibliography_start = text.rfind('\n'.join(lines[i:]))
                logger.debug(f"Bibliography section found at end of document starting with: {line[:50]}")
                break
    
    if bibliography_start is not None:
        bibliography_text = text[bibliography_start:].strip()
        logger.debug(f"Bibliography text length: {len(bibliography_text)}")
        
        # Optional: Try to find the end of the bibliography section
        # This is challenging because it might go to the end of the document
        # or be followed by appendices, acknowledgments, etc.
        
        return bibliography_text
    
    logger.debug("Bibliography section not found")
    return None


def parse_references(bibliography_text):
    """
    Parse references from bibliography text using multiple parsing strategies.
    
    Args:
        bibliography_text: String containing bibliography content
        
    Returns:
        List of parsed reference dictionaries
    """
    if not bibliography_text:
        logger.warning("No bibliography text provided to parse_references")
        return []
    
    # Try different parsing strategies in order of preference
    parsing_strategies = [
        ('BibTeX', _parse_bibtex_references),
        ('biblatex', _parse_biblatex_references),
        ('ACM/natbib', _parse_standard_acm_natbib_references),
        ('regex-based', _parse_references_regex)
    ]
    
    for strategy_name, parse_func in parsing_strategies:
        try:
            logger.debug(f"Attempting {strategy_name} parsing")
            references = parse_func(bibliography_text)
            if references and len(references) > 0:
                logger.info(f"Successfully parsed {len(references)} references using {strategy_name} format")
                return references
            else:
                logger.debug(f"{strategy_name} parsing returned no references")
        except Exception as e:
            logger.debug(f"{strategy_name} parsing failed: {e}")
            continue
    
    logger.warning("All parsing strategies failed to extract references")
    return []


def _parse_bibtex_references(bibliography_text):
    """
    Parse BibTeX formatted references like @inproceedings{...}, @article{...}, etc.
    
    Args:
        bibliography_text: String containing BibTeX entries
        
    Returns:
        List of reference dictionaries
    """
    from refchecker.utils.bibtex_parser import parse_bibtex_references
    return parse_bibtex_references(bibliography_text)


def _parse_biblatex_references(bibliography_text):
    """
    Parse biblatex formatted references like [1] Author. "Title". In: Venue. Year.
    
    Args:
        bibliography_text: String containing biblatex .bbl entries
        
    Returns:
        List of reference dictionaries
    """
    from refchecker.utils.text_utils import extract_latex_references
    return extract_latex_references(bibliography_text)


def _parse_standard_acm_natbib_references(bibliography_text):
    """
    Parse references using regex for standard ACM/natbib format (both ACM Reference Format and simple natbib)
    """
    from refchecker.utils.text_utils import detect_standard_acm_natbib_format
    
    references = []
    
    # Check if this is standard ACM natbib format
    format_info = detect_standard_acm_natbib_format(bibliography_text)
    if format_info['is_acm_natbib']:
        logger.debug("Detected standard ACM natbib format")
        
        # Split by reference entries
        ref_pattern = r'\[(\d+)\]\s*'
        entries = re.split(ref_pattern, bibliography_text)[1:]  # Skip first empty element
        
        for i in range(0, len(entries), 2):
            if i + 1 < len(entries):
                ref_num = entries[i]
                ref_content = entries[i + 1].strip()
                
                try:
                    reference = _parse_simple_natbib_format(int(ref_num), ref_content, f"[{ref_num}]")
                    if reference:
                        references.append(reference)
                        logger.debug(f"Parsed reference {ref_num}: {reference.get('title', 'No title')[:50]}...")
                except Exception as e:
                    logger.debug(f"Error parsing reference {ref_num}: {e}")
                    continue
        
        logger.debug(f"ACM natbib parsing extracted {len(references)} references")
    
    return references


def _parse_simple_natbib_format(ref_num, content, label):
    """
    Parse a simple natbib format reference entry.
    
    Args:
        ref_num: Reference number
        content: Reference content text
        label: Reference label (e.g., "[1]")
        
    Returns:
        Dictionary containing parsed reference information
    """
    from refchecker.utils.text_utils import extract_url_from_reference, extract_year_from_reference
    
    # Basic parsing - this could be enhanced with more sophisticated NLP
    reference = {
        'raw_text': content,
        'label': label,
        'type': 'unknown'
    }
    
    # Try to extract basic information
    # This is a simplified parser - real parsing would be much more complex
    
    # Look for URL
    url = extract_url_from_reference(content)
    if url:
        reference['url'] = url
    
    # Look for year
    year = extract_year_from_reference(content)
    if year:
        reference['year'] = year
    
    # Try to identify the type based on content
    content_lower = content.lower()
    if 'proceedings' in content_lower or 'conference' in content_lower:
        reference['type'] = 'inproceedings'
    elif 'journal' in content_lower or 'trans.' in content_lower:
        reference['type'] = 'article'
    elif 'arxiv' in content_lower:
        reference['type'] = 'misc'
        reference['note'] = 'arXiv preprint'
    
    return reference


def _parse_references_regex(bibliography_text):
    """
    Parse references using regex-based approach (original implementation)
    """
    references = []
    
    # Split bibliography into individual references
    # Look for patterns like [1], [2], etc.
    ref_pattern = r'\[(\d+)\](.*?)(?=\[\d+\]|$)'
    matches = re.findall(ref_pattern, bibliography_text, re.DOTALL)
    
    for ref_num, ref_content in matches:
        ref_content = ref_content.strip()
        if not ref_content:
            continue
            
        reference = {
            'raw_text': ref_content,
            'label': f"[{ref_num}]",
            'type': 'unknown'
        }
        
        # Basic information extraction
        from refchecker.utils.text_utils import extract_url_from_reference, extract_year_from_reference
        
        url = extract_url_from_reference(ref_content)
        if url:
            reference['url'] = url
            
        year = extract_year_from_reference(ref_content)
        if year:
            reference['year'] = year
        
        references.append(reference)
    
    return references


def _is_bibtex_surname_given_format(surname_part, given_part):
    """
    Check if this appears to be a BibTeX "Surname, Given" format.
    
    Args:
        surname_part: The part before the comma
        given_part: The part after the comma
        
    Returns:
        Boolean indicating if this looks like BibTeX name format
    """
    # Simple heuristics to detect BibTeX format
    if not surname_part or not given_part:
        return False
        
    # Check if surname looks like a surname (capitalized, not too long)
    if not re.match(r'^[A-Z][a-zA-Z\s\-\']+$', surname_part.strip()):
        return False
        
    # Check if given part looks like given names (often abbreviated)
    given_clean = given_part.strip()
    if re.match(r'^[A-Z](\.\s*[A-Z]\.?)*$', given_clean):  # Like "J. R." or "M. K."
        return True
    if re.match(r'^[A-Z][a-z]+(\s+[A-Z][a-z]*)*$', given_clean):  # Like "John Robert"
        return True
        
    return False