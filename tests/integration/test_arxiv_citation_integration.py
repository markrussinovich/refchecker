#!/usr/bin/env python3
"""
Integration tests for the ArXiv Citation Checker.

These tests make real API calls to ArXiv to verify the integration works correctly.
They are marked as integration tests and can be skipped in unit test runs.

Run with: pytest tests/integration/test_arxiv_citation_integration.py -v
"""

import pytest
import time

from refchecker.checkers.arxiv_citation import ArXivCitationChecker


# Skip all tests in this module if running quick tests
pytestmark = pytest.mark.integration


class TestArXivCitationIntegration:
    """Integration tests for ArXiv Citation Checker with real API calls."""
    
    @pytest.fixture
    def checker(self):
        """Create a checker instance."""
        return ArXivCitationChecker()
    
    def test_fetch_real_bibtex_attention_paper(self, checker):
        """Test fetching BibTeX for 'Attention Is All You Need' paper."""
        bibtex = checker.fetch_bibtex('1706.03762')
        
        assert bibtex is not None
        assert '@' in bibtex
        assert 'Attention' in bibtex or 'attention' in bibtex
        assert 'Vaswani' in bibtex
    
    def test_fetch_real_bibtex_recent_paper(self, checker):
        """Test fetching BibTeX for a recent paper."""
        # Use a well-known recent paper
        bibtex = checker.fetch_bibtex('2303.08774')  # GPT-4 paper
        
        assert bibtex is not None
        assert '@' in bibtex
    
    def test_fetch_nonexistent_paper(self, checker):
        """Test fetching BibTeX for a non-existent paper ID."""
        # Use an invalid ID that shouldn't exist
        bibtex = checker.fetch_bibtex('9999.99999')
        
        # ArXiv might return empty or error page
        # The important thing is we handle it gracefully
        # Either None or invalid content (not starting with @)
        if bibtex is not None:
            # If we got something, it shouldn't be valid BibTeX
            assert not bibtex.strip().startswith('@') or 'error' in bibtex.lower()
    
    def test_verify_reference_attention_paper(self, checker):
        """Test full verification of the Attention paper."""
        reference = {
            'title': 'Attention Is All You Need',
            'authors': ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar'],
            'year': 2017,
            'url': 'https://arxiv.org/abs/1706.03762'
        }
        
        verified_data, errors, url = checker.verify_reference(reference)
        
        assert verified_data is not None
        assert 'Attention' in verified_data.get('title', '')
        # Note: ArXiv may return different year based on paper revisions
        # The year in ArXiv BibTeX reflects the metadata, not original publication
        assert verified_data.get('year') is not None
        assert verified_data.get('externalIds', {}).get('ArXiv') == '1706.03762'
        assert url == 'https://arxiv.org/abs/1706.03762'
        
        # Authors should be present
        authors = verified_data.get('authors', [])
        assert len(authors) > 0
        author_names = [a.get('name', '') for a in authors]
        assert any('Vaswani' in name for name in author_names)
    
    def test_verify_reference_with_version(self, checker):
        """Test verification of a paper with specific version cited."""
        reference = {
            'title': 'Attention Is All You Need',
            'authors': ['Ashish Vaswani'],
            'year': 2017,
            'url': 'https://arxiv.org/abs/1706.03762v5'  # Specific version
        }
        
        verified_data, errors, url = checker.verify_reference(reference)
        
        assert verified_data is not None
        
        # Should have a version warning
        version_warnings = [e for e in errors if e.get('warning_type') == 'version']
        assert len(version_warnings) == 1
        assert 'v5' in version_warnings[0]['warning_details']
    
    def test_verify_reference_title_mismatch(self, checker):
        """Test detection of title mismatch."""
        reference = {
            'title': 'Completely Wrong Title That Does Not Match',
            'authors': ['Ashish Vaswani'],
            'year': 2017,
            'url': 'https://arxiv.org/abs/1706.03762'
        }
        
        verified_data, errors, url = checker.verify_reference(reference)
        
        assert verified_data is not None
        
        # Should detect title mismatch
        title_errors = [e for e in errors if e.get('error_type') == 'title']
        assert len(title_errors) == 1
    
    def test_verify_reference_author_mismatch(self, checker):
        """Test detection of author mismatch."""
        reference = {
            'title': 'Attention Is All You Need',
            'authors': ['John Doe', 'Jane Smith'],  # Wrong authors
            'year': 2017,
            'url': 'https://arxiv.org/abs/1706.03762'
        }
        
        verified_data, errors, url = checker.verify_reference(reference)
        
        assert verified_data is not None
        
        # Should detect author mismatch
        author_errors = [e for e in errors if e.get('error_type') == 'author']
        assert len(author_errors) == 1
    
    def test_verify_non_arxiv_reference(self, checker):
        """Test that non-ArXiv references are handled correctly."""
        reference = {
            'title': 'Some Paper',
            'authors': ['John Doe'],
            'year': 2023,
            'url': 'https://doi.org/10.1234/test'
        }
        
        verified_data, errors, url = checker.verify_reference(reference)
        
        # Should return None for non-ArXiv references
        assert verified_data is None
        assert errors == []
        assert url is None


