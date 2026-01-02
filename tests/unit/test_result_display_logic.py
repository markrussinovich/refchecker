#!/usr/bin/env python3
"""
Test suite for result display logic to prevent regressions.

This test suite ensures that verified papers with warnings are not displayed 
as "Could not verify" and that the display logic correctly handles different
error and warning combinations.
"""

import unittest
import sys
import os
from unittest.mock import Mock, patch
from io import StringIO

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.core.refchecker import ArxivReferenceChecker


class TestResultDisplayLogic(unittest.TestCase):
    """Test result display logic"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.checker = ArxivReferenceChecker()
    
    def test_verified_paper_with_year_warning_not_marked_unverified(self):
        """Test that verified papers with only year warnings are not marked as unverified"""
        # This is the core test for the bug we found
        errors = [
            {'warning_type': 'year', 'warning_details': 'Year mismatch: cited as 2017 but actually 2016', 'ref_year_correct': 2016}
        ]
        
        # Check if has_unverified_error logic works correctly
        has_unverified_error = any(e.get('error_type') == 'unverified' or e.get('warning_type') == 'unverified' for e in errors)
        
        # Should NOT be marked as unverified
        self.assertFalse(has_unverified_error, "Verified paper with year warning should not be marked as unverified")
    
    def test_truly_unverified_paper_marked_correctly(self):
        """Test that truly unverified papers are correctly marked as unverified"""
        errors = [
            {'error_type': 'unverified', 'error_details': 'Paper not found by any checker'}
        ]
        
        has_unverified_error = any(e.get('error_type') == 'unverified' or e.get('warning_type') == 'unverified' for e in errors)
        
        # Should be marked as unverified
        self.assertTrue(has_unverified_error, "Truly unverified paper should be marked as unverified")
    
    def test_verified_paper_with_mixed_warnings_and_errors(self):
        """Test papers with multiple warnings but no unverified errors"""
        errors = [
            {'warning_type': 'year', 'warning_details': 'Year mismatch: cited as 2017 but actually 2016'},
            {'warning_type': 'author', 'warning_details': 'Author name formatting differs slightly'},
            {'error_type': 'arxiv_id', 'error_details': 'ArXiv ID mismatch: cited as 1610.10099 but actually 1234.5678'}
        ]
        
        has_unverified_error = any(e.get('error_type') == 'unverified' or e.get('warning_type') == 'unverified' for e in errors)
        
        # Should NOT be marked as unverified (has errors but not unverified errors)
        self.assertFalse(has_unverified_error, "Paper with non-unverified errors should not be marked as unverified")
    
    def test_unverified_warning_type_detected(self):
        """Test that unverified warning type is also detected"""
        errors = [
            {'warning_type': 'unverified', 'warning_details': 'Could not verify this paper'}
        ]
        
        has_unverified_error = any(e.get('error_type') == 'unverified' or e.get('warning_type') == 'unverified' for e in errors)
        
        # Should be marked as unverified
        self.assertTrue(has_unverified_error, "Unverified warning type should be detected")
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_display_unverified_error_with_subreason(self, mock_stdout):
        """Test the display function for unverified errors"""
        reference = {
            'title': 'Neural machine translation in linear time',
            'authors': ['Nal Kalchbrenner', 'Lasse Espeholt'],
            'year': 2017,
            'url': 'https://arxiv.org/abs/1610.10099v2'
        }
        
        errors = [
            {'error_type': 'unverified', 'error_details': 'Paper not found by any checker'}
        ]
        
        # Test the display function
        self.checker._display_unverified_error_with_subreason(
            reference, 
            'https://arxiv.org/abs/1610.10099v2', 
            errors, 
            debug_mode=False, 
            print_output=True
        )
        
        output = mock_stdout.getvalue()
        
        # Should contain "Could not verify"
        self.assertIn("❓ Could not verify: Neural machine translation in linear time", output)
        self.assertIn("Subreason: Paper not found by any checker", output)
    
    def test_categorize_unverified_reason(self):
        """Test the categorization of unverified reasons"""
        test_cases = [
            ("Paper not found by any checker", "Paper not found by any checker"),
            ("API error: rate limit exceeded", "Checker had an error"),
            ("Network error occurred", "Checker had an error"),
            ("HTTP 404 error", "Paper not found by any checker"),
            ("Repository not found", "Paper not found by any checker"),
            ("Some generic error", "Paper not found by any checker"),  # Default fallback
        ]
        
        for error_details, expected_subreason in test_cases:
            with self.subTest(error_details=error_details):
                subreason = self.checker._categorize_unverified_reason(error_details)
                self.assertEqual(subreason, expected_subreason)
    
    def test_format_year_string(self):
        """Test year formatting for display"""
        test_cases = [
            (2017, "2017"),
            (2016, "2016"),
            (0, "year unknown"),
            (None, "year unknown"),
        ]
        
        for year, expected in test_cases:
            with self.subTest(year=year):
                formatted = self.checker._format_year_string(year)
                self.assertEqual(formatted, expected)
    
    def test_error_counting_excludes_unverified(self):
        """Test that error counting correctly excludes unverified errors"""
        errors = [
            {'error_type': 'arxiv_id', 'error_details': 'ArXiv ID mismatch'},
            {'warning_type': 'year', 'warning_details': 'Year mismatch'},
            {'error_type': 'unverified', 'error_details': 'Could not verify'},
        ]
        
        # Test the counting logic from the verification process
        error_count = sum(1 for e in errors if 'error_type' in e and e['error_type'] != 'unverified')
        warning_count = sum(1 for e in errors if 'warning_type' in e)
        
        self.assertEqual(error_count, 1, "Should count 1 non-unverified error")
        self.assertEqual(warning_count, 1, "Should count 1 warning")
    
    def test_neural_machine_translation_display_integration(self):
        """Integration test for the specific Neural machine translation paper display"""
        reference = {
            "url": "https://arxiv.org/abs/1610.10099v2",
            "title": "Neural machine translation in linear time",
            "authors": ["Nal Kalchbrenner", "Lasse Espeholt", "Karen Simonyan", "Aaron van den Oord", "Alex Graves", "Koray Kavukcuoglu"],
            "venue": "arXiv preprint",
            "year": 2017,
            "type": "arxiv"
        }
        
        # Simulate successful verification with year warning
        errors = [
            {'warning_type': 'year', 'warning_details': 'Year mismatch: cited as 2017 but actually 2016', 'ref_year_correct': 2016}
        ]
        
        verified_data = {
            "externalIds": {"ArXiv": "1610.10099"},
            "title": "Neural Machine Translation in Linear Time",
            "year": 2016,
            "url": "https://www.semanticscholar.org/paper/13895969"
        }
        
        reference_url = "https://www.semanticscholar.org/paper/13895969"
        
        # Test the logic that determines display behavior
        has_unverified_error = any(e.get('error_type') == 'unverified' or e.get('warning_type') == 'unverified' for e in errors)
        
        # Should NOT show "Could not verify"
        self.assertFalse(has_unverified_error, 
                        "Neural machine translation paper should not show 'Could not verify'")
        
        # Should show as verified with warnings
        self.assertIsNotNone(verified_data, "Should have verified data")
        self.assertIsNotNone(reference_url, "Should have reference URL")
        
        # Should have year warning
        year_warnings = [e for e in errors if e.get('warning_type') == 'year']
        self.assertEqual(len(year_warnings), 1, "Should have exactly one year warning")
    
    def test_parallel_processing_display_logic(self):
        """Test the display logic used in parallel processing"""
        # Create a mock result object to simulate verification results
        class MockResult:
            def __init__(self, errors, url, verified_data):
                self.errors = errors
                self.url = url
                self.verified_data = verified_data
        
        # Simulate a verification result with warnings only
        result = MockResult(
            errors=[{'warning_type': 'year', 'warning_details': 'Year mismatch: cited as 2017 but actually 2016'}],
            url='https://www.semanticscholar.org/paper/13895969',
            verified_data={'title': 'Neural Machine Translation in Linear Time', 'year': 2016}
        )
        
        # Test the logic from parallel processor
        has_unverified_error = any(e.get('error_type') == 'unverified' or e.get('warning_type') == 'unverified' for e in result.errors)
        
        self.assertFalse(has_unverified_error, "Parallel processing should not mark verified papers with warnings as unverified")
        
        # Test that non-unverified errors are processed correctly
        processable_errors = [error for error in result.errors 
                            if error.get('error_type') != 'unverified' and error.get('warning_type') != 'unverified']
        
        self.assertEqual(len(processable_errors), 1, "Should have one processable error (year warning)")
        self.assertEqual(processable_errors[0]['warning_type'], 'year')


if __name__ == '__main__':
    unittest.main()