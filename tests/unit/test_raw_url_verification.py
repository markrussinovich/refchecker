#!/usr/bin/env python3
"""
Unit tests for raw URL verification functionality.
Tests the new logic that verifies URLs when paper validators fail.
"""

import unittest
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.checkers.webpage_checker import WebPageChecker
from refchecker.core.refchecker import ArxivReferenceChecker


class TestRawUrlVerification(unittest.TestCase):
    """Test raw URL verification logic."""
    
    def setUp(self):
        self.webpage_checker = WebPageChecker()
        self.refchecker = ArxivReferenceChecker()
    
    @patch('refchecker.checkers.webpage_checker.WebPageChecker._respectful_request')
    def test_nonexistent_page_returns_correct_error(self, mock_request):
        """Test that non-existent pages return the correct error message."""
        # Mock a 404 response
        mock_request.return_value = None
        
        reference = {
            'title': 'Test Paper',
            'authors': ['John Doe'],
            'year': 2023,
            'url': 'https://example.com/nonexistent'
        }
        
        verified_data, errors, url = self.webpage_checker.verify_raw_url_for_unverified_reference(reference)
        
        self.assertIsNone(verified_data)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['error_type'], 'unverified')
        self.assertEqual(errors[0]['error_details'], 'non-existent web page')
        self.assertEqual(url, 'https://example.com/nonexistent')
    
    @patch('refchecker.checkers.webpage_checker.WebPageChecker._respectful_request')
    def test_existing_page_no_title_match_no_venue(self, mock_request):
        """Test existing page without title match and no venue specified."""
        # Mock a successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'text/html'}
        mock_response.url = 'https://example.com/page'
        mock_response.content = b'<html><head><title>Different Title</title></head><body>Some content</body></html>'
        mock_request.return_value = mock_response
        
        reference = {
            'title': 'Machine Learning Paper',
            'authors': ['John Doe'],
            'year': 2023,
            'url': 'https://example.com/page'
            # No venue specified
        }
        
        verified_data, errors, url = self.webpage_checker.verify_raw_url_for_unverified_reference(reference)
        
        self.assertIsNone(verified_data)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['error_type'], 'unverified')
        self.assertEqual(errors[0]['error_details'], "paper not found and URL doesn't reference it")
        self.assertEqual(url, 'https://example.com/page')
    
    @patch('refchecker.checkers.webpage_checker.WebPageChecker._respectful_request')
    def test_existing_page_title_match_no_venue_verified(self, mock_request):
        """Test existing page with title match and no venue - should be verified."""
        # Mock a successful response with title match
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'text/html'}
        mock_response.url = 'https://example.com/page'
        mock_response.content = b'<html><head><title>Machine Learning Research</title></head><body>This page contains information about Machine Learning Research and related topics.</body></html>'
        mock_request.return_value = mock_response
        
        reference = {
            'title': 'Machine Learning Research',
            'authors': ['John Doe'],
            'year': 2023,
            'url': 'https://example.com/page'
            # No venue specified
        }
        
        verified_data, errors, url = self.webpage_checker.verify_raw_url_for_unverified_reference(reference)
        
        self.assertIsNotNone(verified_data)
        self.assertEqual(len(errors), 0)
        self.assertEqual(verified_data['title'], 'Machine Learning Research')
        self.assertEqual(verified_data['authors'], ['John Doe'])
        self.assertEqual(verified_data['year'], 2023)
        self.assertIn(verified_data['venue'], ['Web Page', 'Example'])  # Can be either depending on organization extraction
        self.assertEqual(verified_data['url'], 'https://example.com/page')
        self.assertEqual(url, 'https://example.com/page')
    
    @patch('refchecker.checkers.webpage_checker.WebPageChecker._respectful_request')
    def test_existing_page_title_match_with_venue_unverified(self, mock_request):
        """Test existing page with title match but venue specified - should remain unverified."""
        # Mock a successful response with title match
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'text/html'}
        mock_response.url = 'https://example.com/page'
        mock_response.content = b'<html><head><title>Machine Learning Research</title></head><body>This page contains information about Machine Learning Research.</body></html>'
        mock_request.return_value = mock_response
        
        reference = {
            'title': 'Machine Learning Research',
            'authors': ['John Doe'],
            'year': 2023,
            'url': 'https://example.com/page',
            'journal': 'Nature'  # Venue specified
        }
        
        verified_data, errors, url = self.webpage_checker.verify_raw_url_for_unverified_reference(reference)
        
        self.assertIsNone(verified_data)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['error_type'], 'unverified')
        self.assertEqual(errors[0]['error_details'], 'paper not verified but URL references paper')
        self.assertEqual(url, 'https://example.com/page')
    
    @patch('refchecker.checkers.webpage_checker.WebPageChecker._respectful_request')
    def test_pdf_document_no_venue_verified(self, mock_request):
        """Test PDF document without venue specified - should be verified."""
        # Mock a PDF response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'application/pdf'}
        mock_response.url = 'https://example.com/paper.pdf'
        mock_request.return_value = mock_response
        
        reference = {
            'title': 'Research Paper',
            'authors': ['Jane Smith'],
            'year': 2023,
            'url': 'https://example.com/paper.pdf'
            # No venue specified
        }
        
        verified_data, errors, url = self.webpage_checker.verify_raw_url_for_unverified_reference(reference)
        
        self.assertIsNotNone(verified_data)
        self.assertEqual(len(errors), 0)
        self.assertEqual(verified_data['title'], 'Research Paper')
        self.assertEqual(verified_data['venue'], 'PDF Document')
        self.assertEqual(verified_data['url'], 'https://example.com/paper.pdf')
    
    @patch('refchecker.checkers.webpage_checker.WebPageChecker._respectful_request')
    def test_403_blocked_no_venue_verified(self, mock_request):
        """Test 403 blocked resource without venue - should be verified."""
        # Mock a 403 response
        mock_response = Mock()
        mock_response.status_code = 403
        mock_request.return_value = mock_response
        
        reference = {
            'title': 'Blocked Resource',
            'authors': ['Test Author'],
            'year': 2023,
            'url': 'https://example.com/blocked'
            # No venue specified
        }
        
        verified_data, errors, url = self.webpage_checker.verify_raw_url_for_unverified_reference(reference)
        
        self.assertIsNotNone(verified_data)
        self.assertEqual(len(errors), 0)
        self.assertEqual(verified_data['venue'], 'Web Page')
        self.assertTrue(verified_data['web_metadata']['access_blocked'])
    
    def test_categorization_of_new_error_messages(self):
        """Test that the new error messages are properly categorized."""
        test_cases = [
            ("non-existent web page", "Non-existent web page"),
            ("paper not found and URL doesn't reference it", "Paper not found and URL doesn't reference it"),
            ("paper not verified but URL references paper", "Paper not verified but URL references paper")
        ]
        
        for error_details, expected_category in test_cases:
            with self.subTest(error_details=error_details):
                category = self.refchecker._categorize_unverified_reason(error_details)
                self.assertEqual(category, expected_category)
    
    def test_no_url_returns_appropriate_error(self):
        """Test that references without URLs return appropriate error."""
        reference = {
            'title': 'Test Paper',
            'authors': ['John Doe'],
            'year': 2023
            # No URL
        }
        
        verified_data, errors, url = self.webpage_checker.verify_raw_url_for_unverified_reference(reference)
        
        self.assertIsNone(verified_data)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['error_type'], 'unverified')
        self.assertEqual(errors[0]['error_details'], "paper not found and URL doesn't reference it")
        self.assertIsNone(url)
    
    @patch('refchecker.checkers.webpage_checker.WebPageChecker._respectful_request')
    def test_partial_title_match_no_venue_verified(self, mock_request):
        """Test partial title match (60% threshold) without venue - should be verified."""
        # Mock a successful response with partial title match
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'text/html'}
        mock_response.url = 'https://example.com/page'
        # Content has most key words from title
        mock_response.content = b'<html><head><title>Research Page</title></head><body>This page discusses advanced machine learning techniques and neural networks.</body></html>'
        mock_request.return_value = mock_response
        
        reference = {
            'title': 'Advanced Machine Learning Techniques',
            'authors': ['John Doe'],
            'year': 2023,
            'url': 'https://example.com/page'
            # No venue specified
        }
        
        verified_data, errors, url = self.webpage_checker.verify_raw_url_for_unverified_reference(reference)
        
        self.assertIsNotNone(verified_data)
        self.assertEqual(len(errors), 0)
        self.assertIn(verified_data['venue'], ['Web Page', 'Example'])  # Can be either depending on organization extraction
    
    @patch('refchecker.checkers.webpage_checker.WebPageChecker.verify_raw_url_for_unverified_reference')
    def test_integration_with_main_verifier(self, mock_url_verify):
        """Test integration with the main reference verifier."""
        # Mock URL verification returning verified data
        mock_verified_data = {
            'title': 'Test Paper',
            'authors': ['John Doe'],
            'year': 2023,
            'venue': 'Web Page',
            'url': 'https://example.com/test'
        }
        mock_url_verify.return_value = (mock_verified_data, [], 'https://example.com/test')
        
        reference = {
            'title': 'Test Paper',
            'authors': ['John Doe'],
            'year': 2023,
            'url': 'https://example.com/test',
            'raw_text': 'Test reference'
        }
        
        source_paper = {'title': 'Source Paper', 'authors': ['Author']}
        
        # Should return verified data from URL verification
        verified_data, errors, url = self.refchecker.verify_raw_url_reference(reference)
        
        self.assertIsNotNone(verified_data)
        self.assertEqual(len(errors), 0)
        self.assertEqual(url, 'https://example.com/test')
        self.assertEqual(verified_data['venue'], 'Web Page')


