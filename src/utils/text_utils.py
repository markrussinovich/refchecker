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


def clean_title_for_search(title):
    """
    Clean title for API search queries while preserving important structural elements.
    
    This function strikes a balance between cleaning up problematic characters
    and preserving structure that helps APIs find the exact paper (e.g., colons,
    capitalization, meaningful punctuation).
    
    Args:
        title: Title string to clean for search
        
    Returns:
        Cleaned title optimized for search queries
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''
    
    # Clean up newlines and normalize whitespace (but preserve other structure)
    title = title.replace('\n', ' ').strip()
    title = re.sub(r'\s+', ' ', title)  # Normalize whitespace only
    
    # Note: We intentionally preserve:
    # - Capitalization (helps with exact matching)
    # - Colons and other meaningful punctuation (structural markers)
    # - Special characters that might be part of proper names or technical terms
    
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
    
    # Remove common prefixes that don't affect the actual title content
    prefixes_to_remove = [
        'original contribution:',
        'original article:',
        'research article:',
        'technical note:',
        'brief communication:',
        'review:',
        'editorial:',
        'commentary:'
    ]
    
    for prefix in prefixes_to_remove:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            break
    
    # Remove common abbreviation/system name prefixes followed by colons
    # This handles cases like "HuRef: title", "GPT-4: title", "BERT: title", etc.
    # Match any sequence of letters, digits, or hyphens followed by colon and space
    prefix_pattern = r'^[a-z0-9\-]+:\s+'
    normalized = re.sub(prefix_pattern, '', normalized)
    
    # Remove all non-alphanumeric characters (keeping only letters and numbers)
    normalized = re.sub(r'[^a-z0-9]', '', normalized)
    
    return normalized



def normalize_diacritics(text: str) -> str:
    """
    Normalize diacritics in text by removing accent marks and converting to ASCII equivalent.
    
    Args:
        text: Input text with possible diacritics
        
    Returns:
        Text with diacritics normalized
        
    Examples:
        'Horkỳ' -> 'horky'
        'Vojtěch' -> 'vojtech'
        'José' -> 'jose'
        'Łukasz' -> 'lukasz'
    """
    # First handle special characters that don't decompose properly
    special_chars = {
        'ł': 'l', 'Ł': 'L',
        'đ': 'd', 'Đ': 'D', 
        'ħ': 'h', 'Ħ': 'H',
        'ø': 'o', 'Ø': 'O',
        'þ': 'th', 'Þ': 'TH',
        'ß': 'ss',
        'æ': 'ae', 'Æ': 'AE',
        'œ': 'oe', 'Œ': 'OE',
    }
    
    for special, replacement in special_chars.items():
        text = text.replace(special, replacement)
    
    # Decompose characters into base + combining characters (NFD normalization)
    normalized = unicodedata.normalize('NFD', text)
    # Remove all combining characters (accents, diacritics)
    ascii_text = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')
    return ascii_text

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
    
    # Normalize case and diacritics for comparison
    name1 = normalize_diacritics(name1.strip().lower())
    name2 = normalize_diacritics(name2.strip().lower())
    
    # Only consider substring match if they are very similar (e.g., identical with/without punctuation)
    # Remove this overly broad check that causes false positives like "marie k. johnson" matching "k. johnson"
    # if name1 in name2 or name2 in name1:
    #     return True
    
    # Split into parts (first name, last name, etc.)
    parts1 = name1.split()
    parts2 = name2.split()
    
    
    # Special case: Handle hyphenated first names vs initials
    # e.g., "Stein JP" vs "Jan-Philipp Stein"
    if (len(parts1) == 2 and len(parts2) == 2 and 
        len(parts1[1]) == 2 and '-' in parts2[0] and len(parts2[1]) > 1):
        # parts1 is "Last FI" format, parts2 is "First-Second Last" format
        last_name1 = parts1[0]  # "Stein"
        initials1 = parts1[1]  # "JP"
        hyphenated_first2 = parts2[0]  # "Jan-Philipp" 
        last_name2 = parts2[1]  # "Stein"
        
        # Split hyphenated name
        first_parts = hyphenated_first2.split('-')
        if (last_name1 == last_name2 and 
            len(initials1) >= 2 and len(first_parts) >= 2 and
            initials1[0] == first_parts[0][0] and
            initials1[1] == first_parts[1][0]):
            return True
    
    if (len(parts1) == 2 and len(parts2) == 2 and 
        '-' in parts1[0] and len(parts1[1]) > 1 and len(parts2[1]) == 2):
        # parts1 is "First-Second Last" format, parts2 is "Last FI" format  
        hyphenated_first1 = parts1[0]  # "Jan-Philipp"
        last_name1 = parts1[1]  # "Stein"
        last_name2 = parts2[0]  # "Stein"
        initials2 = parts2[1]  # "JP"
        
        # Split hyphenated name
        first_parts = hyphenated_first1.split('-')
        if (last_name1 == last_name2 and 
            len(initials2) >= 2 and len(first_parts) >= 2 and
            first_parts[0][0] == initials2[0] and
            first_parts[1][0] == initials2[1]):
            return True

    # Special case: Handle "Last I/FI" vs "F. I. Last" patterns (with periods)
    # e.g., "Fang G" vs "G. Fang", "Digman JM" vs "J. M. Digman", "Kaelbling LP" vs "L. Kaelbling"
    if (len(parts1) == 2 and len(parts2) >= 2 and 
        len(parts1[1]) >= 1 and all(len(p.rstrip('.')) == 1 for p in parts2[:-1]) and len(parts2[-1]) > 1):
        # parts1 is "Last I/FI" format, parts2 is "F. I. Last" format
        last_name1 = parts1[0]  # "Fang" or "Digman"
        initials1 = parts1[1]  # "G" or "JM"
        last_name2 = parts2[-1]  # "Fang" or "Digman"
        initials2 = [p.rstrip('.') for p in parts2[:-1]]  # ["G"] or ["J", "M"]
        
        if last_name1 == last_name2:
            # Handle both single initials and multiple initials with middle initial omission
            if len(initials1) == 1:
                # Single initial case: "Fang G" vs "G. Fang"
                if len(initials2) == 1 and initials1 == initials2[0]:
                    return True
            else:
                # Multiple initials case: allow middle initial omission
                if (len(initials2) >= 1 and initials1[0] == initials2[0] and
                    (len(initials1) == len(initials2) and all(initials1[i] == initials2[i] for i in range(len(initials1))) or
                     len(initials2) == 1)):  # Middle initial omitted in parts2
                    return True
    
    if (len(parts1) >= 2 and len(parts2) == 2 and 
        all(len(p.rstrip('.')) == 1 for p in parts1[:-1]) and len(parts1[-1]) > 1 and len(parts2[1]) >= 1):
        # parts1 is "F. I. Last" format, parts2 is "Last I/FI" format  
        last_name1 = parts1[-1]  # "Fang" or "Digman"
        initials1 = [p.rstrip('.') for p in parts1[:-1]]  # ["G"] or ["J", "M"]
        last_name2 = parts2[0]  # "Fang" or "Digman"
        initials2 = parts2[1]  # "G" or "JM"
        
        if last_name1 == last_name2:
            # Handle both single initials and multiple initials with middle initial omission
            if len(initials2) == 1:
                # Single initial case: "G. Fang" vs "Fang G"
                if len(initials1) == 1 and initials1[0] == initials2:
                    return True
            else:
                # Multiple initials case: allow middle initial omission
                if (len(initials1) >= 1 and initials1[0] == initials2[0] and
                    (len(initials1) == len(initials2) and all(initials1[i] == initials2[i] for i in range(len(initials1))) or
                     len(initials1) == 1)):  # Middle initial omitted in parts1
                    return True

    # Special case: Handle "LastName FM" vs "FirstName MiddleInitial. LastName" patterns
    # e.g., "Kostick-Quenet KM" vs "Kristin M. Kostick-Quenet"
    # e.g., "McCrae RR" vs "Robert R. McCrae" 
    # e.g., "Beaver KM" vs "Kevin M. Beaver"
    if (len(parts1) == 2 and len(parts2) == 3 and 
        len(parts1[1]) >= 2 and len(parts2[0]) > 1 and len(parts2[1].rstrip('.')) == 1 and len(parts2[2]) > 1):
        # parts1 is "LastName FM" format, parts2 is "FirstName M. LastName" format
        last_name1 = parts1[0]  # "Kostick-Quenet"
        initials1 = parts1[1]  # "KM"
        first_name2 = parts2[0]  # "Kristin" 
        middle_initial2 = parts2[1].rstrip('.')  # "M"
        last_name2 = parts2[2]  # "Kostick-Quenet"
        
        if (last_name1 == last_name2 and 
            len(initials1) >= 2 and
            initials1[0] == first_name2[0] and
            initials1[1] == middle_initial2):
            return True
    
    if (len(parts1) == 3 and len(parts2) == 2 and 
        len(parts1[0]) > 1 and len(parts1[1].rstrip('.')) == 1 and len(parts1[2]) > 1 and len(parts2[1]) >= 2):
        # parts1 is "FirstName M. LastName" format, parts2 is "LastName FM" format  
        first_name1 = parts1[0]  # "Kristin"
        middle_initial1 = parts1[1].rstrip('.')  # "M"
        last_name1 = parts1[2]  # "Kostick-Quenet"
        last_name2 = parts2[0]  # "Kostick-Quenet"
        initials2 = parts2[1]  # "KM"
        
        if (last_name1 == last_name2 and 
            len(initials2) >= 2 and
            first_name1[0] == initials2[0] and
            middle_initial1 == initials2[1]):
            return True

    # Special case: Handle "Last FM" vs "First M Last" patterns (with middle initial, no periods)
    # e.g., "Cardamone NC" vs "Nicholas C Cardamone"
    if (len(parts1) == 2 and len(parts2) == 3 and 
        len(parts1[1]) == 2 and len(parts2[0]) > 1 and len(parts2[1]) == 1 and len(parts2[2]) > 1):
        # parts1 is "Last FM" format, parts2 is "First M Last" format
        last_name1 = parts1[0]  # "Cardamone"
        initials1 = parts1[1]  # "NC"
        first_name2 = parts2[0]  # "Nicholas" 
        middle_initial2 = parts2[1]  # "C"
        last_name2 = parts2[2]  # "Cardamone"
        
        if (last_name1 == last_name2 and 
            len(initials1) >= 2 and
            initials1[0] == first_name2[0] and
            initials1[1] == middle_initial2):
            return True
    
    if (len(parts1) == 3 and len(parts2) == 2 and 
        len(parts1[0]) > 1 and len(parts1[1]) == 1 and len(parts1[2]) > 1 and len(parts2[1]) == 2):
        # parts1 is "First M Last" format, parts2 is "Last FM" format  
        first_name1 = parts1[0]  # "Nicholas"
        middle_initial1 = parts1[1]  # "C"
        last_name1 = parts1[2]  # "Cardamone"
        last_name2 = parts2[0]  # "Cardamone"
        initials2 = parts2[1]  # "NC"
        
        if (last_name1 == last_name2 and 
            len(initials2) >= 2 and
            first_name1[0] == initials2[0] and
            middle_initial1 == initials2[1]):
            return True

    # Special case: Handle single letter first name variations like "S. Jeong" vs "S Jeong"
    if (len(parts1) == 2 and len(parts2) == 2 and
        len(parts1[0]) == 1 and len(parts2[0]) == 1):
        # Both have single letter first names, compare directly
        if parts1[0] == parts2[0] and parts1[1] == parts2[1]:
            return True
    
    # If either name has only one part, compare directly
    if len(parts1) == 1 or len(parts2) == 1:
        return parts1[-1] == parts2[-1]  # Compare last parts (last names)
    
    # IMPORTANT: Check special cases BEFORE the general last name comparison
    # because some cases like compound last names don't follow the standard pattern
    
    # Special case: Handle compound last names with first names/initials
    # e.g., "Della Santina C" vs "Cosimo Della Santina"
    if (len(parts1) == 3 and len(parts2) == 3 and 
        len(parts1[2]) == 1 and len(parts2[0]) > 1):
        # Check if parts1[0] + parts1[1] matches parts2[1] + parts2[2] (compound last names)
        compound_last1 = f"{parts1[0]} {parts1[1]}"  # "Della Santina"
        compound_last2 = f"{parts2[1]} {parts2[2]}"  # "Della Santina"
        first_initial1 = parts1[2]  # "C"
        first_name2 = parts2[0]  # "Cosimo"
        
        if (compound_last1 == compound_last2 and 
            first_initial1 == first_name2[0]):
            return True
    
    if (len(parts1) == 3 and len(parts2) == 3 and 
        len(parts1[0]) > 1 and len(parts2[2]) == 1):
        # Reverse case: "Cosimo Della Santina" vs "Della Santina C"
        first_name1 = parts1[0]  # "Cosimo"
        compound_last1 = f"{parts1[1]} {parts1[2]}"  # "Della Santina"
        compound_last2 = f"{parts2[0]} {parts2[1]}"  # "Della Santina" 
        first_initial2 = parts2[2]  # "C"
        
        if (compound_last1 == compound_last2 and 
            first_name1[0] == first_initial2):
            return True

    # Special case: Handle "Last M" vs "First M. Last" patterns where M could be middle initial
    # e.g., "Jitosho R" vs "Rianna M. Jitosho" - R could be middle initial or other
    if (len(parts1) == 2 and len(parts2) == 3 and 
        len(parts1[1]) == 1 and len(parts2[0]) > 1 and len(parts2[1].rstrip('.')) == 1 and len(parts2[2]) > 1):
        # parts1 is "Last I" format, parts2 is "First M. Last" format
        last_name1 = parts1[0]  # "Jitosho"
        initial1 = parts1[1]  # "R"
        first_name2 = parts2[0]  # "Rianna"
        middle_initial2 = parts2[1].rstrip('.')  # "M"
        last_name2 = parts2[2]  # "Jitosho"
        
        # Check if they could be the same person (same last name, and initial could be middle or other)
        if (last_name1 == last_name2 and 
            (initial1 == first_name2[0] or initial1 == middle_initial2)):
            return True
    
    if (len(parts1) == 3 and len(parts2) == 2 and 
        len(parts1[0]) > 1 and len(parts1[1].rstrip('.')) == 1 and len(parts1[2]) > 1 and len(parts2[1]) == 1):
        # parts1 is "First M. Last" format, parts2 is "Last I" format  
        first_name1 = parts1[0]  # "Rianna"
        middle_initial1 = parts1[1].rstrip('.')  # "M"
        last_name1 = parts1[2]  # "Jitosho"
        last_name2 = parts2[0]  # "Jitosho"
        initial2 = parts2[1]  # "R"
        
        # Same logic - if last names match and any initial matches, consider it a match
        if (last_name1 == last_name2 and 
            (first_name1[0] == initial2 or middle_initial1 == initial2)):
            return True

    # Special case: Handle "Last FM" vs "F. Last" patterns (middle initial can be omitted)
    # e.g., "Kaelbling LP" vs "L. Kaelbling" (P middle initial is omitted)
    if (len(parts1) == 2 and len(parts2) == 2 and 
        len(parts1[1]) == 2 and len(parts2[0].rstrip('.')) == 1 and len(parts2[1]) > 1):
        # parts1 is "Last FM" format, parts2 is "F. Last" format
        last_name1 = parts1[0]  # "Kaelbling"
        initials1 = parts1[1]  # "LP"
        first_initial2 = parts2[0].rstrip('.')  # "L"
        last_name2 = parts2[1]  # "Kaelbling"
        
        if (last_name1 == last_name2 and 
            initials1[0] == first_initial2):  # Only check first initial, allow middle to be omitted
            return True
    
    if (len(parts1) == 2 and len(parts2) == 2 and 
        len(parts1[0].rstrip('.')) == 1 and len(parts1[1]) > 1 and len(parts2[1]) == 2):
        # parts1 is "F. Last" format, parts2 is "Last FM" format  
        first_initial1 = parts1[0].rstrip('.')  # "L"
        last_name1 = parts1[1]  # "Kaelbling"
        last_name2 = parts2[0]  # "Kaelbling"
        initials2 = parts2[1]  # "LP"
        
        if (last_name1 == last_name2 and 
            first_initial1 == initials2[0]):  # Only check first initial, allow middle to be omitted
            return True
    
    # Special case: Handle "Last I" vs "First Last" patterns 
    # e.g., "Alessi C" vs "Carlo Alessi", "Fang G" vs "Guoxin Fang"
    if (len(parts1) == 2 and len(parts2) == 2 and
        len(parts1[1]) == 1 and len(parts2[0]) > 1 and len(parts2[1]) > 1):
        # parts1 is "Last I" format, parts2 is "First Last" format
        last_name1 = parts1[0]  # "Alessi"
        initial1 = parts1[1]  # "C"
        first_name2 = parts2[0]  # "Carlo"
        last_name2 = parts2[1]  # "Alessi"
        
        if last_name1 == last_name2 and initial1 == first_name2[0]:
            return True
    
    # Special case: Handle "First Last" vs "Last I" patterns 
    # e.g., "Carlo Alessi" vs "Alessi C", "Guoxin Fang" vs "Fang G"
    if (len(parts1) == 2 and len(parts2) == 2 and
        len(parts1[0]) > 1 and len(parts1[1]) > 1 and len(parts2[1]) == 1):
        # parts1 is "First Last" format, parts2 is "Last I" format
        first_name1 = parts1[0]  # "Carlo"
        last_name1 = parts1[1]  # "Alessi"
        last_name2 = parts2[0]  # "Alessi"
        initial2 = parts2[1]  # "C"
        
        if last_name1 == last_name2 and first_name1[0] == initial2:
            return True

    # Special case: Handle "Last II" vs "First Second Last" patterns 
    # e.g., "Nazeer MS" vs "Muhammad Sunny Nazeer", "Thuruthel TG" vs "Thomas George Thuruthel"
    if (len(parts1) == 2 and len(parts2) == 3 and
        len(parts1[1]) == 2 and len(parts2[0]) > 1 and len(parts2[1]) > 1 and len(parts2[2]) > 1):
        # parts1 is "Last II" format, parts2 is "First Second Last" format
        last_name1 = parts1[0]  # "Nazeer"
        initials1 = parts1[1]  # "MS"
        first_name2 = parts2[0]  # "Muhammad"
        second_name2 = parts2[1]  # "Sunny"
        last_name2 = parts2[2]  # "Nazeer"
        
        if (last_name1 == last_name2 and 
            initials1[0] == first_name2[0] and initials1[1] == second_name2[0]):
            return True
    
    # Special case: Handle "First Second Last" vs "Last II" patterns 
    # e.g., "Muhammad Sunny Nazeer" vs "Nazeer MS", "Thomas George Thuruthel" vs "Thuruthel TG"
    if (len(parts1) == 3 and len(parts2) == 2 and
        len(parts1[0]) > 1 and len(parts1[1]) > 1 and len(parts1[2]) > 1 and len(parts2[1]) == 2):
        # parts1 is "First Second Last" format, parts2 is "Last II" format
        first_name1 = parts1[0]  # "Muhammad"
        second_name1 = parts1[1]  # "Sunny"
        last_name1 = parts1[2]  # "Nazeer"
        last_name2 = parts2[0]  # "Nazeer"
        initials2 = parts2[1]  # "MS"
        
        if (last_name1 == last_name2 and 
            first_name1[0] == initials2[0] and second_name1[0] == initials2[1]):
            return True

    # Compare last names (last parts) - they must match (for standard cases)
    if parts1[-1] != parts2[-1]:
        return False
    
    def _matches_name_part(abbrev, full):
        """Check if abbreviated name part matches full name part"""
        # Handle cases like "S." vs "Scott", "A.-D." vs "Alexandru-Daniel", "I. J." vs "I."
        abbrev_clean = abbrev.rstrip('.')
        full_clean = full.rstrip('.')
        
        # If abbrev is single letter, check if it matches first letter of full name
        if len(abbrev_clean) == 1:
            return abbrev_clean == full_clean[0] if full_clean else False
        
        # If abbrev has hyphens/dashes, check each part FIRST (before general multiple initials)
        if '-' in abbrev_clean:
            abbrev_letters = [p.strip().rstrip('.') for p in abbrev_clean.split('-')]
            if '-' in full:
                # Full name also has hyphens - match part by part
                full_parts_split = [p.strip() for p in full.split('-')]
                if len(abbrev_letters) == len(full_parts_split):
                    for al, fp in zip(abbrev_letters, full_parts_split):
                        if len(al) == 1 and al != fp[0]:
                            return False
                        elif len(al) > 1 and al != fp:
                            return False
                    return True
                else:
                    return False
            else:
                # Full name doesn't have hyphens, but abbrev does
                # Try to match by treating the full name as space-separated parts
                # e.g., "A.-D." vs "Alexandru Daniel" 
                full_space_parts = full.split()
                if len(abbrev_letters) == len(full_space_parts):
                    for al, fp in zip(abbrev_letters, full_space_parts):
                        if len(al) == 1 and al != fp[0]:
                            return False
                        elif len(al) > 1 and al != fp:
                            return False
                    return True
                else:
                    return False
        
        # Handle multiple initials case: "I. J." should match "I."
        # Split by spaces, dots, and hyphens to get individual initials
        abbrev_initials = [p.strip().rstrip('.').lstrip('-') for p in re.split(r'[\s.\-]+', abbrev_clean) if p.strip()]
        full_initials = [p.strip().rstrip('.').lstrip('-') for p in re.split(r'[\s.\-]+', full_clean) if p.strip()]
        
        # If both are multiple initials, check if they match appropriately
        if len(abbrev_initials) > 1 and len(full_initials) >= 1:
            # Handle cases like "l.g" vs "leslie g" or "i j" vs "i"
            # Also handle reverse case like "leslie g" vs "l.g"
            
            # Determine which one has the initials and which has full names
            if all(len(p) == 1 for p in abbrev_initials) and any(len(p) > 1 for p in full_initials):
                # abbrev has initials, full has names: "l g" vs "leslie g"
                # Must have same number of parts or fewer initials than full names
                if len(abbrev_initials) > len(full_initials):
                    return False
                for i, abbrev_initial in enumerate(abbrev_initials):
                    if i < len(full_initials):
                        if abbrev_initial != full_initials[i][0]:
                            return False
                return True
            elif any(len(p) > 1 for p in abbrev_initials) and all(len(p) == 1 for p in full_initials):
                # abbrev has names, full has initials: "leslie g" vs "l g"  
                # But only match if they have the same number of parts
                if len(abbrev_initials) != len(full_initials):
                    return False
                for i, full_initial in enumerate(full_initials):
                    if full_initial != abbrev_initials[i][0]:
                        return False
                return True
            else:
                # Mixed case or both same type, use original logic
                for i, abbrev_initial in enumerate(abbrev_initials):
                    if i < len(full_initials):
                        full_part = full_initials[i]
                        # If abbrev_initial is single letter and full_part is longer, compare with first letter
                        if len(abbrev_initial) == 1 and len(full_part) > 1:
                            if abbrev_initial != full_part[0]:
                                return False
                        # If both are single letters or same length, compare directly
                        elif abbrev_initial != full_part:
                            return False
                    # If abbrev has more initials than full, that's OK (extra initials ignored)
                return True
        
        # Otherwise, abbrev should be contained in full name
        return full.startswith(abbrev_clean)

    # Handle abbreviated vs full names
    def matches_abbreviated(abbrev_parts, full_parts):
        """Check if abbreviated name matches full name"""
        # Note: abbrev_parts can have more parts than full_parts in cases like:
        # "I. J. Smith" (3 parts) vs "I. Smith" (2 parts) where "I. J." should match "I."
        
        # Special case: single part abbreviated name vs single part full name
        # e.g., "A.-D." vs "Alexandru-Daniel"
        if len(abbrev_parts) == 1 and len(full_parts) == 1:
            return _matches_name_part(abbrev_parts[0], full_parts[0])
        
        # Last names must match exactly
        if abbrev_parts[-1] != full_parts[-1]:
            return False
        
        # Handle different scenarios based on number of parts
        if len(abbrev_parts) == len(full_parts):
            # Same number of parts - match each part except last (already checked)
            for i in range(len(abbrev_parts) - 1):
                if not _matches_name_part(abbrev_parts[i], full_parts[i]):
                    return False
        elif len(abbrev_parts) < len(full_parts):
            # Fewer abbreviated parts - match first parts
            # e.g., "Q." (1 part) vs "Qing Xue" (2 parts) - no first names to check
            # e.g., "A. Smith" (2 parts) vs "Alexander John Smith" (3 parts) - check "A." vs "Alexander"
            # e.g., "L.G. Valiant" (2 parts) vs "Leslie G. Valiant" (3 parts) - check "L.G." vs "Leslie G."
            num_first_names = len(abbrev_parts) - 1  # All but last part
            for i in range(num_first_names):
                # Special handling for concatenated initials like "L.G." vs multiple full names
                abbrev_part = abbrev_parts[i]
                if ('.' in abbrev_part and len(abbrev_part.rstrip('.')) > 1 and 
                    all(len(c) == 1 for c in abbrev_part.rstrip('.').replace('.', ''))):
                    # This looks like concatenated initials (e.g., "L.G.")
                    # Match against combined full parts
                    remaining_full_parts_count = len(full_parts) - len(abbrev_parts) + 1
                    combined_full = ' '.join(full_parts[i:i + remaining_full_parts_count])
                    if not _matches_name_part(abbrev_part, combined_full):
                        return False
                    # Skip the matched full parts
                    continue
                else:
                    # Regular single initial matching
                    if not _matches_name_part(abbrev_part, full_parts[i]):
                        return False
        elif len(abbrev_parts) > len(full_parts):
            # More abbreviated parts than full parts
            # e.g., "I. J. Smith" (3 parts) vs "I. Smith" (2 parts)
            # Check if the first parts of abbrev match the first parts of full
            num_full_first_names = len(full_parts) - 1  # All but last part of full
            
            # Build a combined abbreviated first name from multiple parts
            # "I. J." should be treated as one first name unit
            if num_full_first_names == 1:
                # full has one first name, abbrev has multiple first name parts
                
                # Special case: Handle "Nitin J." vs "N." - check if first name initial matches
                # e.g., abbrev_parts = ['nitin', 'j.', 'sanket'], full_parts = ['n.', 'sanket']
                if (len(abbrev_parts) >= 2 and 
                    len(full_parts[0].rstrip('.')) == 1 and 
                    len(abbrev_parts[0]) > 1):
                    # Check if first letter of full first name matches first letter of abbreviated first name
                    if abbrev_parts[0][0] == full_parts[0].rstrip('.'):
                        return True
                
                combined_abbrev_first = ' '.join(abbrev_parts[:-1])  # All but last
                if not _matches_name_part(combined_abbrev_first, full_parts[0]):
                    return False
            else:
                # More complex case - match part by part for available positions
                for i in range(min(num_full_first_names, len(abbrev_parts) - 1)):
                    if not _matches_name_part(abbrev_parts[i], full_parts[i]):
                        return False
        
        return True
    
    # Check if name1 is abbreviated form of name2
    if any('.' in part for part in parts1):
        return matches_abbreviated(parts1, parts2)
    
    # Check if name2 is abbreviated form of name1
    if any('.' in part for part in parts2):
        return matches_abbreviated(parts2, parts1)
    
    # For non-abbreviated names, compare first initials and last names
    if parts1[0][0] != parts2[0][0]:
        return False
    
    return True


def compare_authors(cited_authors: list, correct_authors: list, normalize_func=None) -> tuple:
    """
    Compare author lists to check if they match.
    This is the centralized, shared method used across all checker modules.
    
    Args:
        cited_authors: List of author names as cited (may contain "et al")
        correct_authors: List of correct author data (can be strings or dict objects)
        normalize_func: Optional function to normalize author names (deprecated)
        
    Returns:
        Tuple of (match_result, error_message)
    """
    # Extract author names from database data if they're dict objects
    if correct_authors and isinstance(correct_authors[0], dict):
        correct_names = [author.get('name', '') for author in correct_authors]
    else:
        correct_names = correct_authors[:]  # Make a copy to avoid modifying original
    
    # Clean up cited author names - remove "et al" and normalize
    cleaned_cited = []
    for author in cited_authors:
        # Remove reference numbers (e.g., "[1]")
        author = re.sub(r'^\[\d+\]', '', str(author))
        # Remove line breaks
        author = author.replace('\n', ' ')
        
        # Handle "et al" cases properly
        author_clean = author.strip()
        if author_clean.lower() == 'et al':
            # Skip pure "et al" entries
            continue
        elif 'et al' in author_clean.lower():
            # Remove "et al" from the author name (e.g., "S. M. Lundberg et al" -> "S. M. Lundberg")
            author_clean = re.sub(r'\s+et\s+al\.?', '', author_clean, flags=re.IGNORECASE).strip()
            if author_clean:  # Only add if something remains
                cleaned_cited.append(author_clean)
        else:
            cleaned_cited.append(author_clean)
    
    if not cleaned_cited:
        return True, "No authors to compare"
    
    if not correct_names:
        return False, "No correct authors provided"
    
    # Handle "et al" cases and length mismatches
    has_et_al = any('et al' in str(a).lower() for a in cited_authors)
    
    if len(cleaned_cited) < len(correct_names) and (has_et_al or len(cleaned_cited) <= 3):
        # Only compare the authors that are listed
        correct_names = correct_names[:len(cleaned_cited)]
    elif len(cleaned_cited) > len(correct_names) and len(correct_names) >= 3:
        # Use available correct authors
        cleaned_cited = cleaned_cited[:len(correct_names)]
    
    # If there's a big count mismatch and no "et al", it's likely an error
    if abs(len(cleaned_cited) - len(correct_names)) > 3 and not has_et_al:
        return False, "Author count mismatch"
    
    # Compare first author (most important) using the enhanced name matching
    if cleaned_cited and correct_names:
        # Use raw names for comparison (is_name_match handles normalization internally)
        cited_first = cleaned_cited[0]
        correct_first = correct_names[0]
        
        if not is_name_match(cited_first, correct_first):
            return False, f"First author mismatch: '{cited_first}' vs '{correct_first}'"
    
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
    
    # Ensure corrected_journal is a string (sometimes it can be a dict)
    if isinstance(corrected_journal, dict):
        corrected_journal = corrected_journal.get('name', '') if corrected_journal else ''
    elif corrected_journal and not isinstance(corrected_journal, str):
        corrected_journal = str(corrected_journal)
    
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
    
    # Ensure venue is a string (sometimes it can be a dict)
    if isinstance(correct_venue, dict):
        correct_venue = correct_venue.get('name', '') if correct_venue else ''
    elif correct_venue and not isinstance(correct_venue, str):
        correct_venue = str(correct_venue)
    
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
    
    # Ensure venue is a string (sometimes it can be a dict)
    if isinstance(correct_venue, dict):
        correct_venue = correct_venue.get('name', '') if correct_venue else ''
    elif correct_venue and not isinstance(correct_venue, str):
        correct_venue = str(correct_venue)
    
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
    
    # Handle common technical term variations before other processing
    # This helps with terms like "mmWave" vs "mm wave", "AI-driven" vs "AI driven", etc.
    tech_patterns = [
        (r'\bmmwave\b', 'mm wave'),  # mmWave -> mm wave
        (r'\bmm\s+wave\b', 'mmwave'),  # mm wave -> mmWave (for reverse check)
        (r'\bai\s*-?\s*driven\b', 'ai driven'),  # AI-driven/AI-Driven -> ai driven
        (r'\bml\s*-?\s*based\b', 'ml based'),  # ML-based -> ml based
        (r'\b6g\s+networks?\b', '6g network'),  # 6G networks -> 6g network
        (r'\b5g\s+networks?\b', '5g network'),  # 5G networks -> 5g network
    ]
    
    t1_tech_normalized = t1
    t2_tech_normalized = t2
    for pattern, replacement in tech_patterns:
        t1_tech_normalized = re.sub(pattern, replacement, t1_tech_normalized)
        t2_tech_normalized = re.sub(pattern, replacement, t2_tech_normalized)
    
    # Check for match after tech term normalization
    if t1_tech_normalized == t2_tech_normalized:
        return 1.0
    
    # Normalize hyphens to handle hyphenation differences
    # Replace hyphens with spaces and normalize whitespace
    t1_dehyphenated = re.sub(r'-', ' ', t1_tech_normalized)
    t1_dehyphenated = re.sub(r'\s+', ' ', t1_dehyphenated).strip()
    t2_dehyphenated = re.sub(r'-', ' ', t2_tech_normalized)
    t2_dehyphenated = re.sub(r'\s+', ' ', t2_dehyphenated).strip()
    
    # Check for match after hyphen normalization
    if t1_dehyphenated == t2_dehyphenated:
        return 1.0
    
    # Handle compound word variations - normalize common academic compound words
    # This fixes cases like "pre trained" vs "pretrained", "multi modal" vs "multimodal"
    compound_patterns = [
        (r'\bpre\s+trained\b', 'pretrained'),
        (r'\bpretrained\b', 'pre trained'),  # reverse mapping
        (r'\bmulti\s+modal\b', 'multimodal'),
        (r'\bmultimodal\b', 'multi modal'),
        (r'\bmulti\s+task\b', 'multitask'),
        (r'\bmultitask\b', 'multi task'),
        (r'\bmulti\s+agent\b', 'multiagent'),
        (r'\bmultiagent\b', 'multi agent'),
        (r'\bmulti\s+class\b', 'multiclass'),
        (r'\bmulticlass\b', 'multi class'),
        (r'\bmulti\s+layer\b', 'multilayer'),
        (r'\bmultilayer\b', 'multi layer'),
        (r'\bco\s+training\b', 'cotraining'),
        (r'\bcotraining\b', 'co training'),
        (r'\bfew\s+shot\b', 'fewshot'),
        (r'\bfewshot\b', 'few shot'),
        (r'\bzero\s+shot\b', 'zeroshot'),
        (r'\bzeroshot\b', 'zero shot'),
        (r'\bone\s+shot\b', 'oneshot'),
        (r'\boneshot\b', 'one shot'),
        (r'\breal\s+time\b', 'realtime'),
        (r'\brealtime\b', 'real time'),
        (r'\breal\s+world\b', 'realworld'),
        (r'\brealworld\b', 'real world'),
        
        # Handle BERT variants and technical terms with hyphens/spaces
        (r'\bscib\s+ert\b', 'scibert'),  # SciB ERT -> SciBERT
        (r'\bscibert\b', 'scib ert'),    # SciBERT -> SciB ERT (reverse mapping)
        (r'\bbio\s+bert\b', 'biobert'),  # Bio BERT -> BioBERT
        (r'\bbiobert\b', 'bio bert'),    # BioBERT -> Bio BERT
        (r'\brob\s+erta\b', 'roberta'),  # Rob ERTa -> RoBERTa
        (r'\broberta\b', 'rob erta'),    # RoBERTa -> Rob ERTa
        (r'\bdeb\s+erta\b', 'deberta'),  # Deb ERTa -> DeBERTa
        (r'\bdeberta\b', 'deb erta'),    # DeBERTa -> Deb ERTa
        (r'\bon\s+line\b', 'online'),
        (r'\bonline\b', 'on line'),
        (r'\boff\s+line\b', 'offline'),
        (r'\boffline\b', 'off line'),
    ]
    
    t1_compound_normalized = t1_dehyphenated
    t2_compound_normalized = t2_dehyphenated
    for pattern, replacement in compound_patterns:
        t1_compound_normalized = re.sub(pattern, replacement, t1_compound_normalized)
        t2_compound_normalized = re.sub(pattern, replacement, t2_compound_normalized)
    
    # Check for match after compound word normalization
    if t1_compound_normalized == t2_compound_normalized:
        return 1.0
    
    # Additional normalization: remove punctuation for comparison
    t1_normalized = re.sub(r'[^\w\s]', ' ', t1_compound_normalized)
    t1_normalized = re.sub(r'\s+', ' ', t1_normalized).strip()
    t2_normalized = re.sub(r'[^\w\s]', ' ', t2_compound_normalized)
    t2_normalized = re.sub(r'\s+', ' ', t2_normalized).strip()
    
    # Check for match after full normalization
    if t1_normalized == t2_normalized:
        return 1.0
    
    # Handle edition differences - check if one title is the same as the other but with edition info
    # Common edition patterns: "Second Edition", "2nd Edition", "Revised Edition", etc.
    edition_patterns = [
        r'\s+second\s+edition\s*$',
        r'\s+third\s+edition\s*$',
        r'\s+fourth\s+edition\s*$',
        r'\s+fifth\s+edition\s*$',
        r'\s+\d+(?:st|nd|rd|th)\s+edition\s*$',
        r'\s+revised\s+edition\s*$',
        r'\s+updated\s+edition\s*$',
        r'\s+new\s+edition\s*$',
        r'\s+latest\s+edition\s*$',
    ]
    
    # Check if removing edition info from one title makes them match
    for pattern in edition_patterns:
        t1_no_edition = re.sub(pattern, '', t1_normalized, flags=re.IGNORECASE).strip()
        t2_no_edition = re.sub(pattern, '', t2_normalized, flags=re.IGNORECASE).strip()
        
        # If removing edition info from either title makes them equal, they're the same work
        if (t1_no_edition == t2_normalized) or (t2_no_edition == t1_normalized) or (t1_no_edition == t2_no_edition):
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


def are_venues_substantially_different(venue1: str, venue2: str) -> bool:
    """
    Check if two venue names are substantially different (not just minor variations).
    This function uses a generic approach to handle academic venue abbreviations and formats.
    
    Args:
        venue1: First venue name
        venue2: Second venue name
        
    Returns:
        True if venues are substantially different, False if they match/overlap
    """
    if not venue1 or not venue2:
        return bool(venue1 != venue2)
    
    def expand_abbreviations(text):
        """Generic abbreviation expansion using common academic patterns"""
        # Common academic abbreviations mapping
        common_abbrevs = {
            # IEEE specific abbreviations (only expand with periods, not full words)
            'robot.': 'robotics',
            'autom.': 'automation',
            'lett.': 'letters',
            'trans.': 'transactions',
            'syst.': 'systems',
            'netw.': 'networks',
            'learn.': 'learning',
            'ind.': 'industrial',
            'electron.': 'electronics',
            'mechatron.': 'mechatronics',
            'intell.': 'intelligent',
            'transp.': 'transportation',
            'contr.': 'control',
            'mag.': 'magazine',
            
            # General academic abbreviations (only expand with periods)
            'int.': 'international',
            'intl.': 'international', 
            'conf.': 'conference',
            'j.': 'journal',
            'proc.': 'proceedings',
            'assoc.': 'association',
            'comput.': 'computer',
            'sci.': 'science',
            'eng.': 'engineering',
            'res.': 'research',
            'dev.': 'development',
            'technol.': 'technology',
            'adv.': 'advanced',
            'artif.': 'artificial',
            'mach.': 'machine',
            'anal.': 'analysis',
            'appl.': 'applications',
            'theor.': 'theoretical',
            'pract.': 'practical',
            'found.': 'foundations',
            'princ.': 'principles',
            'mech.': 'mechanical',
            'des.': 'design',
            'manuf.': 'manufacturing',
            'syst.': 'systems',
            
            # Common venue name patterns
            'iros': 'international conference on intelligent robots and systems',
            'icra': 'international conference on robotics and automation',
            'corl': 'conference on robot learning',
            'rss': 'robotics science and systems',
            'humanoids': 'ieee international conference on humanoid robots',
            'iser': 'international symposium on experimental robotics',
            'case': 'ieee international conference on automation science and engineering',
            'ddcls': 'data driven control and learning systems conference',
        }
        
        # Apply abbreviation expansion
        words = text.split()
        expanded_words = []
        
        for word in words:
            # Remove punctuation for lookup but preserve it
            clean_word = re.sub(r'[.,;:]$', '', word.lower())
            punct = word[-1] if word and word[-1] in '.,;:' else ''
            
            if clean_word in common_abbrevs:
                expanded_words.append(common_abbrevs[clean_word])
            else:
                expanded_words.append(word)
        
        return ' '.join(expanded_words)
    
    def create_acronym_from_title(title):
        """Generate potential acronyms from full titles"""
        # Remove common words that don't contribute to acronyms
        stop_words = {'the', 'a', 'an', 'of', 'on', 'in', 'at', 'to', 'for', 'with', 'by', 'and', 'or'}
        words = [w for w in title.lower().split() if w not in stop_words and len(w) > 2]
        
        # Create acronym from first letters
        if len(words) >= 2:
            return ''.join(word[0] for word in words[:6])  # Limit to 6 chars for reasonable acronyms
        return None
    
    def extract_conference_acronyms(text):
        """Extract potential conference acronyms from text"""
        # Look for patterns like "IROS, 2012" or "CoRL, 2023" 
        acronym_matches = re.findall(r'\b([A-Z]{3,8})\s*,?\s*\d{4}', text)
        
        # Also look for standalone acronyms at the beginning
        start_acronym = re.match(r'^([A-Z]{3,8})\b', text.strip())
        if start_acronym:
            acronym_matches.append(start_acronym.group(1))
            
        return [a.lower() for a in acronym_matches]
    
    def normalize_venue(venue):
        """Normalize venue names with generic abbreviation handling"""
        venue_lower = venue.lower().strip()
        
        # Remove years, volumes, pages, and other citation metadata
        venue_lower = re.sub(r',?\s*\d{4}[a-z]?\s*$', '', venue_lower)  # Years like "2024" or "2024b"
        venue_lower = re.sub(r',?\s*\(\d{4}\)$', '', venue_lower)  # Years in parentheses
        venue_lower = re.sub(r',?\s*vol\.\s*\d+.*$', '', venue_lower)  # Volume info
        venue_lower = re.sub(r',?\s*\d+\(\d+\).*$', '', venue_lower)  # Issue info
        venue_lower = re.sub(r',?\s*pp?\.\s*\d+.*$', '', venue_lower)  # Page info
        venue_lower = re.sub(r'\s*\(print\).*$', '', venue_lower)  # Print designation
        venue_lower = re.sub(r'\s*\(\d{4}\.\s*print\).*$', '', venue_lower)  # Year.Print
        
        # Remove procedural prefixes
        prefixes_to_remove = [
            r'^\d{4}\s+\d+(st|nd|rd|th)\s+',  # "2012 IEEE/RSJ"
            r'^\d{4}\s+',                     # "2024 "
            r'^proceedings\s+(of\s+)?(the\s+)?',
            r'^proc\.\s+(of\s+)?(the\s+)?',
            r'^in\s+',
        ]
        
        for prefix_pattern in prefixes_to_remove:
            venue_lower = re.sub(prefix_pattern, '', venue_lower)
        
        # Expand abbreviations generically
        venue_lower = expand_abbreviations(venue_lower)
        
        # Remove organization prefixes/suffixes that don't affect identity
        venue_lower = re.sub(r'^ieee\s+', '', venue_lower)  # Remove IEEE prefix
        venue_lower = re.sub(r'^ieee/\w+\s+', '', venue_lower)  # Remove "IEEE/RSJ " etc
        venue_lower = re.sub(r'\s+ieee\s*$', '', venue_lower)  # Remove IEEE suffix
        venue_lower = re.sub(r'/\w+\s+', ' ', venue_lower)  # Remove "/ACM " style org separators
        
        # Clean up punctuation and spacing
        venue_lower = re.sub(r'[.,;:]', '', venue_lower)  # Remove punctuation
        venue_lower = re.sub(r'\s+', ' ', venue_lower)     # Normalize whitespace
        venue_lower = venue_lower.strip()
        
        return venue_lower
    
    def check_acronym_match(venue1, venue2):
        """Check if one venue is an acronym of the other"""
        # Extract acronyms from both venues
        acronyms1 = extract_conference_acronyms(venue1)
        acronyms2 = extract_conference_acronyms(venue2)
        
        # Check if either venue contains known acronyms
        norm1 = normalize_venue(venue1)
        norm2 = normalize_venue(venue2)
        
        # Generate potential acronyms from full names
        potential_acronym1 = create_acronym_from_title(norm1)
        potential_acronym2 = create_acronym_from_title(norm2)
        
        # Check various acronym matching scenarios
        if acronyms1 and potential_acronym2:
            if any(acr == potential_acronym2 for acr in acronyms1):
                return True
                
        if acronyms2 and potential_acronym1:
            if any(acr == potential_acronym1 for acr in acronyms2):
                return True
        
        # Check direct acronym matches
        if acronyms1 and acronyms2:
            if any(a1 == a2 for a1 in acronyms1 for a2 in acronyms2):
                return True
        
        return False
    
    # Normalize both venues first
    norm1 = normalize_venue(venue1)
    norm2 = normalize_venue(venue2)
    
    # Direct match after normalization (highest priority)
    if norm1 == norm2:
        return False
    
    # Check if one venue is likely an acronym of the other
    if check_acronym_match(venue1, venue2):
        return False
    
    # Calculate word-level similarity with fuzzy matching
    words1 = set(norm1.split())
    words2 = set(norm2.split())
    
    # Remove common stop words that don't affect venue identity
    stop_words = {'the', 'a', 'an', 'of', 'on', 'in', 'at', 'to', 'for', 'with', 'by', 'and', 'or'}
    words1 = words1 - stop_words
    words2 = words2 - stop_words
    
    # If either venue has no meaningful words, consider them different
    if not words1 or not words2:
        return True
    
    def words_are_similar(word1, word2):
        """Check if two words are similar (roots, abbreviations, etc.)"""
        # Exact match
        if word1 == word2:
            return True
            
        # Check if one is an abbreviation of the other
        # Remove periods for comparison
        clean1 = word1.rstrip('.')
        clean2 = word2.rstrip('.')
        
        # Short word is prefix of longer word (like "sci" -> "science")
        if len(clean1) >= 3 and len(clean2) >= 3:
            if clean1.startswith(clean2) or clean2.startswith(clean1):
                return True
        
        # Check common word root patterns
        word_roots = {
            'robot': 'robotics', 'robotics': 'robot',
            'sci': 'science', 'science': 'sci',
            'adv': 'advanced', 'advanced': 'adv', 
            'intell': 'intelligent', 'intelligent': 'intell',
            'syst': 'systems', 'systems': 'syst',
            'int': 'international', 'international': 'int',
            'res': 'research', 'research': 'res',
            'autom': 'automation', 'automation': 'autom',
            'lett': 'letters', 'letters': 'lett',
            'trans': 'transactions', 'transactions': 'trans',
            'electron': 'electronics', 'electronics': 'electron',
            'mech': 'mechanical', 'mechanical': 'mech',
            'eng': 'engineering', 'engineering': 'eng',
            'comput': 'computer', 'computer': 'comput',
            'j': 'journal', 'journal': 'j',
            'des': 'design', 'design': 'des',
            'soft': 'soft',  # Keep soft as is
        }
        
        # Check if words are related through root mappings
        if clean1 in word_roots and word_roots[clean1] == clean2:
            return True
        if clean2 in word_roots and word_roots[clean2] == clean1:
            return True
            
        return False
    
    # Order-aware fuzzy matching - words should match in sequence
    words1_list = list(words1)
    words2_list = list(words2)
    
    # If word counts are very different, they're likely different venues
    if len(words1) > 0 and len(words2) > 0:
        ratio = max(len(words1), len(words2)) / min(len(words1), len(words2))
        if ratio > 2.0:  # One has more than twice as many words
            return True
    
    # Try to match words in order, allowing for some flexibility
    matched_pairs = 0
    
    # Use dynamic programming-like approach to find best alignment
    if len(words1_list) <= len(words2_list):
        shorter, longer = words1_list, words2_list
    else:
        shorter, longer = words2_list, words1_list
    
    # For each word in shorter list, find best match in remaining longer list
    used_indices = set()
    for i, short_word in enumerate(shorter):
        best_match_idx = None
        
        # Look for matches starting from current position with some flexibility
        search_start = max(0, i - 1)  # Allow some reordering
        search_end = min(len(longer), i + 3)  # But not too much
        
        for j in range(search_start, search_end):
            if j not in used_indices and words_are_similar(short_word, longer[j]):
                best_match_idx = j
                break
        
        if best_match_idx is not None:
            matched_pairs += 1
            used_indices.add(best_match_idx)
    
    # Calculate similarity based on how well shorter list is covered
    coverage = matched_pairs / len(shorter) if shorter else 0
    
    # Consider venues the same if they have 80%+ coverage of shorter list
    return coverage < 0.8


def find_best_match(search_results, cleaned_title, year=None, authors=None):
    """
    Find the best match from search results using similarity scoring
    
    Args:
        search_results: List of search result dictionaries
        cleaned_title: The cleaned title to match against
        year: Optional year for bonus scoring
        authors: Optional list of author names for additional scoring
        
    Returns:
        Tuple of (best_match, best_score) or (None, 0) if no good match
    """
    if not search_results:
        return None, 0
    
    # Collect all results with their scores for stable sorting
    scored_results = []
    
    for result in search_results:
        result_title = result.get('title') or result.get('display_name', '')
        
        # Calculate similarity score using utility function
        score = calculate_title_similarity(cleaned_title, result_title)
        
        # Bonus for year match
        result_year = result.get('publication_year') or result.get('year')
        if year and result_year and year == result_year:
            score += 0.1
        
        # Bonus for first author match when multiple papers have same/similar titles
        if authors and len(authors) > 0:
            result_authors = result.get('authors', [])
            if result_authors and len(result_authors) > 0:
                cited_first_author = authors[0]
                result_first_author = result_authors[0]
                
                # Extract author name from different formats
                if isinstance(result_first_author, dict):
                    result_first_author_name = result_first_author.get('name', '')
                else:
                    result_first_author_name = str(result_first_author)
                
                # Check if first authors match using existing name matching logic
                if is_name_match(cited_first_author, result_first_author_name):
                    score += 0.2  # Significant bonus for first author match
        
        scored_results.append((score, result))
    
    # Sort by score (descending), then by title for stable ordering when scores are equal
    scored_results.sort(key=lambda x: (-x[0], x[1].get('title', '')))
    
    if scored_results:
        best_score, best_match = scored_results[0]
        return best_match, best_score
    
    return None, 0


def normalize_arxiv_url(url: str) -> str:
    """
    Normalize ArXiv URLs to a standard format for comparison.
    
    Args:
        url: The URL to normalize
        
    Returns:
        Normalized URL (abs format for ArXiv URLs, original for others)
    """
    if not url or 'arxiv.org' not in url:
        return url
    
    # Extract ArXiv ID from URL
    arxiv_match = re.search(r'arxiv\.org/(?:abs|pdf)/([^\s/?#]+?)(?:\.pdf|v\d+)?(?:[?\#]|$)', url)
    if arxiv_match:
        arxiv_id = arxiv_match.group(1)
        return f"https://arxiv.org/abs/{arxiv_id}"
    
    return url


def deduplicate_urls(urls: List[str]) -> List[str]:
    """
    Deduplicate URLs by normalizing ArXiv URLs, removing equivalent ones.
    
    Args:
        urls: List of URLs to deduplicate
        
    Returns:
        List of unique URLs (with ArXiv URLs normalized to abs format)
    """
    if not urls:
        return []
    
    # Filter out empty URLs
    valid_urls = [url for url in urls if url]
    if not valid_urls:
        return []
    
    if len(valid_urls) == 1:
        return [valid_urls[0]]
    
    # Normalize all URLs for comparison and keep the preferred format
    normalized_urls = {}
    for url in valid_urls:
        normalized = normalize_arxiv_url(url)
        if normalized not in normalized_urls:
            # For ArXiv URLs, prefer the normalized (abs) format
            if 'arxiv.org' in normalized and normalized != url:
                normalized_urls[normalized] = normalized
            else:
                normalized_urls[normalized] = url
    
    # Return all unique URLs
    return list(normalized_urls.values())