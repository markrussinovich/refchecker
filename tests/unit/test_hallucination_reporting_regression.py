from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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


def test_parallel_applied_hallucination_assessment_is_not_reapplied():
    """Bulk/parallel output and report counts must use the same applied verdict."""
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.report_builder = ReportBuilder()
    checker.errors = []
    checker.total_errors_found = 0
    checker.total_warnings_found = 0
    checker.total_info_found = 0
    checker.total_unverified_refs = 0
    checker._format_paper_authors = lambda paper: 'Source Author'
    checker._get_source_paper_url = lambda paper: 'https://example.com/source'
    checker.extract_arxiv_id_from_url = lambda url: ''
    checker._display_unverified_error_with_subreason = MagicMock()
    checker._display_non_unverified_errors = MagicMock()

    paper = SimpleNamespace(
        title='Source Paper',
        published=SimpleNamespace(year=2026),
        get_short_id=lambda: 'source-paper',
    )
    reference = {
        'title': 'Suspicious Reference',
        'authors': ['Author One'],
        'year': 2025,
        'venue': 'TestConf',
        'url': '',
        'raw_text': '[1] Suspicious Reference',
    }
    errors = [{'error_type': 'unverified', 'error_details': 'Reference could not be verified'}]
    assessment = {'verdict': 'LIKELY', 'explanation': 'No matching paper was found.'}

    with patch(
        'refchecker.core.hallucination_policy.apply_hallucination_verdict',
        side_effect=AssertionError('already-applied parallel verdict should not be reapplied'),
    ) as apply_verdict:
        checker._process_reference_result(
            paper,
            reference,
            errors,
            reference_url=None,
            paper_errors=[],
            unverified_count=0,
            debug_mode=False,
            print_output=False,
            precomputed_hallucination=assessment,
            precomputed_hallucination_applied=True,
        )

    apply_verdict.assert_not_called()
    assert checker.errors[0]['hallucination_assessment'] == assessment
    assert checker.total_unverified_refs == 1