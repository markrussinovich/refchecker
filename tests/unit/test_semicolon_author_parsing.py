#!/usr/bin/env python3
"""
Unit tests for semicolon-separated author parsing to prevent regressions
"""
import unittest
import sys
import os

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.text_utils import parse_authors_with_initials


class TestSemicolonAuthorParsing(unittest.TestCase):
    """Test semicolon-separated author parsing functionality"""
    
    def test_semicolon_separated_authors(self):
        """Test basic semicolon-separated author parsing"""
        test_input = "Smith, J.; Doe, A. B.; Wilson, C."
        expected = ["Smith, J.", "Doe, A. B.", "Wilson, C."]
        
        result = parse_authors_with_initials(test_input)
        
        self.assertEqual(result, expected)
        self.assertEqual(len(result), 3)
    
    def test_semicolon_with_and_connector(self):
        """Test semicolon-separated authors with 'and' connector"""
        test_input = "Hashimoto, K.; Saoud, A.; Kishida, M.; Ushio, T.; and Dimarogonas, D. V."
        expected = ["Hashimoto, K.", "Saoud, A.", "Kishida, M.", "Ushio, T.", "Dimarogonas, D. V."]
        
        result = parse_authors_with_initials(test_input)
        
        self.assertEqual(result, expected)
        self.assertEqual(len(result), 5)
    
    def test_semicolon_with_others(self):
        """Test semicolon-separated authors with 'others' converted to 'et al'"""
        test_input = "Brown, A.; Green, B. C.; and others"
        expected = ["Brown, A.", "Green, B. C.", "et al"]
        
        result = parse_authors_with_initials(test_input)
        
        self.assertEqual(result, expected)
        self.assertEqual(len(result), 3)
    
    def test_semicolon_with_et_al(self):
        """Test semicolon-separated authors with explicit 'et al'"""
        test_input = "Last, F.; Middle, S.; Final, T.; et al"
        expected = ["Last, F.", "Middle, S.", "Final, T.", "et al"]
        
        result = parse_authors_with_initials(test_input)
        
        self.assertEqual(result, expected)
        self.assertEqual(len(result), 4)
    
    def test_semicolon_with_multiple_initials(self):
        """Test semicolon format with multiple initials like 'D. V.'"""
        test_input = "Author, A. B.; Second, C. D. E.; Third, F."
        expected = ["Author, A. B.", "Second, C. D. E.", "Third, F."]
        
        result = parse_authors_with_initials(test_input)
        
        self.assertEqual(result, expected)
        self.assertEqual(len(result), 3)
    
    def test_regression_original_problem(self):
        """Test the specific case that was failing in the user report"""
        test_input = "Hashimoto, K.; Saoud, A.; Kishida, M.; Ushio, T.; and Dimarogonas, D. V."
        
        result = parse_authors_with_initials(test_input)
        
        # Should parse exactly 5 authors
        self.assertEqual(len(result), 5)
        
        # Specific author checks
        self.assertEqual(result[0], "Hashimoto, K.")
        self.assertEqual(result[1], "Saoud, A.")  # This should NOT be "K.; Saoud"
        self.assertEqual(result[2], "Kishida, M.")
        self.assertEqual(result[3], "Ushio, T.")
        self.assertEqual(result[4], "Dimarogonas, D. V.")
        
        # No author should contain incorrect combinations
        for author in result:
            self.assertNotIn(";", author, f"Author '{author}' should not contain semicolon")
            self.assertFalse(author.endswith(";"), f"Author '{author}' should not end with semicolon")
    
    def test_fallback_to_other_formats(self):
        """Test that non-semicolon formats still work as before"""
        # Test that 'and' format still works
        and_format = "John Smith and Jane Doe"
        result_and = parse_authors_with_initials(and_format)
        self.assertEqual(result_and, ["John Smith", "Jane Doe"])
        
        # Test that comma-separated initials still work
        comma_format = "Jiang, J, Xia, G. G, Carlton, D. B"
        result_comma = parse_authors_with_initials(comma_format)
        self.assertEqual(len(result_comma), 3)
        self.assertIn("Jiang, J", result_comma)


if __name__ == '__main__':
    unittest.main()