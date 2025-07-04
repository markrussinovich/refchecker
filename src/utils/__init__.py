"""
Utility functions for text processing and author comparison
"""

from .text_utils import (
    clean_author_name, clean_title, normalize_text, 
    extract_arxiv_id_from_url, clean_conference_markers_from_title,
    remove_year_from_title
)
from .author_utils import compare_authors, levenshtein_distance, extract_authors_list

__all__ = [
    "clean_author_name", "clean_title", "normalize_text", 
    "extract_arxiv_id_from_url", "clean_conference_markers_from_title",
    "remove_year_from_title", "compare_authors", "levenshtein_distance", 
    "extract_authors_list"
]