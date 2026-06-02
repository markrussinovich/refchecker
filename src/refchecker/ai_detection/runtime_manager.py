"""Install / status for the local-detector inference runtime (optional deps).

The local detector needs an inference runtime that is deliberately **not**
bundled (to keep the desktop sidecar small): ``transformers`` plus a backend
(``torch`` — required for the default ``desklib`` model, which ships
safetensors only — or ``onnxruntime`` for an ONNX export).

This module installs that runtime, on demand, into a writable per-user
directory via ``pip --target`` and prepends that directory to ``sys.path`` so
the frozen/desktop interpreter (and a normal source install) can import the
freshly-installed packages without a restart.

Why ``--target`` rather than a plain ``pip install``:
* In the PyInstaller desktop bundle there is no writable ``site-packages``; a
  ``--target`` dir under the app-data directory is the only place we can write.
* It keeps the heavy ML deps out of the base environment / bundle entirely.

Install runs in a background thread and reports progress through a module-level
status dict (poll ``runtime_status``), mirroring :mod:`model_manager`.
"""

from __future__ import annotations

import importlib
import io
import logging
import os
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Package sets per variant. transformers is always needed; the backend differs.
# "torch" is the default because the bundled desklib model ships safetensors
# only (no model.onnx), so onnxruntime alone cannot run it.
_VARIANTS: Dict[str, List[str]] = {
    "torch": ["torch", "transformers", "huggingface_hub"],
    "onnx": ["onnxruntime", "transformers", "huggingface_hub"],
}
DEFAULT_VARIANT = "torch"

# Standalone pip zipapp, used only when the (frozen) interpreter has no
# importable ``pip`` of its own. Pinned to the version-agnostic redirect.
_PIP_PYZ_URL = "https://bootstrap.pypa.io/pip/pip.pyz"

_lock = threading.Lock()
_status: Dict[str, object] = {"state": "idle", "message": "", "variant": None}
_thread: Optional[threading.Thread] = None
_on_path_done = False

# Rolling install/diagnostic log (newest-last), streamed live to the UI debugger
# so a failing desktop install shows the real pip output instead of failing
# silently. Capped so it can't grow without bound.
_LOG_CAP = 400
_log: List[str] = []


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


def get_log(limit: int = 160) -> List[str]:
    with _lock:
        return _log[-limit:]


class _LogWriter(io.TextIOBase):
    """File-like sink that streams written text into the install log live (used
    to capture in-process pip output as it happens)."""

    def write(self, s):  # noqa: D401
        if s:
            _log_line(s.rstrip("\n"))
        return len(s)

    def flush(self):
        return None


def is_frozen() -> bool:
    """True when running inside a PyInstaller (desktop sidecar) bundle."""
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def runtime_dir() -> Path:
    """Writable directory the optional runtime is installed into."""
    env = os.environ.get("REFCHECKER_AI_DETECTION_RUNTIME_DIR")
    if env:
        return Path(env)
    data = os.environ.get("REFCHECKER_DATA_DIR")
    if data:
        return Path(data) / "ai-detection-runtime"
    cache = os.environ.get("REFCHECKER_CACHE_DIR")
    if cache:
        return Path(cache) / "ai-detection-runtime"
    return Path.home() / ".cache" / "refchecker" / "ai-detection-runtime"


def ensure_on_path() -> None:
    """Prepend the runtime dir to ``sys.path`` so installed deps are importable.

    Idempotent and cheap; safe to call before every dependency check. Only
    touches ``sys.path`` when the directory actually exists, so a normal
    environment that never installed a runtime is unaffected.
    """
    global _on_path_done
    d = runtime_dir()
    try:
        exists = d.is_dir()
    except OSError:
        exists = False
    if not exists:
        return
    s = str(d)
    if s not in sys.path:
        sys.path.insert(0, s)
        # A freshly-created dir may have been probed (and cached as missing)
        # by an earlier import attempt; clear that so the new packages resolve.
        importlib.invalidate_caches()
    _on_path_done = True


# ── pip invocation ─────────────────────────────────────────────────────────

def _torch_index_args(variant: str) -> List[str]:
    """Pull the CPU-only torch wheel on Linux/Windows (the default PyPI torch
    wheel there is the multi-hundred-MB CUDA build). macOS wheels are CPU."""
    if variant == "torch" and sys.platform.startswith(("linux", "win")):
        return ["--index-url", "https://download.pytorch.org/whl/cpu",
                "--extra-index-url", "https://pypi.org/simple"]
    return []


