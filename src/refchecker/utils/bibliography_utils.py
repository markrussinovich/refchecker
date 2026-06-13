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
        ('Vancouver/NLM', _parse_vancouver_style_references),
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


_VANCOUVER_HEAD = re.compile(
    # First author of a Vancouver/NLM entry: Surname (1-3 letter initials),
    # optionally followed by ", Surname BC" repeats. Captures the start of
    # each candidate reference in an unnumbered medical-style bibliography.
    r"(?:^|\n)\s*"
    r"(?P<head>[A-Z][A-Za-zÀ-ſ'\-]+\s+[A-ZÀ-ÝŁŃÓŚŹŻČĎĚŇŘŠŤÚŮÝŽ]{1,4}(?:-[A-ZÀ-ÝŁŃÓŚŹŻČĎĚŇŘŠŤÚŮÝŽ])?"
    r"(?:,\s+[A-Z][A-Za-zÀ-ſ'\-]+\s+[A-ZÀ-ÝŁŃÓŚŹŻČĎĚŇŘŠŤÚŮÝŽ]{1,4}(?:-[A-ZÀ-ÝŁŃÓŚŹŻČĎĚŇŘŠŤÚŮÝŽ])?){0,15}"
    r")"
    r"(?=[\.,;])"
)
_YEAR_IN_ENTRY = re.compile(r'(?<!\d)(19|20)\d{2}(?!\d)')


def _parse_vancouver_style_references(bibliography_text):
    """
    Parse unnumbered Vancouver / NLM-style references that lack
    bracketed labels — entries like

        Wang Y, Cheng C, ... Eur Radiol. 2014;24(8):1777-1784.

    are missed by the ACM/natbib and regex strategies because both
    require a leading "[N]". We locate each "Surname AB," head and
    take the text up to the next head as one entry.
    """
    if not bibliography_text or not bibliography_text.strip():
        return []

    text = bibliography_text.replace('\r\n', '\n')
    starts = [m.start('head') for m in _VANCOUVER_HEAD.finditer(text)]
    # Need at least 2 plausible heads — a single match could just be a
    # body sentence inside a different bibliography style.
    if len(starts) < 2:
        return []

    chunks = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        chunk = text[start:end].strip().rstrip(',')
        chunks.append(chunk)

    # Validate that this really looks like a Vancouver bibliography: at
    # least 60% of chunks must contain a year, otherwise we're probably
    # snagging body prose and the fallback strategies should take over.
    with_year = sum(1 for c in chunks if _YEAR_IN_ENTRY.search(c))
    if len(chunks) == 0 or with_year / len(chunks) < 0.6:
        return []

    from refchecker.utils.text_utils import extract_url_from_reference, extract_year_from_reference
    # Filter junk first so the resulting labels are a contiguous 1..N
    # rather than skipping numbers around any dropped <30-char chunks.
    valid_chunks = [c for c in chunks if len(c) >= 30]
    references = []
    for idx, chunk in enumerate(valid_chunks, start=1):
        reference = {
            'raw_text': chunk,
            'label': f"[{idx}]",
            'type': 'article',
        }
        url = extract_url_from_reference(chunk)
        if url:
            reference['url'] = url
        year = extract_year_from_reference(chunk)
        if year:
            reference['year'] = year
        references.append(reference)
    logger.debug(f"Vancouver/NLM parsing extracted {len(references)} references")
    return references


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