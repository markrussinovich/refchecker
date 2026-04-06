"""Regression tests for hallucination flagging decisions.

Uses representative references from real reports (fixture file) to ensure:
- Verified refs with high author overlap are NOT sent to LLM.
- Fabricated-author refs (0% overlap) get deterministic LIKELY verdict.
- Year-only / venue-only mismatches never trigger hallucination check.
- Unverified refs properly trigger hallucination check.

No LLM calls are made — all assertions use the deterministic path only.
"""

import json
import os
import pytest

from refchecker.core.hallucination_policy import (
    check_author_hallucination,
    run_hallucination_check,
    should_check_hallucination,
)

_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'fixtures', 'hallucination_regression_refs.json'
)


def _load_fixture():
    with open(_FIXTURE_PATH) as f:
        return json.load(f)


_CASES = _load_fixture()
_IDS = [c['id'] for c in _CASES]


@pytest.mark.parametrize('case', _CASES, ids=_IDS)
def test_should_check_hallucination(case):
    """should_check_hallucination returns expected True/False."""
    entry = case['error_entry']
    expected = case['expect_should_check']
    result = should_check_hallucination(entry)
    assert result == expected, (
        f"should_check_hallucination for '{case['id']}': "
        f"expected {expected}, got {result}"
    )


@pytest.mark.parametrize('case', _CASES, ids=_IDS)
def test_deterministic_author_check(case):
    """check_author_hallucination returns expected verdict or None."""
    entry = case['error_entry']
    expected_verdict = case['expect_deterministic_verdict']
    result = check_author_hallucination(entry)

    if expected_verdict is None:
        assert result is None, (
            f"check_author_hallucination for '{case['id']}': "
            f"expected None, got {result}"
        )
    else:
        assert result is not None, (
            f"check_author_hallucination for '{case['id']}': "
            f"expected verdict '{expected_verdict}', got None"
        )
        assert result['verdict'] == expected_verdict, (
            f"check_author_hallucination for '{case['id']}': "
            f"expected '{expected_verdict}', got '{result['verdict']}'"
        )


@pytest.mark.parametrize('case', _CASES, ids=_IDS)
def test_run_hallucination_check_no_llm(case):
    """run_hallucination_check with llm_client=None returns expected verdict."""
    entry = case['error_entry']
    expected_verdict = case['expect_run_no_llm_verdict']
    result = run_hallucination_check(entry, llm_client=None)

    if expected_verdict is None:
        assert result is None, (
            f"run_hallucination_check(no LLM) for '{case['id']}': "
            f"expected None, got {result}"
        )
    else:
        assert result is not None, (
            f"run_hallucination_check(no LLM) for '{case['id']}': "
            f"expected verdict '{expected_verdict}', got None"
        )
        assert result['verdict'] == expected_verdict, (
            f"run_hallucination_check(no LLM) for '{case['id']}': "
            f"expected '{expected_verdict}', got '{result['verdict']}'"
        )


# ── Backend-level tests for _has_real_errors and _pre_screen_hallucination ──

class TestHasRealErrors:
    """Tests for RefCheckerWrapper._has_real_errors (suggestion filtering)."""

    @staticmethod
    def _call(raw_errors):
        from backend.refchecker_wrapper import ProgressRefChecker
        return ProgressRefChecker._has_real_errors(raw_errors)

    def test_suggestion_only(self):
        raw = [{'is_suggestion': True, 'error_type': 'suggestion_arxiv_url',
                'error_details': 'Could include arXiv URL'}]
        assert self._call(raw) is False

    def test_info_only(self):
        raw = [{'is_info': True, 'error_type': 'info',
                'error_details': 'Informational note'}]
        assert self._call(raw) is False

    def test_suggestion_type_prefix(self):
        raw = [{'error_type': 'suggestion_doi', 'error_details': 'DOI suggestion'}]
        assert self._call(raw) is False

    def test_real_error(self):
        raw = [{'error_type': 'author', 'error_details': 'Author count mismatch'}]
        assert self._call(raw) is True

    def test_mixed_suggestion_and_error(self):
        raw = [
            {'is_suggestion': True, 'error_type': 'suggestion_arxiv_url',
             'error_details': 'arXiv URL'},
            {'error_type': 'author', 'error_details': 'Author mismatch'},
        ]
        assert self._call(raw) is True

    def test_empty(self):
        assert self._call([]) is False
        assert self._call(None) is False


