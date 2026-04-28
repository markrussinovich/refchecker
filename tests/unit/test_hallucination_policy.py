"""Tests for hallucination policy pre-filter and LLM-based assessment."""

import csv
import logging

from unittest.mock import MagicMock

from refchecker.core.hallucination_policy import (
    build_hallucination_error_entry,
    check_author_hallucination,
    detect_name_order_warning,
    apply_hallucination_verdict,
    run_hallucination_check,
    should_check_hallucination,
    _compute_author_overlap,
    _strip_team_names,
)
from refchecker.core.report_builder import ReportBuilder
from refchecker.llm.hallucination_verifier import build_assessment_prompt
from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier, normalize_hallucination_model


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


def test_parse_verdict_preserves_found_venue():
    verdict, explanation, link, found_metadata = LLMHallucinationVerifier._parse_verdict(
        'EXPLANATION: The exact paper was found.\n'
        'LINK: https://aclanthology.org/2023.findings-acl.719/\n'
        'FOUND_TITLE: Membership Inference Attacks against Language Models via Neighbourhood Comparison\n'
        'FOUND_AUTHORS: Justus Mattern, Fatemehsadat Mireshghallah\n'
        'FOUND_VENUE: Findings of the Association for Computational Linguistics: ACL 2023\n'
        'FOUND_YEAR: 2023\n'
        'VERDICT: UNLIKELY\n'
    )

    assert verdict == 'UNLIKELY'
    assert explanation == 'The exact paper was found.'
    assert link == 'https://aclanthology.org/2023.findings-acl.719/'
    assert found_metadata['venue'] == 'Findings of the Association for Computational Linguistics: ACL 2023'


def test_anthropic_haiku_model_aliases_normalize_to_versioned_id():
    assert normalize_hallucination_model('anthropic', 'claude-haiku-4.5') == 'claude-haiku-4-5-20251001'
    assert normalize_hallucination_model('anthropic', 'claude-haiku-4-5') == 'claude-haiku-4-5-20251001'
    assert normalize_hallucination_model('anthropic', 'claude-haiku-4-5-20251001') == 'claude-haiku-4-5-20251001'


def test_apply_hallucination_verdict_rechecks_found_venue():
    result = {
        'status': 'error',
        'errors': [],
    }
    reference = {
        'title': 'Membership inference attacks against language models via neighbourhood comparison',
        'authors': ['Justus Mattern', 'Fatemehsadat Mireshghallah'],
        'year': 2023,
        'venue': 'Wrong Venue',
    }
    assessment = {
        'verdict': 'UNLIKELY',
        'explanation': 'The exact paper was found.',
        'link': 'https://aclanthology.org/2023.findings-acl.719/',
        'found_title': 'Membership Inference Attacks against Language Models via Neighbourhood Comparison',
        'found_authors': 'Justus Mattern, Fatemehsadat Mireshghallah',
        'found_venue': 'Findings of the Association for Computational Linguistics: ACL 2023',
        'found_year': '2023',
    }

    updated = apply_hallucination_verdict(result, assessment, reference)

    assert updated['status'] == 'verified'
    assert updated['errors'] == []
    assert updated['warnings'][0]['error_type'] == 'venue'
    assert updated['warnings'][0]['ref_venue_correct'] == 'Findings of the Association for Computational Linguistics: ACL 2023'


def test_apply_hallucination_verdict_replaces_stale_db_urls_after_llm_recheck():
    result = {
        'status': 'warning',
        'errors': [],
        'warnings': [
            {'error_type': 'year', 'error_details': 'Year mismatch:\n cited: 2018\n actual: 2020'},
        ],
        'authoritative_urls': [
            {'type': 'semantic_scholar', 'url': 'https://api.semanticscholar.org/CorpusID:221910705'},
            {'type': 'doi', 'url': 'https://doi.org/10.1080/14697688.2020.1813475'},
        ],
        'matched_database': 'Semantic Scholar',
    }
    reference = {
        'title': 'High-dimensional probability : an introduction with applications in data science',
        'authors': ['Roman Vershynin'],
        'year': 2018,
        'venue': 'Cambridge series in statistical and probabilistic mathematics ; 47. Cambridge University Press',
    }
    assessment = {
        'verdict': 'UNLIKELY',
        'explanation': 'The exact book was found.',
        'link': 'https://www.cambridge.org/core/books/highdimensional-probability/797C466DA29743D2C8213493BD2D2102',
        'found_title': 'High-Dimensional Probability: An Introduction with Applications in Data Science',
        'found_authors': 'Roman Vershynin',
        'found_venue': 'Cambridge University Press',
        'found_year': '2018',
    }

    updated = apply_hallucination_verdict(result, assessment, reference)

    assert updated['status'] == 'verified'
    assert updated['errors'] == []
    assert updated['matched_database'] == 'LLM search'
    assert updated['authoritative_urls'] == [
        {
            'type': 'llm_verified',
            'url': 'https://www.cambridge.org/core/books/highdimensional-probability/797C466DA29743D2C8213493BD2D2102',
        }
    ]
    assert [warning['error_type'] for warning in updated['warnings']] == ['venue']


