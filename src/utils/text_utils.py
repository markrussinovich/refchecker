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
    
    # If one is a substring of the other, consider it a match
    if name1 in name2 or name2 in name1:
        return True
    
    # Split into parts (first name, last name, etc.)
    parts1 = name1.split()
    parts2 = name2.split()
    
    # Special case: Handle "Last F" vs "First Last" patterns
    # e.g., "Husain W" vs "Waqar Husain", "Rammstedt B" vs "Beatrice Rammstedt"
    if (len(parts1) == 2 and len(parts2) == 2 and 
        len(parts1[1]) == 1 and len(parts2[0]) > 1 and len(parts2[1]) > 1):
        # parts1 is "Last F" format, parts2 is "First Last" format
        last_name1 = parts1[0]  # "Husain"
        first_initial1 = parts1[1]  # "W"
        first_name2 = parts2[0]  # "Waqar" 
        last_name2 = parts2[1]  # "Husain"
        
        if (last_name1 == last_name2 and 
            first_initial1 == first_name2[0]):
            return True
    
    if (len(parts1) == 2 and len(parts2) == 2 and 
        len(parts1[0]) > 1 and len(parts1[1]) > 1 and len(parts2[1]) == 1):
        # parts1 is "First Last" format, parts2 is "Last F" format  
        first_name1 = parts1[0]  # "Waqar"
        last_name1 = parts1[1]  # "Husain"
        last_name2 = parts2[0]  # "Husain"
        first_initial2 = parts2[1]  # "W"
        
        if (last_name1 == last_name2 and 
            first_name1[0] == first_initial2):
            return True
    
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

    # Special case: Handle "Last FI" vs "F. I. Last" patterns (with periods)
    # e.g., "Digman JM" vs "J. M. Digman", "Soto CJ" vs "C. Soto" 
    if (len(parts1) == 2 and len(parts2) >= 2 and 
        len(parts1[1]) >= 2 and all(len(p.rstrip('.')) == 1 for p in parts2[:-1]) and len(parts2[-1]) > 1):
        # parts1 is "Last FI" format, parts2 is "F. I. Last" format
        last_name1 = parts1[0]  # "Digman"
        initials1 = parts1[1]  # "JM"
        last_name2 = parts2[-1]  # "Digman"
        initials2 = [p.rstrip('.') for p in parts2[:-1]]  # ["J", "M"]
        
        if (last_name1 == last_name2 and 
            len(initials1) == len(initials2) and
            all(initials1[i] == initials2[i] for i in range(len(initials1)))):
            return True
    
    if (len(parts1) >= 2 and len(parts2) == 2 and 
        all(len(p.rstrip('.')) == 1 for p in parts1[:-1]) and len(parts1[-1]) > 1 and len(parts2[1]) >= 2):
        # parts1 is "F. I. Last" format, parts2 is "Last FI" format  
        last_name1 = parts1[-1]  # "Digman"
        initials1 = [p.rstrip('.') for p in parts1[:-1]]  # ["J", "M"]
        last_name2 = parts2[0]  # "Digman"
        initials2 = parts2[1]  # "JM"
        
        if (last_name1 == last_name2 and 
            len(initials1) == len(initials2) and
            all(initials1[i] == initials2[i] for i in range(len(initials1)))):
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
    
    # Compare last names (last parts) - they must match
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
        
        # If both are multiple initials, check if first matches
        if len(abbrev_initials) > 1 and len(full_initials) >= 1:
            # "I J" should match "I" - first initial should match
            return abbrev_initials[0] == full_initials[0] if abbrev_initials[0] and full_initials[0] else False
        
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
            num_first_names = len(abbrev_parts) - 1  # All but last part
            for i in range(num_first_names):
                if not _matches_name_part(abbrev_parts[i], full_parts[i]):
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
    
    # Additional normalization: remove punctuation for comparison
    t1_normalized = re.sub(r'[^\w\s]', ' ', t1_dehyphenated)
    t1_normalized = re.sub(r'\s+', ' ', t1_normalized).strip()
    t2_normalized = re.sub(r'[^\w\s]', ' ', t2_dehyphenated)
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
    This function handles various venue name formats, acronyms, and overlaps.
    
    Args:
        venue1: First venue name
        venue2: Second venue name
        
    Returns:
        True if venues are substantially different, False if they match/overlap
    """
    if not venue1 or not venue2:
        return bool(venue1 != venue2)
    
    # Case 0: Handle specific IEEE journal abbreviation patterns first
    def normalize_ieee_journal(venue):
        """Normalize IEEE journal names to handle standard abbreviations"""
        venue_lower = venue.lower().strip()
        
        # IEEE journal abbreviation mappings
        ieee_mappings = {
            'ieee trans. commun.': 'ieee transactions on communications',
            'ieee trans. wireless commun.': 'ieee transactions on wireless communications', 
            'ieee trans. netw. sci. eng.': 'ieee transactions on network science and engineering',
            'ieee trans. pattern anal. mach. intell.': 'ieee transactions on pattern analysis and machine intelligence',
            'ieee trans. image process.': 'ieee transactions on image processing',
            'ieee trans. signal process.': 'ieee transactions on signal processing',
            'ieee trans. cogn. commun. netw.': 'ieee transactions on cognitive communications and networking',
            'ieee j. sel. topics signal process.': 'ieee journal on selected topics in signal processing',
            'ieee netw. lett.': 'ieee networking letters',
            'ieee commun. lett.': 'ieee communications letters',
            'ieee commun. mag.': 'ieee communications magazine',
            'ieee veh. technol. mag.': 'ieee vehicular technology magazine',
            'ieee commun. surveys tuts.': 'ieee communications surveys and tutorials',
            'nat. mach. intell.': 'nature machine intelligence',
            # ACM Transactions abbreviations
            'acm trans. inf. syst.': 'acm transactions on information systems',
            'acm transactions on information systems (tois)': 'acm transactions on information systems',
            'acm trans. comput. syst.': 'acm transactions on computer systems',
            'acm transactions on computer systems (tocs)': 'acm transactions on computer systems',
            'acm trans. database syst.': 'acm transactions on database systems',
            'acm transactions on database systems (tods)': 'acm transactions on database systems',
            'acm trans. softw. eng. methodol.': 'acm transactions on software engineering and methodology',
            'acm transactions on software engineering and methodology (tosem)': 'acm transactions on software engineering and methodology',
            # Common conference abbreviations - major ML/CV/AI conferences
            'proc. ieee int. conf. commun. (icc)': 'ieee international conference on communications',
            'proc. ieee wireless commun. and netw. conf. (wcnc)': 'ieee wireless communications and networking conference', 
            'proc. ieee global commun. conf. (globecom)': 'global communications conference',
            'proc. int. conf. mach. learn. (icml)': 'international conference on machine learning',
            'adv. neural inf. process. syst.': 'neural information processing systems',
            'adv. neural inform. process. syst.': 'neural information processing systems', # Alternative NeurIPS abbreviation
            'proc. ieee.': 'proceedings of the ieee',
            
            # Journal abbreviations
            'j. mach. learn. res.': 'journal of machine learning research',
            'jmlr': 'journal of machine learning research',
            
            # Machine Learning conferences
            'int. conf. mach. learn.': 'international conference on machine learning',
            'icml': 'international conference on machine learning',
            'int. conf. learn. represent.': 'international conference on learning representations',
            'iclr': 'international conference on learning representations',
            
            # Computer Vision conferences  
            'int. conf. comput. vis.': 'ieee international conference on computer vision',
            'iccv': 'ieee international conference on computer vision',
            # Also map to the version without IEEE prefix
            'international conference on computer vision': 'int. conf. comput. vis.',
            'ieee conf. comput. vis. pattern recog.': 'computer vision and pattern recognition',
            'cvpr': 'computer vision and pattern recognition',
            'eur. conf. comput. vis.': 'european conference on computer vision',
            'eccv': 'european conference on computer vision',
            
            # AI conferences
            'aaai conf. artif. intell.': 'aaai conference on artificial intelligence',
            'aaai': 'aaai conference on artificial intelligence',
            'int. joint conf. artif. intell.': 'international joint conference on artificial intelligence',
            'ijcai': 'international joint conference on artificial intelligence',
            
            # NLP conferences
            'annu. meet. assoc. comput. linguist.': 'annual meeting of the association for computational linguistics',
            'acl': 'annual meeting of the association for computational linguistics',
            'conf. empir. methods nat. lang. process.': 'conference on empirical methods in natural language processing',
            'emnlp': 'conference on empirical methods in natural language processing',
            # Add reverse mappings for when the full name is cited and abbreviation is correct
            'ieee transactions on communications': 'ieee trans. commun.',
            'ieee transactions on wireless communications': 'ieee trans. wireless commun.',
            'ieee transactions on network science and engineering': 'ieee trans. netw. sci. eng.',
            'ieee transactions on pattern analysis and machine intelligence': 'ieee trans. pattern anal. mach. intell.',
            'ieee transactions on image processing': 'ieee trans. image process.',
            'ieee transactions on signal processing': 'ieee trans. signal process.',
            'ieee transactions on cognitive communications and networking': 'ieee trans. cogn. commun. netw.',
            'ieee journal on selected topics in signal processing': 'ieee j. sel. topics signal process.',
            'ieee networking letters': 'ieee netw. lett.',
            'ieee communications letters': 'ieee commun. lett.',
            'ieee communications magazine': 'ieee commun. mag.',
            'ieee vehicular technology magazine': 'ieee veh. technol. mag.',
            'ieee communications surveys and tutorials': 'ieee commun. surveys tuts.',
            'nature machine intelligence': 'nat. mach. intell.',
            # ACM Transactions reverse mappings
            'acm transactions on information systems': 'acm trans. inf. syst.',
            'acm transactions on computer systems': 'acm trans. comput. syst.',
            'acm transactions on database systems': 'acm trans. database syst.',
            'acm transactions on software engineering and methodology': 'acm trans. softw. eng. methodol.',
            # Reverse conference mappings
            'ieee international conference on communications': 'proc. ieee int. conf. commun. (icc)',
            'ieee wireless communications and networking conference': 'proc. ieee wireless commun. and netw. conf. (wcnc)',
            'global communications conference': 'proc. ieee global commun. conf. (globecom)',
            'international conference on machine learning': 'int. conf. mach. learn.',
            'neural information processing systems': 'adv. neural inf. process. syst.',
            'proceedings of the ieee': 'proc. ieee.',
            
            # Journal reverse mappings
            'journal of machine learning research': 'j. mach. learn. res.',
            
            # Reverse ML conference mappings
            'international conference on learning representations': 'int. conf. learn. represent.',
            
            # Reverse CV conference mappings
            'ieee international conference on computer vision': 'int. conf. comput. vis.',
            'computer vision and pattern recognition': 'ieee conf. comput. vis. pattern recog.',
            'european conference on computer vision': 'eur. conf. comput. vis.',
            
            # Reverse AI conference mappings
            'aaai conference on artificial intelligence': 'aaai conf. artif. intell.',
            'international joint conference on artificial intelligence': 'int. joint conf. artif. intell.',
            
            # Reverse NLP conference mappings
            'annual meeting of the association for computational linguistics': 'annu. meet. assoc. comput. linguist.',
            'conference on empirical methods in natural language processing': 'conf. empir. methods nat. lang. process.',
            
            # Database and Information Management conferences
            'international conference on scientific and statistical database management': 'international conference on statistical and scientific database management',
            'international conference on statistical and scientific database management': 'international conference on scientific and statistical database management',
            '29th international conference on scientific and statistical database management': 'international conference on statistical and scientific database management',
            'in proceedings of the 29th international conference on scientific and statistical database management': 'international conference on statistical and scientific database management',
            'proceedings of the 29th international conference on scientific and statistical database management': 'international conference on statistical and scientific database management',
            
            # Information and Knowledge Management conferences  
            'international conference on information and knowledge management': 'acm international conference on information and knowledge management',
            'acm international conference on information and knowledge management': 'international conference on information and knowledge management',
            'conference on information and knowledge management': 'international conference on information and knowledge management',
            'acm on conference on information and knowledge management': 'international conference on information and knowledge management',
            '2017 acm on conference on information and knowledge management': 'international conference on information and knowledge management',
            'in proceedings of the 2017 acm on conference on information and knowledge management': 'international conference on information and knowledge management',
            'proceedings of the 2017 acm on conference on information and knowledge management': 'international conference on information and knowledge management',
            
            # SIGIR conferences
            'annual international acm sigir conference on research and development in information retrieval': 'international acm sigir conference on research and development in information retrieval',
            'international acm sigir conference on research and development in information retrieval': 'annual international acm sigir conference on research and development in information retrieval',
            'acm sigir conference on research and development in information retrieval': 'annual international acm sigir conference on research and development in information retrieval',
            'sigir conference on research and development in information retrieval': 'annual international acm sigir conference on research and development in information retrieval',
            '45th international acm sigir conference on research and development in information retrieval': 'annual international acm sigir conference on research and development in information retrieval',
            'in proceedings of the 45th international acm sigir conference on research and development in information retrieval': 'annual international acm sigir conference on research and development in information retrieval',
            'proceedings of the 45th international acm sigir conference on research and development in information retrieval': 'annual international acm sigir conference on research and development in information retrieval',
            
            # Knowledge and Systems Engineering conferences
            'international conference on knowledge and systems engineering': 'kse',
            'kse': 'international conference on knowledge and systems engineering',
            '15th international conference on knowledge and systems engineering': 'international conference on knowledge and systems engineering',
            'in 2023 15th international conference on knowledge and systems engineering': 'international conference on knowledge and systems engineering',
            '2023 15th international conference on knowledge and systems engineering': 'international conference on knowledge and systems engineering',
            
            # ECML/PKDD conferences
            'joint european conference on machine learning and knowledge discovery in databases': 'ecml/pkdd',
            'ecml/pkdd': 'joint european conference on machine learning and knowledge discovery in databases',
            'european conference on machine learning and knowledge discovery in databases': 'ecml/pkdd',
            'ecml pkdd': 'joint european conference on machine learning and knowledge discovery in databases',
            'in joint european conference on machine learning and knowledge discovery in databases': 'ecml/pkdd',
        }
        
        # Normalize for comparison - handle common variations
        # Remove year prefixes/suffixes and normalize separators
        normalized = re.sub(r'^\d{4}\s+', '', venue_lower)  # Remove year prefix like "2024 "
        normalized = re.sub(r'\s+\d{4}$', '', normalized)   # Remove year suffix like " 2024"
        normalized = normalized.replace(' & ', ' and ')     # Normalize & to "and"
        normalized = normalized.replace('&', 'and')         # Handle &amp; etc
        
        # Remove common procedural prefixes and publisher information
        # Handle "Proceedings of the [ordinal] [publisher]" patterns with careful conference name preservation
        
        # Special handling for ACM proceedings with ordinal numbers - preserve conference name
        # Pattern: "proceedings of the 31st acm international conference..." -> "international conference..."
        acm_ordinal_match = re.search(r'^proceedings\s+of\s+(the\s+)?\d+(st|nd|rd|th)\s+acm\s+(.*)', normalized)
        if acm_ordinal_match:
            # Preserve everything after "ACM" as the actual conference name
            conference_name = acm_ordinal_match.group(3).strip()
            normalized = conference_name
        else:
            # Handle companion proceedings pattern: "companion proceedings of the acm on web conference 2024"
            companion_match = re.search(r'^companion\s+proceedings\s+of\s+(the\s+)?acm\s+on\s+(.*)', normalized)
            if companion_match:
                # Extract conference name and normalize it
                conference_name = companion_match.group(2).strip()
                # Remove year if present
                conference_name = re.sub(r'\s+\d{4}$', '', conference_name)
                # Convert "web conference" -> "the web conference"
                if conference_name == 'web conference':
                    conference_name = 'the web conference'
                normalized = conference_name
            else:
                # Apply other prefix removal patterns
                prefixes_to_remove = [
                    r'^proceedings\s+of\s+(the\s+)?acm\s+',
                    r'^proceedings\s+of\s+(the\s+)?\d+(st|nd|rd|th)\s+',
                    r'^proceedings\s+of\s+(the\s+)?',
                    r'^companion\s+proceedings\s+of\s+(the\s+)?acm\s+on\s+',
                    r'^companion\s+proceedings\s+of\s+(the\s+)?\d+(st|nd|rd|th)\s+acm\s+',
                    r'^in\s+proceedings\s+of\s+(the\s+)?',
                    r'^advances\s+in\s+',
                    r'^\d+(st|nd|rd|th)\s+',  # Remove ordinal numbers at start
                ]
                
                for prefix_pattern in prefixes_to_remove:
                    normalized = re.sub(prefix_pattern, '', normalized)
        
        # Remove publisher names and year suffixes from conference names
        publisher_patterns = [
            r'\s+\d{4}(,\s*\d{4})?$',  # Remove trailing years like " 2024" or " 2024, 2024"
            r'\s*,\s*\d{4}$',          # Remove ", 2024" suffix
        ]
        
        for pattern in publisher_patterns:
            normalized = re.sub(pattern, '', normalized)
        
        # Try exact mapping first (with original)
        if venue_lower in ieee_mappings:
            return ieee_mappings[venue_lower]
            
        # Try exact mapping with normalized version
        if normalized in ieee_mappings:
            return ieee_mappings[normalized]
        
        # Try pattern-based matching for variations
        # Handle "Trans." vs "Transactions", "Commun." vs "Communications", etc.
        patterns = [
            (r'\btrans\.\s*', 'transactions '),
            (r'\bcommun\.\s*', 'communications '),
            (r'\bnetw\.\s*', 'network '),
            (r'\bwireless\s+commun\.\s*', 'wireless communications '),
            (r'\bsci\.\s*', 'science '),
            (r'\beng\.\s*', 'engineering '),
            (r'\bcogn\.\s*', 'cognitive '),
            (r'\bj\.\s*', 'journal '),
            (r'\bsel\.\s*', 'selected '),
            (r'\bsignal\s+process\.\s*', 'signal processing '),
            (r'\blett\.\s*', 'letters '),
            (r'\bmag\.\s*', 'magazine '),
            (r'\bveh\.\s*', 'vehicular '),
            (r'\btechnol\.\s*', 'technology '),
            (r'\bsurveys\s+tuts\.\s*', 'surveys and tutorials '),
            (r'\bmach\.\s*', 'machine '),
            (r'\bintell\.\s*', 'intelligence '),
            
            # Conference abbreviations
            (r'\bconf\.\s*', 'conference '),
            (r'\bint\.\s*', 'international '),
            (r'\beur\.\s*', 'european '),
            (r'\bcomput\.\s*', 'computer '),
            (r'\bvis\.\s*', 'vision '),
            (r'\blearn\.\s*', 'learning '),
            (r'\brepresent\.\s*', 'representations '),
            (r'\bartif\.\s*', 'artificial '),
            (r'\blinguist\.\s*', 'linguistics '),
            (r'\bprocess\.\s*', 'processing '),
            (r'\binform\.\s*', 'information '),
            (r'\banal\.\s*', 'analysis '),
            (r'\bpattern\s+recog\.\s*', 'pattern recognition '),
            (r'\bmeet\.\s*', 'meeting '),
            (r'\bannu\.\s*', 'annual '),
            (r'\bassoc\.\s*', 'association '),
            (r'\bempir\.\s*', 'empirical '),
            (r'\bmethods\s+nat\.\s+lang\.\s*', 'methods in natural language '),
            # Reverse patterns
            (r'\btransactions\s+', 'trans. '),
            (r'\bcommunications\s+', 'commun. '),
            (r'\bnetwork\s+', 'netw. '),
            (r'\bwireless\s+communications\s+', 'wireless commun. '),
            (r'\bscience\s+', 'sci. '),
            (r'\bengineering\s+', 'eng. '),
            (r'\bcognitive\s+', 'cogn. '),
            (r'\bjournal\s+', 'j. '),
            (r'\bselected\s+', 'sel. '),
            (r'\bsignal\s+processing\s+', 'signal process. '),
            (r'\bletters\s+', 'lett. '),
            (r'\bmagazine\s+', 'mag. '),
            (r'\bvehicular\s+', 'veh. '),
            (r'\btechnology\s+', 'technol. '),
            (r'\bsurveys\s+and\s+tutorials\s+', 'surveys tuts. '),
            (r'\bmachine\s+', 'mach. '),
            (r'\bintelligence\s+', 'intell. '),
            
            # Reverse conference patterns
            (r'\bconference\s+', 'conf. '),
            (r'\binternational\s+', 'int. '),
            (r'\beuropean\s+', 'eur. '),
            (r'\bcomputer\s+', 'comput. '),
            (r'\bvision\s+', 'vis. '),
            (r'\blearning\s+', 'learn. '),
            (r'\brepresentations\s+', 'represent. '),
            (r'\bartificial\s+', 'artif. '),
            (r'\blinguistics\s+', 'linguist. '),
            (r'\bprocessing\s+', 'process. '),
            (r'\binformation\s+', 'inform. '),
            (r'\banalysis\s+', 'anal. '),
            (r'\bpattern\s+recognition\s+', 'pattern recog. '),
            (r'\bmeeting\s+', 'meet. '),
            (r'\bannual\s+', 'annu. '),
            (r'\bassociation\s+', 'assoc. '),
            (r'\bempirical\s+', 'empir. '),
            (r'\bmethods\s+in\s+natural\s+language\s+', 'methods nat. lang. '),
        ]
        
        for pattern, replacement in patterns:
            normalized = re.sub(pattern, replacement, normalized)
        
        # Clean up extra spaces
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    
    # Check if venues match after IEEE journal normalization
    norm_venue1_ieee = normalize_ieee_journal(venue1)
    norm_venue2_ieee = normalize_ieee_journal(venue2)
    
    if norm_venue1_ieee == norm_venue2_ieee:
        return False  # They match - not substantially different
    
    # Also check cross-mapping (abbreviated vs full)
    if (normalize_ieee_journal(norm_venue1_ieee) == norm_venue2_ieee or
        normalize_ieee_journal(norm_venue2_ieee) == norm_venue1_ieee):
        return False  # They match - not substantially different
    
    # Special handling for IEEE prefix variations in computer vision conferences
    # Check if one has "ieee" prefix and the other doesn't, but otherwise they match
    def remove_ieee_prefix(venue_name):
        return re.sub(r'^ieee\s+', '', venue_name.lower().strip())
    
    venue1_no_ieee = remove_ieee_prefix(norm_venue1_ieee)
    venue2_no_ieee = remove_ieee_prefix(norm_venue2_ieee)
    
    if venue1_no_ieee == venue2_no_ieee:
        return False  # They match except for IEEE prefix - not substantially different
    
    # General abbreviation matching - check if one venue is an abbreviation of the other
    def is_abbreviation_match(full_venue, abbrev_venue):
        """
        Check if abbrev_venue is an abbreviation of full_venue.
        Returns True if words in abbrev_venue are abbreviations of words in full_venue.
        
        Examples: 
        - "Nat. Mac. Intell." matches "Nature Machine Intelligence"
        - "Comput. Educ." matches "Computers & Education"
        """
        # Clean and split venues into words, including & as separator
        full_words = re.split(r'[\s,\-/&]+', full_venue.lower().strip())
        abbrev_words = re.split(r'[\s,\-/&]+', abbrev_venue.lower().strip())
        
        # Remove empty words and common stop words
        stop_words = {'the', 'of', 'on', 'in', 'for', 'and', 'or', 'to', 'a', 'an'}
        full_words = [w for w in full_words if w and w not in stop_words]
        abbrev_words = [w for w in abbrev_words if w and w not in stop_words]
        
        # If different number of significant words, less likely to be abbreviation
        if len(abbrev_words) != len(full_words):
            return False
            
        # Check each word pair
        for full_word, abbrev_word in zip(full_words, abbrev_words):
            # Remove trailing period from abbreviation
            abbrev_clean = abbrev_word.rstrip('.')
            
            # Check if abbreviation matches:
            # 1. Same word (exact match)
            # 2. First few letters match (abbreviation)
            # 3. Single letter abbreviations are allowed for common words like "journal" -> "j"
            if not (full_word == abbrev_clean or 
                   full_word.startswith(abbrev_clean)):
                return False
                
        return True
    
    # Test abbreviation matching in both directions
    if is_abbreviation_match(venue1, venue2) or is_abbreviation_match(venue2, venue1):
        return False  # They match as abbreviation - not substantially different
    
    # Special case: Check if one venue is a full acronym of the other (like "CLICIT" vs "Computational Linguistics")
    def is_full_acronym_match(full_venue, acronym_venue):
        """Check if acronym_venue is an acronym formed from the words of full_venue"""
        if len(acronym_venue) < 3:  # Too short to be meaningful acronym
            return False
            
        # Clean the full venue first - remove proceedings, ordinals, parentheses
        cleaned_venue = full_venue.lower()
        # Remove procedural prefixes
        cleaned_venue = re.sub(r'^(proceedings\s+of\s+(the\s+)?|advances\s+in\s+)', '', cleaned_venue)
        # Remove ordinals
        cleaned_venue = re.sub(r'\b(the\s+)?\d+(st|nd|rd|th)\s+', '', cleaned_venue)
        # Remove parenthetical content (often contains existing acronyms)
        cleaned_venue = re.sub(r'\s*\([^)]*\)', '', cleaned_venue)
        
        # Split into significant words
        full_words = re.split(r'[\s,\-/&]+', cleaned_venue.strip())
        stop_words = {'the', 'of', 'on', 'in', 'for', 'and', 'or', 'to', 'a', 'an', 'at'}
        significant_words = [w for w in full_words if w and w not in stop_words and len(w) > 1 and not w.isdigit()]
        
        # Extract first letters to form potential acronym
        if len(significant_words) < 2:  # Need at least 2 words for acronym
            return False
            
        potential_acronym = ''.join(word[0].upper() for word in significant_words)
        actual_acronym = acronym_venue.upper().strip()
        
        # Check various acronym patterns
        return (potential_acronym == actual_acronym or 
                potential_acronym.startswith(actual_acronym) or
                actual_acronym.startswith(potential_acronym))
    
    # Test full acronym matching in both directions
    if is_full_acronym_match(venue1, venue2) or is_full_acronym_match(venue2, venue1):
        return False  # They match as full acronym - not substantially different

    # Case 1: Check if one is an acronym of the other
    def extract_acronym(full_name):
        """Extract potential acronym from full conference name"""
        # Split by common separators and take first letter of each significant word
        words = re.split(r'[\s:,\-/]+', full_name)
        # Filter out common words that don't contribute to acronyms
        significant_words = [w for w in words if w.lower() not in 
                           ['and', 'or', 'of', 'on', 'in', 'for', 'the', 'a', 'an', 'to', 'with']]
        if len(significant_words) >= 2:
            return ''.join(word[0].upper() for word in significant_words if word)
        return None
    
    def clean_venue_for_acronym_check(venue):
        """Clean venue name for acronym matching"""
        # Remove years, ordinal numbers, and special characters
        cleaned = re.sub(r"'?\d{2,4}$", '', venue)  # Remove trailing years like '95, 2017
        cleaned = re.sub(r'\s+\d+$', '', cleaned)   # Remove trailing numbers like " 26"
        cleaned = cleaned.strip()
        return cleaned
    
    # Clean venues for comparison
    clean_venue1 = clean_venue_for_acronym_check(venue1)
    clean_venue2 = clean_venue_for_acronym_check(venue2)
    
    # Check if one is short (likely acronym) and other is long (likely full name)
    short_venue, long_venue = (clean_venue1, clean_venue2) if len(clean_venue1) <= len(clean_venue2) else (clean_venue2, clean_venue1)
    
    # If short venue looks like an acronym (all caps, <= 8 chars)
    if len(short_venue) <= 8 and short_venue.isupper():
        # Try to match as acronym
        potential_acronym = extract_acronym(long_venue)
        if potential_acronym and potential_acronym.lower() == short_venue.lower():
            return False  # They match - not substantially different
        
        # Try partial acronym matching (for cases like NDSS vs NDSSS)
        # Check if the short venue is a prefix of the potential acronym
        if potential_acronym and len(short_venue) < len(potential_acronym):
            if potential_acronym.lower().startswith(short_venue.lower()):
                # Additional check: make sure we're not matching too loosely
                # Require at least 75% of the acronym to match
                if len(short_venue) >= len(potential_acronym) * 0.75:
                    return False  # They match - not substantially different
        
        # Try alternative acronym extraction for common patterns
        # Handle cases where final words like "Symposium", "Conference", "Workshop" might be omitted
        words = re.split(r'[\s:,\-/]+', long_venue)
        significant_words = [w for w in words if w.lower() not in 
                           ['and', 'or', 'of', 'on', 'in', 'for', 'the', 'a', 'an', 'to', 'with']]
        
        # Try acronym without common conference/symposium endings
        endings_to_try = ['symposium', 'conference', 'workshop', 'meeting', 'proceedings']
        for ending in endings_to_try:
            if significant_words and significant_words[-1].lower() == ending:
                alt_words = significant_words[:-1]  # Remove the ending word
                if len(alt_words) >= 2:
                    alt_acronym = ''.join(word[0].upper() for word in alt_words if word)
                    if alt_acronym and alt_acronym.lower() == short_venue.lower():
                        return False  # They match - not substantially different
        
        # Also check if short venue is contained in long venue as word
        if short_venue.lower() in long_venue.lower():
            return False
    
    # Case 2: Check for overlap in normalized venues
    # Normalize both venues for better overlap detection
    def normalize_for_overlap(venue):
        normalized = venue.lower()
        # Remove common prefixes
        normalized = re.sub(r'^(proceedings\s+of\s+(the\s+)?|advances\s+in\s+)', '', normalized)
        
        # Remove ordinal numbers (1st, 2nd, 3rd, 4th, etc.) and their preceding "the"
        normalized = re.sub(r'\b(the\s+)?\d+(st|nd|rd|th)\s+', '', normalized)
        
        # Remove acronyms in parentheses (like "(RDSM)", "(CLiC-it 2024)", etc.)
        normalized = re.sub(r'\s*\([^)]*\)', '', normalized)
        
        # Normalize IEEE variations (IEEE/CVF → IEEE, IEEE/ACM → IEEE, etc.)
        normalized = re.sub(r'\bieee/[a-z]+\b', 'ieee', normalized)
        # Normalize workshop/conference variations
        normalized = re.sub(r'\bworkshop/winter\b', 'winter', normalized)
        
        # Remove common stop words from conference titles
        stop_words = ['of', 'the', 'on', 'in', 'for', 'and', 'a', 'an']
        words = normalized.split()
        filtered_words = [w for w in words if w not in stop_words]
        normalized = ' '.join(filtered_words)
        
        # Remove punctuation and normalize spaces
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    
    norm_venue1 = normalize_for_overlap(clean_venue1)
    norm_venue2 = normalize_for_overlap(clean_venue2)
    
    # One venue contains the other (after removing numbers and normalization)
    if norm_venue1 in norm_venue2 or norm_venue2 in norm_venue1:
        return False
    
    # Case 2.5: Check if venues are the same but with year in different positions
    # Extract years and compare venues without years
    def extract_year_and_venue(venue):
        # Find 4-digit years
        year_match = re.search(r'\b(19|20)\d{2}\b', venue)
        if year_match:
            year = year_match.group()
            venue_without_year = re.sub(r'\b(19|20)\d{2}\b', '', venue).strip()
            # Clean up extra spaces and punctuation
            venue_without_year = re.sub(r'[,\s]+', ' ', venue_without_year).strip()
            return year, venue_without_year
        return None, venue
    
    year1, venue1_no_year = extract_year_and_venue(venue1)
    year2, venue2_no_year = extract_year_and_venue(venue2)
    
    # If both have years and years match, compare venues without years
    if year1 and year2 and year1 == year2:
        # Normalize venues without years for comparison
        norm_venue1_no_year = normalize_for_overlap(venue1_no_year)
        norm_venue2_no_year = normalize_for_overlap(venue2_no_year)
        
        # Remove common prefixes like "in", "proceedings of"
        norm_venue1_no_year = re.sub(r'^(in\s+|proceedings\s+of\s+)', '', norm_venue1_no_year)
        norm_venue2_no_year = re.sub(r'^(in\s+|proceedings\s+of\s+)', '', norm_venue2_no_year)
        
        # Check if they're the same after removing years and normalizing
        if norm_venue1_no_year == norm_venue2_no_year:
            return False  # Same venue, just year in different position
    
    # Case 3: Standard word-based similarity check
    words1 = set(venue1.split())
    words2 = set(venue2.split())
    
    # Calculate Jaccard similarity (intersection over union)
    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))
    
    if union == 0:
        return venue1 != venue2
    
    jaccard_similarity = intersection / union
    
    # If venues have high word overlap (80%+), consider them the same
    # This handles cases like "ACM SIGACT-SIGMOD" vs "ACM SIGACT-SIGMOD-SIGART"
    return jaccard_similarity < 0.8


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