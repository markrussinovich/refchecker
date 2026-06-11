"""Regression tests for R04 — the LLM hallucination-check hang.

These lock in two guarantees so the UI can never wedge forever on
"Checking for hallucination with LLM…":

1. ``LLMHallucinationVerifier`` passes explicit request timeouts to every
   provider client (OpenAI client + Responses call, Anthropic, Google) and
   does NOT chain a second full-length chat call once the per-call wall-clock
   budget is exhausted.

2. The backend wrapper runs the deferred hallucination checks on a dedicated
   bounded ``ThreadPoolExecutor`` and bounds each task with ``asyncio.wait_for``.
   A task that runs *past* its timeout still completes the phase, emits a final
   ``reference_result`` with ``hallucination_check_pending=False``, and leaves
   no reference permanently pending.
"""

import asyncio
import time

import pytest


# ---------------------------------------------------------------------------
# 1. Verifier client timeouts + no-chained-fallback-when-over-budget
# ---------------------------------------------------------------------------

class _DummyResponses:
    def create(self, **kwargs):  # pragma: no cover - not exercised here
        raise AssertionError("should not be called in this test")


class _RecordingOpenAIClient:
    """Stand-in for openai.OpenAI that records the kwargs it was built with
    and the per-call options threaded via .with_options()."""

    last_init_kwargs = None
    last_with_options = None

    def __init__(self, **kwargs):
        _RecordingOpenAIClient.last_init_kwargs = kwargs
        self.responses = _DummyResponses()

    def with_options(self, **opts):
        _RecordingOpenAIClient.last_with_options = opts
        return self


def test_openai_client_gets_explicit_request_timeout(monkeypatch):
    """_init_openai must build the client with an explicit timeout."""
    # openai is an optional, lazily-imported LLM-provider dep (see
    # requirements-dev.txt) — absent on CI, so skip rather than fail there.
    openai = pytest.importorskip("openai")
    from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier

    monkeypatch.setattr(openai, "OpenAI", _RecordingOpenAIClient)

    v = object.__new__(LLMHallucinationVerifier)
    v.provider = "openai"
    v.api_key = "sk-test"
    v.endpoint = None
    v.model = "gpt-4o"
    v._use_responses_api = False
    v._init_openai()

    kwargs = _RecordingOpenAIClient.last_init_kwargs
    assert kwargs is not None
    assert "timeout" in kwargs, "OpenAI client built without an explicit timeout"
    # Vanilla OpenAI (no custom endpoint) should enable the web-search path.
    assert v._use_responses_api is True


def test_openai_responses_call_uses_bounded_per_call_timeout(monkeypatch):
    """The web-search Responses call must thread a bounded per-call timeout."""
    openai = pytest.importorskip("openai")  # optional provider dep — skip on CI
    from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier

    monkeypatch.setattr(openai, "OpenAI", _RecordingOpenAIClient)

    captured = {}

    class _Resp:
        output = []

    def _create(**kwargs):
        return _Resp()

    v = object.__new__(LLMHallucinationVerifier)
    v.provider = "openai"
    v.api_key = "sk-test"
    v.endpoint = None
    v.model = "gpt-4o"
    v._use_responses_api = False
    v._init_openai()
    # Swap in a responses object that records it was reached via with_options.
    v.client.responses.create = _create  # type: ignore[attr-defined]

    # Avoid the real usage-tracking import path during the unit test.
    monkeypatch.setattr(
        "refchecker.llm.hallucination_verifier._record_hallucination_usage",
        lambda *a, **k: None,
    )

    v._call_openai_with_web_search("system", "user")
    assert _RecordingOpenAIClient.last_with_options is not None
    assert "timeout" in _RecordingOpenAIClient.last_with_options
    assert _RecordingOpenAIClient.last_with_options["timeout"] > 0


def test_google_client_gets_explicit_request_timeout(monkeypatch):
    """_init_google must pass http_options timeout (ms) to genai.Client."""
    from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier

    recorded = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            recorded.update(kwargs)

    class _FakeGenAI:
        Client = _FakeClient

    import sys
    import types

    fake_google = types.ModuleType("google")
    fake_google.genai = _FakeGenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", _FakeGenAI)

    v = object.__new__(LLMHallucinationVerifier)
    v.provider = "google"
    v.api_key = "g-test"
    v.endpoint = None
    v.model = "gemini-2.0-flash"
    v._init_google()

    assert "http_options" in recorded, "Google client built without http_options timeout"
    assert recorded["http_options"].get("timeout"), "Google client http_options missing timeout"


