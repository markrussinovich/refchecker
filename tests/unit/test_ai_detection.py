"""Unit tests for the AI-generated-text detection package.

These cover the honesty policy (banding, abstention, clamping) and the
graceful-degradation contract — backends must return a result, never raise,
when their dependency / model / key is missing. No network or ML deps needed.
"""

import pytest

from refchecker.ai_detection import base, run_detection


LONG_PROSE = (
    "The cell membrane regulates the transport of molecules across its "
    "lipid bilayer through a combination of passive diffusion and active "
    "transport mechanisms that depend on embedded protein channels. "
) * 30


def test_banding_thresholds():
    assert base.band_from_probability(0.95) == base.BAND_HIGH
    assert base.band_from_probability(0.50) == base.BAND_MEDIUM
    assert base.band_from_probability(0.10) == base.BAND_LOW


def test_abstain_too_short():
    assert base.should_abstain("only a few words here") == "too_short"


def test_abstain_technical_section():
    math_heavy = "x = 3.14 + alpha^2 / beta - gamma * 2 == 0 ; " * 80
    assert base.should_abstain(math_heavy) == "technical_section"


def test_long_prose_is_assessable():
    assert base.count_words(LONG_PROSE) >= base.MIN_WORDS
    assert base.should_abstain(LONG_PROSE) is None


def test_windows_clear_reliability_floor():
    windows = base.iter_windows(LONG_PROSE)
    assert windows
    assert all(base.count_words(w) >= base.MIN_WORDS for w in windows)


def test_combine_bands_is_conservative():
    # AND-logic: any disagreement demotes; high only when all agree.
    assert base.combine_bands_and(["high", "medium"]) == "medium"
    assert base.combine_bands_and(["high", "high"]) == "high"
    assert base.combine_bands_and(["low", "high"]) == "low"
    # Abstain dominates: any abstaining backend demotes to inconclusive.
    assert base.combine_bands_and(["high", "inconclusive"]) == "inconclusive"
    assert base.combine_bands_and(["high", "unavailable"]) == "inconclusive"
    assert base.combine_bands_and(["inconclusive", "unavailable"]) == "inconclusive"


def test_clamp_only_lowers_severity():
    # An explanation backend may lower but never raise the calibrated band.
    assert base.clamp_not_above("medium", "high") == "medium"
    assert base.clamp_not_above("high", "low") == "low"
    assert base.clamp_not_above("low", "medium") == "low"


def test_local_backend_unavailable_without_model():
    r = run_detection(LONG_PROSE, title="t", backend="local")
    assert r.band == base.BAND_UNAVAILABLE
    assert r.abstain_reason in ("model_not_installed", "deps_not_installed")
    assert r.disclaimer  # honesty disclaimer always present


def test_llm_backend_unavailable_without_key():
    r = run_detection(LONG_PROSE, title="t", backend="llm-judge",
                      provider="anthropic", api_key=None)
    assert r.band == base.BAND_UNAVAILABLE
    assert r.abstain_reason == "llm_not_configured"


def test_api_backend_requires_consent():
    r = run_detection(LONG_PROSE, backend="api", service="pangram",
                      api_key="x", consent=False)
    assert r.band == base.BAND_UNAVAILABLE
    assert r.abstain_reason == "consent_required"


def test_unknown_backend_is_graceful():
    r = run_detection(LONG_PROSE, backend="does-not-exist")
    assert r.band == base.BAND_UNAVAILABLE


def test_result_serialization_shape():
    r = run_detection(LONG_PROSE, backend="local")
    d = r.to_dict()
    for key in ("band", "overall_score", "spans", "disclaimer",
                "abstain_reason", "operating_point", "backend_used"):
        assert key in d


def test_never_emits_binary_verdict_strings():
    # The disclaimer must not claim authorship or a probability of guilt.
    text = base.DISCLAIMER.lower()
    assert "not" in text and "sole" in text


