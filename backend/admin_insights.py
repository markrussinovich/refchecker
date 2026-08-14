"""Admin analytics over the check history.

RefChecker records every run in ``check_history`` (one row per paper checked,
with per-reference detail in ``results_json``) but nothing ever surfaced that
data in aggregate. ``/api/admin/activity`` returns a flat, anonymised dump of
recent rows, which answers "what happened lately" but not "how many people use
this, how much are they checking, and how much of it is hallucinated".

This module holds the read-only queries behind the admin dashboard. It is
deliberately separate from ``backend/main.py`` so the SQL is testable without
standing up the app.

A note on where the numbers come from: aggregate counters
(``total_refs``/``hallucination_count``/...) are persisted as columns on
``check_history`` when a run completes, so fleet-wide totals are plain SQL SUMs
and stay fast as history grows. Per-reference detail is only unpacked for a
single check at a time, where the cost is bounded and the caller wants the
individual references anyway.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)

# check_history stores naive UTC strings in SQLite's default format, so windows
# are compared as strings in that same format rather than as epoch numbers.
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"

# A check row carries no session id — the product has no server-side session
# concept. Runs by one user separated by less than this are treated as a single
# sitting, which is what an operator means by "a session".
DEFAULT_SESSION_GAP_MINUTES = 30

# Guardrails so a malformed query string cannot ask for the whole table.
MAX_USER_ROWS = 500
MAX_SESSION_CHECKS = 2000
MAX_PAPER_ROWS = 500

# ``paper_key`` is not reliably unique per paper. Uploads that never yielded a
# title are all stored as ``title:unknown-paper`` and every pasted body is
# ``title:pasted-text``, so grouping on the column alone merges hundreds of
# unrelated documents into a single "paper". These placeholder keys are the ones
# that must never be treated as an identity.
_PLACEHOLDER_KEYS = ("title:unknown-paper", "title:pasted-text", "title:untitled")
_PLACEHOLDER_TITLES = ("pasted text", "unknown paper", "untitled", "untitled document")


def _sql_list(values: tuple) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


# Identity of a paper, most trustworthy signal first: a real key (arxiv:/doi:/a
# genuine title slug), else the title (which for an untitled upload is the
# filename, and so still groups repeat runs of the same file), else the check
# itself so unrelated rows are never merged. Shared by the overview count and
# the papers list so the two can never disagree about what a paper is.
# Identity of a paper, most trustworthy signal first: a real key (arxiv:/doi:/a
# genuine title slug), else the title (which for an untitled upload is the
# filename, and so still groups repeat runs of the same file), else the check
# itself so unrelated rows are never merged. Shared by the overview count and
# the papers list so the two can never disagree about what a paper is.
def _paper_group_expr(alias: str = "") -> str:
    """SQL for the identity of a paper, optionally qualified by a table alias.

    Most trustworthy signal first: a real key (``arxiv:``/``doi:``/a genuine
    title slug), else the title (which for an untitled upload is the filename,
    and so still groups repeat runs of the same file), else the check row itself
    so unrelated documents are never merged.

    Shared by the overview count and the papers list so the two can never
    disagree about what a paper is.
    """
    p = f"{alias}." if alias else ""
    return f"""
    CASE
        WHEN {p}paper_key IS NOT NULL AND TRIM({p}paper_key) != ''
             AND LOWER(TRIM({p}paper_key)) NOT IN ({_sql_list(_PLACEHOLDER_KEYS)})
            THEN 'k:' || LOWER(TRIM({p}paper_key))
        WHEN {p}paper_title IS NOT NULL AND TRIM({p}paper_title) != ''
             AND LOWER(TRIM({p}paper_title)) NOT IN ({_sql_list(_PLACEHOLDER_TITLES)})
            THEN 't:' || LOWER(TRIM({p}paper_title))
        ELSE 'c:' || {p}id
    END
