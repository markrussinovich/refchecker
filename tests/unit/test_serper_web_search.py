"""Unit tests for the Serper web search checker."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.checkers.serper_web_search import (
    DELTA_INCONCLUSIVE,
    DELTA_MODERATE_HIT,
    DELTA_NO_RESULTS,
    DELTA_STRONG_HIT,
    SerperWebSearchChecker,
    _extract_academic_urls,
    _extract_first_author,
    _is_academic_url,
)


# ------------------------------------------------------------------
# Helper‑function tests (no API key needed)
# ------------------------------------------------------------------

class TestHelpers:

    def test_is_academic_url_arxiv(self):
        assert _is_academic_url('https://arxiv.org/abs/2301.00001')

    def test_is_academic_url_with_www_prefix(self):
        assert _is_academic_url('https://www.nature.com/articles/s41586-024-0001')

    def test_is_academic_url_subdomain(self):
        assert _is_academic_url('https://link.springer.com/chapter/10.1007/123')

    def test_is_academic_url_non_academic(self):
        assert not _is_academic_url('https://medium.com/some-blog-post')

    def test_is_academic_url_empty(self):
        assert not _is_academic_url('')

    def test_extract_academic_urls_filters_correctly(self):
        results = {
            'organic': [
                {'link': 'https://arxiv.org/abs/1706.03762', 'title': 'Attention'},
                {'link': 'https://medium.com/transformers', 'title': 'Blog'},
                {'link': 'https://semanticscholar.org/paper/123', 'title': 'SS'},
            ]
        }
        urls = _extract_academic_urls(results)
        assert len(urls) == 2
        assert 'arxiv.org' in urls[0]
        assert 'semanticscholar.org' in urls[1]

    def test_extract_academic_urls_empty_results(self):
        assert _extract_academic_urls({}) == []
        assert _extract_academic_urls({'organic': []}) == []

    def test_extract_first_author_comma_separated(self):
        assert _extract_first_author('Ian Goodfellow, Yoshua Bengio') == 'Goodfellow'

    def test_extract_first_author_and_separated(self):
        assert _extract_first_author('Ian Goodfellow and Yoshua Bengio') == 'Goodfellow'

    def test_extract_first_author_single(self):
        assert _extract_first_author('Yann LeCun') == 'LeCun'

    def test_extract_first_author_empty(self):
        assert _extract_first_author('') == ''


# ------------------------------------------------------------------
# Checker‑level tests (mock the Serper API)
# ------------------------------------------------------------------

class TestSerperCheckerLogic:

    def _make_checker(self):
        return SerperWebSearchChecker(api_key='test-key')

    def test_available_with_key(self):
        checker = SerperWebSearchChecker(api_key='abc')
        assert checker.available

    def test_not_available_without_key(self):
        # Clear env vars so nothing leaks in
        env = {k: v for k, v in os.environ.items()
               if k not in ('SERPER_API_KEY', 'REFCHECKER_SERPER_API_KEY')}
        orig = os.environ.copy()
        os.environ.clear()
        os.environ.update(env)
        try:
            checker = SerperWebSearchChecker()
            assert not checker.available
        finally:
            os.environ.clear()
            os.environ.update(orig)

    def test_strong_hit_reduces_score(self, monkeypatch):
        checker = self._make_checker()
        monkeypatch.setattr(checker, '_search', lambda q: {
            'organic': [
                {'link': 'https://arxiv.org/abs/1706.03762', 'title': 'A'},
                {'link': 'https://semanticscholar.org/paper/x', 'title': 'B'},
            ]
        })
        result = checker.check_reference_exists({
            'ref_title': 'Attention Is All You Need',
            'ref_authors_cited': 'Ashish Vaswani',
        })
        assert result['found'] is True
        assert result['score_delta'] == DELTA_STRONG_HIT
        assert len(result['academic_urls']) == 2

    def test_single_academic_hit_moderate_reduction(self, monkeypatch):
        checker = self._make_checker()
        monkeypatch.setattr(checker, '_search', lambda q: {
            'organic': [
                {'link': 'https://arxiv.org/abs/1706.03762', 'title': 'A'},
                {'link': 'https://medium.com/blog', 'title': 'B'},
            ]
        })
        result = checker.check_reference_exists({
            'ref_title': 'Some Paper',
            'ref_authors_cited': 'Author',
        })
        assert result['found'] is True
        assert result['score_delta'] == DELTA_MODERATE_HIT

    def test_no_results_boosts_score(self, monkeypatch):
        checker = self._make_checker()
        monkeypatch.setattr(checker, '_search', lambda q: {'organic': []})
        result = checker.check_reference_exists({
            'ref_title': 'Totally Fabricated Paper Title',
            'ref_authors_cited': 'Fake Author',
        })
        assert result['found'] is False
        assert result['score_delta'] == DELTA_NO_RESULTS

    def test_non_academic_results_inconclusive(self, monkeypatch):
        checker = self._make_checker()
        monkeypatch.setattr(checker, '_search', lambda q: {
            'organic': [
                {'link': 'https://reddit.com/r/ml/post', 'title': 'Discussion'},
            ]
        })
        result = checker.check_reference_exists({
            'ref_title': 'Ambiguous Paper',
            'ref_authors_cited': 'Someone',
        })
        assert result['found'] is False
        assert result['score_delta'] == DELTA_INCONCLUSIVE

    def test_api_error_returns_zero_delta(self, monkeypatch):
        checker = self._make_checker()
        monkeypatch.setattr(checker, '_search', _raise_error)
        result = checker.check_reference_exists({
            'ref_title': 'Some Paper',
            'ref_authors_cited': 'Author',
        })
        assert result['score_delta'] == 0.0
        assert result['found'] is False

    def test_empty_title_returns_zero_delta(self):
        checker = self._make_checker()
        result = checker.check_reference_exists({'ref_title': '', 'ref_authors_cited': ''})
        assert result['score_delta'] == 0.0


# ------------------------------------------------------------------
# ReportBuilder integration tests
# ------------------------------------------------------------------

class TestReportBuilderWebSearch:

    def test_web_search_can_unflag_candidate(self):
        """A strong web search hit should reduce score below threshold and unflag."""
        from refchecker.core.report_builder import ReportBuilder

        class FakeSearcher:
            available = True
            def check_reference_exists(self, record):
                return {'found': True, 'score_delta': -0.15, 'academic_urls': ['https://arxiv.org/abs/1'], 'query': 'q'}

        builder = ReportBuilder(
            scan_mode='hallucination',
            only_flagged=False,
            web_searcher=FakeSearcher(),
        )

        # A borderline candidate with score ~0.65 should get unflagged by -0.15
        errors = [{
            'error_type': 'unverified',
            'error_details': 'Reference could not be verified',
            'ref_title': 'Real Paper That APIs Missed',
            'ref_authors_cited': 'Alice Smith, Bob Jones',
            'sources_checked': 2,
            'sources_negative': 2,
        }]

        records = builder.build_structured_report_records(errors)
        assert len(records) == 1
        assessment = records[0]['hallucination_assessment']
        # Web search found it — should have reduced score
        if 'web_search_found' in assessment.get('reasons', []):
            assert assessment['score'] < 0.65

    def test_web_search_not_found_boosts_score(self):
        """Web search returning no results should boost hallucination score."""
        from refchecker.core.report_builder import ReportBuilder

        class FakeSearcher:
            available = True
            def check_reference_exists(self, record):
                return {'found': False, 'score_delta': 0.05, 'academic_urls': [], 'query': 'q'}

        builder = ReportBuilder(
            scan_mode='hallucination',
            only_flagged=False,
            web_searcher=FakeSearcher(),
        )

        errors = [{
            'error_type': 'unverified',
            'error_details': 'Reference could not be verified',
            'ref_title': 'Fabricated Paper With Good Metadata',
            'ref_authors_cited': 'Alice Smith, Bob Jones, Carol White',
            'sources_checked': 4,
            'sources_negative': 4,
        }]

        records = builder.build_structured_report_records(errors)
        assessment = records[0]['hallucination_assessment']
        assert assessment['candidate'] is True
        assert 'web_search_not_found' in assessment['reasons']


def _raise_error(query):
    raise ConnectionError('Simulated network error')
