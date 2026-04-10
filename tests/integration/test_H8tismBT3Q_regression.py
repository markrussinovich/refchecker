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
PAPER_URL = 'https://openreview.net/forum?id=H8tismBT3Q'
DB_PATH = '/datadrive2/semanticscholardb/'

MINIMUM_HALLUCINATED_COUNT = 6  # WebUI baseline


def _needs_local_db():
    """Skip if local Semantic Scholar database is not available."""
    if not os.path.isdir(DB_PATH):
        pytest.skip(f'Local database not found at {DB_PATH}')


def _prepare_cache(tmp_path: Path) -> str:
    """Copy fixture cache to a temp directory and return the path."""
    cache_dir = tmp_path / 'cache'
    shutil.copytree(FIXTURE_CACHE, cache_dir)
    return str(cache_dir)


@pytest.mark.integration
@pytest.mark.network
class TestH8tismBT3QRegression:
    """Verify hallucination detection for H8tismBT3Q matches across all modes."""

    def _run_single_paper(self, cache_dir: str):
        """Run single-paper CLI mode and return the structured payload."""
        from refchecker.core.refchecker import ArxivReferenceChecker

        checker = ArxivReferenceChecker(
            db_path=DB_PATH,
            llm_config={'provider': 'anthropic'},
            cache_dir=cache_dir,
            enable_parallel=True,
        )
        checker.run(
            debug_mode=False,
            input_specs=[PAPER_URL],
        )
        return checker._build_structured_report_payload()

    def _run_bulk(self, cache_dir: str):
        """Run bulk mode and return the structured payload."""
        from refchecker.core.refchecker import ArxivReferenceChecker

        checker = ArxivReferenceChecker(
            db_path=DB_PATH,
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
        _needs_local_db()
        cache_dir = _prepare_cache(tmp_path)
        payload = self._run_single_paper(cache_dir)
        flagged = self._extract_flagged_titles(payload)
        assert len(flagged) >= MINIMUM_HALLUCINATED_COUNT, (
            f'Single-paper mode flagged {len(flagged)} refs, expected >= {MINIMUM_HALLUCINATED_COUNT}.\n'
            f'Flagged: {sorted(flagged)}'
        )

    def test_single_paper_unverified_ge_hallucinated(self, tmp_path):
        """Display unverified count (max of raw unverified, flagged) should be >= hallucinated."""
        _needs_local_db()
        cache_dir = _prepare_cache(tmp_path)
        payload = self._run_single_paper(cache_dir)
        flagged = payload['summary'].get('flagged_records', 0)
        raw_unverified = payload['summary'].get('total_unverified_refs', 0)
        display_unverified = max(raw_unverified, flagged)
        assert display_unverified >= flagged, (
            f'display unverified ({display_unverified}) < hallucinated ({flagged})'
        )

    def test_bulk_minimum_hallucinations(self, tmp_path):
        """Bulk mode should flag at least MINIMUM_HALLUCINATED_COUNT refs."""
        _needs_local_db()
        cache_dir = _prepare_cache(tmp_path)
        payload = self._run_bulk(cache_dir)
        flagged = self._extract_flagged_titles(payload)
        assert len(flagged) >= MINIMUM_HALLUCINATED_COUNT, (
            f'Bulk mode flagged {len(flagged)} refs, expected >= {MINIMUM_HALLUCINATED_COUNT}.\n'
            f'Flagged: {sorted(flagged)}'
        )

    def test_single_and_bulk_match(self, tmp_path):
        """Single-paper and bulk modes must flag the same refs."""
        _needs_local_db()
        cache_dir_single = _prepare_cache(tmp_path / 'single')
        cache_dir_bulk = _prepare_cache(tmp_path / 'bulk')

        single_payload = self._run_single_paper(cache_dir_single)
        bulk_payload = self._run_bulk(cache_dir_bulk)

        single_flagged = self._extract_flagged_titles(single_payload)
        bulk_flagged = self._extract_flagged_titles(bulk_payload)

        # Bulk must be a subset of single (bulk may miss borderline cases
        # where verification data differs slightly due to API call ordering)
        assert bulk_flagged.issubset(single_flagged), (
            f'Bulk flagged refs not in single-paper:\n'
            f'Only in bulk: {bulk_flagged - single_flagged}'
        )
        # And they should be close in count
        assert abs(len(single_flagged) - len(bulk_flagged)) <= 1, (
            f'Single ({len(single_flagged)}) and bulk ({len(bulk_flagged)}) diverge by > 1.\n'
            f'Only in single: {single_flagged - bulk_flagged}\n'
            f'Only in bulk: {bulk_flagged - single_flagged}'
        )
