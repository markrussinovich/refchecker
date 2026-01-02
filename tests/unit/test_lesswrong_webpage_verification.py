#!/usr/bin/env python3
"""
Unit tests for LessWrong webpage verification functionality.
"""

import unittest
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.checkers.webpage_checker import WebPageChecker


class TestLessWrongWebpageVerification(unittest.TestCase):
    """Test LessWrong webpage verification functionality."""
    
    def setUp(self):
        self.checker = WebPageChecker()
    
    def test_lesswrong_url_recognition(self):
        """Test that LessWrong URLs are recognized as verifiable web pages."""
        lesswrong_urls = [
            'https://www.lesswrong.com/posts/RYcoJdvmoBbi5Nax7/jailbreaking-chatgpt-on-release-day',
            'https://lesswrong.com/posts/123/some-post',
            'https://www.lesswrong.com/posts/abc/another-post-title'
        ]
        
        for url in lesswrong_urls:
            with self.subTest(url=url):
                result = self.checker.is_web_page_url(url)
                self.assertTrue(result, f"LessWrong URL should be recognized: {url}")
    
    def test_posts_indicator_recognition(self):
        """Test that URLs with 'posts' are recognized as verifiable."""
        post_urls = [
            'https://example.com/posts/123/title',
            'https://medium.com/posts/article',
            'https://blog.example.com/posts/2024/01/post-title'
        ]
        
        for url in post_urls:
            with self.subTest(url=url):
                result = self.checker.is_web_page_url(url)
                self.assertTrue(result, f"URL with 'posts' should be recognized: {url}")
    
    def test_lesswrong_domain_recognition(self):
        """Test that LessWrong domain is in known documentation domains."""
        result = self.checker._is_likely_webpage('https://www.lesswrong.com/anything')
        self.assertTrue(result, "LessWrong domain should be recognized as a known domain")
    
    def test_lesswrong_reference_structure(self):
        """Test typical LessWrong reference structure."""
        reference = {
            'title': 'LessWrong Post: Jailbreaking ChatGPT',
            'authors': ['Web Resource'],
            'url': 'https://www.lesswrong.com/posts/RYcoJdvmoBbi5Nax7/jailbreaking-chatgpt-on-release-day',
            'year': None
        }
        
        # Test URL recognition
        is_webpage = self.checker.is_web_page_url(reference['url'])
        self.assertTrue(is_webpage, "LessWrong reference URL should be recognized as webpage")
        
        # Note: We don't test actual verification here to avoid network dependencies
        # That would require mocking or integration tests


if __name__ == '__main__':
    unittest.main()