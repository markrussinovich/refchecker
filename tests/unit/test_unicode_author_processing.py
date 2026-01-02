#!/usr/bin/env python3
"""
Test suite for Unicode author name processing to prevent regressions.

This test suite ensures that Unicode handling in author name processing works correctly:
- LaTeX escaped characters are properly converted
- Unicode normalization works correctly
- Polish and other diacritics are handled properly
- Existing functionality is preserved
"""

import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.text_utils import clean_author_name


class TestUnicodeAuthorProcessing(unittest.TestCase):
    """Test Unicode author name processing functionality"""
    
    def test_latex_escaped_characters(self):
        """Test that LaTeX escaped characters are properly converted"""
        test_cases = [
            ("P. Wawrzy\\'nski", "P. Wawrzy'nski"),
            ("John\\'s Paper", "John's Paper"),
            ("Author\\\"Quote", "Author\"Quote"),
            ("Em--dash Test", "Em–dash Test"),
            ("Em---dash Test", "Em—dash Test"),
            ("Non~breaking~space", "Non breaking space"),
        ]
        
        for input_name, expected_output in test_cases:
            with self.subTest(input_name=input_name):
                result = clean_author_name(input_name)
                self.assertEqual(result, expected_output,
                               f"Failed to process LaTeX escape in '{input_name}'")
    
    def test_polish_diacritics(self):
        """Test that Polish diacritic handling works correctly"""
        test_cases = [
            ("Pawel Wawrzynski", "Pawel Wawrzynski"),  # Normal case
            ("Paweł Wawrzyński", "Paweł Wawrzyński"),  # Proper Unicode
            ("Jan Kowalski", "Jan Kowalski"),
        ]
        
        for input_name, expected_output in test_cases:
            with self.subTest(input_name=input_name):
                result = clean_author_name(input_name)
                self.assertEqual(result, expected_output,
                               f"Failed to process Polish name '{input_name}'")
    
    def test_unicode_normalization(self):
        """Test Unicode normalization (NFKC)"""
        import unicodedata
        
        # Test cases with combining characters vs precomposed
        test_cases = [
            ("José", "José"),  # Should normalize to NFC form
            ("naïve", "naïve"),  # i with combining diaeresis vs precomposed
            ("café", "café"),   # e with combining acute vs precomposed
        ]
        
        for input_name, expected_base in test_cases:
            with self.subTest(input_name=input_name):
                result = clean_author_name(input_name)
                # Check that result is in normalized form
                normalized_expected = unicodedata.normalize('NFKC', expected_base)
                self.assertEqual(result, normalized_expected,
                               f"Failed to normalize '{input_name}'")
    
    def test_mixed_unicode_and_latex(self):
        """Test mixed Unicode and LaTeX processing"""
        test_cases = [
            ("José García\\'s Work", "José García's Work"),
            ("François M\\\"uller", "François M\"uller"),
            ("André~van~der~Berg", "André van der Berg"),
        ]
        
        for input_name, expected_output in test_cases:
            with self.subTest(input_name=input_name):
                result = clean_author_name(input_name)
                self.assertEqual(result, expected_output,
                               f"Failed to process mixed Unicode/LaTeX '{input_name}'")
    
    def test_preserve_existing_functionality(self):
        """Test that existing functionality is preserved"""
        test_cases = [
            ("M. Bowling.", "M. Bowling"),  # Period removal
            ("Dr. John Smith", "John Smith"),  # Title removal
            ("John Smith (University)", "John Smith"),  # Affiliation removal
            ("J. Smith†", "J. Smith"),  # Symbol removal
            ("John  Multiple   Spaces", "John Multiple Spaces"),  # Space normalization
        ]
        
        for input_name, expected_output in test_cases:
            with self.subTest(input_name=input_name):
                result = clean_author_name(input_name)
                self.assertEqual(result, expected_output,
                               f"Existing functionality broken for '{input_name}'")
    
    def test_comprehensive_author_processing(self):
        """Test comprehensive author name processing"""
        test_cases = [
            ("Dr. Paweł Wawrzyński.", "Paweł Wawrzyński"),
            ("Prof. José García (MIT)", "José García"),
            ("M.~G.~Bellemare†", "M. G. Bellemare"),
            ("François\\\"Muller\\\"", "François\"Muller\""),
        ]
        
        for input_name, expected_output in test_cases:
            with self.subTest(input_name=input_name):
                result = clean_author_name(input_name)
                self.assertEqual(result, expected_output,
                               f"Comprehensive processing failed for '{input_name}'")
    
    def test_real_world_unicode_cases(self):
        """Test real-world Unicode cases from academic papers"""
        test_cases = [
            # Common European names
            ("Björn Andersson", "Björn Andersson"),
            ("François Chollet", "François Chollet"),
            ("José Martínez", "José Martínez"),
            ("Müller, Hans", "Müller, Hans"),
            
            # Asian names (that might have Unicode issues)
            ("李明", "李明"),
            ("田中太郎", "田中太郎"),
            
            # Names with apostrophes
            ("O'Connor", "O'Connor"),
            ("D'Angelo", "D'Angelo"),
        ]
        
        for input_name, expected_output in test_cases:
            with self.subTest(input_name=input_name):
                result = clean_author_name(input_name)
                self.assertEqual(result, expected_output,
                               f"Real-world case failed for '{input_name}'")
    
    def test_edge_cases_unicode(self):
        """Test Unicode edge cases"""
        test_cases = [
            ("", ""),  # Empty string
            ("A", "A"),  # Single character
            ("José García-López", "José García-López"),  # Hyphenated names
            ("van der Berg", "van der Berg"),  # Particles
            ("MacPherson", "MacPherson"),  # Scottish names
        ]
        
        for input_name, expected_output in test_cases:
            with self.subTest(input_name=input_name):
                result = clean_author_name(input_name)
                self.assertEqual(result, expected_output,
                               f"Edge case failed for '{input_name}'")
    
    def test_author_matching_similarity(self):
        """Test that Unicode processing helps with author matching"""
        # These should be processable for matching
        matching_pairs = [
            ("P. Wawrzy\\'nski", "Pawel Wawrzynski"),
            ("M. Bowling.", "Michael Bowling"),
            ("J. García", "José García"),
            ("F. Müller", "François Müller"),
        ]
        
        for bib_form, db_form in matching_pairs:
            with self.subTest(pair=f"{bib_form} vs {db_form}"):
                cleaned_bib = clean_author_name(bib_form)
                cleaned_db = clean_author_name(db_form)
                
                # Basic similarity checks
                # 1. First initials should match
                if cleaned_bib and cleaned_db:
                    bib_first = cleaned_bib.split()[0] if cleaned_bib.split() else ""
                    db_first = cleaned_db.split()[0] if cleaned_db.split() else ""
                    
                    if len(bib_first) == 2 and bib_first.endswith('.'):  # Initial form
                        self.assertEqual(bib_first[0].upper(), db_first[0].upper(),
                                       f"First initial mismatch: {cleaned_bib} vs {cleaned_db}")
                    
                    # 2. Last names should be comparable
                    bib_last = cleaned_bib.split()[-1].lower().replace("'", "") if cleaned_bib.split() else ""
                    db_last = cleaned_db.split()[-1].lower().replace("'", "") if cleaned_db.split() else ""
                    
                    # Should be substring or similar
                    self.assertTrue(
                        bib_last in db_last or db_last in bib_last or bib_last == db_last,
                        f"Last name similarity failed: {bib_last} vs {db_last}"
                    )


if __name__ == '__main__':
    unittest.main()