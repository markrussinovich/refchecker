"""Tests for hallucination policy pre-filter and LLM-based assessment."""

import csv

from unittest.mock import MagicMock

from refchecker.core.hallucination_policy import (
    build_hallucination_error_entry,
    check_author_hallucination,
    detect_name_order_warning,
    run_hallucination_check,
    should_check_hallucination,
    _compute_author_overlap,
    _strip_team_names,
)
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


def test_build_hallucination_entry_keeps_authors_for_arxiv_id():
    raw_errors = [{
        'error_type': 'arxiv_id',
        'error_details': "Incorrect ArXiv ID: paper 'Open3DVQA' does not have ArXiv ID 2503.11094",
        'ref_authors_correct': 'Weichen Zhan, Zile Zhou, Zhiheng Zheng',
    }]
    reference = {
        'title': 'Open3dvqa: A benchmark for comprehensive spatial reasoning with multi-modal large language model in open space',
        'authors': ['Weichen Zhan', 'Zile Zhou', 'Zhiheng Zheng'],
        'year': 2025,
        'url': 'https://arxiv.org/abs/2503.11094',
        'venue': '',
    }

    entry = build_hallucination_error_entry(
        raw_errors,
        reference,
        verified_url='https://api.semanticscholar.org/CorpusID:282593059',
    )

    assert entry is not None
    assert entry['ref_authors_correct'] == 'Weichen Zhan, Zile Zhou, Zhiheng Zheng'


def test_verified_arxiv_id_conflict_with_high_author_overlap_should_not_be_checked():
    entry = {
        'error_type': 'arxiv_id',
        'error_details': "Incorrect ArXiv ID: paper 'Open3DVQA: A Benchmark for Comprehensive Spatial Reasoning with Multimodal Large Language Model in Open Space' does not have ArXiv ID 2503.11094",
        'ref_title': 'Open3dvqa: A benchmark for comprehensive spatial reasoning with multi-modal large language model in open space',
        'ref_authors_cited': 'Weichen Zhan, Zile Zhou, Zhiheng Zheng, Chen Gao, Jinqiang Cui, Yong Li, Xinlei Chen, Xiao-Ping Zhang',
        'ref_authors_correct': 'Weichen Zhan, Zile Zhou, Zhiheng Zheng, Chen Gao, Jinqiang Cui, Yong Li, Xinlei Chen, Xiao-Ping Zhang',
        'ref_verified_url': 'https://api.semanticscholar.org/CorpusID:282593059',
        'ref_url_cited': 'https://arxiv.org/abs/2503.11094',
    }

    assert should_check_hallucination(entry) is False


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


def test_github_verified_author_mismatch_should_be_checked():
    """GitHub-verified refs with author mismatch (org name vs real authors) need LLM check.

    When a GitHub checker verifies the repo exists but returns the org owner
    as "author" (e.g. 'mll-lab-nu'), and the cited reference lists 16 real
    authors, the mismatch cannot be resolved without LLM assessment.
    Regression test for commit c28a010.
    """
    entry = {
        'error_type': 'author',
        'error_details': 'Author mismatch:\n'
                         'cited:  Kangrui Wang, Pingyue Zhang, Zihan Wang\n'
                         'actual: mll-lab-nu (mll-lab-nu)',
        'ref_title': 'Reinforcing visual state reasoning for multi-turn vlm agents',
        'ref_authors_cited': 'Kangrui Wang, Pingyue Zhang, Zihan Wang',
        'ref_url_cited': 'https://github.com/RAGEN-AI/VAGEN',
        'ref_verified_url': 'https://github.com/RAGEN-AI/VAGEN',
    }
    assert should_check_hallucination(entry) is True


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


