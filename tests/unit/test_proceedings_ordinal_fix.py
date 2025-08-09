#!/usr/bin/env python3
"""
Test suite for proceedings with ordinal numbers fix

This test ensures that venue names like "Proceedings of the ACM SIGOPS 29th Symposium..."
are correctly normalized to match their canonical forms.
"""

import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from utils.text_utils import normalize_venue_for_display, are_venues_substantially_different


class TestProceedingsOrdinalFix(unittest.TestCase):
    """Test proceedings normalization with ordinal numbers"""
    
    def test_acm_sigops_29th_symposium(self):
        """Test the specific case that was failing"""
        cited_venue = 'Proceedings of the ACM SIGOPS 29th Symposium on Operating Systems Principles'
        actual_venue = 'Symposium on Operating Systems Principles'
        
        # Test normalization
        normalized_cited = normalize_venue_for_display(cited_venue)
        normalized_actual = normalize_venue_for_display(actual_venue)
        
        self.assertEqual(normalized_cited, 'Symposium on Operating Systems Principles')
        self.assertEqual(normalized_actual, 'Symposium on Operating Systems Principles')
        self.assertEqual(normalized_cited, normalized_actual)
        
        # Test venue comparison
        self.assertFalse(are_venues_substantially_different(cited_venue, actual_venue),
                        "These venues should be considered the same after normalization")
        
        # Test that no venue warning would be generated (simulating the checker logic)
        from utils.error_utils import create_venue_warning
        should_create_warning = are_venues_substantially_different(cited_venue, actual_venue)
        self.assertFalse(should_create_warning, 
                        "No venue warning should be generated for properly normalized venues")
    
    def test_ieee_ordinal_conference(self):
        """Test IEEE proceedings with ordinals"""
        cited_venue = 'Proceedings of the IEEE 25th International Conference on Computer Vision'
        actual_venue = 'International Conference on Computer Vision'
        
        normalized_cited = normalize_venue_for_display(cited_venue)
        normalized_actual = normalize_venue_for_display(actual_venue)
        
        self.assertEqual(normalized_cited, 'International Conference on Computer Vision')
        self.assertEqual(normalized_actual, 'International Conference on Computer Vision')
        self.assertEqual(normalized_cited, normalized_actual)
        
        self.assertFalse(are_venues_substantially_different(cited_venue, actual_venue))
    
    def test_usenix_osdi_ordinal(self):
        """Test USENIX OSDI with ordinals"""
        cited_venue = 'Proceedings of the USENIX OSDI 15th Symposium on Operating Systems Design'
        actual_venue = 'Symposium on Operating Systems Design'
        
        normalized_cited = normalize_venue_for_display(cited_venue)
        normalized_actual = normalize_venue_for_display(actual_venue)
        
        self.assertEqual(normalized_cited, 'Symposium on Operating Systems Design')
        self.assertEqual(normalized_actual, 'Symposium on Operating Systems Design')
        self.assertEqual(normalized_cited, normalized_actual)
        
        self.assertFalse(are_venues_substantially_different(cited_venue, actual_venue))
    
    def test_simple_ordinal_proceedings(self):
        """Test proceedings with simple ordinals (no org names)"""
        cited_venue = 'Proceedings of the 29th Conference on Machine Learning'
        actual_venue = 'Conference on Machine Learning'
        
        normalized_cited = normalize_venue_for_display(cited_venue)
        normalized_actual = normalize_venue_for_display(actual_venue)
        
        self.assertEqual(normalized_cited, 'Conference on Machine Learning')
        self.assertEqual(normalized_actual, 'Conference on Machine Learning')
        self.assertEqual(normalized_cited, normalized_actual)
        
        self.assertFalse(are_venues_substantially_different(cited_venue, actual_venue))
    
    def test_neurips_preserved(self):
        """Test that proceedings without org prefixes are preserved correctly"""
        # This case should NOT be over-processed
        venue = 'Proceedings of Neural Information Processing Systems'
        normalized = normalize_venue_for_display(venue)
        
        # Should preserve the full name, not just "Systems"
        self.assertEqual(normalized, 'Neural Information Processing Systems')
    
    def test_multiple_organization_names(self):
        """Test proceedings with multiple organization acronyms"""
        cited_venue = 'Proceedings of the ACM SIGCOMM 45th Annual Conference on Data Communication'
        actual_venue = 'Annual Conference on Data Communication'
        
        normalized_cited = normalize_venue_for_display(cited_venue)
        normalized_actual = normalize_venue_for_display(actual_venue)
        
        self.assertEqual(normalized_cited, 'Annual Conference on Data Communication')
        self.assertEqual(normalized_actual, 'Annual Conference on Data Communication')
        self.assertEqual(normalized_cited, normalized_actual)
        
        self.assertFalse(are_venues_substantially_different(cited_venue, actual_venue))
    
    def test_edge_cases(self):
        """Test edge cases that should not be affected"""
        test_cases = [
            # Regular journals should not be affected
            ('IEEE Transactions on Software Engineering', 'IEEE Transactions on Software Engineering'),
            
            # Conference names without proceedings prefix should not be affected
            ('Neural Information Processing Systems', 'Neural Information Processing Systems'),
            
            # Proceedings without ordinals should work as before
            ('Proceedings of the International Conference on Learning', 'International Conference on Learning'),
        ]
        
        for input_venue, expected_output in test_cases:
            with self.subTest(venue=input_venue):
                normalized = normalize_venue_for_display(input_venue)
                self.assertEqual(normalized, expected_output)


if __name__ == '__main__':
    unittest.main()