"""Tests for the admin analytics endpoints.

These cover the questions the dashboard exists to answer — how many users,
papers, references and hallucinations — plus the session grouping, which is
synthesised rather than stored and so has no other source of truth.
"""
import asyncio
import importlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend import admin_insights
from backend.database import Database


def _run(coro):
    return asyncio.run(coro)


def _ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def admin_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_admin_insights")
    monkeypatch.setenv("REFCHECKER_MULTIUSER", "true")
    api_main = importlib.reload(importlib.import_module("backend.main"))
    temp_db = Database(str(tmp_path / "admin.db"))
    _run(temp_db.init_db())
    monkeypatch.setattr(api_main, "db", temp_db)
    yield api_main, temp_db


async def _make_user(db, handle, is_admin=False):
    return await db.create_or_update_user(
        provider="github",
        provider_id=handle,
        email=f"{handle}@example.com",
        name=handle,
    )


async def _insert_check(db, **kwargs):
    """Insert a check_history row directly.

    The production write path goes through create_pending_check +
    update_check_results, but these tests need control over timestamps to
    exercise windowing and session grouping.
    """
    import aiosqlite

    fields = {
        "paper_title": "A paper",
        "paper_source": "https://arxiv.org/abs/1706.03762",
        "source_type": "url",
        "status": "completed",
        "total_refs": 10,
        "refs_verified": 8,
        "errors_count": 1,
        "warnings_count": 1,
        "unverified_count": 1,
        "hallucination_count": 0,
        "refs_with_errors": 1,
        "refs_with_warnings_only": 1,
        "suggestions_count": 0,
        "duration_ms": 1000,
        "results_json": None,
        "user_id": None,
        "batch_id": None,
        "batch_label": None,
        "paper_key": None,
        "llm_model": None,
        "extraction_method": None,
        "failure_class": None,
        "timestamp": _ts(datetime.now(timezone.utc)),
    }
    fields.update(kwargs)
    fields.setdefault("started_at", fields["timestamp"])
    fields.setdefault("completed_at", fields["timestamp"])

    columns = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            f"INSERT INTO check_history ({columns}) VALUES ({placeholders})",
            tuple(fields.values()),
        )
        await conn.commit()
        return cursor.lastrowid


def test_overview_totals_count_users_papers_references_and_hallucinations(admin_db):
    api_main, db = admin_db
    alice = _run(_make_user(db, "alice"))
    bob = _run(_make_user(db, "bob"))

    _run(_insert_check(db, user_id=alice, paper_key="arxiv:1", total_refs=10, hallucination_count=2))
    _run(_insert_check(db, user_id=alice, paper_key="arxiv:2", total_refs=5, hallucination_count=0))
    _run(_insert_check(db, user_id=bob, paper_key="arxiv:1", total_refs=7, hallucination_count=1))

    admin = api_main.UserInfo(id=alice, provider="github", is_admin=True)
    result = _run(api_main.get_admin_insights_overview(days=30, current_user=admin))

    totals = result["totals"]
    assert totals["total_users"] == 2
    assert totals["active_users"] == 2
    assert totals["checks"] == 3
    assert totals["distinct_papers"] == 2, "the same paper checked twice is one paper"
    assert totals["references_checked"] == 22
    assert totals["hallucinations"] == 3
    assert totals["papers_with_hallucinations"] == 2
    assert totals["hallucination_rate"] == pytest.approx(3 * 100 / 22, rel=1e-3)
    assert totals["avg_references_per_check"] == pytest.approx(22 / 3, rel=1e-2)


def test_overview_window_excludes_older_checks(admin_db):
    api_main, db = admin_db
    user = _run(_make_user(db, "alice"))
    now = datetime.now(timezone.utc)

    _run(_insert_check(db, user_id=user, timestamp=_ts(now - timedelta(days=2)), total_refs=3))
    _run(_insert_check(db, user_id=user, timestamp=_ts(now - timedelta(days=90)), total_refs=100))

    admin = api_main.UserInfo(id=user, provider="github", is_admin=True)

    recent = _run(api_main.get_admin_insights_overview(days=30, current_user=admin))
    assert recent["totals"]["checks"] == 1
    assert recent["totals"]["references_checked"] == 3

    everything = _run(api_main.get_admin_insights_overview(days=0, current_user=admin))
    assert everything["totals"]["checks"] == 2
    assert everything["totals"]["references_checked"] == 103
    assert everything["window_days"] is None


