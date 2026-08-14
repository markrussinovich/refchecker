"""Tests for the admin dashboard's paper rollup and user-activity distinctions.

Two defects motivate these:

* ``paper_key`` is not unique per paper. Every untitled upload is stored as
  ``title:unknown-paper`` and every pasted body as ``title:pasted-text``, so
  counting distinct keys merged hundreds of unrelated documents into one.
* The user list could not distinguish somebody who signed up and never ran
  anything from somebody who was busy last quarter, because both show zero
  inside the selected window.
"""
import asyncio
import importlib
from datetime import datetime, timedelta, timezone

import pytest

from backend import admin_insights
from backend.database import Database


def _run(coro):
    return asyncio.run(coro)


def _ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def admin_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_admin_papers")
    monkeypatch.setenv("REFCHECKER_MULTIUSER", "true")
    api_main = importlib.reload(importlib.import_module("backend.main"))
    temp_db = Database(str(tmp_path / "admin.db"))
    _run(temp_db.init_db())
    monkeypatch.setattr(api_main, "db", temp_db)
    yield api_main, temp_db


async def _make_user(db, handle):
    return await db.create_or_update_user(
        provider="github", provider_id=handle, email=f"{handle}@example.com", name=handle
    )


async def _insert_check(db, **kwargs):
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
        "user_id": None,
        "paper_key": None,
        "paper_identifier_type": None,
        "paper_identifier_value": None,
        "original_filename": None,
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


class TestPlaceholderKeysAreNotAPaperIdentity:
    """The bug that made 189 pasted texts look like a single paper."""

    def test_pasted_texts_are_separate_papers(self, admin_db):
        _, db = admin_db
        for _ in range(3):
            _run(
                _insert_check(
                    db, paper_key="title:pasted-text", paper_title="Pasted Text", source_type="text"
                )
            )

        report = _run(admin_insights.get_papers(db.db_path, days=0))

        assert report["total_papers"] == 3
        assert len({p["paper_id"] for p in report["papers"]}) == 3

    def test_untitled_uploads_group_by_filename_not_by_placeholder(self, admin_db):
        _, db = admin_db
        _run(_insert_check(db, paper_key="title:unknown-paper", paper_title="custom.bib"))
        _run(_insert_check(db, paper_key="title:unknown-paper", paper_title="custom.bib"))
        _run(_insert_check(db, paper_key="title:unknown-paper", paper_title="other.bib"))

        report = _run(admin_insights.get_papers(db.db_path, days=0))

        assert report["total_papers"] == 2
        by_title = {p["title"]: p for p in report["papers"]}
        assert by_title["custom.bib"]["checks"] == 2
        assert by_title["other.bib"]["checks"] == 1

    def test_a_real_key_still_groups_repeat_checks(self, admin_db):
        _, db = admin_db
        _run(_insert_check(db, paper_key="arxiv:1706.03762", paper_title="Attention"))
        _run(_insert_check(db, paper_key="arxiv:1706.03762", paper_title="Attention Is All"))

        report = _run(admin_insights.get_papers(db.db_path, days=0))

        assert report["total_papers"] == 1
        assert report["papers"][0]["checks"] == 2

    def test_rows_with_no_key_and_no_title_never_merge(self, admin_db):
        # paper_title is NOT NULL in the schema, so "no title" is the empty string.
        _, db = admin_db
        _run(_insert_check(db, paper_key=None, paper_title=""))
        _run(_insert_check(db, paper_key=None, paper_title="   "))

        report = _run(admin_insights.get_papers(db.db_path, days=0))

        assert report["total_papers"] == 2

    def test_overview_distinct_papers_uses_the_same_identity(self, admin_db):
        """The overview count and the papers list must never disagree."""
        _, db = admin_db
        for _ in range(4):
            _run(_insert_check(db, paper_key="title:pasted-text", paper_title="Pasted Text"))
        _run(_insert_check(db, paper_key="arxiv:1", paper_title="Attention"))

        overview = _run(admin_insights.get_overview(db.db_path, days=0))
        papers = _run(admin_insights.get_papers(db.db_path, days=0))

        assert overview["totals"]["distinct_papers"] == papers["total_papers"] == 5