def test_call_uncached_does_not_chain_chat_when_over_budget(monkeypatch):
    """Once the per-call budget is exhausted, a web-search failure must NOT
    fall through into a second full-length chat completion — it must re-raise."""
    from refchecker.llm import hallucination_verifier as hv

    # Force the budget to "already elapsed" so the fallback gate is closed.
    monkeypatch.setattr(hv, "_CALL_DEADLINE_S", -1.0)

    v = object.__new__(hv.LLMHallucinationVerifier)
    v.provider = "anthropic"

    chat_called = {"n": 0}

    def _web_search(_s, _u):
        raise RuntimeError("web search blew up")

    def _chat(_s, _u):
        chat_called["n"] += 1
        return ("UNLIKELY", [])

    v._call_anthropic_with_web_search = _web_search
    v._call_anthropic_chat = _chat

    with pytest.raises(RuntimeError):
        v._call_uncached("system", "user")
    assert chat_called["n"] == 0, "chat fallback was chained despite exhausted budget"


def test_call_uncached_chats_when_within_budget(monkeypatch):
    """Within budget, the chat fallback is still used on web-search failure."""
    from refchecker.llm import hallucination_verifier as hv

    monkeypatch.setattr(hv, "_CALL_DEADLINE_S", 600.0)

    v = object.__new__(hv.LLMHallucinationVerifier)
    v.provider = "anthropic"

    chat_called = {"n": 0}
    v._call_anthropic_with_web_search = lambda _s, _u: (_ for _ in ()).throw(RuntimeError("x"))
    v._call_anthropic_chat = lambda _s, _u: (chat_called.__setitem__("n", 1) or ("UNLIKELY", []))

    text, urls = v._call_uncached("system", "user")
    assert chat_called["n"] == 1
    assert text == "UNLIKELY"


# ---------------------------------------------------------------------------
# 2. Backend wrapper — over-timeout task still completes, no ref left pending
# ---------------------------------------------------------------------------

def _make_wrapper_for_timeout(events, ha_timeout, sync_sleep):
    """Build a minimal ProgressRefChecker wired to exercise ONLY the deferred
    hallucination phase of _check_references_parallel.

    - emit_progress is stubbed to capture events (no DB/cache coupling).
    - _check_single_reference_with_limit returns a ready result that the real
      pre-screen routes to the async LLM pool.
    - _run_hallucination_check_sync sleeps PAST ha_timeout to simulate a hang.
    """
    from concurrent.futures import ThreadPoolExecutor
    from backend.refchecker_wrapper import ProgressRefChecker

    w = object.__new__(ProgressRefChecker)
    w.cancel_event = None
    w.hallucination_verifier = object()  # truthy → deferred phase runs
    w._ha_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="halluc-test")
    w._ha_task_timeout = ha_timeout  # injected tiny budget for the test

    async def _emit(event_type, data):
        events.append((event_type, dict(data) if isinstance(data, dict) else data))

    w.emit_progress = _emit

    async def _check_single(reference, idx, total_refs, loop, limiter=None):
        # A result whose only raw error is "unverified" with no authoritative
        # URL → the real _pre_screen_hallucination returns 'needs_async'.
        return {
            "index": idx + 1,
            "title": reference.get("title"),
            "status": "unverified",
            "errors": [{"error_type": "unverified", "error_details": "Could not verify"}],
            "warnings": [],
            "suggestions": [],
            "authoritative_urls": [],
            "_raw_errors": [{"error_type": "unverified", "error_details": "Could not verify"}],
        }

    w._check_single_reference_with_limit = _check_single

    def _sync_hang(result, reference):
        # Simulate a hung LLM call that runs well past the wait_for budget.
        time.sleep(sync_sleep)
        result = dict(result)
        result["hallucination_check_pending"] = False
        return result

    w._run_hallucination_check_sync = _sync_hang
    return w


