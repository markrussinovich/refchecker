"""Download / status / delete for the local AI-text-detection model.

The local detector (desklib DeBERTa) is an **on-demand** download — it is
never bundled into the desktop sidecar (which deliberately excludes torch /
transformers to stay small) and never auto-downloads on first check.  Weights
live under a Tauri-resolved app-data directory passed via an env var, mirroring
the ``REFCHECKER_CACHE_DIR`` convention used elsewhere.

Download runs in a background thread and reports progress through a
module-level status dict, mirroring the existing local-database downloader UX
(poll ``status`` rather than streaming).
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

#: HuggingFace repo for the default local detector (DeBERTa-v3, MIT licence).
#: Kept as a module-level constant for full backward-compatibility: the
#: original single-detector code path (the legacy ``model_*`` /
#: ``start_download`` / ``delete_model`` functions below, the ``local_backend``
#: engine, and the existing ``/api/ai-detection/model/*`` endpoints) all still
#: operate on this one repo. The new multi-detector API layers on top via
#: :data:`DETECTOR_REGISTRY` + the ``detector_*`` functions, and the
#: ``desklib`` registry entry resolves to the SAME on-disk path, so existing
#: installs are picked up unchanged.
MODEL_REPO = "desklib/ai-text-detector-v1.01"
_MODEL_DIRNAME = "desklib-ai-text-detector-v1.01"


# ── Multi-detector registry (R61 / §14) ───────────────────────────────────
#
# Each entry describes ONE installable open-source AI-text detector. Tier-1
# detectors are classifier heads we can actually load + run locally; Tier-2
# ("heavy") metric/zero-shot detectors are listed for honesty but marked
# ``installable: False`` until a real runner exists — they are NEVER selectable
# to run and NEVER report a fabricated number. ``arch``/``head`` drive the
# per-arch loader in ``local_backend``:
#   * ``custom_mean_pool`` — desklib's bespoke mean-pooled DeBERTa + 1-logit head
#   * ``sequence_classification`` — standard ``AutoModelForSequenceClassification``
#     (RoBERTa / e5 / Longformer), sigmoid for 1 logit else softmax[ai_index].
#
# ``threshold`` is this detector's own score→"high" cut point (per-detector, not
# a shared global) so each model is banded on its own calibration. ``size_mb``
# and ``license`` are REAL, research-verified values shown to the user before
# install (no invented numbers). ``raid_note`` is the one-line provenance.

DEFAULT_DETECTOR = "desklib"

DETECTOR_REGISTRY: Dict[str, Dict[str, object]] = {
    "desklib": {
        "key": "desklib",
        "repo": "desklib/ai-text-detector-v1.01",
        "arch": "deberta-v3-large",
        "head": "custom_mean_pool",
        "size_mb": 870,
        "tier": 1,
        "threshold": 0.85,
        "license": "MIT",
        "raid_note": "RAID leaderboard leader among open models (default).",
        "installable": True,
        "heavy": False,
        "label": "Desklib (DeBERTa-v3-large)",
        "dirname": _MODEL_DIRNAME,
    },
    "superannotate": {
        "key": "superannotate",
        "repo": "SuperAnnotate/ai-detector",
        "arch": "roberta-large",
        "head": "sequence_classification",
        "size_mb": 1420,
        "tier": 1,
        "threshold": 0.85,
        "license": "SuperAnnotate (research/eval)",
        "raid_note": "#1 open-source on RAID (late 2024); a low-FPR variant "
                     "(SuperAnnotate/ai-detector-low-fpr) also exists.",
        "installable": True,
        "heavy": False,
        "label": "SuperAnnotate (RoBERTa-Large)",
        "dirname": "superannotate-ai-detector",
    },
    "e5-small-lora": {
        "key": "e5-small-lora",
        "repo": "MayZhou/e5-small-lora-ai-generated-detector",
        "arch": "e5-small",
        "head": "sequence_classification",
        "size_mb": 130,
        "tier": 1,
        "threshold": 0.85,
        "license": "MIT",
        "raid_note": "RAID-optimized, tiny/fast/CPU-friendly (~89% acc; "
                     "ONNX port exists).",
        "installable": True,
        "heavy": False,
        "label": "e5-small + LoRA",
        "dirname": "e5-small-lora-ai-generated-detector",
    },
    "mage": {
        "key": "mage",
        "repo": "yaful/MAGE",
        "arch": "longformer",
        "head": "sequence_classification",
        "size_mb": 570,
        "tier": 1,
        "threshold": 0.85,
        "license": "Apache-2.0",
        "raid_note": "\"Detection in the wild\" (ACL 2024); strong "
                     "out-of-domain.",
        "installable": True,
        "heavy": False,
        "label": "MAGE (Longformer)",
        "dirname": "mage-longformer",
    },
    # ── Tier-2 heavy metric / zero-shot detectors. Listed for honesty; NOT
    # runnable in this build → installable=False so the API refuses to install
    # or select them, and they never report a number. The size/RAM warnings are
    # real so the FE can show why they are opt-in. ────────────────────────────
    "binoculars": {
        "key": "binoculars",
        "repo": "(paired causal LMs)",
        "arch": "metric-zeroshot",
        "head": "metric",
        "size_mb": 14000,
        "tier": 2,
        "threshold": None,
        "license": "see component models",
        "raid_note": "Best-in-class at low FPR; needs TWO LLMs loaded "
                     "simultaneously — heavy RAM/VRAM. Not runnable in this "
                     "build.",
        "installable": False,
        "heavy": True,
        "label": "Binoculars (zero-shot, 2 LLMs)",
        "dirname": "binoculars",
    },
    "fast-detectgpt": {
        "key": "fast-detectgpt",
        "repo": "(GPT-Neo-2.7B scorer)",
        "arch": "metric-zeroshot",
        "head": "metric",
        "size_mb": 11000,
        "tier": 2,
        "threshold": None,
        "license": "see component models",
        "raid_note": "340x faster than DetectGPT; ~11 GB scorer download. Not "
                     "runnable in this build.",
        "installable": False,
        "heavy": True,
        "label": "Fast-DetectGPT (zero-shot)",
        "dirname": "fast-detectgpt",
    },
    "radar": {
        "key": "radar",
        "repo": "TrustSafeAI/RADAR-Vicuna-7B",
        "arch": "vicuna-7b",
        "head": "metric",
        "size_mb": 13000,
        "tier": 2,
        "threshold": None,
        "license": "see model card",
        "raid_note": "Adversarially-trained, robust to paraphrase; 7B-scale "
                     "(~13 GB) download. Not runnable in this build.",
        "installable": False,
        "heavy": True,
        "label": "RADAR (Vicuna-7B)",
        "dirname": "radar-vicuna-7b",
    },
}

#: Detector keys that can actually be installed + run locally (Tier-1).
def runnable_detector_keys() -> list:
    return [k for k, v in DETECTOR_REGISTRY.items() if v.get("installable")]


def get_detector(key: str) -> Optional[Dict[str, object]]:
    """Return the registry entry for ``key`` (None if unknown)."""
    return DETECTOR_REGISTRY.get((key or "").strip().lower())


def detector_dir(key: str) -> Path:
    """On-disk directory for detector ``key``'s weights.

    ``desklib`` resolves to the SAME path the legacy single-detector code uses
    (``model_path()``), so an already-installed desklib model is picked up by
    the new API without a re-download.
    """
    entry = get_detector(key)
    if not entry:
        raise KeyError(f"unknown detector: {key!r}")
    return model_storage_dir() / str(entry["dirname"])

# Background download state (single global model, single download at a time).
_lock = threading.Lock()
_status: Dict[str, object] = {
    "state": "idle",        # idle | downloading | installed | error
    "message": "",
    "repo": MODEL_REPO,
}
_thread: Optional[threading.Thread] = None

# Rolling download log surfaced to the Settings debugger (so a failed model
# download shows the real reason instead of failing silently).
_LOG_CAP = 200
_log: list = []


def _log_line(msg: str) -> None:
    import time
    stamp = time.strftime("%H:%M:%S")
    with _lock:
        for line in (str(msg).splitlines() or [""]):
            _log.append(f"{stamp}  {line}")
        if len(_log) > _LOG_CAP:
            del _log[: len(_log) - _LOG_CAP]


def _log_reset() -> None:
    with _lock:
        _log.clear()


def get_log(limit: int = 120) -> list:
    with _lock:
        return _log[-limit:]


def model_storage_dir() -> Path:
    """Directory that holds downloaded detection models."""
    env = os.environ.get("REFCHECKER_AI_DETECTION_MODEL_DIR")
    if env:
        return Path(env)
    cache = os.environ.get("REFCHECKER_CACHE_DIR")
    if cache:
        return Path(cache) / "ai-detection-models"
    return Path.home() / ".cache" / "refchecker" / "ai-detection-models"


def model_path() -> Path:
    """Filesystem path where the default local model is installed."""
    return model_storage_dir() / _MODEL_DIRNAME


_WEIGHT_FILES = ("model.onnx", "model.safetensors", "pytorch_model.bin")
#: Written ONLY after a download is verified complete (weight file size matches
#: the repo's expected size). Required for "installed" so a partial/truncated
#: download — e.g. a SIGKILLed resume that left a short model.safetensors — is
#: never accepted (it would fail or score with garbage at inference).
_OK_MARKER = ".refcheck_model_ok"


def is_model_installed() -> bool:
    # Require config.json, a real weight artifact, AND the completion marker —
    # checking only that the weight file *exists* would accept a truncated
    # download (snapshot_download writes config first; a partial weight file can
    # linger). The marker is written only after the size is verified complete.
    p = model_path()
    if not (p.is_dir() and (p / "config.json").is_file()):
        return False
    if not any((p / f).is_file() for f in _WEIGHT_FILES):
        return False
    return (p / _OK_MARKER).is_file()


def _model_complete(expected_weight_bytes: int) -> bool:
    """True when config + a weight file are present and the (largest) weight
    file is at least 99% of its expected size — the authoritative completeness
    check the worker runs before writing the marker."""
    p = model_path()
    if not (p.is_dir() and (p / "config.json").is_file()):
        return False
    weights = [p / f for f in _WEIGHT_FILES if (p / f).is_file()]
    if not weights:
        return False
    try:
        biggest = max(w.stat().st_size for w in weights)
    except OSError:
        return False
    if expected_weight_bytes > 0:
        return biggest >= int(expected_weight_bytes * 0.99)
    return biggest > 50 * 1024 * 1024  # no expected size known → 50 MB sanity floor


def _write_ok_marker() -> None:
    try:
        (model_path() / _OK_MARKER).write_text("ok\n")
    except OSError:
        pass


_MODEL_INFO_FILE = ".refcheck_model_info.json"


def _resolve_latest_revision():
    """Best-effort: the current HEAD commit sha of the model repo on Hugging
    Face. Returns None on any failure (offline, rate-limited, hf_hub missing)."""
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(MODEL_REPO)
        return getattr(info, "sha", None) or getattr(info, "lastModified", None)
    except Exception:  # noqa: BLE001
        return None


def _write_model_info() -> None:
    """Record the resolved HF revision + timestamp at download time so a later,
    explicitly-invoked check can tell whether the repo has since updated. Never
    fatal — a missing info file just means the next check reports 'unknown'."""
    try:
        import json
        from datetime import datetime, timezone
        info = {
            "repo": MODEL_REPO,
            "resolved_revision": _resolve_latest_revision(),
            "download_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (model_path() / _MODEL_INFO_FILE).write_text(json.dumps(info))
    except Exception:  # noqa: BLE001
        pass


def query_update_available() -> Dict[str, object]:
    """Is a newer revision of the model available on Hugging Face?

    EXPLICITLY invoked (e.g. when the Settings panel opens) — NEVER call this
    from model_status(), which the UI polls every 1-2s during downloads; the HF
    round-trip must not sit on that hot path. Network failures degrade to
    'unable_to_check' so the caller never breaks.
    """
    if not is_model_installed():
        return {"update_available": False, "status": "not_installed"}
    try:
        import json
        info_path = model_path() / _MODEL_INFO_FILE
        stored = None
        if info_path.is_file():
            try:
                stored = (json.loads(info_path.read_text()) or {}).get("resolved_revision")
            except Exception:  # noqa: BLE001
                stored = None
        latest = _resolve_latest_revision()
        if latest is None:
            return {"update_available": False, "status": "unable_to_check", "repo": MODEL_REPO}
        if stored is None:
            # Installed before update-tracking existed — record current as
            # baseline so we don't nag, and report no update this time.
            _write_model_info()
            return {"update_available": False, "status": "baseline_recorded",
                    "latest_revision": str(latest), "repo": MODEL_REPO}
        return {
            "update_available": str(stored) != str(latest),
            "status": "checked",
            "current_revision": str(stored),
            "latest_revision": str(latest),
            "repo": MODEL_REPO,
        }
    except Exception:  # noqa: BLE001
        return {"update_available": False, "status": "unable_to_check", "repo": MODEL_REPO}


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def model_status() -> Dict[str, object]:
    """Return current install/download status for the API + Settings UI."""
    installed = is_model_installed()
    with _lock:
        state = _status.get("state")
        message = _status.get("message", "")
        log = list(_log[-120:])
    # If a previous process installed it, reflect that even when state==idle.
    if installed and state not in ("downloading",):
        state = "installed"
    size = _dir_size_bytes(model_path()) if installed else 0
    return {
        "state": state,
        "message": message,
        "installed": installed,
        "repo": MODEL_REPO,
        "path": str(model_path()),
        "size_bytes": size,
        "deps_available": deps_available(),
        "log": log,
    }


def deps_available() -> bool:
    """Whether an inference runtime (onnxruntime OR torch+transformers) exists.

    Delegates to :mod:`runtime_manager`, which first makes an on-demand
    ``--target`` runtime install (if any) importable by prepending it to
    ``sys.path`` — so a runtime the user installed from the app is detected
    without restarting the server.
    """
    from . import runtime_manager
    return runtime_manager.deps_available()


def _safe_mb(path: Path) -> float:
    try:
        return _dir_size_bytes(path) / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return 0.0


def _set_progress(mb: float, total_mb: float) -> None:
    if total_mb:
        pct = min(99, int(mb * 100 / total_mb))
        msg = f"Downloading… {mb:.0f} / {total_mb:.0f} MB ({pct}%)"
    else:
        msg = f"Downloading… {mb:.0f} MB"
    with _lock:
        if _status.get("state") == "downloading":
            _status["message"] = msg


def _fetch_sizes() -> tuple:
    """(total_mb, max_weight_bytes) from repo metadata — for the % display and
    the completeness check. (total_mb, 0) on failure."""
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(MODEL_REPO, files_metadata=True)
        sizes = [(getattr(s, "size", 0) or 0) for s in (info.siblings or [])]
        total_mb = sum(sizes) / (1024 * 1024)
        max_weight = max(sizes) if sizes else 0  # the safetensors/bin is the big one
        _log_line(f"total size ~{total_mb:.0f} MB (weight ~{max_weight / (1024*1024):.0f} MB)")
        return total_mb, max_weight
    except Exception as exc:  # noqa: BLE001
        _log_line(f"(could not fetch total size: {exc})")
        return 0.0, 0


def run_hf_download_cli(repo: str, dest: str) -> int:
    """Run snapshot_download in THIS clean process — the bundle's --hf-download
    mode. HF_HUB_DISABLE_XET is set BEFORE huggingface_hub is imported, which is
    the only reliable way to disable the Xet backend (it stalls in the bundle);
    `import hf_xet` is also blocked as a belt. A fresh standard LFS download."""
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
    sys.modules.setdefault("hf_xet", None)  # makes `import hf_xet` raise → xet off
    try:
        from . import runtime_manager
        runtime_manager.ensure_on_path()
    except Exception:  # noqa: BLE001
        pass
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"hf import failed: {exc}", flush=True)
        return 1
    try:
        snapshot_download(repo_id=repo, local_dir=dest)
        print("HF_DOWNLOAD_OK", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"download error: {exc}", flush=True)
        return 1


def _download_supervised(dest: Path, total_mb: float, expected_weight: int) -> bool:
    """Frozen desktop: download in a CLEAN subprocess (Xet truly off). The key
    lesson from the field: do NOT SIGKILL hf_hub mid-download — that corrupts its
    resume state and restarts from ~0. Instead let each subprocess run to its
    natural exit (hf_hub retries+resumes internally via the read timeout), then
    re-run to RESUME cleanly from the consistent .incomplete. SIGKILL only as a
    true-hang last resort (no progress AND no exit for 6 minutes)."""
    import subprocess
    import time
    for attempt in range(1, 11):
        start_mb = _safe_mb(dest)
        _log_line(f"download attempt {attempt} (xet off, resuming from {start_mb:.0f} MB)")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        proc = subprocess.Popen(
            [sys.executable, "--hf-download", MODEL_REPO, str(dest)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        out: list = []
        threading.Thread(
            target=lambda: [out.append(ln.rstrip("\n")) for ln in proc.stdout], daemon=True,
        ).start()
        last_mb, last_advance, tick = start_mb, time.monotonic(), 0
        while proc.poll() is None:
            time.sleep(3)
            mb = _safe_mb(dest)
            _set_progress(mb, total_mb)
            tick += 1
            if tick % 6 == 0:  # ~18s
                _log_line(f"progress: {mb:.0f} / {total_mb:.0f} MB" if total_mb else f"progress: {mb:.0f} MB")
            if mb >= last_mb + 1:
                last_mb, last_advance = mb, time.monotonic()
            elif time.monotonic() - last_advance > 360:  # 6 min, genuine hang
                _log_line(f"no progress for 6 min at {mb:.0f} MB — restarting the process (resume)")
                proc.kill()
                break
        try:
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001
            proc.kill()
        if _model_complete(expected_weight):
            return True
        _log_line(f"attempt {attempt} ended (exit={proc.returncode}); not complete yet — "
                  f"{' | '.join(out[-3:])}")
        time.sleep(2)  # brief backoff before resuming
    return _model_complete(expected_weight)


def _download_in_process(dest: Path, total_mb: float, expected_weight: int) -> bool:
    """Source install: in-process snapshot_download with Xet disabled + a live
    size reporter (no frozen-bundle Xet-stall concerns here)."""
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")
    sys.modules.setdefault("hf_xet", None)
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # noqa: BLE001
        import traceback
        _log_line("huggingface_hub import failed:\n" + traceback.format_exc())
        return False
    stop = threading.Event()

    def _report() -> None:
        while not stop.wait(1.5):
            _set_progress(_safe_mb(dest), total_mb)

    threading.Thread(target=_report, daemon=True).start()
    try:
        snapshot_download(repo_id=MODEL_REPO, local_dir=str(dest))
        return _model_complete(expected_weight)
    except Exception:  # noqa: BLE001
        import traceback
        _log_line("ERROR: download failed:\n" + traceback.format_exc())
        return False
    finally:
        stop.set()


def _cleanup_hf_cache(dest: Path) -> None:
    """Remove hf_hub's .cache/.incomplete scratch after a verified download so
    the model dir holds only the final files (and frees the resume scratch)."""
    for sub in (".cache", ".huggingface"):
        try:
            shutil.rmtree(dest / sub, ignore_errors=True)
        except OSError:
            pass


def _purge_truncated_finals(expected_weight: int) -> None:
    """Remove a truncated TOP-LEVEL weight file (e.g. a model.safetensors left
    half-written by a SIGKILLed copy). hf_hub would otherwise see the final file
    present and SKIP re-downloading it, so the model could never complete. A
    COMPLETE file (size >= expected) is kept — snapshot_download then no-ops."""
    if not expected_weight:
        return
    p = model_path()
    for f in _WEIGHT_FILES:
        wf = p / f
        try:
            if wf.is_file() and wf.stat().st_size < int(expected_weight * 0.99):
                _log_line(f"removing truncated {f} ({wf.stat().st_size/(1024*1024):.0f} MB "
                          f"< expected {expected_weight/(1024*1024):.0f} MB) for a clean re-fetch")
                wf.unlink()
        except OSError:
            pass


def _download_worker() -> None:
    global _status
    _log_reset()
    _log_line(f"=== downloading {MODEL_REPO} ===")
    try:
        from . import runtime_manager
        runtime_manager.ensure_on_path()
        frozen = runtime_manager.is_frozen()
    except Exception:  # noqa: BLE001
        frozen = False
    dest = model_path()
    existing = _safe_mb(dest)
    if existing > 1:
        _log_line(f"{existing:.0f} MB already present — will resume / verify")
    total_mb, expected_weight = _fetch_sizes()
    _purge_truncated_finals(expected_weight)
    _log_line(f"target={dest}")
    with _lock:
        _status = {"state": "downloading", "repo": MODEL_REPO,
                   "message": f"Downloading {MODEL_REPO}…"}
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        ok = (_download_supervised(dest, total_mb, expected_weight) if frozen
              else _download_in_process(dest, total_mb, expected_weight))
    except Exception:  # noqa: BLE001
        import traceback
        _log_line("ERROR:\n" + traceback.format_exc())
        ok = False
    if ok and _model_complete(expected_weight):
        _write_ok_marker()
        _write_model_info()  # record the resolved HF revision for update checks
        _cleanup_hf_cache(dest)
        mb = _safe_mb(dest)
        _log_line(f"SUCCESS: model installed and verified ({mb:.0f} MB)")
        with _lock:
            _status = {"state": "installed", "repo": MODEL_REPO,
                       "message": f"Model installed ({mb:.0f} MB)."}
        logger.info("AI-detection model installed at %s", dest)
    else:
        _log_line("ERROR: download did not complete or is incomplete — see the log above.")
        with _lock:
            _status = {"state": "error", "repo": MODEL_REPO,
                       "message": "Download failed or stalled — see the log below."}
    try:
        from . import diagnostics
        with _lock:
            st = _status.get("state")
        diagnostics.record({"backend": "model-download", "outcome": st, "reason": MODEL_REPO})
    except Exception:  # noqa: BLE001
        pass


def start_download() -> Dict[str, object]:
    """Kick off a background download (idempotent while one is running).

    The guard, state transition, and thread spawn happen in ONE locked
    critical section so two near-simultaneous callers can't both launch a
    snapshot_download into the same directory (TOCTOU).
    """
    global _thread, _status
    if is_model_installed():
        return model_status()
    with _lock:
        if _status.get("state") == "downloading" and _thread and _thread.is_alive():
            return dict(_status)
        # Mark downloading synchronously (the worker also sets it, but doing it
        # here closes the window before the thread first acquires the lock).
        _status = {"state": "downloading", "repo": MODEL_REPO,
                   "message": "Download started."}
        _thread = threading.Thread(target=_download_worker, daemon=True)
        _thread.start()
        return dict(_status)


def delete_model() -> Dict[str, object]:
    """Remove the installed model from disk.

    Refuses while a download is in flight and does the rmtree + state reset
    inside the SAME locked section as the download state machine, so a delete
    can't race a concurrent snapshot_download (which would recreate the dir and
    flip the state back to 'installed', silently undoing the delete).
    """
    global _status
    with _lock:
        if _status.get("state") == "downloading" and _thread and _thread.is_alive():
            return {"state": "downloading", "repo": MODEL_REPO,
                    "message": "Cannot remove the model while a download is in progress."}
        p = model_path()
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        _status = {"state": "idle", "repo": MODEL_REPO, "message": "Model removed."}
    return model_status()


# ── Per-detector install / status / remove (multi-detector layer, R61) ─────
#
# These parameterize the on-demand HF download + ``.refcheck_model_info.json``
# pattern per detector ``key``. They REUSE the same completeness rules
# (config.json + a real weight artifact + a verified-complete OK marker) as the
# single-detector path. ``desklib`` delegates to the legacy functions above so
# its (possibly in-flight) download state and existing on-disk install are
# preserved byte-for-byte — no behavioural change for existing users.

# Per-key download state (keyed by detector key). Each value mirrors the legacy
# ``_status`` dict shape. Guarded by ``_lock`` (shared with the legacy state).
_detector_status: Dict[str, Dict[str, object]] = {}
_detector_threads: Dict[str, threading.Thread] = {}


def _detector_ok_marker(key: str) -> Path:
    return detector_dir(key) / _OK_MARKER


def _detector_info_file(key: str) -> Path:
    return detector_dir(key) / _MODEL_INFO_FILE


def is_detector_installed(key: str) -> bool:
    """True when detector ``key`` is fully downloaded + verified.

    ``desklib`` reuses the legacy ``is_model_installed()`` so an existing
    install (which predates this registry) is recognised unchanged.
    """
    if (key or "").lower() == DEFAULT_DETECTOR:
        return is_model_installed()
    entry = get_detector(key)
    if not entry:
        return False
    p = detector_dir(key)
    if not (p.is_dir() and (p / "config.json").is_file()):
        return False
    if not any((p / f).is_file() for f in _WEIGHT_FILES):
        return False
    return (p / _OK_MARKER).is_file()


def _detector_complete(key: str, expected_weight_bytes: int) -> bool:
    p = detector_dir(key)
    if not (p.is_dir() and (p / "config.json").is_file()):
        return False
    weights = [p / f for f in _WEIGHT_FILES if (p / f).is_file()]
    if not weights:
        return False
    try:
        biggest = max(w.stat().st_size for w in weights)
    except OSError:
        return False
    if expected_weight_bytes > 0:
        return biggest >= int(expected_weight_bytes * 0.99)
    return biggest > 50 * 1024 * 1024


def detector_status(key: str) -> Dict[str, object]:
    """Install/download status for ONE detector, including registry metadata.

    Honesty contract: a Tier-2 / non-installable detector reports
    ``installable: False`` and is NEVER ``installed`` (we don't have a runner),
    so the FE can show it as unavailable and never offer to run it.
    """
    entry = get_detector(key)
    if not entry:
        return {"key": key, "state": "unknown", "installed": False,
                "installable": False, "error": "unknown_detector"}
    k = str(entry["key"])
    installable = bool(entry.get("installable"))
    if k == DEFAULT_DETECTOR:
        base = model_status()
        installed = bool(base.get("installed"))
        state = base.get("state")
        size = base.get("size_bytes", 0)
        log = base.get("log", [])
    else:
        installed = is_detector_installed(k) if installable else False
        with _lock:
            st = _detector_status.get(k, {})
            state = st.get("state", "idle")
            log = list(st.get("log", []))[-120:] if isinstance(st.get("log"), list) else []
        if installed and state not in ("downloading",):
            state = "installed"
        size = _dir_size_bytes(detector_dir(k)) if installed else 0
    return {
        "key": k,
        "repo": entry["repo"],
        "arch": entry["arch"],
        "head": entry["head"],
        "tier": entry["tier"],
        "size_mb": entry["size_mb"],
        "threshold": entry["threshold"],
        "license": entry["license"],
        "raid_note": entry["raid_note"],
        "label": entry.get("label", k),
        "heavy": bool(entry.get("heavy")),
        "installable": installable,
        "installed": installed,
        "state": state,
        "path": str(detector_dir(k)),
        "size_bytes": size,
        "deps_available": deps_available(),
        "log": log,
    }


def registry_status() -> Dict[str, object]:
    """Full registry + per-detector status for the manager UI / API.

    The default detector is reported first; the order otherwise follows the
    registry (Tier-1 before Tier-2).
    """
    detectors = [detector_status(k) for k in DETECTOR_REGISTRY]
    return {
        "default": DEFAULT_DETECTOR,
        "detectors": detectors,
        "deps_available": deps_available(),
    }


def _detector_log(key: str, msg: str) -> None:
    import time
    stamp = time.strftime("%H:%M:%S")
    with _lock:
        st = _detector_status.setdefault(key, {"state": "idle", "log": []})
        log = st.setdefault("log", [])
        for line in (str(msg).splitlines() or [""]):
            log.append(f"{stamp}  {line}")
        if len(log) > _LOG_CAP:
            del log[: len(log) - _LOG_CAP]


def _fetch_sizes_for(repo: str) -> tuple:
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(repo, files_metadata=True)
        sizes = [(getattr(s, "size", 0) or 0) for s in (info.siblings or [])]
        total_mb = sum(sizes) / (1024 * 1024)
        max_weight = max(sizes) if sizes else 0
        return total_mb, max_weight
    except Exception:  # noqa: BLE001
        return 0.0, 0


def _resolve_latest_revision_for(repo: str):
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(repo)
        return getattr(info, "sha", None) or getattr(info, "lastModified", None)
    except Exception:  # noqa: BLE001
        return None


def _write_detector_info(key: str) -> None:
    try:
        import json
        from datetime import datetime, timezone
        entry = get_detector(key) or {}
        info = {
            "repo": entry.get("repo"),
            "resolved_revision": _resolve_latest_revision_for(str(entry.get("repo") or "")),
            "download_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _detector_info_file(key).write_text(json.dumps(info))
    except Exception:  # noqa: BLE001
        pass


def _detector_download_worker(key: str) -> None:
    """Background download of a non-default detector via in-process
    snapshot_download (Xet disabled), mirroring ``_download_in_process``."""
    entry = get_detector(key)
    repo = str(entry["repo"])
    dest = detector_dir(key)
    _detector_log(key, f"=== downloading {repo} ===")
    total_mb, expected_weight = _fetch_sizes_for(repo)
    with _lock:
        _detector_status[key] = {
            "state": "downloading",
            "log": _detector_status.get(key, {}).get("log", []),
            "message": f"Downloading {repo}…",
        }
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")
    sys.modules.setdefault("hf_xet", None)
    ok = False
    try:
        from . import runtime_manager
        runtime_manager.ensure_on_path()
    except Exception:  # noqa: BLE001
        pass
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=repo, local_dir=str(dest))
        ok = _detector_complete(key, expected_weight)
    except Exception:  # noqa: BLE001
        import traceback
        _detector_log(key, "ERROR: download failed:\n" + traceback.format_exc())
        ok = False
    with _lock:
        log = _detector_status.get(key, {}).get("log", [])
    if ok:
        try:
            _detector_ok_marker(key).write_text("ok\n")
        except OSError:
            pass
        _write_detector_info(key)
        mb = _safe_mb(dest)
        _detector_log(key, f"SUCCESS: detector installed ({mb:.0f} MB)")
        with _lock:
            _detector_status[key] = {"state": "installed", "log": log,
                                     "message": f"Installed ({mb:.0f} MB)."}
    else:
        _detector_log(key, "ERROR: download did not complete — see log.")
        with _lock:
            _detector_status[key] = {"state": "error", "log": log,
                                     "message": "Download failed or incomplete."}
    try:
        from . import diagnostics
        with _lock:
            stt = _detector_status.get(key, {}).get("state")
        diagnostics.record({"backend": "detector-download", "outcome": stt,
                            "reason": f"{key}:{repo}"})
    except Exception:  # noqa: BLE001
        pass


def start_detector_download(key: str) -> Dict[str, object]:
    """Start (or report) the background download of detector ``key``.

    Refuses non-installable (Tier-2) detectors honestly — they have no runner,
    so we never download or mark them installable. ``desklib`` delegates to the
    legacy ``start_download()`` so its state machine is untouched.
    """
    entry = get_detector(key)
    if not entry:
        return {"key": key, "state": "error", "error": "unknown_detector",
                "installable": False}
    if not entry.get("installable"):
        return {"key": str(entry["key"]), "state": "unavailable",
                "installable": False,
                "message": "This detector is heavy and not runnable in this "
                           "build; it cannot be installed.",
                "heavy": bool(entry.get("heavy"))}
    if not deps_available():
        return {"key": str(entry["key"]), "state": "error",
                "error": "deps_not_installed", "installable": True,
                "message": "Local detection runtime not installed (torch + "
                           "transformers). Install it first."}
    k = str(entry["key"])
    if k == DEFAULT_DETECTOR:
        start_download()
        return detector_status(k)
    if is_detector_installed(k):
        return detector_status(k)
    with _lock:
        st = _detector_status.get(k, {})
        th = _detector_threads.get(k)
        if st.get("state") == "downloading" and th and th.is_alive():
            return detector_status(k)
        _detector_status[k] = {"state": "downloading",
                               "log": st.get("log", []),
                               "message": "Download started."}
        t = threading.Thread(target=_detector_download_worker, args=(k,), daemon=True)
        _detector_threads[k] = t
        t.start()
    return detector_status(k)


def delete_detector(key: str) -> Dict[str, object]:
    """Remove an installed detector from disk (per-key).

    Refuses while that detector's download is in flight. ``desklib`` delegates
    to the legacy ``delete_model()``.
    """
    entry = get_detector(key)
    if not entry:
        return {"key": key, "state": "error", "error": "unknown_detector"}
    k = str(entry["key"])
    if k == DEFAULT_DETECTOR:
        delete_model()
        return detector_status(k)
    with _lock:
        th = _detector_threads.get(k)
        st = _detector_status.get(k, {})
        if st.get("state") == "downloading" and th and th.is_alive():
            return {"key": k, "state": "downloading",
                    "message": "Cannot remove while a download is in progress."}
        p = detector_dir(k)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        _detector_status[k] = {"state": "idle", "log": st.get("log", []),
                               "message": "Detector removed."}
    return detector_status(k)
