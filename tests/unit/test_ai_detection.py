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
import sys
import importlib

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
    assert argv[0] == "install"
    assert "--no-input" in argv and "--target" in argv
    assert argv[argv.index("--target") + 1] == str(tmp_path)
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


def test_runtime_status_includes_live_log(monkeypatch, tmp_path):
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_RUNTIME_DIR", str(tmp_path))
    _rt._log_reset()
    _rt._log_line("hello-debug-line")
    st = _rt.runtime_status()
    assert isinstance(st.get("log"), list)
    assert any("hello-debug-line" in line for line in st["log"])


def test_log_writer_streams_into_buffer():
    _rt._log_reset()
    w = _rt._LogWriter()
    w.write("downloading torch...\n")
    assert any("downloading torch" in line for line in _rt.get_log())


def test_diagnostics_ring_buffer_newest_first():
    from refchecker.ai_detection import diagnostics
    diagnostics.clear()
    diagnostics.record({"backend": "local", "outcome": "low"})
    diagnostics.record({"backend": "api", "outcome": "high"})
    evs = diagnostics.events()
    assert evs[0]["backend"] == "api" and evs[1]["backend"] == "local"
    assert all("ts" in e for e in evs)


def test_clean_target_wipes_but_keeps_pip_pyz(monkeypatch, tmp_path):
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_RUNTIME_DIR", str(tmp_path))
    (tmp_path / "torch").mkdir()
    (tmp_path / "junk.txt").write_text("x")
    (tmp_path / "pip.pyz").write_bytes(b"PK")
    _rt._clean_target()
    assert not (tmp_path / "torch").exists()
    assert not (tmp_path / "junk.txt").exists()
    assert (tmp_path / "pip.pyz").exists()  # the downloaded pip is preserved


def test_pip_argv_has_upgrade_and_cli_entry_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_RUNTIME_DIR", str(tmp_path))
    assert "--upgrade" in _rt._pip_argv("torch")  # re-install replaces, not skips
    assert callable(_rt.run_pip_cli)               # bundle --pip-install entry


def test_runtime_finder_overrides_partial_shadow(tmp_path):
    """Reproduce the PyInstaller partial-shadow (a `pkg` with no `pkg/auto.py`
    pre-cached, mimicking the frozen bundle) and prove the finder + sys.modules
    eviction make the complete runtime copy win so `pkg.auto` resolves."""
    pkg = "_rcshadowpkg"
    bundle, runtime = tmp_path / "bundle", tmp_path / "runtime"
    (bundle / pkg).mkdir(parents=True)
    (bundle / pkg / "__init__.py").write_text("VER = 'bundle'\n")        # partial: no auto.py
    (runtime / pkg).mkdir(parents=True)
    (runtime / pkg / "__init__.py").write_text("VER = 'runtime'\n")
    (runtime / pkg / "auto.py").write_text("X = 1\n")                    # complete

    finder = None
    orig_path = list(sys.path)
    try:
        # mimic server startup importing the PARTIAL copy first (caches it)
        sys.path.insert(0, str(bundle))
        importlib.invalidate_caches()
        assert importlib.import_module(pkg).VER == "bundle"
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(pkg + ".auto")  # the shadow bug, reproduced

        # apply the fix exactly as runtime_manager does
        finder = _rt._RuntimeTargetFinder(str(runtime), frozenset({pkg}))
        sys.meta_path.insert(0, finder)
        sys.path.append(str(runtime))               # append, not insert(0)
        for n in [k for k in list(sys.modules) if k == pkg or k.startswith(pkg + ".")]:
            del sys.modules[n]
        importlib.invalidate_caches()

        assert importlib.import_module(pkg).VER == "runtime"   # finder won over the partial
        importlib.import_module(pkg + ".auto")                 # previously-missing submodule resolves
    finally:
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
        for n in [k for k in list(sys.modules) if k == pkg or k.startswith(pkg + ".")]:
            del sys.modules[n]
        sys.path[:] = orig_path
        importlib.invalidate_caches()


def test_model_status_includes_log(monkeypatch, tmp_path):
    from refchecker.ai_detection import model_manager as _mm
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_MODEL_DIR", str(tmp_path))
    _mm._log_reset()
    _mm._log_line("hello-model-log")
    st = _mm.model_status()
    assert isinstance(st.get("log"), list)
    assert any("hello-model-log" in line for line in st["log"])


def test_model_download_drops_removed_symlinks_kwarg():
    # local_dir_use_symlinks was REMOVED in huggingface_hub 1.x → it must not be
    # passed (it raised TypeError and made the download fail silently), and the
    # worker must make the pip-installed runtime importable first.
    import inspect
    from refchecker.ai_detection import model_manager as _mm
    src = inspect.getsource(_mm._download_worker)
    assert "local_dir_use_symlinks=" not in src  # the removed kwarg is not passed
    assert "ensure_on_path" in src


def test_model_download_subprocess_and_xet_off():
    # The desktop download runs in a clean subprocess (xet truly off, set before
    # huggingface_hub import); the supervisor resumes via re-run rather than
    # SIGKILLing hf_hub mid-stream (which corrupts resume).
    import inspect
    from refchecker.ai_detection import model_manager as _mm
    assert callable(_mm.run_hf_download_cli)
    cli = inspect.getsource(_mm.run_hf_download_cli)
    assert 'HF_HUB_DISABLE_XET' in cli and 'hf_xet' in cli  # xet disabled + blocked
    sup = inspect.getsource(_mm._download_supervised)
    assert '--hf-download' in sup and 'resuming' in sup


def test_model_installed_requires_completion_marker(monkeypatch, tmp_path):
    # A weight file that merely EXISTS must not count as installed — only after
    # the verified-complete marker is written (guards against truncated partials).
    from refchecker.ai_detection import model_manager as _mm
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_MODEL_DIR", str(tmp_path))
    d = _mm.model_path()
    d.mkdir(parents=True)
    (d / "config.json").write_text("{}")
    (d / "model.safetensors").write_bytes(b"x" * (60 * 1024 * 1024))  # 60 MB "weight"
    assert _mm.is_model_installed() is False          # no marker → not installed
    assert _mm._model_complete(0) is True             # 60 MB passes the no-expected floor
    assert _mm._model_complete(200 * 1024 * 1024) is False  # but not vs a 200 MB expected
    _mm._write_ok_marker()
    assert _mm.is_model_installed() is True            # marker present → installed


def test_runtime_finder_default_deny(tmp_path):
    # non-allowlisted names and submodules are never claimed (server untouched)
    f = _rt._RuntimeTargetFinder(str(tmp_path), frozenset({"torch"}))
    assert f.find_spec("httpx") is None      # not allowlisted → server keeps its copy
    assert f.find_spec("torch.nn") is None    # submodule → follows parent __path__
    assert "tqdm" in _rt._ML_ALLOWLIST and "httpx" not in _rt._ML_ALLOWLIST


def test_run_detection_records_a_diagnostic_event():
    from refchecker.ai_detection import diagnostics
    diagnostics.clear()
    # unknown backend → graceful unavailable, and still recorded
    run_detection("some text", backend="nope-not-real")
    evs = diagnostics.events()
    assert evs and evs[0]["backend"] == "nope-not-real"
    assert evs[0]["outcome"] in ("unavailable", "error")
