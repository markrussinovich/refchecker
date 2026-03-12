"""Integration test for a mixed real-plus-hallucinated citation fixture."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.core.refchecker import ArxivReferenceChecker


class TestHallucinationMixedFixture:
    """Verify that hallucination mode flags the fake citation in a mixed fixture."""

    def test_mixed_bib_fixture_flags_only_fake_reference(self, temp_dir):
        fixture_path = Path(__file__).resolve().parents[1] / 'fixtures' / 'hallucination_mixed_sample.bib'
        report_path = temp_dir / 'hallucination_report.json'

        checker = ArxivReferenceChecker(
            llm_config={'disabled': True},
            report_file=str(report_path),
            report_format='json',
        )

        checker.run(local_pdf_path=str(fixture_path))

        payload = json.loads(report_path.read_text(encoding='utf-8'))
        summary = payload['summary']
        records = payload['records']

        assert summary['total_papers_processed'] == 1
        assert summary['total_references_processed'] == 4
        assert summary['flagged_records'] == 1
        assert summary['flagged_papers'] == 1

        # All records are now included; filter to flagged only for assertion
        flagged = [r for r in records if r.get('hallucination_assessment', {}).get('candidate')]
        assert len(flagged) == 1

        record = flagged[0]
        assert record['source_title'] == 'Hallucination Mixed Sample'
        assert record['ref_title'] == 'Hallucinated Coconut Reasoning for Quantum Citation Alignment'
        assert record['error_type'] == 'unverified'
        assert record['hallucination_assessment']['candidate'] is True
        assert record['hallucination_assessment']['level'] in {'medium', 'high'}
        assert 'unverified' in record['hallucination_assessment']['reasons']
