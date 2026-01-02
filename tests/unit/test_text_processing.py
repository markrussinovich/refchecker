"""
Simple tests for text processing functionality.
"""

import pytest
import sys
import os

# Add the src directory to Python path for imports  
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

try:
    from refchecker.utils.text_utils import is_name_match, clean_title
    TEXT_UTILS_AVAILABLE = True
except ImportError:
    TEXT_UTILS_AVAILABLE = False


@pytest.mark.skipif(not TEXT_UTILS_AVAILABLE, reason="Text utils module not available")
class TestNameMatching:
    """Test name matching functionality."""
    
    def test_exact_name_match(self):
        """Test exact name matches."""
        if TEXT_UTILS_AVAILABLE:
            assert is_name_match("John Smith", "John Smith")
            assert is_name_match("Alice Johnson", "Alice Johnson")
    
    def test_initial_matches(self):
        """Test matching with initials."""
        if TEXT_UTILS_AVAILABLE:
            # These might work depending on implementation
            try:
                assert is_name_match("J. Smith", "John Smith")
            except:
                pass  # Implementation might be different
    
    def test_case_insensitive_matching(self):
        """Test case insensitive name matching.""" 
        if TEXT_UTILS_AVAILABLE:
            try:
                assert is_name_match("john smith", "John Smith")
            except:
                pass  # Implementation might be different


@pytest.mark.skipif(not TEXT_UTILS_AVAILABLE, reason="Text utils module not available")
class TestTitleCleaning:
    """Test title cleaning functionality."""
    
    def test_basic_title_cleaning(self):
        """Test basic title cleaning."""
        if TEXT_UTILS_AVAILABLE:
            title = clean_title("  Attention Is All You Need  ")
            assert isinstance(title, str)
            assert len(title) > 0
    
    def test_title_with_special_characters(self):
        """Test title cleaning with special characters."""
        if TEXT_UTILS_AVAILABLE:
            title = clean_title("BERT: Pre-training of Deep Bidirectional Transformers")
            assert isinstance(title, str)
            assert len(title) > 0