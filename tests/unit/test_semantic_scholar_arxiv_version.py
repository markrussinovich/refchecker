"""
Unit tests for ArXiv version checking in Semantic Scholar checker.

Tests the new functionality that flags when a Semantic Scholar result has
an arXiv ID pointing to a paper with newer versions available.
"""

import unittest
from unittest.mock import patch, MagicMock
from refchecker.checkers.semantic_scholar import NonArxivReferenceChecker


class TestArxivVersionExtraction(unittest.TestCase):
    """Test extraction of ArXiv ID and version from references."""
    
    def setUp(self):
        self.checker = NonArxivReferenceChecker()
    
    def test_extract_arxiv_id_with_version(self):
        """Test extracting ArXiv ID when version is specified."""
        ref = {'url': 'https://arxiv.org/abs/1706.03762v2'}
        arxiv_id, version = self.checker._extract_arxiv_id_and_version(ref)
        self.assertEqual(arxiv_id, '1706.03762')
        self.assertEqual(version, 'v2')
    
    def test_extract_arxiv_id_without_version(self):
        """Test extracting ArXiv ID when no version is specified."""
        ref = {'url': 'https://arxiv.org/abs/1706.03762'}
        arxiv_id, version = self.checker._extract_arxiv_id_and_version(ref)
        self.assertEqual(arxiv_id, '1706.03762')
        self.assertIsNone(version)
    
    def test_extract_arxiv_id_from_pdf_url(self):
        """Test extracting ArXiv ID from PDF URL."""
        ref = {'url': 'https://arxiv.org/pdf/2301.12345v3.pdf'}
        arxiv_id, version = self.checker._extract_arxiv_id_and_version(ref)
        self.assertEqual(arxiv_id, '2301.12345')
        self.assertEqual(version, 'v3')
    
    def test_extract_arxiv_id_from_raw_text(self):
        """Test extracting ArXiv ID from raw text citation."""
        ref = {'raw_text': 'arXiv:1706.03762v5'}
        arxiv_id, version = self.checker._extract_arxiv_id_and_version(ref)
        self.assertEqual(arxiv_id, '1706.03762')
        self.assertEqual(version, 'v5')
    
    def test_no_arxiv_id(self):
        """Test when no ArXiv ID is present."""
        ref = {'url': 'https://doi.org/10.1000/example'}
        arxiv_id, version = self.checker._extract_arxiv_id_and_version(ref)
        self.assertIsNone(arxiv_id)
        self.assertIsNone(version)


