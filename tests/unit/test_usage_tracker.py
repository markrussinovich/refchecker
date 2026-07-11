"""R47 — per-check LLM token + $ telemetry.

These lock the backend accounting that drives the on-screen ``LLMUsageBadge``:

  * the per-check ``refchecker.llm.usage_tracker`` accumulates tokens + cost
    keyed by ``(check_id, flow)`` and ``snapshot()`` returns the live totals
    (the shape the ``/history/{id}/llm-usage`` endpoint serves);
  * ``article_chat`` (chat + summarize) now records into the per-check meter so
    follow-up spend ticks the badge up live — previously it only hit the
    process-global tracker and the badge stayed flat;
  * REGRESSION for the previously-$0 hallucination path: the verifier's usage
    helper records real provider tokens under flow ``hallucination`` so the
    badge no longer shows ``$0.000`` after "Halluc checked N".

Honesty: only real provider-returned token counts are recorded; a zero-token
response records nothing (no fabricated cost).
"""

import importlib

import pytest

usage_tracker = importlib.import_module("refchecker.llm.usage_tracker")


@pytest.fixture(autouse=True)
def _isolate_tracker():
    """Each test gets a clean per-check accumulator + no thread-local bleed."""
    usage_tracker._state.clear()
    usage_tracker.set_current_check(None)
    yield
    usage_tracker._state.clear()
    usage_tracker.set_current_check(None)


# --------------------------------------------------------------------------- #
# Provider response fakes (only the attributes the trackers read).            #
# --------------------------------------------------------------------------- #

class _OpenAIUsage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeOpenAIResponse:
    def __init__(self, text, prompt_tokens, completion_tokens):
        self.choices = [type("C", (), {"message": type("M", (), {"content": text})()})()]
        self.usage = _OpenAIUsage(prompt_tokens, completion_tokens)


class _FakeChatCompletions:
    def __init__(self, response):
        self._response = response

    def create(self, **_kwargs):
        return self._response


class _FakeOpenAIClient:
    def __init__(self, response):
        self.chat = type("Chat", (), {"completions": _FakeChatCompletions(response)})()


# --------------------------------------------------------------------------- #
# 1. Per-check accumulation + snapshot totals.                                 #
# --------------------------------------------------------------------------- #

def test_record_accumulates_per_flow_and_snapshot_returns_totals():
    cid = "101"
    usage_tracker.reset(cid)
    usage_tracker.record(check_id=cid, model="gpt-4o-mini", input_tokens=1000,
                         output_tokens=500, flow="extract")
    usage_tracker.record(check_id=cid, model="gpt-4o-mini", input_tokens=2000,
                         output_tokens=400, flow="verify")
    # Second extract call accumulates into the same flow bucket.
    usage_tracker.record(check_id=cid, model="gpt-4o-mini", input_tokens=500,
                         output_tokens=100, flow="extract")

    snap = usage_tracker.snapshot(cid)
    assert snap["input_tokens"] == 3500
    assert snap["output_tokens"] == 1000
    assert snap["calls"] == 3
    # Per-flow split is the badge's hover breakdown.
    assert snap["by_flow"]["extract"]["input_tokens"] == 1500
    assert snap["by_flow"]["extract"]["output_tokens"] == 600
    assert snap["by_flow"]["extract"]["calls"] == 2
    assert snap["by_flow"]["verify"]["input_tokens"] == 2000
    # Real cost, non-zero, sums across flows.
    assert snap["cost_usd"] > 0
    flow_cost = sum(v["cost_usd"] for v in snap["by_flow"].values())
    assert snap["cost_usd"] == pytest.approx(flow_cost)


def test_checks_are_isolated_and_zero_token_records_nothing():
    usage_tracker.reset("A")
    usage_tracker.reset("B")
    usage_tracker.record(check_id="A", model="gpt-4o", input_tokens=100,
                         output_tokens=50, flow="extract")
    # Honesty: a zero-token response must not register a call or cost.
    usage_tracker.record(check_id="A", model="gpt-4o", input_tokens=0,
                         output_tokens=0, flow="verify")

    snap_a = usage_tracker.snapshot("A")
    snap_b = usage_tracker.snapshot("B")
    assert snap_a["calls"] == 1
    assert "verify" not in snap_a["by_flow"]
    # No bleed across checks.
    assert snap_b["input_tokens"] == 0
    assert snap_b["cost_usd"] == 0.0
    assert snap_b["calls"] == 0


def test_snapshot_unknown_check_is_empty_not_error():
    snap = usage_tracker.snapshot("does-not-exist")
    assert snap == {
        "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        "calls": 0, "by_flow": {}, "by_model": {},
    }


