"""Unit tests for the Anthropic reference-extraction provider request shape.

anthropic SDK 1.x removed ``temperature`` / ``top_p`` / ``top_k`` from
``messages.create()`` (passing one raises ``TypeError``), and Opus 4.7+
reject sampling parameters server-side. Temperature is therefore sent via
``extra_body`` only for models that still accept it. Uses a MOCK client:
no network, no real keys.
"""

from types import SimpleNamespace

import pytest

from refchecker.llm.providers import AnthropicProvider, _anthropic_accepts_temperature


class _FakeMessages:
    def __init__(self, capture):
        self._capture = capture

    def create(self, **kwargs):
        self._capture.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


def _call(model):
    capture = {}
    provider = AnthropicProvider({"api_key": "test-key", "model": model, "temperature": 0.1})
    provider.client = SimpleNamespace(messages=_FakeMessages(capture))
    assert provider._call_llm("Respond with only the word 'ok'.") == "ok"
    return provider, capture


@pytest.mark.parametrize("model, accepts", [
    ("claude-sonnet-4-6", True),
    ("claude-haiku-4-5", True),
    ("claude-opus-4-1-20250805", True),
    ("claude-sonnet-4-20250514", True),
    ("claude-3-5-sonnet-latest", True),
    ("claude-3-haiku-20240307", True),
    ("anthropic.claude-sonnet-4-6", True),
    ("claude-opus-4-5@20251101", True),
    ("claude-opus-4-7", False),
    ("claude-opus-4-7[1m]", False),
    ("claude-opus-4-8", False),
    ("claude-sonnet-5", False),
    ("claude-opus-5-5", False),
    ("claude-fable-5-1", False),
    ("anthropic.claude-opus-5-5", False),
    ("my-custom-alias", False),
    ("", False),
])
def test_anthropic_accepts_temperature(model, accepts):
    assert _anthropic_accepts_temperature(model) is accepts


def test_call_llm_sends_temperature_via_extra_body_for_older_models():
    provider, capture = _call("claude-sonnet-4-6")

    # Never as a top-level kwarg: SDK 1.x raises TypeError for it.
    for param in ("temperature", "top_p", "top_k"):
        assert param not in capture
    assert capture["extra_body"] == {"temperature": 0.1}
    assert capture["model"] == "claude-sonnet-4-6"
    assert capture["max_tokens"] == provider.max_tokens
    assert capture["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_call_llm_omits_temperature_for_newer_models():
    _, capture = _call("claude-opus-5-5")

    for param in ("temperature", "top_p", "top_k", "extra_body"):
        assert param not in capture
    assert capture["model"] == "claude-opus-5-5"
