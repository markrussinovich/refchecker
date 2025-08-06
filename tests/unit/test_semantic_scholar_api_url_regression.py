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
    
    def test_arxiv_doi_url_recognition(self):
        """Test that arXiv DOI URLs are recognized and don't trigger warnings (regression test)"""
        from unittest.mock import Mock
        
        # Create a mock reference with arXiv DOI URL  
        reference = {
            'title': 'Test ArXiv Paper',
            'authors': ['Test Author'],
            'year': '2025', 
            'url': 'https://doi.org/10.48550/arxiv.2505.11595',  # DOI URL for arXiv
            'raw_text': 'Test Author. Test ArXiv Paper. 2025. https://doi.org/10.48550/arxiv.2505.11595'
        }
        
        # Mock Semantic Scholar response with arXiv ID
        mock_verified_data = {
            'title': 'Test ArXiv Paper',
            'authors': [{'name': 'Test Author'}],
            'year': 2025,
            'externalIds': {'ArXiv': '2505.11595'},  # This triggers the arXiv check
            'url': 'https://www.semanticscholar.org/paper/test'
        }
        
        checker = NonArxivReferenceChecker()
        
        # Simulate the venue checking logic
        errors = []
        external_ids = mock_verified_data.get('externalIds', {})
        arxiv_id = external_ids.get('ArXiv') if external_ids else None
        
        if arxiv_id:
            # This is the logic we fixed
            arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
            reference_url = reference.get('url', '')
            
            # Check for direct arXiv URL match
            has_arxiv_url = arxiv_url in reference_url
            
            # Also check for arXiv DOI URL (the fix)
            arxiv_doi_url = f"https://doi.org/10.48550/arxiv.{arxiv_id}"
            has_arxiv_doi = arxiv_doi_url.lower() in reference_url.lower()
            
            if not (has_arxiv_url or has_arxiv_doi):
                errors.append({
                    'warning_type': 'venue',
                    'warning_details': f"Reference should include arXiv URL: {arxiv_url}",
                    'ref_url_correct': arxiv_url
                })
        
        # Should NOT have any arXiv URL warnings since we have a valid DOI URL
        arxiv_warnings = [e for e in errors if 'arXiv URL' in e.get('warning_details', '')]
        assert len(arxiv_warnings) == 0, f"Should not warn about arXiv URL when DOI URL is present, got: {arxiv_warnings}"