# --------------------------------------------------------------------------- #
# 2. article_chat (chat + summarize) records into the per-check meter.         #
# --------------------------------------------------------------------------- #

def _chat_assistant(response, check_id):
    from backend.article_chat import ArticleAssistant
    a = ArticleAssistant(provider="openai", api_key="test-key",
                         model="gpt-4o-mini", check_id=check_id)
    a.client = _FakeOpenAIClient(response)
    return a


def test_summarize_records_under_summarize_flow_for_the_check():
    cid = "555"
    usage_tracker.reset(cid)
    resp = _FakeOpenAIResponse("MOCK SUMMARY", prompt_tokens=1200, completion_tokens=300)
    assistant = _chat_assistant(resp, cid)

    out = assistant.summarize("Grounding paper text.", source="pdf")
    assert out["summary"] == "MOCK SUMMARY"

    snap = usage_tracker.snapshot(cid)
    assert "summarize" in snap["by_flow"]
    assert snap["by_flow"]["summarize"]["input_tokens"] == 1200
    assert snap["by_flow"]["summarize"]["output_tokens"] == 300
    assert snap["cost_usd"] > 0


def test_chat_records_under_chat_flow_and_accumulates_with_summarize():
    cid = "777"
    usage_tracker.reset(cid)
    # Summarize first, then a chat follow-up; the badge must tick up across both.
    sum_resp = _FakeOpenAIResponse("S", prompt_tokens=800, completion_tokens=120)
    _chat_assistant(sum_resp, cid).summarize("text", source="pdf")

    chat_resp = _FakeOpenAIResponse("A", prompt_tokens=400, completion_tokens=60)
    assistant = _chat_assistant(chat_resp, cid)
    out = assistant.chat([{"role": "user", "content": "What is X?"}], "text", source="pdf")
    assert out["answer"] == "A"

    snap = usage_tracker.snapshot(cid)
    assert snap["by_flow"]["summarize"]["input_tokens"] == 800
    assert snap["by_flow"]["chat"]["input_tokens"] == 400
    # Live totals reflect chat + summarize follow-up spend.
    assert snap["input_tokens"] == 1200
    assert snap["output_tokens"] == 180
    assert snap["calls"] == 2


def test_chat_without_check_id_does_not_pollute_default_bucket():
    """Honesty: no check in scope → nothing attributed to the shared bucket."""
    resp = _FakeOpenAIResponse("A", prompt_tokens=300, completion_tokens=40)
    assistant = _chat_assistant(resp, None)
    assistant.summarize("text", source="pdf")
    assert usage_tracker.snapshot("default")["calls"] == 0


# --------------------------------------------------------------------------- #
# 3. REGRESSION — the previously-$0 hallucination path now records real cost.  #
# --------------------------------------------------------------------------- #

def test_hallucination_usage_records_under_hallucination_flow():
    """The hallucination verifier's usage helper must push real provider tokens
    into the per-check meter under flow 'hallucination' — the screenshot case
    where the badge showed $0.000 after "Halluc checked N"."""
    cid = "909"
    usage_tracker.reset(cid)
    usage_tracker.set_current_check(cid)

    from refchecker.llm import providers
    resp = _FakeOpenAIResponse("VERDICT: UNLIKELY", prompt_tokens=2500, completion_tokens=180)
    with usage_tracker.FlowScope("hallucination"):
        providers._track_openai_usage(resp, "gpt-4o-mini")

    snap = usage_tracker.snapshot(cid)
    assert "hallucination" in snap["by_flow"]
    assert snap["by_flow"]["hallucination"]["input_tokens"] == 2500
    assert snap["by_flow"]["hallucination"]["output_tokens"] == 180
    # The regression: cost is now non-zero, not $0.000.
    assert snap["by_flow"]["hallucination"]["cost_usd"] > 0
    assert snap["cost_usd"] > 0


def test_hallucination_verifier_helper_attributes_to_current_check():
    """End-to-end through the verifier's own ``_record_hallucination_usage``
    helper (the function every hallucination LLM call invokes)."""
    cid = "910"
    usage_tracker.reset(cid)
    usage_tracker.set_current_check(cid)

    hv = importlib.import_module("refchecker.llm.hallucination_verifier")
    resp = _FakeOpenAIResponse("VERDICT: LIKELY", prompt_tokens=1500, completion_tokens=90)
    with usage_tracker.FlowScope("hallucination"):
        hv._record_hallucination_usage("openai", "gpt-4o-mini", resp)

    snap = usage_tracker.snapshot(cid)
    assert snap["by_flow"]["hallucination"]["input_tokens"] == 1500
    assert snap["cost_usd"] > 0
