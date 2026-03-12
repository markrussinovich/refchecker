import csv

from refchecker.core.hallucination_policy import assess_hallucination_candidate
from refchecker.core.report_builder import ReportBuilder
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


def test_operational_unverified_issue_is_not_candidate():
    entry = {
        'error_type': 'unverified',
        'error_details': 'GitHub API rate limit exceeded',
        'ref_title': 'Scaling Laws for Neural Language Models in Realistic Training Regimes',
        'ref_authors_cited': 'Author One, Author Two',
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is False
    assert result['level'] == 'none'
    assert result['score'] == 0.0
    assert 'verification_infrastructure_issue' in result['reasons']


def test_url_reference_only_unverified_issue_is_not_candidate():
    entry = {
        'error_type': 'unverified',
        'error_details': "paper not verified but URL references paper",
        'ref_title': 'A Real Project Page',
        'ref_authors_cited': 'Author One',
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is False
    assert result['level'] == 'none'
    assert 'verification_infrastructure_issue' in result['reasons']


def test_api_failure_is_not_candidate():
    entry = {
        'error_type': 'api_failure',
        'error_details': 'Semantic Scholar API failed: temporary outage',
        'ref_title': 'Another Real Paper',
        'ref_authors_cited': 'Author One, Author Two',
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is False
    assert result['level'] == 'none'
    assert result['score'] == 0.0
    assert result['reasons'] == ['verification_infrastructure_issue']


def test_multi_source_negative_boosts_score_to_high():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Could not verify reference using any available API',
        'ref_title': 'Efficient Neural Network Pruning Using Iterative Sparse Retraining',
        'ref_authors_cited': 'Shuang Li, Yifan Chen',
        'sources_checked': 4,
        'sources_negative': 4,
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is True
    assert result['level'] == 'high'
    assert result['score'] >= 0.85
    assert 'multi_source_negative_very_high' in result['reasons']


def test_three_source_negative_gives_high_boost():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Could not verify reference using any available API',
        'ref_title': 'Some Fabricated Paper Title That Does Not Exist Anywhere',
        'ref_authors_cited': 'Author One, Author Two',
        'sources_checked': 3,
        'sources_negative': 3,
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is True
    assert result['score'] == 0.8
    assert 'multi_source_negative_high' in result['reasons']


def test_two_source_negative_gives_moderate_boost():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Could not verify reference using any available API',
        'ref_title': 'Some Fabricated Paper Title That Does Not Exist',
        'ref_authors_cited': 'Author One, Author Two',
        'sources_checked': 3,
        'sources_negative': 2,
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is True
    assert result['level'] in {'medium', 'high'}
    assert 'multi_source_negative' in result['reasons']


def test_no_source_tracking_preserves_existing_behavior():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Scaling Laws for Neural Language Models in Realistic Training Regimes',
        'ref_authors_cited': 'Author One, Author Two',
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is True
    assert result['level'] in {'medium', 'high'}
    assert result['score'] == 0.65
    assert 'multi_source_negative' not in result['reasons']


def test_arxiv_year_conflict_boosts_score():
    """ArXiv ID 2402.xxxxx implies 2024, but citation claims 2019 — major conflict."""
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Some Fabricated Paper About Transformers',
        'ref_authors_cited': 'Author One',
        'ref_url_cited': 'https://arxiv.org/abs/2402.12345',
        'ref_year_cited': '2019',
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is True
    assert 'arxiv_year_conflict' in result['reasons']
    assert result['score'] >= 0.9


def test_arxiv_year_off_by_one_is_minor():
    """Off-by-one year is common (Dec submission → Jan publication)."""
    entry = {
        'error_type': 'year',
        'error_details': 'Year mismatch: cited 2023, actual 2024',
        'ref_title': 'A Real Paper With Minor Year Error',
        'ref_authors_cited': 'Author One',
        'ref_url_cited': 'https://arxiv.org/abs/2312.12345',
        'ref_year_cited': '2024',
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is False
    assert 'arxiv_year_conflict' not in result['reasons']


def test_arxiv_year_consistency_no_arxiv_id():
    """References without arXiv IDs should not trigger this check."""
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'A Paper Without ArXiv ID',
        'ref_authors_cited': 'Author One, Author Two',
        'ref_url_cited': '',
        'ref_year_cited': '2019',
    }

    result = assess_hallucination_candidate(entry)

    assert 'arxiv_year_conflict' not in result['reasons']
    assert 'arxiv_year_minor_conflict' not in result['reasons']


def test_high_buzzword_density_boosts_score():
    """Title with high ML buzzword density should get a score boost."""
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Self-Organizing Transformers for Cross-domain Representation Learning',
        'ref_authors_cited': 'Author One, Author Two',
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is True
    assert 'high_buzzword_density' in result['reasons'] or 'moderate_buzzword_density' in result['reasons']
    assert result['score'] > 0.65


def test_specific_title_no_buzzword_penalty():
    """A specific, non-generic title should not trigger buzzword density."""
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding',
        'ref_authors_cited': 'Author One, Author Two',
    }

    result = assess_hallucination_candidate(entry)

    # BERT is specific enough; buzzword density should be moderate at most
    assert 'high_buzzword_density' not in result['reasons']


def test_rich_author_list_boosts_unverified_score():
    """3+ authors on an unverifiable paper is a Frankenstein signal."""
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Reinforcement Learning with Adversarial Networks',
        'ref_authors_cited': 'Ian Goodfellow, Samy Bengio, Yann LeCun',
    }

    result = assess_hallucination_candidate(entry)

    assert result['candidate'] is True
    assert 'rich_author_list_unverified' in result['reasons']


def test_single_author_no_rich_list_signal():
    """Single-author unverified ref should not trigger rich_author_list."""
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Some Fabricated Paper Title That Does Not Exist',
        'ref_authors_cited': 'Single Author',
    }

    result = assess_hallucination_candidate(entry)

    assert 'rich_author_list_unverified' not in result['reasons']