class TestPapersAreChronological:
    def test_most_recently_checked_first(self, admin_db):
        _, db = admin_db
        now = datetime.now(timezone.utc)
        _run(_insert_check(db, paper_key="arxiv:old", timestamp=_ts(now - timedelta(days=5))))
        _run(_insert_check(db, paper_key="arxiv:new", timestamp=_ts(now - timedelta(hours=1))))
        _run(_insert_check(db, paper_key="arxiv:mid", timestamp=_ts(now - timedelta(days=2))))

        papers = _run(admin_insights.get_papers(db.db_path, days=0))["papers"]

        assert [p["paper_key"] for p in papers] == ["arxiv:new", "arxiv:mid", "arxiv:old"]

    def test_a_repeat_check_moves_the_paper_to_the_top(self, admin_db):
        _, db = admin_db
        now = datetime.now(timezone.utc)
        _run(_insert_check(db, paper_key="arxiv:a", timestamp=_ts(now - timedelta(days=9))))
        _run(_insert_check(db, paper_key="arxiv:b", timestamp=_ts(now - timedelta(days=3))))
        _run(_insert_check(db, paper_key="arxiv:a", timestamp=_ts(now - timedelta(minutes=5))))

        papers = _run(admin_insights.get_papers(db.db_path, days=0))["papers"]

        assert papers[0]["paper_key"] == "arxiv:a"
        assert papers[0]["checks"] == 2
        assert papers[0]["first_checked_at"] < papers[0]["last_checked_at"]

    def test_window_excludes_older_papers(self, admin_db):
        _, db = admin_db
        now = datetime.now(timezone.utc)
        _run(_insert_check(db, paper_key="arxiv:recent", timestamp=_ts(now - timedelta(days=2))))
        _run(_insert_check(db, paper_key="arxiv:ancient", timestamp=_ts(now - timedelta(days=200))))

        papers = _run(admin_insights.get_papers(db.db_path, days=30))["papers"]

        assert [p["paper_key"] for p in papers] == ["arxiv:recent"]


class TestStatsComeFromTheLatestCheck:
    def test_a_fixed_bibliography_is_not_averaged_with_its_earlier_failure(self, admin_db):
        """Re-running after fixing references should show the improved result."""
        _, db = admin_db
        now = datetime.now(timezone.utc)
        _run(
            _insert_check(
                db,
                paper_key="arxiv:x",
                timestamp=_ts(now - timedelta(days=1)),
                total_refs=10,
                refs_verified=2,
                errors_count=8,
                hallucination_count=4,
            )
        )
        _run(
            _insert_check(
                db,
                paper_key="arxiv:x",
                timestamp=_ts(now),
                total_refs=10,
                refs_verified=10,
                errors_count=0,
                hallucination_count=0,
            )
        )

        paper = _run(admin_insights.get_papers(db.db_path, days=0))["papers"][0]

        assert paper["checks"] == 2
        assert paper["refs_verified"] == 10
        assert paper["errors"] == 0
        assert paper["hallucinations"] == 0
        assert paper["verified_rate"] == 100.0

    def test_latest_check_id_is_the_newest_row(self, admin_db):
        _, db = admin_db
        now = datetime.now(timezone.utc)
        _run(_insert_check(db, paper_key="arxiv:x", timestamp=_ts(now - timedelta(days=1))))
        newest = _run(_insert_check(db, paper_key="arxiv:x", timestamp=_ts(now)))

        paper = _run(admin_insights.get_papers(db.db_path, days=0))["papers"][0]

        assert paper["latest_check_id"] == newest

    def test_identical_timestamps_resolve_to_the_higher_id(self, admin_db):
        """Two checks in the same second must still pick one winner, not vary."""
        _, db = admin_db
        stamp = _ts(datetime.now(timezone.utc))
        _run(_insert_check(db, paper_key="arxiv:x", timestamp=stamp, refs_verified=1))
        newest = _run(_insert_check(db, paper_key="arxiv:x", timestamp=stamp, refs_verified=9))

        paper = _run(admin_insights.get_papers(db.db_path, days=0))["papers"][0]

        assert paper["latest_check_id"] == newest
        assert paper["refs_verified"] == 9

    def test_counts_span_every_check_and_every_user(self, admin_db):
        _, db = admin_db
        alice = _run(_make_user(db, "alice"))
        bob = _run(_make_user(db, "bob"))
        _run(_insert_check(db, paper_key="arxiv:x", user_id=alice))
        _run(_insert_check(db, paper_key="arxiv:x", user_id=bob))
        _run(_insert_check(db, paper_key="arxiv:x", user_id=bob, status="failed"))

        paper = _run(admin_insights.get_papers(db.db_path, days=0))["papers"][0]

        assert paper["checks"] == 3
        assert paper["checked_by"] == 2
        assert paper["failed_checks"] == 1