def _pip_argv(variant: str) -> List[str]:
    argv = ["install", "--no-input", "--disable-pip-version-check",
            "--no-warn-script-location",
            # --upgrade so a re-install REPLACES existing dirs instead of
            # skipping them ("Target directory ... already exists"), which would
            # otherwise leave a half-old/half-new mix that fails to import.
            "--upgrade", "--target", str(runtime_dir())]
    # In the frozen bundle there is no compiler / usable build environment, so
    # never let pip fall back to building an sdist from source; and skip the
    # cache dir (the bundle's HOME may be read-only / unexpected).
    if is_frozen():
        argv += ["--only-binary=:all:", "--no-cache-dir"]
    argv += _torch_index_args(variant)
    argv += _VARIANTS[variant]
    return argv


def _clean_target() -> None:
    """Empty the runtime dir (keep a downloaded pip.pyz) before a fresh install.

    A prior interrupted/failed install leaves a partial tree that ``pip
    --target`` skips rather than repairs; wiping guarantees a coherent install.
    """
    import shutil
    d = runtime_dir()
    if not d.is_dir():
        return
    _log_line("clearing previous runtime dir for a clean install")
    for child in d.iterdir():
        if child.name == "pip.pyz":
            continue
        try:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        except OSError as exc:  # noqa: PERF203
            _log_line(f"could not remove {child.name}: {exc}")


def _verbose_import_check() -> Tuple[bool, str]:
    """Try to import the runtime and return the REAL traceback on failure, so
    a 'pip succeeded but not importable' case shows why (not a silent retry)."""
    ensure_on_path()
    importlib.invalidate_caches()
    errs: List[str] = []
    for backend in ("torch", "onnxruntime"):
        try:
            importlib.import_module(backend)
            importlib.import_module("transformers")
            return True, ""
        except Exception:  # noqa: BLE001
            import traceback
            errs.append(f"--- import {backend} + transformers failed ---\n"
                        + traceback.format_exc())
    return False, "\n".join(errs)


def _run_pip_subprocess(argv: List[str]) -> bool:
    """Run ``{sys.executable} -m pip`` — the clean path for source installs.

    Streams pip's output into the live log so the UI debugger shows progress.
    """
    import subprocess
    cmd = [sys.executable, "-m", "pip", *argv]
    _log_line("$ " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    try:
        for line in proc.stdout:  # live stream
            _log_line(line.rstrip("\n"))
        proc.wait(timeout=3600)
    finally:
        if proc.poll() is None:
            proc.kill()
    return proc.returncode == 0


def _run_pip_frozen_subprocess(argv: List[str]) -> bool:
    """Install in the frozen desktop bundle by re-invoking the bundle itself in
    a hidden ``--pip-install`` mode (handled in ``server_entry``).

    Running pip in a SEPARATE process — rather than in-process inside the live
    server — is what makes this reliable: the child has a clean ``sys.path`` and
    no FastAPI/torch already imported, so pip can't half-import torch into the
    running server and leave it broken. Same interpreter → ABI-matched wheels.
    Output is streamed back into the live log.
    """
    import subprocess
    cmd = [sys.executable, "--pip-install", *argv]
    _log_line("$ <app> --pip-install " + " ".join(argv))
    _log_line("(launching a clean installer subprocess; the one-file bundle "
              "re-extracts first, so expect ~30s before pip output appears)")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    try:
        for line in proc.stdout:
            _log_line(line.rstrip("\n"))
        proc.wait(timeout=3600)
    finally:
        if proc.poll() is None:
            proc.kill()
    return proc.returncode == 0


def run_pip_cli(argv: List[str]) -> int:
    """Run pip in THIS (clean) process — the bundle's ``--pip-install`` entry.

    Uses an importable ``pip`` if the bundle has one, else the downloaded
    ``pip.pyz``. Output goes to real stdout so the parent captures it.
    """
    import runpy
    if importlib.util.find_spec("pip") is not None:
        print("[pip] using bundled pip", flush=True)
        sys.argv = ["pip", *argv]
        try:
            runpy.run_module("pip", run_name="__main__", alter_sys=True)
            return 0
        except SystemExit as exc:
            return int(exc.code or 0)
    pyz = _ensure_pip_pyz()
    if pyz is None:
        print("[pip] could not obtain pip", flush=True)
        return 1
    print("[pip] using downloaded pip.pyz", flush=True)
    sys.argv = ["pip", *argv]
    try:
        runpy.run_path(str(pyz), run_name="__main__")
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)


def _ensure_pip_pyz() -> Optional[Path]:
    """Download the standalone pip zipapp into the runtime dir (once)."""
    dest = runtime_dir() / "pip.pyz"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    try:
        import urllib.request
        dest.parent.mkdir(parents=True, exist_ok=True)
        _log_line(f"Downloading pip from {_PIP_PYZ_URL}…")
        with urllib.request.urlopen(_PIP_PYZ_URL, timeout=60) as resp:  # noqa: S310
            data = resp.read()
        dest.write_bytes(data)
        _log_line(f"pip.pyz downloaded ({len(data)} bytes)")
        return dest
    except Exception as exc:  # noqa: BLE001
        _log_line(f"pip download failed: {exc}")
        return None


