#!/usr/bin/env python3
"""
BibTeX format parser utility

Handles parsing of standard BibTeX format references like:
@article{key,
  title={Title},
  author={Author Name and Other Author},
  year={2023}
}
"""

import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def detect_bibtex_format(text: str) -> bool:
    """
    Detect if text contains BibTeX format references
    
    Args:
        text: Text to analyze
        
    Returns:
        True if BibTeX format detected, False otherwise
    """
    # Look for BibTeX entry patterns
    return bool(re.search(r'@\w+\s*\{', text))


def parse_bibtex_entries(bib_content: str) -> List[Dict[str, Any]]:
    """
    Parse BibTeX entries from text content
    
    Args:
        bib_content: String containing BibTeX entries
        
    Returns:
        List of dictionaries, each containing a parsed BibTeX entry
    """
    if not bib_content:
        return []
    
    entries = []
    
    # Pattern to match BibTeX entries (excluding @string, @comment, @preamble)
    # First find entry starts, then use brace counting for proper boundaries
    entry_start_pattern = r'@(article|inproceedings|incproceedings|book|incollection|inbook|proceedings|techreport|mastersthesis|masterthesis|phdthesis|misc|unpublished|conference|manual|booklet|collection)\s*\{\s*([^,]+)\s*,'
    
    # Find entry starts and extract complete entries using brace counting
    start_matches = list(re.finditer(entry_start_pattern, bib_content, re.DOTALL | re.IGNORECASE))
    
    for start_match in start_matches:
        entry_type = start_match.group(1).lower()
        entry_key = start_match.group(2).strip()
        
        # Find the complete entry by counting braces
        start_pos = start_match.start()
        brace_start = bib_content.find('{', start_pos)
        if brace_start == -1:
            continue
        
        # Count braces to find the end of this entry
        brace_count = 0
        end_pos = brace_start
        
        for i, char in enumerate(bib_content[brace_start:], brace_start):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_pos = i + 1
                    break
        
        if brace_count != 0:
            logger.warning(f"Unbalanced braces in BibTeX entry starting at position {start_pos}")
            continue
        
        # Extract the entry content (inside the outermost braces)
        entry_content = bib_content[brace_start+1:end_pos-1]
        
        # Parse the entry content
        parsed_entry = parse_bibtex_entry_content(entry_type, entry_key, entry_content)
        if parsed_entry:
            entries.append(parsed_entry)
    
    return entries


def parse_bibtex_entry_content(entry_type: str, entry_key: str, content: str) -> Dict[str, Any]:
    """
    Parse the content of a single BibTeX entry
    
    Args:
        entry_type: Type of BibTeX entry (article, inproceedings, etc.)
        entry_key: The citation key
        content: Content inside the braces
        
    Returns:
        Dictionary with parsed entry data
    """
    fields = {}
    
    # Use a more robust approach with manual parsing
    i = 0
    while i < len(content):
        # Skip whitespace
        while i < len(content) and content[i].isspace():
            i += 1
        
        if i >= len(content):
            break
        
        # Look for field name
        field_start = i
        while i < len(content) and (content[i].isalnum() or content[i] == '_'):
            i += 1
        
        if i == field_start:
            i += 1  # Skip non-alphanumeric character
            continue
        
        field_name = content[field_start:i].lower()
        
        # Skip whitespace
        while i < len(content) and content[i].isspace():
            i += 1
        
        # Look for equals sign
        if i >= len(content) or content[i] != '=':
            continue
        i += 1  # Skip '='
        
        # Skip whitespace
        while i < len(content) and content[i].isspace():
            i += 1
        
        if i >= len(content):
            break
        
        # Parse field value
        field_value = ""
        if content[i] == '"':
            # Handle quoted strings
            i += 1  # Skip opening quote
            value_start = i
            while i < len(content) and content[i] != '"':
                i += 1
            if i < len(content):
                field_value = content[value_start:i]
                i += 1  # Skip closing quote
        elif content[i] == '{':
            # Handle braced strings with proper nesting
            brace_count = 0
            value_start = i + 1  # Skip opening brace
            i += 1
            while i < len(content):
                if content[i] == '{':
                    brace_count += 1
                elif content[i] == '}':
                    if brace_count == 0:
                        break
                    brace_count -= 1
                i += 1
            
            if i < len(content):
                field_value = content[value_start:i]
                i += 1  # Skip closing brace
        
        if field_value:
            field_value = field_value.strip()
            # Strip outer quotes if present (handles cases like title = {"Some Title"})
            if field_value.startswith('"') and field_value.endswith('"'):
                field_value = field_value[1:-1]
            fields[field_name] = field_value
        
        # Skip to next field (look for comma)
        while i < len(content) and content[i] not in ',}':
            i += 1
        if i < len(content) and content[i] == ',':
            i += 1
    
    # Fallback to regex if manual parsing failed
    if not fields:
        logger.debug("Manual parsing failed, trying regex approach")
        field_pattern = r'(\w+)\s*=\s*(?:\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}|"([^"]*)")'
        
        for match in re.finditer(field_pattern, content, re.DOTALL):
            field_name = match.group(1).lower()
            field_value = match.group(2) or match.group(3) or ""
            field_value = field_value.strip()
            if field_value.startswith('"') and field_value.endswith('"'):
                field_value = field_value[1:-1]
            fields[field_name] = field_value
    
    return {
        'type': entry_type,
        'key': entry_key,
        'fields': fields
    }


