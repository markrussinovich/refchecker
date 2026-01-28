#!/usr/bin/env python3
"""
Author comparison utilities for ArXiv Reference Checker
"""

import re
import logging
from .text_utils import normalize_text

logger = logging.getLogger(__name__)

def levenshtein_distance(s1, s2):
    """
    Calculate the Levenshtein distance between two strings
    
    Args:
        s1, s2: Strings to compare
        
    Returns:
        Integer distance
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]

def compare_authors(cited_authors, correct_authors, threshold=0.8):
    """
    Compare two author lists and return similarity metrics
    
    Args:
        cited_authors: List of authors as cited (can be strings or dicts with 'name' key)
        correct_authors: List of correct authors (can be strings or dicts with 'name' key)
        threshold: Similarity threshold (0-1)
        
    Returns:
        Dictionary with comparison results
    """
    # Normalize author lists to strings (handle dict format from APIs)
    def normalize_author_list(authors):
        result = []
        for a in authors:
            if isinstance(a, dict):
                result.append(a.get('name', str(a)))
            else:
                result.append(str(a))
        return result
    
    cited_authors = normalize_author_list(cited_authors) if cited_authors else []
    correct_authors = normalize_author_list(correct_authors) if correct_authors else []
    
    if not cited_authors or not correct_authors:
        return {
            'match': False,
            'similarity': 0.0,
            'details': 'One or both author lists empty'
        }
    
    # Handle "et al." cases
    cited_has_et_al = any('et al' in author.lower() for author in cited_authors)
    correct_has_et_al = len(correct_authors) > 3
    
    if cited_has_et_al or correct_has_et_al:
        # Compare only the first few authors
        cited_main = [a for a in cited_authors if 'et al' not in a.lower()][:3]
        correct_main = correct_authors[:3]
        
        if len(cited_main) == 0:
            return {
                'match': True,  # "et al." without specific authors
                'similarity': 0.9,
                'details': 'Et al. reference'
            }
    else:
        cited_main = cited_authors
        correct_main = correct_authors
    
    # Calculate similarities for each cited author
    similarities = []
    matched_authors = 0
    
    for cited_author in cited_main:
        cited_norm = normalize_text(cited_author)
        best_similarity = 0.0
        best_match = ''
        
        for correct_author in correct_main:
            correct_norm = normalize_text(correct_author)
            
            # Calculate similarity
            if cited_norm == correct_norm:
                similarity = 1.0
            elif cited_norm in correct_norm or correct_norm in cited_norm:
                similarity = 0.9
            else:
                # Use Levenshtein distance
                max_len = max(len(cited_norm), len(correct_norm))
                if max_len == 0:
                    similarity = 1.0
                else:
                    distance = levenshtein_distance(cited_norm, correct_norm)
                    similarity = 1.0 - (distance / max_len)
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = correct_author
        
        similarities.append({
            'cited': cited_author,
            'matched': best_match,
            'similarity': best_similarity
        })
        
        if best_similarity >= threshold:
            matched_authors += 1
    
    # Calculate overall match
    if len(cited_main) == 0:
        overall_similarity = 0.0
    else:
        overall_similarity = matched_authors / len(cited_main)
    
    # Determine if it's a match
    is_match = overall_similarity >= threshold
    
    # Handle author count mismatch
    count_penalty = 0
    if len(cited_main) != len(correct_main):
        count_diff = abs(len(cited_main) - len(correct_main))
        count_penalty = min(0.1 * count_diff, 0.3)  # Max 30% penalty
        overall_similarity = max(0, overall_similarity - count_penalty)
    
    details = f"Matched {matched_authors}/{len(cited_main)} authors"
    if count_penalty > 0:
        details += f", count mismatch penalty: {count_penalty:.1f}"
    
    return {
        'match': is_match,
        'similarity': overall_similarity,
        'details': details,
        'author_matches': similarities
    }

def extract_authors_list(authors_text):
    """
    Extract a list of authors from text
    
    Args:
        authors_text: String containing author names
        
    Returns:
        List of cleaned author names
    """
    if not isinstance(authors_text, str):
        return []
    
    # Remove common prefixes
    authors_text = re.sub(r'^(by|authors?:)\s*', '', authors_text, flags=re.IGNORECASE)
    
    # Split by common separators
    separators = [',', ';', ' and ', ' & ', '\n']
    authors = [authors_text]
    
    for sep in separators:
        new_authors = []
        for author in authors:
            new_authors.extend([a.strip() for a in author.split(sep)])
        authors = new_authors
    
    # Clean each author name
    from .text_utils import clean_author_name
    cleaned_authors = []
    for author in authors:
        if author.strip():  # Skip empty strings
            cleaned = clean_author_name(author)
            if cleaned:  # Only add non-empty cleaned names
                cleaned_authors.append(cleaned)
    
    return cleaned_authors