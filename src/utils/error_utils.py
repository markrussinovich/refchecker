#!/usr/bin/env python3
"""
Error Utilities for Reference Checking

This module provides standardized error and warning creation functions
for reference checkers.
"""

from typing import Dict, List, Any, Optional


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
        'warning_details': f"Year mismatch: cited as {cited_year} but actually {correct_year}",
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
            'error_details': f"DOI mismatch: cited as {cited_doi} but actually {correct_doi}",
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


def create_venue_warning(cited_venue: str, correct_venue: str) -> Dict[str, str]:
    """
    Create a standardized venue warning dictionary.
    
    Args:
        cited_venue: Venue as cited in the reference
        correct_venue: Correct venue from database
        
    Returns:
        Standardized warning dictionary
    """
    return {
        'warning_type': 'venue',
        'warning_details': f"Venue mismatch: cited as '{cited_venue}' but actually '{correct_venue}'",
        'ref_venue_correct': correct_venue
    }


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