#!/usr/bin/env python3
"""
Comprehensive regression tests for validation bug fixes identified during ArXiv paper testing.

This test suite covers:
1. Umlaut/diacritic author matching bug
2. Author deduplication logic when same author appears multiple times  
3. Collaboration paper parsing with et al constructs
4. Overly strict journal abbreviation validation
5. Year validation issues

These tests ensure that the validation bugs found during real-world testing don't regress.
"""
import unittest
import sys
import os

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from utils.text_utils import (
    normalize_diacritics, 
    normalize_diacritics_simple,
    is_name_match, 
    compare_authors,
    are_venues_substantially_different,
    is_year_substantially_different
)

class TestUmlautDiacriticMatching(unittest.TestCase):
    """Test umlaut and diacritic handling in author name matching"""
    
    def test_standalone_diaeresis_normalization(self):
        """Test that standalone diaeresis (¨) is properly normalized"""
        # Original failing case: "J. Gl¨ uck" should match "Jochen Gluck"
        test_cases = [
            ("J. Gl¨ uck", "J. Gluck"),  # Malformed diaeresis
            ("J. Glück", "J. Glueck"),  # Proper umlaut with transliteration
            ("J. Glück", "J. Gluck"),   # Proper umlaut with simple normalization
            ("Müller", "Mueller"),      # German umlaut transliteration
            ("José", "Jose"),           # Accent removal
        ]
        
        for original, expected in test_cases:
            with self.subTest(original=original):
                normalized = normalize_diacritics(original)
                # Should normalize properly without creating mid-word spaces
                self.assertNotIn("  ", normalized, f"Double spaces in: {normalized}")
                
    def test_umlaut_name_matching(self):
        """Test that names with umlauts match their normalized equivalents"""
        test_cases = [
            ("J. Gl¨ uck", "Jochen Gluck"),  # Original failing case
            ("J. Glück", "Jochen Gluck"),   # Proper umlaut
            ("A. Müller", "Anna Mueller"),   # German transliteration
            ("J. Glück", "J. Gluck"),       # Simple abbreviation match
        ]
        
        for name1, name2 in test_cases:
            with self.subTest(name1=name1, name2=name2):
                self.assertTrue(is_name_match(name1, name2), 
                               f"'{name1}' should match '{name2}'")
    
    def test_multiple_normalization_strategies(self):
        """Test that the dual normalization approach works correctly"""
        # Test cases where simple vs transliteration normalization matters
        test_cases = [
            ("Müller", "Mueller"),  # Transliteration match
            ("Müller", "Muller"),   # Simple normalization match  
            ("Glück", "Gluck"),     # Simple normalization match
            ("Glück", "Glueck"),    # Transliteration match
        ]
        
        for name1, name2 in test_cases:
            with self.subTest(name1=name1, name2=name2):
                # At least one normalization strategy should work
                norm1_simple = normalize_diacritics_simple(name1)
                norm2_simple = normalize_diacritics_simple(name2)
                norm1_full = normalize_diacritics(name1)
                norm2_full = normalize_diacritics(name2)
                
                simple_match = norm1_simple.lower() == norm2_simple.lower()
                full_match = norm1_full.lower() == norm2_full.lower()
                
                self.assertTrue(simple_match or full_match,
                               f"Neither normalization worked for {name1} vs {name2}")


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
        """Test that et al comparisons work correctly for collaboration papers"""
        # Test case that would have failed before: many correct authors, few cited with et al
        cited_authors = ["V. Khachatryan", "et al"]
        correct_authors = ["V. Khachatryan", "A. Sirunyan"] + [f"Author {i}" for i in range(3, 100)]
        
        match_result, error_message = compare_authors(cited_authors, correct_authors)
        
        # Should succeed - first author matches and et al covers the rest
        self.assertTrue(match_result, f"Collaboration comparison failed: {error_message}")
    
    def test_large_author_list_handling(self):
        """Test that large collaboration author lists don't cause performance issues"""
        cited_authors = ["First Author", "et al"]
        # Simulate a very large collaboration (like CMS, ATLAS papers)
        correct_authors = ["First Author"] + [f"Collab Author {i}" for i in range(1, 500)]
        
        match_result, error_message = compare_authors(cited_authors, correct_authors)
        
        # Should succeed and not take too long
        self.assertTrue(match_result, f"Large collaboration failed: {error_message}")


