"""Tests for hallucination policy pre-filter and LLM-based assessment."""

import csv

from refchecker.core.hallucination_policy import check_author_hallucination, should_check_hallucination
from refchecker.core.report_builder import ReportBuilder


# ------------------------------------------------------------------
# Pre-filter tests (should_check_hallucination)
# ------------------------------------------------------------------

def test_unverified_reference_should_be_checked():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Scaling Laws for Neural Language Models in Realistic Training Regimes',
        'ref_authors_cited': 'Author One, Author Two',
    }
    assert should_check_hallucination(entry) is True


def test_year_only_issue_should_not_be_checked():
    entry = {
        'error_type': 'year',
        'error_details': 'Year mismatch: cited 2024, actual 2023',
        'ref_title': 'A Real Paper',
        'ref_authors_cited': 'Author One',
    }
    assert should_check_hallucination(entry) is False


def test_arxiv_id_conflict_should_be_checked():
    entry = {
        'error_type': 'arxiv_id',
        'error_details': 'ArXiv ID mismatch: cited as 1111.1111 but actually 2222.2222',
        'ref_title': 'Another Paper Title',
        'ref_authors_cited': 'Author One, Author Two',
    }
    assert should_check_hallucination(entry) is True


def test_venue_only_issue_should_not_be_checked():
    entry = {
        'error_type': 'venue',
        'error_details': 'Venue mismatch',
        'ref_title': 'Real Paper With Wrong Venue',
        'ref_authors_cited': 'Author One',
    }
    assert should_check_hallucination(entry) is False


def test_api_failure_should_not_be_checked():
    entry = {
        'error_type': 'api_failure',
        'error_details': 'Rate limit exceeded',
        'ref_title': 'Some Paper',
        'ref_authors_cited': 'Author One',
    }
    assert should_check_hallucination(entry) is False


def test_multiple_with_title_mismatch_should_be_checked():
    entry = {
        'error_type': 'multiple',
        'error_details': '- title mismatch\n- author mismatch',
        'ref_title': 'Paper With Multiple Issues',
        'ref_authors_cited': 'Author One',
    }
    assert should_check_hallucination(entry) is True


def test_multiple_with_only_year_venue_should_not_be_checked():
    entry = {
        'error_type': 'multiple',
        'error_details': '- year mismatch\n- venue mismatch',
        'ref_title': 'Paper With Minor Issues',
        'ref_authors_cited': 'Author One',
    }
    assert should_check_hallucination(entry) is False


def test_short_title_should_not_be_checked():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Short',
        'ref_authors_cited': 'Author One',
    }
    assert should_check_hallucination(entry) is False


def test_doi_conflict_should_be_checked():
    entry = {
        'error_type': 'doi',
        'error_details': 'DOI points to different paper',
        'ref_title': 'Paper With DOI Conflict That Is Long Enough',
        'ref_authors_cited': 'Author One',
    }
    assert should_check_hallucination(entry) is True


# ------------------------------------------------------------------
# Author overlap tests (check_author_hallucination)
# ------------------------------------------------------------------

def test_two_authors_one_wrong_should_not_flag_hallucination():
    """With only 2 cited authors and 1 matching, it's a normal citation error."""
    entry = {
        'ref_authors_cited': 'Smith, Wrong Author',
        'ref_authors_correct': 'Smith, Jones',
    }
    assert check_author_hallucination(entry) is None


def test_two_authors_none_matching_should_flag_hallucination():
    """With 2 cited authors and 0 matching, it may be hallucinated."""
    entry = {
        'ref_authors_cited': 'Fake One, Fake Two',
        'ref_authors_correct': 'Smith, Jones, Lee',
    }
    result = check_author_hallucination(entry)
    assert result is not None
    assert result['verdict'] == 'LIKELY'


def test_many_authors_low_overlap_should_flag_hallucination():
    """With many cited authors and low overlap, flag hallucination."""
    entry = {
        'ref_authors_cited': 'Fake A, Fake B, Fake C, Smith',
        'ref_authors_correct': 'Smith, Jones, Lee, Chen',
    }
    result = check_author_hallucination(entry)
    assert result is not None
    assert result['verdict'] == 'LIKELY'


# ------------------------------------------------------------------
# URL tests (references with cited URLs should not be hallucination-checked)
# ------------------------------------------------------------------

def test_reference_with_url_should_not_be_checked():
    """Verified references (non-unverified error type) with a URL are not hallucination candidates."""
    entry = {
        'error_type': 'author',
        'error_details': 'Author mismatch',
        'ref_title': 'Fair learning',
        'ref_authors_cited': 'Mark A. Lemley, Bryan Casey',
        'ref_url_cited': 'https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3528447',
    }
    assert should_check_hallucination(entry) is False