def test_likely_verdict_with_matching_found_metadata_replaces_wrong_db_match():
    result = {
        'status': 'error',
        'errors': [
            {
                'error_type': 'author',
                'error_details': 'Author count mismatch: 3 cited vs 2 correct',
                'ref_authors_correct': 'Rasmus Bruckner, Matt R. Nassar',
            }
        ],
        'authoritative_urls': [
            {'type': 'doi', 'url': 'https://doi.org/10.31234/osf.io/ce8jf'},
        ],
        'matched_database': 'CrossRef',
    }
    reference = {
        'title': 'Moral decision-making under uncertainty',
        'authors': ['Christian Tarsney', 'Teruji Thomas', 'William MacAskill'],
        'year': 2024,
        'venue': 'n.d.',
    }
    assessment = {
        'verdict': 'LIKELY',
        'explanation': 'The verified URL points to a different paper.',
        'link': 'https://plato.stanford.edu/entries/moral-decision-uncertainty/',
        'found_title': 'Moral Decision-Making Under Uncertainty',
        'found_authors': 'Christian Tarsney, Teruji Thomas, William MacAskill',
        'found_venue': 'Stanford Encyclopedia of Philosophy',
        'found_year': '2024',
    }

    updated = apply_hallucination_verdict(result, assessment, reference)

    assert updated['status'] == 'verified'
    assert updated['errors'] == []
    assert updated['matched_database'] == 'LLM search'
    assert updated['hallucination_assessment']['verdict'] == 'UNLIKELY'
    assert updated['hallucination_assessment']['original_verdict'] == 'LIKELY'
    assert updated['authoritative_urls'] == [
        {
            'type': 'llm_verified',
            'url': 'https://plato.stanford.edu/entries/moral-decision-uncertainty/',
        }
    ]


def test_apply_hallucination_verdict_marks_llm_search_database_for_upgraded_reference():
    result = {
        'status': 'unverified',
        'errors': [{'error_type': 'unverified', 'error_details': 'Could not verify'}],
    }
    assessment = {
        'verdict': 'UNLIKELY',
        'explanation': 'The exact paper was found.',
        'link': 'https://arxiv.org/abs/2506.00181',
    }

    updated = apply_hallucination_verdict(result, assessment)

    assert updated['status'] == 'verified'
    assert updated['matched_database'] == 'LLM search'
    assert updated['authoritative_urls'] == [
        {'type': 'llm_verified', 'url': 'https://arxiv.org/abs/2506.00181'}
    ]


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


def test_hallucination_prompt_treats_matching_huggingface_dataset_as_valid():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'code instructions',
        'ref_authors_cited': 'red1xe',
        'ref_year_cited': '2023',
        'ref_url_cited': 'https://huggingface.co/datasets/red1xe/code_instructions',
        'original_reference': {
            'venue': '',
            'url': 'https://huggingface.co/datasets/red1xe/code_instructions',
        },
    }

    system_prompt, user_prompt = build_assessment_prompt(entry)

    assert 'DATASET REFERENCES' in system_prompt
    assert 'red1xe/code_instructions' in system_prompt
    assert 'Do NOT require datasets to have academic-paper authors' in system_prompt
    assert 'https://huggingface.co/datasets/red1xe/code_instructions' in user_prompt


def test_hallucination_prompt_treats_official_model_docs_as_valid_sources():
    entry = {
        'error_type': 'url',
        'error_details': (
            'Cited URL does not reference this paper: '
            'https://www.llama.com/docs/model-cards-and-prompt-formats/llama4/'
        ),
        'ref_title': 'Llama 4|Model Cards and Prompt Formats',
        'ref_authors_cited': 'Meta',
        'ref_year_cited': '2025',
        'ref_url_cited': 'https://www.llama.com/docs/model-cards-and-prompt-formats/llama4/',
        'original_reference': {
            'venue': 'None',
            'url': 'https://www.llama.com/docs/model-cards-and-prompt-formats/llama4/',
        },
    }

    system_prompt, user_prompt = build_assessment_prompt(entry)

    assert 'OFFICIAL MODEL OR PRODUCT DOCUMENTATION' in system_prompt
    assert 'Llama 4 | Model Cards and Prompt Formats' in system_prompt
    assert 'limitation of the paper-oriented checker' in system_prompt
    assert 'https://www.llama.com/docs/model-cards-and-prompt-formats/llama4/' in user_prompt


