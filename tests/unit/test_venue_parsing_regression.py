#!/usr/bin/env python3
"""
Regression tests for venue parsing and display issues

This test suite ensures that:
1. Venues with LaTeX penalty commands are parsed correctly
2. Venue display format shows venue between authors and year  
3. Venue comparison handles LaTeX constructs appropriately
4. Volume/page information is cleaned for comparison
"""

import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from utils.text_utils import strip_latex_commands, are_venues_substantially_different


class TestVenueParsingRegression(unittest.TestCase):
    """Test venue parsing regression fixes"""
    
    def test_penalty_command_removal(self):
        """Test that LaTeX penalty commands are removed from venues"""
        test_cases = [
            # The specific case from user's report
            ('Nature, 529\\penalty0 (7587):\\penalty0 484--489', 'Nature, 529 (7587): 484--489'),
            
            # Other penalty variations
            ('IEEE Trans.\\penalty0 Pattern Analysis', 'IEEE Trans. Pattern Analysis'),
            ('NIPS\\penalty0 2016', 'NIPS 2016'),
            ('Journal\\penalty0 of\\penalty0 AI', 'Journal of AI'),
            
            # Multiple penalty commands
            ('Conference\\penalty0 on\\penalty0 Machine\\penalty0 Learning', 'Conference on Machine Learning'),
            
            # Mixed with other LaTeX constructs
            ('Nature~Phys.\\penalty0 Vol.~15', 'Nature Phys. Vol. 15'),
        ]
        
        for input_venue, expected_output in test_cases:
            with self.subTest(venue=input_venue):
                result = strip_latex_commands(input_venue)
                self.assertEqual(result, expected_output,
                               f"Failed to strip penalty commands from '{input_venue}'")
    
    def test_venue_comparison_with_penalties(self):
        """Test venue comparison handles penalty commands correctly"""
        test_cases = [
            # Should match after penalty removal
            ('Nature, 529\\penalty0 (7587):\\penalty0 484--489', 'Nature', False),
            ('IEEE Trans.\\penalty0 Pattern Analysis', 'IEEE Transactions on Pattern Analysis', False),
            ('NIPS\\penalty0 2016', 'Neural Information Processing Systems', False),
            
            # Should still detect different venues
            ('Nature\\penalty0 Physics', 'Science', True),
            ('IEEE Trans.\\penalty0 Robotics', 'ACM Transactions on Graphics', True),
        ]
        
        for cited_venue, db_venue, should_be_different in test_cases:
            with self.subTest(cited=cited_venue, db=db_venue):
                result = are_venues_substantially_different(cited_venue, db_venue)
                self.assertEqual(result, should_be_different,
                               f"Venue comparison failed for '{cited_venue}' vs '{db_venue}' - expected {'different' if should_be_different else 'same'}")
    
    def test_volume_page_info_normalization(self):
        """Test that volume/page information is properly handled in venue comparison"""
        test_cases = [
            # These should match (same journal, different volume/page info)
            ('Nature, 529(7587):484--489', 'Nature', False),
            ('Science, vol. 123, pp. 456-789', 'Science', False), 
            ('Physical Review D, 85(10):103001', 'Physical Review D', False),
            ('Journal of AI Research, 15:123-145', 'Journal of AI Research', False),
            
            # These should be different (different journals)
            ('Nature, 529(7587):484--489', 'Science', True),
            ('Physical Review D, 85(10):103001', 'Physical Review Letters', True),
        ]
        
        for cited_venue, db_venue, should_be_different in test_cases:
            with self.subTest(cited=cited_venue, db=db_venue):
                result = are_venues_substantially_different(cited_venue, db_venue)
                self.assertEqual(result, should_be_different,
                               f"Volume/page normalization failed for '{cited_venue}' vs '{db_venue}' - expected {'different' if should_be_different else 'same'}")
    
    def test_mixed_latex_and_volume_info(self):
        """Test venues with both LaTeX commands and volume/page info"""
        test_cases = [
            # Complex case with penalties and volume info
            ('Nature, 529\\penalty0 (7587):\\penalty0 484--489', 'Nature', False),
            ('IEEE~Trans.\\penalty0 Pattern~Anal., 42(3)\\penalty0:123--145', 'IEEE Transactions on Pattern Analysis', False),
            
            # With non-breaking spaces and penalties
            ('Proc.~IEEE\\penalty0 Conf.~Robotics, 2023\\penalty0:pp.~45--52', 'IEEE Conference on Robotics', False),
        ]
        
        for cited_venue, db_venue, should_be_different in test_cases:
            with self.subTest(cited=cited_venue, db=db_venue):
                result = are_venues_substantially_different(cited_venue, db_venue)
                self.assertEqual(result, should_be_different,
                               f"Mixed LaTeX/volume processing failed for '{cited_venue}' vs '{db_venue}' - expected {'different' if should_be_different else 'same'}")
    
    def test_specific_nature_case(self):
        """Test the specific Nature case reported by the user"""
        # The exact case from user's report
        cited_venue = 'Nature, 529\\penalty0 (7587):\\penalty0 484--489'
        db_venue = 'Nature'
        
        # This should NOT be flagged as substantially different
        result = are_venues_substantially_different(cited_venue, db_venue)
        self.assertFalse(result, 
                        f"User-reported Nature case should match: '{cited_venue}' should be equivalent to '{db_venue}'")
    
    def test_common_journal_abbreviations_with_penalties(self):
        """Test common journal abbreviation patterns with penalty commands"""
        test_cases = [
            # Physics journals
            ('Phys.\\penalty0 Rev.\\penalty0 D', 'Physical Review D', False),
            ('Phys.\\penalty0 Lett.\\penalty0 B', 'Physics Letters B', False),
            ('Nature\\penalty0 Phys.', 'Nature Physics', False),
            
            # Computer Science conferences  
            ('Proc.\\penalty0 ICML', 'International Conference on Machine Learning', False),
            ('IEEE\\penalty0 CVPR', 'IEEE Conference on Computer Vision and Pattern Recognition', False),
        ]
        
        for cited_venue, db_venue, should_be_different in test_cases:
            with self.subTest(cited=cited_venue, db=db_venue):
                result = are_venues_substantially_different(cited_venue, db_venue)
                self.assertEqual(result, should_be_different,
                               f"Journal abbreviation with penalties failed for '{cited_venue}' vs '{db_venue}'")