class TestWebContentVenues(unittest.TestCase):
    """Test web content venue detection and verification"""
    
    def test_news_venue_verified(self):
        """Test that news venues are correctly verified"""
        checker = WebPageChecker()
        
        # Test various news venues
        news_venues = [
            "CBC News",
            "BBC News", 
            "CNN",
            "Reuters",
            "The Guardian",
            "New York Times",
            "Wall Street Journal"
        ]
        
        for venue in news_venues:
            with self.subTest(venue=venue):
                self.assertTrue(checker._is_web_content_venue(venue, "https://example.com/news/article"))
    
    def test_tech_publication_venue_verified(self):
        """Test that tech publications are correctly verified"""
        checker = WebPageChecker()
        
        tech_venues = [
            "TechCrunch",
            "Wired",
            "The Verge", 
            "Ars Technica",
            "MIT Technology Review"
        ]
        
        for venue in tech_venues:
            with self.subTest(venue=venue):
                self.assertTrue(checker._is_web_content_venue(venue, "https://example.com/tech/article"))
    
    def test_blog_platform_venue_verified(self):
        """Test that blog platforms are correctly verified"""
        checker = WebPageChecker()
        
        blog_venues = [
            "Medium",
            "Company Blog",
            "Personal Blog",
            "Substack"
        ]
        
        for venue in blog_venues:
            with self.subTest(venue=venue):
                self.assertTrue(checker._is_web_content_venue(venue, "https://example.com/blog/post"))
    
    def test_academic_venue_not_web_content(self):
        """Test that academic venues are not considered web content"""
        checker = WebPageChecker()
        
        academic_venues = [
            "Nature",
            "Science",
            "Proceedings of the IEEE",
            "ACM Transactions on Graphics",
            "International Conference on Machine Learning",
            "Journal of Artificial Intelligence Research"
        ]
        
        for venue in academic_venues:
            with self.subTest(venue=venue):
                self.assertFalse(checker._is_web_content_venue(venue, "https://example.com/paper"))
    
    def test_url_domain_influences_detection(self):
        """Test that URL domain can influence web content detection"""
        checker = WebPageChecker()
        
        # Generic venue but URL suggests news content
        self.assertTrue(checker._is_web_content_venue("Some Publication", "https://cbc.ca/news/article"))
        self.assertTrue(checker._is_web_content_venue("Article", "https://techcrunch.com/blog/post"))
        self.assertTrue(checker._is_web_content_venue("Report", "https://medium.com/@author/story"))
        
        # Generic venue with academic URL should not be web content
        self.assertFalse(checker._is_web_content_venue("Some Publication", "https://ieee.org/paper"))

    @patch.object(WebPageChecker, '_respectful_request')
    def test_news_article_with_venue_verified(self, mock_request):
        """Test that a news article with proper venue gets verified"""
        checker = WebPageChecker()
        
        # Mock successful HTTP response with title match
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'text/html'}
        mock_response.content = b'''
        <html>
            <head><title>Breaking News: Important Story</title></head>
            <body>
                <h1>Breaking News: Important Story</h1>
                <p>This is the full content of the important story...</p>
            </body>
        </html>
        '''
        mock_response.url = "https://cbc.ca/news/important-story"
        mock_request.return_value = mock_response
        
        reference = {
            'title': 'Breaking News: Important Story',
            'authors': ['Reporter Name'],
            'year': '2025',
            'venue': 'CBC News',
            'url': 'https://cbc.ca/news/important-story'
        }
        
        verified_data, errors, url = checker.verify_raw_url_for_unverified_reference(reference)
        
        # Should be verified because it's a news venue with matching content
        self.assertIsNotNone(verified_data)
        self.assertEqual(len(errors), 0)
        self.assertEqual(verified_data['venue'], 'CBC News')  # Original venue preserved
        self.assertEqual(verified_data['url'], reference['url'])


