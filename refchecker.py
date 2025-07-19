#!/usr/bin/env python3
"""
Main entry point for RefChecker CLI

This is a wrapper that imports and runs the core refchecker functionality
with the proper package structure.
"""

import sys
import os

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import all modules to ensure they're available
import checkers.semantic_scholar
import checkers.local_semantic_scholar
import checkers.openalex
import checkers.crossref
import checkers.enhanced_hybrid_checker
import utils.text_utils
import utils.author_utils

from core.refchecker import main

if __name__ == "__main__":
    main()