def test_url_error_should_be_checked():
    """References with a broken/wrong URL (error_type='url') should be hallucination candidates."""
    entry = {
        'error_type': 'url',
        'error_details': 'Non-existent web page: https://example.com/fake',
        'ref_title': 'Language-guided reinforcement learning for explainable agents',
        'ref_authors_cited': 'Yuxuan Jiang, Hongyuan Zha',
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


# ------------------------------------------------------------------
# Name-order swap detection
# ------------------------------------------------------------------

def test_name_order_swap_detected_as_unlikely():
    """LastName FirstName vs FirstName LastName should be UNLIKELY (warning)."""
    entry = {
        'error_type': 'author',
        'ref_title': 'Words or vision: Do vision-language models have blind faith in text',
        'ref_authors_cited': 'Deng Ailin, Cao Tri, Chen Zhirui, Hooi Bryan',
        'ref_authors_correct': 'Ailin Deng, Tri Cao, Zhirui Chen, Bryan Hooi',
        'ref_verified_url': 'https://api.semanticscholar.org/CorpusID:12345',
    }
    result = detect_name_order_warning(entry)
    assert result is not None
    assert result['verdict'] == 'UNLIKELY'
    assert 'order' in result['explanation'].lower()


def test_name_order_swap_not_triggered_for_different_people():
    """Completely different authors should not be flagged as name-order swap."""
    entry = {
        'error_type': 'author',
        'ref_title': 'Some paper title that is long enough for the check',
        'ref_authors_cited': 'Junyi Chen, Shuming Shen, Andi Chen, Wen Wu',
        'ref_authors_correct': 'Junyi Ao, Rui Wang, Long Zhou, Shujie Liu',
    }
    result = detect_name_order_warning(entry)
    assert result is None


def test_name_order_swap_integrated_in_run_hallucination_check():
    """run_hallucination_check should return UNLIKELY for name-order swaps."""
    entry = {
        'error_type': 'author',
        'ref_title': 'Multi-modal hallucination control by visual information grounding',
        'ref_authors_cited': 'Favero Alessandro, Zancato Luca, Trager Matthew',
        'ref_authors_correct': 'Alessandro Favero, Luca Zancato, Matthew Trager',
        'ref_verified_url': 'https://example.com/paper',
    }
    result = run_hallucination_check(entry, llm_client=None)
    assert result is not None
    assert result['verdict'] == 'UNLIKELY'


# ------------------------------------------------------------------
# Team-name stripping in author overlap
# ------------------------------------------------------------------

def test_team_name_stripped_from_cited_authors():
    """Team names like 'DeepSeek-AI' should be stripped before overlap."""
    overlap = _compute_author_overlap(
        'DeepSeek-AI, Xiao Bi, Deli Chen, Guanting Chen',
        'DeepSeek-AI Xiao Bi, Deli Chen, Guanting Chen',
    )
    assert overlap is not None
    assert overlap >= 0.9


def test_qwen_team_name_stripped():
    """Qwen team prefix should be stripped."""
    overlap = _compute_author_overlap(
        'Qwen, An Yang, Baosong Yang, Beichen Zhang',
        'Qwen An Yang, Baosong Yang, Beichen Zhang',
    )
    assert overlap is not None
    assert overlap >= 0.9


def test_strip_team_names_function():
    """_strip_team_names should remove known team names and handle DB concatenation."""
    result = _strip_team_names(['DeepSeek-AI', 'Xiao Bi', 'Deli Chen'])
    assert result == ['Xiao Bi', 'Deli Chen']

    result2 = _strip_team_names(['Qwen An Yang', 'Baosong Yang'])
    assert result2 == ['An Yang', 'Baosong Yang']


def test_team_name_does_not_affect_genuine_mismatch():
    """Team name stripping should not mask genuinely fabricated authors."""
    overlap = _compute_author_overlap(
        'Qwen, Fake Author One, Fake Author Two, Fake Author Three',
        'Qwen An Yang, Baosong Yang, Beichen Zhang',
    )
    assert overlap is not None
    assert overlap < 0.2  # Genuinely different authors


# ------------------------------------------------------------------
# Verified ref with fabricated authors — hallucination detection
# ------------------------------------------------------------------

def test_verified_ref_zero_overlap_flagged_as_likely():
    """A verified ref with 0% author overlap should be LIKELY hallucinated."""
    entry = {
        'error_type': 'multiple',
        'error_details': 'Author 1 mismatch',
        'ref_title': 'Speecht5: Unified-modal encoder-decoder pre-training',
        'ref_authors_cited': 'Junyi Chen, Shuming Shen, Andi Chen, Wen Wu, Jiantao Kang, Haohe Li',
        'ref_authors_correct': 'Junyi Ao, Rui Wang, Long Zhou, Shujie Liu, Shuo Ren, Yu Wu',
        'ref_verified_url': 'https://api.semanticscholar.org/CorpusID:238856828',
    }
    result = run_hallucination_check(entry, llm_client=None)
    assert result is not None
    assert result['verdict'] == 'LIKELY'


def test_verified_ref_high_overlap_not_flagged():
    """A verified ref with good author overlap should not be flagged."""
    entry = {
        'error_type': 'author',
        'error_details': 'Year mismatch',
        'ref_title': 'Attention Is All You Need: A Long Title For Testing',
        'ref_authors_cited': 'Ashish Vaswani, Noam Shazeer, Niki Parmar',
        'ref_authors_correct': 'Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit',
        'ref_verified_url': 'https://arxiv.org/abs/1706.03762',
    }
    result = run_hallucination_check(entry, llm_client=None)
    assert result is None  # No hallucination for well-matching authors


# ------------------------------------------------------------------
# LLM override behavior
# ------------------------------------------------------------------

def test_deterministic_likely_is_final():
    """When deterministic author-overlap returns LIKELY, the LLM is NOT called.

    All three paths (CLI, Batch, WebUI) now treat a deterministic LIKELY as
    final — the LLM is only invoked when deterministic screening is
    inconclusive ('needs_llm').
    """
    entry = {
        'error_type': 'multiple',
        'error_details': 'Author mismatch',
        'ref_title': 'Fairness in machine learning: a survey with some extra words',
        'ref_authors_cited': 'Solon Barocas, Moritz Hardt, Arvind Narayanan',
        'ref_authors_correct': 'L. Oneto, S. Chiappa',
        'ref_verified_url': 'https://api.semanticscholar.org/CorpusID:12345',
    }
    mock_llm = MagicMock()
    mock_llm.available = True
    mock_llm.assess.return_value = {
        'verdict': 'UNLIKELY',
        'explanation': 'Paper found: NeurIPS 2017 tutorial by Barocas and Hardt.',
        'web_search': None,
    }
    result = run_hallucination_check(entry, llm_client=mock_llm)
    assert result['verdict'] == 'LIKELY'  # deterministic is final
    mock_llm.assess.assert_not_called()  # LLM never invoked


def test_llm_likely_overrides_no_deterministic():
    """When deterministic check returns None but LLM says LIKELY, use LLM."""
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'A totally fabricated paper that does not exist anywhere',
        'ref_authors_cited': 'Fake Author One, Fake Author Two, Fake Author Three',
    }
    mock_llm = MagicMock()
    mock_llm.available = True
    mock_llm.assess.return_value = {
        'verdict': 'LIKELY',
        'explanation': 'No paper with this title exists.',
        'web_search': None,
    }
    result = run_hallucination_check(entry, llm_client=mock_llm)
    assert result['verdict'] == 'LIKELY'


