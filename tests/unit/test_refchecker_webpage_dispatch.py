from unittest.mock import MagicMock

from refchecker.core.refchecker import ArxivReferenceChecker


def test_standard_verification_prefers_webpage_checker_for_web_reference():
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.verify_github_reference = MagicMock(return_value=None)
    checker.verify_webpage_reference = MagicMock(
        return_value=(None, "https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_3/", {"title": "Llama 3.3"})
    )
    checker.non_arxiv_checker = MagicMock()

    reference = {
        "title": "Llama 3.3 — model cards and prompt formats",
        "authors": ["Meta AI"],
        "year": 2024,
        "venue": "n.d.",
        "url": "https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_3/",
    }

    result = checker.verify_reference_standard(None, reference)

    assert result == (None, reference["url"], {"title": "Llama 3.3"})
    checker.verify_github_reference.assert_called_once_with(reference)
    checker.verify_webpage_reference.assert_called_once_with(reference)
    checker.non_arxiv_checker.verify_reference.assert_not_called()


def test_standard_verification_falls_back_to_academic_checker_when_not_webpage():
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.verify_github_reference = MagicMock(return_value=None)
    checker.verify_webpage_reference = MagicMock(return_value=None)
    checker.non_arxiv_checker = MagicMock()
    checker.non_arxiv_checker.verify_reference.return_value = (
        {"title": "Attention Is All You Need"},
        [],
        "https://arxiv.org/abs/1706.03762",
    )

    reference = {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani"],
        "year": 2017,
        "venue": "NeurIPS",
        "url": "https://arxiv.org/abs/1706.03762",
    }

    result = checker.verify_reference_standard(None, reference)

    assert result == (None, "https://arxiv.org/abs/1706.03762", {"title": "Attention Is All You Need"})
    checker.non_arxiv_checker.verify_reference.assert_called_once_with(reference)