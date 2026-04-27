from refchecker.checkers.webpage_checker import WebPageChecker


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