"""


_PAPER_GROUP_EXPR = _paper_group_expr()


def _paper_link(
    source_type: Optional[str],
    paper_source: Optional[str],
    identifier_type: Optional[str],
    identifier_value: Optional[str],
) -> Optional[str]:
    """Resolve a paper to an openable URL, or None for uploads and pasted text.

    Local paths are deliberately not returned: ``/data/uploads/...`` is a path
    on the server that means nothing to a browser, and emitting it as a link
    would produce one that always fails.
    """
    ident_type = (identifier_type or "").strip().lower()
    ident = (identifier_value or "").strip()
    if ident and ident_type == "arxiv":
        return f"https://arxiv.org/abs/{ident.replace('arXiv:', '').replace('arxiv:', '')}"
    if ident and ident_type == "doi":
        return "https://doi.org/" + ident.replace("https://doi.org/", "").replace("doi:", "")

    src = (paper_source or "").strip()
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if (source_type or "").strip().lower() == "url" and src:
        # A bare arXiv id is a legitimate "url" source in this product.
        return f"https://arxiv.org/abs/{src}" if src[0].isdigit() else None
    return None


def _window_start(days: Optional[int]) -> Optional[str]:
    """Return the inclusive lower bound for a `days`-wide window, or None for all time."""
    if not days or days <= 0:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(_TS_FORMAT)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("T", " ")
    if text.endswith("Z"):
        text = text[:-1]
    # Stored values vary between second and microsecond precision.
    for fmt in (_TS_FORMAT, "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text[: 26 if "." in text else 19], fmt)
        except ValueError:
            continue
    return None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _rate(numerator: int, denominator: int) -> Optional[float]:
    """Percentage, or None when there is nothing to divide by.

    Returning None rather than 0 keeps "no data yet" visually distinct from
    "genuinely zero percent" in the dashboard.
    """
    if not denominator:
        return None
    return round(numerator * 100.0 / denominator, 2)


# Columns summarising a check. Kept in one place so the sessions view, the user
# view and the recent-activity view cannot drift apart.
_CHECK_COLUMNS = """
    id, user_id, paper_title, paper_source, source_type, paper_key,
    original_filename, custom_label, status, failure_class,
    timestamp, started_at, completed_at, duration_ms,
    total_refs, refs_verified, refs_with_errors, refs_with_warnings_only,
    errors_count, warnings_count, suggestions_count, unverified_count,
    hallucination_count, llm_provider, llm_model, extraction_method,
    cache_hit, batch_id, batch_label
"""

# One row per check, reduced to the totals the dashboard adds up.
_TOTALS_SELECT = """
    COUNT(*) AS checks,
    COALESCE(SUM(total_refs), 0) AS references_checked,
    COALESCE(SUM(refs_verified), 0) AS references_verified,
    COALESCE(SUM(errors_count), 0) AS errors,
    COALESCE(SUM(warnings_count), 0) AS warnings,
    COALESCE(SUM(unverified_count), 0) AS unverified,
    COALESCE(SUM(hallucination_count), 0) AS hallucinations,
    COALESCE(SUM(refs_with_errors), 0) AS refs_with_errors,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
    SUM(CASE WHEN hallucination_count > 0 THEN 1 ELSE 0 END) AS papers_with_hallucinations