@pytest.mark.parametrize("score,expected", [
    (0.0, base.BAND_LOW),
    (0.29, base.BAND_LOW),
    (0.30, base.BAND_MEDIUM),
    (0.84, base.BAND_MEDIUM),
    (0.85, base.BAND_HIGH),
    (1.0, base.BAND_HIGH),
])
def test_band_boundaries(score, expected):
    assert base.band_from_probability(score) == expected


def test_merged_trailing_window_is_capped():
    # No emitted window exceeds the encoder budget (1.5x the window size).
    words = " ".join("word%d" % i for i in range(900))
    windows = base.iter_windows(words, window_words=350, overlap=0.5)
    assert windows
    assert all(len(w.split()) <= int(350 * 1.5) for w in windows)


def test_trailing_window_above_floor_is_not_dropped():
    # A ~300-word tail clears MIN_WORDS, so it must be emitted as its own
    # window (covering the document end) rather than silently dropped — else
    # up to ~19% of the body would be excluded from the score-driving mean.
    n = 650
    words = ["word%d" % i for i in range(n)]
    windows = base.iter_windows(" ".join(words), window_words=350, overlap=0.5)
    # The final word of the document must appear in the last window.
    assert words[-1] in windows[-1].split()


def test_subfloor_tail_is_merged_or_dropped_not_emitted_alone():
    # A genuinely short tail (< MIN_WORDS) must never become its own window.
    n = 360  # windows: [0:350] then a 10-word tail
    words = " ".join("word%d" % i for i in range(n))
    windows = base.iter_windows(words, window_words=350, overlap=0.5)
    assert all(base.count_words(w) >= base.MIN_WORDS for w in windows)


def test_ai_positive_index_resolution():
    from refchecker.ai_detection.local_backend import _ai_positive_index
    # AI at index 0
    assert _ai_positive_index({0: "AI", 1: "Human"}) == 0
    assert _ai_positive_index({0: "Fake", 1: "Real"}) == 0
    assert _ai_positive_index({0: "human", 1: "ai-generated"}) == 1
    assert _ai_positive_index({0: "machine-generated", 1: "human-written"}) == 0
    # Ambiguous → None (caller must abstain, never guess)
    assert _ai_positive_index({0: "LABEL_0", 1: "LABEL_1"}) is None
    assert _ai_positive_index({0: "positive", 1: "negative"}) is None
    assert _ai_positive_index(None) is None
    # Multiple AI-ish labels → ambiguous → None
    assert _ai_positive_index({0: "ai", 1: "gpt", 2: "human"}) is None


def test_llm_judge_standalone_capped_at_medium():
    # The honesty cap: a standalone (no-API-key) llm-judge can never emit high.
    # We can't call a real LLM, but the cap mechanism is clamp_not_above, which
    # we assert never lets a band exceed medium.
    assert base.clamp_not_above(base.BAND_MEDIUM, base.BAND_HIGH) == base.BAND_MEDIUM
    assert base.clamp_not_above(base.BAND_MEDIUM, base.BAND_MEDIUM) == base.BAND_MEDIUM
    assert base.clamp_not_above(base.BAND_MEDIUM, base.BAND_LOW) == base.BAND_LOW


def test_api_cost_estimate():
    assert base.estimate_api_cost("pangram", 2000) == 0.1
    assert base.estimate_api_cost("gptzero", 1000) == 0.015
    assert base.estimate_api_cost("unknown", 1000) == 0.0
    assert base.estimate_api_cost("pangram", 0) == 0.0


def test_api_score_coercion_rejects_out_of_range():
    # A malformed out-of-[0,1] score must NOT band 'high' — it degrades to None
    # (insufficient_signal), never a fabricated accusation.
    from refchecker.ai_detection.api_backend import _coerce_score
    assert _coerce_score(0.9) == 0.9
    assert _coerce_score(0.0) == 0.0
    assert _coerce_score(1.0) == 1.0
    assert _coerce_score(85) is None        # 0-100 scale leak
    assert _coerce_score(1.5) is None
    assert _coerce_score(-0.1) is None
    assert _coerce_score("0.7") == 0.7
    assert _coerce_score("bad") is None
    assert _coerce_score(None) is None


