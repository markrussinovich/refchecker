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


def _download_worker() -> None:
    global _status
    _log_reset()
    _log_line(f"=== downloading {MODEL_REPO} ===")
    # huggingface_hub is pip-installed into the runtime --target dir; make it
    # importable in this process (and let the meta-path finder route it) first.
    try:
        from . import runtime_manager
        runtime_manager.ensure_on_path()
    except Exception:  # noqa: BLE001
        pass
    try:
        import huggingface_hub
        from huggingface_hub import snapshot_download
        _log_line(f"huggingface_hub {getattr(huggingface_hub, '__version__', '?')}")
    except Exception as exc:  # noqa: BLE001
        import traceback
        _log_line("huggingface_hub import failed:\n" + traceback.format_exc())
        with _lock:
            _status = {"state": "error", "repo": MODEL_REPO,
                       "message": f"huggingface_hub not available — install the runtime first. {exc}"}
        return

    dest = model_path()
    stop = threading.Event()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            _status = {"state": "downloading", "repo": MODEL_REPO,
                       "message": f"Downloading {MODEL_REPO}…"}
        _log_line(f"target={dest}")

        # Live size reporter → the UI status bar shows real progress (the model
        # is a few hundred MB; snapshot_download gives no easy callback).
        def _report() -> None:
            while not stop.wait(1.5):
                try:
                    mb = _dir_size_bytes(dest) / (1024 * 1024)
                except Exception:  # noqa: BLE001
                    mb = 0
                with _lock:
                    if _status.get("state") == "downloading":
                        _status["message"] = f"Downloading… {mb:.0f} MB"
        threading.Thread(target=_report, daemon=True).start()

        # NOTE: `local_dir_use_symlinks` was REMOVED in huggingface_hub 1.x
        # (passing it raises TypeError); local_dir downloads are direct copies
        # by default now, which is exactly what we want.
        snapshot_download(repo_id=MODEL_REPO, local_dir=str(dest))
        stop.set()
        mb = _dir_size_bytes(dest) / (1024 * 1024)
        _log_line(f"SUCCESS: model installed ({mb:.0f} MB)")
        with _lock:
            _status = {"state": "installed", "repo": MODEL_REPO,
                       "message": f"Model installed ({mb:.0f} MB)."}
        logger.info("AI-detection model installed at %s", dest)
    except Exception as exc:  # noqa: BLE001
        stop.set()
        import traceback
        _log_line("ERROR: download failed:\n" + traceback.format_exc())
        logger.warning("AI-detection model download failed: %s", exc)
        with _lock:
            _status = {"state": "error", "repo": MODEL_REPO,
                       "message": f"Download failed — see the log below. {exc}"}
    finally:
        stop.set()
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
