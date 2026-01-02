#!/usr/bin/env python3
"""
Unit tests for PDF Paper Checker
"""

import unittest
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from refchecker.checkers.pdf_paper_checker import PDFPaperChecker


class TestPDFPaperChecker(unittest.TestCase):
    """Test PDF paper checker functionality"""
    
    def setUp(self):
        self.checker = PDFPaperChecker()
    
    def test_can_check_reference_pdf_url(self):
        """Test that direct PDF URLs are recognized"""
        reference = {'url': 'https://example.com/document.pdf'}
        self.assertTrue(self.checker.can_check_reference(reference))
    
    def test_can_check_reference_institutional_domains(self):
        """Test that institutional domains are recognized"""
        test_cases = [
            'https://university.edu/research/paper',
            'https://government.gov/policy/report',
            'https://organization.org/study',
            'https://aecea.ca/resources/document'
        ]
        
        for url in test_cases:
            with self.subTest(url=url):
                reference = {'url': url}
                self.assertTrue(self.checker.can_check_reference(reference))
    
    def test_can_check_reference_non_pdf_domains(self):
        """Test that non-PDF domains are rejected"""
        test_cases = [
            'https://example.com/blog/post',
            'https://github.com/user/repo',
            'https://twitter.com/post'
        ]
        
        for url in test_cases:
            with self.subTest(url=url):
                reference = {'url': url}
                self.assertFalse(self.checker.can_check_reference(reference))
    
    def test_can_check_reference_no_url(self):
        """Test that references without URLs are rejected"""
        reference = {'title': 'Test Paper'}
        self.assertFalse(self.checker.can_check_reference(reference))
    
    def test_authors_match(self):
        """Test author matching logic"""
        # Exact match
        self.assertTrue(self.checker._authors_match("John Smith", "John Smith"))
        
        # Similar names
        self.assertTrue(self.checker._authors_match("J. Smith", "John Smith"))
        self.assertTrue(self.checker._authors_match("John Smith", "J. Smith"))
        
        # Different names
        self.assertFalse(self.checker._authors_match("John Smith", "Jane Doe"))
    
    def test_parse_title_and_authors(self):
        """Test title and author parsing from PDF text"""
        test_text = """
        Research Report 2025
        
        Important Study on Education Policy
        
        John Smith, Jane Doe, University of Example
        Mary Johnson, Example Institute
        
        Abstract: This study examines...
        """
        
        title, authors = self.checker._parse_title_and_authors(test_text)
        
        # Should extract a meaningful title
        self.assertGreater(len(title), 10)
        
        # Should find some authors
        self.assertGreater(len(authors), 0)
    
    @patch.object(PDFPaperChecker, '_download_pdf')
    @patch.object(PDFPaperChecker, '_extract_pdf_data')
    def test_verify_reference_success(self, mock_extract, mock_download):
        """Test successful PDF verification"""
        # Mock PDF download
        mock_download.return_value = b'%PDF-1.4 mock pdf content'
        
        # Mock PDF data extraction
        mock_extract.return_value = {
            'title': 'Test Document',
            'authors': ['Test Author'],
            'text': 'This is a test document with relevant content',
            'page_count': 5,
            'extraction_method': 'pdfplumber'
        }
        
        reference = {
            'title': 'Test Document',
            'authors': ['Test Author'],
            'venue': 'Test Venue',
            'url': 'https://example.org/test.pdf'
        }
        
        verified_data, errors, url = self.checker.verify_reference(reference)
        
        # Should be verified
        self.assertIsNotNone(verified_data)
        self.assertEqual(len(errors), 0)
        self.assertEqual(verified_data['title'], 'Test Document')
        self.assertEqual(verified_data['venue'], 'Test Venue')
        self.assertIn('pdf_metadata', verified_data)
    
    @patch.object(PDFPaperChecker, '_download_pdf')
    def test_verify_reference_download_failure(self, mock_download):
        """Test verification when PDF download fails"""
        # Mock failed download
        mock_download.return_value = None
        
        reference = {
            'title': 'Test Document',
            'url': 'https://example.org/test.pdf'
        }
        
        verified_data, errors, url = self.checker.verify_reference(reference)
        
        # Should not be verified
        self.assertIsNone(verified_data)
        self.assertEqual(len(errors), 1)
        self.assertIn('could not download PDF content', errors[0]['error_details'])
    
    @patch.object(PDFPaperChecker, '_find_pdf_url_in_page')
    @patch.object(PDFPaperChecker, '_download_pdf')
    def test_verify_reference_with_pdf_link_detection(self, mock_download, mock_find_pdf):
        """Test verification with PDF link detection"""
        # First download attempt fails (not a direct PDF)
        # Second download attempt succeeds (found PDF link)
        mock_download.side_effect = [None, b'%PDF-1.4 mock pdf content']
        
        # Mock finding PDF link
        mock_find_pdf.return_value = 'https://example.org/actual-document.pdf'
        
        reference = {
            'title': 'Test Document',
            'url': 'https://example.org/page-with-pdf-link'
        }
        
        # Should call find_pdf_url_in_page when direct download fails
        with patch.object(self.checker, '_extract_pdf_data') as mock_extract:
            mock_extract.return_value = {
                'title': 'Test Document',
                'text': 'test document content',
                'page_count': 1,
                'extraction_method': 'test'
            }
            
            verified_data, errors, url = self.checker.verify_reference(reference)
            
            # Should find the PDF link and verify
            mock_find_pdf.assert_called_once()
            self.assertEqual(mock_download.call_count, 2)  # Called twice
    
    def test_validate_citation_title_match(self):
        """Test citation validation with title matching"""
        reference = {
            'title': 'Test Document Title',
            'authors': ['Test Author']
        }
        
        pdf_data = {
            'title': 'Test Document Title',
            'authors': ['Test Author'],
            'text': 'This is the content of the test document title and more text'
        }
        
        is_valid, errors = self.checker._validate_citation(reference, pdf_data)
        
        self.assertTrue(is_valid)
        # Should have at most warning about authors (since they're found)
        error_types = [err.get('error_type') for err in errors]
        self.assertNotIn('unverified', error_types)
    
    def test_validate_citation_title_mismatch(self):
        """Test citation validation with title mismatch"""
        reference = {
            'title': 'Expected Document Title',
            'authors': ['Test Author']
        }
        
        pdf_data = {
            'title': 'Completely Different Title',
            'authors': ['Different Author'],
            'text': 'This document is about something completely different'
        }
        
        is_valid, errors = self.checker._validate_citation(reference, pdf_data)
        
        self.assertFalse(is_valid)
        self.assertGreater(len(errors), 0)
        self.assertIn('title not found in PDF content', errors[0]['error_details'])


if __name__ == '__main__':
    unittest.main()