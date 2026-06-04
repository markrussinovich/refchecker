# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the RefChecker desktop sidecar.

Run from the repo root (so that `src/refchecker` and `backend/` resolve):

    pyinstaller tauri-app/python/refchecker-server.spec --noconfirm
"""
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

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

# Ship the refchecker package SOURCE (.py) alongside the bytecode. PyInstaller
# normally bundles only .pyc, so a module's __file__ points to a path under the
# extraction dir that does NOT exist. When torch/transformers emit a warning (or
# anything raises a traceback) while a refchecker frame is on the stack, Python's
# formatter tries to read that frame's source line via that path and raises
#   FileNotFoundError: .../_MEIxxxx/refchecker/ai_detection/local_backend.py
# which surfaced as "local detection model failed to load". Placing the .py at
# the same path the loader reports makes inspect/warnings/tracebacks behave
# exactly as in dev (no read failure), for every module — not just the one that
# happened to warn this time. Target path mirrors the import name (refchecker/…,
# NOT src/refchecker/…), matching the reported __file__.
_src_root = REPO_ROOT / "src"
_pkg_src = _src_root / "refchecker"
if _pkg_src.exists():
    for path in _pkg_src.rglob("*.py"):
        if path.is_file():
            rel_parent = path.parent.relative_to(_src_root)
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

# Bundle pip (+ its vendored deps) so the optional AI-detection inference
# runtime can be installed from the app in the frozen desktop build: the
# install re-invokes this bundle in a clean `--pip-install` subprocess that runs
# `pip install --target <app-data>`, resolving wheels for THIS interpreter's
# version/platform (ABI-matched). Without a bundled pip the subprocess falls
# back to downloading the standalone pip.pyz.
try:
    _pip_datas, _pip_bins, _pip_hidden = collect_all("pip")
    datas += _pip_datas
    hiddenimports += _pip_hidden
except Exception:
    pass  # pip missing at build time → runtime falls back to pip.pyz download

# Belt-and-suspenders for the known import-shadowing case: the base app imports
# only `from tqdm import tqdm`, so PyInstaller freezes a PARTIAL tqdm (no
# tqdm/auto.py) that shadows the complete pip-installed runtime copy
# ("No module named 'tqdm.auto'"). collect_all bundles the COMPLETE tqdm so it
# works even if the runtime_manager meta-path finder is bypassed. (tqdm is a
# build-time base dep, so this is present.)
try:
    _tq_datas, _tq_bins, _tq_hidden = collect_all("tqdm")
    datas += _tq_datas
    hiddenimports += _tq_hidden
except Exception:
    pass

# Ship the FULL Python standard library. The optional AI-detection runtime
# (torch / transformers, pip-installed at runtime into a --target dir) imports
# stdlib modules the base app never uses — e.g. torch needs `timeit`, which
# PyInstaller would otherwise omit, giving "ModuleNotFoundError: No module
# named 'timeit'" at import time. Adding every stdlib top-level name (plus the
# submodules of the packages torch/transformers/numpy reach into) makes any
# pip-installed runtime importable inside the frozen interpreter.
import sys as _sys
_STDLIB_SKIP = {
    "tkinter", "turtle", "turtledemo", "idlelib", "lib2to3", "antigravity",
    "this", "test", "pydoc_data", "ensurepip", "venv",
}
hiddenimports += [
    _m for _m in sorted(getattr(_sys, "stdlib_module_names", set()))
    if not _m.startswith("_") and _m not in _STDLIB_SKIP
]
for _pkg in ("xml", "concurrent", "ctypes", "multiprocessing", "logging",
             "json", "http", "email", "unittest", "importlib", "encodings",
             "collections", "sqlite3", "urllib", "html", "wsgiref", "asyncio",
             "dbm", "curses"):
    try:
        hiddenimports += collect_submodules(_pkg)
    except Exception:
        pass

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
        "torch",         # vllm is opt-in; keep desktop bundle small
        "vllm",
        "transformers",  # also the AI-detection local backend — opt-in download
        "onnxruntime",   # AI-detection local backend runtime — installed separately
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
