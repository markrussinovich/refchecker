"""Cross-mode consistency test: CLI single, CLI bulk, and WebUI must produce
identical hallucination verdicts for the same paper.

Uses the in-repo fixture cache (tests/fixtures/test_cache) with network
blocked at the socket level so the test is fully self-contained and fast.
All data comes from the local S2 DB, API response cache, and LLM response
cache — no external calls are made.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, Optional
from unittest.mock import MagicMock

import requests
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'
CACHE_ROOT = _FIXTURES / 'test_cache'
DB_PATH = str(CACHE_ROOT)

def _blocked_request(self, url, **kw):
    r = MagicMock(); r.status_code = 404; r.text = ''; r.content = b''
    r.json.return_value = {}; r.headers = {}; r.ok = False; return r

# Discover papers with cached bibliographies
_PAPER_IDS = []
if CACHE_ROOT.is_dir():
    for d in sorted(CACHE_ROOT.iterdir()):
        if d.name.startswith('openreview_') and (d / 'bibliography.json').is_file():
            _PAPER_IDS.append(d.name.removeprefix('openreview_'))


# ── Helpers ──

def _ref_verdicts_cli(payload: dict) -> Dict[str, Optional[str]]:
    return {
        r.get('ref_title', '').lower(): (r.get('hallucination_assessment') or {}).get('verdict')
        for r in payload['records']
    }


def _ref_verdicts_webui(result: dict) -> Dict[str, Optional[str]]:
    return {
        r.get('title', '').lower(): (r.get('hallucination_assessment') or {}).get('verdict')
        for r in (result.get('references') or []) if r
    }


def _compare_verdicts(a, b, label_a, label_b, paper_id):
    diffs = [
        f'  {t[:60]}: {label_a}={a.get(t)}  {label_b}={b.get(t)}'
        for t in sorted(set(list(a) + list(b)))
        if a.get(t) != b.get(t)
    ]
    assert not diffs, (
        f'[{paper_id}] {label_a} vs {label_b}: {len(diffs)} ref(s) differ:\n'
        + '\n'.join(diffs)
    )


# ── Run all modes for a paper (network blocked) ──

_cache: Dict[str, dict] = {}


def _get_paper_results(paper_id: str) -> dict:
    """Run single/bulk/webui once per paper, cache in module dict."""
    if paper_id in _cache:
        return _cache[paper_id]

    cache_dir = str(CACHE_ROOT)
    url = f'https://openreview.net/forum?id={paper_id}'

    # Block network, restore after
    _orig_get = requests.Session.get
    _orig_post = requests.Session.post
    requests.Session.get = _blocked_request
    requests.Session.post = _blocked_request
    _orig_httpx = None
    try:
        import httpx
        _orig_httpx = httpx.Client.send
        httpx.Client.send = lambda self, *a, **k: (_ for _ in ()).throw(
            ConnectionError('blocked'))
    except ImportError:
        pass

    try:
        from refchecker.core.refchecker import ArxivReferenceChecker

        # Single
        c = ArxivReferenceChecker(db_path=DB_PATH, llm_config={'provider': 'anthropic'},
                                  cache_dir=cache_dir, enable_parallel=True)
        c.run(debug_mode=True, input_specs=[url])
        single_payload = c._build_structured_report_payload()

        # Bulk
        c = ArxivReferenceChecker(db_path=DB_PATH, llm_config={'provider': 'anthropic'},
                                  cache_dir=cache_dir, enable_parallel=True)
        c.run(debug_mode=True, input_specs=[url, url])
        bulk_payload = c._build_structured_report_payload()

        # WebUI
        from backend.refchecker_wrapper import ProgressRefChecker
        w = ProgressRefChecker(llm_provider='anthropic', use_llm=True,
                               db_path=DB_PATH, cache_dir=cache_dir)
        webui_result = asyncio.get_event_loop().run_until_complete(
            w.check_paper(url, 'url'))
    finally:
        requests.Session.get = _orig_get
        requests.Session.post = _orig_post
        if _orig_httpx:
            import httpx
            httpx.Client.send = _orig_httpx

    entry = {
        'single_verdicts': _ref_verdicts_cli(single_payload),
        'single_summary': single_payload['summary'],
        'bulk_verdicts': _ref_verdicts_cli(bulk_payload),
        'bulk_summary': bulk_payload['summary'],
        'webui_verdicts': _ref_verdicts_webui(webui_result),
        'webui_summary': webui_result['summary'],
    }
    _cache[paper_id] = entry
    return entry


@pytest.mark.integration
@pytest.mark.parametrize('paper_id', _PAPER_IDS, ids=_PAPER_IDS)
class TestMultiPaperModeConsistency:
    """All three modes must produce identical per-reference hallucination verdicts."""

    def test_all_modes_match(self, paper_id: str, tmp_path):
        r = _get_paper_results(paper_id)

        _compare_verdicts(r['single_verdicts'], r['bulk_verdicts'],
                          'Single', 'Bulk', paper_id)
        _compare_verdicts(r['single_verdicts'], r['webui_verdicts'],
                          'Single', 'WebUI', paper_id)

        s_flag = r['single_summary']['flagged_records']
        b_flag = r['bulk_summary']['flagged_records']
        w_flag = r['webui_summary']['hallucination_count']
        assert s_flag == b_flag == w_flag, (
            f'[{paper_id}] Hallucination counts differ: '
            f'Single={s_flag} Bulk={b_flag} WebUI={w_flag}'
        )

        s_err = r['single_summary']['total_errors_found']
        b_err = r['bulk_summary']['total_errors_found']
        w_err = r['webui_summary']['errors_count']
        assert s_err == b_err == w_err, (
            f'[{paper_id}] Error counts differ: '
            f'Single={s_err} Bulk={b_err} WebUI={w_err}'
        )
