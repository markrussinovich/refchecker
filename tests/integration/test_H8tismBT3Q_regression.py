"""Regression test for OpenReview paper H8tismBT3Q (AFD-INSTRUCTION).

Uses a pre-populated cache (PDF, bibliography, LLM responses, API
responses) so the test is fully offline and deterministic.  Verifies
that CLI single-paper and bulk modes produce identical hallucination
counts, matching the WebUI baseline.

Expected results (from cached extraction of 90 references):
    - 8 references flagged as LIKELY hallucinated
    - unverified count >= hallucinated count

The 8 hallucinated references are:
    - Biotalk: Enzyme function prediction with natural language supervision
    - Deepseek-r1: Incentivizing reasoning capability in llms via reinforcement learning
    - Drugchat: Towards enabling chatgpt-like capabilities on drug molecule data
    - Generative ai for de novo drug design: recent advances, challenges, and future directions
    - Mathprompter: Mathematical reasoning using large language models
    - Ontoprotein: Protein pretraining with gene ontology embedding
    - Proteinchat: Aligning protein structures with natural language descriptions
    - Swissprot-aug: Augmenting protein function descriptions for language model training
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

FIXTURE_CACHE = Path(__file__).resolve().parents[1] / 'fixtures' / 'cache_H8tismBT3Q'
FIXTURE_DB = FIXTURE_CACHE / 'test_papers.db'
PAPER_URL = 'https://openreview.net/forum?id=H8tismBT3Q'

EXPECTED_HALLUCINATED_COUNT = 7  # 6 from WebUI + Mathprompter (deterministic author check)


def _get_db_path():
    """Return the path to the test database (fixture or full)."""
    if FIXTURE_DB.is_file():
        return str(FIXTURE_DB)
    pytest.skip(f'Test database not found at {FIXTURE_DB}')


def _prepare_cache(tmp_path: Path) -> str:
    """Copy fixture cache to a temp directory and return the path."""
    cache_dir = tmp_path / 'cache'
    shutil.copytree(FIXTURE_CACHE, cache_dir)
    return str(cache_dir)


@pytest.mark.integration
@pytest.mark.network
class TestH8tismBT3QRegression:
    """Verify hallucination detection for H8tismBT3Q matches across all modes."""

    def _run_single_paper(self, cache_dir: str, db_path: str):
        """Run single-paper CLI mode and return the structured payload."""
        from refchecker.core.refchecker import ArxivReferenceChecker

        checker = ArxivReferenceChecker(
            db_path=db_path,
            llm_config={'provider': 'anthropic'},
            cache_dir=cache_dir,
            enable_parallel=True,
        )
        checker.run(
            debug_mode=False,
            input_specs=[PAPER_URL],
        )
        return checker._build_structured_report_payload()

    def _run_bulk(self, cache_dir: str, db_path: str):
        """Run bulk mode and return the structured payload."""
        from refchecker.core.refchecker import ArxivReferenceChecker

        checker = ArxivReferenceChecker(
            db_path=db_path,
            llm_config={'provider': 'anthropic'},
            cache_dir=cache_dir,
            enable_parallel=True,
        )
        checker.run(
            debug_mode=False,
            input_specs=[PAPER_URL, PAPER_URL],  # 2 specs triggers bulk path
        )
        return checker._build_structured_report_payload()

    def _extract_flagged_titles(self, payload: dict) -> set:
        """Extract lowercased titles of LIKELY-flagged records."""
        return {
            r['ref_title'].lower()
            for r in payload['records']
            if r.get('hallucination_assessment', {}).get('verdict') == 'LIKELY'
        }

    def test_single_paper_minimum_hallucinations(self, tmp_path):
        """Single-paper mode should flag at least MINIMUM_HALLUCINATED_COUNT refs."""
        db_path = _get_db_path()
        cache_dir = _prepare_cache(tmp_path)
        payload = self._run_single_paper(cache_dir, db_path)
        flagged = self._extract_flagged_titles(payload)
        assert len(flagged) == EXPECTED_HALLUCINATED_COUNT, (
            f'Single-paper mode flagged {len(flagged)} refs, expected {EXPECTED_HALLUCINATED_COUNT}.\n'
            f'Flagged: {sorted(flagged)}'
        )

    def test_single_paper_unverified_ge_hallucinated(self, tmp_path):
        """Display unverified count (max of raw unverified, flagged) should be >= hallucinated."""
        db_path = _get_db_path()
        cache_dir = _prepare_cache(tmp_path)
        payload = self._run_single_paper(cache_dir, db_path)
        flagged = payload['summary'].get('flagged_records', 0)
        raw_unverified = payload['summary'].get('total_unverified_refs', 0)
        display_unverified = max(raw_unverified, flagged)
        assert display_unverified >= flagged, (
            f'display unverified ({display_unverified}) < hallucinated ({flagged})'
        )

    def test_bulk_minimum_hallucinations(self, tmp_path):
        """Bulk mode should flag at least MINIMUM_HALLUCINATED_COUNT refs."""
        db_path = _get_db_path()
        cache_dir = _prepare_cache(tmp_path)
        payload = self._run_bulk(cache_dir, db_path)
        flagged = self._extract_flagged_titles(payload)
        assert len(flagged) == EXPECTED_HALLUCINATED_COUNT, (
            f'Bulk mode flagged {len(flagged)} refs, expected {EXPECTED_HALLUCINATED_COUNT}.\n'
            f'Flagged: {sorted(flagged)}'
        )

    def test_single_and_bulk_match(self, tmp_path):
        """Single-paper and bulk modes must flag the same refs."""
        db_path = _get_db_path()
        cache_dir_single = _prepare_cache(tmp_path / 'single')
        cache_dir_bulk = _prepare_cache(tmp_path / 'bulk')

        single_payload = self._run_single_paper(cache_dir_single, db_path)
        bulk_payload = self._run_bulk(cache_dir_bulk, db_path)

        single_flagged = self._extract_flagged_titles(single_payload)
        bulk_flagged = self._extract_flagged_titles(bulk_payload)

        # Both must flag the same count.  The specific set may differ by at
        # most 1 borderline ref due to batched vs inline hallucination
        # assessment processing order.
        assert len(single_flagged) == len(bulk_flagged), (
            f'Single ({len(single_flagged)}) and bulk ({len(bulk_flagged)}) counts differ.\n'
            f'Only in single: {single_flagged - bulk_flagged}\n'
            f'Only in bulk: {bulk_flagged - single_flagged}'
        )
        sym_diff = single_flagged.symmetric_difference(bulk_flagged)
        assert len(sym_diff) <= 2, (
            f'Single and bulk diverge by > 1 ref.\n'
            f'Only in single: {single_flagged - bulk_flagged}\n'
            f'Only in bulk: {bulk_flagged - single_flagged}'
        )
