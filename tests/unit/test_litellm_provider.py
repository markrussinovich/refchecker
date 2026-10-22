"""Tests for the LiteLLM provider across every LLM call path.

``litellm`` is an optional extra that CI does not install, so each test swaps
in a fake ``litellm`` module and asserts the kwargs that reach
``litellm.completion`` and how the response is parsed back.
"""

import sys
import types

import pytest

from refchecker.config.settings import (
    DEFAULT_EXTRACTION_MODELS,
    HALLUCINATION_CAPABLE_PROVIDERS,
)


class _Message:
    def __init__(self, content, annotations=None):
        self.content = content
        self.annotations = annotations


class _Usage:
    def __init__(self, prompt_tokens=120, completion_tokens=30):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Response:
    def __init__(self, content, annotations=None, cost=None):
        self.choices = [types.SimpleNamespace(message=_Message(content, annotations))]
        self.usage = _Usage()
        self._hidden_params = {"response_cost": cost} if cost is not None else {}


@pytest.fixture
def fake_litellm(monkeypatch):
    """Install a fake ``litellm`` module and record every completion call."""
    module = types.ModuleType("litellm")
    module.calls = []
    module.responses = []
    module.web_search_models = set()

    def completion(**kwargs):
        module.calls.append(kwargs)
        result = module.responses.pop(0) if module.responses else _Response("ok")
        if isinstance(result, Exception):
            raise result
        return result

    def supports_web_search(model):
        return model in module.web_search_models

    module.completion = completion
    module.supports_web_search = supports_web_search
    monkeypatch.setitem(sys.modules, "litellm", module)
    return module


# ---------------------------------------------------------------------------
# Extraction provider
# ---------------------------------------------------------------------------

def test_factory_creates_litellm_provider(fake_litellm):
    from refchecker.llm.base import create_llm_provider
    from refchecker.llm.providers import LiteLLMProvider

    provider = create_llm_provider("litellm", {"model": "bedrock/us.anthropic.claude-sonnet-4-6-v1:0"})
    assert isinstance(provider, LiteLLMProvider)
    assert provider.is_available()


def test_extraction_call_omits_blank_credentials(fake_litellm):
    from refchecker.llm.providers import LiteLLMProvider

    fake_litellm.responses.append(_Response("Vaswani et al. Attention Is All You Need. 2017."))
    provider = LiteLLMProvider({"model": "vertex_ai/gemini-2.5-pro"})
    text = provider._call_llm("[1] Vaswani et al. 2017")

    assert text == "Vaswani et al. Attention Is All You Need. 2017."
    call = fake_litellm.calls[0]
    assert call["model"] == "vertex_ai/gemini-2.5-pro"
    assert call["drop_params"] is True
    # No key or endpoint given: LiteLLM must read the provider's own env vars.
    assert "api_key" not in call
    assert "api_base" not in call
    assert call["messages"][0]["role"] == "system"
    assert call["messages"][1] == {"role": "user", "content": "[1] Vaswani et al. 2017"}
    assert call["max_tokens"] == provider.max_tokens
    assert call["temperature"] == provider.temperature


def test_extraction_call_forwards_key_and_endpoint(fake_litellm):
    from refchecker.llm.providers import LiteLLMProvider

    provider = LiteLLMProvider({
        "model": "hosted_vllm/meta-llama/Llama-3.1-8B-Instruct",
        "api_key": "sk-test",
        "endpoint": "http://localhost:8000/v1/chat/completions",
    })
    provider._call_llm("prompt")

    call = fake_litellm.calls[0]
    assert call["api_key"] == "sk-test"
    assert call["api_base"] == "http://localhost:8000/v1"


def test_extraction_defaults_to_settings_model(fake_litellm):
    from refchecker.llm.providers import LiteLLMProvider

    LiteLLMProvider({})._call_llm("prompt")
    assert fake_litellm.calls[0]["model"] == DEFAULT_EXTRACTION_MODELS["litellm"]