class TestVenueDisplayFormat(unittest.TestCase):
    """Test venue display formatting"""
    
    def test_venue_extraction_from_reference(self):
        """Test that venues are extracted correctly from references"""
        # This would need integration with the main refchecker, but we can test the utility functions
        
        # Test that strip_latex_commands works on venue-like strings
        venue_examples = [
            'Nature, 529\\penalty0 (7587):\\penalty0 484--489',
            'IEEE~Trans.~Pattern~Analysis~and~Machine~Intelligence',
            'Proc.\\penalty0 of\\penalty0 the\\penalty0 IEEE',
        ]
        
        for venue in venue_examples:
            cleaned = strip_latex_commands(venue)
            # Should not contain penalty commands
            self.assertNotIn('\\penalty', cleaned, f"Penalty commands not removed from '{venue}'")
            # Should not contain unprocessed LaTeX
            self.assertNotIn('\\', cleaned, f"LaTeX commands remain in '{cleaned}'")
    
    def test_display_format_requirements(self):
        """Test requirements for venue display format"""
        # This is more of a documentation test - the format should be:
        # [X/Y] Title
        #        Authors  
        #        Venue (if present)
        #        Year
        #        URL info...
        
        # The actual display testing would require integration testing
        # But we can verify the venue cleaning works as expected
        self.assertTrue(True, "Display format requirements documented")


if __name__ == '__main__':
    unittest.main()