"""


def _totals_from_row(row: Optional[Any]) -> Dict[str, int]:
    data = dict(row) if row else {}
    return {
        key: _int(data.get(key))
        for key in (
            "checks",
            "references_checked",
            "references_verified",
            "errors",
            "warnings",
            "unverified",
            "hallucinations",
            "refs_with_errors",
            "completed",
            "failed",
            "papers_with_hallucinations",
        )
    }


@asynccontextmanager
async def _connect(db_path: str) -> AsyncIterator[aiosqlite.Connection]:
    """Open a reporting connection and always close it.

    This is a context manager rather than a coroutine returning a connection
    because an ``aiosqlite.Connection`` may only be started once: awaiting it
    and *then* using it as an ``async with`` target starts its worker thread a
    second time, which raises and leaves the thread orphaned.
    """
    conn = await aiosqlite.connect(db_path)
    try:
        # Read-only reporting must never block a check that is trying to write.
        await conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = aiosqlite.Row
        yield conn
    finally:
        await conn.close()


async def get_overview(db_path: str, days: Optional[int] = 30) -> Dict[str, Any]:
    """Fleet-wide totals, a daily activity series, and headline breakdowns."""
    since = _window_start(days)
    where = "WHERE timestamp >= ?" if since else ""
    params: List[Any] = [since] if since else []

    async with _connect(db_path) as conn:
        async with conn.execute(f"SELECT {_TOTALS_SELECT} FROM check_history {where}", params) as cur:
            totals = _totals_from_row(await cur.fetchone())

        async with conn.execute(
            f"""SELECT COUNT(DISTINCT user_id) AS active_users,
                       COUNT(DISTINCT {_PAPER_GROUP_EXPR}) AS distinct_papers
                FROM check_history {where}""",
            params,
        ) as cur:
            row = dict(await cur.fetchone() or {})
            totals["active_users"] = _int(row.get("active_users"))
            totals["distinct_papers"] = _int(row.get("distinct_papers"))

        async with conn.execute("SELECT COUNT(*) AS n FROM users") as cur:
            totals["total_users"] = _int((await cur.fetchone() or {"n": 0})["n"])

        # Median-ish signal without a percentile function: mean duration of the
        # runs that actually finished.
        async with conn.execute(
            f"""SELECT AVG(duration_ms) AS avg_duration_ms
                FROM check_history
                {where + (' AND' if where else 'WHERE')} duration_ms IS NOT NULL AND duration_ms > 0""",
            params,
        ) as cur:
            avg_row = dict(await cur.fetchone() or {})
            avg = avg_row.get("avg_duration_ms")
            totals["avg_duration_ms"] = int(avg) if avg else None

        daily = []
        async with conn.execute(
            f"""SELECT substr(timestamp, 1, 10) AS day,
                       COUNT(*) AS checks,
                       COUNT(DISTINCT user_id) AS users,
                       COALESCE(SUM(total_refs), 0) AS references_checked,
                       COALESCE(SUM(hallucination_count), 0) AS hallucinations
                FROM check_history {where}
                GROUP BY day ORDER BY day""",
            params,
        ) as cur:
            async for row in cur:
                item = dict(row)
                daily.append(
                    {
                        "day": item.get("day"),
                        "checks": _int(item.get("checks")),
                        "users": _int(item.get("users")),
                        "references_checked": _int(item.get("references_checked")),
                        "hallucinations": _int(item.get("hallucinations")),
                    }
                )

        breakdowns: Dict[str, List[Dict[str, Any]]] = {}
        for key, column in (
            ("source_types", "source_type"),
            ("extraction_methods", "extraction_method"),
            ("models", "llm_model"),
            ("failure_classes", "failure_class"),
        ):
            rows = []
            async with conn.execute(
                f"""SELECT {column} AS name, COUNT(*) AS count
                    FROM check_history
                    {where + (' AND' if where else 'WHERE')} {column} IS NOT NULL AND {column} != ''
                    GROUP BY {column} ORDER BY count DESC LIMIT 10""",
                params,
            ) as cur:
                async for row in cur:
                    item = dict(row)
                    rows.append({"name": item.get("name"), "count": _int(item.get("count"))})
            breakdowns[key] = rows

    totals["hallucination_rate"] = _rate(totals["hallucinations"], totals["references_checked"])
    totals["verified_rate"] = _rate(totals["references_verified"], totals["references_checked"])
    totals["avg_references_per_check"] = (
        round(totals["references_checked"] / totals["checks"], 1) if totals["checks"] else None
    )

    return {
        "window_days": days if days and days > 0 else None,
        "since": since,
        "totals": totals,
        "daily": daily,
        "breakdowns": breakdowns,
    }


async def get_users(
    db_path: str,
    days: Optional[int] = None,
    limit: int = 100,
    active_only: bool = False,
) -> Dict[str, Any]:
    """Per-user rollup, busiest first.

    LEFT JOIN from ``users`` so someone who signed in but never ran a check can
    still be counted — that distinction matters when judging adoption — but the
    two reasons a row shows zero are very different and must not look alike:
    a user who has never run anything, versus one who was busy last quarter and
    simply falls outside the current window. Every row therefore also carries
    lifetime totals, and ``active_only`` drops the users with no activity in the
    window so the list is not swamped by sign-ups who never returned.

    Ordering falls back to lifetime activity so that when the window is narrow
    the ``limit`` keeps the people who actually use the product, rather than an
    arbitrary slice of never-active accounts that all tie at zero.

    Checks whose ``user_id`` is NULL (rows predating the column, or single-user
    mode) are reported separately rather than silently dropped.
    """
    since = _window_start(days)
    limit = max(1, min(_int(limit) or 100, MAX_USER_ROWS))
    check_filter = "AND c.timestamp >= ?" if since else ""
    params: List[Any] = [since] if since else []
    having = "HAVING checks > 0" if active_only else ""

    async with _connect(db_path) as conn:
        users = []
        async with conn.execute(
            f"""SELECT u.id, u.provider, u.email, u.name, u.avatar_url,
                       u.is_admin, u.created_at,
                       COUNT(c.id) AS checks,
                       COUNT(DISTINCT {_paper_group_expr('c')}) AS distinct_papers,
                       COALESCE(SUM(c.total_refs), 0) AS references_checked,
                       COALESCE(SUM(c.refs_verified), 0) AS references_verified,
                       COALESCE(SUM(c.errors_count), 0) AS errors,
                       COALESCE(SUM(c.warnings_count), 0) AS warnings,
                       COALESCE(SUM(c.unverified_count), 0) AS unverified,
                       COALESCE(SUM(c.hallucination_count), 0) AS hallucinations,
                       MIN(c.timestamp) AS first_check_at,
                       MAX(c.timestamp) AS last_check_at,
                       (SELECT COUNT(*) FROM check_history h WHERE h.user_id = u.id)
                           AS lifetime_checks,
                       (SELECT COALESCE(SUM(h.total_refs), 0) FROM check_history h
                             WHERE h.user_id = u.id) AS lifetime_references_checked,
                       (SELECT MAX(h.timestamp) FROM check_history h WHERE h.user_id = u.id)
                           AS lifetime_last_check_at
                FROM users u
                LEFT JOIN check_history c
                       ON c.user_id = u.id {check_filter}
                GROUP BY u.id
                {having}
                ORDER BY checks DESC, lifetime_checks DESC, u.id ASC
                LIMIT ?""",
            (*params, limit),
        ) as cur:
            async for row in cur:
                item = dict(row)
                email = item.get("email")
                # An empty window is not the same as never having run anything.
                lifetime_checks = _int(item.get("lifetime_checks"))
                users.append(
                    {
                        "id": item.get("id"),
                        "provider": item.get("provider"),
                        "email": email,
                        "email_domain": email.split("@", 1)[1] if email and "@" in email else None,
                        "name": item.get("name"),
                        "avatar_url": item.get("avatar_url"),
                        "is_admin": bool(item.get("is_admin")),
                        "created_at": item.get("created_at"),
                        "checks": _int(item.get("checks")),
                        "distinct_papers": _int(item.get("distinct_papers")),
                        "references_checked": _int(item.get("references_checked")),
                        "references_verified": _int(item.get("references_verified")),
                        "errors": _int(item.get("errors")),
                        "warnings": _int(item.get("warnings")),
                        "unverified": _int(item.get("unverified")),
                        "hallucinations": _int(item.get("hallucinations")),
                        "hallucination_rate": _rate(
                            _int(item.get("hallucinations")), _int(item.get("references_checked"))
                        ),
                        "first_check_at": item.get("first_check_at"),
                        "last_check_at": item.get("last_check_at"),
                        "lifetime_checks": lifetime_checks,
                        "lifetime_references_checked": _int(
                            item.get("lifetime_references_checked")
                        ),
                        "lifetime_last_check_at": item.get("lifetime_last_check_at"),
                        "never_checked": lifetime_checks == 0,
                    }
                )

        # Counted over the whole users table, not the truncated page, so the UI
        # can say "12 of 512" honestly even when limit clipped the list.
        async with conn.execute(
            f"""SELECT COUNT(*) AS total_users,
                       SUM(CASE WHEN in_window > 0 THEN 1 ELSE 0 END) AS active_users,
                       SUM(CASE WHEN lifetime = 0 THEN 1 ELSE 0 END) AS never_checked_users
                FROM (
                    SELECT (SELECT COUNT(*) FROM check_history h
                             WHERE h.user_id = u.id
                             {'AND h.timestamp >= ?' if since else ''}) AS in_window,
                           (SELECT COUNT(*) FROM check_history h
                             WHERE h.user_id = u.id) AS lifetime
                      FROM users u
                )""",
            params,
        ) as cur:
            row = dict(await cur.fetchone() or {})
            counts = {
                "total_users": _int(row.get("total_users")),
                "active_users": _int(row.get("active_users")),
                "never_checked_users": _int(row.get("never_checked_users")),
            }
            counts["idle_users"] = max(
                0, counts["total_users"] - counts["active_users"] - counts["never_checked_users"]
            )

        where = "WHERE c.user_id IS NULL" + (" AND c.timestamp >= ?" if since else "")
        async with conn.execute(
            f"""SELECT COUNT(*) AS checks,
                       COALESCE(SUM(c.total_refs), 0) AS references_checked,
                       COALESCE(SUM(c.hallucination_count), 0) AS hallucinations
                FROM check_history c {where}""",
            params,
        ) as cur:
            row = dict(await cur.fetchone() or {})
            unattributed = {
                "checks": _int(row.get("checks")),
                "references_checked": _int(row.get("references_checked")),
                "hallucinations": _int(row.get("hallucinations")),
            }

    return {
        "users": users,
        "unattributed": unattributed,
        "counts": counts,
        "active_only": bool(active_only),
        "truncated": len(users) >= limit,
        "window_days": days or None,
    }


async def get_papers(
    db_path: str,
    days: Optional[int] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Every paper that has been checked, most recently checked first.

    One row per *paper*, not per check, so a document run five times appears
    once with ``checks: 5``. Identity comes from :func:`_paper_group_expr`; see
    there for why ``paper_key`` alone is not enough.

    The headline stats are taken from the paper's most recent check rather than
    summed across all of them: re-running a paper after fixing its bibliography
    should show the improved result, not the sum of every attempt. Cross-check
    totals are still exposed as ``checks`` and ``checked_by`` for context.
    """
    since = _window_start(days)
    limit = max(1, min(_int(limit) or 100, MAX_PAPER_ROWS))
    where = "WHERE timestamp >= ?" if since else ""
    params: List[Any] = [since] if since else []
    group = _paper_group_expr()

    async with _connect(db_path) as conn:
        async with conn.execute(
            f"""SELECT COUNT(*) AS papers FROM (
                    SELECT 1 FROM check_history {where} GROUP BY {group}
                )""",
            params,
        ) as cur:
            total_papers = _int((await cur.fetchone() or {"papers": 0})["papers"])

        papers: List[Dict[str, Any]] = []
        # The per-paper stats must come from one specific row — the most recent
        # check. Grouping with bare columns would *appear* to do this, but
        # SQLite only defines that behaviour when a query has exactly one
        # min/max aggregate, and this one needs both. ROW_NUMBER picks the row
        # explicitly instead, with id as a tiebreak so two checks sharing a
        # timestamp still resolve to a stable winner.
        async with conn.execute(
            f"""WITH scoped AS (
                    SELECT *, {group} AS paper_id,
                           COALESCE(started_at, timestamp) AS sort_at
                      FROM check_history {where}
                ),
                grouped AS (
                    SELECT paper_id,
                           COUNT(*) AS checks,
                           COUNT(DISTINCT user_id) AS checked_by,
                           SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_checks,
                           MIN(sort_at) AS first_checked_at,
                           MAX(sort_at) AS last_checked_at
                      FROM scoped GROUP BY paper_id
                ),
                ranked AS (
                    SELECT paper_id, id,
                           ROW_NUMBER() OVER (
                               PARTITION BY paper_id ORDER BY sort_at DESC, id DESC
                           ) AS rn
                      FROM scoped
                )
                SELECT g.paper_id, g.checks, g.checked_by, g.failed_checks,
                       g.first_checked_at, g.last_checked_at,
                       c.id, c.user_id, c.paper_title, c.paper_source, c.source_type,
                       c.paper_key, c.original_filename, c.custom_label, c.status,
                       c.failure_class, c.duration_ms, c.total_refs, c.refs_verified,
                       c.refs_with_errors, c.refs_with_warnings_only, c.errors_count,
                       c.warnings_count, c.suggestions_count, c.unverified_count,
                       c.hallucination_count, c.llm_provider, c.llm_model,
                       c.extraction_method, c.paper_identifier_type,
                       c.paper_identifier_value
                  FROM grouped g
                  JOIN ranked r ON r.paper_id = g.paper_id AND r.rn = 1
                  JOIN check_history c ON c.id = r.id
                 ORDER BY g.last_checked_at DESC, c.id DESC
                 LIMIT ?""",
            (*params, limit),
        ) as cur:
            async for row in cur:
                item = dict(row)
                total_refs = _int(item.get("total_refs"))
                papers.append(
                    {
                        "paper_id": item.get("paper_id"),
                        "latest_check_id": item.get("id"),
                        "title": item.get("paper_title") or item.get("original_filename"),
                        "custom_label": item.get("custom_label"),
                        "original_filename": item.get("original_filename"),
                        "source_type": item.get("source_type"),
                        "paper_key": item.get("paper_key"),
                        "identifier_type": item.get("paper_identifier_type"),
                        "identifier_value": item.get("paper_identifier_value"),
                        "url": _paper_link(
                            item.get("source_type"),
                            item.get("paper_source"),
                            item.get("paper_identifier_type"),
                            item.get("paper_identifier_value"),
                        ),
                        "user_id": item.get("user_id"),
                        "first_checked_at": item.get("first_checked_at"),
                        "last_checked_at": item.get("last_checked_at"),
                        "checks": _int(item.get("checks")),
                        "checked_by": _int(item.get("checked_by")),
                        "failed_checks": _int(item.get("failed_checks")),
                        "status": item.get("status"),
                        "failure_class": item.get("failure_class"),
                        "duration_ms": item.get("duration_ms"),
                        "llm_model": item.get("llm_model"),
                        "llm_provider": item.get("llm_provider"),
                        "extraction_method": item.get("extraction_method"),
                        "total_refs": total_refs,
                        "refs_verified": _int(item.get("refs_verified")),
                        "refs_with_errors": _int(item.get("refs_with_errors")),
                        "refs_with_warnings_only": _int(item.get("refs_with_warnings_only")),
                        "errors": _int(item.get("errors_count")),
                        "warnings": _int(item.get("warnings_count")),
                        "suggestions": _int(item.get("suggestions_count")),
                        "unverified": _int(item.get("unverified_count")),
                        "hallucinations": _int(item.get("hallucination_count")),
                        "hallucination_rate": _rate(
                            _int(item.get("hallucination_count")), total_refs
                        ),
                        "verified_rate": _rate(_int(item.get("refs_verified")), total_refs),
                    }
                )

        owners = {p["user_id"] for p in papers if p.get("user_id") is not None}
        people: Dict[int, Dict[str, Any]] = {}
        if owners:
            placeholders = ", ".join("?" for _ in owners)
            async with conn.execute(
                f"SELECT id, email, name FROM users WHERE id IN ({placeholders})",
                tuple(owners),
            ) as cur:
                async for row in cur:
                    person = dict(row)
                    people[person["id"]] = {
                        "id": person.get("id"),
                        "name": person.get("name"),
                        "email": person.get("email"),
                    }

    for paper in papers:
        paper["user"] = people.get(paper.get("user_id"))

    return {
        "papers": papers,
        "total_papers": total_papers,
        "truncated": len(papers) >= limit,
        "window_days": days or None,
        "since": since,
    }