def test_verified_arxiv_id_high_overlap_skips_llm():
    entry = {
        'error_type': 'arxiv_id',
        'error_details': "Incorrect ArXiv ID: paper 'Open3DVQA: A Benchmark for Comprehensive Spatial Reasoning with Multimodal Large Language Model in Open Space' does not have ArXiv ID 2503.11094",
        'ref_title': 'Open3dvqa: A benchmark for comprehensive spatial reasoning with multi-modal large language model in open space',
        'ref_authors_cited': 'Weichen Zhan, Zile Zhou, Zhiheng Zheng, Chen Gao, Jinqiang Cui, Yong Li, Xinlei Chen, Xiao-Ping Zhang',
        'ref_authors_correct': 'Weichen Zhan, Zile Zhou, Zhiheng Zheng, Chen Gao, Jinqiang Cui, Yong Li, Xinlei Chen, Xiao-Ping Zhang',
        'ref_verified_url': 'https://api.semanticscholar.org/CorpusID:282593059',
        'ref_url_cited': 'https://arxiv.org/abs/2503.11094',
    }
    mock_llm = MagicMock()
    mock_llm.available = True

    result = run_hallucination_check(entry, llm_client=mock_llm)

    assert result is None
    mock_llm.assess.assert_not_called()


# ------------------------------------------------------------------
# enhanced_name_match: reversed name order
# ------------------------------------------------------------------

def test_enhanced_name_match_reversed_order():
    """enhanced_name_match should handle FirstName/LastName reversal."""
    from refchecker.utils.text_utils import enhanced_name_match
    assert enhanced_name_match('Deng Ailin', 'Ailin Deng') is True
    assert enhanced_name_match('Liu Zhuang', 'Zhuang Liu') is True
    assert enhanced_name_match('Favero Alessandro', 'Alessandro Favero') is True
    # Different people should still not match
    assert enhanced_name_match('John Smith', 'Jane Doe') is False
