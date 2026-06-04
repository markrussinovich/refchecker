#!/usr/bin/env python3
"""Regression test for the Seen-References live write path.

`upsert_verified_reference` referenced an undefined `result_json` variable, so
EVERY live write raised NameError (silently swallowed by the wrapper's
emit_progress except) — the seen-library count was frozen because new checks
could never add to it. This locks in that the write records refs and dedups.
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from backend.database import Database  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_seen_refs_upsert_records_and_dedups():
    tmp = tempfile.mktemp(suffix='.db')

    async def run():
        db = Database(tmp)
        await db.init_db()
        assert await db.count_verified_references() == 0

        # Would raise NameError('result_json') before the fix.
        key = await db.upsert_verified_reference(
            {'title': 'A study of widgets', 'authors': ['Jane Smith'],
             'year': 2020, 'status': 'verified', 'doi': '10.1/abc'})
        assert key  # a non-None identity key came back

        await db.upsert_verified_reference(
            {'title': 'A different paper on gadgets', 'authors': ['John Doe'],
             'year': 2021, 'status': 'error', 'doi': '10.2/xyz'})
        assert await db.count_verified_references() == 2  # both recorded

        # Re-seeing the same ref must NOT grow the count (dedup by identity key).
        await db.upsert_verified_reference(
            {'title': 'A study of widgets', 'authors': ['Jane Smith'],
             'year': 2020, 'status': 'verified', 'doi': '10.1/abc'})
        assert await db.count_verified_references() == 2

        growth = await db.verified_references_recent_growth()
        assert growth.get('last_24_hours', 0) >= 2  # the growth chip will move

    try:
        _run(run())
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
