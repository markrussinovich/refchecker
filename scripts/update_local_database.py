#!/usr/bin/env python3
"""Convenience wrapper for building or refreshing local RefChecker databases."""

import argparse
import os
from pathlib import Path
import sys

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from refchecker.database.local_database_updater import main


def _acquire_refresh_lock(argv):
    """Hold a per-database lock for the lifetime of this refresh process."""
    if fcntl is None:
        return None, False

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--database')
    parser.add_argument('--db-path')
    args, _ = parser.parse_known_args(argv)
    if not args.database or not args.db_path:
        return None, False

    db_path = Path(args.db_path).expanduser().resolve()
    lock_path = db_path.with_name(f'.{db_path.name}.{args.database}.refresh.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open('w')
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(
            f'{args.database} refresh already running for {db_path}; skipping',
            file=sys.stderr,
        )
        lock_handle.close()
        return None, True

    lock_handle.write(f'{os.getpid()}\n')
    lock_handle.flush()
    return lock_handle, False


if __name__ == '__main__':
    refresh_lock, skipped = _acquire_refresh_lock(sys.argv[1:])
    if skipped:
        raise SystemExit(0)
    try:
        raise SystemExit(main())
    finally:
        if refresh_lock is not None:
            refresh_lock.close()