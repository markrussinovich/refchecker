import pytest

from refchecker.checkers.openreview_checker import OpenReviewReferenceChecker
from refchecker.utils.cache_utils import cache_api_response
from refchecker.services.pdf_processor import PDFProcessor


def test_anonymous_review_pdf_title_ignores_line_number_gutter():
    text = "\n".join(f"{i:03d}" for i in range(54)) + """
Under review as a conference paper at ICLR 2026
GRF-LLM: ENVIRONMENT-AWARE WIRELESS
CHANNEL MODELING VIA LLM-GUIDED 3D GAUS-
SIANS
Anonymous authors
Paper under double-blind review
ABSTRACT
This is the abstract, not part of the title.
"""
    assert PDFProcessor()._extract_title_from_text(text) == (
        "GRF-LLM: ENVIRONMENT-AWARE WIRELESS CHANNEL MODELING VIA LLM-GUIDED 3D GAUSSIANS"
    )


@pytest.mark.parametrize("heading", [
    "Verifying your browser", "Checking your browser...",
    "Verify you are human", "Just a moment...",
])
def test_browser_verification_page_is_not_paper_metadata(heading):
    checker = OpenReviewReferenceChecker(request_delay=0)
    assert checker._parse_web_page(
        f"<html><title>{heading}</title><h1>{heading}</h1></html>",
        "https://openreview.net/forum?id=paper",
    ) is None


def test_real_paper_about_browser_verification_is_not_rejected():
    checker = OpenReviewReferenceChecker(request_delay=0)
    metadata = checker._parse_web_page(
        '<title>OpenReview</title><h2 class="citation_title">'
        'Understanding browser verification in modern web applications</h2>',
        "https://openreview.net/forum?id=paper",
    )
    assert metadata["title"] == "Understanding browser verification in modern web applications"


def test_old_challenge_metadata_cache_does_not_override_pdf_fallback(tmp_path, monkeypatch):
    checker = OpenReviewReferenceChecker(request_delay=0)
    checker.cache_dir = str(tmp_path)
    cache_api_response(str(tmp_path), 'openreview', 'get_metadata', 'paper', {
        "title": "Verifying your browser", "authors": [],
    })
    monkeypatch.setattr(checker, "_get_paper_metadata_uncached", lambda _paper_id: None)
    assert checker.get_paper_metadata("paper") is None


def test_valid_metadata_replaces_old_challenge_cache(tmp_path, monkeypatch):
    checker = OpenReviewReferenceChecker(request_delay=0)
    checker.cache_dir = str(tmp_path)
    cache_api_response(str(tmp_path), 'openreview', 'get_metadata', 'paper', {
        "title": "Verifying your browser", "authors": [],
    })
    actual = {"title": "A real paper", "authors": ["A. Author"]}
    monkeypatch.setattr(checker, "_get_paper_metadata_uncached", lambda _paper_id: actual)
    assert checker.get_paper_metadata("paper") == actual
    monkeypatch.setattr(checker, "_get_paper_metadata_uncached", lambda _paper_id: pytest.fail("Cache should be valid"))
    assert checker.get_paper_metadata("paper") == actual
