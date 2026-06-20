"""Regression tests for the total_refs over-count bug.

BUG (reproduced live): the progress read "Checking references (28/23) · 122%
complete" and history rows showed "59/43" — processed_refs exceeded total_refs,
so progress went past 100%. Root cause: total_refs was an EARLY estimate (the
initial extraction count) while the actual number of references checked could be
higher (de-dup / merge / re-extraction), so processed overshot the denominator.

The fix reconciles total_refs to the REAL final reference count: it is raised to
at least processed_refs once the reference set is known, so progress can never
exceed 100%. These tests pin that invariant at the database recompute layer
(``_compute_reference_buckets_from_results`` + the read paths that consume it).
"""
import asyncio

from backend.database import Database, _compute_reference_buckets_from_results


def _run(coro):
    return asyncio.run(coro)


def _verified_refs(n):
    """n distinct, finalized 'verified' reference results."""
    return [
        {"index": i + 1, "status": "verified", "errors": [], "warnings": [], "suggestions": []}
        for i in range(n)
    ]


def test_pure_recompute_raises_total_to_processed():
    """The reconciled total is never below the real processed count, even when
    the stored estimate (43) lagged the actual reference set (59)."""
    results = _verified_refs(59)

    buckets = _compute_reference_buckets_from_results(
        results, is_complete=True, stored_total_refs=43,
    )

    assert buckets["processed_refs"] == 59
    # total_refs reconciled UP to the real count — no more "59/43".
    assert buckets["total_refs"] == 59
    assert buckets["total_refs"] >= buckets["processed_refs"]


def test_pure_recompute_keeps_larger_stored_total():
    """When the stored total already exceeds processed (refs still streaming in),
    the larger stored total is preserved — we never shrink the denominator."""
    results = _verified_refs(10)

    buckets = _compute_reference_buckets_from_results(
        results, is_complete=False, stored_total_refs=23,
    )

    assert buckets["processed_refs"] == 10
    assert buckets["total_refs"] == 23
    assert buckets["total_refs"] >= buckets["processed_refs"]


def test_pure_recompute_handles_missing_stored_total():
    """With no stored total, total_refs falls back to the processed count."""
    results = _verified_refs(7)

    buckets = _compute_reference_buckets_from_results(results, is_complete=True)

    assert buckets["processed_refs"] == 7
    assert buckets["total_refs"] == 7


def test_completed_check_reconciles_total_to_real_count(tmp_path):
    """End-to-end through the DB: persist an early total_refs estimate (23) but a
    results_json with MORE verified refs (28), then assert both the history card
    and the detail view report total_refs >= processed_refs (no 122%)."""
    db = Database(str(tmp_path / "history.db"))
    _run(db.init_db())

    results = _verified_refs(28)

    check_id = _run(db.create_pending_check(
        paper_title="Over-count repro",
        paper_source="https://openreview.net/forum?id=overcount",
        source_type="url",
    ))

    # Persist the EARLY estimate (23) alongside the real 28-ref result set —
    # exactly the de-dup/merge/re-extraction race that produced "28/23 · 122%".
    _run(db.update_check_results(
        check_id=check_id,
        paper_title="Over-count repro",
        total_refs=23,
        errors_count=0,
        warnings_count=0,
        suggestions_count=0,
        unverified_count=0,
        refs_with_errors=0,
        refs_with_warnings_only=0,
        refs_verified=28,
        results=results,
        status="completed",
        refs_with_suggestions_only=0,
        hallucination_count=0,
    ))

    history_item = _run(db.get_history(limit=1))[0]
    detail_item = _run(db.get_check_by_id(check_id))

    for item in (history_item, detail_item):
        assert item["processed_refs"] == 28
        # Reconciled to the real count: total >= processed, so the UI computes
        # 28/28 = 100% rather than 28/23 = 122%.
        assert item["total_refs"] >= item["processed_refs"]
        assert item["total_refs"] == 28
        # The invariant the UI relies on to clamp progress.
        assert (item["processed_refs"] / item["total_refs"]) <= 1.0