def _run_pip(argv: List[str]) -> bool:
    if is_frozen():
        return _run_pip_frozen_subprocess(argv)
    return _run_pip_subprocess(argv)


# ── status / install ───────────────────────────────────────────────────────

def deps_available() -> bool:
    """Whether an inference runtime (onnxruntime OR torch, + transformers) is
    importable — after making sure an installed --target runtime is on path."""
    ensure_on_path()
    for backend in ("onnxruntime", "torch"):
        try:
            importlib.import_module(backend)
            importlib.import_module("transformers")
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def installed_variant() -> Optional[str]:
    """Which backend is importable, if any ('torch' preferred for desklib)."""
    ensure_on_path()
    try:
        importlib.import_module("transformers")
    except Exception:  # noqa: BLE001
        return None
    for name, variant in (("torch", "torch"), ("onnxruntime", "onnx")):
        try:
            importlib.import_module(name)
            return variant
        except Exception:  # noqa: BLE001
            continue
    return None


def runtime_status() -> Dict[str, object]:
    with _lock:
        state = _status.get("state")
        message = _status.get("message", "")
        variant = _status.get("variant")
        log = list(_log[-160:])
    available = deps_available()
    if available and state != "installing":
        state = "installed"
    return {
        "state": state,
        "message": message,
        "deps_available": available,
        "installed_variant": installed_variant(),
        "installing_variant": variant,
        "default_variant": DEFAULT_VARIANT,
        "variants": list(_VARIANTS.keys()),
        "is_frozen": is_frozen(),
        "target": str(runtime_dir()),
        "log": log,
    }


def _install_worker(variant: str) -> None:
    global _status
    try:
        _log_line(f"=== installing '{variant}' runtime ===")
        _log_line(f"frozen={is_frozen()} python={sys.version.split()[0]} "
                  f"platform={sys.platform} executable={sys.executable}")
        _log_line(f"target={runtime_dir()}")
        runtime_dir().mkdir(parents=True, exist_ok=True)
        _clean_target()
        ok = _run_pip(_pip_argv(variant))
        # Make the just-installed packages importable in-process so the next
        # check / status poll sees them without a restart, then VERIFY they
        # actually import — a pip exit 0 that still can't be imported (ABI
        # mismatch, partial install) must surface as an error WITH the real
        # traceback, not a false "installed" that makes the UI poll forever.
        importable, import_err = _verbose_import_check()
        _log_line(f"pip ok={ok} runtime_importable={importable}")
        if ok and importable:
            _log_line(f"SUCCESS: {variant} runtime installed and importable")
            with _lock:
                _status = {"state": "installed", "variant": variant,
                           "message": f"Installed {variant} runtime."}
            logger.info("AI-detection runtime (%s) installed at %s", variant, runtime_dir())
        elif ok:
            _log_line("ERROR: pip reported success but the runtime cannot be imported:")
            _log_line(import_err or "(no import error captured)")
            with _lock:
                _status = {"state": "error", "variant": variant,
                           "message": ("Installed, but the runtime still isn't importable. "
                                       "See the install log below for the import error.")}
            logger.warning("AI-detection runtime installed but not importable")
        else:
            _log_line("ERROR: pip install failed")
            with _lock:
                _status = {"state": "error", "variant": variant,
                           "message": "Install failed — see the install log below."}
            logger.warning("AI-detection runtime install failed")
    except Exception as exc:  # noqa: BLE001
        import traceback
        _log_line("CRASH:\n" + traceback.format_exc())
        logger.warning("AI-detection runtime install crashed: %s", exc)
        with _lock:
            _status = {"state": "error", "variant": variant,
                       "message": f"Install crashed: {exc}"}


def start_install(variant: str = DEFAULT_VARIANT) -> Dict[str, object]:
    """Kick off a background runtime install (idempotent while one runs)."""
    global _thread, _status
    variant = (variant or DEFAULT_VARIANT).lower()
    if variant not in _VARIANTS:
        variant = DEFAULT_VARIANT
    if deps_available():
        return runtime_status()
    with _lock:
        if _status.get("state") == "installing" and _thread and _thread.is_alive():
            return dict(_status, **{"deps_available": False})
    _log_reset()  # fresh log per install attempt (own lock — keep out of the block above)
    with _lock:
        _status = {"state": "installing", "variant": variant,
                   "message": f"Installing {variant} runtime…"}
        _thread = threading.Thread(target=_install_worker, args=(variant,), daemon=True)
        _thread.start()
    return runtime_status()
