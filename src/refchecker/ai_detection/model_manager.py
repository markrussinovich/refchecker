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
MODEL_REPO = "desklib/ai-text-detector-v1.01"
_MODEL_DIRNAME = "desklib-ai-text-detector-v1.01"

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


def is_model_installed() -> bool:
    # Require an actual weight artifact, not just config.json — snapshot_download
    # writes the tiny config first, so checking only config.json would report
    # "installed" mid-download (premature poll-loop exit + a spurious
    # model_load_failed if a check starts before the weights land).
    p = model_path()
    if not (p.is_dir() and (p / "config.json").is_file()):
        return False
    return any((p / f).is_file() for f in _WEIGHT_FILES)


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


def _fetch_total_mb() -> float:
    """Total download size for the % display (metadata call, no download)."""
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(MODEL_REPO, files_metadata=True)
        mb = sum((getattr(s, "size", 0) or 0) for s in (info.siblings or [])) / (1024 * 1024)
        _log_line(f"total size ~{mb:.0f} MB")
        return mb
    except Exception as exc:  # noqa: BLE001
        _log_line(f"(could not fetch total size: {exc})")
        return 0.0


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


def _download_supervised(dest: Path, total_mb: float) -> bool:
    """Frozen desktop: download in a CLEAN subprocess (Xet truly off) under a
    stall watchdog — kill + retry (resume) when progress flatlines for 120s, and
    wipe for a fresh restart if two attempts make no headway at all."""
    import subprocess
    import time
    prev_start = -1.0
    stuck_rounds = 0
    for attempt in range(1, 7):
        start_mb = _safe_mb(dest)
        stuck_rounds = stuck_rounds + 1 if start_mb <= prev_start + 1 else 0
        prev_start = start_mb
        if stuck_rounds >= 2:
            _log_line("no cross-attempt progress — wiping the partial for a clean restart")
            _wipe_model_dir(dest)
            start_mb, prev_start, stuck_rounds = 0.0, -1.0, 0
        _log_line(f"download attempt {attempt} (clean subprocess, xet off, from {start_mb:.0f} MB)")
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
        last_mb, last_advance, stalled, tick = start_mb, time.monotonic(), False, 0
        while proc.poll() is None:
            time.sleep(2)
            mb = _safe_mb(dest)
            _set_progress(mb, total_mb)
            tick += 1
            if tick % 8 == 0:  # ~16s
                _log_line(f"progress: {mb:.0f} / {total_mb:.0f} MB" if total_mb else f"progress: {mb:.0f} MB")
            if mb >= last_mb + 1:
                last_mb, last_advance = mb, time.monotonic()
            elif time.monotonic() - last_advance > 120:
                _log_line(f"STALL: stuck at {mb:.0f} MB for 120s — killing and retrying")
                stalled = True
                proc.kill()
                break
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()
        if is_model_installed():
            return True
        if not stalled:
            _log_line(f"attempt {attempt} exited code={proc.returncode}: {' | '.join(out[-4:])}")
    return is_model_installed()


def _download_in_process(dest: Path, total_mb: float) -> bool:
    """Source install: in-process snapshot_download with Xet disabled + a live
    size reporter (no frozen-bundle Xet-stall concerns here)."""
    os.environ["HF_HUB_DISABLE_XET"] = "1"
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
        return is_model_installed()
    except Exception:  # noqa: BLE001
        import traceback
        _log_line("ERROR: download failed:\n" + traceback.format_exc())
        return False
    finally:
        stop.set()


def _wipe_model_dir(dest: Path) -> None:
    try:
        shutil.rmtree(dest, ignore_errors=True)
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
        _log_line(f"{existing:.0f} MB already present — will resume")
    total_mb = _fetch_total_mb()
    _log_line(f"target={dest}")
    with _lock:
        _status = {"state": "downloading", "repo": MODEL_REPO,
                   "message": f"Downloading {MODEL_REPO}…"}
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        ok = _download_supervised(dest, total_mb) if frozen else _download_in_process(dest, total_mb)
    except Exception:  # noqa: BLE001
        import traceback
        _log_line("ERROR:\n" + traceback.format_exc())
        ok = False
    if ok and is_model_installed():
        mb = _safe_mb(dest)
        _log_line(f"SUCCESS: model installed ({mb:.0f} MB)")
        with _lock:
            _status = {"state": "installed", "repo": MODEL_REPO,
                       "message": f"Model installed ({mb:.0f} MB)."}
        logger.info("AI-detection model installed at %s", dest)
    else:
        _log_line("ERROR: download did not complete — see the log above.")
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
