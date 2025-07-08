#!/usr/bin/env python3
"""
Text processing utilities for ArXiv Reference Checker
"""

import re
import logging

logger = logging.getLogger(__name__)

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

def normalize_text(text):
    """
    Normalize text for comparison by removing special characters and converting to lowercase
    
    Args:
        text: Text to normalize
        
    Returns:
        Normalized text
    """
    if not isinstance(text, str):
        return str(text).lower() if text is not None else ''
    
    # Remove special characters except spaces and alphanumeric
    text = re.sub(r'[^\w\s]', '', text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text.lower()

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