class TestPreScreenHallucination:
    """Tests for RefCheckerWrapper._pre_screen_hallucination."""

    @staticmethod
    def _make_wrapper():
        """Create a minimal ProgressRefChecker for testing."""
        from backend.refchecker_wrapper import ProgressRefChecker
        wrapper = object.__new__(ProgressRefChecker)
        return wrapper

    def _call(self, result, reference):
        wrapper = self._make_wrapper()
        return wrapper._pre_screen_hallucination(result, reference)

    def test_suggestion_only_skips(self):
        result = {
            '_raw_errors': [{'is_suggestion': True, 'error_type': 'suggestion_arxiv_url',
                             'error_details': 'arXiv URL suggestion'}],
            'authoritative_urls': [{'type': 'semantic_scholar',
                                    'url': 'https://api.semanticscholar.org/CorpusID:123'}],
        }
        ref = {'title': 'Some Paper', 'authors': ['A Author'], 'year': '2024'}
        outcome, _ = self._call(result, ref)
        assert outcome == 'skip'

    def test_zero_overlap_resolved_as_hallucination(self):
        result = {
            '_raw_errors': [{'error_type': 'author',
                             'error_details': 'Author count mismatch: 4 vs 8',
                             'ref_authors_correct': 'X Yan, Y Xiong, Z Kundu, W Yang, S Deng, M Wang, W Xia, S Soatto'}],
            'authoritative_urls': [{'type': 'semantic_scholar',
                                    'url': 'https://s2/CorpusID:123'}],
            'errors': [{'error_type': 'author', 'error_details': 'mismatch'}],
            'warnings': [],
            'suggestions': [],
            'status': 'error',
        }
        ref = {'title': 'Positive-congruent training', 'year': '2024',
               'authors': ['L. Zhou', 'Y. Zheng', 'T. Li', 'Y. Wang']}
        outcome, resolved = self._call(result, ref)
        assert outcome == 'resolved'
        assert resolved['hallucination_assessment']['verdict'] == 'LIKELY'
        assert resolved['status'] == 'hallucination'

    def test_high_overlap_verified_skips(self):
        result = {
            '_raw_errors': [{'error_type': 'author',
                             'error_details': 'Author count mismatch: 7 vs 6',
                             'ref_authors_correct': 'Runjian Chen, Han Zhang, Avinash Ravichandran, Wenqi Shao, Alex Wong, Ping Luo'}],
            'authoritative_urls': [{'type': 'semantic_scholar',
                                    'url': 'https://s2/CorpusID:274464966'}],
        }
        ref = {'title': 'CLAP: Unsupervised 3d representation learning',
               'authors': ['Runjian Chen', 'Hang Zhang', 'Avinash Ravichandran',
                           'Hyoungseob Park', 'Wenqi Shao', 'Alex Wong', 'Ping Luo'],
               'year': '2026'}
        outcome, _ = self._call(result, ref)
        assert outcome == 'skip'

    def test_unverified_needs_async(self):
        result = {
            '_raw_errors': [{'error_type': 'unverified',
                             'error_details': 'Could not be verified'}],
            'authoritative_urls': [],
        }
        ref = {'title': 'A made-up reference for testing', 'year': '2024',
               'authors': ['John Doe', 'Jane Smith']}
        outcome, _ = self._call(result, ref)
        assert outcome == 'needs_async'


class TestHasRealErrorsRawFormat:
    """Tests for _has_real_errors with verifier's raw format (info_type key)."""

    @staticmethod
    def _call(raw_errors):
        from backend.refchecker_wrapper import ProgressRefChecker
        return ProgressRefChecker._has_real_errors(raw_errors)

    def test_raw_info_type_only(self):
        """Raw verifier entries with only info_type are NOT real errors."""
        raw = [{'info_type': 'url',
                'info_details': 'Reference could include arXiv URL: https://arxiv.org/abs/2501.00467'}]
        assert self._call(raw) is False

    def test_raw_warning_type_only(self):
        """Raw verifier entries with only warning_type ARE real (warnings are checked)."""
        raw = [{'warning_type': 'venue',
                'warning_details': 'Venue mismatch'}]
        assert self._call(raw) is True

    def test_raw_error_type(self):
        """Raw verifier entries with error_type ARE real errors."""
        raw = [{'error_type': 'author',
                'error_details': 'Author count mismatch'}]
        assert self._call(raw) is True

    def test_raw_info_plus_warning(self):
        """Mix of raw info + warning — has real errors (warning)."""
        raw = [
            {'info_type': 'url', 'info_details': 'arXiv URL suggestion'},
            {'warning_type': 'venue', 'warning_details': 'Venue mismatch'},
        ]
        assert self._call(raw) is True

    def test_raw_info_only_multiple(self):
        """Multiple info-only raw entries — no real errors."""
        raw = [
            {'info_type': 'url', 'info_details': 'arXiv URL suggestion'},
            {'info_type': 'doi', 'info_details': 'DOI suggestion'},
        ]
        assert self._call(raw) is False


class TestPreScreenRawInfoOnly:
    """Pre-screen should skip refs whose only raw errors are info entries."""

    @staticmethod
    def _make_wrapper():
        from backend.refchecker_wrapper import ProgressRefChecker
        return object.__new__(ProgressRefChecker)

    def _call(self, result, reference):
        wrapper = self._make_wrapper()
        return wrapper._pre_screen_hallucination(result, reference)

    def test_raw_info_only_skips(self):
        """Ref with only info_type raw errors (arXiv URL suggestion) is skipped."""
        result = {
            '_raw_errors': [{'info_type': 'url',
                             'info_details': 'Reference could include arXiv URL: https://arxiv.org/abs/2501.00467'}],
            'authoritative_urls': [{'type': 'semantic_scholar',
                                    'url': 'https://api.semanticscholar.org/CorpusID:275212990'}],
        }
        ref = {'title': 'Score-based metropolis-hastings algorithms',
               'authors': ['Ahmed Aloui', 'Ali Hasan', 'Juncheng Dong',
                            'Zihao Wu', 'Vahid Tarokh'],
               'year': '2024'}
        outcome, _ = self._call(result, ref)
        assert outcome == 'skip'


