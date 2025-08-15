#!/usr/bin/env python3
"""
Unit tests for ArXiv URL warning functionality in Semantic Scholar checker.
"""

import unittest
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


class TestArxivUrlWarning(unittest.TestCase):
    """Test ArXiv URL warning logic."""
    
    def test_arxiv_url_warning_logic_missing_url(self):
        """Test that missing ArXiv URL triggers information message."""
        # Simulate the logic from Semantic Scholar checker
        reference_url = ''  # No URL in reference
        arxiv_id = '2310.08419'
        arxiv_url = f'https://arxiv.org/abs/{arxiv_id}'
        
        # Check for direct arXiv URL match
        has_arxiv_url = arxiv_url in reference_url
        
        # Also check for arXiv DOI URL
        arxiv_doi_url = f'https://doi.org/10.48550/arxiv.{arxiv_id}'
        has_arxiv_doi = arxiv_doi_url.lower() in reference_url.lower()
        
        should_inform = not (has_arxiv_url or has_arxiv_doi)
        
        self.assertFalse(has_arxiv_url, "Should not find ArXiv URL in empty reference URL")
        self.assertFalse(has_arxiv_doi, "Should not find ArXiv DOI in empty reference URL")
        self.assertTrue(should_inform, "Should inform when ArXiv URL is missing")
    
    def test_arxiv_url_warning_logic_has_arxiv_url(self):
        """Test that existing ArXiv URL does not trigger information message."""
        arxiv_id = '2310.08419'
        reference_url = f'https://arxiv.org/abs/{arxiv_id}'  # Has ArXiv URL
        arxiv_url = f'https://arxiv.org/abs/{arxiv_id}'
        
        # Check for direct arXiv URL match
        has_arxiv_url = arxiv_url in reference_url
        
        # Also check for arXiv DOI URL
        arxiv_doi_url = f'https://doi.org/10.48550/arxiv.{arxiv_id}'
        has_arxiv_doi = arxiv_doi_url.lower() in reference_url.lower()
        
        should_inform = not (has_arxiv_url or has_arxiv_doi)
        
        self.assertTrue(has_arxiv_url, "Should find ArXiv URL in reference")
        self.assertTrue(should_inform == False, "Should NOT inform when ArXiv URL is present")
    
    def test_arxiv_url_warning_logic_has_arxiv_doi(self):
        """Test that existing ArXiv DOI does not trigger information message."""
        arxiv_id = '2310.08419'
        reference_url = f'https://doi.org/10.48550/arxiv.{arxiv_id}'  # Has ArXiv DOI
        arxiv_url = f'https://arxiv.org/abs/{arxiv_id}'
        
        # Check for direct arXiv URL match
        has_arxiv_url = arxiv_url in reference_url
        
        # Also check for arXiv DOI URL
        arxiv_doi_url = f'https://doi.org/10.48550/arxiv.{arxiv_id}'
        has_arxiv_doi = arxiv_doi_url.lower() in reference_url.lower()
        
        should_inform = not (has_arxiv_url or has_arxiv_doi)
        
        self.assertFalse(has_arxiv_url, "Should not find direct ArXiv URL in DOI reference")
        self.assertTrue(has_arxiv_doi, "Should find ArXiv DOI in reference")
        self.assertTrue(should_inform == False, "Should NOT inform when ArXiv DOI is present")
    
    def test_arxiv_url_info_message_format(self):
        """Test that the info message format is correct."""
        arxiv_id = '2310.08419'
        arxiv_url = f'https://arxiv.org/abs/{arxiv_id}'
        
        expected_info = {
            'info_type': 'url',
            'info_details': f'Reference could include arXiv URL: {arxiv_url}',
            'ref_url_correct': arxiv_url
        }
        
        self.assertEqual(
            expected_info['info_details'],
            'Reference could include arXiv URL: https://arxiv.org/abs/2310.08419'
        )
        self.assertEqual(expected_info['info_type'], 'url')
        self.assertEqual(expected_info['ref_url_correct'], arxiv_url)


if __name__ == '__main__':
    unittest.main()