def test_hallucination_prompt_treats_vendor_tech_intro_as_valid_source():
    entry = {
        'error_type': 'url',
        'error_details': (
            'Cited URL does not reference this paper: '
            'https://seed.bytedance.com/en/seed1_6'
        ),
        'ref_title': 'Seed1.6 Tech Introduction',
        'ref_authors_cited': 'ByteDance Seed Team',
        'ref_year_cited': '2025',
        'ref_url_cited': 'https://seed.bytedance.com/en/seed1_6',
        'original_reference': {
            'venue': 'Technical report',
            'url': 'https://seed.bytedance.com/en/seed1_6',
        },
    }

    system_prompt, user_prompt = build_assessment_prompt(entry)

    assert 'vendor technical reports' in system_prompt
    assert 'Seed1.6 Tech Introduction' in system_prompt
    assert 'Do NOT require these sources to be peer-reviewed papers' in system_prompt
    assert 'https://seed.bytedance.com/en/seed1_6' in user_prompt


def test_verified_official_model_docs_likely_is_corrected_to_unlikely():
    entry = {
        'error_type': 'multiple',
        'error_details': 'Cited URL does not reference this paper',
        'ref_title': 'Llama 3.3 — model cards and prompt formats',
        'ref_authors_cited': 'Meta AI',
        'ref_year_cited': '2024',
        'ref_url_cited': 'https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_3/',
        'ref_verified_url': 'https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_3/',
        'original_reference': {
            'venue': 'n.d.',
            'url': 'https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_3/',
        },
    }

    verdict, explanation = LLMHallucinationVerifier._apply_verified_safety_net(
        'LIKELY',
        'The page was not found.',
        entry,
        [],
    )

    assert verdict == 'UNLIKELY'
    assert 'official web source' in explanation


def test_verified_academic_wrong_arxiv_id_is_not_corrected_by_real_world_safety_net():
    entry = {
        'error_type': 'multiple',
        'error_details': 'Incorrect ArXiv ID',
        'ref_title': 'Gte: General text embeddings with weak supervision',
        'ref_authors_cited': 'Fake Author',
        'ref_url_cited': 'https://arxiv.org/abs/2308.03281',
        'ref_verified_url': 'https://arxiv.org/abs/2308.03281',
        'original_reference': {
            'venue': 'arXiv preprint arXiv:2308.03281',
            'url': 'https://arxiv.org/abs/2308.03281',
        },
    }

    verdict, _ = LLMHallucinationVerifier._apply_verified_safety_net(
        'LIKELY',
        'The arXiv ID points to a different paper.',
        entry,
        [],
    )

    assert verdict == 'LIKELY'


def test_citation_evidence_does_not_verify_unverified_academic_paper():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Prophet inequalities with unknown distributions',
        'ref_authors_cited': (
            'Hossein Esfandiari, Mohammad Taghi Hajiaghayi, '
            'Brendan Lucier, Morteza Zadimoghaddam'
        ),
        'ref_year_cited': '2017',
        'ref_url_cited': '',
        'original_reference': {
            'venue': 'Proceedings of the 49th Annual ACM SIGACT Symposium on Theory of Computing (STOC)',
        },
    }

    verdict, explanation = LLMHallucinationVerifier._apply_citation_evidence_guard(
        'UNLIKELY',
        (
            'The paper "Prophet inequalities with unknown distributions" by '
            'Esfandiari, Hajiaghayi, Lucier, and Zadimoghaddam, presented at '
            'STOC 2017, is referenced in another arXiv paper.'
        ),
        entry,
    )

    assert verdict == 'LIKELY'
    assert 'citation or reference in another paper is not proof' in explanation


def test_citation_evidence_guard_does_not_override_verified_paper():
    entry = {
        'error_type': 'author',
        'error_details': 'Author formatting mismatch',
        'ref_title': 'A verified academic paper',
        'ref_authors_cited': 'Author One, Author Two',
        'ref_verified_url': 'https://doi.org/10.1000/example',
    }

    verdict, explanation = LLMHallucinationVerifier._apply_citation_evidence_guard(
        'UNLIKELY',
        'The paper also appears in another publication bibliography.',
        entry,
    )

    assert verdict == 'UNLIKELY'
    assert explanation == 'The paper also appears in another publication bibliography.'


