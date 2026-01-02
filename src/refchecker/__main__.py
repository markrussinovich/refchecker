#!/usr/bin/env python3
"""
Allow running refchecker as a module: python -m refchecker

This provides a clean entry point without import collision issues.
"""

from .core.refchecker import main

if __name__ == "__main__":
    main()
