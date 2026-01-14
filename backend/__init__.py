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

from .main import app

__all__ = ["app"]