def test_hallucination_prompt_treats_software_project_citation_as_valid_source():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Leela chess zero',
        'ref_authors_cited': 'Gian-Carlo Pascutto, Gary Linscott',
        'ref_year_cited': '2019',
        'ref_url_cited': '',
        'original_reference': {
            'venue': '',
            'url': '',
        },
    }

    system_prompt, user_prompt = build_assessment_prompt(entry)

    assert 'SOFTWARE OR CODE PROJECT REFERENCES' in system_prompt
    assert 'Do NOT require a DOI, paper venue, academic database' in system_prompt
    assert 'Leela Chess Zero' in system_prompt
    assert 'Leela chess zero' in user_prompt


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


def test_zero_author_overlap_defers_to_llm_when_available():
    """0% author overlap should call the LLM because the DB match may be wrong."""
    entry = {
        'error_type': 'author',
        'error_details': 'Author mismatch',
        'ref_title': 'A title that may match a different paper',
        'ref_authors_cited': 'Alice One, Bob Two, Carol Three',
        'ref_authors_correct': 'Xavier Four, Yolanda Five, Zach Six',
    }
    llm_client = MagicMock()
    llm_client.assess.return_value = {
        'verdict': 'UNLIKELY',
        'explanation': 'Found a different paper with the cited authors.',
        'web_search': None,
    }

    result = run_hallucination_check(entry, llm_client=llm_client)

    llm_client.assess.assert_called_once()
    assert result['verdict'] == 'UNLIKELY'


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


def test_verified_ref_author_field_with_title_words_is_garbled_metadata():
    entry = {
        'error_type': 'multiple',
        'error_details': 'Author mismatch',
        'ref_title': 'M3-Embedding: Multi-Linguality, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation',
        'ref_authors_cited': 'Multi-Linguality Multi-Functionality Multi-Granularity',
        'ref_authors_correct': 'Jianlv Chen, Shitao Xiao, Peitian Zhang, Kun Luo, Defu Lian, Zheng Liu',
        'ref_verified_url': 'https://arxiv.org/abs/2402.03216',
    }

    result = run_hallucination_check(entry, llm_client=None)

    assert result is not None
    assert result['verdict'] == 'UNLIKELY'
    assert 'metadata extraction error' in result['explanation']


def test_unverified_split_word_title_artifact_calls_llm_when_available():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'De novo design of a fluorescence-activatingβ-barrel',
        'ref_authors_cited': 'Jiayi Dou, Anastassia A V orobieva, William Sheffler',
        'ref_year_cited': 2018,
        'ref_venue_cited': 'Nature',
    }
    llm_client = MagicMock()
    llm_client.assess.return_value = {
        'verdict': 'UNLIKELY',
        'explanation': 'Found the paper despite the title formatting artifact.',
        'web_search': None,
    }

    result = run_hallucination_check(entry, llm_client=llm_client)

    llm_client.assess.assert_called_once()
    assert result['verdict'] == 'UNLIKELY'


def test_empty_author_broken_prefix_title_is_uncertain_extraction_artifact():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Paper not found by any checker',
        'ref_title': 'ling structural representations into protein sequence models',
        'ref_authors_cited': '',
        'ref_year_cited': 2025,
        'ref_venue_cited': 'The Thirteenth International Conference on Learning Representations',
        'ref_raw_text': '#ling structural representations into protein sequence models#The Thirteenth International Conference on Learning Representations#2025#',
        'original_reference': {
            'authors': [],
            'title': 'ling structural representations into protein sequence models',
            'raw_text': '#ling structural representations into protein sequence models#The Thirteenth International Conference on Learning Representations#2025#',
        },
    }

    result = run_hallucination_check(entry, llm_client=None)

    assert result is not None
    assert result['verdict'] == 'UNCERTAIN'
    assert 'truncated extraction artifact' in result['explanation']


def test_empty_author_normal_lowercase_title_is_not_broken_prefix_artifact():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Paper not found by any checker',
        'ref_title': 'the effects of representation learning on synthetic tasks',
        'ref_authors_cited': '',
        'ref_raw_text': '#the effects of representation learning on synthetic tasks#2025#',
        'original_reference': {
            'authors': [],
            'title': 'the effects of representation learning on synthetic tasks',
            'raw_text': '#the effects of representation learning on synthetic tasks#2025#',
        },
    }

    result = run_hallucination_check(entry, llm_client=None)

    assert result is None


