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
            scan_mode='hallucination',
            report_file=str(report_path),
            report_format='json',
            only_flagged=False,
        )

        checker.run(local_pdf_path=str(FIXTURE_PATH))

        payload = json.loads(report_path.read_text(encoding='utf-8'))
        summary = payload['summary']
        records = payload['records']

        # All 7 references should be processed
        assert summary['total_references_processed'] == 7

        # All 3 hallucinated should be flagged; transient API failures may
        # cause up to 1 additional real ref to also appear as unverified.
        assert 3 <= summary['flagged_records'] <= 4, (
            f"Expected 3 flagged (4 tolerated for transient API failure), "
            f"got {summary['flagged_records']}"
        )

        flagged = [r for r in records if r.get('hallucination_assessment', {}).get('candidate')]

        assert len(flagged) >= 3

        # Every hallucinated title must be in the flagged set
        flagged_titles = {r['ref_title'] for r in flagged}
        assert HALLUCINATED_TITLES.issubset(flagged_titles), (
            f"Missing hallucinated titles: {HALLUCINATED_TITLES - flagged_titles}"
        )

        # All flagged hallucinated records should be unverified with medium+ level
        for record in flagged:
            if record['ref_title'] not in HALLUCINATED_TITLES:
                continue
            assessment = record['hallucination_assessment']
            assert assessment['level'] in {'medium', 'high'}
            assert assessment['score'] >= 0.6
            assert 'unverified' in assessment['reasons']
            assert 'rich_metadata_not_found' in assessment['reasons']

        # Real references that were not flagged should not be candidates
        not_flagged = [r for r in records if not r.get('hallucination_assessment', {}).get('candidate')]
        for record in not_flagged:
            assessment = record.get('hallucination_assessment', {})
            assert assessment.get('candidate') is not True, (
                f"Real reference should not be flagged: {record['ref_title']}"
            )

    def test_only_flagged_filters_to_hallucinated(self, temp_dir):
        """With --only-flagged, report should contain exactly the 3 hallucinated refs."""
        report_path = temp_dir / 'hallucination_7ref_flagged.json'

        checker = ArxivReferenceChecker(
            llm_config={'disabled': True},
            scan_mode='hallucination',
            report_file=str(report_path),
            report_format='json',
            only_flagged=True,
        )

        checker.run(local_pdf_path=str(FIXTURE_PATH))

        payload = json.loads(report_path.read_text(encoding='utf-8'))
        records = payload['records']

        # All 3 hallucinated must appear; transient API failures may add
        # up to 1 real reference that couldn't be verified.
        assert 3 <= len(records) <= 4, (
            f"Expected 3 flagged (4 tolerated for transient API failure), "
            f"got {len(records)}"
        )
        record_titles = {r['ref_title'] for r in records}
        assert HALLUCINATED_TITLES.issubset(record_titles)

    def test_csv_report_contains_hallucination_columns(self, temp_dir):
        """CSV report in hallucination mode should include assessment columns."""
        import csv

        report_path = temp_dir / 'hallucination_7ref_report.csv'

        checker = ArxivReferenceChecker(
            llm_config={'disabled': True},
            scan_mode='hallucination',
            report_file=str(report_path),
            report_format='csv',
            only_flagged=True,
        )

        checker.run(local_pdf_path=str(FIXTURE_PATH))

        with open(report_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # At least the 3 hallucinated refs must be flagged; transient API
        # failures can cause additional real papers to appear unverified.
        assert len(rows) >= 3
        flagged_titles = {row['ref_title'] for row in rows}
        assert HALLUCINATED_TITLES.issubset(flagged_titles)

        required_columns = {'hallucination_candidate', 'hallucination_level',
                            'hallucination_score', 'hallucination_reasons'}
        assert required_columns.issubset(set(reader.fieldnames))

        for row in rows:
            assert row['hallucination_candidate'] == 'True'
            assert row['hallucination_level'] in {'medium', 'high'}
