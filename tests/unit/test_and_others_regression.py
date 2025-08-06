#!/usr/bin/env python3
"""
Regression tests for 'and others' handling in author parsing

This test suite ensures that "and others" is treated the same as "et al"
in both text parsing and BibTeX parsing contexts.
"""

import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from utils.text_utils import parse_authors_with_initials
from core.refchecker import ArxivReferenceChecker


class TestAndOthersRegression(unittest.TestCase):
    """Test 'and others' handling regression fixes"""
    
    def test_and_others_in_bibtex_format(self):
        """Test 'and others' in BibTeX comma-separated format"""
        test_cases = [
            # Basic case
            ("Smith, John and Doe, Jane and others", ["Smith, John", "Doe, Jane", "et al"]),
            
            # Multiple authors with 'and others'
            ("Zheng, Lianmin and Yin, Liangsheng and Xie, Zhiqiang and others", 
             ["Zheng, Lianmin", "Yin, Liangsheng", "Xie, Zhiqiang", "et al"]),
            
            # Single author with 'and others'
            ("Smith, John and others", ["Smith, John", "et al"]),
            
            # Comparison: 'et al' should work the same way
            ("Smith, John and Doe, Jane and et al", ["Smith, John", "Doe, Jane", "et al"]),
            ("Smith, John and Doe, Jane and et al.", ["Smith, John", "Doe, Jane", "et al"]),
        ]
        
        for input_authors, expected_output in test_cases:
            with self.subTest(input_authors=input_authors):
                result = parse_authors_with_initials(input_authors)
                self.assertEqual(result, expected_output,
                               f"Failed for input: {input_authors}")
    
    def test_and_others_edge_cases(self):
        """Test edge cases for 'and others' handling"""
        test_cases = [
            # Case sensitivity
            ("Smith, John and Others", ["Smith, John", "et al"]),
            ("Smith, John and OTHERS", ["Smith, John", "et al"]),
            
            # No authors before 'and others' (should not add et al)
            ("and others", []),
            ("others", []),
            
            # Mixed with regular authors
            ("Smith, John and Jones, Sarah and Brown, Mike and others",
             ["Smith, John", "Jones, Sarah", "Brown, Mike", "et al"]),
        ]
        
        for input_authors, expected_output in test_cases:
            with self.subTest(input_authors=input_authors):
                result = parse_authors_with_initials(input_authors)
                self.assertEqual(result, expected_output,
                               f"Failed for input: {input_authors}")
    
    def test_bibtex_entry_parsing_with_and_others(self):
        """Test BibTeX entry parsing handles 'and others' correctly"""
        bibtex_content = '''
@article{test2023example,
  title={A Test Paper with Many Authors},
  author={Smith, John and Doe, Jane and Johnson, Mike and Williams, Sarah and Brown, David and others},
  journal={Test Journal},
  year={2023}
}
'''
        
        checker = ArxivReferenceChecker()
        entries = checker._parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(entries), 1, "Should parse exactly one entry")
        
        entry = entries[0]
        authors = entry.get('authors', [])
        
        # Should have 5 named authors plus 'et al'
        self.assertEqual(len(authors), 6, f"Expected 6 authors (5 named + et al), got: {authors}")
        
        # Last author should be 'et al'
        self.assertEqual(authors[-1], "et al", f"Last author should be 'et al', got: {authors[-1]}")
        
        # Should not contain 'others' as an author
        others_authors = [a for a in authors if 'others' in a.lower()]
        self.assertEqual(len(others_authors), 0, f"Should not contain 'others' as author: {others_authors}")
        
        # Check that named authors are preserved
        expected_named_authors = ["Smith, John", "Doe, Jane", "Johnson, Mike", "Williams, Sarah", "Brown, David"]
        self.assertEqual(authors[:-1], expected_named_authors, "Named authors not preserved correctly")
    
    def test_user_reported_case(self):
        """Test the specific case reported by the user"""
        user_bibtex = '''
@inproceedings{zheng2023judging,
  title={Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena},
  author={Zheng, Lianmin and Yin, Liangsheng and Xie, Zhiqiang and Sun, Chuyue Livia and Huang, Jeff and Yu, Cody Hao and Cao, Shiyi and Kozyrakis, Christos and Stoica, Ion and Gonzalez, Joseph E and others},
  booktitle={Advances in Neural Information Processing Systems},
  year={2023}
}
'''
        
        checker = ArxivReferenceChecker()
        entries = checker._parse_bibtex_references(user_bibtex)
        
        self.assertEqual(len(entries), 1, "Should parse exactly one entry")
        
        entry = entries[0]
        authors = entry.get('authors', [])
        
        # Should have the 10 named authors plus 'et al'
        self.assertEqual(len(authors), 11, f"Expected 11 authors (10 named + et al), got: {len(authors)}")
        
        # Last author should be 'et al'
        self.assertEqual(authors[-1], "et al", f"Last author should be 'et al', got: {authors[-1]}")
        
        # Check specific authors from the user's example
        expected_first_few = ["Zheng, Lianmin", "Yin, Liangsheng", "Xie, Zhiqiang", "Sun, Chuyue Livia"]
        self.assertEqual(authors[:4], expected_first_few, "First few authors don't match expected")
        
        expected_last_named = "Gonzalez, Joseph E"
        self.assertEqual(authors[-2], expected_last_named, f"Second-to-last author should be {expected_last_named}")
    
    def test_backwards_compatibility_et_al(self):
        """Ensure existing 'et al' handling still works correctly"""
        test_cases = [
            # Various 'et al' formats should still work
            ("Smith, John and et al", ["Smith, John", "et al"]),
            ("Smith, John and et al.", ["Smith, John", "et al"]),
            ("Doe, Jane and Jones, Mike and et al", ["Doe, Jane", "Jones, Mike", "et al"]),
        ]
        
        for input_authors, expected_output in test_cases:
            with self.subTest(input_authors=input_authors):
                result = parse_authors_with_initials(input_authors)
                self.assertEqual(result, expected_output,
                               f"Backwards compatibility failed for: {input_authors}")
    
    def test_no_false_positives(self):
        """Ensure words containing 'others' are not falsely converted"""
        test_cases = [
            # Author names that contain 'others' should not be converted
            ("Brothers, John and Sisters, Jane", ["Brothers, John", "Sisters, Jane"]),
            ("Mothers, Mary and Fathers, Frank", ["Mothers, Mary", "Fathers, Frank"]),
            
            # Regular author lists without et al indicators
            ("Smith, John and Doe, Jane and Brown, Mike", ["Smith, John", "Doe, Jane", "Brown, Mike"]),
        ]
        
        for input_authors, expected_output in test_cases:
            with self.subTest(input_authors=input_authors):
                result = parse_authors_with_initials(input_authors)
                self.assertEqual(result, expected_output,
                               f"False positive for: {input_authors}")
                
                # Ensure no 'et al' was incorrectly added
                self.assertNotIn("et al", result, f"'et al' incorrectly added to: {input_authors}")


if __name__ == '__main__':
    unittest.main()