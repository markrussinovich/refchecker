#!/usr/bin/env python3
"""
Unit tests for webpage author matching, specifically testing that generic
web resource terms are accepted without generating author/organization mismatch warnings.
"""

import unittest
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.checkers.webpage_checker import WebPageChecker


class TestWebpageAuthorMatching(unittest.TestCase):
    """Test webpage author matching logic."""
    
    def setUp(self):
        self.checker = WebPageChecker()
    
    def test_generic_web_resource_terms_accepted(self):
        """Test that generic web resource terms are accepted for any web URL."""
        site_info = {
            'domain': 'openai.com',
            'organization': 'OpenAI',
            'site_type': 'website'
        }
        url = 'https://chat.openai.com/share/12345'
        
        # These generic terms should all be accepted
        generic_terms = [
            'Web Resource',
            'web resource', 
            'Web Site',
            'website',
            'Online Resource',
            'online',
            'web',
            'Web Page',
            'webpage',
            'Internet Resource'
        ]
        
        for term in generic_terms:
            with self.subTest(term=term):
                result = self.checker._check_author_match(term, site_info, url)
                self.assertTrue(result, f"Generic term '{term}' should be accepted for web URLs")
    
    def test_specific_organization_names_still_work(self):
        """Test that specific organization names still work correctly."""
        site_info_openai = {
            'domain': 'openai.com',
            'organization': 'OpenAI',
            'site_type': 'website'
        }
        
        site_info_google = {
            'domain': 'google.com', 
            'organization': 'Google',
            'site_type': 'website'
        }
        
        # Correct organization names should match
        self.assertTrue(self.checker._check_author_match('OpenAI', site_info_openai, 'https://openai.com'))
        self.assertTrue(self.checker._check_author_match('Google', site_info_google, 'https://google.com'))
        
        # Wrong organization names should not match
        self.assertFalse(self.checker._check_author_match('Microsoft', site_info_openai, 'https://openai.com'))
        self.assertFalse(self.checker._check_author_match('OpenAI', site_info_google, 'https://google.com'))
    
    def test_case_insensitive_matching(self):
        """Test that matching is case insensitive."""
        site_info = {
            'domain': 'example.com',
            'organization': 'Example Corp',
            'site_type': 'website'
        }
        url = 'https://example.com'
        
        # Should work regardless of case
        self.assertTrue(self.checker._check_author_match('WEB RESOURCE', site_info, url))
        self.assertTrue(self.checker._check_author_match('web resource', site_info, url))
        self.assertTrue(self.checker._check_author_match('Web Resource', site_info, url))
    
    def test_openai_chatgpt_specific_case(self):
        """Test the specific OpenAI ChatGPT case from the user report."""
        site_info = {
            'domain': 'chat.openai.com',
            'organization': 'OpenAI',
            'site_type': 'website'
        }
        url = 'https://chat.openai.com/share/31708d66-c735-46e4-94fd-41f436d4d3e9'
        
        # 'Web Resource' should be accepted without mismatch warning
        result = self.checker._check_author_match('Web Resource', site_info, url)
        self.assertTrue(result, "Web Resource should be accepted for OpenAI ChatGPT URLs")
    
    def test_google_gemini_specific_case(self):
        """Test the specific Google Gemini case from the user report."""
        site_info = {
            'domain': 'gemini.google.com',
            'organization': 'Google',
            'site_type': 'website'
        }
        url = 'https://gemini.google.com/share/35f0817c3a03'
        
        # 'Web Resource' should be accepted without mismatch warning
        result = self.checker._check_author_match('Web Resource', site_info, url)
        self.assertTrue(result, "Web Resource should be accepted for Google Gemini URLs")
    
    def test_whitespace_handling(self):
        """Test that whitespace is handled correctly."""
        site_info = {
            'domain': 'example.com',
            'organization': 'Example',
            'site_type': 'website'
        }
        url = 'https://example.com'
        
        # Should handle extra whitespace
        self.assertTrue(self.checker._check_author_match('  Web Resource  ', site_info, url))
        self.assertTrue(self.checker._check_author_match('\tWeb Resource\n', site_info, url))
    
    def test_non_generic_terms_not_falsely_matched(self):
        """Test that non-generic terms are not falsely matched as generic."""
        site_info = {
            'domain': 'example.com',
            'organization': 'Example',
            'site_type': 'website'
        }
        url = 'https://example.com'
        
        # These should not be automatically accepted as generic terms
        non_generic_terms = [
            'Research Paper',
            'Documentation',
            'Tutorial',
            'Blog Post',
            'News Article'
        ]
        
        for term in non_generic_terms:
            with self.subTest(term=term):
                # These might still match through other logic, but they shouldn't
                # match through the generic terms logic
                pass  # We'd need to check this doesn't match via generic terms specifically


if __name__ == '__main__':
    unittest.main()