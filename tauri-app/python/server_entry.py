"""
PyInstaller entrypoint for the RefChecker desktop sidecar.

Bundles backend.main:app + the prebuilt SPA in backend/static/ into a
single executable that the Tauri shell launches on a chosen port.

CLI:
    refchecker-server [--host 127.0.0.1] [--port 8765]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _resolve_data_dir() -> Path:
    """
    Per-user, writable data dir for the desktop app.

    Honors REFCHECKER_DATA_DIR if set (lets users / CI override). Otherwise
    picks a platform-appropriate location so the bundled SQLite DB, cache,
    and uploaded PDFs survive across app launches.
    """
    override = os.environ.get("REFCHECKER_DATA_DIR")
    if override:
        return Path(override).expanduser()

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "RefChecker"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "RefChecker"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "RefChecker"


def main() -> int:
    # PyInstaller unpacks bundled modules under sys._MEIPASS — make them
    # importable before anything else (needed for the --pip-install mode too).
    if hasattr(sys, "_MEIPASS"):
        sys.path.insert(0, sys._MEIPASS)

    # Hidden installer mode: the AI-detection runtime installer re-invokes this
    # bundle as a clean, ABI-matched pip runner (a fresh process with no server
    # loaded). Handle it before argparse so the pass-through pip args aren't
    # rejected. See refchecker.ai_detection.runtime_manager.
    if len(sys.argv) >= 2 and sys.argv[1] == "--pip-install":
        try:
            from refchecker.ai_detection import runtime_manager
        except Exception as exc:  # noqa: BLE001
            print(f"pip-install mode: cannot import runtime_manager: {exc}", flush=True)
            return 1
        return runtime_manager.run_pip_cli(sys.argv[2:])

    # Hidden model-download mode: a clean process where HF_HUB_DISABLE_XET is set
    # BEFORE huggingface_hub is imported (the only way to truly disable the Xet
    # backend, which stalls in the bundle), invoked + watchdogged by the parent.
    #   argv: --hf-download <repo_id> <dest_dir>
    if len(sys.argv) >= 4 and sys.argv[1] == "--hf-download":
        try:
            from refchecker.ai_detection import model_manager
            return model_manager.run_hf_download_cli(sys.argv[2], sys.argv[3])
        except Exception as exc:  # noqa: BLE001
            print(f"hf-download mode failed: {exc}", flush=True)
            return 1

    parser = argparse.ArgumentParser(prog="refchecker-server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    data_dir = _resolve_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("REFCHECKER_DATA_DIR", str(data_dir))
    os.environ.setdefault("REFCHECKER_LOG_DIR", str(data_dir / "logs"))

    # Load the in-app auth config (multi-user + OAuth credentials) written by
    # Settings -> "Enable accounts & Teams", so the desktop app can turn on
    # accounts/Teams WITHOUT hand-editing a .env. Applied on each sidecar start;
    # real environment variables still win (setdefault), so docker/.env deploys
    # are unaffected. Delete <data_dir>/auth_config.env to revert to single-user.
    _auth_cfg = data_dir / "auth_config.env"
    try:
        if _auth_cfg.exists():
            for _line in _auth_cfg.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _k, _v = _line.split("=", 1)
                _k, _v = _k.strip(), _v.strip()
                if _k and _v:
                    os.environ.setdefault(_k, _v)
    except Exception as _e:  # noqa: BLE001
        print(f"auth_config load skipped: {_e}", flush=True)

    import uvicorn  # noqa: E402  (imported after env is set; sys.path set above)

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
