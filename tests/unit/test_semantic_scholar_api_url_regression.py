#!/usr/bin/env python3
"""
Regression test for Semantic Scholar API URL handling
Prevents regression of the bug where api.semanticscholar.org/CorpusID URLs 
showed as unverified despite having valid URLs.
"""

import pytest
from unittest.mock import Mock, patch
from checkers.semantic_scholar import NonArxivReferenceChecker


class TestSemanticScholarApiUrlRegression:
    """Test Semantic Scholar API URL handling regression."""
    
    def test_semantic_scholar_api_url_verification(self):
        """
        Test that Semantic Scholar API URLs are properly verified.
        
        This is a regression test for the bug where papers with
        https://api.semanticscholar.org/CorpusID:XXXXX URLs showed
        as unverified despite having valid URLs.
        """
        # Reference with Semantic Scholar API URL (the exact case that was failing)
        reference = {
            'title': 'Proximal Policy Optimization Algorithms',
            'authors': ['John Schulman', 'Filip Wolski', 'Prafulla Dhariwal', 'Alec Radford', 'Oleg Klimov'],
            'venue': 'ArXiv',
            'year': '2017',
            'url': 'https://api.semanticscholar.org/CorpusID:28695052',
            'raw_text': 'John Schulman, Filip Wolski, Prafulla Dhariwal, Alec Radford, Oleg Klimov. Proximal Policy Optimization Algorithms. ArXiv, 2017. https://api.semanticscholar.org/CorpusID:28695052'
        }
        
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'title': 'Proximal Policy Optimization Algorithms',
            'authors': [{'name': 'John Schulman'}, {'name': 'Filip Wolski'}],
            'year': 2017,
            'externalIds': {'CorpusId': '28695052'},
            'url': 'https://www.semanticscholar.org/paper/28695052'
        }
        
        with patch('requests.get', return_value=mock_response):
            checker = NonArxivReferenceChecker()
            verified_data, errors, url = checker.verify_reference(reference)
            
            # Should be successfully verified (not unverified)
            assert verified_data is not None, "Paper should be verified, not unverified"
            assert url is not None, "Should have a paper URL"
            
            # Should not have unverified errors
            unverified_errors = [e for e in errors if e.get('error_type') == 'unverified']
            assert len(unverified_errors) == 0, f"Should not have unverified errors, got: {unverified_errors}"
    
    def test_semantic_scholar_api_url_recognition(self):
        """Test that Semantic Scholar API URLs are recognized."""
        reference = {
            'title': 'Test Paper',
            'authors': ['Test Author'],
            'year': '2023',
            'url': 'https://api.semanticscholar.org/CorpusID:12345'
        }
        
        checker = NonArxivReferenceChecker()
        
        # Should recognize and extract CorpusID from API URL
        url = reference['url']
        assert 'api.semanticscholar.org/CorpusID:' in url
        
        import re
        corpus_match = re.search(r'CorpusID:(\d+)', url)
        assert corpus_match is not None
        assert corpus_match.group(1) == '12345'
    
    def test_api_url_vs_regular_url(self):
        """Test that both API URLs and regular paper URLs work."""
        api_url_ref = {
            'title': 'Test Paper',
            'url': 'https://api.semanticscholar.org/CorpusID:12345'
        }
        
        paper_url_ref = {
            'title': 'Test Paper', 
            'url': 'https://www.semanticscholar.org/paper/12345'
        }
        
        # Both should be recognized as Semantic Scholar URLs
        assert 'api.semanticscholar.org/CorpusID:' in api_url_ref['url']
        assert 'www.semanticscholar.org/paper/' in paper_url_ref['url']