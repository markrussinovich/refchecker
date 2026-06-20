"""Unit tests for the multi-detector registry + multi-run compare API (R61/I1).

Covers, with NO network and NO real ML weights:

* registry shape + honesty invariants (Tier-2 heavy detectors are not
  installable / never selectable to run),
* per-detector install / status / remove using a mocked HF snapshot_download,
* per-arch head selection (the registry's ``head`` field drives the loader),
* multi-run aggregation + per-sentence agreement + pairwise-agreement math,
* uninstalled / non-installable detectors ABSTAIN (never a fabricated number),
* backward-compat: the default 'desklib' key delegates to the legacy
  single-detector functions and shares its on-disk path.
"""

import sys

import pytest

from refchecker.ai_detection import model_manager as mm
from refchecker.ai_detection import multi_run


# ── Registry shape + honesty invariants ────────────────────────────────────

def test_registry_has_required_tier1_detectors():
    reg = mm.DETECTOR_REGISTRY
    for key in ("desklib", "superannotate", "e5-small-lora", "mage"):
        assert key in reg, f"missing Tier-1 detector {key}"
        e = reg[key]
        assert e["tier"] == 1
        assert e["installable"] is True
        assert e["heavy"] is False
        # Real metadata must be present (no None placeholders for size/license).
        assert isinstance(e["size_mb"], (int, float)) and e["size_mb"] > 0
        assert e["license"] and isinstance(e["license"], str)
        assert e["repo"] and e["raid_note"]


def test_default_detector_is_desklib_and_repo_backward_compatible():
    assert mm.DEFAULT_DETECTOR == "desklib"
    # The desklib registry entry's repo must equal the legacy MODEL_REPO const,
    # and its on-disk dir must equal the legacy model_path() — so an existing
    # install is picked up by the new API unchanged.
    assert mm.DETECTOR_REGISTRY["desklib"]["repo"] == mm.MODEL_REPO
    assert mm.detector_dir("desklib") == mm.model_path()


def test_registry_per_arch_heads():
    # Each Tier-1 detector declares the head the loader must use.
    assert mm.DETECTOR_REGISTRY["desklib"]["head"] == "custom_mean_pool"
    for k in ("superannotate", "e5-small-lora", "mage"):
        assert mm.DETECTOR_REGISTRY[k]["head"] == "sequence_classification"


def test_tier2_detectors_listed_but_not_installable():
    # Honesty: heavy zero-shot/metric detectors are listed for transparency but
    # are NOT installable and NEVER runnable (no fabricated support).
    for key in ("binoculars", "fast-detectgpt", "radar"):
        e = mm.DETECTOR_REGISTRY[key]
        assert e["tier"] == 2
        assert e["installable"] is False
        assert e["heavy"] is True
    assert "desklib" in mm.runnable_detector_keys()
    assert "binoculars" not in mm.runnable_detector_keys()


def test_registry_status_shape():
    st = mm.registry_status()
    assert st["default"] == "desklib"
    assert isinstance(st["detectors"], list) and st["detectors"]
    keys = {d["key"] for d in st["detectors"]}
    assert {"desklib", "superannotate", "mage"} <= keys
    for d in st["detectors"]:
        for f in ("key", "repo", "arch", "head", "tier", "size_mb",
                  "license", "installable", "installed", "state"):
            assert f in d, f"detector status missing {f}"


def test_unknown_detector_is_graceful():
    assert mm.get_detector("does-not-exist") is None
    st = mm.detector_status("does-not-exist")
    assert st["installed"] is False and st["installable"] is False


# ── Per-detector install / status / remove (mocked HF) ──────────────────────

@pytest.fixture
def detector_dir_env(monkeypatch, tmp_path):
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_MODEL_DIR", str(tmp_path))
    # Deps are present so install isn't short-circuited by a missing runtime.
    monkeypatch.setattr(mm, "deps_available", lambda: True)
    return tmp_path