class TestPaperLinks:
    def test_arxiv_identifier_becomes_an_abs_url(self, admin_db):
        _, db = admin_db
        _run(
            _insert_check(
                db,
                paper_key="arxiv:1706.03762",
                paper_identifier_type="arxiv",
                paper_identifier_value="1706.03762",
                paper_source="1706.03762",
            )
        )
        paper = _run(admin_insights.get_papers(db.db_path, days=0))["papers"][0]
        assert paper["url"] == "https://arxiv.org/abs/1706.03762"

    def test_doi_identifier_becomes_a_resolver_url(self, admin_db):
        _, db = admin_db
        _run(
            _insert_check(
                db,
                paper_key="doi:10.1/abc",
                paper_identifier_type="doi",
                paper_identifier_value="10.1/abc",
                paper_source="10.1/abc",
            )
        )
        paper = _run(admin_insights.get_papers(db.db_path, days=0))["papers"][0]
        assert paper["url"] == "https://doi.org/10.1/abc"

    def test_a_url_source_is_passed_through(self, admin_db):
        _, db = admin_db
        _run(_insert_check(db, paper_key="arxiv:z", paper_source="https://example.org/paper.pdf"))
        paper = _run(admin_insights.get_papers(db.db_path, days=0))["papers"][0]
        assert paper["url"] == "https://example.org/paper.pdf"

    def test_an_upload_has_no_link_rather_than_a_dead_server_path(self, admin_db):
        """/data/uploads/... means nothing to a browser and must not be a link."""
        _, db = admin_db
        _run(
            _insert_check(
                db,
                paper_key="title:unknown-paper",
                paper_title="thesis.pdf",
                source_type="file",
                paper_source="/data/uploads/7/abc_thesis.pdf",
            )
        )
        paper = _run(admin_insights.get_papers(db.db_path, days=0))["papers"][0]
        assert paper["url"] is None

    def test_pasted_text_has_no_link(self, admin_db):
        _, db = admin_db
        _run(
            _insert_check(
                db,
                paper_key="title:pasted-text",
                paper_title="Pasted Text",
                source_type="text",
                paper_source="/tmp/refchecker_texts/pasted_abc.txt",
            )
        )
        paper = _run(admin_insights.get_papers(db.db_path, days=0))["papers"][0]
        assert paper["url"] is None


class TestPapersCarryTheirOwner:
    def test_the_latest_checker_is_named(self, admin_db):
        _, db = admin_db
        alice = _run(_make_user(db, "alice"))
        _run(_insert_check(db, paper_key="arxiv:x", user_id=alice))

        paper = _run(admin_insights.get_papers(db.db_path, days=0))["papers"][0]

        assert paper["user"]["email"] == "alice@example.com"

    def test_an_unattributed_check_has_no_owner_but_still_appears(self, admin_db):
        _, db = admin_db
        _run(_insert_check(db, paper_key="arxiv:x", user_id=None))

        papers = _run(admin_insights.get_papers(db.db_path, days=0))["papers"]

        assert len(papers) == 1
        assert papers[0]["user"] is None

    def test_empty_database_reports_zero_papers_not_an_error(self, admin_db):
        _, db = admin_db
        report = _run(admin_insights.get_papers(db.db_path, days=0))
        assert report["total_papers"] == 0
        assert report["papers"] == []