def test_split_word_title_artifact_needs_llm():
    entry = {
        'error_type': 'unverified',
        'error_details': 'Paper not found by any checker',
        'ref_title': 'Improving mutual information estimatio n with annealed and energy-based bounds',
        'ref_authors_cited': 'Rob Brekelmans, Sicong Huang, Marzyeh Ghassemi',
        'ref_raw_text': 'Rob Brekelmans*Sicong Huang*Marzyeh Ghassemi#Improving mutual information estimatio n with annealed and energy-based bounds#International Conference on Learning Representations#2022#',
        'original_reference': {
            'authors': ['Rob Brekelmans', 'Sicong Huang', 'Marzyeh Ghassemi'],
            'title': 'Improving mutual information estimatio n with annealed and energy-based bounds',
            'raw_text': 'Rob Brekelmans*Sicong Huang*Marzyeh Ghassemi#Improving mutual information estimatio n with annealed and energy-based bounds#International Conference on Learning Representations#2022#',
        },
    }

    result = run_hallucination_check(entry, llm_client=None)

    assert result is None


def test_overlapping_split_word_title_artifacts_need_llm():
    for title in (
        'Eff ect of tokenization on transformers for biological sequences',
        'Discrete diffus ion modeling by estimating the ratios of the data distribution',
        'A compara tive analysis of discrete entropy estimators for large-alphabet problems',
    ):
        entry = {
            'error_type': 'unverified',
            'error_details': 'Paper not found by any checker',
            'ref_title': title,
            'ref_authors_cited': 'Example Author, Second Author',
            'original_reference': {
                'authors': ['Example Author', 'Second Author'],
                'title': title,
                'raw_text': f'Example Author*Second Author#{title}#2024#',
            },
        }

        result = run_hallucination_check(entry, llm_client=None)

        assert result is None


def test_concatenated_word_title_artifact_needs_llm():
    for title in (
        'Deepconfidentstepstonewpockets: Strategiesfordockinggeneralization',
        'Reviewondiscoverystudio: Animportanttoolformolecular docking',
        'Provably robust multi-bit watermarking forAI-generatedtext',
    ):
        entry = {
            'error_type': 'unverified',
            'error_details': 'Paper not found by any checker',
            'ref_title': title,
            'ref_authors_cited': 'Example Author, Second Author',
            'original_reference': {
                'authors': ['Example Author', 'Second Author'],
                'title': title,
                'raw_text': f'Example Author*Second Author#{title}#2024#',
            },
        }

        result = run_hallucination_check(entry, llm_client=None)

        assert result is None


def test_truncated_first_author_fragment_is_uncertain():
    entry = {
        'error_type': 'multiple',
        'error_details': 'Author mismatch',
        'ref_title': 'Multi-modal deep learning',
        'ref_authors_cited': 'ngyu Kim, Juhan Nam, Honglak Lee, Andrew Y Ng',
        'ref_authors_correct': 'Cem Akkus, Luyang Chu, Vladana Djakovic',
        'ref_verified_url': 'https://arxiv.org/abs/2301.04856',
        'ref_raw_text': 'ngyu Kim*Juhan Nam*Honglak Lee*Andrew Y Ng#Multi-modal deep learning#ICML#2011#',
        'original_reference': {
            'authors': ['ngyu Kim', 'Juhan Nam', 'Honglak Lee', 'Andrew Y Ng'],
            'title': 'Multi-modal deep learning',
            'raw_text': 'ngyu Kim*Juhan Nam*Honglak Lee*Andrew Y Ng#Multi-modal deep learning#ICML#2011#',
        },
    }

    result = run_hallucination_check(entry, llm_client=None)

    assert result is not None
    assert result['verdict'] == 'UNCERTAIN'
    assert 'truncated name fragment' in result['explanation']


# ------------------------------------------------------------------
# LLM override behavior
# ------------------------------------------------------------------

