"""R61 — the FE-selected multi-detector run-set must reach run_detectors.

Two layers are covered:

1. FastAPI surface (the gap that was fixed): the check request models carry an
   ``ai_detection_detectors`` field and ``run_check`` carries the matching
   parameter, so the value the frontend sends is actually threaded through to
   the wrapper rather than silently dropped.

2. Wrapper behavior: ``_run_ai_detection`` with >1 selected detector attaches a
   side-by-side ``multi`` payload (``detectors: [...]`` + ``comparison``) via
   ``run_detectors``; a single/empty selection keeps the existing
   single-detector payload byte-for-byte (backward compat for desklib users).
"""
import asyncio
import inspect

import refchecker.ai_detection as aidet
from backend.refchecker_wrapper import ProgressRefChecker


# --------------------------------------------------------------------------- #
# 1. FastAPI passthrough surface
# --------------------------------------------------------------------------- #

def test_request_models_and_run_check_expose_ai_detection_detectors():
    import backend.main as m

    # JSON request models (batch URLs + the sibling model) carry the field.
    assert "ai_detection_detectors" in m.BatchUrlsRequest.model_fields

    # run_check forwards it down to the wrapper.
    assert "ai_detection_detectors" in inspect.signature(m.run_check).parameters

    # The multipart check endpoints declare it as a (repeatable) Form param.
    form_endpoints = [
        o for o in vars(m).values()
        if inspect.isfunction(o)
        and "ai_detection_enabled" in inspect.signature(o).parameters
        and "ai_detection_service" in inspect.signature(o).parameters
    ]
    assert form_endpoints, "expected at least one ai-detection check endpoint"
    assert all(
        "ai_detection_detectors" in inspect.signature(o).parameters
        for o in form_endpoints
    ), "a check endpoint accepts ai-detection params but not ai_detection_detectors"


# --------------------------------------------------------------------------- #
# 2. Wrapper multi-run behavior
# --------------------------------------------------------------------------- #

class _FakeSingleResult:
    def to_dict(self):
        return {"backend": "local", "band": "low", "score": 0.12}


def _make_wrapper(detectors):
    w = object.__new__(ProgressRefChecker)
    w.ai_detection_enabled = True
    w.ai_detection_backend = "local"
    w.ai_detection_detectors = list(detectors)
    w.check_id = 1

    async def _noop_emit(*_a, **_k):
        return None

    w.emit_progress = _noop_emit
    return w


def test_two_installed_detectors_produce_compare_payload(monkeypatch):
    """>1 detector → payload carries multi.detectors[...] + multi.comparison."""
    calls = {}

    def fake_run_detection(text, *, title=None, backend="local", check_id=None, **opts):
        return _FakeSingleResult()

    def fake_run_detectors(text, keys):
        calls["keys"] = list(keys)
        return {
            "detectors": [
                {"key": "desklib", "score": 0.12, "band": "low"},
                {"key": "e5-small-lora", "score": 0.81, "band": "high"},
            ],
            "comparison": {"agreement": 0, "per_sentence": []},
        }

    monkeypatch.setattr(aidet, "run_detection", fake_run_detection, raising=False)
    monkeypatch.setattr(aidet, "run_detectors", fake_run_detectors, raising=False)

    wrapper = _make_wrapper(["desklib", "e5-small-lora"])
    payload = asyncio.run(wrapper._run_ai_detection("Some manuscript body text.", "A Title"))

    # The chosen run-set actually reached run_detectors...
    assert calls["keys"] == ["desklib", "e5-small-lora"]
    # ...and the compare summary is attached honestly.
    assert "multi" in payload
    assert [d["key"] for d in payload["multi"]["detectors"]] == ["desklib", "e5-small-lora"]
    assert "comparison" in payload["multi"]
    # Top-level result stays the single configured detector (backward compat).
    assert payload["band"] == "low"


def test_single_detector_keeps_legacy_payload_and_skips_run_detectors(monkeypatch):
    """1 (or 0) detector → no multi payload, run_detectors never called."""
    def fake_run_detection(text, *, title=None, backend="local", check_id=None, **opts):
        return _FakeSingleResult()

    def boom_run_detectors(text, keys):  # pragma: no cover - must not run
        raise AssertionError("run_detectors must not be called for a single detector")

    monkeypatch.setattr(aidet, "run_detection", fake_run_detection, raising=False)
    monkeypatch.setattr(aidet, "run_detectors", boom_run_detectors, raising=False)

    wrapper = _make_wrapper(["desklib"])
    payload = asyncio.run(wrapper._run_ai_detection("Some manuscript body text.", "A Title"))

    assert "multi" not in payload
    assert payload["band"] == "low"