class TestNeverCheckedVersusIdle:
    """A sign-up who never ran anything is not the same as a lapsed user."""

    def test_lifetime_activity_survives_the_window(self, admin_db):
        _, db = admin_db
        lapsed = _run(_make_user(db, "lapsed"))
        _run(_make_user(db, "ghost"))
        _run(
            _insert_check(
                db,
                user_id=lapsed,
                timestamp=_ts(datetime.now(timezone.utc) - timedelta(days=200)),
                total_refs=42,
            )
        )

        report = _run(admin_insights.get_users(db.db_path, days=30))
        by_email = {u["email"]: u for u in report["users"]}

        lapsed_row = by_email["lapsed@example.com"]
        ghost_row = by_email["ghost@example.com"]
        # Both are zero *in the window* — the point is that they no longer look alike.
        assert lapsed_row["checks"] == ghost_row["checks"] == 0
        assert lapsed_row["lifetime_checks"] == 1
        assert lapsed_row["never_checked"] is False
        assert lapsed_row["lifetime_references_checked"] == 42
        assert lapsed_row["lifetime_last_check_at"] is not None
        assert ghost_row["lifetime_checks"] == 0
        assert ghost_row["never_checked"] is True
        assert ghost_row["lifetime_last_check_at"] is None

    def test_active_only_drops_users_idle_in_the_window(self, admin_db):
        _, db = admin_db
        active = _run(_make_user(db, "active"))
        _run(_make_user(db, "ghost"))
        _run(_insert_check(db, user_id=active))

        report = _run(admin_insights.get_users(db.db_path, days=30, active_only=True))

        assert [u["email"] for u in report["users"]] == ["active@example.com"]
        assert report["active_only"] is True

    def test_counts_describe_the_whole_table_not_the_returned_page(self, admin_db):
        _, db = admin_db
        busy = _run(_make_user(db, "busy"))
        lapsed = _run(_make_user(db, "lapsed"))
        _run(_make_user(db, "ghost1"))
        _run(_make_user(db, "ghost2"))
        _run(_insert_check(db, user_id=busy))
        _run(
            _insert_check(
                db,
                user_id=lapsed,
                timestamp=_ts(datetime.now(timezone.utc) - timedelta(days=200)),
            )
        )

        report = _run(admin_insights.get_users(db.db_path, days=30, limit=1))

        assert len(report["users"]) == 1  # page is clipped...
        assert report["counts"]["total_users"] == 4  # ...but the counts are not
        assert report["counts"]["active_users"] == 1
        assert report["counts"]["never_checked_users"] == 2
        assert report["counts"]["idle_users"] == 1
        assert report["truncated"] is True

    def test_lapsed_users_outrank_never_active_ones_when_the_window_is_empty(self, admin_db):
        """Otherwise a narrow window fills the limit with arbitrary dead accounts."""
        _, db = admin_db
        for i in range(3):
            _run(_make_user(db, f"ghost{i}"))
        lapsed = _run(_make_user(db, "lapsed"))
        _run(
            _insert_check(
                db,
                user_id=lapsed,
                timestamp=_ts(datetime.now(timezone.utc) - timedelta(days=200)),
            )
        )

        report = _run(admin_insights.get_users(db.db_path, days=30, limit=1))

        assert report["users"][0]["email"] == "lapsed@example.com"

    def test_user_paper_counts_use_the_shared_identity(self, admin_db):
        _, db = admin_db
        user = _run(_make_user(db, "alice"))
        for _ in range(3):
            _run(
                _insert_check(
                    db, user_id=user, paper_key="title:pasted-text", paper_title="Pasted Text"
                )
            )

        report = _run(admin_insights.get_users(db.db_path, days=0))

        assert report["users"][0]["distinct_papers"] == 3
