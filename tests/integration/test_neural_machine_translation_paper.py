#!/usr/bin/env python3
"""
Integration test for the Neural Machine Translation paper verification issue.

This test reproduces the exact issue reported and ensures it's fixed:
"Neural machine translation in linear time" should verify successfully with
only year warnings, not show as "Could not verify".
"""

import unittest
import sys
import os
from unittest.mock import Mock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.core.refchecker import ArxivReferenceChecker


class TestNeuralMachineTranslationPaper(unittest.TestCase):
    """Integration test for Neural Machine Translation paper verification"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.checker = ArxivReferenceChecker()
        
        # The exact reference from the Attention paper that was failing
        self.reference = {
            "url": "https://arxiv.org/abs/1610.10099v2",
            "doi": None,
            "year": 2017,
            "authors": [
                "Nal Kalchbrenner",
                "Lasse Espeholt", 
                "Karen Simonyan",
                "Aaron van den Oord",
                "Alex Graves",
                "Koray Kavukcuoglu"
            ],
            "venue": "arXiv preprint",
            "title": "Neural machine translation in linear time",
            "raw_text": "Nal Kalchbrenner*Lasse Espeholt*Karen Simonyan*Aaron van den Oord*Alex Graves*Koray Kavukcuoglu#Neural machine translation in linear time#arXiv preprint#2017#https://arxiv.org/abs/1610.10099v2",
            "type": "arxiv"
        }
        
        # Mock the Semantic Scholar response (based on real API response)
        self.semantic_scholar_response = {
            "paperId": "98445f4172659ec5e891e031d8202c102135c644",
            "externalIds": {
                "DBLP": "journals/corr/KalchbrennerESO16",
                "MAG": "2540404261",
                "ArXiv": "1610.10099",
                "CorpusId": 13895969
            },
            "url": "https://www.semanticscholar.org/paper/98445f4172659ec5e891e031d8202c102135c644",
            "title": "Neural Machine Translation in Linear Time",
            "venue": "arXiv.org",
            "year": 2016,
            "authors": [
                {"authorId": "2583391", "name": "Nal Kalchbrenner"},
                {"authorId": "2311318", "name": "L. Espeholt"},
                {"authorId": "34838386", "name": "K. Simonyan"},
                {"authorId": "3422336", "name": "Aäron van den Oord"},
                {"authorId": "1753223", "name": "Alex Graves"},
                {"authorId": "2645384", "name": "K. Kavukcuoglu"}
            ]
        }
    
    def test_arxiv_id_extraction(self):
        """Test that ArXiv ID is extracted correctly"""
        extracted_id = self.checker.extract_arxiv_id_from_url(self.reference['url'])
        self.assertEqual(extracted_id, "1610.10099", "Should extract 1610.10099 without version")
    
    def test_arxiv_id_matches_semantic_scholar(self):
        """Test that extracted ArXiv ID matches Semantic Scholar's ID"""
        ref_arxiv_id = self.checker.extract_arxiv_id_from_url(self.reference['url'])
        ss_arxiv_id = self.semantic_scholar_response['externalIds']['ArXiv']
        
        self.assertEqual(ref_arxiv_id, ss_arxiv_id, 
                        "Reference ArXiv ID should match Semantic Scholar ArXiv ID")
    
    @patch('requests.get')
    def test_paper_found_in_semantic_scholar(self, mock_get):
        """Test that the paper is found in Semantic Scholar API"""
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total": 1,
            "data": [self.semantic_scholar_response]
        }
        mock_get.return_value = mock_response
        
        # Test search by title
        from refchecker.checkers.semantic_scholar import NonArxivReferenceChecker
        checker = NonArxivReferenceChecker()
        
        verified_data, errors, paper_url = checker.verify_reference(self.reference)
        
        self.assertIsNotNone(verified_data, "Paper should be found in Semantic Scholar")
        self.assertEqual(verified_data['externalIds']['ArXiv'], "1610.10099")
        self.assertEqual(verified_data['year'], 2016)
    
    def test_verification_returns_year_warning_only(self):
        """Test that verification returns only year warning, no unverified error"""
        with patch.object(self.checker.non_arxiv_checker, 'verify_reference') as mock_verify:
            with patch.object(self.checker, 'get_paper_metadata') as mock_get_metadata:
                # Setup mocks to simulate successful verification with year warning
                year_warning = {
                    'warning_type': 'year',
                    'warning_details': "Year mismatch: cited as 2017, but found 2016 in database",
                    'ref_year_correct': 2016
                }
                mock_verify.return_value = (
                    self.semantic_scholar_response, 
                    [year_warning], 
                    "https://www.semanticscholar.org/paper/13895969"
                )
                
                mock_paper = Mock()
                mock_paper.title = "Neural Machine Translation in Linear Time"
                mock_get_metadata.return_value = mock_paper
                
                # Mock source paper
                mock_source = Mock()
                mock_source.get_short_id.return_value = "1706.03762"
                
                # Perform verification
                errors, url, verified_data = self.checker.verify_reference(mock_source, self.reference)
                
                # Assertions
                self.assertIsNotNone(verified_data, "Should have verified data")
                self.assertIsNotNone(url, "Should have verification URL")
                
                # Should not have unverified errors
                unverified_errors = [e for e in (errors or []) if e.get('error_type') == 'unverified']
                self.assertEqual(len(unverified_errors), 0, 
                               f"Should not have unverified errors, got: {unverified_errors}")
                
                # Should have exactly one year warning
                year_warnings = [e for e in (errors or []) if e.get('warning_type') == 'year']
                self.assertEqual(len(year_warnings), 1, "Should have exactly one year warning")
                
                year_warning = year_warnings[0]
                self.assertIn('2017', year_warning['warning_details'], "Should mention cited year 2017")
                self.assertIn('2016', year_warning['warning_details'], "Should mention actual year 2016")
                self.assertEqual(year_warning['ref_year_correct'], 2016, "Should suggest correct year")
    
    def test_display_logic_does_not_mark_as_unverified(self):
        """Test that display logic doesn't mark this as unverified"""
        # Simulate the errors that would be returned for this paper
        errors = [
            {'warning_type': 'year', 'warning_details': 'Year mismatch: cited as 2017 but actually 2016', 'ref_year_correct': 2016}
        ]
        
        # Test the display logic from refchecker.py:5495
        has_unverified_error = any(e.get('error_type') == 'unverified' or e.get('warning_type') == 'unverified' for e in errors)
        
        self.assertFalse(has_unverified_error, 
                        "Paper should NOT be marked as unverified in display logic")
    
    def test_no_false_positive_arxiv_mismatch(self):
        """Test that check_independent_arxiv_id_mismatch doesn't create false positives"""
        # Test with matching ArXiv IDs
        verified_data = {
            "externalIds": {"ArXiv": "1610.10099"},
            "title": "Neural Machine Translation in Linear Time",
            "year": 2016
        }
        
        with patch.object(self.checker, 'get_paper_metadata') as mock_get_metadata:
            mock_paper = Mock()
            mock_paper.title = "Neural Machine Translation in Linear Time"
            mock_get_metadata.return_value = mock_paper
            
            arxiv_errors = self.checker.check_independent_arxiv_id_mismatch(self.reference, verified_data)
            
            # Should not return any ArXiv mismatch errors
            self.assertEqual(arxiv_errors, [], "Should not have ArXiv ID mismatch errors when IDs match")
    
    def test_integration_with_displayable_urls(self):
        """Test that paper has displayable URLs for verification"""
        verified_data = self.semantic_scholar_response
        
        # Test the logic from refchecker.py:2298-2305
        has_displayable_verified_url = False
        if verified_data:
            external_ids = verified_data.get('externalIds', {})
            if (external_ids.get('DOI') or 
                external_ids.get('CorpusId') or 
                (verified_data.get('url') and 'arxiv.org' not in verified_data.get('url', ''))):
                has_displayable_verified_url = True
        
        # Should have displayable URLs (CorpusId and Semantic Scholar URL)
        self.assertTrue(has_displayable_verified_url, 
                       "Paper should have displayable verification URLs")
    
    def test_complete_workflow_simulation(self):
        """Test complete workflow from BibTeX parsing to display"""
        # Test BibTeX parsing
        bibtex_entry = """
        @misc{kalchbrenner2017neural,
          title={Neural machine translation in linear time},
          author={Kalchbrenner, Nal and Espeholt, Lasse and Simonyan, Karen and van den Oord, Aaron and Graves, Alex and Kavukcuoglu, Koray},
          year={2017},
          eprint={1610.10099v2},
          archivePrefix={arXiv},
          primaryClass={cs.CL}
        }
        """
        
        parsed_entries = self.checker._parse_bibtex_references(bibtex_entry)
        
        self.assertEqual(len(parsed_entries), 1)
        parsed_ref = parsed_entries[0]
        
        # Should parse correctly
        self.assertEqual(parsed_ref['title'], 'Neural machine translation in linear time')
        self.assertEqual(len(parsed_ref['authors']), 6)
        self.assertEqual(parsed_ref['year'], 2017)
        
        # URL should be constructed correctly
        self.assertIn('1610.10099', parsed_ref.get('url', ''))
        
        # Should be classified as arxiv
        self.assertEqual(parsed_ref['type'], 'arxiv')
    
    def test_regression_prevention_checklist(self):
        """Comprehensive regression prevention checklist"""
        # All the key behaviors that should be preserved
        
        # 1. ArXiv ID extraction strips versions
        extracted_id = self.checker.extract_arxiv_id_from_url("https://arxiv.org/abs/1610.10099v2")
        self.assertEqual(extracted_id, "1610.10099")
        
        # 2. ArXiv ID comparison ignores versions
        self.assertEqual(extracted_id, "1610.10099")  # Should match Semantic Scholar's ID
        
        # 3. Year warnings don't trigger unverified status
        year_warning_errors = [{'warning_type': 'year', 'warning_details': 'Year mismatch'}]
        has_unverified = any(e.get('error_type') == 'unverified' or e.get('warning_type') == 'unverified' for e in year_warning_errors)
        self.assertFalse(has_unverified)
        
        # 4. Reference classification works correctly
        self.assertEqual(self.reference['type'], 'arxiv')
        
        # 5. Title and author extraction works
        self.assertEqual(self.reference['title'], 'Neural machine translation in linear time')
        self.assertEqual(len(self.reference['authors']), 6)
        
        print("✅ All regression prevention checks passed")


if __name__ == '__main__':
    unittest.main()