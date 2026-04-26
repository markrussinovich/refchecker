"""Regression tests for targeted reference-extraction false positives."""

from refchecker.llm.base import LLMProvider
from refchecker.utils.url_utils import clean_url_punctuation


def test_clean_url_punctuation_strips_next_reference_after_pdf_url():
    glued_url = (
        'https://www-cdn.anthropic.com/6d8a8055020700718b0c49369f60816ba2a7c285.pdf'
        '%20Shuai%20Bai,%20Wen%20Zhang,%20and%20Bo%20Jing.%20Deepseek-v3%20technical%20report,%202024.'
    )

    assert clean_url_punctuation(glued_url) == (
        'https://www-cdn.anthropic.com/6d8a8055020700718b0c49369f60816ba2a7c285.pdf'
    )


def test_clean_url_punctuation_preserves_encoded_spaces_before_pdf_suffix():
    url = 'https://example.com/reports/Claude%204%20System%20Card.pdf'

    assert clean_url_punctuation(url) == url


def test_repair_truncated_arxiv_doi_from_source_bibliography():
    refs = [
        'a*Ying Tang*et al.#DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning#arXiv preprint#2025#https://doi.org/10.48550/ARXIV.25'
    ]
    bibliography_text = (
        'DeepSeek-AI, Daya Guo, Dejian Yang, Haowei Zhang, Junxiao Song, et al. '
        'DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning. '
        'arXiv preprint arXiv:2501.12948, 2025. DOI: 10.48550/ARXIV.2501.12948\n'
        'Other Team. Another 2025 arXiv paper. DOI: 10.48550/arXiv.2502.00001'
    )

    repaired = LLMProvider._repair_truncated_arxiv_dois(refs, bibliography_text)

    assert '10.48550/ARXIV.2501.12948' in repaired[0]
    assert '10.48550/ARXIV.25' not in repaired[0].replace('10.48550/ARXIV.2501.12948', '')


def test_repair_truncated_arxiv_doi_leaves_complete_doi_unchanged():
    refs = [
        'DeepSeek-AI#DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning#arXiv preprint#2025#https://doi.org/10.48550/ARXIV.2501.12948'
    ]
    bibliography_text = (
        'DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning. '
        'DOI: 10.48550/ARXIV.2501.12948'
    )

    assert LLMProvider._repair_truncated_arxiv_dois(refs, bibliography_text) == refs