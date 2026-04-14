"""Deterministic cached full-paper regressions.

This is the default end-to-end cached paper suite. It serves both purposes:
correctness (expected hallucination counts for known cached papers) and
cross-mode consistency (CLI single, CLI bulk, and WebUI agree).

All data comes from the fixture cache and local test DB. External network is
blocked so the suite remains deterministic.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, Optional
from unittest.mock import MagicMock

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'
CACHE_ROOT = _FIXTURES / 'test_cache'
DB_PATH = str(CACHE_ROOT)


def _blocked_request(self, url, **kw):
    response = MagicMock()
    response.status_code = 404
    response.text = ''
    response.content = b''
    response.json.return_value = {}
    response.headers = {}
    response.ok = False
    return response


PAPER_CASES = [
    ('0FhrtdKLtD', 2),
    ('5vdw8Qmrre', 0),
    ('H8tismBT3Q', 2),
    ('JFY9MZtWTu', 6),
    ('ioYdy7aghG', 0),
    ('izbBqTL8vb', 0),
]

_RESULTS_CACHE: Dict[str, dict] = {}


def _skip_if_missing() -> None:
    if not CACHE_ROOT.is_dir():
        pytest.skip(f'Fixture cache not found at {CACHE_ROOT}')

    missing = [
        paper_id
        for paper_id, _ in PAPER_CASES
        if not (CACHE_ROOT / f'openreview_{paper_id}' / 'bibliography.json').is_file()
    ]
    if missing:
        pytest.skip(f'Cached bibliographies missing for: {", ".join(sorted(missing))}')


def _flagged_titles_cli(payload: dict) -> set[str]:
    return {
        record.get('ref_title', '').lower()
        for record in payload.get('records', [])
        if (record.get('hallucination_assessment') or {}).get('verdict') == 'LIKELY'
    }


def _flagged_titles_webui(result: dict) -> set[str]:
    return {
        ref.get('title', '').lower()
        for ref in (result.get('references') or [])
        if ref and (ref.get('hallucination_assessment') or {}).get('verdict') == 'LIKELY'
    }


def _compare_verdicts(
    left: Dict[str, Optional[str]],
    right: Dict[str, Optional[str]],
    left_label: str,
    right_label: str,
    paper_id: str,
) -> None:
    diffs = [
        f'  {title[:60]}: {left_label}={left.get(title)}  {right_label}={right.get(title)}'
        for title in sorted(set(left) | set(right))
        if left.get(title) != right.get(title)
    ]
    assert not diffs, (
        f'[{paper_id}] {left_label} vs {right_label}: {len(diffs)} ref(s) differ:\n'
        + '\n'.join(diffs)
    )


def _ref_verdicts_cli(payload: dict) -> Dict[str, Optional[str]]:
    return {
        record.get('ref_title', '').lower(): (record.get('hallucination_assessment') or {}).get('verdict')
        for record in payload.get('records', [])
    }


def _ref_verdicts_webui(result: dict) -> Dict[str, Optional[str]]:
    return {
        ref.get('title', '').lower(): (ref.get('hallucination_assessment') or {}).get('verdict')
        for ref in (result.get('references') or []) if ref
    }


def _get_paper_results(paper_id: str) -> dict:
    if paper_id in _RESULTS_CACHE:
        return _RESULTS_CACHE[paper_id]

    _skip_if_missing()

    url = f'https://openreview.net/forum?id={paper_id}'

    orig_get = requests.Session.get
    orig_post = requests.Session.post
    requests.Session.get = _blocked_request
    requests.Session.post = _blocked_request
    orig_httpx = None
    try:
        import httpx

        orig_httpx = httpx.Client.send
        httpx.Client.send = lambda self, *a, **k: (_ for _ in ()).throw(ConnectionError('blocked'))
    except ImportError:
        pass

    try:
        from refchecker.core.refchecker import ArxivReferenceChecker
        from backend.refchecker_wrapper import ProgressRefChecker

        checker = ArxivReferenceChecker(
            db_path=DB_PATH,
            llm_config={'provider': 'anthropic'},
            cache_dir=str(CACHE_ROOT),
            enable_parallel=True,
        )
        checker.run(debug_mode=True, input_specs=[url])
        single_payload = checker._build_structured_report_payload()

        checker = ArxivReferenceChecker(
            db_path=DB_PATH,
            llm_config={'provider': 'anthropic'},
            cache_dir=str(CACHE_ROOT),
            enable_parallel=True,
        )
        checker.run(debug_mode=True, input_specs=[url, url])
        bulk_payload = checker._build_structured_report_payload()

        web_checker = ProgressRefChecker(
            llm_provider='anthropic',
            use_llm=True,
            db_path=DB_PATH,
            cache_dir=str(CACHE_ROOT),
        )
        webui_result = asyncio.get_event_loop().run_until_complete(web_checker.check_paper(url, 'url'))
    finally:
        requests.Session.get = orig_get
        requests.Session.post = orig_post
        if orig_httpx:
            import httpx

            httpx.Client.send = orig_httpx

    result = {
        'single_payload': single_payload,
        'single_verdicts': _ref_verdicts_cli(single_payload),
        'bulk_payload': bulk_payload,
        'bulk_verdicts': _ref_verdicts_cli(bulk_payload),
        'webui_result': webui_result,
        'webui_verdicts': _ref_verdicts_webui(webui_result),
    }
    _RESULTS_CACHE[paper_id] = result
    return result


@pytest.mark.integration
class TestCachedFullPaperRegression:
    """Default cached full-paper regressions: correctness plus mode consistency."""

    @pytest.mark.parametrize(
        'paper_id, expected_hallucinated_count',
        PAPER_CASES,
        ids=[paper_id for paper_id, _ in PAPER_CASES],
    )
    def test_cached_paper_correctness_and_mode_consistency(
        self,
        paper_id: str,
        expected_hallucinated_count: int,
    ) -> None:
        result = _get_paper_results(paper_id)

        single_flagged = _flagged_titles_cli(result['single_payload'])
        bulk_flagged = _flagged_titles_cli(result['bulk_payload'])
        webui_flagged = _flagged_titles_webui(result['webui_result'])

        _compare_verdicts(result['single_verdicts'], result['bulk_verdicts'], 'Single', 'Bulk', paper_id)
        _compare_verdicts(result['single_verdicts'], result['webui_verdicts'], 'Single', 'WebUI', paper_id)

        assert len(single_flagged) == expected_hallucinated_count, (
            f'[{paper_id}] single mode flagged {len(single_flagged)} refs, '
            f'expected {expected_hallucinated_count}.\nFlagged: {sorted(single_flagged)}'
        )
        assert len(bulk_flagged) == expected_hallucinated_count, (
            f'[{paper_id}] bulk mode flagged {len(bulk_flagged)} refs, '
            f'expected {expected_hallucinated_count}.\nFlagged: {sorted(bulk_flagged)}'
        )
        assert len(webui_flagged) == expected_hallucinated_count, (
            f'[{paper_id}] WebUI mode flagged {len(webui_flagged)} refs, '
            f'expected {expected_hallucinated_count}.\nFlagged: {sorted(webui_flagged)}'
        )

        single_summary = result['single_payload']['summary']
        bulk_summary = result['bulk_payload']['summary']
        webui_summary = result['webui_result']['summary']

        assert single_summary['flagged_records'] == bulk_summary['flagged_records'] == webui_summary['hallucination_count'], (
            f'[{paper_id}] Hallucination counts differ: '
            f'Single={single_summary["flagged_records"]} '
            f'Bulk={bulk_summary["flagged_records"]} '
            f'WebUI={webui_summary["hallucination_count"]}'
        )

        assert single_summary['total_errors_found'] == bulk_summary['total_errors_found'] == webui_summary['errors_count'], (
            f'[{paper_id}] Error counts differ: '
            f'Single={single_summary["total_errors_found"]} '
            f'Bulk={bulk_summary["total_errors_found"]} '
            f'WebUI={webui_summary["errors_count"]}'
        )