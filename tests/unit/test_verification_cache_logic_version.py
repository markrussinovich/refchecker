#!/usr/bin/env python3
"""Cached verdicts must not outlive the logic that produced them.

The WebUI caches whole verification results keyed on a reference's identity and
replays them for any reference it has seen before. The cache had no notion of
*which code* produced a stored verdict, so a fixed bug was never visible for a
reference anyone had already checked — the stale verdict was replayed forever,
and even the "Re-verify" button replayed it.

Real case: reference 1 of the user's paper (a Kimi model card) kept reporting
"Cited URL does not reference this paper" from a cache entry written before the
blocked-URL fix, carrying ``from_cache: true``.

A logic-version stamp fixes this. Rows written by superseded logic stay in the
Seen References library but stop short-circuiting verification.
"""

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import backend.database as backend_db  # noqa: E402
from backend.database import Database, cached_result_is_current  # noqa: E402
from refchecker.core.verification_logic_version import VERIFICATION_LOGIC_VERSION  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


KIMI = {
    'title': 'Kimi K3: Model weights and technical report',
    'authors': ['Moonshot AI'],
    'year': 2026,
    'venue': 'Open-weight release',
    'doi': '10.9/kimi-k3',
    'status': 'unverified',
    'errors': [{
        'error_type': 'url',
        'error_details': 'Cited URL does not reference this paper: https://huggingface.co/moonshotai/Kimi-K3',
    }],
}


class TestLogicVersionConstant:
    def test_version_is_a_positive_int(self):
        assert isinstance(VERIFICATION_LOGIC_VERSION, int)
        assert VERIFICATION_LOGIC_VERSION > 0

    def test_backend_reads_the_shared_core_value(self):
        """All three paths must agree on one value, so the backend reads the core."""
        assert backend_db.current_verification_logic_version() == VERIFICATION_LOGIC_VERSION


class TestCachedResultIsCurrent:
    def test_missing_stamp_is_stale(self):
        """Every row written before the stamp existed must be re-verified."""
        assert not cached_result_is_current({'logic_version': None})

    def test_absent_column_is_stale(self):
        """Can't prove currency without the column, so don't trust the row."""
        assert not cached_result_is_current({})

    def test_older_version_is_stale(self):
        assert not cached_result_is_current({'logic_version': VERIFICATION_LOGIC_VERSION - 1})

    def test_current_version_is_fresh(self):
        assert cached_result_is_current({'logic_version': VERIFICATION_LOGIC_VERSION})

    def test_unparseable_version_is_stale(self):
        assert not cached_result_is_current({'logic_version': 'banana'})


class TestCacheReplay:
    @pytest.mark.parametrize('cached_year,cited_year', [(2016, 2015), (2015, 2016)])
    def test_same_doi_with_different_year_must_be_reverified(self, tmp_path, cached_year, cited_year):
        async def run():
            db = Database(str(tmp_path / 'resnet.db'))
            await db.init_db()
            reference = {
                'title': 'Deep Residual Learning for Image Recognition',
                'authors': 'Kaiming He, Xiangyu Zhang, Shaoqing Ren, Jian Sun',
                'year': cached_year,
                'venue': 'CVPR',
                'doi': '10.1109/cvpr.2016.90',
                'status': 'verified',
            }
            await db.upsert_verified_reference(reference)
            changed = dict(reference, year=cited_year)

            assert await db.lookup_verified_reference(changed) is None
            assert await db.find_verified_by_fuzzy(changed) is None
            assert await db.count_verified_references() == 1

        _run(run())

    def test_cache_hit_cannot_overwrite_the_cited_year(self, tmp_path):
        async def run():
            db = Database(str(tmp_path / 'overwritten-year.db'))
            await db.init_db()
            cited = {
                'title': 'Deep Residual Learning for Image Recognition',
                'authors': 'Kaiming He, Xiangyu Zhang, Shaoqing Ren, Jian Sun',
                'year': 2015, 'doi': '10.1109/cvpr.2016.90',
            }
            await db.upsert_verified_reference(dict(
                cited, year=2016, original_reference=dict(cited), status='verified',
            ))

            assert await db.lookup_verified_reference(cited) is None
            assert await db.find_verified_by_fuzzy(cited) is None

        _run(run())

    def test_stale_entry_is_not_replayed_but_is_still_listed(self):
        tmp = tempfile.mktemp(suffix='.db')

        async def run():
            db = Database(tmp)
            await db.init_db()

            key = await db.upsert_verified_reference(dict(KIMI))
            assert key

            # Simulate an entry written by the previous release.
            import aiosqlite
            async with aiosqlite.connect(tmp) as raw:
                await raw.execute(
                    "UPDATE verified_reference_identity SET logic_version = NULL")
                await raw.commit()

            assert await db.lookup_verified_reference(dict(KIMI)) is None, \
                "A verdict from superseded logic must not short-circuit verification"
            assert await db.find_verified_by_fuzzy(dict(KIMI)) is None, \
                "The fuzzy lookup must respect the logic version too"

            # The library keeps showing it — we invalidate replay, not history.
            assert await db.count_verified_references() == 1
            rows = await db.list_verified_references()
            assert any(r.get('title') == KIMI['title'] for r in rows)

        try:
            _run(run())
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_current_entry_is_still_replayed(self):
        """The cache must keep working — it saves substantial network/LLM traffic."""
        tmp = tempfile.mktemp(suffix='.db')

        async def run():
            db = Database(tmp)
            await db.init_db()
            await db.upsert_verified_reference(dict(KIMI))

            cached = await db.lookup_verified_reference(dict(KIMI))
            assert cached is not None, "A freshly written entry must still be a cache hit"
            assert cached['result']['title'] == KIMI['title']

        try:
            _run(run())
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_reverify_overwrites_the_stale_row(self):
        """Re-checking a stale reference must refresh both the verdict and stamp."""
        tmp = tempfile.mktemp(suffix='.db')

        async def run():
            db = Database(tmp)
            await db.init_db()
            await db.upsert_verified_reference(dict(KIMI))

            import aiosqlite
            async with aiosqlite.connect(tmp) as raw:
                await raw.execute(
                    "UPDATE verified_reference_identity SET logic_version = NULL")
                await raw.commit()
            assert await db.lookup_verified_reference(dict(KIMI)) is None

            # The re-verification the cache miss forces, now clean.
            fixed = dict(KIMI, status='verified', errors=[])
            await db.upsert_verified_reference(fixed)

            cached = await db.lookup_verified_reference(dict(KIMI))
            assert cached is not None, "The refreshed entry must be usable again"
            assert cached['result']['errors'] == []
            assert await db.count_verified_references() == 1  # updated, not duplicated

        try:
            _run(run())
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


class TestVerificationCacheKey:
    def test_key_changes_with_the_logic_version(self, monkeypatch):
        """The second cache is versioned via its key rather than a column."""
        db = Database(tempfile.mktemp(suffix='.db'))
        before = db._compute_reference_cache_key(dict(KIMI))

        monkeypatch.setattr(
            backend_db, 'current_verification_logic_version',
            lambda: VERIFICATION_LOGIC_VERSION + 1)
        after = db._compute_reference_cache_key(dict(KIMI))

        assert before != after, "Superseded results must stop being addressable"

    def test_key_is_stable_for_the_same_reference(self):
        db = Database(tempfile.mktemp(suffix='.db'))
        assert db._compute_reference_cache_key(dict(KIMI)) == \
            db._compute_reference_cache_key(dict(KIMI))
