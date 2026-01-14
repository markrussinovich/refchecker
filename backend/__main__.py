#!/usr/bin/env python3
"""
Allow running backend as a module: python -m backend

This provides a clean entry point for the WebUI backend server.
"""

from .cli import main

if __name__ == "__main__":
    main()
