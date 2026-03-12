"""Unit tests for the web search checker (provider-agnostic)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.checkers.web_search import (
    DELTA_INCONCLUSIVE,
    DELTA_MODERATE_HIT,
    DELTA_NO_RESULTS,
    DELTA_STRONG_HIT,
    GeminiSearchProvider,
    OpenAISearchProvider,
    WebSearchChecker,
    WebSearchProvider,
    create_web_search_checker,
    is_academic_url,
    _extract_academic_urls_from_results,
)


# ------------------------------------------------------------------
# Helper-function tests
# ------------------------------------------------------------------

class TestHelpers:

    def test_is_academic_url_arxiv(self):
        assert is_academic_url('https://arxiv.org/abs/2301.00001')

    def test_is_academic_url_with_www_prefix(self):
        assert is_academic_url('https://www.nature.com/articles/s41586-024-0001')

    def test_is_academic_url_subdomain(self):
        assert is_academic_url('https://link.springer.com/chapter/10.1007/123')

    def test_is_academic_url_non_academic(self):
        assert not is_academic_url('https://medium.com/some-blog-post')

    def test_is_academic_url_empty(self):
        assert not is_academic_url('')

    def test_extract_academic_urls_filters_correctly(self):
        results = [
            {'link': 'https://arxiv.org/abs/1706.03762', 'title': 'A', 'snippet': ''},
            {'link': 'https://medium.com/transformers', 'title': 'B', 'snippet': ''},
            {'link': 'https://semanticscholar.org/paper/123', 'title': 'C', 'snippet': ''},
        ]
        urls = _extract_academic_urls_from_results(results)
        assert len(urls) == 2
        assert 'arxiv.org' in urls[0]
        assert 'semanticscholar.org' in urls[1]

    def test_extract_academic_urls_empty(self):
        assert _extract_academic_urls_from_results([]) == []


# ------------------------------------------------------------------
# Provider subclass checks
# ------------------------------------------------------------------

class TestProviderInterface:

    def test_openai_is_subclass(self):
        assert issubclass(OpenAISearchProvider, WebSearchProvider)

    def test_gemini_is_subclass(self):
        assert issubclass(GeminiSearchProvider, WebSearchProvider)

    def test_openai_provider_name(self):
        assert OpenAISearchProvider.name == 'openai'

    def test_gemini_provider_name(self):
        assert GeminiSearchProvider.name == 'gemini'

    def test_openai_available_with_key(self, _clean_env):
        """OpenAI provider should be available when a key is set and openai is installed."""
        os.environ['OPENAI_API_KEY'] = 'test-key'
        p = OpenAISearchProvider()
        assert p.available

    def test_gemini_not_available_without_key(self, _clean_env):
        p = GeminiSearchProvider()
        assert not p.available


# ------------------------------------------------------------------
# Stub provider for checker-level tests
# ------------------------------------------------------------------

class StubProvider(WebSearchProvider):
    """In-memory provider returning canned results."""

    name = 'stub'

    def __init__(self, results=None, error=None):
        self._results = results or []
        self._error = error

    @property
    def available(self) -> bool:
        return True

    def search(self, query: str, num_results: int = 10):
        if self._error:
            raise self._error
        return self._results


# ------------------------------------------------------------------
# WebSearchChecker logic tests (provider-agnostic)
# ------------------------------------------------------------------

class TestWebSearchCheckerLogic:

    def test_strong_hit_reduces_score(self):
        provider = StubProvider(results=[
            {'link': 'https://arxiv.org/abs/1706.03762', 'title': 'A', 'snippet': ''},
            {'link': 'https://semanticscholar.org/paper/x', 'title': 'B', 'snippet': ''},
        ])
        checker = WebSearchChecker(provider)
        result = checker.check_reference_exists({
            'ref_title': 'Attention Is All You Need',
            'ref_authors_cited': 'Ashish Vaswani',
        })
        assert result['found'] is True
        assert result['score_delta'] == DELTA_STRONG_HIT
        assert len(result['academic_urls']) == 2
        assert result['provider'] == 'stub'

    def test_single_academic_hit_moderate_reduction(self):
        provider = StubProvider(results=[
            {'link': 'https://arxiv.org/abs/1706.03762', 'title': 'A', 'snippet': ''},
            {'link': 'https://medium.com/blog', 'title': 'B', 'snippet': ''},
        ])
        checker = WebSearchChecker(provider)
        result = checker.check_reference_exists({
            'ref_title': 'Some Paper',
            'ref_authors_cited': 'Author',
        })
        assert result['found'] is True
        assert result['score_delta'] == DELTA_MODERATE_HIT

    def test_no_results_boosts_score(self):
        checker = WebSearchChecker(StubProvider(results=[]))
        result = checker.check_reference_exists({
            'ref_title': 'Totally Fabricated Paper',
            'ref_authors_cited': 'Fake Author',
        })
        assert result['found'] is False
        assert result['score_delta'] == DELTA_NO_RESULTS

    def test_non_academic_results_inconclusive(self):
        provider = StubProvider(results=[
            {'link': 'https://reddit.com/r/ml/post', 'title': 'D', 'snippet': ''},
        ])
        checker = WebSearchChecker(provider)
        result = checker.check_reference_exists({
            'ref_title': 'Ambiguous Paper',
            'ref_authors_cited': 'Someone',
        })
        assert result['found'] is False
        assert result['score_delta'] == DELTA_INCONCLUSIVE

    def test_api_error_returns_zero_delta(self):
        provider = StubProvider(error=ConnectionError('boom'))
        checker = WebSearchChecker(provider)
        result = checker.check_reference_exists({
            'ref_title': 'Paper',
            'ref_authors_cited': 'Author',
        })
        assert result['score_delta'] == 0.0
        assert result['found'] is False

    def test_empty_title_returns_zero_delta(self):
        checker = WebSearchChecker(StubProvider())
        result = checker.check_reference_exists({'ref_title': '', 'ref_authors_cited': ''})
        assert result['score_delta'] == 0.0

    def test_checker_not_available_without_provider(self):
        checker = WebSearchChecker(None)
        assert not checker.available


# ------------------------------------------------------------------
# Factory tests
# ------------------------------------------------------------------

class TestFactory:

    def test_factory_returns_openai_when_key_set(self, _clean_env):
        os.environ['OPENAI_API_KEY'] = 'test-openai-key'
        checker = create_web_search_checker()
        assert checker.available
        assert checker._provider_name == 'openai'

    def test_factory_prefers_openai_over_gemini(self, _clean_env):
        os.environ['OPENAI_API_KEY'] = 'openai-key'
        os.environ['GOOGLE_API_KEY'] = 'google-key'
        checker = create_web_search_checker()
        assert checker._provider_name == 'openai'

    def test_factory_preferred_provider_override(self, _clean_env, monkeypatch):
        os.environ['OPENAI_API_KEY'] = 'openai-key'
        os.environ['GOOGLE_API_KEY'] = 'google-key'
        # Gemini provider needs google.generativeai — mock to make it available
        import types
        fake_genai = types.ModuleType('google.generativeai')
        fake_genai.configure = lambda **kw: None
        fake_genai.GenerativeModel = lambda *a, **kw: object()
        monkeypatch.setitem(sys.modules, 'google.generativeai', fake_genai)
        checker = create_web_search_checker(preferred_provider='gemini')
        assert checker._provider_name == 'gemini'

    def test_factory_no_keys_returns_unavailable(self, _clean_env):
        checker = create_web_search_checker()
        assert not checker.available


# ------------------------------------------------------------------
# ReportBuilder integration
# ------------------------------------------------------------------

class TestReportBuilderWebSearch:

    def test_web_search_can_unflag_candidate(self):
        from refchecker.core.report_builder import ReportBuilder

        provider = StubProvider(results=[
            {'link': 'https://arxiv.org/abs/1234.5678', 'title': 'X', 'snippet': ''},
            {'link': 'https://semanticscholar.org/paper/y', 'title': 'Y', 'snippet': ''},
        ])
        builder = ReportBuilder(
            scan_mode='hallucination',
            only_flagged=False,
            web_searcher=WebSearchChecker(provider),
        )

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
        if 'web_search_found' in assessment.get('reasons', []):
            assert assessment['score'] < 0.65

    def test_web_search_not_found_boosts_score(self):
        from refchecker.core.report_builder import ReportBuilder

        provider = StubProvider(results=[])
        builder = ReportBuilder(
            scan_mode='hallucination',
            only_flagged=False,
            web_searcher=WebSearchChecker(provider),
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


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture()
def _clean_env():
    """Temporarily remove web-search-related env vars to isolate tests."""
    keys = ('OPENAI_API_KEY', 'REFCHECKER_OPENAI_API_KEY', 'OPENAI_CHAT_KEY',
            'GOOGLE_API_KEY', 'REFCHECKER_GOOGLE_API_KEY',
            'SERPER_API_KEY', 'REFCHECKER_SERPER_API_KEY',
            'BRAVE_SEARCH_API_KEY', 'REFCHECKER_BRAVE_SEARCH_API_KEY')
    saved = {k: os.environ.pop(k) for k in keys if k in os.environ}
    yield
    for k, v in saved.items():
        os.environ[k] = v