def test_active_users_counts_only_those_who_checked_in_the_window(admin_db):
    """The headline user count is window-scoped, not the registration total."""
    api_main, db = admin_db
    alice = _run(_make_user(db, "alice"))
    bob = _run(_make_user(db, "bob"))
    _run(_make_user(db, "carol"))  # signed up, never ran a check
    now = datetime.now(timezone.utc)

    _run(_insert_check(db, user_id=alice, timestamp=_ts(now - timedelta(days=2)), total_refs=3))
    _run(_insert_check(db, user_id=alice, timestamp=_ts(now - timedelta(days=3)), total_refs=3))
    # Bob only checked long before the window.
    _run(_insert_check(db, user_id=bob, timestamp=_ts(now - timedelta(days=90)), total_refs=9))

    admin = api_main.UserInfo(id=alice, provider="github", is_admin=True)

    recent = _run(api_main.get_admin_insights_overview(days=30, current_user=admin))
    assert recent["totals"]["active_users"] == 1, "only alice checked in the last 30 days"
    assert recent["totals"]["total_users"] == 3, "registration total is still reported"

    everything = _run(api_main.get_admin_insights_overview(days=0, current_user=admin))
    assert everything["totals"]["active_users"] == 2, "carol never checked"
    assert everything["totals"]["total_users"] == 3


def test_overview_daily_series_buckets_by_day(admin_db):
    api_main, db = admin_db
    user = _run(_make_user(db, "alice"))
    # Anchor at midday so the two same-day checks cannot straddle midnight:
    # offsetting from "now" made this fail whenever the suite ran near 00:00 UTC.
    earlier_day = (datetime.now(timezone.utc) - timedelta(days=2)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    later_day = earlier_day + timedelta(days=1)
    _run(_insert_check(db, user_id=user, timestamp=_ts(earlier_day)))
    _run(_insert_check(db, user_id=user, timestamp=_ts(earlier_day - timedelta(hours=2))))
    _run(_insert_check(db, user_id=user, timestamp=_ts(later_day)))

    admin = api_main.UserInfo(id=user, provider="github", is_admin=True)
    result = _run(api_main.get_admin_insights_overview(days=30, current_user=admin))

    assert len(result["daily"]) == 2
    assert [d["checks"] for d in result["daily"]] == [2, 1]


def test_users_rollup_lists_inactive_users_and_unattributed_checks(admin_db):
    api_main, db = admin_db
    alice = _run(_make_user(db, "alice"))
    _run(_make_user(db, "never-checked"))

    _run(_insert_check(db, user_id=alice, total_refs=10, hallucination_count=2))
    # Rows predating the user_id column must not vanish from the totals.
    _run(_insert_check(db, user_id=None, total_refs=4, hallucination_count=1))

    admin = api_main.UserInfo(id=alice, provider="github", is_admin=True)
    result = _run(api_main.get_admin_insights_users(days=0, limit=100, current_user=admin))

    by_name = {u["name"]: u for u in result["users"]}
    assert by_name["alice"]["checks"] == 1
    assert by_name["alice"]["references_checked"] == 10
    assert by_name["alice"]["hallucinations"] == 2
    assert by_name["alice"]["email_domain"] == "example.com"

    assert by_name["never-checked"]["checks"] == 0, "a signed-up user who never ran a check must still appear"
    assert by_name["never-checked"]["hallucination_rate"] is None

    assert result["unattributed"]["checks"] == 1
    assert result["unattributed"]["references_checked"] == 4


def test_sessions_split_on_an_inactivity_gap(admin_db):
    api_main, db = admin_db
    user = _run(_make_user(db, "alice"))
    base = datetime.now(timezone.utc) - timedelta(hours=6)

    # Two runs close together, then a long pause, then one more.
    _run(_insert_check(db, user_id=user, timestamp=_ts(base)))
    _run(_insert_check(db, user_id=user, timestamp=_ts(base + timedelta(minutes=5))))
    _run(_insert_check(db, user_id=user, timestamp=_ts(base + timedelta(hours=3))))

    admin = api_main.UserInfo(id=user, provider="github", is_admin=True)
    result = _run(
        api_main.get_admin_insights_user_sessions(
            user_id=user, days=0, gap_minutes=30, current_user=admin
        )
    )

    assert result["total_checks"] == 3
    assert len(result["sessions"]) == 2
    # Newest sitting first.
    assert result["sessions"][0]["checks"] == 1
    assert result["sessions"][1]["checks"] == 2
    assert result["user"]["name"] == "alice"


def test_a_batch_is_never_split_across_sessions(admin_db):
    """A batch is an explicit user action; slow batches must stay one session."""
    api_main, db = admin_db
    user = _run(_make_user(db, "alice"))
    base = datetime.now(timezone.utc) - timedelta(hours=8)

    for offset in (0, 90, 180):  # far more than the 30 minute gap
        _run(
            _insert_check(
                db,
                user_id=user,
                batch_id="batch-1",
                batch_label="My batch",
                timestamp=_ts(base + timedelta(minutes=offset)),
            )
        )

    admin = api_main.UserInfo(id=user, provider="github", is_admin=True)
    result = _run(
        api_main.get_admin_insights_user_sessions(
            user_id=user, days=0, gap_minutes=30, current_user=admin
        )
    )

    assert len(result["sessions"]) == 1
    assert result["sessions"][0]["checks"] == 3
    assert result["sessions"][0]["batch_labels"] == ["My batch"]


def test_session_totals_add_up_across_its_checks(admin_db):
    api_main, db = admin_db
    user = _run(_make_user(db, "alice"))
    now = datetime.now(timezone.utc)
    _run(_insert_check(db, user_id=user, timestamp=_ts(now), total_refs=10, hallucination_count=2))
    _run(
        _insert_check(
            db, user_id=user, timestamp=_ts(now + timedelta(minutes=1)),
            total_refs=6, hallucination_count=1,
        )
    )

    admin = api_main.UserInfo(id=user, provider="github", is_admin=True)
    result = _run(
        api_main.get_admin_insights_user_sessions(user_id=user, days=0, current_user=admin)
    )

    session = result["sessions"][0]
    assert session["checks"] == 2
    assert session["references_checked"] == 16
    assert session["hallucinations"] == 3


def test_check_detail_returns_individual_references(admin_db):
    api_main, db = admin_db
    user = _run(_make_user(db, "alice"))
    references = [
        {"index": 0, "title": "Real paper", "status": "verified", "errors": [], "warnings": []},
        {
            "index": 1,
            "title": "Invented paper",
            "status": "unverified",
            "errors": [],
            "warnings": [],
            "hallucination_assessment": {"verdict": "LIKELY"},
        },
    ]
    check_id = _run(
        _insert_check(db, user_id=user, results_json=json.dumps(references), hallucination_count=1)
    )

    admin = api_main.UserInfo(id=user, provider="github", is_admin=True)
    detail = _run(api_main.get_admin_insights_check(check_id=check_id, current_user=admin))

    assert detail["id"] == check_id
    assert len(detail["references"]) == 2
    assert detail["references"][1]["title"] == "Invented paper"
    assert detail["user"]["name"] == "alice", "the admin view must say whose check this was"


def test_check_detail_is_not_scoped_to_the_admins_own_checks(admin_db):
    """The whole point of the admin view: see other people's checks."""
    api_main, db = admin_db
    alice = _run(_make_user(db, "alice"))
    bob = _run(_make_user(db, "bob", is_admin=True))
    check_id = _run(_insert_check(db, user_id=alice))

    admin = api_main.UserInfo(id=bob, provider="github", is_admin=True)
    detail = _run(api_main.get_admin_insights_check(check_id=check_id, current_user=admin))
    assert detail["user"]["name"] == "alice"


def test_missing_check_is_a_404(admin_db):
    api_main, db = admin_db
    admin = api_main.UserInfo(id=1, provider="github", is_admin=True)
    with pytest.raises(HTTPException) as exc:
        _run(api_main.get_admin_insights_check(check_id=999999, current_user=admin))
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "call",
    [
        lambda m, u: m.get_admin_insights_overview(days=30, current_user=u),
        lambda m, u: m.get_admin_insights_users(days=0, limit=10, current_user=u),
        lambda m, u: m.get_admin_insights_papers(days=0, limit=10, current_user=u),
        lambda m, u: m.get_admin_insights_user_sessions(user_id=1, current_user=u),
        lambda m, u: m.get_admin_insights_check(check_id=1, current_user=u),
    ],
)
def test_non_admins_are_refused(admin_db, call):
    api_main, db = admin_db
    intruder = api_main.UserInfo(id=42, provider="github", is_admin=False)
    with pytest.raises(HTTPException) as exc:
        _run(call(api_main, intruder))
    assert exc.value.status_code == 403