def test_provider_unavailable_without_litellm(monkeypatch):
    from refchecker.llm.providers import LiteLLMProvider

    monkeypatch.setitem(sys.modules, "litellm", None)
    assert LiteLLMProvider({"model": "anthropic/claude-sonnet-4-6"}).is_available() is False


def test_per_check_meter_uses_litellm_cost(fake_litellm):
    from refchecker.llm import usage_tracker
    from refchecker.llm.providers import LiteLLMProvider

    usage_tracker.reset("litellm-cost")
    usage_tracker.set_current_check("litellm-cost")
    try:
        fake_litellm.responses.append(_Response("refs", cost=0.0042))
        LiteLLMProvider({"model": "bedrock/us.anthropic.claude-sonnet-4-6-v1:0"})._call_llm("prompt")
        snap = usage_tracker.snapshot("litellm-cost")
    finally:
        usage_tracker.set_current_check(None)
        usage_tracker.reset("litellm-cost")

    assert snap["input_tokens"] == 120
    assert snap["output_tokens"] == 30
    assert snap["cost_usd"] == pytest.approx(0.0042)


# ---------------------------------------------------------------------------
# Hallucination verifier
# ---------------------------------------------------------------------------

def test_litellm_is_hallucination_capable():
    assert "litellm" in HALLUCINATION_CAPABLE_PROVIDERS


def test_verifier_available_without_api_key(fake_litellm):
    from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier

    verifier = LLMHallucinationVerifier(provider="litellm", model="bedrock/us.anthropic.claude-sonnet-4-6-v1:0")
    assert verifier.available
    assert verifier.api_key is None


def test_verifier_web_search_collects_cited_urls(fake_litellm):
    from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier

    model = "anthropic/claude-sonnet-4-6"
    fake_litellm.web_search_models.add(model)
    fake_litellm.responses.append(_Response(
        "VERDICT: UNLIKELY",
        annotations=[
            {"type": "url_citation", "url_citation": {"url": "https://arxiv.org/abs/1706.03762"}},
            types.SimpleNamespace(type="url_citation", url_citation=types.SimpleNamespace(url="https://dl.acm.org/doi/10.5555/3295222.3295349")),
            {"type": "url_citation", "url_citation": {"url": "https://arxiv.org/abs/1706.03762"}},
        ],
    ))
    verifier = LLMHallucinationVerifier(provider="litellm", model=model)
    text, urls = verifier._call_uncached("system", "user")

    assert text == "VERDICT: UNLIKELY"
    assert urls == [
        "https://arxiv.org/abs/1706.03762",
        "https://dl.acm.org/doi/10.5555/3295222.3295349",
    ]
    call = fake_litellm.calls[0]
    assert call["web_search_options"] == {"search_context_size": "medium"}
    assert call["drop_params"] is True


def test_verifier_uses_plain_chat_when_model_cannot_search(fake_litellm):
    from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier

    fake_litellm.responses.append(_Response("VERDICT: UNCERTAIN"))
    verifier = LLMHallucinationVerifier(provider="litellm", model="ollama/llama3.1")
    text, urls = verifier._call_uncached("system", "user")

    assert (text, urls) == ("VERDICT: UNCERTAIN", [])
    call = fake_litellm.calls[0]
    assert "web_search_options" not in call
    assert call["temperature"] == 0.0


def test_verifier_falls_back_to_chat_when_web_search_fails(fake_litellm):
    from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier

    model = "gemini/gemini-2.5-flash"
    fake_litellm.web_search_models.add(model)
    fake_litellm.responses.extend([RuntimeError("search tool rejected"), _Response("VERDICT: LIKELY")])
    verifier = LLMHallucinationVerifier(provider="litellm", model=model)
    text, urls = verifier._call_uncached("system", "user")

    assert (text, urls) == ("VERDICT: LIKELY", [])
    assert "web_search_options" in fake_litellm.calls[0]
    assert "web_search_options" not in fake_litellm.calls[1]

    # The failed search is not retried on the next reference.
    verifier._call_uncached("system", "user")
    assert len(fake_litellm.calls) == 3
    assert "web_search_options" not in fake_litellm.calls[2]


