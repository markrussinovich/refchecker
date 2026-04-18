#!/usr/bin/env python3
"""Convenience wrapper for building or refreshing local RefChecker databases."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from refchecker.database.local_database_updater import main


if __name__ == '__main__':
    raise SystemExit(main())