def test_unparseable_results_json_does_not_break_the_detail_view(admin_db):
    api_main, db = admin_db
    user = _run(_make_user(db, "alice"))
    check_id = _run(_insert_check(db, user_id=user, results_json="{not json"))

    admin = api_main.UserInfo(id=user, provider="github", is_admin=True)
    detail = _run(api_main.get_admin_insights_check(check_id=check_id, current_user=admin))
    assert detail["references"] == []


def test_session_grouping_handles_missing_timestamps():
    """Rows written by older versions can lack started_at/completed_at."""
    sessions = admin_insights.group_checks_into_sessions(
        [
            {"id": 1, "timestamp": None, "started_at": None, "completed_at": None},
            {"id": 2, "timestamp": "2026-01-01 10:00:00"},
        ],
        gap_minutes=30,
    )
    assert sum(s["checks"] for s in sessions) == 2


def test_empty_database_reports_zeros_not_errors(admin_db):
    api_main, db = admin_db
    admin = api_main.UserInfo(id=1, provider="github", is_admin=True)

    overview = _run(api_main.get_admin_insights_overview(days=30, current_user=admin))
    assert overview["totals"]["checks"] == 0
    assert overview["totals"]["hallucination_rate"] is None
    assert overview["daily"] == []

    users = _run(api_main.get_admin_insights_users(days=0, limit=10, current_user=admin))
    assert users["users"] == []