def test_record_detection_usage_attributes_to_check_and_flow():
    from refchecker.llm import usage_tracker
    usage_tracker.reset("ut-test")
    base.record_detection_usage("ut-test", "local:desklib", input_tokens=500, cost_usd=0.0)
    base.record_detection_usage("ut-test", "api:pangram", input_tokens=2000,
                                cost_usd=base.estimate_api_cost("pangram", 2000))
    snap = usage_tracker.snapshot("ut-test")
    assert "ai_detection" in snap["by_flow"]
    assert snap["by_flow"]["ai_detection"]["input_tokens"] == 2500
    assert round(snap["cost_usd"], 4) == 0.1


# ── runtime_manager: optional inference-runtime install (no network) ────────

import sys as _sys

from refchecker.ai_detection import runtime_manager as _rt


def test_runtime_dir_prefers_explicit_then_data_then_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("REFCHECKER_DATA_DIR", str(tmp_path / "data"))
    assert _rt.runtime_dir() == tmp_path / "rt"
    monkeypatch.delenv("REFCHECKER_AI_DETECTION_RUNTIME_DIR", raising=False)
    assert _rt.runtime_dir() == tmp_path / "data" / "ai-detection-runtime"
    monkeypatch.delenv("REFCHECKER_DATA_DIR", raising=False)
    monkeypatch.setenv("REFCHECKER_CACHE_DIR", str(tmp_path / "cache"))
    assert _rt.runtime_dir() == tmp_path / "cache" / "ai-detection-runtime"


def test_pip_argv_torch_targets_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_RUNTIME_DIR", str(tmp_path))
    argv = _rt._pip_argv("torch")
    assert argv[:3] == ["install", "--no-input", "--target"]
    assert str(tmp_path) in argv
    assert "torch" in argv and "transformers" in argv


def test_pip_argv_cpu_torch_index_off_mac(monkeypatch, tmp_path):
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(_rt.sys, "platform", "linux")
    assert "https://download.pytorch.org/whl/cpu" in _rt._pip_argv("torch")
    # the onnx variant never pulls the torch index
    assert "https://download.pytorch.org/whl/cpu" not in _rt._pip_argv("onnx")


def test_pip_argv_frozen_forces_binary_only(monkeypatch, tmp_path):
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(_rt, "is_frozen", lambda: True)
    assert "--only-binary=:all:" in _rt._pip_argv("torch")


def test_ensure_on_path_noop_when_missing_then_adds_once(monkeypatch, tmp_path):
    target = tmp_path / "rt"
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_RUNTIME_DIR", str(target))
    s = str(target)
    assert s not in _sys.path
    _rt.ensure_on_path()              # dir absent → no-op
    assert s not in _sys.path
    target.mkdir()
    try:
        _rt.ensure_on_path()
        assert _sys.path[0] == s
        _rt.ensure_on_path()          # idempotent
        assert _sys.path.count(s) == 1
    finally:
        while s in _sys.path:
            _sys.path.remove(s)


def test_runtime_status_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_RUNTIME_DIR", str(tmp_path))
    st = _rt.runtime_status()
    for k in ("deps_available", "installed_variant", "default_variant",
              "variants", "is_frozen", "target"):
        assert k in st
    assert st["default_variant"] == "torch"
    assert set(st["variants"]) == {"torch", "onnx"}


def test_start_install_short_circuits_when_runtime_present(monkeypatch, tmp_path):
    # When deps are already importable, start_install must NOT spawn pip — it
    # normalizes a bogus variant and returns status without side effects.
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(_rt, "deps_available", lambda: True)
    res = _rt.start_install("bogus")
    assert res["deps_available"] is True