class TestArXivRateLimiting:
    """Integration tests for rate limiting behavior."""
    
    def test_rate_limiter_enforces_delay(self):
        """Test that rate limiter enforces delay between requests."""
        from refchecker.utils.arxiv_rate_limiter import ArXivRateLimiter
        
        # Reset the singleton to get a fresh instance
        ArXivRateLimiter.reset_instance()
        limiter = ArXivRateLimiter.get_instance()
        
        # Set a short delay for testing
        limiter.delay = 0.5
        
        # First wait should be immediate (or very quick)
        start = time.time()
        limiter.wait()
        first_wait = time.time() - start
        
        # Second wait should enforce the delay
        start = time.time()
        limiter.wait()
        second_wait = time.time() - start
        
        # Second wait should be close to the delay
        assert second_wait >= 0.4  # Allow some tolerance
        
        # Reset for other tests
        ArXivRateLimiter.reset_instance()
    
    def test_multiple_fetches_respect_rate_limit(self):
        """Test that multiple fetches respect rate limiting."""
        checker = ArXivCitationChecker()
        
        # Set a shorter delay for testing (but still be polite)
        checker.rate_limiter.delay = 1.0
        
        start = time.time()
        
        # Make two requests
        checker.fetch_bibtex('1706.03762')
        checker.fetch_bibtex('2303.08774')
        
        elapsed = time.time() - start
        
        # Should have waited at least ~1 second between requests
        assert elapsed >= 0.9


class TestEnhancedHybridIntegration:
    """Test integration with EnhancedHybridReferenceChecker."""
    
    def test_hybrid_checker_uses_arxiv_citation_first(self):
        """Test that hybrid checker tries ArXiv citation first for ArXiv papers."""
        from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
        
        # Create hybrid checker with ArXiv citation enabled
        checker = EnhancedHybridReferenceChecker(
            enable_arxiv_citation=True,
            enable_openalex=False,  # Disable others to speed up test
            enable_crossref=False,
        )
        
        assert checker.arxiv_citation is not None
        
        reference = {
            'title': 'Attention Is All You Need',
            'authors': ['Ashish Vaswani'],
            'year': 2017,
            'url': 'https://arxiv.org/abs/1706.03762'
        }
        
        verified_data, errors, url = checker.verify_reference(reference)
        
        # Should get data (from ArXiv citation checker or fallback)
        assert verified_data is not None
        
        # Check stats - arxiv_citation should have been tried
        stats = checker.get_performance_stats()
        arxiv_stats = stats.get('arxiv_citation', {})
        assert arxiv_stats.get('total_calls', 0) > 0
    
    def test_hybrid_checker_can_disable_arxiv_citation(self):
        """Test that ArXiv citation checker can be disabled."""
        from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
        
        checker = EnhancedHybridReferenceChecker(
            enable_arxiv_citation=False,
        )
        
        assert checker.arxiv_citation is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