def test_over_timeout_task_completes_and_clears_pending():
    """An over-budget hallucination task must NOT wedge: the phase completes,
    a final reference_result with hallucination_check_pending=False is emitted,
    and the returned results carry no permanently-pending reference.

    Driven via asyncio.run so the test needs no pytest-asyncio config.
    """

    async def _run():
        events = []
        # Tiny outer budget (0.2s) with a sync task that sleeps 2s → guaranteed timeout.
        wrapper = _make_wrapper_for_timeout(events, ha_timeout=0.2, sync_sleep=2.0)

        references = [{"title": "A definitely-made-up reference", "year": "2024",
                       "authors": ["John Doe", "Jane Smith"]}]

        started = time.monotonic()
        results_list, *_rest = await asyncio.wait_for(
            wrapper._check_references_parallel(references, total_refs=1, extraction_method="regex"),
            timeout=30.0,  # the whole phase must finish well under this
        )
        elapsed = time.monotonic() - started
        wrapper._ha_executor.shutdown(wait=False)
        return results_list, events, elapsed

    results_list, events, elapsed = asyncio.run(_run())

    # Completed within budget (not ~the 2s sync sleep, and nowhere near 150s).
    assert elapsed < 5.0, f"phase took too long ({elapsed:.1f}s) — did it wait on the hung task?"

    # No reference left permanently pending in the settled results.
    assert results_list and results_list[0] is not None
    assert not results_list[0].get("hallucination_check_pending"), \
        "reference left permanently pending after over-timeout"

    # A final per-ref reference_result with the pending flag cleared was emitted.
    ref_events = [d for et, d in events if et == "reference_result" and isinstance(d, dict)]
    assert ref_events, "no reference_result events emitted"
    assert ref_events[-1].get("hallucination_check_pending") is False, \
        "final reference_result did not clear hallucination_check_pending"


def test_hallucination_tasks_use_dedicated_executor():
    """The deferred hallucination tasks must run on self._ha_executor, never
    the shared default executor (None)."""

    async def _run():
        events = []
        # Fast sync task so the success path runs (no timeout); we only care which
        # executor run_in_executor was handed.
        wrapper = _make_wrapper_for_timeout(events, ha_timeout=30.0, sync_sleep=0.0)

        seen_executors = []
        loop = asyncio.get_event_loop()
        real_run_in_executor = loop.run_in_executor

        def _spy_run_in_executor(executor, func, *args):
            if getattr(func, "__name__", "") == "_sync_hang":
                seen_executors.append(executor)
            return real_run_in_executor(executor, func, *args)

        loop.run_in_executor = _spy_run_in_executor
        try:
            references = [{"title": "Another made-up reference", "year": "2024",
                          "authors": ["John Doe", "Jane Smith"]}]
            await wrapper._check_references_parallel(references, total_refs=1, extraction_method="regex")
        finally:
            loop.run_in_executor = real_run_in_executor
            wrapper._ha_executor.shutdown(wait=False)
        return seen_executors, wrapper._ha_executor

    seen_executors, ha_executor = asyncio.run(_run())

    assert seen_executors, "hallucination task never dispatched to an executor"
    assert all(ex is ha_executor for ex in seen_executors), \
        "hallucination task ran on the shared default executor, not the dedicated pool"


# ---------------------------------------------------------------------------
# 3. R54 — the per-request hallucination executor must be closed (no thread leak)
# ---------------------------------------------------------------------------

def test_close_shuts_down_ha_executor():
    """R54: ProgressRefChecker.close() shuts down the dedicated hallucination
    executor so a per-request checker does not leak its worker threads. close()
    must also be idempotent (it is called best-effort from a finally)."""
    wrapper = _make_wrapper_for_timeout([], ha_timeout=30.0, sync_sleep=0.0)
    ex = wrapper._ha_executor
    assert ex is not None, "wrapper has no dedicated hallucination executor"

    wrapper.close()
    with pytest.raises(RuntimeError):
        ex.submit(lambda: None)  # cannot schedule new futures after shutdown

    # Idempotent: a second close() (e.g. double finally) must not raise.
    wrapper.close()


def test_run_check_finally_invokes_checker_close():
    """R54 regression guard: the per-request checker constructed in
    backend/main.run_check must be closed in a finally, so the executor is not
    leaked. Guards against the regression where close() exists but is never
    called from the request path."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "backend" / "main.py").read_text()
    assert "checker = ProgressRefChecker(" in src
    # After the (single) construction site there must be a finally that closes it.
    tail = src[src.index("checker = ProgressRefChecker("):]
    assert "finally:" in tail, "no finally after the checker is constructed"
    assert ".close()" in tail, "checker is never closed after construction (thread leak)"
