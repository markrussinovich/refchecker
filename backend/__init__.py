# Backend package for RefChecker Web UI
"""
RefChecker Web UI Backend

This package provides the FastAPI backend for the RefChecker Web UI,
including WebSocket support for real-time progress updates.

Usage:
    # As a command line tool (after pip install):
    refchecker-webui --host 0.0.0.0 --port 8000
    
    # As a Python module:
    python -m backend --host 0.0.0.0 --port 8000
    
    # With uvicorn directly:
    uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""

# Load .env before any other imports so auth/config modules see the values.
try:
    from pathlib import Path as _Path
    import sys as _sys

    _repo_root = _Path(__file__).resolve().parent.parent
    _src_dir = _repo_root / "src"
    if _src_dir.is_dir() and str(_src_dir) not in _sys.path:
        _sys.path.insert(0, str(_src_dir))

    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_repo_root / ".env")
except ImportError:
    pass

# Expose `app` LAZILY (PEP 562). Eagerly importing backend.main here forced the
# entire FastAPI app + refchecker.core (tqdm/fitz/…) to load whenever ANY leaf
# backend module was imported — which broke lightweight imports/tests of pure
# modules like backend.inline_citation_checker in minimal environments. Serving
# still uses `backend.main:app` directly, and `from backend import app` keeps
# working via this hook.
def __getattr__(name):
    if name == "app":
        from .main import app
        return app
    raise AttributeError(f"module 'backend' has no attribute {name!r}")


__all__ = ["app"]