class TestArxivVersionCheck(unittest.TestCase):
    """Test the version update checking functionality."""
    
    def setUp(self):
        self.checker = NonArxivReferenceChecker()
    
    @patch.object(NonArxivReferenceChecker, '_get_latest_arxiv_version_number')
    def test_version_update_converts_errors_to_warnings(self, mock_get_latest):
        """Test that errors are converted to warnings with version suffix when citing older version."""
        mock_get_latest.return_value = 5
        
        reference = {
            'url': 'https://arxiv.org/abs/1706.03762v2',
            'title': 'Attention Is All You Need'
        }
        paper_data = {
            'title': 'Attention Is All You Need',
            'authors': [{'name': 'Ashish Vaswani'}]
        }
        arxiv_id = '1706.03762'
        
        # Initial errors that should be converted to warnings
        errors = [
            {'error_type': 'title', 'error_details': 'Title mismatch', 'ref_title_correct': 'Correct Title'},
            {'error_type': 'author', 'error_details': 'Author count mismatch', 'ref_authors_correct': 'Author A, Author B'}
        ]
        
        warnings, matched_version = self.checker._check_arxiv_version_update(reference, paper_data, arxiv_id, errors)
        
        # Should have converted errors to warnings with version suffix
        self.assertEqual(matched_version, 2)
        self.assertEqual(len(warnings), 2)
        self.assertIn('warning_type', warnings[0])
        self.assertIn('(v2 vs v5 update)', warnings[0]['warning_type'])
        self.assertIn('(v2 vs v5 update)', warnings[1]['warning_type'])
        self.assertEqual(warnings[0]['ref_title_correct'], 'Correct Title')
    
    @patch.object(NonArxivReferenceChecker, '_get_latest_arxiv_version_number')
    def test_no_conversion_when_latest_version_cited(self, mock_get_latest):
        """Test errors remain as errors when latest version is cited."""
        mock_get_latest.return_value = 5
        
        reference = {
            'url': 'https://arxiv.org/abs/1706.03762v5',
            'title': 'Attention Is All You Need'
        }
        paper_data = {
            'title': 'Attention Is All You Need',
            'authors': [{'name': 'Ashish Vaswani'}]
        }
        arxiv_id = '1706.03762'
        errors = [{'error_type': 'title', 'error_details': 'Title mismatch'}]
        
        result_errors, matched_version = self.checker._check_arxiv_version_update(reference, paper_data, arxiv_id, errors)
        
        # Should return original errors unchanged when citing latest version
        self.assertIsNone(matched_version)
        self.assertEqual(result_errors, errors)
    
    @patch.object(NonArxivReferenceChecker, '_get_latest_arxiv_version_number')
    def test_no_conversion_when_single_version(self, mock_get_latest):
        """Test errors remain as errors when paper only has one version."""
        mock_get_latest.return_value = 1
        
        reference = {
            'url': 'https://arxiv.org/abs/2301.12345',
            'title': 'Some Paper'
        }
        paper_data = {
            'title': 'Some Paper',
            'authors': [{'name': 'Author'}]
        }
        arxiv_id = '2301.12345'
        errors = [{'error_type': 'title', 'error_details': 'Title mismatch'}]
        
        result_errors, matched_version = self.checker._check_arxiv_version_update(reference, paper_data, arxiv_id, errors)
        
        self.assertIsNone(matched_version)
        self.assertEqual(result_errors, errors)
    
    @patch.object(NonArxivReferenceChecker, '_get_latest_arxiv_version_number')
    def test_no_conversion_when_version_unknown(self, mock_get_latest):
        """Test errors remain unchanged when version cannot be determined."""
        mock_get_latest.return_value = None
        
        reference = {
            'url': 'https://arxiv.org/abs/2301.12345',
            'title': 'Some Paper'
        }
        paper_data = {
            'title': 'Some Paper',
            'authors': [{'name': 'Author'}]
        }
        arxiv_id = '2301.12345'
        errors = [{'error_type': 'title', 'error_details': 'Title mismatch'}]
        
        result_errors, matched_version = self.checker._check_arxiv_version_update(reference, paper_data, arxiv_id, errors)
        
        self.assertIsNone(matched_version)
        self.assertEqual(result_errors, errors)
    
    def test_convert_errors_to_version_warnings(self):
        """Test the error to warning conversion preserves all fields."""
        errors = [
            {'error_type': 'title', 'error_details': 'Title mismatch: cited vs actual', 'ref_title_correct': 'Correct Title'},
            {'error_type': 'author', 'error_details': 'Author count mismatch: 6 cited vs 8 correct', 'ref_authors_correct': 'A, B, C'},
            {'info_type': 'url', 'info_details': 'Consider adding URL', 'ref_url_correct': 'https://example.com'},
        ]
        
        version_suffix = " (v1 vs v3 update)"
        warnings = self.checker._convert_errors_to_version_warnings(errors, version_suffix)
        
        self.assertEqual(len(warnings), 3)
        
        # First error converted to warning
        self.assertEqual(warnings[0]['warning_type'], 'title (v1 vs v3 update)')
        self.assertEqual(warnings[0]['warning_details'], 'Title mismatch: cited vs actual')
        self.assertEqual(warnings[0]['ref_title_correct'], 'Correct Title')
        
        # Second error converted to warning
        self.assertEqual(warnings[1]['warning_type'], 'author (v1 vs v3 update)')
        self.assertEqual(warnings[1]['ref_authors_correct'], 'A, B, C')
        
        # Info type should remain unchanged
        self.assertEqual(warnings[2]['info_type'], 'url')


class TestLatestVersionFetch(unittest.TestCase):
    """Test fetching the latest version number from ArXiv."""
    
    def setUp(self):
        self.checker = NonArxivReferenceChecker()
    
    @patch('refchecker.checkers.semantic_scholar.requests.get')
    @patch('refchecker.utils.arxiv_rate_limiter.ArXivRateLimiter.wait')
    def test_parse_version_numbers_from_html(self, mock_wait, mock_get):
        """Test parsing version numbers from ArXiv abstract page."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '''
            <html>
            <body>
                <div class="submission-history">
                    From: Author [view email]<br>
                    [v1] Mon, 1 Jan 2024 00:00:00 UTC<br>
                    [v2] Tue, 2 Jan 2024 00:00:00 UTC<br>
                    [v3] Wed, 3 Jan 2024 00:00:00 UTC<br>
                </div>
            </body>
            </html>
        '''
        mock_get.return_value = mock_response
        
        latest_version = self.checker._get_latest_arxiv_version_number('2401.00000')
        
        self.assertEqual(latest_version, 3)


if __name__ == '__main__':
    unittest.main()
