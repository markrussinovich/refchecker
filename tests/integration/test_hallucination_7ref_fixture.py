"""Integration test for the 7-reference hallucination triage fixture.

Fixture composition:
    1 accurate reference      — should verify cleanly (no record emitted)
    3 minor-issue references  — real papers with year/author/venue errors
    3 hallucinated references — completely fabricated, documented LLM patterns

Note: Hallucination detection requires an LLM to be configured.
When LLM is disabled, no hallucination flags are produced.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.core.refchecker import ArxivReferenceChecker

FIXTURE_PATH = Path(__file__).resolve().parents[1] / 'fixtures' / 'hallucination_7ref_sample.bib'

HALLUCINATED_TITLES = {
    'Efficient Neural Network Pruning Using Iterative Sparse Retraining',
    'Reinforcement Learning with Adversarial Networks',
    'Self-Organizing Transformers for Cross-domain Representation Learning',
}


@pytest.mark.integration
@pytest.mark.network
class TestHallucination7RefFixture:
    """Verify reference checking processes all 7 references in the fixture."""

    def test_fixture_processes_all_references(self, temp_dir):
        """All 7 references should be processed and issues detected."""
        report_path = temp_dir / 'hallucination_7ref_report.json'

        checker = ArxivReferenceChecker(
            llm_config={'disabled': True},
            report_file=str(report_path),
            report_format='json',
        )

        checker.run(local_pdf_path=str(FIXTURE_PATH))

        payload = json.loads(report_path.read_text(encoding='utf-8'))
        summary = payload['summary']
        records = payload['records']

        # All 7 references should be processed
        assert summary['total_references_processed'] == 7

        # Without LLM, no hallucination flags are produced
        assert summary['flagged_records'] == 0

        # But the 3 fabricated refs should still be unverified
        unverified = [r for r in records if r.get('error_type') == 'unverified'
                      or (r.get('error_type') == 'multiple' and 'unverified' in r.get('error_details', '').lower())]
        unverified_titles = {r['ref_title'] for r in unverified}
        assert HALLUCINATED_TITLES.issubset(unverified_titles)

    def test_csv_report_includes_hallucination_columns(self, temp_dir):
        """CSV report should always include hallucination columns."""
        import csv

        report_path = temp_dir / 'hallucination_7ref_report.csv'

        checker = ArxivReferenceChecker(
            llm_config={'disabled': True},
            report_file=str(report_path),
            report_format='csv',
        )

        checker.run(local_pdf_path=str(FIXTURE_PATH))

        with open(report_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        required_columns = {'hallucination_verdict', 'hallucination_explanation'}
        assert required_columns.issubset(set(reader.fieldnames))
        assert len(rows) >= 3  # At least the 3 fabricated + some real with issues
