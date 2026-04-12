"""Cross-mode consistency test: CLI single, CLI bulk, and WebUI must produce
identical hallucination verdicts for the same paper + cache.

Uses the in-repo fixture cache (tests/fixtures/test_cache) so the test
is fully self-contained — no external data dependencies or network calls.
All external HTTP requests are blocked; everything runs from the local DB
and API response cache.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'
CACHE_ROOT = _FIXTURES / 'test_cache'
DB_PATH = str(CACHE_ROOT)  # contains test_papers.db

# Discover all papers that have a cached bibliography
_PAPER_IDS = []
if CACHE_ROOT.is_dir():
    for d in sorted(CACHE_ROOT.iterdir()):
        if d.name.startswith('openreview_') and (d / 'bibliography.json').is_file():
            paper_id = d.name.removeprefix('openreview_')
            _PAPER_IDS.append(paper_id)


# ── Network blocking ──


# ── Per-reference result: (title, verdict) ──

def _ref_verdicts_cli(payload: dict) -> Dict[str, Optional[str]]:
    """Map lowercased ref title → hallucination verdict from CLI payload."""
    out = {}
    for r in payload['records']:
        title = r.get('ref_title', '').lower()
        ha = r.get('hallucination_assessment') or {}
        out[title] = ha.get('verdict')
    return out


def _ref_verdicts_webui(result: dict) -> Dict[str, Optional[str]]:
    """Map lowercased ref title → hallucination verdict from WebUI result."""
    out = {}
    for r in result.get('references') or []:
        if not r:
            continue
        title = r.get('title', '').lower()
        ha = r.get('hallucination_assessment') or {}
        out[title] = ha.get('verdict')
    return out


# ── Runners (network is blocked by the test fixture) ──

def _run_single(paper_id: str, cache_dir: str):
    from refchecker.core.refchecker import ArxivReferenceChecker
    url = f'https://openreview.net/forum?id={paper_id}'
    checker = ArxivReferenceChecker(
        db_path=DB_PATH, llm_config={'provider': 'anthropic'},
        cache_dir=cache_dir, enable_parallel=True,
    )
    checker.run(debug_mode=False, input_specs=[url])
    payload = checker._build_structured_report_payload()
    return _ref_verdicts_cli(payload), payload['summary']


def _run_bulk(paper_id: str, cache_dir: str):
    from refchecker.core.refchecker import ArxivReferenceChecker
    url = f'https://openreview.net/forum?id={paper_id}'
    checker = ArxivReferenceChecker(
        db_path=DB_PATH, llm_config={'provider': 'anthropic'},
        cache_dir=cache_dir, enable_parallel=True,
    )
    checker.run(debug_mode=False, input_specs=[url, url])
    payload = checker._build_structured_report_payload()
    return _ref_verdicts_cli(payload), payload['summary']


def _run_webui(paper_id: str, cache_dir: str):
    from backend.refchecker_wrapper import ProgressRefChecker
    url = f'https://openreview.net/forum?id={paper_id}'
    checker = ProgressRefChecker(
        llm_provider='anthropic', use_llm=True,
        db_path=DB_PATH, cache_dir=cache_dir,
    )
    result = asyncio.get_event_loop().run_until_complete(
        checker.check_paper(url, 'url')
    )
    return _ref_verdicts_webui(result), result['summary']


def _compare_verdicts(a: Dict[str, Optional[str]], b: Dict[str, Optional[str]],
                      label_a: str, label_b: str, paper_id: str):
    """Assert two verdict maps are identical; produce a clear diff on failure."""
    diffs = []
    all_titles = sorted(set(list(a.keys()) + list(b.keys())))
    for t in all_titles:
        va = a.get(t)
        vb = b.get(t)
        if va != vb:
            diffs.append(f'  {t[:60]}: {label_a}={va}  {label_b}={vb}')
    assert not diffs, (
        f'[{paper_id}] {label_a} vs {label_b}: {len(diffs)} ref(s) differ:\n'
        + '\n'.join(diffs)
    )


@pytest.mark.integration
@pytest.mark.parametrize('paper_id', _PAPER_IDS, ids=_PAPER_IDS)
class TestMultiPaperModeConsistency:
    """All three modes must produce identical per-reference hallucination verdicts."""

    def test_all_modes_match(self, paper_id: str, tmp_path):
        """CLI single, CLI bulk, and WebUI must all produce the exact
        same hallucination verdict for every reference, and the same
        aggregate counts.

        All external HTTP calls return 404 instantly — data comes solely
        from the local Semantic Scholar DB, API response cache, and LLM
        response cache in tests/fixtures/test_cache.
        """
        cache_dir = str(CACHE_ROOT)

        single_verdicts, single_summary = _run_single(paper_id, cache_dir)
        bulk_verdicts, bulk_summary = _run_bulk(paper_id, cache_dir)
        webui_verdicts, webui_summary = _run_webui(paper_id, cache_dir)

        # Per-reference verdicts must match exactly.
        _compare_verdicts(single_verdicts, bulk_verdicts, 'Single', 'Bulk', paper_id)
        _compare_verdicts(single_verdicts, webui_verdicts, 'Single', 'WebUI', paper_id)

        # Aggregate hallucination counts must match.
        s_flag = single_summary['flagged_records']
        b_flag = bulk_summary['flagged_records']
        w_flag = webui_summary['hallucination_count']
        assert s_flag == b_flag == w_flag, (
            f'[{paper_id}] Hallucination counts differ: '
            f'Single={s_flag} Bulk={b_flag} WebUI={w_flag}'
        )

        # Error counts must match.
        s_err = single_summary['total_errors_found']
        b_err = bulk_summary['total_errors_found']
        w_err = webui_summary['errors_count']
        assert s_err == b_err == w_err, (
            f'[{paper_id}] Error counts differ: '
            f'Single={s_err} Bulk={b_err} WebUI={w_err}'
        )