def test_deterministic_likely_is_final():
    """When deterministic author-overlap returns LIKELY on a verified ref,
    the LLM IS called to distinguish wrong-edition matches from grafted refs.

    For verified refs, the rule-based LIKELY is overridden by the LLM because
    the checker may have matched a different edition/paper with the same title.
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
    assert result['verdict'] == 'UNLIKELY'  # LLM overrides rule-based for verified refs
    mock_llm.assess.assert_called_once()  # LLM invoked for verified refs


def test_deterministic_likely_is_final_without_llm():
    """Without an LLM, deterministic LIKELY is still final for verified refs."""
    entry = {
        'error_type': 'multiple',
        'error_details': 'Author mismatch',
        'ref_title': 'Fairness in machine learning: a survey with some extra words',
        'ref_authors_cited': 'Solon Barocas, Moritz Hardt, Arvind Narayanan',
        'ref_authors_correct': 'L. Oneto, S. Chiappa',
        'ref_verified_url': 'https://api.semanticscholar.org/CorpusID:12345',
    }
    result = run_hallucination_check(entry, llm_client=None)
    assert result['verdict'] == 'LIKELY'  # deterministic is final without LLM


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


def test_deep_hallucination_check_logs_when_llm_is_invoked(caplog):
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'A fabricated reference title long enough to require the LLM path',
        'ref_authors_cited': 'Fake Author One, Fake Author Two',
    }
    mock_llm = MagicMock()
    mock_llm.available = True
    mock_llm.assess.return_value = {
        'verdict': 'LIKELY',
        'explanation': 'No paper with this title exists.',
        'source': 'deep_hallucination_cache',
        'web_search': None,
    }

    with caplog.at_level(logging.DEBUG, logger='refchecker.core.hallucination_policy'):
        result = run_hallucination_check(entry, llm_client=mock_llm)

    assert result['verdict'] == 'LIKELY'
    assert 'deep hallucination check start' in caplog.text
    assert 'deep hallucination check verdict=LIKELY' in caplog.text


def test_verified_safety_net_keeps_likely_when_author_overlap_unknown():
    entry = {
        'error_type': 'author',
        'error_details': 'Author count mismatch: 1 cited vs 9 correct',
        'ref_title': 'Overcoming data scarcity in biomedical imaging with a foundational multi-task model',
        'ref_authors_cited': 'Chia-Yu et al. Chang',
        'ref_authors_correct': (
            'Raphael Schaefer, Till Nicke, Henning Hoefener, Annkristin Lange, '
            'D. Merhof, Friedrich Feuerhake, Volkmar Schulz, Johannes Lotz, F. Kiessling'
        ),
        'ref_verified_url': 'https://api.semanticscholar.org/CorpusID:265221081',
    }

    verdict, explanation = LLMHallucinationVerifier._apply_verified_safety_net(
        'LIKELY', 'The cited paper exists, but the cited authors are for a different work.', entry, [],
    )

    assert verdict == 'LIKELY'
    assert 'downgraded' not in explanation


def test_verified_safety_net_keeps_likely_when_author_overlap_is_half():
    entry = {
        'error_type': 'author',
        'error_details': 'Author mismatch',
        'ref_title': 'A verified paper with half fabricated authors',
        'ref_authors_cited': 'Ashish Vaswani, Noam Shazeer, Fake Author, Imaginary Person',
        'ref_authors_correct': 'Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit',
        'ref_verified_url': 'https://arxiv.org/abs/1706.03762',
    }

    verdict, explanation = LLMHallucinationVerifier._apply_verified_safety_net(
        'LIKELY', 'Only half of the cited author list matches the verified paper.', entry, [],
    )

    assert verdict == 'LIKELY'
    assert 'downgraded' not in explanation


def test_deep_hallucination_assessment_log_includes_full_explanation(caplog):
    verifier = object.__new__(LLMHallucinationVerifier)
    verifier.provider = 'google'
    verifier.model = 'gemini-test'
    verifier.client = object()
    verifier.cache_dir = None
    full_explanation = (
        'The cited paper exists under the title "Overcoming data scarcity in biomedical imaging '
        'with a foundational multi-task model" and was published in Nature Computational Science '
        'in 2024. The cited author list belongs to a different work. FULL_EXPLANATION_TAIL'
    )
    verifier._call = lambda system_prompt, user_prompt: (
        f'EXPLANATION: {full_explanation}\nVERDICT: LIKELY',
        [],
    )
    entry = {
        'error_type': 'unverified',
        'error_details': 'Reference could not be verified',
        'ref_title': 'Overcoming data scarcity in biomedical imaging with a foundational multi-task model',
        'ref_authors_cited': 'Chia-Yu et al. Chang',
    }

    with caplog.at_level(logging.DEBUG, logger='refchecker.llm.hallucination_verifier'):
        result = verifier.assess(entry)

    assert result['verdict'] == 'LIKELY'
    assert full_explanation in caplog.text
    assert 'FULL_EXPLANATION_TAIL' in caplog.text


def test_ungrounded_unlikely_for_academic_reference_is_uncertain():
    verifier = object.__new__(LLMHallucinationVerifier)
    verifier.provider = 'google'
    verifier.model = 'gemini-test'
    verifier.client = object()
    verifier.cache_dir = None
    verifier._call = lambda system_prompt, user_prompt: (
        'EXPLANATION: The paper was found at the provided URL with exact title and authors.\n'
        'LINK: https://academic.oup.com/asj/advance-article/doi/10.1093/asj/sjae251/7941969\n'
        'VERDICT: UNLIKELY',
        [],
    )
    entry = {
        'error_type': 'multiple',
        'error_details': 'All available checkers failed\nPaper not verified; cited URL could not be accessed',
        'ref_title': '3d breast scanning in plastic surgery utilizing free iphone lidar applications and standard consumer devices: A comparative analysis',
        'ref_authors_cited': 'Dawid Boczar, Magdalena Kitala, Klaudia Nowak, Bartlomiej Nowak, Rafal Slojewski',
        'ref_year_cited': 2024,
        'ref_url_cited': 'https://academic.oup.com/asj/advance-article-abstract/doi/10.1093/asj/sjae251/7941969',
        'original_reference': {
            'venue': 'Aesthetic Surgery Journal',
            'url': 'https://academic.oup.com/asj/advance-article-abstract/doi/10.1093/asj/sjae251/7941969',
        },
    }

    result = verifier.assess(entry)

    assert result['verdict'] == 'UNCERTAIN'
    assert 'not grounded in web search results or verified metadata' in result['explanation']


def test_unlikely_low_overlap_author_mismatch_is_corrected_to_likely():
    verifier = object.__new__(LLMHallucinationVerifier)
    verifier.provider = 'google'
    verifier.model = 'gemini-test'
    verifier.client = object()
    verifier.cache_dir = None
    verifier._call = lambda system_prompt, user_prompt: (
        'EXPLANATION: The paper exists, but the cited author list contains an error; this is metadata rather than fabrication.\n'
        'LINK: https://api.semanticscholar.org/CorpusID:53438169\n'
        'FOUND_TITLE: Prophet inequalities for independent random variables from an unknown distribution\n'
        'FOUND_AUTHORS: José R. Correa, Paul Dütting, Felix A. Fischer, Kevin Schewior\n'
        'FOUND_YEAR: 2019\n'
        'VERDICT: UNLIKELY',
        [],
    )
    entry = {
        'error_type': 'author (v1 vs v2 update)',
        'error_details': 'Author 2 mismatch:\n  cited: Pablo D. A. Foncea\n  actual: Paul Dütting',
        'ref_title': 'Prophet inequalities for independent random variables from an unknown distribution',
        'ref_authors_cited': 'José Correa, Pablo D. A. Foncea, Ruben Hoeksma, Tim Roughgarden',
        '_ref_authors_cited_list': ['José Correa', 'Pablo D. A. Foncea', 'Ruben Hoeksma', 'Tim Roughgarden'],
        'ref_authors_correct': 'José R. Correa, Paul Dütting, Felix A. Fischer, Kevin Schewior',
        'ref_verified_url': 'https://api.semanticscholar.org/CorpusID:53438169',
    }

    result = verifier.assess(entry)

    assert result['verdict'] == 'LIKELY'
    assert 'real title with fabricated coauthors' in result['explanation']


def test_unlikely_low_overlap_allowed_when_found_authors_match_cited_authors():
    verdict, explanation = LLMHallucinationVerifier._apply_unlikely_author_mismatch_guard(
        'UNLIKELY',
        'The checker matched a different edition; the cited authors appear on the found source.',
        {
            'error_type': 'multiple',
            'ref_title': 'Convergence of Probability Measures',
            'ref_authors_cited': 'Patrick Billingsley, Example Coauthor, Third Author',
            '_ref_authors_cited_list': ['Patrick Billingsley', 'Example Coauthor', 'Third Author'],
            'ref_authors_correct': 'Fake Database Author, Another Database Author, Third Database Author',
            'ref_verified_url': 'https://example.org/wrong-edition',
        },
        ['https://example.org/cited-edition'],
        {'authors': 'Patrick Billingsley, Example Coauthor, Third Author'},
    )

    assert verdict == 'UNLIKELY'
    assert 'corrected' not in explanation


def test_unlikely_low_overlap_rejects_conflicting_found_authors_for_checked_url():
    verdict, explanation = LLMHallucinationVerifier._apply_unlikely_author_mismatch_guard(
        'UNLIKELY',
        'The paper exists, and the second author discrepancy is a minor metadata error.',
        {
            'error_type': 'author (v1 vs v2 update)',
            'ref_title': 'Prophet inequalities for independent random variables from an unknown distribution',
            'ref_authors_cited': 'José Correa, Pablo D. A. Foncea, Ruben Hoeksma, Tim Roughgarden',
            '_ref_authors_cited_list': ['José Correa', 'Pablo D. A. Foncea', 'Ruben Hoeksma', 'Tim Roughgarden'],
            'ref_authors_correct': 'José R. Correa, Paul Dütting, Felix A. Fischer, Kevin Schewior',
            'ref_url_cited': 'https://arxiv.org/abs/1811.06114',
            'ref_verified_url': 'https://api.semanticscholar.org/CorpusID:53438169',
        },
        [],
        {'authors': 'José Correa, Paul Dütting, Ruben Hoeksma, Tim Roughgarden'},
        'https://arxiv.org/abs/1811.06114',
    )

    assert verdict == 'LIKELY'
    assert 'real title with fabricated coauthors' in explanation


def test_unlikely_low_overlap_accepts_found_authors_when_found_title_matches_citation():
    verdict, explanation = LLMHallucinationVerifier._apply_unlikely_author_mismatch_guard(
        'UNLIKELY',
        'The exact paper with this title and author list was found on ACL Anthology.',
        {
            'error_type': 'author',
            'ref_title': 'Membership inference attacks against language models via neighbourhood comparison',
            'ref_authors_cited': 'Justus Mattern, Fatemehsadat Mireshghallah, Zhijing Jin, Bernhard Schoelkopf, Mrinmaya Sachan, Taylor Berg-Kirkpatrick',
            '_ref_authors_cited_list': [
                'Justus Mattern',
                'Fatemehsadat Mireshghallah',
                'Zhijing Jin',
                'Bernhard Schoelkopf',
                'Mrinmaya Sachan',
                'Taylor Berg-Kirkpatrick',
            ],
            'ref_authors_correct': 'Shang-Ching Liu, ShengKun Wang, Wenqi Lin, Chung-Wei Hsiung, Yi-Chen Hsieh, Yu-Ping Cheng, Sian-Hong Luo, Tsungyao Chang, Jianwei Zhang',
            'ref_url_cited': 'https://aclanthology.org/2023.findings-acl.719/',
            'ref_verified_url': 'https://aclanthology.org/2023.findings-acl.719/',
        },
        ['https://aclanthology.org/2023.findings-acl.719.pdf'],
        {
            'title': 'Membership Inference Attacks against Language Models via Neighbourhood Comparison',
            'authors': 'Justus Mattern, Fatemehsadat Mireshghallah, Zhijing Jin, Bernhard Schölkopf, Mrinmaya Sachan, Taylor Berg-Kirkpatrick',
            'year': '2023',
        },
        'https://aclanthology.org/2023.findings-acl.719/',
    )

    assert verdict == 'UNLIKELY'
    assert 'corrected' not in explanation


def test_google_rate_limit_retry_eventually_succeeds(monkeypatch):
    verifier = object.__new__(LLMHallucinationVerifier)
    verifier.model = 'gemini-test'
    response = MagicMock()
    response.text = 'ok'
    generate_content = MagicMock(side_effect=[RuntimeError('429 RESOURCE_EXHAUSTED'), response])
    verifier.client = MagicMock()
    verifier.client.models.generate_content = generate_content
    sleeps = []
    monkeypatch.setattr('refchecker.llm.hallucination_verifier.random.random', lambda: 0.25)
    monkeypatch.setattr('refchecker.llm.hallucination_verifier.time.sleep', sleeps.append)

    result = verifier._google_generate_content_with_retry(
        contents='prompt',
        config=object(),
        purpose='test call',
    )

    assert result is response
    assert generate_content.call_count == 2
    assert sleeps == [1.25]


def test_google_non_rate_limit_error_is_not_retried(monkeypatch):
    verifier = object.__new__(LLMHallucinationVerifier)
    verifier.model = 'gemini-test'
    generate_content = MagicMock(side_effect=RuntimeError('invalid request'))
    verifier.client = MagicMock()
    verifier.client.models.generate_content = generate_content
    sleep = MagicMock()
    monkeypatch.setattr('refchecker.llm.hallucination_verifier.time.sleep', sleep)

    try:
        verifier._google_generate_content_with_retry(
            contents='prompt',
            config=object(),
            purpose='test call',
        )
    except RuntimeError as exc:
        assert 'invalid request' in str(exc)
    else:
        raise AssertionError('Expected RuntimeError')

    assert generate_content.call_count == 1
    sleep.assert_not_called()


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
