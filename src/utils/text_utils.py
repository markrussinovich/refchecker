#!/usr/bin/env python3
"""
Text processing utilities for ArXiv Reference Checker
"""

import re
import logging
import unicodedata

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

def clean_title(title):
    """
    Clean and normalize a paper title
    
    Args:
        title: Title string
        
    Returns:
        Cleaned title
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''
    
    # Fix hyphenated words broken across lines (e.g., "jailbreak- ing" -> "jailbreaking")
    title = re.sub(r'([a-z])-\s+([a-z])', r'\1\2', title)
    
    # Remove extra whitespace
    title = re.sub(r'\s+', ' ', title).strip()
    
    # Remove quotes
    title = title.strip('"\'')
    
    # Remove trailing punctuation except periods
    title = re.sub(r'[,;:!?]+$', '', title)
    
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