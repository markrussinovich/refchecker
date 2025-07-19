#!/usr/bin/env python3
"""
Database Processing Utilities for Reference Checking

This module provides utilities for processing database results,
particularly for Semantic Scholar data processing.
"""

import json
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


def process_semantic_scholar_result(paper_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a single Semantic Scholar database result by parsing JSON fields
    and reconstructing the paper data structure.
    
    Args:
        paper_data: Raw paper data dictionary from database
        
    Returns:
        Processed paper data dictionary
    """
    try:
        # Extract authors from JSON
        if paper_data.get('authors'):
            if isinstance(paper_data['authors'], str):
                paper_data['authors'] = json.loads(paper_data['authors'])
        else:
            paper_data['authors'] = []
        
        # Reconstruct external IDs from flattened columns
        external_ids = {}
        for key, value in paper_data.items():
            if key.startswith('externalIds_') and value:
                external_id_type = key.replace('externalIds_', '')
                external_ids[external_id_type] = value
        paper_data['externalIds'] = external_ids
        
        # Add other JSON fields
        if paper_data.get('s2FieldsOfStudy'):
            if isinstance(paper_data['s2FieldsOfStudy'], str):
                paper_data['s2FieldsOfStudy'] = json.loads(paper_data['s2FieldsOfStudy'])
        
        if paper_data.get('publicationTypes'):
            if isinstance(paper_data['publicationTypes'], str):
                paper_data['publicationTypes'] = json.loads(paper_data['publicationTypes'])
        
        return paper_data
        
    except Exception as e:
        logger.warning(f"Error processing database result: {e}")
        return paper_data


def process_semantic_scholar_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Process multiple Semantic Scholar database results.
    
    Args:
        results: List of raw database row dictionaries
        
    Returns:
        List of processed paper data dictionaries
    """
    processed_results = []
    
    for paper_data in results:
        processed_result = process_semantic_scholar_result(paper_data)
        if processed_result:
            processed_results.append(processed_result)
    
    return processed_results


def extract_external_ids(paper_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract external IDs from flattened database columns.
    
    Args:
        paper_data: Paper data dictionary from database
        
    Returns:
        Dictionary of external IDs
    """
    external_ids = {}
    
    for key, value in paper_data.items():
        if key.startswith('externalIds_') and value:
            external_id_type = key.replace('externalIds_', '')
            external_ids[external_id_type] = value
    
    return external_ids


def parse_json_field(data: Dict[str, Any], field_name: str) -> Any:
    """
    Parse a JSON field from database data, handling both string and already-parsed data.
    
    Args:
        data: Database record dictionary
        field_name: Name of the field to parse
        
    Returns:
        Parsed data or empty list/dict if parsing fails
    """
    try:
        field_data = data.get(field_name)
        if not field_data:
            return [] if field_name in ['authors', 's2FieldsOfStudy', 'publicationTypes'] else {}
        
        if isinstance(field_data, str):
            return json.loads(field_data)
        else:
            return field_data
            
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse JSON field '{field_name}': {e}")
        return [] if field_name in ['authors', 's2FieldsOfStudy', 'publicationTypes'] else {}


def reconstruct_paper_structure(row_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reconstruct the full paper data structure from flattened database row.
    
    Args:
        row_data: Raw database row data
        
    Returns:
        Reconstructed paper data structure
    """
    # Start with the row data
    paper_data = dict(row_data)
    
    # Parse JSON fields
    paper_data['authors'] = parse_json_field(paper_data, 'authors')
    paper_data['s2FieldsOfStudy'] = parse_json_field(paper_data, 's2FieldsOfStudy')
    paper_data['publicationTypes'] = parse_json_field(paper_data, 'publicationTypes')
    
    # Reconstruct external IDs
    paper_data['externalIds'] = extract_external_ids(paper_data)
    
    return paper_data


def safe_json_loads(json_string: str, default_value: Any = None) -> Any:
    """
    Safely load JSON string with fallback to default value.
    
    Args:
        json_string: JSON string to parse
        default_value: Default value if parsing fails
        
    Returns:
        Parsed JSON data or default value
    """
    if not json_string:
        return default_value
    
    try:
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug(f"Failed to parse JSON: {e}")
        return default_value


def flatten_external_ids(external_ids: Dict[str, str]) -> Dict[str, str]:
    """
    Flatten external IDs dictionary into database column format.
    
    Args:
        external_ids: Dictionary of external IDs
        
    Returns:
        Flattened dictionary with externalIds_ prefix
    """
    flattened = {}
    
    for id_type, id_value in external_ids.items():
        flattened[f'externalIds_{id_type}'] = id_value
    
    return flattened


def validate_paper_data(paper_data: Dict[str, Any]) -> bool:
    """
    Validate that paper data has required fields.
    
    Args:
        paper_data: Paper data dictionary to validate
        
    Returns:
        True if data appears valid, False otherwise
    """
    # Check for essential fields
    required_fields = ['title']
    
    for field in required_fields:
        if not paper_data.get(field):
            return False
    
    # Validate authors field
    authors = paper_data.get('authors', [])
    if not isinstance(authors, list):
        return False
    
    return True