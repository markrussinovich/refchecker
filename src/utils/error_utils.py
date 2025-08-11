#!/usr/bin/env python3
"""
Error Utilities for Reference Checking

This module provides standardized error and warning creation functions
for reference checkers.
"""

from typing import Dict, List, Any, Optional


def print_labeled_multiline(label: str, text: str) -> None:
    """
    Print a multi-line message with consistent label formatting.
    
    This function ensures consistent indentation for all error and warning messages,
    regardless of emoji width differences in the labels.
    
    Args:
        label: The label (e.g., "❌ Error", "⚠️  Warning")
        text: The multi-line text to print
    """
    prefix = f"      {label}: "
    lines = (text or "").splitlines() or [""]
    
    # Print the first line with the label prefix
    print(prefix + lines[0])
    
    # Print subsequent lines with fixed indentation to ensure consistency
    # Use fixed 19-character indentation to align regardless of emoji width
    fixed_indent = " " * 15
    for line in lines[1:]:
        print(fixed_indent + line)


def format_three_line_mismatch(mismatch_type: str, left: str, right: str) -> str:
    """
    Format a three-line mismatch message with fixed indentation.

    This creates a clean, consistently formatted mismatch message that separates
    the mismatch type from the values being compared:

    Example:
    Title mismatch:
        'Cited Title'
    vs: 'Correct Title'

    Args:
        mismatch_type: The type of mismatch (e.g., "Author 2 mismatch", "Title mismatch")
        left: The cited/incorrect value
        right: The correct value

    Returns:
        Three-line formatted mismatch message
    """
    # Ensure mismatch_type ends with a colon
    if not mismatch_type.endswith(":"):
        mismatch_type = mismatch_type.rstrip() + ":"
    
    # Use fixed indentation for clean, consistent alignment
    indent = ""  # spaces for content indentation
    vs_indent = ""   # vs: starts at column 0 for clear visual separation
    
    return f"{mismatch_type}\n{indent}cited:  '{left}'\n{vs_indent}actual: '{right}'"


def format_title_mismatch(cited_title: str, verified_title: str) -> str:
    """
    Format a three-line title mismatch message.

    Output format:
    Title mismatch:
        'Cited Title'
    vs: 'Correct Title'
    """
    return format_three_line_mismatch("Title mismatch", cited_title, verified_title)


def format_year_mismatch(cited_year: int | str, correct_year: int | str) -> str:
    """
    Three-line year mismatch message.
    """
    return format_three_line_mismatch("Year mismatch", str(cited_year), str(correct_year))


def format_doi_mismatch(cited_doi: str, correct_doi: str) -> str:
    """
    Three-line DOI mismatch message.
    """
    return format_three_line_mismatch("DOI mismatch", str(cited_doi), str(correct_doi))

def create_author_error(error_details: str, correct_authors: List[Dict[str, str]]) -> Dict[str, str]:
    """
    Create a standardized author error dictionary.
    
    Args:
        error_details: Description of the author error
        correct_authors: List of correct author data from database
        
    Returns:
        Standardized error dictionary
    """
    return {
        'error_type': 'author',
        'error_details': error_details,
        'ref_authors_correct': ', '.join([author.get('name', '') for author in correct_authors])
    }


def create_year_warning(cited_year: int, correct_year: int) -> Dict[str, Any]:
    """
    Create a standardized year warning dictionary.
    
    Args:
        cited_year: Year as cited in the reference
        correct_year: Correct year from database
        
    Returns:
        Standardized warning dictionary
    """
    return {
        'warning_type': 'year',
        'warning_details': format_year_mismatch(cited_year, correct_year),
        'ref_year_correct': correct_year
    }


def create_doi_error(cited_doi: str, correct_doi: str) -> Optional[Dict[str, str]]:
    """
    Create a standardized DOI error dictionary.
    
    Args:
        cited_doi: DOI as cited in the reference
        correct_doi: Correct DOI from database
        
    Returns:
        Standardized error dictionary if DOIs differ, None if they match after cleaning
    """
    # Strip trailing periods before comparison to avoid false mismatches
    cited_doi_clean = cited_doi.rstrip('.')
    correct_doi_clean = correct_doi.rstrip('.')
    
    # Only create error if DOIs are actually different after cleaning
    if cited_doi_clean != correct_doi_clean:
        return {
            'error_type': 'doi',
            'error_details': format_doi_mismatch(cited_doi, correct_doi),
            'ref_doi_correct': correct_doi
        }
    
    return None


def create_title_error(error_details: str, correct_title: str) -> Dict[str, str]:
    """
    Create a standardized title error dictionary.
    
    Args:
        error_details: Description of the title error
        correct_title: Correct title from database
        
    Returns:
        Standardized error dictionary
    """
    return {
        'error_type': 'title',
        'error_details': error_details,
        'ref_title_correct': correct_title
    }


def clean_venue_for_comparison(venue: str) -> str:
    """
    Clean venue name for display in warnings using the shared normalization logic.
    
    Args:
        venue: Raw venue string
        
    Returns:
        Cleaned venue name suitable for display
    """
    from utils.text_utils import normalize_venue_for_display
    return normalize_venue_for_display(venue)


