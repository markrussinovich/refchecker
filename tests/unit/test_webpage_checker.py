from refchecker.checkers.webpage_checker import WebPageChecker


class DummyResponse:
    def __init__(self, html, url="https://example.com/page", status_code=200):
        self.content = html.encode("utf-8")
        self.url = url
        self.status_code = status_code
        self.headers = {"content-type": "text/html; charset=utf-8"}


def test_ai_vendor_model_docs_are_web_page_urls():
    checker = WebPageChecker()

    assert checker.is_web_page_url(
        "https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_3/"
    )
    assert checker.is_web_page_url(
        "https://ai.meta.com/blog/llama-4-multimodal-intelligence/"
    )
    assert checker.is_web_page_url(
        "https://platform.openai.com/docs/models#gpt-4-1-mini"
    )
    assert checker.is_web_page_url(
        "https://www.anthropic.com/news/claude-4"
    )
    assert checker.is_web_page_url(
        "https://hkunlp.github.io/blog/2025/Polaris"
    )
    assert checker.is_web_page_url(
        "https://ai.gitcode.com/ascend-tribe/openPangu-Embedded-7B-DeepDiver"
    )


def test_model_card_and_release_venues_are_web_content():
    checker = WebPageChecker()

    assert checker._is_web_content_venue(
        "Model cards and prompt formats",
        "https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_3/",
    )
    assert checker._is_web_content_venue(
        "Meta AI Blog",
        "https://ai.meta.com/blog/llama-4-multimodal-intelligence/",
    )
    assert checker._is_web_content_venue(
        "Technical report, Anthropic PBC",
        "https://www.anthropic.com/news/claude-4",
    )


def test_academic_arxiv_url_is_not_web_content_venue():
    checker = WebPageChecker()

    assert not checker._is_web_content_venue(
        "arXiv preprint arXiv:2402.07314",
        "https://arxiv.org/abs/2402.07314",
    )


def test_non_academic_url_can_verify_even_with_academic_venue(monkeypatch):
    checker = WebPageChecker(request_delay=0)

    html = """
    <html>
      <head><title>Introducing Claude</title></head>
      <body><main><p>Introducing Claude, Anthropic's helpful AI assistant.</p></main></body>
    </html>
    """
    monkeypatch.setattr(
        checker,
        "_respectful_request",
        lambda url: DummyResponse(html, url="https://www.anthropic.com/news/introducing-claude"),
    )

    verified_data, errors, url = checker.verify_raw_url_for_unverified_reference({
        "title": "Introducing Claude",
        "authors": ["Anthropic"],
        "year": 2023,
        "venue": "arXiv preprint arXiv:2301.00000",
        "url": "https://www.anthropic.com/index/introducing-claude/",
    })

    assert verified_data is not None
    assert errors == []
    assert url == "https://www.anthropic.com/index/introducing-claude/"


def test_academic_url_with_academic_venue_still_requires_paper_verification(monkeypatch):
    checker = WebPageChecker(request_delay=0)

    html = """
    <html>
      <head><title>Some arXiv paper title</title></head>
      <body><main><p>Some arXiv paper title.</p></main></body>
    </html>
    """
    monkeypatch.setattr(
        checker,
        "_respectful_request",
        lambda url: DummyResponse(html, url="https://arxiv.org/abs/2402.07314"),
    )

    verified_data, errors, url = checker.verify_raw_url_for_unverified_reference({
        "title": "Some arXiv paper title",
        "authors": ["Example Author"],
        "year": 2024,
        "venue": "arXiv preprint arXiv:2402.07314",
        "url": "https://arxiv.org/abs/2402.07314",
    })

    assert verified_data is None
    assert errors == [{"error_type": "unverified", "error_details": "paper not verified but URL references paper"}]
    assert url == "https://arxiv.org/abs/2402.07314"