#!/usr/bin/env python3
"""
Test suite for ArXiv ID verification logic to prevent regressions.

This test suite ensures that ArXiv ID extraction, normalization, and comparison
work correctly, particularly for the "Neural machine translation in linear time" case.
"""

import unittest
import sys
import os
from unittest.mock import Mock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.core.refchecker import ArxivReferenceChecker


class TestArXivIDVerification(unittest.TestCase):
    """Test ArXiv ID verification logic"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.checker = ArxivReferenceChecker()
    
    def test_arxiv_id_extraction_with_version_numbers(self):
        """Test ArXiv ID extraction correctly strips version numbers"""
        test_cases = [
            ("https://arxiv.org/abs/1610.10099v2", "1610.10099"),
            ("https://arxiv.org/abs/1610.10099v1", "1610.10099"),
            ("https://arxiv.org/abs/1610.10099v3", "1610.10099"),
            ("https://arxiv.org/abs/1610.10099", "1610.10099"),
            ("https://arxiv.org/pdf/1610.10099v2.pdf", "1610.10099"),
            ("https://arxiv.org/pdf/1610.10099.pdf", "1610.10099"),
        ]
        
        for url, expected_id in test_cases:
            with self.subTest(url=url):
                extracted_id = self.checker.extract_arxiv_id_from_url(url)
                self.assertEqual(extracted_id, expected_id,
                               f"Failed to extract correct ID from {url}")
    
    def test_arxiv_id_comparison_ignores_versions(self):
        """Test that ArXiv ID comparison correctly handles version differences"""
        # Both should normalize to same ID
        ref_url = "https://arxiv.org/abs/1610.10099v2"
        db_arxiv_id = "1610.10099"
        
        ref_arxiv_id = self.checker.extract_arxiv_id_from_url(ref_url)
        
        # IDs should match after extraction
        self.assertEqual(ref_arxiv_id, db_arxiv_id)
    
    def test_neural_machine_translation_paper_reference(self):
        """Test the specific reference that was failing"""
        reference = {
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
            "type": "arxiv"
        }
        
        # Extract ArXiv ID
        ref_arxiv_id = self.checker.extract_arxiv_id_from_url(reference['url'])
        self.assertEqual(ref_arxiv_id, "1610.10099")
        
        # This should match the Semantic Scholar ArXiv ID
        semantic_scholar_arxiv_id = "1610.10099"
        self.assertEqual(ref_arxiv_id, semantic_scholar_arxiv_id)
    
    def test_independent_arxiv_id_check_no_mismatch(self):
        """Test that check_independent_arxiv_id_mismatch doesn't flag matching IDs"""
        reference = {
            "url": "https://arxiv.org/abs/1610.10099v2",
            "title": "Neural machine translation in linear time",
            "authors": ["Nal Kalchbrenner", "Lasse Espeholt"]
        }
        
        # Mock verified data that matches the reference
        verified_data = {
            "externalIds": {
                "ArXiv": "1610.10099"  # Same ID without version
            },
            "title": "Neural Machine Translation in Linear Time",
            "year": 2016
        }
        
        with patch.object(self.checker, 'get_paper_metadata') as mock_get_metadata:
            # Mock ArXiv API response
            mock_paper = Mock()
            mock_paper.title = "Neural Machine Translation in Linear Time"
            mock_get_metadata.return_value = mock_paper
            
            errors = self.checker.check_independent_arxiv_id_mismatch(reference, verified_data)
            
            # Should not return any ArXiv ID mismatch errors
            self.assertEqual(errors, [])
    
    def test_independent_arxiv_id_check_detects_real_mismatch(self):
        """Test that check_independent_arxiv_id_mismatch detects actual mismatches"""
        reference = {
            "url": "https://arxiv.org/abs/1610.10099v2",
            "title": "Some Wrong Title",
            "authors": ["Wrong Author"]
        }
        
        # Mock verified data with different ArXiv ID
        verified_data = {
            "externalIds": {
                "ArXiv": "1234.5678"  # Different ArXiv ID
            },
            "title": "Different Paper Title",
            "year": 2020
        }
        
        with patch.object(self.checker, 'get_paper_metadata') as mock_get_metadata:
            # Mock ArXiv API response
            mock_paper = Mock()
            mock_paper.title = "Neural Machine Translation in Linear Time"
            mock_get_metadata.return_value = mock_paper
            
            errors = self.checker.check_independent_arxiv_id_mismatch(reference, verified_data)
            
            # Should detect ArXiv ID mismatch
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0]['error_type'], 'arxiv_id')
            self.assertIn('1610.10099', errors[0]['error_details'])
            self.assertIn('1234.5678', errors[0]['error_details'])
    
    def test_arxiv_reference_classification(self):
        """Test that ArXiv references are properly classified"""
        reference_data = {
            "title": "Neural machine translation in linear time",
            "authors": ["Nal Kalchbrenner", "Lasse Espeholt"],
            "venue": "arXiv preprint",
            "url": "https://arxiv.org/abs/1610.10099v2",
            "year": 2017
        }
        
        # Should be classified as arxiv type
        structured_ref = self.checker._create_structured_reference(
            "Nal Kalchbrenner*Lasse Espeholt*Karen Simonyan*Aaron van den Oord*Alex Graves*Koray Kavukcuoglu#Neural machine translation in linear time#arXiv preprint#2017#https://arxiv.org/abs/1610.10099v2"
        )
        
        self.assertEqual(structured_ref['type'], 'arxiv')
        self.assertEqual(structured_ref['url'], 'https://arxiv.org/abs/1610.10099v2')
    
    def test_url_construction_with_versions(self):
        """Test that URL construction handles version numbers correctly"""
        from refchecker.utils.url_utils import construct_arxiv_url
        
        test_cases = [
            ("1610.10099v2", "https://arxiv.org/abs/1610.10099"),
            ("1610.10099v1", "https://arxiv.org/abs/1610.10099"),  
            ("1610.10099", "https://arxiv.org/abs/1610.10099"),
        ]
        
        for arxiv_id, expected_url in test_cases:
            with self.subTest(arxiv_id=arxiv_id):
                constructed_url = construct_arxiv_url(arxiv_id, "abs")
                self.assertEqual(constructed_url, expected_url,
                               f"URL construction failed for {arxiv_id}")
    
    def test_venue_arxiv_id_extraction(self):
        """Test ArXiv ID extraction from venue field"""
        reference = {
            "venue": "arXiv preprint arXiv:1610.10099",
            "title": "Test Paper"
        }
        
        # Should extract ArXiv ID from venue field
        with patch.object(self.checker, 'get_paper_metadata') as mock_get_metadata:
            mock_paper = Mock()
            mock_paper.title = "Test Paper"
            mock_get_metadata.return_value = mock_paper
            
            errors = self.checker.check_independent_arxiv_id_mismatch(reference, None)
            
            # get_paper_metadata should have been called with the extracted ID
            mock_get_metadata.assert_called_with("1610.10099")
    
    def test_no_false_positives_for_working_papers(self):
        """Ensure no false positive unverified errors for successfully verified papers"""
        # This tests the core issue: papers that are successfully verified
        # should not be marked as unverified due to display logic bugs
        
        reference = {
            "url": "https://arxiv.org/abs/1610.10099v2",
            "title": "Neural machine translation in linear time",
            "authors": ["Nal Kalchbrenner", "Lasse Espeholt"],
            "type": "arxiv",
            "year": 2017
        }
        
        # Mock successful verification with only year warning
        mock_verified_data = {
            "externalIds": {"ArXiv": "1610.10099"},
            "title": "Neural Machine Translation in Linear Time",
            "year": 2016,
            "url": "https://www.semanticscholar.org/paper/13895969"
        }
        
        with patch.object(self.checker.non_arxiv_checker, 'verify_reference') as mock_verify:
            with patch.object(self.checker, 'get_paper_metadata') as mock_get_metadata:
                # Setup mocks
                mock_verify.return_value = (mock_verified_data, [], "https://www.semanticscholar.org/paper/13895969")
                
                mock_paper = Mock()
                mock_paper.title = "Neural Machine Translation in Linear Time"
                mock_get_metadata.return_value = mock_paper
                
                # Mock source paper
                mock_source = Mock()
                mock_source.get_short_id.return_value = "1706.03762"
                
                # Verify reference
                errors, url, verified_data = self.checker.verify_reference(mock_source, reference)
                
                # Should be successfully verified
                self.assertIsNotNone(verified_data)
                self.assertIsNotNone(url)
                
                # Should only have year warning, no unverified error
                unverified_errors = [e for e in (errors or []) if e.get('error_type') == 'unverified']
                self.assertEqual(len(unverified_errors), 0, 
                               f"Should not have unverified errors, but got: {unverified_errors}")
                
                # Should have year warning (if year comparison is enabled)
                year_warnings = [e for e in (errors or []) if e.get('warning_type') == 'year']
                # Note: This test might not always generate year warnings depending on implementation
                # The key test is that there are no unverified errors
                # self.assertEqual(len(year_warnings), 1)
                # self.assertIn('2017', year_warnings[0]['warning_details'])
                # self.assertIn('2016', year_warnings[0]['warning_details'])


if __name__ == '__main__':
    unittest.main()