class TestVenueDetection(unittest.TestCase):
    """Test venue detection logic for URL verification."""
    
    def test_no_venue_detected_correctly(self):
        """Test that references without venues are detected correctly."""
        references_without_venue = [
            {'title': 'Test', 'authors': ['A'], 'url': 'http://example.com'},
            {'title': 'Test', 'authors': ['A'], 'journal': '', 'url': 'http://example.com'},
            {'title': 'Test', 'authors': ['A'], 'venue': None, 'url': 'http://example.com'},
            {'title': 'Test', 'authors': ['A'], 'booktitle': '', 'url': 'http://example.com'}
        ]
        
        for ref in references_without_venue:
            with self.subTest(ref=ref):
                has_venue = bool(ref.get('journal') or ref.get('venue') or ref.get('booktitle'))
                self.assertFalse(has_venue, f"Reference should not have venue: {ref}")
    
    def test_venue_detected_correctly(self):
        """Test that references with venues are detected correctly."""
        references_with_venue = [
            {'title': 'Test', 'authors': ['A'], 'journal': 'Nature', 'url': 'http://example.com'},
            {'title': 'Test', 'authors': ['A'], 'venue': 'Conference', 'url': 'http://example.com'},
            {'title': 'Test', 'authors': ['A'], 'booktitle': 'Proceedings', 'url': 'http://example.com'}
        ]
        
        for ref in references_with_venue:
            with self.subTest(ref=ref):
                has_venue = bool(ref.get('journal') or ref.get('venue') or ref.get('booktitle'))
                self.assertTrue(has_venue, f"Reference should have venue: {ref}")


if __name__ == '__main__':
    unittest.main()