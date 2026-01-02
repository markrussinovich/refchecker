#!/usr/bin/env python3
"""
Main entry point for RefChecker CLI

This is a wrapper that imports and runs the core refchecker functionality
with the proper package structure.

Usage:
    python run_refchecker.py --paper PAPER_SPEC [options]
    
Alternatively, you can run as a module:
    python -m refchecker --paper PAPER_SPEC [options]
    
Or if installed via pip:
    academic-refchecker --paper PAPER_SPEC [options]
"""

import sys
import os

# Add the src directory to Python path so refchecker package can be found
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from refchecker.core.refchecker import main

if __name__ == "__main__":
    main()