def test_paper_rollups_group_flagged_records_by_source_paper():
    rb = ReportBuilder()
    errors = [
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

    records = rb.build_structured_report_records(errors)
    paper_rollups = rb.build_paper_rollups(records)

    assert len(paper_rollups) == 2
    assert paper_rollups[0]['source_paper_id'] == 'ZG3RaNIsO8'
    assert paper_rollups[0]['total_records'] == 2
    assert paper_rollups[0]['flagged_records'] == 1
    assert paper_rollups[1]['source_paper_id'] == 'fB0hRu9GZUS'
    assert paper_rollups[1]['flagged_records'] == 1


def test_write_structured_report_csv_flattens_hallucination_assessment(tmp_path):
    report_file = str(tmp_path / 'hallucination_report.csv')
    rb = ReportBuilder(
        report_file=report_file,
        report_format='csv',
    )
    errors = [
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
    stats = {
        'total_papers_processed': 1,
        'total_references_processed': 4,
        'total_errors_found': 1,
        'total_warnings_found': 0,
        'total_info_found': 0,
        'total_unverified_refs': 1,
    }

    payload = rb.build_structured_report_payload(errors, stats)
    rb.write_structured_report(payload)

    with open(report_file, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]['source_paper_id'] == 'ZG3RaNIsO8'
    assert rows[0]['hallucination_candidate'] == 'True'
    assert rows[0]['hallucination_level'] in {'medium', 'high'}
    assert 'unverified' in rows[0]['hallucination_reasons']


def test_build_hallucination_console_lines_summarizes_flagged_papers():
    rb = ReportBuilder()
    errors = [
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
    stats = {
        'total_papers_processed': 3,
        'total_references_processed': 7,
        'total_errors_found': 2,
        'total_warnings_found': 0,
        'total_info_found': 0,
        'total_unverified_refs': 2,
    }

    payload = rb.build_structured_report_payload(errors, stats)
    lines = rb.build_hallucination_console_lines(payload)
    output = '\n'.join(lines)

    assert 'HALLUCINATION CANDIDATES' in output
    assert 'Flagged references: 2' in output
    assert 'Paper One' in output
    assert 'Paper Two' in output
    assert 'Paper Three' not in output
