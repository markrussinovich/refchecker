"""
Utility functions for text processing, author comparison, mocking, and configuration validation
"""

from .text_utils import (
    clean_author_name, clean_title, normalize_text, 
    clean_conference_markers_from_title,
    remove_year_from_title
)
from .url_utils import extract_arxiv_id_from_url
from .author_utils import compare_authors, levenshtein_distance, extract_authors_list
from .mock_objects import (
    MockPaper, MockReference, MockLLMProvider, MockSemanticScholarAPI, MockArxivAPI,
    create_mock_config, create_mock_paper, create_mock_reference, 
    create_mock_bibliography, create_mock_extracted_references
)
from .config_validator import ConfigValidator, ValidationResult

__all__ = [
    "clean_author_name", "clean_title", "normalize_text", 
    "extract_arxiv_id_from_url", "clean_conference_markers_from_title",
    "remove_year_from_title", "compare_authors", "levenshtein_distance", 
    "extract_authors_list", "MockPaper", "MockReference", "MockLLMProvider", 
    "MockSemanticScholarAPI", "MockArxivAPI", "create_mock_config", 
    "create_mock_paper", "create_mock_reference", "create_mock_bibliography", 
    "create_mock_extracted_references", "ConfigValidator", "ValidationResult"
]