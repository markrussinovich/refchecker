#!/usr/bin/env python3
"""
Text processing utilities for ArXiv Reference Checker
"""

import re
import logging
import unicodedata
from typing import List

logger = logging.getLogger(__name__)


def normalize_text(text):
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
        'Ł': 'L', 'ł': 'l',
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
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    
    # Remove special characters
    text = re.sub(r'[^\w\s]', '', text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text.lower()


def clean_author_name(author):
    """
    Clean and normalize an author name
    
    Args:
        author: Author name string
        
    Returns:
        Cleaned author name
    """
    if not isinstance(author, str):
        return str(author) if author is not None else ''
    
    # Remove extra whitespace
    author = re.sub(r'\s+', ' ', author).strip()
    
    # Remove common prefixes/suffixes
    author = re.sub(r'\b(Dr\.?|Prof\.?|Professor|Mr\.?|Ms\.?|Mrs\.?)\s*', '', author, flags=re.IGNORECASE)
    
    # Remove email addresses
    author = re.sub(r'\S+@\S+\.\S+', '', author)
    
    # Remove affiliations in parentheses or brackets
    author = re.sub(r'\([^)]*\)', '', author)
    author = re.sub(r'\[[^\]]*\]', '', author)
    
    # Remove numbers and superscripts
    author = re.sub(r'\d+', '', author)
    author = re.sub(r'[†‡§¶‖#*]', '', author)
    
    # Clean up extra spaces
    author = re.sub(r'\s+', ' ', author).strip()
    
    return author

def clean_title_basic(title):
    """
    Basic title cleaning: remove newlines, normalize whitespace, and remove trailing punctuation.
    Used for title extraction where we want to preserve most content.
    
    Args:
        title: Title string
        
    Returns:
        Cleaned title with basic formatting
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''
    
    # Clean up newlines and normalize whitespace
    title = title.replace('\n', ' ').strip()
    title = re.sub(r'\s+', ' ', title)
    
    # Remove trailing punctuation
    title = re.sub(r'[.,;:]+$', '', title)
    
    return title


def clean_title(title):
    """
    Full title cleaning and normalization including quote removal, hyphen fixes, and year removal.
    Used for final title processing and comparison.
    
    Args:
        title: Title string
        
    Returns:
        Fully cleaned and normalized title
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''
    
    # Start with basic cleaning
    title = clean_title_basic(title)
    
    # Fix hyphenated words broken across lines (e.g., "jailbreak- ing" -> "jailbreaking")
    title = re.sub(r'([a-z])-\s+([a-z])', r'\1\2', title)
    
    # Remove quotes
    title = title.strip('"\'')
    
    # Remove year information from title
    title = remove_year_from_title(title)
    
    return title


def extract_arxiv_id_from_url(url):
    """
    Extract ArXiv ID from URL
    
    Args:
        url: URL string
        
    Returns:
        ArXiv ID or None if not found
    """
    if not isinstance(url, str):
        return None
    
    # Common ArXiv URL patterns
    patterns = [
        r'arxiv\.org/abs/(\d+\.\d+(?:v\d+)?)',
        r'arxiv\.org/pdf/(\d+\.\d+(?:v\d+)?)',
        r'arxiv:(\d+\.\d+(?:v\d+)?)',
        r'arXiv:(\d+\.\d+(?:v\d+)?)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None

def extract_year_from_text(text):
    """
    Extract a 4-digit year from text
    
    Args:
        text: Text to search
        
    Returns:
        Year as integer or None if not found
    """
    if not isinstance(text, str):
        return None
    
    # Look for 4-digit years (1900-2099)
    year_match = re.search(r'\b(19|20)\d{2}\b', text)
    if year_match:
        return int(year_match.group())
    
    return None

def clean_conference_markers_from_title(title):
    """
    Remove conference markers from title
    
    Args:
        title: Title string
        
    Returns:
        Title with conference markers removed
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''
    
    # Remove common conference markers
    patterns = [
        r'\s*\(.*?conference.*?\)\s*',
        r'\s*\(.*?workshop.*?\)\s*',
        r'\s*\(.*?symposium.*?\)\s*',
        r'\s*\(.*?proceedings.*?\)\s*',
        r'\s*In\s+Proceedings.*',
        r'\s*Proceedings\s+of.*',
    ]
    
    for pattern in patterns:
        title = re.sub(pattern, ' ', title, flags=re.IGNORECASE)
    
    # Clean up extra spaces
    title = re.sub(r'\s+', ' ', title).strip()
    
    return title

def remove_year_from_title(title):
    """
    Remove year information from title
    
    Args:
        title: Title string
        
    Returns:
        Title with year removed
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''
    
    # Remove years in parentheses, at the beginning, or at the end
    title = re.sub(r'\s*\((19|20)\d{2}\)\s*', ' ', title)
    title = re.sub(r'^(19|20)\d{2}\.\s*', '', title)
    title = re.sub(r'\s+(19|20)\d{2}\s*$', '', title)
    
    # Clean up extra spaces
    title = re.sub(r'\s+', ' ', title).strip()
    
    return title


def normalize_author_name(name: str) -> str:
    """
    Normalize author name for comparison.
    This function is used across multiple checker modules.
    
    Args:
        name: Author name
        
    Returns:
        Normalized name
    """
    if not name:
        return ""
    
    # Remove reference numbers (e.g., "[1]")
    name = re.sub(r'^\[\d+\]', '', name)
    
    # Use common normalization function
    return normalize_text(name)


def normalize_paper_title(title: str) -> str:
    """
    Normalize paper title by converting to lowercase and removing whitespace and punctuation.
    This function is used across multiple checker modules.
    
    Args:
        title: Original paper title
        
    Returns:
        Normalized title string
    """
    if not title:
        return ""
    
    # Convert to lowercase
    normalized = title.lower()
    
    # Remove all non-alphanumeric characters (keeping only letters and numbers)
    normalized = re.sub(r'[^a-z0-9]', '', normalized)
    
    return normalized



def is_name_match(name1: str, name2: str) -> bool:
    """
    Check if two author names match, allowing for variations.
    This function is used across multiple checker modules.
    
    Args:
        name1: First author name
        name2: Second author name
        
    Returns:
        True if names match, False otherwise
    """
    if not name1 or not name2:
        return False
    
    # If one is a substring of the other, consider it a match
    if name1 in name2 or name2 in name1:
        return True
    
    # Split into parts (first name, last name, etc.)
    parts1 = name1.split()
    parts2 = name2.split()
    
    # If either name has only one part, compare directly
    if len(parts1) == 1 or len(parts2) == 1:
        return parts1[-1] == parts2[-1]  # Compare last parts (last names)
    
    # Compare last names (last parts)
    if parts1[-1] != parts2[-1]:
        return False
    
    # Compare first initials
    if parts1[0][0] != parts2[0][0]:
        return False
    
    return True


def compare_authors(cited_authors: list, correct_authors: list, normalize_func=None) -> tuple:
    """
    Compare author lists to check if they match.
    This function is used across multiple checker modules.
    
    Args:
        cited_authors: List of author names as cited
        correct_authors: List of author data from the database
        normalize_func: Optional function to normalize author names
        
    Returns:
        Tuple of (match_result, error_message)
    """
    if normalize_func is None:
        normalize_func = normalize_author_name
    
    # Extract author names from database data if they're dict objects
    if correct_authors and isinstance(correct_authors[0], dict):
        correct_names = [author.get('name', '') for author in correct_authors]
    else:
        correct_names = correct_authors
    
    # Normalize names for comparison
    normalized_cited = [normalize_func(name) for name in cited_authors]
    normalized_correct = [normalize_func(name) for name in correct_names]
    
    # If the cited list is much shorter, it might be using "et al."
    # In this case, just check the authors that are listed
    if len(normalized_cited) < len(normalized_correct) and len(normalized_cited) <= 3:
        # Only compare the first few authors
        normalized_correct = normalized_correct[:len(normalized_cited)]
    
    # Compare first author (most important)
    if normalized_cited and normalized_correct:
        if not is_name_match(normalized_cited[0], normalized_correct[0]):
            return False, f"First author mismatch: '{cited_authors[0]}' vs '{correct_names[0]}'"
    
    return True, "Authors match"


def detect_latex_bibliography_format(text):
    """
    Detect if the bibliography is in LaTeX format
    
    Args:
        text: Text content to analyze
        
    Returns:
        dict with detection results containing:
        - is_latex: bool indicating if LaTeX format detected
        - format_type: str ('bibtex', 'thebibliography', 'bibliography_command', None)
        - details: dict with specific information about the detected format
    """
    if not text:
        return {
            'is_latex': False,
            'format_type': None,
            'details': {}
        }
    
    details = {}
    
    # Check for BibTeX entries (@article, @book, @inproceedings, etc.)
    bibtex_pattern = r'@(article|book|inproceedings|incollection|conference|proceedings|techreport|mastersthesis|phdthesis|misc|unpublished)\s*\{'
    bibtex_matches = re.findall(bibtex_pattern, text, re.IGNORECASE)
    
    if bibtex_matches:
        details['bibtex_entries'] = len(bibtex_matches)
        details['entry_types'] = list(set(bibtex_matches))
        return {
            'is_latex': True,
            'format_type': 'bibtex',
            'details': details
        }
    
    # Check for LaTeX bibliography environment
    thebib_pattern = r'\\begin\{thebibliography\}.*?\\end\{thebibliography\}'
    thebib_match = re.search(thebib_pattern, text, re.DOTALL | re.IGNORECASE)
    
    if thebib_match:
        # Count \bibitem entries
        bibitem_matches = re.findall(r'\\bibitem(?:\[[^\]]*\])?\{[^}]+\}', text)
        details['bibitem_count'] = len(bibitem_matches)
        return {
            'is_latex': True,
            'format_type': 'thebibliography',
            'details': details
        }
    
    # Check for \bibliography{} command
    bibcommand_pattern = r'\\bibliography\{([^}]+)\}'
    bibcommand_match = re.search(bibcommand_pattern, text, re.IGNORECASE)
    
    if bibcommand_match:
        bib_files = bibcommand_match.group(1).split(',')
        details['bibliography_files'] = [f.strip() for f in bib_files]
        return {
            'is_latex': True,
            'format_type': 'bibliography_command',
            'details': details
        }
    
    return {
        'is_latex': False,
        'format_type': None,
        'details': {}
    }


def strip_latex_commands(text):
    """
    Strip LaTeX commands and markup from text
    
    Args:
        text: Text containing LaTeX markup
        
    Returns:
        Cleaned text with LaTeX commands removed
    """
    if not text:
        return ""
    
    # Remove comments
    text = re.sub(r'%.*', '', text)
    
    # Remove common text formatting commands
    text = re.sub(r'\\(textbf|textit|emph|underline|textsc|texttt)\{([^{}]*)\}', r'\2', text)
    
    # Remove font size commands
    text = re.sub(r'\\(tiny|scriptsize|footnotesize|small|normalsize|large|Large|LARGE|huge|Huge)\b', '', text)
    
    # Remove math mode delimiters
    text = re.sub(r'\$([^$]*)\$', r'\1', text)
    text = re.sub(r'\\begin\{equation\}.*?\\end\{equation\}', '', text, flags=re.DOTALL)
    text = re.sub(r'\\begin\{align\}.*?\\end\{align\}', '', text, flags=re.DOTALL)
    
    # Remove section commands but keep the text
    text = re.sub(r'\\(section|subsection|subsubsection|paragraph|subparagraph)\*?\{([^{}]*)\}', r'\2', text)
    
    # Remove citation commands but keep the keys
    text = re.sub(r'\\cite[pt]?\*?\{([^}]+)\}', r'[\1]', text)
    
    # Remove common commands
    text = re.sub(r'\\(newline|linebreak|pagebreak|clearpage|newpage)\b', ' ', text)
    
    # Remove escaped characters
    text = re.sub(r'\\([&%$#_{}~^\\])', r'\1', text)
    
    # Remove remaining commands with arguments
    text = re.sub(r'\\[a-zA-Z]+\{[^{}]*\}', '', text)
    
    # Remove remaining commands without arguments
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    return text


def parse_bibtex_entries(bib_content):
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
    
    # Pattern to match BibTeX entries
    entry_pattern = r'@(\w+)\s*\{\s*([^,]+)\s*,\s*(.*?)\n\s*\}'
    
    # Find all entries
    matches = re.finditer(entry_pattern, bib_content, re.DOTALL | re.IGNORECASE)
    
    for match in matches:
        entry_type = match.group(1).lower()
        entry_key = match.group(2).strip()
        fields_text = match.group(3)
        
        # Parse fields using a more robust approach
        fields = {}
        
        # Split fields by looking for field = pattern
        field_starts = []
        field_pattern = r'(\w+)\s*='
        for match in re.finditer(field_pattern, fields_text):
            field_starts.append((match.group(1), match.start(), match.end()))
        
        for i, (field_name, _, end) in enumerate(field_starts):
            # Find the value part after the =
            value_start = end
            
            # Find where this field ends (either next field or end of text)
            if i + 1 < len(field_starts):
                value_end = field_starts[i + 1][1]
            else:
                value_end = len(fields_text)
            
            value_text = fields_text[value_start:value_end].strip()
            
            # Remove leading/trailing comma and whitespace
            value_text = value_text.strip(' ,\n\t')
            
            # Extract the value within braces
            if value_text.startswith('{'):
                # Find matching closing brace using proper brace counting
                brace_count = 0
                for j, char in enumerate(value_text):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            field_value = value_text[1:j]  # Remove outer braces
                            break
                else:
                    # If we couldn't find matching brace, take the whole thing
                    field_value = value_text[1:] if value_text.startswith('{') else value_text
            else:
                field_value = value_text
            
            # Remove surrounding braces (common in BibTeX for preserving capitalization)
            # Handle both single braces {Title} and double braces {{Title}}
            # Also handle cases like {{GPTFUZZER:} Rest of title}
            while field_value.startswith('{') and field_value.endswith('}'):
                # Check if removing braces would leave a balanced string
                inner_value = field_value[1:-1].strip()
                if inner_value:
                    field_value = inner_value
                else:
                    break
            
            # Handle partial braces like {GPTFUZZER:} Rest of title
            # Replace individual brace-protected words/phrases with just their content
            field_value = re.sub(r'\{([^}]+)\}', r'\1', field_value)
            
            # Clean up the field value
            field_value = strip_latex_commands(field_value)
            fields[field_name.lower()] = field_value
        
        entries.append({
            'type': entry_type,
            'key': entry_key,
            'fields': fields
        })
    
    return entries


def extract_latex_references(text, file_path=None):  # pylint: disable=unused-argument
    """
    Extract references from LaTeX content programmatically
    
    Args:
        text: LaTeX text content
        file_path: Optional path to the file (for .bib file resolution)
        
    Returns:
        List of reference dictionaries with extracted metadata
    """
    references = []
    
    # Detect the bibliography format
    format_info = detect_latex_bibliography_format(text)
    
    if not format_info['is_latex']:
        return references
    
    if format_info['format_type'] == 'bibtex':
        # Parse BibTeX entries directly from text
        entries = parse_bibtex_entries(text)
        
        for entry in entries:
            fields = entry['fields']
            
            # Skip entries without essential fields (title or author)
            # These are typically URL-only entries like @misc{key, howpublished={\url{...}}}
            if not fields.get('title') and not fields.get('author'):
                continue
            
            # Reconstruct the full BibTeX entry for raw_text
            bibtex_lines = [f"@{entry['type']}{{{entry['key']},"]
            for field_name, field_value in fields.items():
                # Keep the original field value with proper BibTeX formatting
                bibtex_lines.append(f"  {field_name} = {{{field_value}}},")
            # Remove trailing comma from last field and close the entry
            if bibtex_lines[-1].endswith(','):
                bibtex_lines[-1] = bibtex_lines[-1][:-1]
            bibtex_lines.append("}")
            full_bibtex = '\n'.join(bibtex_lines)
            
            # Extract common reference information
            ref = {
                'raw_text': full_bibtex,
                'title': fields.get('title', ''),
                'authors': [],
                'year': None,
                'journal': fields.get('journal', ''),
                'url': fields.get('url', ''),
                'doi': fields.get('doi', ''),
                'bibtex_key': entry['key'],
                'bibtex_type': entry['type']
            }
            
            # Preserve all original BibTeX fields for formatting correction
            for field_name, field_value in fields.items():
                if field_name not in ref:  # Don't overwrite already processed fields
                    ref[field_name] = field_value
            
            # Parse authors
            if 'author' in fields:
                author_text = fields['author']
                # Split by 'and' and clean up
                authors = [author.strip() for author in re.split(r'\s+and\s+', author_text)]
                ref['authors'] = authors
            
            # Extract year
            if 'year' in fields:
                year_match = re.search(r'\d{4}', fields['year'])
                if year_match:
                    ref['year'] = int(year_match.group())
            
            references.append(ref)
    
    elif format_info['format_type'] == 'thebibliography':
        # Parse \bibitem entries
        bibitem_pattern = r'\\bibitem(?:\[([^\]]*)\])?\{([^}]+)\}\s*(.*?)(?=\\bibitem|\\end\{thebibliography\})'
        
        matches = re.finditer(bibitem_pattern, text, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            label = match.group(1) if match.group(1) else match.group(2)
            key = match.group(2)
            content = match.group(3).strip()
            
            # Clean LaTeX commands from content
            cleaned_content = strip_latex_commands(content)
            
            ref = {
                'raw_text': cleaned_content,
                'title': '',
                'authors': [],
                'year': None,
                'journal': '',
                'url': '',
                'doi': '',
                'bibitem_key': key,
                'bibitem_label': label
            }
            
            # Try to extract structured information from cleaned content
            # This is a basic implementation - could be enhanced
            
            # Extract year
            year_match = re.search(r'\b(19|20)\d{2}\b', cleaned_content)
            if year_match:
                ref['year'] = int(year_match.group())
            
            # Extract potential title (often in quotes or italics)
            title_match = re.search(r'["""]([^"""]+)["""]', cleaned_content)
            if not title_match:
                title_match = re.search(r'\*([^*]+)\*', cleaned_content)
            if title_match:
                ref['title'] = title_match.group(1).strip()
            
            # Simple author extraction (names before year or title)
            author_part = cleaned_content
            if ref['year']:
                author_part = cleaned_content.split(str(ref['year']))[0]
            elif ref['title']:
                author_part = cleaned_content.split(ref['title'])[0]
            
            # Extract names (very basic approach)
            potential_authors = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]*\.?)?\s+[A-Z][a-z]+\b', author_part)
            if potential_authors:
                ref['authors'] = potential_authors[:5]  # Limit to first 5 matches
            
            references.append(ref)
    
    elif format_info['format_type'] == 'bibliography_command':
        # Handle \bibliography{} command - would need to read .bib files
        # For now, return empty list as we can't read external files here
        # This could be enhanced to read the referenced .bib files
        pass
    
    return references


def format_corrected_reference(original_reference, corrected_data, error_entry):
    """
    Format a corrected reference in the same format as the original
    
    Args:
        original_reference: The original reference dict with format info
        corrected_data: The correct data from the verification service
        error_entry: The error entry with correction details
        
    Returns:
        Formatted corrected reference string
    """
    if not original_reference or not corrected_data:
        return None
    
    # Check if this is a BibTeX reference
    if original_reference.get('bibtex_key'):
        return format_corrected_bibtex(original_reference, corrected_data, error_entry)
    
    # Check if this is a bibitem reference
    if original_reference.get('bibitem_key'):
        return format_corrected_bibitem(original_reference, corrected_data, error_entry)
    
    # Default: format as plain text citation
    return format_corrected_plaintext(original_reference, corrected_data, error_entry)


def format_corrected_bibtex(original_reference, corrected_data, error_entry):
    """Format a corrected BibTeX entry in the same style as the original"""
    
    # Get the corrected information
    correct_title = error_entry.get('ref_title_correct') or corrected_data.get('title', '')
    correct_authors = error_entry.get('ref_authors_correct') or corrected_data.get('authors', '')
    correct_year = error_entry.get('ref_year_correct') or corrected_data.get('year', '')
    correct_url = error_entry.get('ref_url_correct') or corrected_data.get('url', '')
    correct_doi = corrected_data.get('externalIds', {}).get('DOI', '') if corrected_data else ''
    
    # Get original BibTeX details
    bibtex_key = original_reference.get('bibtex_key', 'unknown')
    bibtex_type = original_reference.get('bibtex_type', 'article')
    
    # Build the corrected BibTeX entry
    lines = [f"@{bibtex_type}{{{bibtex_key},"]
    
    # Add fields in typical BibTeX order
    if correct_authors:
        # Format authors for BibTeX (replace commas with ' and ')
        if ', ' in correct_authors:
            authors = correct_authors.split(', ')
            bibtex_authors = ' and '.join(authors)
        else:
            bibtex_authors = correct_authors
        lines.append(f"  author = {{{bibtex_authors}}},")
    
    if correct_title:
        lines.append(f"  title = {{{correct_title}}},")
    
    # Add journal/venue field - prefer original if available, otherwise use corrected data
    original_journal = original_reference.get('journal', '') or original_reference.get('booktitle', '')
    corrected_journal = corrected_data.get('journal', '') or corrected_data.get('venue', '') if corrected_data else ''
    journal_to_use = original_journal or corrected_journal
    
    if journal_to_use and bibtex_type in ['article', 'inproceedings', 'conference']:
        field_name = 'journal' if bibtex_type == 'article' else 'booktitle'
        lines.append(f"  {field_name} = {{{journal_to_use}}},")
    
    # Add other common fields from original reference if present
    original_fields_to_preserve = ['eprint', 'archiveprefix', 'primaryclass', 'volume', 'number', 'pages', 'publisher', 'note']
    for field in original_fields_to_preserve:
        if original_reference.get(field):
            lines.append(f"  {field} = {{{original_reference[field]}}},")
    
    if correct_year:
        lines.append(f"  year = {{{correct_year}}},")
    
    if correct_url:
        lines.append(f"  url = {{{correct_url}}},")
    
    if correct_doi:
        lines.append(f"  doi = {{{correct_doi}}},")
    
    # Remove trailing comma from last field
    if lines[-1].endswith(','):
        lines[-1] = lines[-1][:-1]
    
    lines.append("}")
    
    return '\n'.join(lines)


def format_corrected_bibitem(original_reference, corrected_data, error_entry):
    """Format a corrected \\bibitem entry"""
    
    # Get the corrected information
    correct_title = error_entry.get('ref_title_correct') or corrected_data.get('title', '')
    correct_authors = error_entry.get('ref_authors_correct') or corrected_data.get('authors', '')
    correct_year = error_entry.get('ref_year_correct') or corrected_data.get('year', '')
    correct_url = error_entry.get('ref_url_correct') or corrected_data.get('url', '')
    correct_venue = corrected_data.get('journal', '') or corrected_data.get('venue', '')
    
    # Get original bibitem details
    bibitem_key = original_reference.get('bibitem_key', 'unknown')
    bibitem_label = original_reference.get('bibitem_label', bibitem_key)
    
    # Build the corrected bibitem entry
    if bibitem_label != bibitem_key:
        bibitem_line = f"\\bibitem[{bibitem_label}]{{{bibitem_key}}}"
    else:
        bibitem_line = f"\\bibitem{{{bibitem_key}}}"
    
    # Format the citation text
    citation_parts = []
    
    if correct_authors:
        citation_parts.append(correct_authors)
    
    if correct_year:
        citation_parts.append(f"({correct_year})")
    
    if correct_title:
        citation_parts.append(f"\\textit{{{correct_title}}}")
    
    if correct_venue:
        citation_parts.append(f"In \\textit{{{correct_venue}}}")
    
    if correct_url:
        citation_parts.append(f"\\url{{{correct_url}}}")
    
    citation_text = '. '.join(citation_parts) + '.'
    
    return f"{bibitem_line}\n{citation_text}"


def format_corrected_plaintext(original_reference, corrected_data, error_entry):
    """Format a corrected plaintext citation"""
    
    # Get the corrected information
    correct_title = error_entry.get('ref_title_correct') or corrected_data.get('title', '')
    correct_authors = error_entry.get('ref_authors_correct') or corrected_data.get('authors', '')
    correct_year = error_entry.get('ref_year_correct') or corrected_data.get('year', '')
    correct_url = error_entry.get('ref_url_correct') or corrected_data.get('url', '')
    correct_venue = corrected_data.get('journal', '') or corrected_data.get('venue', '')
    
    # Build a standard citation format
    citation_parts = []
    
    if correct_authors:
        citation_parts.append(correct_authors)
    
    if correct_year:
        citation_parts.append(f"({correct_year})")
    
    if correct_title:
        citation_parts.append(f'"{correct_title}"')
    
    if correct_venue:
        citation_parts.append(f"In {correct_venue}")
    
    if correct_url:
        citation_parts.append(f"{correct_url}")
    
    return '. '.join(citation_parts) + '.'


def calculate_title_similarity(title1: str, title2: str) -> float:
    """
    Calculate similarity between two titles using multiple approaches
    
    Args:
        title1: First title
        title2: Second title
        
    Returns:
        Similarity score between 0 and 1
    """
    if not title1 or not title2:
        return 0.0
    
    # Normalize titles for comparison
    t1 = title1.lower().strip()
    t2 = title2.lower().strip()
    
    # Exact match
    if t1 == t2:
        return 1.0
    
    # Normalize hyphens to handle hyphenation differences
    # Replace hyphens with spaces and normalize whitespace
    t1_dehyphenated = re.sub(r'-', ' ', t1)
    t1_dehyphenated = re.sub(r'\s+', ' ', t1_dehyphenated).strip()
    t2_dehyphenated = re.sub(r'-', ' ', t2)
    t2_dehyphenated = re.sub(r'\s+', ' ', t2_dehyphenated).strip()
    
    # Check for match after hyphen normalization
    if t1_dehyphenated == t2_dehyphenated:
        return 1.0
    
    # Additional normalization: remove punctuation for comparison
    t1_normalized = re.sub(r'[^\w\s]', ' ', t1_dehyphenated)
    t1_normalized = re.sub(r'\s+', ' ', t1_normalized).strip()
    t2_normalized = re.sub(r'[^\w\s]', ' ', t2_dehyphenated)
    t2_normalized = re.sub(r'\s+', ' ', t2_normalized).strip()
    
    # Check for match after full normalization
    if t1_normalized == t2_normalized:
        return 1.0
    
    # Check if one is substring of another, but require substantial overlap
    # to avoid false positives like "Rust programming language" vs "RustBelt: securing..."
    shorter_title = t1 if len(t1) < len(t2) else t2
    longer_title = t2 if len(t1) < len(t2) else t1
    
    if shorter_title in longer_title:
        # Calculate what percentage of the shorter title matches
        overlap_ratio = len(shorter_title) / len(longer_title)
        # Only return high score if substantial portion of longer title matches
        if overlap_ratio >= 0.8:  # At least 80% overlap required
            return 0.95
        else:
            # Partial substring match - use lower score
            return 0.7
    
    # Also check substring match with dehyphenated versions
    shorter_dehyp = t1_dehyphenated if len(t1_dehyphenated) < len(t2_dehyphenated) else t2_dehyphenated
    longer_dehyp = t2_dehyphenated if len(t1_dehyphenated) < len(t2_dehyphenated) else t1_dehyphenated
    
    if shorter_dehyp in longer_dehyp:
        overlap_ratio = len(shorter_dehyp) / len(longer_dehyp)
        if overlap_ratio >= 0.8:
            return 0.95
        else:
            return 0.7
    
    # Check substring match with fully normalized versions
    shorter_norm = t1_normalized if len(t1_normalized) < len(t2_normalized) else t2_normalized
    longer_norm = t2_normalized if len(t1_normalized) < len(t2_normalized) else t1_normalized
    
    if shorter_norm in longer_norm:
        overlap_ratio = len(shorter_norm) / len(longer_norm)
        if overlap_ratio >= 0.8:
            return 0.95
        else:
            return 0.7
    
    # Split into words and calculate word overlap using fully normalized versions
    words1 = set(t1_normalized.split())
    words2 = set(t2_normalized.split())
    
    # Remove common stop words that don't add much meaning
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
    words1_filtered = words1 - stop_words
    words2_filtered = words2 - stop_words
    
    # If filtering removed too many words, fall back to unfiltered comparison
    if not words1_filtered or not words2_filtered:
        words1_filtered = words1
        words2_filtered = words2
    
    if not words1_filtered or not words2_filtered:
        return 0.0
    
    # Calculate Jaccard similarity (intersection over union)
    intersection = len(words1_filtered.intersection(words2_filtered))
    union = len(words1_filtered.union(words2_filtered))
    jaccard_score = intersection / union if union > 0 else 0.0
    
    # For titles with high word overlap, boost the score
    overlap_ratio = intersection / min(len(words1_filtered), len(words2_filtered))
    if overlap_ratio >= 0.9 and jaccard_score >= 0.7:
        # High overlap suggests they are likely the same paper
        return max(0.85, jaccard_score)
    
    # Calculate word order similarity for key phrases
    # This helps catch cases like "BLACKSMITH: Rowhammering in the Frequency Domain"
    # vs "BLACKSMITH: Scalable Rowhammering in the Frequency Domain"
    key_phrases1 = _extract_key_phrases(t1_normalized)
    
    phrase_matches = 0
    for phrase in key_phrases1:
        if phrase in t2_normalized:
            phrase_matches += 1
    
    phrase_score = phrase_matches / len(key_phrases1) if key_phrases1 else 0.0
    
    # Combine scores with weights
    # Jaccard similarity gets more weight for overall content
    # Phrase matching gets weight for maintaining key concepts
    final_score = (jaccard_score * 0.7) + (phrase_score * 0.3)
    
    return min(final_score, 1.0)


def _extract_key_phrases(title: str) -> List[str]:
    """
    Extract key phrases from a title
    
    Args:
        title: Title to extract phrases from
        
    Returns:
        List of key phrases
    """
    # Look for patterns like "WORD:" or distinctive multi-word phrases
    phrases = []
    
    # Extract colon-separated main topics (like "BLACKSMITH:")
    colon_parts = title.split(':')
    if len(colon_parts) > 1:
        main_topic = colon_parts[0].strip()
        if len(main_topic) > 2:  # Avoid single letters
            phrases.append(main_topic)
    
    # Extract quoted phrases
    quoted = re.findall(r'"([^"]*)"', title)
    phrases.extend([q for q in quoted if len(q) > 2])
    
    # Extract capitalized words/phrases (likely important terms)
    cap_words = re.findall(r'\b[A-Z][A-Z]+\b', title)  # All caps words
    phrases.extend([w for w in cap_words if len(w) > 2])
    
    return phrases


def find_best_match(search_results, cleaned_title, year=None):
    """
    Find the best match from search results using similarity scoring
    
    Args:
        search_results: List of search result dictionaries
        cleaned_title: The cleaned title to match against
        year: Optional year for bonus scoring
        
    Returns:
        Tuple of (best_match, best_score) or (None, 0) if no good match
    """
    if not search_results:
        return None, 0
    
    best_match = None
    best_score = 0
    
    for result in search_results:
        result_title = result.get('title') or result.get('display_name', '')
        
        # Calculate similarity score using utility function
        score = calculate_title_similarity(cleaned_title, result_title)
        
        # Bonus for year match
        result_year = result.get('publication_year')
        if year and result_year and year == result_year:
            score += 0.1
        
        if score > best_score:
            best_score = score
            best_match = result
    
    return best_match, best_score