"""Deterministic cached full-paper regressions without live LLM usage.

This suite verifies that given the same cached bibliography and local DB,
CLI single, CLI bulk, and WebUI all produce identical per-reference
verification assessments.  Each mode runs its own full code path; the
outputs are normalised into a common format and compared.

External network is blocked so the suite remains deterministic.
No LLM provider is configured; all data comes from the fixture cache.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'
CACHE_ROOT = _FIXTURES / 'test_cache'
# Explicit path to the test DB file so all modes resolve identically.
DB_FILE = str(CACHE_ROOT / 'test_papers.db')


def _blocked_request(self, *args, **kw):
    response = MagicMock()
    response.status_code = 404
    response.text = ''
    response.content = b''
    response.json.return_value = {}
    response.headers = {}
    response.ok = False
    return response


PAPER_CASES = [
    '0FhrtdKLtD',
    '5vdw8Qmrre',
    'H8tismBT3Q',
    'JFY9MZtWTu',
    'ioYdy7aghG',
    'izbBqTL8vb',
]

_RESULTS_CACHE: dict[str, dict] = {}


def _skip_if_missing() -> None:
    if not CACHE_ROOT.is_dir():
        pytest.skip(f'Fixture cache not found at {CACHE_ROOT}')
    if not Path(DB_FILE).is_file():
        pytest.skip(f'Test DB not found at {DB_FILE}')
    missing = [
        pid for pid in PAPER_CASES
        if not (CACHE_ROOT / f'openreview_{pid}' / 'bibliography.json').is_file()
    ]
    if missing:
        pytest.skip(f'Cached bibliographies missing for: {", ".join(sorted(missing))}')


def _load_cached_bibliography(paper_id: str) -> List[Dict[str, Any]]:
    path = CACHE_ROOT / f'openreview_{paper_id}' / 'bibliography.json'
    return json.loads(path.read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# Normalisation helpers – convert each mode's output into a common format:
#   { title_lower → sorted list of (severity, issue_type) tuples }
# where severity ∈ {'error', 'warning', 'info'} and issue_type is a string
# like 'year', 'author', 'venue', 'url', 'unverified', etc.
# ---------------------------------------------------------------------------

def _normalise_cli(payload: dict) -> Dict[str, List[Tuple[str, str]]]:
    """Normalise CLI / Bulk structured-report records."""
    m: Dict[str, List[Tuple[str, str]]] = {}
    for rec in payload.get('records', []):
        title = rec.get('ref_title', '').lower().strip()
        issues: List[Tuple[str, str]] = []
        for e in rec.get('_original_errors', []):
            if 'error_type' in e:
                issues.append(('error', e['error_type']))
            elif 'warning_type' in e:
                issues.append(('warning', e['warning_type']))
            elif 'info_type' in e:
                issues.append(('info', e['info_type']))
        m[title] = sorted(issues)
    return m


def _normalise_webui(result: dict) -> Dict[str, List[Tuple[str, str]]]:
    """Normalise WebUI per-reference results."""
    m: Dict[str, List[Tuple[str, str]]] = {}
    for ref in (result.get('references') or []):
        title = ref.get('title', '').lower().strip()
        issues: List[Tuple[str, str]] = []
        for e in ref.get('errors', []):
            issues.append(('error', e.get('error_type', '')))
        for w in ref.get('warnings', []):
            issues.append(('warning', w.get('error_type', '')))
        for s in ref.get('suggestions', []):
            issues.append(('info', s.get('suggestion_type') or s.get('error_type', '')))
        if issues:
            m[title] = sorted(issues)
    return m


def _compare_assessments(
    left: Dict[str, List],
    right: Dict[str, List],
    left_label: str,
    right_label: str,
    paper_id: str,
) -> None:
    all_titles = sorted(set(left) | set(right))
    diffs = []
    for title in all_titles:
        l = left.get(title, [])
        r = right.get(title, [])
        if l != r:
            diffs.append(
                f'  {title[:60]}:\n'
                f'    {left_label}: {l}\n'
                f'    {right_label}: {r}'
            )
    assert not diffs, (
        f'[{paper_id}] {left_label} vs {right_label}: '
        f'{len(diffs)} ref(s) differ:\n' + '\n'.join(diffs)
    )


# ---------------------------------------------------------------------------
# Network-blocking context manager
# ---------------------------------------------------------------------------

class _BlockedNetwork:
    """Block all HTTP and set arxiv retries to zero."""

    def __enter__(self):
        self._orig_request = requests.Session.request
        self._orig_get = requests.Session.get
        self._orig_post = requests.Session.post
        requests.Session.request = _blocked_request
        requests.Session.get = _blocked_request
        requests.Session.post = _blocked_request

        self._orig_httpx = None
        try:
            import httpx
            self._orig_httpx = httpx.Client.send
            httpx.Client.send = (
                lambda self, *a, **k: (_ for _ in ()).throw(ConnectionError('blocked'))
            )
        except ImportError:
            pass

        import arxiv
        self._orig_arxiv_init = arxiv.Client.__init__
        _real = self._orig_arxiv_init
        def _fast(inst, *a, **kw):
            kw['delay_seconds'] = 0
            kw['num_retries'] = 0
            return _real(inst, *a, **kw)
        arxiv.Client.__init__ = _fast
        return self

    def __exit__(self, *exc):
        requests.Session.request = self._orig_request
        requests.Session.get = self._orig_get
        requests.Session.post = self._orig_post
        if self._orig_httpx is not None:
            import httpx
            httpx.Client.send = self._orig_httpx
        import arxiv
        arxiv.Client.__init__ = self._orig_arxiv_init
        return False


# ---------------------------------------------------------------------------
# Result collection – runs all 3 modes (cached per paper_id)
# ---------------------------------------------------------------------------

def _get_paper_results(paper_id: str) -> dict:
    if paper_id in _RESULTS_CACHE:
        return _RESULTS_CACHE[paper_id]

    _skip_if_missing()
    url = f'https://openreview.net/forum?id={paper_id}'
    bib = _load_cached_bibliography(paper_id)

    with _BlockedNetwork():
        from refchecker.core.refchecker import ArxivReferenceChecker
        from backend.refchecker_wrapper import ProgressRefChecker

        # ---- CLI single ----
        checker = ArxivReferenceChecker(
            db_path=DB_FILE, llm_config=None,
            cache_dir=str(CACHE_ROOT), enable_parallel=True,
        )
        checker.run(debug_mode=False, input_specs=[url])
        single_payload = checker._build_structured_report_payload()

        # ---- CLI bulk (duplicate URL → dedup to 1) ----
        checker = ArxivReferenceChecker(
            db_path=DB_FILE, llm_config=None,
            cache_dir=str(CACHE_ROOT), enable_parallel=True,
        )
        checker.run(debug_mode=False, input_specs=[url, url])
        bulk_payload = checker._build_structured_report_payload()

        # ---- WebUI ----
        web_checker = ProgressRefChecker(
            llm_provider=None, use_llm=False,
            db_path=DB_FILE, cache_dir=str(CACHE_ROOT),
        )
        webui_result = asyncio.run(web_checker.check_paper(url, 'url'))

    result = {
        'single_payload': single_payload,
        'bulk_payload': bulk_payload,
        'webui_result': webui_result,
        'bib_count': len(bib),
        'norm_single': _normalise_cli(single_payload),
        'norm_bulk': _normalise_cli(bulk_payload),
        'norm_webui': _normalise_webui(webui_result),
    }
    _RESULTS_CACHE[paper_id] = result
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestCachedFullPaperRegression:
    """Given identical cached inputs, all modes must produce the same
    per-reference verification assessment."""

    @pytest.mark.parametrize('paper_id', PAPER_CASES, ids=PAPER_CASES)
    def test_bibliography_count_matches(self, paper_id: str) -> None:
        """All modes process the same number of references."""
        r = _get_paper_results(paper_id)
        n = r['bib_count']
        assert r['single_payload']['summary']['total_references_processed'] == n
        assert r['bulk_payload']['summary']['total_references_processed'] == n
        assert r['webui_result']['summary']['total_refs'] == n

    @pytest.mark.parametrize('paper_id', PAPER_CASES, ids=PAPER_CASES)
    def test_single_vs_bulk(self, paper_id: str) -> None:
        """CLI single and CLI bulk produce identical assessments."""
        r = _get_paper_results(paper_id)
        _compare_assessments(
            r['norm_single'], r['norm_bulk'], 'Single', 'Bulk', paper_id)

    @pytest.mark.parametrize('paper_id', PAPER_CASES, ids=PAPER_CASES)
    def test_single_vs_webui(self, paper_id: str) -> None:
        """CLI single and WebUI produce identical assessments."""
        r = _get_paper_results(paper_id)
        _compare_assessments(
            r['norm_single'], r['norm_webui'], 'Single', 'WebUI', paper_id)

    @pytest.mark.parametrize('paper_id', PAPER_CASES, ids=PAPER_CASES)
    def test_webui_uses_cache(self, paper_id: str) -> None:
        """WebUI loads bibliography from the fixture cache."""
        r = _get_paper_results(paper_id)
        assert r['webui_result']['summary']['extraction_method'] == 'cache'