# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the RefChecker desktop sidecar.

Run from the repo root (so that `src/refchecker` and `backend/` resolve):

    pyinstaller tauri-app/python/refchecker-server.spec --noconfirm
"""
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

REPO_ROOT = Path(os.environ.get("REFCHECKER_REPO_ROOT", os.getcwd())).resolve()
RUNTIME_TMPDIR = os.environ.get("PYINSTALLER_RUNTIME_TMPDIR") or None

ENTRY_SCRIPT = str(REPO_ROOT / "tauri-app" / "python" / "server_entry.py")

# Where Python should look for our two top-level packages during analysis.
PATHS = [
    str(REPO_ROOT),
    str(REPO_ROOT / "src"),
]

# Ship the prebuilt SPA + any package data alongside the binary.
datas = []
static_dir = REPO_ROOT / "backend" / "static"
if static_dir.exists():
    for path in static_dir.rglob("*"):
        if path.is_file():
            rel_parent = path.parent.relative_to(REPO_ROOT)
            datas.append((str(path), str(rel_parent)))

# Backend / refchecker data files (configs, txt, md, conf)
for root, suffixes in [
    (REPO_ROOT / "src" / "refchecker", (".conf", ".txt", ".md", ".json")),
    (REPO_ROOT / "backend", (".html", ".css", ".js", ".svg")),
]:
    if not root.exists():
        continue
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in suffixes:
            rel_parent = path.parent.relative_to(REPO_ROOT)
            datas.append((str(path), str(rel_parent)))

datas += collect_data_files("uvicorn")
datas += collect_data_files("fastapi")

hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("uvicorn.protocols")
hiddenimports += collect_submodules("uvicorn.loops")
hiddenimports += collect_submodules("uvicorn.lifespan")
hiddenimports += collect_submodules("backend")
hiddenimports += collect_submodules("refchecker")
hiddenimports += [
    "fastapi",
    "starlette",
    "starlette.routing",
    "pydantic",
    "pydantic.deprecated.decorator",
    "aiosqlite",
    "websockets",
    "websockets.legacy",
    "websockets.legacy.server",
    "httpx",
    "h11",
    "anyio",
    "email_validator",
    "jose",
    "jose.backends.cryptography_backend",
    "itsdangerous",
    "PIL",
    "PIL.Image",
    "fitz",  # pymupdf
    "pdfplumber",
    "pypdf",
    "bs4",
    "lxml",
    "Levenshtein",
    "fuzzywuzzy",
    "openai",
    "anthropic",
    "google.genai",
    "multipart",
    "python_multipart",
]

a = Analysis(
    [ENTRY_SCRIPT],
    pathex=PATHS,
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        "torch",       # vllm is opt-in; keep desktop bundle small
        "vllm",
        "transformers",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="refchecker-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=RUNTIME_TMPDIR,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
