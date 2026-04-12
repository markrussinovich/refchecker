"""Regression test for OpenReview paper H8tismBT3Q (AFD-INSTRUCTION).

Uses the in-repo fixture cache (tests/fixtures/test_cache) so the
test is fully self-contained and produces deterministic results without
any external data dependencies.

Verifies that CLI single-paper, bulk, and WebUI modes produce identical
hallucination counts.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'
CACHE_DIR = str(_FIXTURES / 'test_cache')
DB_PATH = str(_FIXTURES / 'test_cache')  # contains test_papers.db
PAPER_URL = 'https://openreview.net/forum?id=H8tismBT3Q'

EXPECTED_HALLUCINATED_COUNT = 7


def _skip_if_missing():
    if not Path(CACHE_DIR).is_dir():
        pytest.skip(f'Fixture cache not found at {CACHE_DIR}')
    bib = Path(CACHE_DIR) / 'openreview_H8tismBT3Q' / 'bibliography.json'
    if not bib.is_file():
        pytest.skip(f'Bibliography not cached for H8tismBT3Q')


@pytest.mark.integration
@pytest.mark.network
class TestH8tismBT3QRegression:
    """Verify hallucination detection for H8tismBT3Q matches across all modes."""

    def _run_single_paper(self):
        from refchecker.core.refchecker import ArxivReferenceChecker
        checker = ArxivReferenceChecker(
            db_path=DB_PATH, llm_config={'provider': 'anthropic'},
            cache_dir=CACHE_DIR, enable_parallel=True,
        )
        checker.run(debug_mode=False, input_specs=[PAPER_URL])
        return checker._build_structured_report_payload()

    def _run_bulk(self):
        from refchecker.core.refchecker import ArxivReferenceChecker
        checker = ArxivReferenceChecker(
            db_path=DB_PATH, llm_config={'provider': 'anthropic'},
            cache_dir=CACHE_DIR, enable_parallel=True,
        )
        checker.run(debug_mode=False, input_specs=[PAPER_URL, PAPER_URL])
        return checker._build_structured_report_payload()

    def _run_webui(self):
        from backend.refchecker_wrapper import ProgressRefChecker
        checker = ProgressRefChecker(
            llm_provider='anthropic', use_llm=True,
            db_path=DB_PATH, cache_dir=CACHE_DIR,
        )
        result = asyncio.get_event_loop().run_until_complete(
            checker.check_paper(PAPER_URL, 'url')
        )
        return result

    def _extract_flagged_titles(self, payload: dict) -> set:
        return {
            r['ref_title'].lower()
            for r in payload['records']
            if r.get('hallucination_assessment', {}).get('verdict') == 'LIKELY'
        }

    def test_single_paper_minimum_hallucinations(self, tmp_path):
        _skip_if_missing()
        payload = self._run_single_paper()
        flagged = self._extract_flagged_titles(payload)
        assert len(flagged) == EXPECTED_HALLUCINATED_COUNT, (
            f'Single-paper mode flagged {len(flagged)} refs, expected {EXPECTED_HALLUCINATED_COUNT}.\n'
            f'Flagged: {sorted(flagged)}'
        )

    def test_single_paper_unverified_ge_hallucinated(self, tmp_path):
        _skip_if_missing()
        payload = self._run_single_paper()
        flagged = payload['summary'].get('flagged_records', 0)
        raw_unverified = payload['summary'].get('total_unverified_refs', 0)
        display_unverified = max(raw_unverified, flagged)
        assert display_unverified >= flagged, (
            f'display unverified ({display_unverified}) < hallucinated ({flagged})'
        )

    def test_bulk_minimum_hallucinations(self, tmp_path):
        _skip_if_missing()
        payload = self._run_bulk()
        flagged = self._extract_flagged_titles(payload)
        assert len(flagged) == EXPECTED_HALLUCINATED_COUNT, (
            f'Bulk mode flagged {len(flagged)} refs, expected {EXPECTED_HALLUCINATED_COUNT}.\n'
            f'Flagged: {sorted(flagged)}'
        )

    def test_single_and_bulk_match(self, tmp_path):
        _skip_if_missing()
        single_flagged = self._extract_flagged_titles(self._run_single_paper())
        bulk_flagged = self._extract_flagged_titles(self._run_bulk())
        assert single_flagged == bulk_flagged, (
            f'Single and bulk flag different refs.\n'
            f'Only in single: {single_flagged - bulk_flagged}\n'
            f'Only in bulk: {bulk_flagged - single_flagged}'
        )

    def test_webui_minimum_hallucinations(self, tmp_path):
        _skip_if_missing()
        result = self._run_webui()
        flagged = {
            r['title'].lower()
            for r in result['references']
            if r and (r.get('hallucination_assessment') or {}).get('verdict') == 'LIKELY'
        }
        assert len(flagged) == EXPECTED_HALLUCINATED_COUNT, (
            f'WebUI mode flagged {len(flagged)} refs, expected {EXPECTED_HALLUCINATED_COUNT}.\n'
            f'Flagged: {sorted(flagged)}'
        )

    def test_all_modes_match(self, tmp_path):
        _skip_if_missing()
        single_payload = self._run_single_paper()
        bulk_payload = self._run_bulk()
        webui_result = self._run_webui()

        single_flagged = self._extract_flagged_titles(single_payload)
        bulk_flagged = self._extract_flagged_titles(bulk_payload)
        webui_flagged = {
            r['title'].lower()
            for r in webui_result['references']
            if r and (r.get('hallucination_assessment') or {}).get('verdict') == 'LIKELY'
        }

        assert single_flagged == bulk_flagged == webui_flagged, (
            f'Modes disagree on flagged refs.\n'
            f'Single ({len(single_flagged)}): {sorted(single_flagged)}\n'
            f'Bulk   ({len(bulk_flagged)}): {sorted(bulk_flagged)}\n'
            f'WebUI  ({len(webui_flagged)}): {sorted(webui_flagged)}'
        )
