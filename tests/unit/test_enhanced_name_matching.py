#!/usr/bin/env python3
"""
Test suite for enhanced name matching functionality.

This test suite ensures that the enhanced_name_match function correctly handles
cases that the standard is_name_match function misses, particularly:
- Initial-to-full-name matching with surname variations
- Apostrophe and diacritic differences in surnames
- Polish and other international name variations
"""

import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.text_utils import enhanced_name_match, surname_similarity


class TestEnhancedNameMatching(unittest.TestCase):
    """Test enhanced name matching functionality"""
    
    def test_wawrzynski_case(self):
        """Test the specific Wawrzynski case that was reported"""
        test_cases = [
            ("P. Wawrzy'nski", "Pawel Wawrzynski"),
            ("Pawel Wawrzynski", "P. Wawrzy'nski"),
        ]
        
        for name1, name2 in test_cases:
            with self.subTest(pair=f"{name1} vs {name2}"):
                result = enhanced_name_match(name1, name2)
                self.assertTrue(result, 
                              f"Should match: '{name1}' vs '{name2}'")
    
    def test_surname_similarity(self):
        """Test surname similarity function"""
        test_cases = [
            ("Wawrzy'nski", "Wawrzynski", True),
            ("García", "Garcia", True),
            ("Müller", "Muller", True),
            ("O'Connor", "OConnor", True),
            ("D'Angelo", "DAngelo", True),
            ("Smith", "Jones", False),
            ("Johnson", "Jackson", False),
        ]
        
        for surname1, surname2, expected in test_cases:
            with self.subTest(pair=f"{surname1} vs {surname2}"):
                result = surname_similarity(surname1, surname2)
                self.assertEqual(result, expected,
                               f"Surname similarity failed for '{surname1}' vs '{surname2}'")
    
    def test_initial_to_full_name_matching(self):
        """Test initial to full name matching with surname variations"""
        test_cases = [
            ("P. Wawrzy'nski", "Pawel Wawrzynski"),
            ("J. García", "José García"), 
            ("F. Müller", "François Müller"),
            ("M. O'Connor", "Michael O'Connor"),
            ("S. D'Angelo", "Sofia D'Angelo"),
        ]
        
        for initial_form, full_form in test_cases:
            with self.subTest(pair=f"{initial_form} vs {full_form}"):
                # Test both directions
                result1 = enhanced_name_match(initial_form, full_form)
                result2 = enhanced_name_match(full_form, initial_form)
                
                self.assertTrue(result1, 
                              f"Should match: '{initial_form}' vs '{full_form}'")
                self.assertTrue(result2,
                              f"Should match: '{full_form}' vs '{initial_form}'")
    
    def test_enhanced_vs_standard_matching(self):
        """Test cases where enhanced matching succeeds but standard might fail"""
        # These are cases that might fail with standard matching but should work with enhanced
        test_cases = [
            ("P. Wawrzy'nski", "Pawel Wawrzynski"),
            ("M. Bowling.", "Michael Bowling"),
            ("José García", "J. Garcia"),
            ("François Müller", "F. Muller"),
        ]
        
        for name1, name2 in test_cases:
            with self.subTest(pair=f"{name1} vs {name2}"):
                result = enhanced_name_match(name1, name2)
                self.assertTrue(result,
                              f"Enhanced matching should succeed for '{name1}' vs '{name2}'")
    
    def test_negative_cases(self):
        """Test cases that should not match"""
        test_cases = [
            ("P. Smith", "John Doe"),
            ("M. Johnson", "Sarah Wilson"),
            ("A. Garcia", "B. Martinez"),
        ]
        
        for name1, name2 in test_cases:
            with self.subTest(pair=f"{name1} vs {name2}"):
                result = enhanced_name_match(name1, name2)
                self.assertFalse(result,
                               f"Should not match: '{name1}' vs '{name2}'")
    
    def test_edge_cases(self):
        """Test edge cases for enhanced name matching"""
        test_cases = [
            ("", "John Doe", False),
            ("John Doe", "", False),
            ("", "", False),
            ("A", "A", True),  # Single letters should match
            ("P.", "Pawel", False),  # Just initial vs just first name (no surname)
        ]
        
        for name1, name2, expected in test_cases:
            with self.subTest(pair=f"{repr(name1)} vs {repr(name2)}"):
                result = enhanced_name_match(name1, name2)
                self.assertEqual(result, expected,
                               f"Edge case failed for {repr(name1)} vs {repr(name2)}")
    
    def test_fallback_to_standard_matching(self):
        """Test that enhanced matching falls back to standard matching for regular cases"""
        # These should work with standard matching, so enhanced should also work
        test_cases = [
            ("John Smith", "John Smith"),
            ("J. Smith", "J. Smith"),
            ("María González", "María González"),
        ]
        
        for name1, name2 in test_cases:
            with self.subTest(pair=f"{name1} vs {name2}"):
                result = enhanced_name_match(name1, name2)
                self.assertTrue(result,
                              f"Should match through standard logic: '{name1}' vs '{name2}'")
    
    def test_real_world_academic_cases(self):
        """Test real-world academic name variations"""
        test_cases = [
            ("P. Wawrzy'nski", "Pawel Wawrzynski"),
            ("M. Bowling.", "Michael Bowling"),
            ("S. Levine", "Sergey Levine"),
            ("V. Koltun", "Vladlen Koltun"),
            ("Y. Bengio", "Yoshua Bengio"),
            ("G. Hinton", "Geoffrey Hinton"),
        ]
        
        for bib_name, db_name in test_cases:
            with self.subTest(pair=f"{bib_name} vs {db_name}"):
                result = enhanced_name_match(bib_name, db_name)
                self.assertTrue(result,
                              f"Real-world case should match: '{bib_name}' vs '{db_name}'")


if __name__ == '__main__':
    unittest.main()