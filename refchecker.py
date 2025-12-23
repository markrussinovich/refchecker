#!/usr/bin/env python3
"""
Main entry point for RefChecker CLI

This is a wrapper that imports and runs the core refchecker functionality
with the proper package structure.
"""

import sys
import os

# Add the package directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import all modules to ensure they're available
import refchecker.checkers.semantic_scholar
import refchecker.checkers.local_semantic_scholar
import refchecker.checkers.openalex
import refchecker.checkers.crossref
import refchecker.checkers.enhanced_hybrid_checker
import refchecker.utils.text_utils
import refchecker.utils.author_utils
from refchecker.core.refchecker import main

if __name__ == "__main__":
    main()