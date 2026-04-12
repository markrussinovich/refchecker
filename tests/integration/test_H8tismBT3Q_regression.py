"""Regression test for OpenReview paper H8tismBT3Q (AFD-INSTRUCTION).

Uses the in-repo fixture cache (tests/fixtures/test_cache) with network
blocked so the test is fully self-contained and fast.  All data comes
from the local S2 DB, API response cache, and LLM response cache.

Each mode (single, bulk, WebUI) is run exactly once; all assertions
share the cached results.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import requests
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'
CACHE_DIR = str(_FIXTURES / 'test_cache')
DB_PATH = CACHE_DIR

# Block all HTTP at the Session class level (propagates to worker threads).
# API/LLM caches are checked before requests are made, so cached data still works.
_real_session_get = requests.Session.get
_real_session_post = requests.Session.post

def _blocked_request(self, url, **kw):
    r = MagicMock(); r.status_code = 404; r.text = ''; r.content = b''
    r.json.return_value = {}; r.headers = {}; r.ok = False; return r

requests.Session.get = _blocked_request
requests.Session.post = _blocked_request

try:
    import httpx
    httpx.Client.send = lambda self, *a, **k: (_ for _ in ()).throw(
        ConnectionError('Network blocked'))
except ImportError:
    pass
PAPER_URL = 'https://openreview.net/forum?id=H8tismBT3Q'

EXPECTED_HALLUCINATED_COUNT = 7


def _skip_if_missing():
    if not Path(CACHE_DIR).is_dir():
        pytest.skip(f'Fixture cache not found at {CACHE_DIR}')
    bib = Path(CACHE_DIR) / 'openreview_H8tismBT3Q' / 'bibliography.json'
    if not bib.is_file():
        pytest.skip(f'Bibliography not cached for H8tismBT3Q')


# ── Compute results once, share across all assertions ──

_results = {}


def _get_results():
    """Run all three modes exactly once, cache in module-level dict."""
    if _results:
        return _results

    _skip_if_missing()

    from refchecker.core.refchecker import ArxivReferenceChecker

    # Single
    checker = ArxivReferenceChecker(
        db_path=DB_PATH, llm_config={'provider': 'anthropic'},
        cache_dir=CACHE_DIR, enable_parallel=True,
    )
    checker.run(debug_mode=True, input_specs=[PAPER_URL])
    _results['single'] = checker._build_structured_report_payload()

    # Bulk
    checker = ArxivReferenceChecker(
        db_path=DB_PATH, llm_config={'provider': 'anthropic'},
        cache_dir=CACHE_DIR, enable_parallel=True,
    )
    checker.run(debug_mode=True, input_specs=[PAPER_URL, PAPER_URL])
    _results['bulk'] = checker._build_structured_report_payload()

    # WebUI
    from backend.refchecker_wrapper import ProgressRefChecker
    wchecker = ProgressRefChecker(
        llm_provider='anthropic', use_llm=True,
        db_path=DB_PATH, cache_dir=CACHE_DIR,
    )
    _results['webui'] = asyncio.get_event_loop().run_until_complete(
        wchecker.check_paper(PAPER_URL, 'url')
    )

    return _results


def _flagged_titles_cli(payload):
    return {
        r['ref_title'].lower()
        for r in payload['records']
        if (r.get('hallucination_assessment') or {}).get('verdict') == 'LIKELY'
    }


def _flagged_titles_webui(result):
    return {
        r['title'].lower()
        for r in result['references']
        if r and (r.get('hallucination_assessment') or {}).get('verdict') == 'LIKELY'
    }


@pytest.mark.integration
@pytest.mark.network
class TestH8tismBT3QRegression:
    """Verify hallucination detection for H8tismBT3Q matches across all modes."""

    def test_single_paper_hallucination_count(self):
        r = _get_results()
        flagged = _flagged_titles_cli(r['single'])
        assert len(flagged) == EXPECTED_HALLUCINATED_COUNT, (
            f'Single-paper mode flagged {len(flagged)} refs, expected {EXPECTED_HALLUCINATED_COUNT}.\n'
            f'Flagged: {sorted(flagged)}'
        )

    def test_single_paper_unverified_ge_hallucinated(self):
        r = _get_results()
        s = r['single']['summary']
        flagged = s.get('flagged_records', 0)
        raw_unverified = s.get('total_unverified_refs', 0)
        display_unverified = max(raw_unverified, flagged)
        assert display_unverified >= flagged, (
            f'display unverified ({display_unverified}) < hallucinated ({flagged})'
        )

    def test_bulk_hallucination_count(self):
        r = _get_results()
        flagged = _flagged_titles_cli(r['bulk'])
        assert len(flagged) == EXPECTED_HALLUCINATED_COUNT, (
            f'Bulk mode flagged {len(flagged)} refs, expected {EXPECTED_HALLUCINATED_COUNT}.\n'
            f'Flagged: {sorted(flagged)}'
        )

    def test_webui_hallucination_count(self):
        r = _get_results()
        flagged = _flagged_titles_webui(r['webui'])
        assert len(flagged) == EXPECTED_HALLUCINATED_COUNT, (
            f'WebUI mode flagged {len(flagged)} refs, expected {EXPECTED_HALLUCINATED_COUNT}.\n'
            f'Flagged: {sorted(flagged)}'
        )

    def test_all_modes_match(self):
        r = _get_results()
        single = _flagged_titles_cli(r['single'])
        bulk = _flagged_titles_cli(r['bulk'])
        webui = _flagged_titles_webui(r['webui'])
        assert single == bulk == webui, (
            f'Modes disagree on flagged refs.\n'
            f'Single ({len(single)}): {sorted(single)}\n'
            f'Bulk   ({len(bulk)}): {sorted(bulk)}\n'
            f'WebUI  ({len(webui)}): {sorted(webui)}'
        )