def test_web_resource_with_url_should_not_be_checked():
    """Verified web resources with a URL are not hallucination candidates."""
    entry = {
        'error_type': 'venue',
        'error_details': 'Venue mismatch',
        'ref_title': 'Common Crawl',
        'ref_authors_cited': 'Common Crawl Foundation',
        'ref_url_cited': 'https://commoncrawl.org/',
    }
    assert should_check_hallucination(entry) is False


def test_huggingface_dataset_should_not_be_checked():
    """Verified references pointing to Hugging Face datasets are not hallucination candidates."""
    entry = {
        'error_type': 'author',
        'error_details': 'Author mismatch',
        'ref_title': 'OpenManus-RL Dataset',
        'ref_authors_cited': 'CharlieDreemur',
        'ref_url_cited': 'https://huggingface.co/datasets/CharlieDreemur/OpenManus-RL',
    }
    assert should_check_hallucination(entry) is False


def test_unverified_with_url_should_be_checked():
    """Unverified references WITH a URL should be checked — the URL didn't help verify it."""
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Knowledge-based reinforcement learning: A survey',
        'ref_authors_cited': 'Reinaldo A. C. Bianchi, Luis A. Celiberto Jr',
        'ref_url_cited': 'https://jair.org/index.php/jair/article/view/11182',
    }
    assert should_check_hallucination(entry) is True


def test_no_url_unverified_should_be_checked():
    """Unverified references with NO URL should still be checked."""
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'A Suspicious Paper About Neural Networks',
        'ref_authors_cited': 'John Fakename, Jane Fakename',
        'ref_url_cited': '',
    }
    assert should_check_hallucination(entry) is True


# ------------------------------------------------------------------
# ReportBuilder integration (no LLM configured = no assessment)
# ------------------------------------------------------------------

def test_report_builder_no_llm_skips_assessment():
    """Without an LLM, no hallucination_assessment should be added."""
    rb = ReportBuilder()
    errors = [{
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Suspicious Reference One',
        'ref_authors_cited': 'Author X, Author Y',
    }]
    records = rb.build_structured_report_records(errors)
    assert len(records) == 1
    assert 'hallucination_assessment' not in records[0]


def test_paper_rollups_count_likely_verdicts():
    """Rollups should count records with verdict=LIKELY as flagged."""
    rb = ReportBuilder()
    records = [
        {
            'source_paper_id': 'paper-1',
            'source_title': 'Paper One',
            'source_authors': 'Author A',
            'source_year': 2024,
            'source_url': 'https://example.org/paper-1',
            'error_type': 'unverified',
            'ref_title': 'Fake Reference',
            'hallucination_assessment': {'verdict': 'LIKELY', 'explanation': 'Fabricated.'},
        },
        {
            'source_paper_id': 'paper-1',
            'source_title': 'Paper One',
            'source_authors': 'Author A',
            'source_year': 2024,
            'source_url': 'https://example.org/paper-1',
            'error_type': 'year',
            'ref_title': 'Real Reference',
        },
    ]
    rollups = rb.build_paper_rollups(records)
    assert len(rollups) == 1
    assert rollups[0]['flagged_records'] == 1
    assert rollups[0]['total_records'] == 2


def test_write_csv_includes_hallucination_columns(tmp_path):
    report_file = str(tmp_path / 'report.csv')
    rb = ReportBuilder(report_file=report_file, report_format='csv')
    errors = [{
        'source_paper_id': 'test',
        'source_title': 'Test Paper',
        'source_authors': 'Author A',
        'source_year': 2024,
        'source_url': 'https://example.org',
        'ref_title': 'Some Reference',
        'ref_authors_cited': 'Author X',
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
    }]
    stats = {
        'total_papers_processed': 1,
        'total_references_processed': 1,
        'total_errors_found': 0,
        'total_warnings_found': 0,
        'total_info_found': 0,
        'total_unverified_refs': 1,
    }
    payload = rb.build_structured_report_payload(errors, stats)
    rb.write_structured_report(payload)

    with open(report_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert 'hallucination_verdict' in reader.fieldnames
    assert 'hallucination_explanation' in reader.fieldnames
    assert len(rows) == 1


def test_summary_counts_likely_verdicts():
    rb = ReportBuilder()
    errors = [
        {
            'source_paper_id': 'p1', 'source_title': 'P', 'source_authors': 'A',
            'source_year': 2024, 'source_url': 'u',
            'error_type': 'unverified', 'error_details': 'not found',
            'ref_title': 'Fake Ref', 'ref_authors_cited': 'X',
        },
    ]
    stats = {
        'total_papers_processed': 1, 'total_references_processed': 5,
        'total_errors_found': 0, 'total_warnings_found': 0,
        'total_info_found': 0, 'total_unverified_refs': 1,
    }
    # Without LLM, no flagged records
    payload = rb.build_structured_report_payload(errors, stats)
    assert payload['summary']['flagged_records'] == 0
