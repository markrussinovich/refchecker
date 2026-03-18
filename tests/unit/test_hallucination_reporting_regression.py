from types import SimpleNamespace
from unittest.mock import patch

from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.core.report_builder import ReportBuilder


def test_inline_hallucination_assessment_updates_target_record_only():
    """Regression: inline hallucination results must be written to the
    current reference record, not whichever record was appended last."""
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.report_builder = SimpleNamespace(llm_verifier=object(), web_searcher=None)

    target_record = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Current suspicious paper',
        'ref_authors_cited': 'Author One, Author Two',
        'ref_url_cited': '',
    }
    trailing_record = {
        'error_type': 'year',
        'error_details': 'Year mismatch',
        'ref_title': 'Later paper',
    }
    checker.errors = [target_record, trailing_record]

    reference = {
        'title': 'Current suspicious paper',
        'authors': ['Author One', 'Author Two'],
        'year': 2024,
        'venue': 'Imaginary Conference',
        'url': '',
    }
    errors = [{'error_type': 'unverified', 'error_details': 'Reference could not be verified'}]
    assessment = {'verdict': 'LIKELY', 'explanation': 'Fabricated reference.'}

    with patch('refchecker.core.hallucination_policy.run_hallucination_check', return_value=assessment):
        checker._run_and_display_hallucination_assessment(
            reference,
            errors,
            debug_mode=False,
            print_output=False,
            error_entry_record=target_record,
        )

    assert target_record['hallucination_assessment'] == assessment
    assert 'hallucination_assessment' not in trailing_record


def test_report_rollups_populate_reason_counts_for_likely_records():
    """Likely hallucination rollups should include concrete reason codes."""
    builder = ReportBuilder()
    records = [{
        'source_paper_id': 'paper-1',
        'source_title': 'Paper One',
        'source_authors': 'Unknown',
        'source_year': 2026,
        'source_url': 'file://paper-1',
        'error_type': 'multiple',
        'error_details': 'Reference could not be verified\nIncorrect ArXiv ID: points to different paper',
        'hallucination_assessment': {
            'verdict': 'LIKELY',
            'explanation': 'Fabricated reference.',
        },
    }]

    rollups = builder.build_paper_rollups(records)

    assert len(rollups) == 1
    assert rollups[0]['max_flag_level'] == 'high'
    assert rollups[0]['reason_counts']['unverified'] == 1
    assert rollups[0]['reason_counts']['identifier_conflict'] == 1


def test_report_rollups_respect_explicit_assessment_level_and_reasons():
    """If an assessment already has structured reasons/level, preserve them."""
    builder = ReportBuilder()
    records = [{
        'source_paper_id': 'paper-2',
        'source_title': 'Paper Two',
        'source_authors': 'Unknown',
        'source_year': 2026,
        'source_url': 'file://paper-2',
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'hallucination_assessment': {
            'verdict': 'LIKELY',
            'level': 'medium',
            'reasons': ['web_search_not_found', 'rich_metadata_not_found'],
            'explanation': 'Fabricated reference.',
        },
    }]

    rollups = builder.build_paper_rollups(records)

    assert len(rollups) == 1
    assert rollups[0]['max_flag_level'] == 'medium'
    assert rollups[0]['reason_counts']['web_search_not_found'] == 1
    assert rollups[0]['reason_counts']['rich_metadata_not_found'] == 1


def test_report_builder_trusts_precomputed_assessment():
    """Pre-computed hallucination assessments should be trusted as-is
    by the report builder — no re-running LLM checks."""
    builder = ReportBuilder()
    record_with_assessment = {
        'source_paper_id': 'paper-3',
        'source_title': 'Paper Three',
        'source_authors': 'Unknown',
        'source_year': 2026,
        'source_url': 'file://paper-3',
        'ref_title': 'Generative Adversarial Nets',
        'error_type': 'multiple',
        'error_details': 'Reference could not be verified',
        'hallucination_assessment': {
            'verdict': 'LIKELY',
            'explanation': 'A web search found nothing.',
            'web_search': None,
        },
    }

    records = builder.build_structured_report_records([record_with_assessment])
    # Assessment is preserved as-is, not re-run
    assert records[0]['hallucination_assessment']['verdict'] == 'LIKELY'
    assert records[0]['hallucination_assessment']['explanation'] == 'A web search found nothing.'