def parse_bibtex_references(bibliography_text: str) -> List[Dict[str, Any]]:
    """
    Parse BibTeX formatted references into structured format
    
    Args:
        bibliography_text: String containing BibTeX entries
        
    Returns:
        List of structured reference dictionaries
    """
    from refchecker.utils.text_utils import parse_authors_with_initials, clean_title
    from refchecker.utils.doi_utils import construct_doi_url, is_valid_doi_format
    
    entries = parse_bibtex_entries(bibliography_text)
    references = []
    
    for entry in entries:
        entry_type = entry['type']
        fields = entry['fields']
        
        # Extract required information
        title = fields.get('title', '')
        # Remove braces from BibTeX titles before cleaning
        if title.startswith('{') and title.endswith('}'):
            title = title[1:-1]
        title = clean_title(title)
        
        # Parse authors
        authors_raw = fields.get('author', '')
        authors = []
        if authors_raw:
            try:
                authors = parse_authors_with_initials(authors_raw)
            except Exception as e:
                logger.debug(f"Author parsing failed for '{authors_raw}': {e}")
                # Fallback: split by 'and' and clean up
                author_parts = authors_raw.split(' and ')
                for part in author_parts:
                    # Remove leading "and" from author names (handles cases like "and Krishnamoorthy, S")
                    part = re.sub(r'^and\s+', '', part.strip())
                    if part:
                        authors.append(part)
        
        # Extract year
        year_str = fields.get('year', '')
        year = None
        if year_str:
            try:
                year = int(year_str)
            except (ValueError, TypeError):
                # Try to extract year from string like "2023-04"
                year_match = re.search(r'(\d{4})', year_str)
                if year_match:
                    try:
                        year = int(year_match.group(1))
                    except ValueError:
                        pass
        
        # If no year found but we have a valid title/authors, try extracting from eprint field
        if year is None and (title or authors):
            eprint = fields.get('eprint', '')
            if eprint:
                # Extract year from ArXiv eprint ID (e.g., "2311.09096" -> 2023)
                eprint_year_match = re.match(r'^(\d{2})(\d{2})', eprint)
                if eprint_year_match:
                    yy = int(eprint_year_match.group(1))
                    # Convert to 4-digit year (23 -> 2023, assumes 21st century)
                    if yy >= 91:  # ArXiv started in 1991
                        year = 1900 + yy
                    else:
                        year = 2000 + yy
        
        # Extract journal/venue
        journal = fields.get('journal', fields.get('booktitle', fields.get('venue', '')))
        # Remove braces from journal/venue names
        if journal and journal.startswith('{') and journal.endswith('}'):
            journal = journal[1:-1]
        
        # Extract DOI and construct URL
        doi = fields.get('doi', '')
        doi_url = None
        if doi and is_valid_doi_format(doi):
            doi_url = construct_doi_url(doi)
        
        # Extract other URLs
        url = fields.get('url', '')
        if url:
            from refchecker.utils.url_utils import clean_url
            url = clean_url(url)
        
        # Handle special @misc entries with only howpublished field
        if not title and not authors and entry_type == 'misc':
            howpublished = fields.get('howpublished', '')
            if howpublished:
                # Try to extract a URL from howpublished
                url_patterns = [
                    r'://([^/]+)',  # Missing protocol case: "://example.com/path"
                    r'https?://([^/\s]+)',  # Standard URL
                    r'www\.([^/\s]+)',  # www without protocol
                ]
                
                for pattern in url_patterns:
                    match = re.search(pattern, howpublished)
                    if match:
                        domain = match.group(1)
                        # Reconstruct URL with https if protocol was missing
                        if howpublished.startswith('://'):
                            url = 'https' + howpublished
                        elif not howpublished.startswith(('http://', 'https://')):
                            url = 'https://' + howpublished
                        else:
                            url = howpublished
                        
                        # Clean the reconstructed URL
                        from refchecker.utils.url_utils import clean_url
                        url = clean_url(url)
                        
                        # Generate title from domain/path
                        if 'jailbreakchat.com' in domain:
                            title = 'JailbreakChat Website'
                        elif 'lesswrong.com' in domain:
                            title = 'LessWrong Post: Jailbreaking ChatGPT'
                        elif 'chat.openai.com' in domain:
                            title = 'ChatGPT Conversation Share'
                        elif 'gemini.google.com' in domain:
                            title = 'Gemini Conversation Share'
                        elif 'microsoft.com' in domain:
                            title = 'Microsoft Azure Content Safety API'
                        elif 'perspectiveapi.com' in domain:
                            title = 'Perspective API'
                        else:
                            # Generic title based on domain
                            title = f"Web Resource: {domain}"
                        
                        authors = ["Web Resource"]
                        break
        
        # Handle regular URL field
        if not url:
            url = fields.get('url', fields.get('howpublished', ''))
            
        if url.startswith('\\url{') and url.endswith('}'):
            url = url[5:-1]  # Remove \url{...}
            
        # Clean any URL we extracted
        if url:
            from refchecker.utils.url_utils import clean_url
            url = clean_url(url)
        
        # Construct ArXiv URL from eprint field if no URL present
        if not url and not doi_url:
            eprint = fields.get('eprint', '')
            if eprint and re.match(r'^\d{4}\.\d{4,5}', eprint):
                # Remove version number if present and construct ArXiv URL
                clean_eprint = re.sub(r'v\d+$', '', eprint)
                url = f"https://arxiv.org/abs/{clean_eprint}"
        
        # Determine publication URL (prefer DOI, then URL field)
        publication_url = doi_url if doi_url else url
        
        # Apply defaults only if we still don't have values
        if not authors:
            authors = ["Unknown Author"]
        
        # Clean title
        if not title:
            title = "Unknown Title"
        
        # Determine reference type (for compatibility)
        ref_type = 'other'
        if 'arxiv' in publication_url.lower() if publication_url else False or 'arxiv' in title.lower():
            ref_type = 'arxiv'
        elif publication_url or doi:
            ref_type = 'non-arxiv'
        
        # Create structured reference (matching old format)
        reference = {
            'title': title,
            'authors': authors,
            'year': year,
            'journal': journal,
            'doi': doi,
            'url': publication_url if publication_url else '',
            'type': ref_type,
            'bibtex_key': entry['key'],
            'bibtex_type': entry_type,
            'raw_text': f"@{entry_type}{{{entry['key']}, ...}}"  # Simplified raw text
        }
        
        # Add additional fields based on entry type
        if entry_type == 'inproceedings' or entry_type == 'incproceedings':
            reference['pages'] = fields.get('pages', '')
            reference['organization'] = fields.get('organization', '')
        elif entry_type == 'article':
            reference['volume'] = fields.get('volume', '')
            reference['number'] = fields.get('number', '')
            reference['pages'] = fields.get('pages', '')
        elif entry_type == 'book':
            reference['publisher'] = fields.get('publisher', '')
            reference['isbn'] = fields.get('isbn', '')
        
        references.append(reference)
    
    logger.debug(f"Extracted {len(references)} BibTeX references")
    return references