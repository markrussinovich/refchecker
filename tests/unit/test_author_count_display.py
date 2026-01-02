#!/usr/bin/env python3
"""
Unit tests for author count mismatch display formatting.

This test ensures that when author count mismatches occur, the error message
displays properly formatted author names instead of raw unparsed fragments.
"""

import unittest
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.error_utils import format_author_count_mismatch


class TestAuthorCountDisplay(unittest.TestCase):
    """Test author count mismatch display formatting."""
    
    def test_last_first_format_display(self):
        """Test that 'Last, First' format authors are converted to 'First Last' for display."""
        # Test case: cited authors in "Last, First" format
        cited_last_first = [
            "Kazmi, Mishaal", 
            "Lautraite, Hadrien", 
            "Akbari, Alireza", 
            "Soroco, Mauricio", 
            "Tang, Qiaoyue", 
            "Wang, Tao"
        ]
        
        correct_authors = [
            "Mishaal Kazmi", "H. Lautraite", "Alireza Akbari", 
            "Mauricio Soroco", "Qiaoyue Tang", "Tao Wang", 
            "Sébastien Gambs", "M. L'ecuyer"
        ]
        
        # Test using the compare_authors function which should convert format before display
        from refchecker.utils.text_utils import compare_authors
        match_result, error_msg = compare_authors(cited_last_first, correct_authors)
        
        # Should not match due to count difference
        self.assertFalse(match_result)
        
        # Check that cited authors are displayed in "First Last" format
        self.assertIn("Mishaal Kazmi", error_msg)
        self.assertIn("Hadrien Lautraite", error_msg)
        self.assertIn("Alireza Akbari", error_msg)
        self.assertIn("Mauricio Soroco", error_msg)
        self.assertIn("Qiaoyue Tang", error_msg)
        self.assertIn("Tao Wang", error_msg)
        
        # Should NOT contain "Last, First" format in display
        self.assertNotIn("Kazmi, Mishaal", error_msg)
        self.assertNotIn("Lautraite, Hadrien", error_msg)
        
        # Check that the header shows correct counts
        self.assertIn("6 cited vs 8 correct", error_msg)
        
        # Check that the correct authors are displayed properly
        self.assertIn("Sébastien Gambs", error_msg)
        self.assertIn("M. L'ecuyer", error_msg)
    
    
    def test_original_issue_case(self):
        """Test the exact case from the original issue report."""
        # This represents the case where parsing failed and raw comma-separated
        # data was split incorrectly, resulting in 6 fragments instead of 6 authors
        cited_fragments = ["Kazmi", "Mishaal", "Lautraite", "Hadrien", "Akbari", "Alireza"]
        correct_authors = ["Mishaal Kazmi", "H. Lautraite", "Alireza Akbari", "Someone Else"]
        
        # Test using compare_authors which does the conversion
        from refchecker.utils.text_utils import compare_authors
        match_result, error_msg = compare_authors(cited_fragments, correct_authors)
        
        self.assertFalse(match_result)
        
        # The error message content will depend on the logic in compare_authors
        # Since we have 6 fragments vs 4 correct, it should trigger author count mismatch
        self.assertIn("Author count mismatch", error_msg)
    
    def test_empty_author_lists(self):
        """Test handling of empty author lists."""
        error_msg = format_author_count_mismatch(
            cited_count=0,
            correct_count=0,
            cited_authors=[],
            correct_authors=[]
        )
        
        self.assertIn("0 cited vs 0 correct", error_msg)
        self.assertIn("None", error_msg)


if __name__ == '__main__':
    unittest.main()