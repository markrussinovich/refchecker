"""Reconciler for orphaned in_progress checks (Z1).

A run_check task that dies — or a server restart — between the last reference
and the terminal 'completed' write leaves the DB row stuck at 'in_progress'
forever, so a polling FE never unsticks and AI-detection never appears. These
tests pin the safety contract of the reconciler in backend/database.py:

  • a STALE orphan (not in the live active_checks map, refs all in) is finalized
    to a terminal status COMPUTED from its stored references;
  • a check that IS in active_checks (genuinely running) is NEVER touched;
  • a FRESH orphan (recent, refs not done) is left alone;
  • a zero-ref orphan finalizes to 'error', not 'completed';
  • finalize is idempotent / never downgrades an already-terminal row;
  • AI-detection that never attached is recorded 'unavailable'.
"""
import asyncio
import json

from backend.database import Database


def _run(coro):
    return asyncio.run(coro)


# Two processed refs (1 error, 1 verified) — used for the "all refs in" orphan.
_DONE_REFS = [
    {
        "status": "error",
        "errors": [{"error_type": "author", "error_details": "Author mismatch"}],
        "warnings": [],
        "suggestions": [],
    },
    {
        "status": "verified",
        "errors": [],
        "warnings": [],
        "suggestions": [],
    },
]


def _new_db(tmp_path):
    db = Database(str(tmp_path / "history.db"))
    _run(db.init_db())
    return db


def _set_in_progress_with_refs(db, check_id, refs, total_refs):
    """Force a row into the stuck state: in_progress + persisted refs."""
    async def _go():
        async with __import__("aiosqlite").connect(db.db_path) as conn:
            await conn.execute(
                "UPDATE check_history SET status = 'in_progress', "
                "results_json = ?, total_refs = ? WHERE id = ?",
                (json.dumps(refs), total_refs, check_id),
            )
            await conn.commit()
    _run(_go())


def _make_pending(db, title="Stuck Paper"):
    return _run(db.create_pending_check(
        paper_title=title,
        paper_source="https://openreview.net/forum?id=stuckExample",
        source_type="url",
    ))


def test_stale_orphan_with_all_refs_done_is_finalized_to_computed_status(tmp_path):
    db = _new_db(tmp_path)
    check_id = _make_pending(db)
    # processed (2) >= total (2) > 0  => stale regardless of timestamp.
    _set_in_progress_with_refs(db, check_id, _DONE_REFS, total_refs=2)

    # Not in the live map → eligible.
    stale = _run(db.find_stale_in_progress_checks(active_check_ids=set()))
    assert any(int(r["id"]) == check_id for r in stale)

    terminal = _run(db.finalize_stale_check(check_id))
    assert terminal == "completed"

    row = _run(db.get_check_by_id(check_id))
    assert row["status"] == "completed"
    assert row["completed_at"]  # stamped
    assert "reconciled" in (row.get("cancel_reason") or "")
    # Status computed FROM the stored references, not fabricated.
    assert row["errors_count"] == 1
    assert row["refs_with_errors"] == 1
    assert row["refs_verified"] == 1
    # AI-detection never attached → honest 'unavailable'.
    assert row.get("ai_detection") is not None
    assert row["ai_detection"].get("band") == "unavailable"


def test_check_in_active_map_is_never_finalized(tmp_path):
    db = _new_db(tmp_path)
    check_id = _make_pending(db)
    _set_in_progress_with_refs(db, check_id, _DONE_REFS, total_refs=2)

    # It IS genuinely running (present in the live active_checks ids).
    stale = _run(db.find_stale_in_progress_checks(active_check_ids={check_id}))
    assert all(int(r["id"]) != check_id for r in stale)

    reconciled = _run(db.reconcile_stale_in_progress(active_check_ids={check_id}))
    assert reconciled == 0

    row = _run(db.get_check_by_id(check_id))
    assert row["status"] == "in_progress"  # left untouched
    assert not row.get("completed_at")


def test_fresh_in_progress_with_refs_not_done_is_left_untouched(tmp_path):
    db = _new_db(tmp_path)
    check_id = _make_pending(db)
    # Only 1 of 5 refs processed, and just stamped now → NOT stale.
    _set_in_progress_with_refs(db, check_id, _DONE_REFS[:1], total_refs=5)

    # Long staleness window so the time-fallback can't fire either.
    stale = _run(db.find_stale_in_progress_checks(
        active_check_ids=set(), stale_after_seconds=3600,
    ))
    assert all(int(r["id"]) != check_id for r in stale)

    reconciled = _run(db.reconcile_stale_in_progress(
        active_check_ids=set(), stale_after_seconds=3600,
    ))
    assert reconciled == 0

    row = _run(db.get_check_by_id(check_id))
    assert row["status"] == "in_progress"


def test_zero_ref_orphan_finalizes_to_error(tmp_path):
    db = _new_db(tmp_path)
    check_id = _make_pending(db)
    # No usable refs at all, but old enough to be time-stale.
    _set_in_progress_with_refs(db, check_id, [], total_refs=0)

    async def _age_it():
        async with __import__("aiosqlite").connect(db.db_path) as conn:
            await conn.execute(
                "UPDATE check_history SET started_at = '2000-01-01 00:00:00', "
                "timestamp = '2000-01-01 00:00:00' WHERE id = ?",
                (check_id,),
            )
            await conn.commit()
    _run(_age_it())

    terminal = _run(db.finalize_stale_check(check_id))
    assert terminal == "error"
    row = _run(db.get_check_by_id(check_id))
    assert row["status"] == "error"


def test_finalize_is_idempotent_and_never_downgrades_terminal(tmp_path):
    db = _new_db(tmp_path)
    check_id = _make_pending(db)
    _set_in_progress_with_refs(db, check_id, _DONE_REFS, total_refs=2)

    first = _run(db.finalize_stale_check(check_id))
    assert first == "completed"
    # Second call sees a terminal row → no-op, returns None, doesn't clobber.
    second = _run(db.finalize_stale_check(check_id))
    assert second is None
    row = _run(db.get_check_by_id(check_id))
    assert row["status"] == "completed"


def test_reconcile_sweep_finalizes_only_eligible_rows(tmp_path):
    db = _new_db(tmp_path)
    orphan = _make_pending(db, title="Orphan")
    running = _make_pending(db, title="Running")
    fresh = _make_pending(db, title="Fresh")
    _set_in_progress_with_refs(db, orphan, _DONE_REFS, total_refs=2)
    _set_in_progress_with_refs(db, running, _DONE_REFS, total_refs=2)
    _set_in_progress_with_refs(db, fresh, _DONE_REFS[:1], total_refs=5)

    finalized = _run(db.reconcile_stale_in_progress(
        active_check_ids={running}, stale_after_seconds=3600,
    ))
    assert finalized == 1  # only the orphan

    assert _run(db.get_check_by_id(orphan))["status"] == "completed"
    assert _run(db.get_check_by_id(running))["status"] == "in_progress"
    assert _run(db.get_check_by_id(fresh))["status"] == "in_progress"
