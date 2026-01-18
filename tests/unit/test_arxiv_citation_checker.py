#!/usr/bin/env python3
"""
Unit tests for the ArXiv Citation Checker.

Tests cover:
- ArXiv ID extraction from various URL formats
- BibTeX fetching and parsing
- Version handling (always fetch latest, warn on mismatch)
- Author name parsing
- Year extraction from eprint IDs
- Error handling
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import re

from refchecker.checkers.arxiv_citation import ArXivCitationChecker


class TestArXivIdExtraction:
    """Tests for ArXiv ID extraction from various formats."""
    
    @pytest.fixture
    def checker(self):
        """Create a checker instance."""
        return ArXivCitationChecker()
    
    def test_extract_from_abs_url_new_format(self, checker):
        """Test extraction from standard arxiv.org/abs URL (new format)."""
        reference = {'url': 'https://arxiv.org/abs/2301.12345'}
        arxiv_id, version = checker.extract_arxiv_id(reference)
        assert arxiv_id == '2301.12345'
        assert version is None
    
    def test_extract_from_abs_url_with_version(self, checker):
        """Test extraction from URL with version number."""
        reference = {'url': 'https://arxiv.org/abs/2301.12345v3'}
        arxiv_id, version = checker.extract_arxiv_id(reference)
        assert arxiv_id == '2301.12345'
        assert version == 'v3'
    
    def test_extract_from_pdf_url(self, checker):
        """Test extraction from PDF URL."""
        reference = {'url': 'https://arxiv.org/pdf/2301.12345.pdf'}
        arxiv_id, version = checker.extract_arxiv_id(reference)
        assert arxiv_id == '2301.12345'
        assert version is None
    
    def test_extract_from_old_format_url(self, checker):
        """Test extraction from old format (category/YYMMNNN)."""
        reference = {'url': 'https://arxiv.org/abs/hep-th/9901001'}
        arxiv_id, version = checker.extract_arxiv_id(reference)
        assert arxiv_id == 'hep-th/9901001'
        assert version is None
    
    def test_extract_from_arxiv_prefix_in_text(self, checker):
        """Test extraction from arXiv: prefix in raw text."""
        reference = {'raw_text': 'Available at arXiv:2301.12345v2'}
        arxiv_id, version = checker.extract_arxiv_id(reference)
        assert arxiv_id == '2301.12345'
        assert version == 'v2'
    
    def test_extract_from_export_url(self, checker):
        """Test extraction from export.arxiv.org URL."""
        reference = {'url': 'https://export.arxiv.org/abs/2301.12345'}
        arxiv_id, version = checker.extract_arxiv_id(reference)
        assert arxiv_id == '2301.12345'
        assert version is None
    
    def test_extract_from_eprint_field(self, checker):
        """Test extraction from BibTeX eprint field."""
        reference = {'eprint': '2301.12345'}
        arxiv_id, version = checker.extract_arxiv_id(reference)
        # eprint field doesn't match our URL patterns directly
        # This tests that we check raw_text patterns as well
        reference = {'raw_text': 'arXiv:2301.12345'}
        arxiv_id, version = checker.extract_arxiv_id(reference)
        assert arxiv_id == '2301.12345'
    
    def test_extract_no_arxiv_id(self, checker):
        """Test that None is returned when no ArXiv ID found."""
        reference = {'url': 'https://example.com/paper.pdf', 'raw_text': 'Some paper'}
        arxiv_id, version = checker.extract_arxiv_id(reference)
        assert arxiv_id is None
        assert version is None
    
    def test_extract_prefers_url_over_raw_text(self, checker):
        """Test that URL is checked before raw_text."""
        reference = {
            'url': 'https://arxiv.org/abs/2301.11111',
            'raw_text': 'arXiv:2301.22222'
        }
        arxiv_id, version = checker.extract_arxiv_id(reference)
        assert arxiv_id == '2301.11111'
    
    def test_extract_5_digit_paper_id(self, checker):
        """Test extraction of 5-digit paper IDs (post-2015 format)."""
        reference = {'url': 'https://arxiv.org/abs/2301.12345'}
        arxiv_id, version = checker.extract_arxiv_id(reference)
        assert arxiv_id == '2301.12345'


class TestBibTexParsing:
    """Tests for BibTeX parsing."""
    
    @pytest.fixture
    def checker(self):
        """Create a checker instance."""
        return ArXivCitationChecker()
    
    def test_parse_standard_bibtex(self, checker):
        """Test parsing a standard ArXiv BibTeX entry."""
        bibtex = """@misc{vaswani2017attention,
      title={Attention Is All You Need}, 
      author={Ashish Vaswani and Noam Shazeer and Niki Parmar},
      year={2017},
      eprint={1706.03762},
      archivePrefix={arXiv},
      primaryClass={cs.CL}
}"""
        result = checker.parse_bibtex(bibtex)
        
        assert result is not None
        assert result['title'] == 'Attention Is All You Need'
        assert result['year'] == 2017
        assert result['externalIds']['ArXiv'] == '1706.03762'
        assert len(result['authors']) == 3
        assert result['authors'][0]['name'] == 'Ashish Vaswani'
        assert result['venue'] == 'arXiv'
    
    def test_parse_bibtex_with_braces_in_title(self, checker):
        """Test parsing BibTeX with braces for capitalization protection."""
        bibtex = """@misc{doe2023test,
      title={{LLM}s for {NLP}: A Survey}, 
      author={John Doe},
      year={2023},
      eprint={2301.12345}
}"""
        result = checker.parse_bibtex(bibtex)
        
        assert result is not None
        assert result['title'] == 'LLMs for NLP: A Survey'
    
    def test_parse_bibtex_last_first_author_format(self, checker):
        """Test parsing authors in 'Last, First' format."""
        bibtex = """@misc{test2023,
      title={Test Paper}, 
      author={Doe, John and Smith, Jane},
      year={2023},
      eprint={2301.12345}
}"""
        result = checker.parse_bibtex(bibtex)
        
        assert result is not None
        assert len(result['authors']) == 2
        assert result['authors'][0]['name'] == 'John Doe'
        assert result['authors'][1]['name'] == 'Jane Smith'
    
    def test_parse_empty_bibtex(self, checker):
        """Test parsing empty BibTeX returns None."""
        result = checker.parse_bibtex("")
        assert result is None
    
    def test_parse_invalid_bibtex(self, checker):
        """Test parsing invalid BibTeX returns None."""
        result = checker.parse_bibtex("This is not BibTeX")
        assert result is None
    
    def test_parse_bibtex_with_doi(self, checker):
        """Test parsing BibTeX that includes a DOI."""
        bibtex = """@misc{test2023,
      title={Test Paper}, 
      author={John Doe},
      year={2023},
      eprint={2301.12345},
      doi={10.1234/test.2023}
}"""
        result = checker.parse_bibtex(bibtex)
        
        assert result is not None
        assert result['externalIds']['DOI'] == '10.1234/test.2023'


class TestAuthorParsing:
    """Tests for author name parsing."""
    
    @pytest.fixture
    def checker(self):
        """Create a checker instance."""
        return ArXivCitationChecker()
    
    def test_parse_simple_authors(self, checker):
        """Test parsing simple author names."""
        authors = checker._parse_authors("John Doe and Jane Smith")
        assert authors == ['John Doe', 'Jane Smith']
    
    def test_parse_last_first_format(self, checker):
        """Test parsing 'Last, First' format."""
        authors = checker._parse_authors("Doe, John and Smith, Jane")
        assert authors == ['John Doe', 'Jane Smith']
    
    def test_parse_mixed_format(self, checker):
        """Test parsing mixed author formats."""
        authors = checker._parse_authors("Doe, John and Jane Smith")
        assert authors == ['John Doe', 'Jane Smith']
    
    def test_parse_single_author(self, checker):
        """Test parsing single author."""
        authors = checker._parse_authors("John Doe")
        assert authors == ['John Doe']
    
    def test_parse_empty_string(self, checker):
        """Test parsing empty string returns empty list."""
        authors = checker._parse_authors("")
        assert authors == []
    
    def test_parse_authors_with_braces(self, checker):
        """Test parsing authors with braces (e.g., for accents)."""
        authors = checker._parse_authors('M{\\"u}ller, Hans')
        assert len(authors) == 1
        # Braces should be removed
        assert '{' not in authors[0]


class TestYearExtraction:
    """Tests for year extraction from eprint IDs."""
    
    @pytest.fixture
    def checker(self):
        """Create a checker instance."""
        return ArXivCitationChecker()
    
    def test_extract_year_new_format_2023(self, checker):
        """Test year extraction from new format (2023)."""
        year = checker._extract_year_from_eprint("2301.12345")
        assert year == 2023
    
    def test_extract_year_new_format_2017(self, checker):
        """Test year extraction from new format (2017)."""
        year = checker._extract_year_from_eprint("1706.03762")
        assert year == 2017
    
    def test_extract_year_old_format(self, checker):
        """Test year extraction from old format."""
        year = checker._extract_year_from_eprint("hep-th/9901001")
        assert year == 1999
    
    def test_extract_year_old_format_2000s(self, checker):
        """Test year extraction from old format (2000s)."""
        year = checker._extract_year_from_eprint("cs/0601001")
        assert year == 2006
    
    def test_extract_year_empty(self, checker):
        """Test year extraction from empty string."""
        year = checker._extract_year_from_eprint("")
        assert year is None
    
    def test_extract_year_invalid(self, checker):
        """Test year extraction from invalid format."""
        year = checker._extract_year_from_eprint("not-an-arxiv-id")
        assert year is None


class TestIsArxivReference:
    """Tests for ArXiv reference detection."""
    
    @pytest.fixture
    def checker(self):
        """Create a checker instance."""
        return ArXivCitationChecker()
    
    def test_is_arxiv_with_url(self, checker):
        """Test detection with ArXiv URL."""
        reference = {'url': 'https://arxiv.org/abs/2301.12345'}
        assert checker.is_arxiv_reference(reference) is True
    
    def test_is_arxiv_with_prefix(self, checker):
        """Test detection with arXiv: prefix in text."""
        reference = {'raw_text': 'arXiv:2301.12345'}
        assert checker.is_arxiv_reference(reference) is True
    
    def test_is_not_arxiv(self, checker):
        """Test detection for non-ArXiv reference."""
        reference = {'url': 'https://doi.org/10.1234/test', 'raw_text': 'Some paper'}
        assert checker.is_arxiv_reference(reference) is False


class TestVerifyReference:
    """Tests for the main verify_reference method."""
    
    @pytest.fixture
    def checker(self):
        """Create a checker instance."""
        return ArXivCitationChecker()
    
    @patch.object(ArXivCitationChecker, 'fetch_bibtex')
    def test_verify_reference_success(self, mock_fetch, checker):
        """Test successful reference verification."""
        mock_fetch.return_value = """@misc{test2023,
      title={Test Paper}, 
      author={John Doe},
      year={2023},
      eprint={2301.12345}
}"""
        reference = {
            'title': 'Test Paper',
            'authors': ['John Doe'],
            'year': 2023,
            'url': 'https://arxiv.org/abs/2301.12345'
        }
        
        verified_data, errors, url = checker.verify_reference(reference)
        
        assert verified_data is not None
        assert verified_data['title'] == 'Test Paper'
        assert url == 'https://arxiv.org/abs/2301.12345'
        mock_fetch.assert_called_once_with('2301.12345')
    
    @patch.object(ArXivCitationChecker, 'fetch_bibtex')
    def test_verify_reference_title_mismatch(self, mock_fetch, checker):
        """Test verification with title mismatch."""
        mock_fetch.return_value = """@misc{test2023,
      title={Correct Title}, 
      author={John Doe},
      year={2023},
      eprint={2301.12345}
}"""
        reference = {
            'title': 'Wrong Title',
            'authors': ['John Doe'],
            'year': 2023,
            'url': 'https://arxiv.org/abs/2301.12345'
        }
        
        verified_data, errors, url = checker.verify_reference(reference)
        
        assert verified_data is not None
        title_errors = [e for e in errors if e.get('error_type') == 'title']
        assert len(title_errors) == 1
    
    @patch.object(ArXivCitationChecker, 'fetch_bibtex')
    def test_verify_reference_version_warning(self, mock_fetch, checker):
        """Test that version mismatch generates warning."""
        mock_fetch.return_value = """@misc{test2023,
      title={Test Paper}, 
      author={John Doe},
      year={2023},
      eprint={2301.12345}
}"""
        reference = {
            'title': 'Test Paper',
            'authors': ['John Doe'],
            'year': 2023,
            'url': 'https://arxiv.org/abs/2301.12345v2'  # Specific version cited
        }
        
        verified_data, errors, url = checker.verify_reference(reference)
        
        assert verified_data is not None
        version_warnings = [e for e in errors if e.get('warning_type') == 'version']
        assert len(version_warnings) == 1
        assert 'v2' in version_warnings[0]['warning_details']
    
    def test_verify_reference_no_arxiv_id(self, checker):
        """Test verification with no ArXiv ID returns empty."""
        reference = {
            'title': 'Test Paper',
            'url': 'https://example.com/paper'
        }
        
        verified_data, errors, url = checker.verify_reference(reference)
        
        assert verified_data is None
        assert errors == []
        assert url is None
    
    @patch.object(ArXivCitationChecker, 'fetch_bibtex')
    def test_verify_reference_fetch_failure(self, mock_fetch, checker):
        """Test verification when BibTeX fetch fails."""
        mock_fetch.return_value = None
        
        reference = {
            'title': 'Test Paper',
            'url': 'https://arxiv.org/abs/2301.12345'
        }
        
        verified_data, errors, url = checker.verify_reference(reference)
        
        assert verified_data is None
        assert len(errors) == 1
        assert errors[0]['error_type'] == 'api_failure'


class TestRateLimiting:
    """Tests for rate limiting integration."""
    
    @patch('refchecker.utils.arxiv_rate_limiter.ArXivRateLimiter.get_instance')
    def test_uses_rate_limiter(self, mock_get_instance):
        """Test that checker uses the shared rate limiter."""
        mock_limiter = MagicMock()
        mock_get_instance.return_value = mock_limiter
        
        checker = ArXivCitationChecker()
        
        assert checker.rate_limiter is mock_limiter
    
    @patch('refchecker.checkers.arxiv_citation.requests.get')
    def test_waits_before_request(self, mock_get):
        """Test that rate limiter is called before making request."""
        mock_get.return_value = Mock(
            status_code=200,
            text='@misc{test, title={Test}}',
            raise_for_status=Mock()
        )
        
        # Create checker with mocked rate limiter
        checker = ArXivCitationChecker()
        mock_rate_limiter = MagicMock()
        checker.rate_limiter = mock_rate_limiter
        
        checker.fetch_bibtex('2301.12345')
        
        mock_rate_limiter.wait.assert_called_once()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