def format_missing_venue(correct_venue: str) -> str:
    """
    Format a missing venue message with only the actual value.
    """
    # Only show the actual venue; omit the empty cited line
    return f"Missing venue: '{correct_venue}'"


def create_venue_warning(cited_venue: str, correct_venue: str) -> Dict[str, str]:
    """
    Create a standardized venue warning dictionary.
    
    Args:
        cited_venue: Venue as cited in the reference
        correct_venue: Correct venue from database
        
    Returns:
        Standardized warning dictionary
    """
    # Clean both venues for display in the warning
    clean_cited = clean_venue_for_comparison(cited_venue)
    clean_correct = clean_venue_for_comparison(correct_venue)

    # If cited venue cleans to empty, treat as missing venue instead of mismatch
    if not clean_cited and clean_correct:
        return {
            'warning_type': 'venue',
            'warning_details': format_missing_venue(clean_correct),
            'ref_venue_correct': correct_venue
        }

    return {
        'warning_type': 'venue',
        'warning_details': format_three_line_mismatch("Venue mismatch", clean_cited, clean_correct),
        'ref_venue_correct': correct_venue
    }


def format_venue_mismatch(cited_venue: str, verified_venue: str) -> str:
    """
    Format a three-line venue mismatch message with cleaned venue names.
    """
    clean_cited = clean_venue_for_comparison(cited_venue)
    clean_verified = clean_venue_for_comparison(verified_venue)
    return format_three_line_mismatch("Venue mismatch", clean_cited, clean_verified)


def create_url_error(error_details: str, correct_url: Optional[str] = None) -> Dict[str, str]:
    """
    Create a standardized URL error dictionary.
    
    Args:
        error_details: Description of the URL error
        correct_url: Correct URL from database (optional)
        
    Returns:
        Standardized error dictionary
    """
    error_dict = {
        'error_type': 'url',
        'error_details': error_details
    }
    
    if correct_url:
        error_dict['ref_url_correct'] = correct_url
    
    return error_dict


def create_generic_error(error_type: str, error_details: str, **kwargs) -> Dict[str, Any]:
    """
    Create a generic error dictionary with custom fields.
    
    Args:
        error_type: Type of error (e.g., 'author', 'doi', 'title')
        error_details: Description of the error
        **kwargs: Additional fields to include in the error dictionary
        
    Returns:
        Standardized error dictionary
    """
    error_dict = {
        'error_type': error_type,
        'error_details': error_details
    }
    
    error_dict.update(kwargs)
    return error_dict


def create_generic_warning(warning_type: str, warning_details: str, **kwargs) -> Dict[str, Any]:
    """
    Create a generic warning dictionary with custom fields.
    
    Args:
        warning_type: Type of warning (e.g., 'year', 'venue')
        warning_details: Description of the warning
        **kwargs: Additional fields to include in the warning dictionary
        
    Returns:
        Standardized warning dictionary
    """
    warning_dict = {
        'warning_type': warning_type,
        'warning_details': warning_details
    }
    
    warning_dict.update(kwargs)
    return warning_dict


def format_author_mismatch(author_number: int, cited_author: str, correct_author: str) -> str:
    """
    Format a three-line author mismatch message.
    
    Args:
        author_number: The author position (1-based)
        cited_author: The cited author name
        correct_author: The correct author name
        
    Returns:
        Formatted three-line author mismatch message
    """
    return format_three_line_mismatch(f"Author {author_number} mismatch", cited_author, correct_author)


def format_first_author_mismatch(cited_author: str, correct_author: str) -> str:
    """
    Format a three-line first author mismatch message.
    
    Args:
        cited_author: The cited first author name
        correct_author: The correct first author name
        
    Returns:
        Formatted three-line first author mismatch message
    """
    return format_three_line_mismatch("First author mismatch", cited_author, correct_author)


def format_author_count_mismatch(cited_count: int, correct_count: int, cited_authors: list, correct_authors: list) -> str:
    """
    Format an author count mismatch message showing all cited and correct authors.
    
    Args:
        cited_count: Number of cited authors
        correct_count: Number of correct authors  
        cited_authors: List of cited author names
        correct_authors: List of correct author names
        
    Returns:
        Formatted multi-line author count mismatch message
    """
    # Create the header with count information
    header = f"Author count mismatch: {cited_count} cited vs {correct_count} correct"
    
    # Format author lists
    cited_list = ", ".join(cited_authors) if cited_authors else "None"
    correct_list = ", ".join(correct_authors) if correct_authors else "None"
    
    # Use the same format as other mismatches
    return format_three_line_mismatch(header, cited_list, correct_list)


def format_authors_list(authors: List[Dict[str, str]]) -> str:
    """
    Format a list of author dictionaries into a readable string.
    
    Args:
        authors: List of author data dictionaries
        
    Returns:
        Formatted authors string
    """
    if not authors:
        return ""
    
    return ', '.join([author.get('name', '') for author in authors])


def validate_error_dict(error_dict: Dict[str, Any], required_fields: List[str]) -> bool:
    """
    Validate that an error dictionary contains all required fields.
    
    Args:
        error_dict: Error dictionary to validate
        required_fields: List of required field names
        
    Returns:
        True if all required fields are present, False otherwise
    """
    return all(field in error_dict for field in required_fields)