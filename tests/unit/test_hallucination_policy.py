import csv

from refchecker.core.hallucination_policy import assess_hallucination_candidate
from refchecker.core.refchecker import ArxivReferenceChecker


def test_unverified_rich_reference_becomes_candidate():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Scaling Laws for Neural Language Models in Realistic Training Regimes',
        'ref_authors_cited': 'Author One, Author Two',
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is True
    assert result['level'] in {'medium', 'high'}
    assert 'unverified' in result['reasons']


def test_year_only_issue_is_not_candidate():
    entry = {
        'error_type': 'year',
        'error_details': 'Year mismatch: cited 2024, actual 2023',
        'ref_title': 'A Real Paper',
        'ref_authors_cited': 'Author One',
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is False
    assert result['level'] in {'none', 'low'}


def test_identifier_conflict_is_high_signal():
    entry = {
        'error_type': 'arxiv_id',
        'error_details': 'ArXiv ID mismatch: cited as 1111.1111 but actually 2222.2222',
        'ref_title': 'Another Paper',
        'ref_authors_cited': 'Author One, Author Two',
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is True
    assert result['level'] in {'medium', 'high'}
    assert 'arxiv_id_conflict' in result['reasons']


def test_paper_rollups_group_flagged_records_by_source_paper():
    checker = object.__new__(ArxivReferenceChecker)
    checker.scan_mode = 'hallucination'
    checker.only_flagged = False
    checker.errors = [
        {
            'source_paper_id': 'ZG3RaNIsO8',
            'source_title': 'Paper One',
            'source_authors': 'Author A',
            'source_year': 2024,
            'source_url': 'https://openreview.net/forum?id=ZG3RaNIsO8',
            'error_type': 'unverified',
            'error_details': 'Reference could not be verified',
            'ref_title': 'Suspicious Reference One',
            'ref_authors_cited': 'Author X, Author Y',
        },
        {
            'source_paper_id': 'ZG3RaNIsO8',
            'source_title': 'Paper One',
            'source_authors': 'Author A',
            'source_year': 2024,
            'source_url': 'https://openreview.net/forum?id=ZG3RaNIsO8',
            'error_type': 'year',
            'error_details': 'Year mismatch',
            'ref_title': 'Benign Reference',
            'ref_authors_cited': 'Author Z',
        },
        {
            'source_paper_id': 'fB0hRu9GZUS',
            'source_title': 'Paper Two',
            'source_authors': 'Author B',
            'source_year': 2023,
            'source_url': 'https://openreview.net/forum?id=fB0hRu9GZUS',
            'error_type': 'arxiv_id',
            'error_details': 'ArXiv ID mismatch',
            'ref_title': 'Suspicious Reference Two',
            'ref_authors_cited': 'Author Q, Author R',
        },
    ]

    records = checker._build_structured_report_records()
    paper_rollups = checker._build_paper_rollups(records)

    assert len(paper_rollups) == 2
    assert paper_rollups[0]['source_paper_id'] == 'ZG3RaNIsO8'
    assert paper_rollups[0]['total_records'] == 2
    assert paper_rollups[0]['flagged_records'] == 1
    assert paper_rollups[1]['source_paper_id'] == 'fB0hRu9GZUS'
    assert paper_rollups[1]['flagged_records'] == 1


def test_write_structured_report_csv_flattens_hallucination_assessment(tmp_path):
    checker = object.__new__(ArxivReferenceChecker)
    checker.scan_mode = 'hallucination'
    checker.only_flagged = True
    checker.report_file = str(tmp_path / 'hallucination_report.csv')
    checker.report_format = 'csv'
    checker.total_papers_processed = 1
    checker.total_references_processed = 4
    checker.total_errors_found = 1
    checker.total_warnings_found = 0
    checker.total_info_found = 0
    checker.total_unverified_refs = 1
    checker.errors = [
        {
            'source_paper_id': 'ZG3RaNIsO8',
            'source_title': 'Paper One',
            'source_authors': 'Author A',
            'source_year': 2024,
            'source_url': 'https://openreview.net/forum?id=ZG3RaNIsO8',
            'ref_title': 'Suspicious Reference One',
            'ref_authors_cited': 'Author X, Author Y',
            'error_type': 'unverified',
            'error_details': 'Reference could not be verified',
        }
    ]

    checker.write_structured_report()

    with open(checker.report_file, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]['source_paper_id'] == 'ZG3RaNIsO8'
    assert rows[0]['hallucination_candidate'] == 'True'
    assert rows[0]['hallucination_level'] in {'medium', 'high'}
    assert 'unverified' in rows[0]['hallucination_reasons']


def test_build_hallucination_console_lines_summarizes_flagged_papers():
    checker = object.__new__(ArxivReferenceChecker)
    checker.scan_mode = 'hallucination'
    checker.only_flagged = False
    checker.total_papers_processed = 3
    checker.total_references_processed = 7
    checker.total_errors_found = 2
    checker.total_warnings_found = 0
    checker.total_info_found = 0
    checker.total_unverified_refs = 2
    checker.errors = [
        {
            'source_paper_id': 'paper-1',
            'source_title': 'Paper One',
            'source_authors': 'Author A',
            'source_year': 2024,
            'source_url': 'https://example.org/paper-1',
            'ref_title': 'Suspicious Reference One',
            'ref_authors_cited': 'Author X, Author Y',
            'error_type': 'unverified',
            'error_details': 'Reference could not be verified',
        },
        {
            'source_paper_id': 'paper-2',
            'source_title': 'Paper Two',
            'source_authors': 'Author B',
            'source_year': 2024,
            'source_url': 'https://example.org/paper-2',
            'ref_title': 'Suspicious Reference Two',
            'ref_authors_cited': 'Author Q, Author R',
            'error_type': 'arxiv_id',
            'error_details': 'ArXiv ID mismatch',
        },
        {
            'source_paper_id': 'paper-3',
            'source_title': 'Paper Three',
            'source_authors': 'Author C',
            'source_year': 2024,
            'source_url': 'https://example.org/paper-3',
            'ref_title': 'Benign Reference',
            'ref_authors_cited': 'Author Z',
            'error_type': 'year',
            'error_details': 'Year mismatch',
        },
    ]

    lines = checker._build_hallucination_console_lines()
    output = '\n'.join(lines)

    assert 'HALLUCINATION TRIAGE' in output
    assert 'Flagged papers: 2' in output
    assert 'Flagged references: 2' in output
    assert 'Paper One' in output
    assert 'Paper Two' in output
    assert 'Paper Three' not in output
