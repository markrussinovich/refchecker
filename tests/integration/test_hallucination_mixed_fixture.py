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
    """Verify reference checking on a mixed fixture (real + fabricated)."""

    @pytest.mark.skipif(
        not os.environ.get('ANTHROPIC_API_KEY'),
        reason='ANTHROPIC_API_KEY not set',
    )
    def test_mixed_bib_fixture_processes_all_references(self, temp_dir):
        fixture_path = Path(__file__).resolve().parents[1] / 'fixtures' / 'hallucination_mixed_sample.bib'
        report_path = temp_dir / 'hallucination_report.json'

        checker = ArxivReferenceChecker(
            llm_config={'provider': 'anthropic'},
            report_file=str(report_path),
            report_format='json',
        )

        checker.run(local_pdf_path=str(fixture_path))

        payload = json.loads(report_path.read_text(encoding='utf-8'))
        summary = payload['summary']
        records = payload['records']

        assert summary['total_papers_processed'] == 1
        assert summary['total_references_processed'] == 4

        # With Anthropic LLM, the fabricated ref should be flagged
        assert summary['flagged_records'] >= 1

        # The fabricated ref should be unverified
        unverified = [r for r in records if r.get('error_type') == 'unverified']
        unverified_titles = {r['ref_title'] for r in unverified}
        assert 'Hallucinated Coconut Reasoning for Quantum Citation Alignment' in unverified_titles