def _summarise_session(checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    started = _parse_ts(checks[0].get("started_at") or checks[0].get("timestamp"))
    last = checks[-1]
    ended = _parse_ts(last.get("completed_at") or last.get("timestamp"))
    duration = None
    if started and ended and ended >= started:
        duration = int((ended - started).total_seconds())

    labels = [c.get("batch_label") for c in checks if c.get("batch_label")]
    return {
        "started_at": checks[0].get("started_at") or checks[0].get("timestamp"),
        "ended_at": last.get("completed_at") or last.get("timestamp"),
        "duration_seconds": duration,
        "checks": len(checks),
        "references_checked": sum(_int(c.get("total_refs")) for c in checks),
        "references_verified": sum(_int(c.get("refs_verified")) for c in checks),
        "errors": sum(_int(c.get("errors_count")) for c in checks),
        "warnings": sum(_int(c.get("warnings_count")) for c in checks),
        "unverified": sum(_int(c.get("unverified_count")) for c in checks),
        "hallucinations": sum(_int(c.get("hallucination_count")) for c in checks),
        "batch_labels": sorted(set(labels)),
        "items": checks,
    }


def group_checks_into_sessions(
    checks: List[Dict[str, Any]],
    gap_minutes: int = DEFAULT_SESSION_GAP_MINUTES,
) -> List[Dict[str, Any]]:
    """Split one user's checks (oldest first) into sittings.

    A new session starts when the gap since the previous check exceeds
    ``gap_minutes``, or when the batch id changes — a batch is an explicit,
    user-initiated grouping and should never be split across sessions.
    """
    if not checks:
        return []

    gap = timedelta(minutes=max(1, _int(gap_minutes) or DEFAULT_SESSION_GAP_MINUTES))
    sessions: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []
    previous_end: Optional[datetime] = None
    previous_batch: Any = None

    for check in checks:
        start = _parse_ts(check.get("started_at") or check.get("timestamp"))
        batch = check.get("batch_id")
        same_batch = batch is not None and batch == previous_batch
        too_far = (
            previous_end is not None
            and start is not None
            and (start - previous_end) > gap
        )
        if current and too_far and not same_batch:
            sessions.append(_summarise_session(current))
            current = []

        current.append(check)
        end = _parse_ts(check.get("completed_at") or check.get("timestamp")) or start
        # Guard against clock skew making a session appear to run backwards.
        if end and (previous_end is None or end > previous_end or not current[:-1]):
            previous_end = end
        previous_batch = batch

    if current:
        sessions.append(_summarise_session(current))

    sessions.reverse()  # newest sitting first, which is what an admin opens for
    return sessions


async def get_user_sessions(
    db_path: str,
    user_id: int,
    days: Optional[int] = None,
    gap_minutes: int = DEFAULT_SESSION_GAP_MINUTES,
    limit: int = MAX_SESSION_CHECKS,
) -> Dict[str, Any]:
    """One user's checks, grouped into sessions, newest session first."""
    since = _window_start(days)
    params: List[Any] = [user_id]
    where = "WHERE user_id = ?"
    if since:
        where += " AND timestamp >= ?"
        params.append(since)

    async with _connect(db_path) as conn:
        user = None
        async with conn.execute(
            "SELECT id, provider, email, name, avatar_url, is_admin, created_at FROM users WHERE id = ?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                user = dict(row)
                user["is_admin"] = bool(user.get("is_admin"))

        checks: List[Dict[str, Any]] = []
        async with conn.execute(
            f"""SELECT {_CHECK_COLUMNS} FROM check_history {where}
                ORDER BY COALESCE(started_at, timestamp) ASC
                LIMIT ?""",
            (*params, max(1, min(_int(limit) or MAX_SESSION_CHECKS, MAX_SESSION_CHECKS))),
        ) as cur:
            async for row in cur:
                item = dict(row)
                item["cache_hit"] = bool(item.get("cache_hit"))
                checks.append(item)

    return {
        "user": user,
        "user_id": user_id,
        "gap_minutes": gap_minutes,
        "total_checks": len(checks),
        "sessions": group_checks_into_sessions(checks, gap_minutes),
    }


async def get_check_detail(db_path: str, check_id: int) -> Optional[Dict[str, Any]]:
    """A single check with its per-reference results, for admin drill-down.

    Unlike ``/api/history/{id}`` this is not scoped to the caller's own rows —
    that is the entire point of an admin view — so it must stay behind the admin
    gate.
    """
    async with _connect(db_path) as conn:
        async with conn.execute(
            f"""SELECT {_CHECK_COLUMNS}, results_json, issue_type_counts_json,
                       bibliography_source_kind, paper_identifier_type,
                       paper_identifier_value, source_host, input_bytes
                FROM check_history WHERE id = ?""",
            (check_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None

        check = dict(row)
        check["cache_hit"] = bool(check.get("cache_hit"))

        owner = None
        if check.get("user_id") is not None:
            async with conn.execute(
                "SELECT id, provider, email, name, avatar_url, is_admin FROM users WHERE id = ?",
                (check["user_id"],),
            ) as cur:
                user_row = await cur.fetchone()
                if user_row:
                    owner = dict(user_row)
                    owner["is_admin"] = bool(owner.get("is_admin"))

    for field, target in (("results_json", "references"), ("issue_type_counts_json", "issue_type_counts")):
        raw = check.pop(field, None)
        try:
            check[target] = json.loads(raw) if raw else ([] if target == "references" else {})
        except (TypeError, ValueError):
            logger.warning("Check %s has unparseable %s", check_id, field)
            check[target] = [] if target == "references" else {}

    check["user"] = owner
    return check