# ---------------------------------------------------------------------------
# Article chat + AI-detection judge
# ---------------------------------------------------------------------------

def test_article_assistant_litellm_chat(fake_litellm):
    from backend.article_chat import ArticleAssistant

    fake_litellm.responses.append(_Response("The article proposes the Transformer."))
    assistant = ArticleAssistant(provider="litellm", model="mistral/mistral-large-latest")
    assert assistant.available
    answer = assistant._call("system prompt", [{"role": "user", "content": "What is proposed?"}])

    assert answer == "The article proposes the Transformer."
    call = fake_litellm.calls[0]
    assert call["model"] == "mistral/mistral-large-latest"
    assert call["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "What is proposed?"},
    ]


def test_llm_judge_backend_litellm(fake_litellm):
    from refchecker.ai_detection.llm_backend import LLMJudgeBackend

    fake_litellm.responses.append(_Response('{"band": "low"}'))
    backend = LLMJudgeBackend(provider="litellm", model="groq/llama-3.3-70b-versatile")
    assert backend.available
    assert backend._call("system", "user") == '{"band": "low"}'
    assert fake_litellm.calls[0]["model"] == "groq/llama-3.3-70b-versatile"
    assert fake_litellm.calls[0]["max_tokens"] == 1500


# ---------------------------------------------------------------------------
# CLI + Web UI wiring
# ---------------------------------------------------------------------------

def test_cli_does_not_prompt_for_litellm_key(monkeypatch):
    from refchecker.core.refchecker import get_llm_api_key_interactive

    def _no_prompt(*_args, **_kwargs):
        raise AssertionError("LiteLLM must not prompt for an API key")

    monkeypatch.setattr("getpass.getpass", _no_prompt)
    assert get_llm_api_key_interactive("litellm") is None


def test_webui_cli_accepts_litellm():
    from backend import cli

    args = cli.parse_args([
        "check", "--paper", "1706.03762",
        "--llm-provider", "litellm",
        "--llm-model", "bedrock/us.anthropic.claude-sonnet-4-6-v1:0",
        "--check-hallucinations",
        "--hallucination-provider", "litellm",
    ])
    assert args.llm_provider == "litellm"
    assert args.hallucination_provider == "litellm"


def test_multiuser_rejects_litellm(monkeypatch):
    main = pytest.importorskip("backend.main")
    from fastapi import HTTPException

    monkeypatch.setattr(main, "is_multiuser_mode", lambda: True)
    with pytest.raises(HTTPException) as exc:
        main._ensure_allowed_web_llm_provider("litellm")
    assert exc.value.status_code == 403

    monkeypatch.setattr(main, "is_multiuser_mode", lambda: False)
    main._ensure_allowed_web_llm_provider("litellm")


def test_config_validator_warns_on_unprefixed_model():
    from refchecker.utils.config_validator import ConfigValidator

    result = ConfigValidator()._validate_llm_provider_config("litellm", {"model": "claude-sonnet-4-6"})
    assert result.is_valid
    assert any("provider prefix" in w for w in result.warnings)


def test_import_litellm_quiets_console_unless_debugging(fake_litellm, monkeypatch):
    import logging

    from refchecker.llm.providers import import_litellm

    monkeypatch.delenv("LITELLM_LOG", raising=False)
    lite_logger = logging.getLogger("LiteLLM")
    monkeypatch.setattr(lite_logger, "level", logging.NOTSET)
    assert import_litellm() is fake_litellm
    assert fake_litellm.suppress_debug_info is True
    assert lite_logger.level == logging.WARNING

    monkeypatch.setenv("LITELLM_LOG", "DEBUG")
    lite_logger.setLevel(logging.NOTSET)
    del fake_litellm.suppress_debug_info
    import_litellm()
    assert not hasattr(fake_litellm, "suppress_debug_info")
    assert lite_logger.level == logging.NOTSET