def _install_via_mock(monkeypatch, key, *, weight_bytes=60 * 1024 * 1024):
    """Drive a per-detector download with snapshot_download + HfApi mocked.

    The fake snapshot_download writes config.json + a weight file into the
    detector dir; the size metadata fetch reports a matching expected size.
    """
    dest = mm.detector_dir(key)

    def fake_snapshot_download(repo_id, local_dir, **kw):
        import os
        os.makedirs(local_dir, exist_ok=True)
        with open(os.path.join(local_dir, "config.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(local_dir, "model.safetensors"), "wb") as f:
            f.write(b"x" * weight_bytes)

    fake_hub = type(sys)("huggingface_hub")
    fake_hub.snapshot_download = fake_snapshot_download

    class _Sib:
        def __init__(self, size):
            self.size = size

    class _Info:
        siblings = [_Sib(weight_bytes)]
        sha = "deadbeef"

    class _HfApi:
        def model_info(self, repo, **kw):
            return _Info()

    fake_hub.HfApi = _HfApi
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)


def test_install_status_remove_roundtrip_mocked(monkeypatch, detector_dir_env):
    key = "superannotate"
    _install_via_mock(monkeypatch, key)
    assert mm.is_detector_installed(key) is False
    res = mm.start_detector_download(key)
    # Download runs on a background thread — wait for it.
    t = mm._detector_threads.get(key)
    if t:
        t.join(timeout=20)
    assert mm.is_detector_installed(key) is True
    st = mm.detector_status(key)
    assert st["installed"] is True
    assert st["state"] == "installed"
    assert st["size_bytes"] > 0
    # Remove it.
    mm.delete_detector(key)
    assert mm.is_detector_installed(key) is False


def test_install_refuses_tier2_without_download(monkeypatch, detector_dir_env):
    res = mm.start_detector_download("binoculars")
    assert res["installable"] is False
    assert res["state"] in ("unavailable", "error")
    assert mm.is_detector_installed("binoculars") is False


def test_install_refuses_when_deps_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("REFCHECKER_AI_DETECTION_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(mm, "deps_available", lambda: False)
    res = mm.start_detector_download("mage")
    assert res["state"] == "error"
    assert res["error"] == "deps_not_installed"


def test_desklib_install_delegates_to_legacy(monkeypatch, detector_dir_env):
    # The default key must route through the legacy start_download/delete_model
    # state machine, not the per-detector one.
    called = {"start": 0, "delete": 0}
    monkeypatch.setattr(mm, "start_download", lambda: called.__setitem__("start", called["start"] + 1))
    monkeypatch.setattr(mm, "delete_model", lambda: called.__setitem__("delete", called["delete"] + 1))
    monkeypatch.setattr(mm, "is_model_installed", lambda: False)
    mm.start_detector_download("desklib")
    mm.delete_detector("desklib")
    assert called["start"] == 1 and called["delete"] == 1


# ── Per-arch head selection (mocked engines) ───────────────────────────────

class _FakeEngine:
    """A deterministic stand-in for a loaded detector engine.

    ``score`` returns a per-key constant so the multi-run aggregation + agreement
    math is exercised without any real ML.
    """

    def __init__(self, value):
        self.value = value

    def score(self, text):
        return self.value


def test_load_selects_head_and_caches(monkeypatch, detector_dir_env):
    from refchecker.ai_detection import local_backend
    captured = {}

    def fake_build(model_dir_path, head=None):
        captured["dir"] = str(model_dir_path)
        captured["head"] = head
        return _FakeEngine(0.9)

    monkeypatch.setattr(local_backend, "_build_engine_at", fake_build)
    monkeypatch.setattr(mm, "is_detector_installed", lambda k: True)
    local_backend._engines.clear()

    eng = local_backend.load("superannotate")
    assert isinstance(eng, _FakeEngine)
    # The per-arch head from the registry was threaded to the builder.
    assert captured["head"] == "sequence_classification"
    assert captured["dir"] == str(mm.detector_dir("superannotate"))
    # Cached on second load (builder not called again).
    captured.clear()
    eng2 = local_backend.load("superannotate")
    assert eng2 is eng and "head" not in captured


def test_load_rejects_uninstalled_and_tier2(monkeypatch, detector_dir_env):
    from refchecker.ai_detection import local_backend
    local_backend._engines.clear()
    monkeypatch.setattr(mm, "is_detector_installed", lambda k: False)
    with pytest.raises(FileNotFoundError):
        local_backend.load("mage")
    # Tier-2 / non-installable can never be loaded.
    with pytest.raises(ValueError):
        local_backend.load("binoculars")
    with pytest.raises(ValueError):
        local_backend.load("nope-not-real")


# ── Multi-run aggregation + agreement math ─────────────────────────────────

LONG_PROSE = (
    "The cell membrane regulates the transport of molecules across its lipid "
    "bilayer through a combination of passive diffusion and active transport "
    "mechanisms that depend on embedded protein channels and carrier proteins. "
    "Researchers have studied these processes for decades using a wide variety "
    "of experimental and computational techniques in many laboratories. "
) * 12


def _patch_engines(monkeypatch, scores_by_key):
    """Make local_backend.load return a fixed-score fake engine per key, and
    mark every key installed + deps present."""
    from refchecker.ai_detection import local_backend

    def fake_load(key):
        if key not in scores_by_key:
            raise FileNotFoundError(key)
        return _FakeEngine(scores_by_key[key])

    monkeypatch.setattr(local_backend, "load", fake_load)
    monkeypatch.setattr(mm, "is_detector_installed", lambda k: k in scores_by_key)
    monkeypatch.setattr(mm, "deps_available", lambda: True)


def test_run_detectors_per_detector_scores_and_bands(monkeypatch):
    # desklib scores high (0.95), e5 scores low (0.05) → honest disagreement,
    # NO synthetic ensemble truth.
    _patch_engines(monkeypatch, {"desklib": 0.95, "e5-small-lora": 0.05})
    out = multi_run.run_detectors(LONG_PROSE, ["desklib", "e5-small-lora"])
    dets = {d["key"]: d for d in out["detectors"]}
    assert dets["desklib"]["band"] == "high"
    assert dets["desklib"]["overall_score"] == 0.95
    assert dets["e5-small-lora"]["band"] == "low"
    # No top-level fabricated "ensemble" score exists.
    assert "overall_score" not in out
    assert out["disclaimer"]


def test_run_detectors_comparison_agreement_math(monkeypatch):
    # Two detectors that AGREE (both high) → band_agreement True, pairwise 1.0.
    _patch_engines(monkeypatch, {"desklib": 0.95, "mage": 0.97})
    out = multi_run.run_detectors(LONG_PROSE, ["desklib", "mage"])
    comp = out["comparison"]
    assert set(comp["detectors_compared"]) == {"desklib", "mage"}
    assert comp["band_agreement"] is True
    assert comp["per_sentence"], "per-sentence agreement view must be populated"
    for ps in comp["per_sentence"]:
        assert ps["unanimous"] is True
        assert ps["agreement_count"] == ps["detector_count"]
    assert comp["pairwise_agreement"]
    pa = comp["pairwise_agreement"][0]
    assert pa["agreement"] == 1.0 and pa["shared_sentences"] > 0


def test_run_detectors_records_disagreement(monkeypatch):
    # One high, one low → band_agreement False, pairwise 0.0 (disagreement is
    # signal, surfaced — not hidden behind an averaged number).
    _patch_engines(monkeypatch, {"desklib": 0.95, "e5-small-lora": 0.02})
    out = multi_run.run_detectors(LONG_PROSE, ["desklib", "e5-small-lora"])
    comp = out["comparison"]
    assert comp["band_agreement"] is False
    pa = comp["pairwise_agreement"][0]
    assert pa["agreement"] == 0.0


def test_run_detectors_uninstalled_abstains_no_number(monkeypatch):
    # desklib installed (high); superannotate NOT installed → it ABSTAINS with
    # no score and is excluded from the agreement math.
    _patch_engines(monkeypatch, {"desklib": 0.95})
    out = multi_run.run_detectors(LONG_PROSE, ["desklib", "superannotate"])
    dets = {d["key"]: d for d in out["detectors"]}
    assert dets["superannotate"]["band"] == "unavailable"
    assert dets["superannotate"]["overall_score"] is None
    assert dets["superannotate"]["abstain_reason"] == "model_not_installed"
    # Only the scored detector participates in comparison.
    assert out["comparison"]["detectors_compared"] == ["desklib"]


def test_run_detectors_tier2_key_abstains(monkeypatch):
    _patch_engines(monkeypatch, {"desklib": 0.95})
    out = multi_run.run_detectors(LONG_PROSE, ["desklib", "binoculars"])
    dets = {d["key"]: d for d in out["detectors"]}
    assert dets["binoculars"]["band"] == "unavailable"
    assert dets["binoculars"]["overall_score"] is None
    assert dets["binoculars"]["abstain_reason"] == "detector_not_runnable"


def test_run_detectors_short_body_abstains_all(monkeypatch):
    _patch_engines(monkeypatch, {"desklib": 0.95, "mage": 0.97})
    out = multi_run.run_detectors("too short to assess", ["desklib", "mage"])
    for d in out["detectors"]:
        assert d["band"] in ("inconclusive", "unavailable")
        assert d["overall_score"] is None
    assert out["comparison"]["band_agreement"] is False


def test_run_detectors_accepts_pages_list(monkeypatch):
    _patch_engines(monkeypatch, {"desklib": 0.95})
    pages = [LONG_PROSE[: len(LONG_PROSE) // 2], LONG_PROSE[len(LONG_PROSE) // 2:]]
    out = multi_run.run_detectors(pages, ["desklib"])
    assert out["detectors"][0]["key"] == "desklib"
    assert out["word_count"] > 0


def test_run_detectors_dedupes_and_defaults_keys(monkeypatch):
    _patch_engines(monkeypatch, {"desklib": 0.5})
    # Duplicate keys collapse; empty selection falls back to the default.
    out = multi_run.run_detectors(LONG_PROSE, ["desklib", "desklib", ""])
    assert [d["key"] for d in out["detectors"]] == ["desklib"]
    out2 = multi_run.run_detectors(LONG_PROSE, [])
    assert out2["detectors"][0]["key"] == "desklib"


def test_per_detector_threshold_used_for_band(monkeypatch):
    # A detector with a high own-threshold bands a mid score as medium, while a
    # low-threshold detector would band the same score high. Prove the registry
    # threshold (not a shared global) is what's applied.
    from refchecker.ai_detection import multi_run as mr
    assert mr._band_for_score(0.80, 0.85) == "medium"   # below its 0.85 high cut
    assert mr._band_for_score(0.80, 0.70) == "high"     # above a 0.70 high cut
    assert mr._band_for_score(0.10, 0.85) == "low"


# ── Backward-compat single-detector path (wrapper) ─────────────────────────

def test_wrapper_single_detector_path_unchanged(monkeypatch):
    # With no/one detector selected, _run_ai_detection must NOT invoke the
    # multi-detector compare — the payload stays the single-detector shape.
    import asyncio
    from backend.refchecker_wrapper import ProgressRefChecker
    import refchecker.ai_detection as ai_detection

    captured = {"multi_called": False}

    class FakeResult:
        def to_dict(self):
            return {"band": "low", "backend_used": "local"}

    monkeypatch.setattr(ai_detection, "run_detection", lambda *a, **k: FakeResult())

    def fake_run_detectors(*a, **k):
        captured["multi_called"] = True
        return {"detectors": []}

    monkeypatch.setattr(ai_detection, "run_detectors", fake_run_detectors)

    checker = ProgressRefChecker.__new__(ProgressRefChecker)
    checker.ai_detection_enabled = True
    checker.ai_detection_backend = "local"
    checker.ai_detection_detectors = []          # no selection → single path
    checker.check_id = 7
    checker.progress_callback = None
    checker.hallucination_provider = None
    checker.hallucination_model = None
    checker.hallucination_api_key = None
    checker.hallucination_endpoint = None
    checker.llm_provider = None
    checker.llm_model = None
    checker.api_key = None
    checker.endpoint = None
    checker.ai_detection_service = "pangram"
    checker.ai_detection_api_key = None
    checker.ai_detection_consent = False

    payload = asyncio.run(checker._run_ai_detection(LONG_PROSE, "Paper"))
    assert payload["band"] == "low"
    assert "multi" not in payload
    assert captured["multi_called"] is False


def test_wrapper_multi_detector_attaches_comparison(monkeypatch):
    import asyncio
    from backend.refchecker_wrapper import ProgressRefChecker
    import refchecker.ai_detection as ai_detection

    class FakeResult:
        def to_dict(self):
            return {"band": "high", "backend_used": "local"}

    monkeypatch.setattr(ai_detection, "run_detection", lambda *a, **k: FakeResult())
    monkeypatch.setattr(
        ai_detection, "run_detectors",
        lambda *a, **k: {"detectors": [{"key": "desklib"}, {"key": "mage"}],
                         "comparison": {"band_agreement": True}},
    )

    checker = ProgressRefChecker.__new__(ProgressRefChecker)
    checker.ai_detection_enabled = True
    checker.ai_detection_backend = "local"
    checker.ai_detection_detectors = ["desklib", "mage"]   # >1 → multi path
    checker.check_id = 8
    checker.progress_callback = None
    checker.hallucination_provider = None
    checker.hallucination_model = None
    checker.hallucination_api_key = None
    checker.hallucination_endpoint = None
    checker.llm_provider = None
    checker.llm_model = None
    checker.api_key = None
    checker.endpoint = None
    checker.ai_detection_service = "pangram"
    checker.ai_detection_api_key = None
    checker.ai_detection_consent = False

    payload = asyncio.run(checker._run_ai_detection(LONG_PROSE, "Paper"))
    assert payload["band"] == "high"          # top-level stays single-detector
    assert "multi" in payload
    assert payload["multi"]["comparison"]["band_agreement"] is True