class TestArxivReVerify:
    """Tests for RefChecker._try_arxiv_re_verify (wrong-DB-match fallback)."""

    @staticmethod
    def _make_checker():
        """Create a minimal RefChecker for testing _try_arxiv_re_verify."""
        from unittest.mock import MagicMock
        from refchecker.core.refchecker import ArxivReferenceChecker
        checker = object.__new__(ArxivReferenceChecker)
        # Minimum attributes needed
        checker.db_path = None
        checker.non_arxiv_checker = MagicMock()
        return checker

    def test_no_author_error_returns_none(self):
        """No author error → no re-verification attempted."""
        checker = self._make_checker()
        errors = [{'error_type': 'year', 'error_details': 'Year mismatch'}]
        verified_data = {'title': 'Some paper'}
        ref = {'title': 'Some paper', 'authors': ['A B'], 'year': '2024'}
        result = checker._try_arxiv_re_verify(errors, 'http://s2/123', verified_data, ref)
        assert result == (None, None, None)

    def test_high_overlap_returns_none(self):
        """Author error with high overlap → no re-verification (not a wrong match)."""
        checker = self._make_checker()
        errors = [{
            'error_type': 'author',
            'error_details': 'Author count mismatch: 7 vs 6',
            'ref_authors_cited': 'Runjian Chen, Hang Zhang, Avinash Ravichandran, Hyoungseob Park, Wenqi Shao, Alex Wong, Ping Luo',
            'ref_authors_correct': 'Runjian Chen, Han Zhang, Avinash Ravichandran, Wenqi Shao, Alex Wong, Ping Luo',
        }]
        verified_data = {'title': 'CLAP paper', 'externalIds': {'ArXiv': '2412.03059'}}
        ref = {'title': 'CLAP paper', 'authors': ['Runjian Chen', 'Hang Zhang'], 'year': '2026'}
        result = checker._try_arxiv_re_verify(errors, 'http://s2/123', verified_data, ref)
        assert result == (None, None, None)

    def test_zero_overlap_no_arxiv_returns_none(self):
        """0% overlap but no ArXiv ID → no re-verification possible."""
        checker = self._make_checker()
        errors = [{
            'error_type': 'author',
            'error_details': 'Author count mismatch',
            'ref_authors_cited': 'L. Zhou, Y. Zheng, T. Li, Y. Wang',
            'ref_authors_correct': 'Sijie Yan, Yuanjun Xiong, Kaustav Kundu, Shuo Yang, Siqi Deng, Meng Wang, Wei Xia, Stefano Soatto',
        }]
        verified_data = {'title': 'Other paper', 'externalIds': {}}
        ref = {'title': 'Some paper', 'authors': ['L. Zhou'], 'year': '2024'}
        result = checker._try_arxiv_re_verify(errors, 'http://s2/123', verified_data, ref)
        assert result == (None, None, None)

    def test_zero_overlap_with_arxiv_triggers_reverify(self):
        """0% overlap + ArXiv ID → re-verification is attempted (mocked)."""
        from unittest.mock import patch, MagicMock
        checker = self._make_checker()
        errors = [{
            'error_type': 'author',
            'error_details': 'Author count mismatch: 100 cited vs 2 correct',
            'ref_authors_cited': 'Author1, Author2, Author3, Author4, Author5',
            'ref_authors_correct': 'DifferentA, DifferentB',
        }]
        verified_data = {
            'title': 'DeepSeek-R1',
            'externalIds': {'ArXiv': '2501.12948'},
        }
        ref = {
            'title': 'DeepSeek-R1',
            'authors': ['Author1', 'Author2', 'Author3', 'Author4', 'Author5'],
            'year': '2025',
            'url': 'https://arxiv.org/abs/2501.12948',
        }
        # Mock ArXivCitationChecker.verify_reference to return success
        mock_arxiv_data = {'title': 'DeepSeek-R1: Real Paper', 'authors': []}
        mock_arxiv_errors = []
        mock_arxiv_url = 'https://arxiv.org/abs/2501.12948'

        with patch('refchecker.checkers.arxiv_citation.ArXivCitationChecker') as MockChecker:
            instance = MockChecker.return_value
            instance.extract_arxiv_id.return_value = ('2501.12948', None)
            instance.verify_reference.return_value = (mock_arxiv_data, mock_arxiv_errors, mock_arxiv_url)

            result_errors, result_url, result_data = checker._try_arxiv_re_verify(
                errors, 'http://s2/wrong', verified_data, ref
            )

        assert result_data is not None
        assert result_data['title'] == 'DeepSeek-R1: Real Paper'
        assert result_url == mock_arxiv_url
