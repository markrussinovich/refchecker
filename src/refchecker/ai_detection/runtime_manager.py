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
    argv = ["install", "--no-input", "--target", str(runtime_dir())]
    # In the frozen bundle there is no compiler / usable build environment, so
    # never let pip fall back to building an sdist from source.
    if is_frozen():
        argv.append("--only-binary=:all:")
    argv += _torch_index_args(variant)
    argv += _VARIANTS[variant]
    return argv


def _run_pip_subprocess(argv: List[str]) -> Tuple[bool, str]:
    """Run ``{sys.executable} -m pip`` — the clean path for source installs."""
    import subprocess
    cmd = [sys.executable, "-m", "pip", *argv]
    logger.info("AI-detection runtime install: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    log = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, log


def _run_pip_inprocess(argv: List[str]) -> Tuple[bool, str]:
    """Run pip inside this interpreter — used in the frozen desktop bundle,
    where ``sys.executable`` is the app (not a Python that accepts ``-m pip``).

    Uses an importable ``pip`` if the bundle has one, else downloads the
    official ``pip.pyz`` zipapp and runs it. Either way pip resolves wheels for
    THIS interpreter's version/platform, so installed binaries match the ABI.
    """
    import runpy
    buf = io.StringIO()
    old_argv = sys.argv
    code = 1
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            if importlib.util.find_spec("pip") is not None:
                sys.argv = ["pip", *argv]
                try:
                    runpy.run_module("pip", run_name="__main__", alter_sys=True)
                    code = 0
                except SystemExit as exc:  # pip always exits
                    code = int(exc.code or 0)
            else:
                pyz = _ensure_pip_pyz(buf)
                if pyz is None:
                    return False, buf.getvalue() + "\nCould not obtain pip."
                sys.argv = ["pip", *argv]
                try:
                    runpy.run_path(str(pyz), run_name="__main__")
                    code = 0
                except SystemExit as exc:
                    code = int(exc.code or 0)
    except Exception as exc:  # noqa: BLE001
        return False, buf.getvalue() + f"\npip raised: {exc}"
    finally:
        sys.argv = old_argv
    return code == 0, buf.getvalue()


def _ensure_pip_pyz(buf: io.StringIO) -> Optional[Path]:
    """Download the standalone pip zipapp into the runtime dir (once)."""
    dest = runtime_dir() / "pip.pyz"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    try:
        import urllib.request
        dest.parent.mkdir(parents=True, exist_ok=True)
        buf.write(f"Downloading pip from {_PIP_PYZ_URL}…\n")
        with urllib.request.urlopen(_PIP_PYZ_URL, timeout=60) as resp:  # noqa: S310
            data = resp.read()
        dest.write_bytes(data)
        return dest
    except Exception as exc:  # noqa: BLE001
        buf.write(f"pip download failed: {exc}\n")
        return None


def _run_pip(argv: List[str]) -> Tuple[bool, str]:
    if is_frozen():
        return _run_pip_inprocess(argv)
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
    }


def _install_worker(variant: str) -> None:
    global _status
    try:
        runtime_dir().mkdir(parents=True, exist_ok=True)
        ok, log = _run_pip(_pip_argv(variant))
        tail = "\n".join((log or "").strip().splitlines()[-8:])
        # Make the just-installed packages importable in-process so the next
        # check / status poll sees them without a restart, then VERIFY they
        # actually import — a pip exit 0 that still can't be imported (ABI
        # mismatch, partial install) must surface as an error, not a false
        # "installed" that makes the UI poll forever.
        ensure_on_path()
        importlib.invalidate_caches()
        if ok and deps_available():
            with _lock:
                _status = {"state": "installed", "variant": variant,
                           "message": f"Installed {variant} runtime."}
            logger.info("AI-detection runtime (%s) installed at %s", variant, runtime_dir())
        elif ok:
            with _lock:
                _status = {"state": "error", "variant": variant,
                           "message": ("Installed, but the runtime still isn't importable "
                                       f"(possible version mismatch). {tail}")}
            logger.warning("AI-detection runtime installed but not importable: %s", tail)
        else:
            with _lock:
                _status = {"state": "error", "variant": variant,
                           "message": f"Install failed. {tail}"}
            logger.warning("AI-detection runtime install failed: %s", tail)
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI-detection runtime install crashed: %s", exc)
        with _lock:
            _status = {"state": "error", "variant": variant,
                       "message": f"Install failed: {exc}"}


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
        _status = {"state": "installing", "variant": variant,
                   "message": f"Installing {variant} runtime…"}
        _thread = threading.Thread(target=_install_worker, args=(variant,), daemon=True)
        _thread.start()
    return runtime_status()
