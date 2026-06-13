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
    parser = argparse.ArgumentParser(prog="refchecker-server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    data_dir = _resolve_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("REFCHECKER_DATA_DIR", str(data_dir))
    os.environ.setdefault("REFCHECKER_LOG_DIR", str(data_dir / "logs"))

    # PyInstaller unpacks bundled files under sys._MEIPASS. Make sure the
    # backend's package-relative lookups (e.g. backend/static/index.html)
    # still resolve.
    if hasattr(sys, "_MEIPASS"):
        sys.path.insert(0, sys._MEIPASS)

    import uvicorn  # noqa: E402  (imported after env is set)

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