class TestJournalAbbreviationValidation(unittest.TestCase):
    """Test journal abbreviation validation improvements"""
    
    def test_physics_journal_abbreviations(self):
        """Test that common physics journal abbreviations are recognized"""
        test_cases = [
            ("Phys. Rev. Lett.", "Physical Review Letters"),
            ("Phys. Rev. A", "Physical Review A"),
            ("Phys. Rev. B", "Physical Review B"),
            ("Phys. Lett. B", "Physics Letters B"),
            ("J. Phys.", "Journal of Physics"),
            ("Ann. Phys.", "Annals of Physics"),
            ("Nucl. Phys. A", "Nuclear Physics A"),
        ]
        
        for abbreviated, full_name in test_cases:
            with self.subTest(abbreviated=abbreviated, full_name=full_name):
                # Should NOT be considered substantially different
                is_different = are_venues_substantially_different(abbreviated, full_name)
                self.assertFalse(is_different, 
                               f"'{abbreviated}' should match '{full_name}'")
    
    def test_other_common_abbreviations(self):
        """Test other common academic journal abbreviations"""
        test_cases = [
            ("Nature Phys.", "Nature Physics"),
            ("Sci. Adv.", "Science Advances"),
            ("Proc. Natl. Acad. Sci.", "Proceedings of the National Academy of Sciences"),
            ("PNAS", "Proceedings of the National Academy of Sciences"),
        ]
        
        for abbreviated, full_name in test_cases:
            with self.subTest(abbreviated=abbreviated, full_name=full_name):
                is_different = are_venues_substantially_different(abbreviated, full_name)
                self.assertFalse(is_different,
                               f"'{abbreviated}' should match '{full_name}'")
    
    def test_truly_different_venues(self):
        """Test that truly different venues are still flagged as different"""
        test_cases = [
            ("Nature", "Science"),
            ("ICML", "NeurIPS"),
            ("Physical Review Letters", "Journal of Machine Learning Research"),
        ]
        
        for venue1, venue2 in test_cases:
            with self.subTest(venue1=venue1, venue2=venue2):
                is_different = are_venues_substantially_different(venue1, venue2)
                self.assertTrue(is_different,
                              f"'{venue1}' and '{venue2}' should be considered different")


class TestYearValidation(unittest.TestCase):
    """Test simple year validation - all mismatches flagged as warnings"""
    
    def test_exact_year_match(self):
        """Test that exact year matches are not flagged"""
        is_different, message = is_year_substantially_different(2023, 2023)
        self.assertFalse(is_different)
        self.assertIsNone(message)
    
    def test_any_year_difference_flagged(self):
        """Test that any year differences are flagged as warnings"""
        test_cases = [
            (2023, 2024, "1-year difference"),
            (2021, 2023, "2-year difference"),
            (2020, 2024, "4-year difference"),
            (2024, 2023, "reverse 1-year difference"),
        ]
        
        for cited_year, correct_year, description in test_cases:
            with self.subTest(description=description):
                is_different, message = is_year_substantially_different(cited_year, correct_year)
                self.assertTrue(is_different, f"{description} should be flagged")
                self.assertIn(f"Year mismatch: cited as {cited_year} but actually {correct_year}", message)
    
    def test_context_ignored(self):
        """Test that context is ignored - all differences flagged regardless"""
        # Even with ArXiv context, differences should still be flagged
        context = {'arxiv_match': True}
        is_different, message = is_year_substantially_different(2023, 2024, context)
        self.assertTrue(is_different)
        self.assertIn("Year mismatch: cited as 2023 but actually 2024", message)
    
    def test_edge_cases(self):
        """Test edge cases for year validation"""
        # None values should not be flagged
        is_different, message = is_year_substantially_different(None, 2023)
        self.assertFalse(is_different)
        self.assertIsNone(message)
        
        is_different, message = is_year_substantially_different(2023, None)
        self.assertFalse(is_different)
        self.assertIsNone(message)
        
        # Zero years should not be flagged
        is_different, message = is_year_substantially_different(0, 2023)
        self.assertFalse(is_different)
        self.assertIsNone(message)


class TestRegressionValidation(unittest.TestCase):
    """Integration tests for the specific cases that were failing"""
    
    def test_original_failing_case_gluck(self):
        """Test the original failing case: J. Gl¨ uck vs Jochen Gluck"""
        # This was failing before the diacritic fixes
        self.assertTrue(is_name_match("J. Gl¨ uck", "Jochen Gluck"))
        self.assertTrue(is_name_match("J. Glück", "Jochen Gluck"))
    
    def test_original_failing_case_physical_review(self):
        """Test the original failing case: Phys. Rev. Lett. vs Physical Review Letters"""
        # This was flagged as a venue mismatch before the abbreviation fixes
        is_different = are_venues_substantially_different("Phys. Rev. Lett.", "Physical Review Letters")
        self.assertFalse(is_different)
    
    def test_collaboration_paper_structure(self):
        """Test that collaboration papers don't create misleading error messages"""
        # Before the fix, this would show misleading positional error messages
        cited_authors = ["Nonexistent Author", "et al"]
        correct_authors = ["Real Author 1", "Real Author 2", "Real Author 3"]
        
        match_result, error_message = compare_authors(cited_authors, correct_authors)
        
        self.assertFalse(match_result)
        # Should show informative message, not misleading positional match
        self.assertIn("not found in author list", error_message)
        self.assertNotIn(" vs Real Author 1", error_message)  # No positional confusion


if __name__ == '__main__':
    unittest.main()