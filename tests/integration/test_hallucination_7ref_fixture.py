"""Integration test for the 7-reference hallucination triage fixture.

Fixture composition:
    1 accurate reference      — should verify cleanly (no record emitted)
    3 minor-issue references  — real papers with year/author/venue errors
                                (should NOT be flagged as hallucination candidates)
    3 hallucinated references — completely fabricated, documented LLM patterns
                                (should be flagged as hallucination candidates)
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
    """Verify hallucination mode correctly triages the 7-reference fixture."""

    def test_fixture_flags_only_hallucinated_references(self, temp_dir):
        """All 3 hallucinated refs should be flagged; none of the 4 real refs should be."""
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

        # Exactly 3 should be flagged as hallucination candidates
        assert summary['flagged_records'] == 3

        flagged = [r for r in records if r.get('hallucination_assessment', {}).get('candidate')]
        not_flagged = [r for r in records if not r.get('hallucination_assessment', {}).get('candidate')]

        assert len(flagged) == 3

        # Every flagged record should be one of the hallucinated titles
        flagged_titles = {r['ref_title'] for r in flagged}
        assert flagged_titles == HALLUCINATED_TITLES

        # All flagged records should be unverified with medium+ level
        for record in flagged:
            assessment = record['hallucination_assessment']
            assert assessment['level'] in {'medium', 'high'}
            assert assessment['score'] >= 0.6
            assert 'unverified' in assessment['reasons']
            assert 'rich_metadata_not_found' in assessment['reasons']

        # None of the real references should be flagged
        for record in not_flagged:
            assessment = record.get('hallucination_assessment', {})
            assert assessment.get('candidate') is not True, (
                f"Real reference should not be flagged: {record['ref_title']}"
            )

    def test_all_records_include_hallucination_assessment(self, temp_dir):
        """Every record should include a hallucination_assessment, even non-candidates."""
        report_path = temp_dir / 'hallucination_7ref_all.json'

        checker = ArxivReferenceChecker(
            llm_config={'disabled': True},
            report_file=str(report_path),
            report_format='json',
        )

        checker.run(local_pdf_path=str(FIXTURE_PATH))

        payload = json.loads(report_path.read_text(encoding='utf-8'))
        records = payload['records']

        # All records should have hallucination_assessment
        for record in records:
            assert 'hallucination_assessment' in record, (
                f"Missing hallucination_assessment for: {record.get('ref_title')}"
            )

        # The 3 hallucinated refs must be flagged as candidates
        flagged = [r for r in records if r['hallucination_assessment'].get('candidate')]
        flagged_titles = {r['ref_title'] for r in flagged}
        assert HALLUCINATED_TITLES.issubset(flagged_titles)

    def test_csv_report_contains_hallucination_columns(self, temp_dir):
        """CSV report should always include hallucination assessment columns."""
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

        required_columns = {'hallucination_candidate', 'hallucination_level',
                            'hallucination_score', 'hallucination_reasons'}
        assert required_columns.issubset(set(reader.fieldnames))

        # At least the 3 hallucinated refs must be flagged
        flagged_rows = [row for row in rows if row['hallucination_candidate'] == 'True']
        flagged_titles = {row['ref_title'] for row in flagged_rows}
        assert HALLUCINATED_TITLES.issubset(flagged_titles)

        for row in flagged_rows:
            if row['ref_title'] in HALLUCINATED_TITLES:
                assert row['hallucination_level'] in {'medium', 'high'}
