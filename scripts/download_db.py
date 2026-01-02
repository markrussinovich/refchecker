#!/usr/bin/env python3
"""
Convenience script to download Semantic Scholar database
"""

import sys
import os

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from refchecker.database.download_semantic_scholar_db import main

if __name__ == "__main__":
    main()