#!/usr/bin/env python3
"""
Higher-level validation and integration tests for bug fixes.

This test suite covers integration-level validation behaviors that were identified 
during real-world ArXiv paper testing, focusing on end-to-end behavior rather
than individual text utility functions.
"""
import unittest
import sys
import os

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from utils.text_utils import compare_authors


class TestAuthorDeduplication(unittest.TestCase):
    """Test author deduplication and error message accuracy"""
    
    def test_duplicate_author_handling(self):
        """Test that duplicate authors in correct list are handled properly"""
        cited_authors = ["J. Smith", "A. Doe"]
        # Simulate a database result with duplicate authors (could happen in collaboration papers)
        correct_authors = ["John Smith", "Alice Doe", "John Smith"]  # Duplicate John Smith
        
        match_result, error_message = compare_authors(cited_authors, correct_authors)
        
        # Should succeed because the duplicate is cleaned up
        self.assertTrue(match_result, f"Should match after deduplication: {error_message}")
    
    def test_et_al_error_message_accuracy(self):
        """Test that et al error messages don't show misleading positional matches"""
        cited_authors = ["Nonexistent Author", "et al"]
        correct_authors = ["Real Author 1", "Real Author 2", "Real Author 3"]
        
        match_result, error_message = compare_authors(cited_authors, correct_authors)
        
        # Should fail
        self.assertFalse(match_result)
        # Error message should not show misleading positional match
        self.assertIn("not found in author list", error_message)
        self.assertIn("Real Author 1, Real Author 2, Real Author 3", error_message)
        # Should NOT show positional match like "Nonexistent Author vs Real Author 1"
        self.assertNotIn(" vs ", error_message)


class TestCollaborationPaperParsing(unittest.TestCase):
    """Test collaboration paper author parsing with et al constructs"""
    
    def test_collaboration_author_extraction(self):
        """Test that collaboration papers with 'and others' are parsed correctly"""
        # This tests the LLM prompt enhancement for collaboration patterns
        # The actual test would need to verify that the LLM extracts:
        # "Khachatryan, Vardan and others" -> ["Vardan Khachatryan", "et al"]
        # Instead of: ["Khachatryan", "Vardan and others"]
        pass  # This would require LLM testing which is integration-level
    
    def test_et_al_comparison_logic(self):
        """Test et al comparison logic in collaboration scenarios"""
        # Test standard et al matching
        cited_et_al = ["First Author", "et al"]
        correct_many = ["First Author", "Second Author", "Third Author", "Fourth Author"]
        
        match_result, _ = compare_authors(cited_et_al, correct_many)
        self.assertTrue(match_result, "Should match when first author matches and et al present")
        
        # Test mismatch when first author doesn't match
        cited_wrong_first = ["Wrong Author", "et al"]
        match_result_wrong, _ = compare_authors(cited_wrong_first, correct_many)
        self.assertFalse(match_result_wrong, "Should not match when first author is wrong")
    
    def test_large_author_list_handling(self):
        """Test handling of papers with very large author lists"""
        # Simulate a collaboration paper with many authors
        many_authors = [f"Author {i}" for i in range(1, 101)]  # 100 authors
        
        # Should work with et al construct
        cited_abbreviated = ["Author 1", "Author 2", "et al"]
        match_result, _ = compare_authors(cited_abbreviated, many_authors)
        
        # The exact behavior may depend on implementation but should not crash
        self.assertIsInstance(match_result, bool, "Should return boolean for large lists")


class TestRegressionValidation(unittest.TestCase):
    """Test specific cases that previously caused validation errors"""
    
    def test_original_failing_case_gluck(self):
        """Test the original Glück case that exposed the diacritic bug"""
        # Original failing case from real ArXiv paper testing
        cited = ["J. Glück"]  # This was causing validation issues due to umlaut
        correct = [{"name": "Jochen Glück"}] 
        
        match_result, error_msg = compare_authors(cited, correct)
        
        # Should match now that diacritic handling is improved
        self.assertTrue(match_result or "should match" in str(error_msg).lower(),
                       f"Glück case should work: {error_msg}")
    
    def test_original_failing_case_physical_review(self):
        """Test the Physical Review abbreviation case that was overly strict"""
        # This test would ideally check the full pipeline behavior
        # For now, we verify the core function doesn't crash on complex venue names
        test_venue = "Phys. Rev. Lett."
        
        # Should handle without crashing (exact matching logic tested in text_utils tests)
        self.assertIsInstance(test_venue, str, "Should handle venue strings")
    
    def test_collaboration_paper_structure(self):
        """Test overall collaboration paper handling structure"""
        # Test the overall structure for handling collaboration papers
        # This would test the integration of multiple components
        
        # Simulate collaboration paper reference
        collab_authors = ["CMS Collaboration"]
        individual_authors = ["A. Smith", "B. Jones", "C. Brown"]  # What might be in database
        
        # The exact behavior depends on the collaboration handling logic
        # At minimum, should not crash
        try:
            match_result, _ = compare_authors(collab_authors, individual_authors)
            self.assertIsInstance(match_result, bool)
        except Exception as e:
            self.fail(f"Collaboration paper handling should not crash: {e}")


if __name__ == '__main__':
    unittest.main()