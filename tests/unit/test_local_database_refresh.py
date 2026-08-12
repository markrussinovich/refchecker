"""Local reference database bootstrap/refresh scheduling in the web backend.

These cover the deployment failure mode where the server is configured with a
local Semantic Scholar DB (the Render blueprint sets ``REFCHECKER_DB_PATH``)
but the file does not exist yet: the refresh that would create it used to be
skipped, so every check silently fell back to the slow remote S2 API and the DB
was never built. The CLI never had this gap, so this is also a path-parity
regression guard.
"""

import asyncio
import importlib
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from backend.database import Database


def _run(coro):
    return asyncio.run(coro)


DB_ENV_VARS = (
    "REFCHECKER_DATABASE_DIRECTORY",
    "REFCHECKER_DB_PATH",
    "REFCHECKER_OPENALEX_DB_PATH",
    "REFCHECKER_CROSSREF_DB_PATH",
    "REFCHECKER_DBLP_DB_PATH",
    "REFCHECKER_ACL_DB_PATH",
    "REFCHECKER_DB_AUTO_BOOTSTRAP",
    "REFCHECKER_DB_REFRESH_INTERVAL_HOURS",
    "REFCHECKER_S2_MIN_FREE_GB",
)


def _make_s2_db(path, snapshot="2025-01-15"):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE papers (
                paperId TEXT PRIMARY KEY,
                title TEXT,
                normalized_paper_title TEXT,
                venue TEXT,
                year INTEGER,
                externalIds_DOI TEXT,
                externalIds_ArXiv TEXT,
                authors TEXT
            )
            """
        )
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES (?, ?)", ("last_release_id", snapshot))


@pytest.fixture
def backend_main(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_local_database_refresh")
    monkeypatch.delenv("REFCHECKER_MULTIUSER", raising=False)
    for name in DB_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    api_main = importlib.reload(importlib.import_module("backend.main"))
    temp_db = Database(str(tmp_path / "backend.db"))
    _run(temp_db.init_db())
    monkeypatch.setattr(api_main, "db", temp_db)
    # Never let a test shell out to the multi-hour real refresh.
    launched = []

    async def _fake_refresh(db_name, db_path):
        launched.append((db_name, str(db_path)))

    monkeypatch.setattr(api_main, "_run_database_refresh_subprocess", _fake_refresh)
    api_main._launched_refreshes = launched
    yield api_main


def test_missing_configured_s2_db_is_bootstrapped(backend_main, tmp_path, monkeypatch):
    """Regression: a configured-but-missing S2 DB must schedule its own build."""
    api_main = backend_main
    db_file = tmp_path / "data" / "semantic_scholar.db"
    db_file.parent.mkdir()
    monkeypatch.setenv("REFCHECKER_DB_PATH", str(db_file))
    monkeypatch.setattr(api_main, "S2_BOOTSTRAP_MIN_FREE_GB", 0)

    # Nothing exists yet, so the "active" path set is empty...
    assert _run(api_main._get_configured_database_paths()) == {}

    # ...but the refresh must still be scheduled, or the DB never gets built.
    tasks = _run(_drain(api_main))
    assert ("s2", str(db_file)) in api_main._launched_refreshes
    assert "s2" in tasks


def test_bootstrap_skipped_when_disk_too_small(backend_main, tmp_path, monkeypatch):
    api_main = backend_main
    db_file = tmp_path / "data" / "semantic_scholar.db"
    db_file.parent.mkdir()
    monkeypatch.setenv("REFCHECKER_DB_PATH", str(db_file))
    monkeypatch.setattr(api_main, "S2_BOOTSTRAP_MIN_FREE_GB", 10**9)

    _run(_drain(api_main))
    assert api_main._launched_refreshes == []


def test_bootstrap_can_be_disabled(backend_main, tmp_path, monkeypatch):
    api_main = backend_main
    db_file = tmp_path / "data" / "semantic_scholar.db"
    db_file.parent.mkdir()
    monkeypatch.setenv("REFCHECKER_DB_PATH", str(db_file))
    monkeypatch.setenv("REFCHECKER_DB_AUTO_BOOTSTRAP", "false")
    monkeypatch.setattr(api_main, "S2_BOOTSTRAP_MIN_FREE_GB", 0)

    _run(_drain(api_main))
    assert api_main._launched_refreshes == []


def test_existing_db_is_refreshed_not_rebuilt(backend_main, tmp_path, monkeypatch):
    api_main = backend_main
    db_file = tmp_path / "data" / "semantic_scholar.db"
    db_file.parent.mkdir()
    _make_s2_db(db_file)
    monkeypatch.setenv("REFCHECKER_DB_PATH", str(db_file))

    _run(_drain(api_main))
    assert api_main._launched_refreshes == [("s2", str(db_file))]


async def _drain(api_main):
    tasks = await api_main._schedule_database_refreshes()
    if tasks:
        await asyncio.gather(*tasks.values(), return_exceptions=True)
    return tasks


def test_refresh_interval_defaults_to_daily_and_is_configurable(backend_main, monkeypatch):
    api_main = backend_main
    assert api_main._db_refresh_interval_seconds() == 24 * 3600

    monkeypatch.setenv("REFCHECKER_DB_REFRESH_INTERVAL_HOURS", "6")
    assert api_main._db_refresh_interval_seconds() == 6 * 3600

    # 0 disables the loop entirely (single-run behaviour).
    monkeypatch.setenv("REFCHECKER_DB_REFRESH_INTERVAL_HOURS", "0")
    assert api_main._db_refresh_interval_seconds() is None


def test_refresh_loop_repeats_until_cancelled(backend_main, tmp_path, monkeypatch):
    """The loop must keep refreshing; refreshing only at startup let a
    long-running deployment drift months behind the latest S2 release."""
    api_main = backend_main
    db_file = tmp_path / "data" / "semantic_scholar.db"
    db_file.parent.mkdir()
    _make_s2_db(db_file)
    monkeypatch.setenv("REFCHECKER_DB_PATH", str(db_file))
    monkeypatch.setattr(api_main, "_db_refresh_interval_seconds", lambda: 0.01)

    async def scenario():
        task = asyncio.create_task(api_main._database_refresh_loop())
        for _ in range(200):
            if len(api_main._launched_refreshes) >= 3:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    _run(scenario())
    assert len(api_main._launched_refreshes) >= 3


def test_refresh_loop_stops_when_interval_disabled(backend_main, tmp_path, monkeypatch):
    api_main = backend_main
    db_file = tmp_path / "data" / "semantic_scholar.db"
    db_file.parent.mkdir()
    _make_s2_db(db_file)
    monkeypatch.setenv("REFCHECKER_DB_PATH", str(db_file))
    monkeypatch.setenv("REFCHECKER_DB_REFRESH_INTERVAL_HOURS", "0")

    async def scenario():
        await asyncio.wait_for(api_main._database_refresh_loop(), timeout=5)

    _run(scenario())
    assert api_main._launched_refreshes == [("s2", str(db_file))]


def test_status_endpoint_reports_missing_local_s2(backend_main, tmp_path, monkeypatch):
    api_main = backend_main
    db_file = tmp_path / "data" / "semantic_scholar.db"
    db_file.parent.mkdir()
    monkeypatch.setenv("REFCHECKER_DB_PATH", str(db_file))
    admin = api_main.UserInfo(
        id=1, email="a@example.com", name="a", provider="github", is_admin=True
    )

    status = _run(api_main.get_local_database_status(admin))
    assert status["using_local_s2"] is False
    s2 = next(d for d in status["databases"] if d["database"] == "s2")
    assert s2["exists"] is False
    assert s2["path"] == str(db_file)
    assert status["refresh_interval_hours"] == 24


def test_status_endpoint_reports_present_local_s2(backend_main, tmp_path, monkeypatch):
    api_main = backend_main
    db_file = tmp_path / "data" / "semantic_scholar.db"
    db_file.parent.mkdir()
    _make_s2_db(db_file, snapshot="2026-02-01")
    monkeypatch.setenv("REFCHECKER_DB_PATH", str(db_file))
    admin = api_main.UserInfo(
        id=1, email="a@example.com", name="a", provider="github", is_admin=True
    )

    status = _run(api_main.get_local_database_status(admin))
    assert status["using_local_s2"] is True
    s2 = next(d for d in status["databases"] if d["database"] == "s2")
    assert s2["exists"] is True
    assert s2["snapshot"] == "2026-02-01"
    assert s2["size_bytes"] > 0
    assert s2["modified_at"] is not None


def test_status_endpoint_requires_admin(backend_main):
    api_main = backend_main
    user = api_main.UserInfo(
        id=2, email="u@example.com", name="u", provider="github", is_admin=False
    )
    with pytest.raises(Exception) as exc:
        _run(api_main.get_local_database_status(user))
    assert "403" in str(exc.value) or "Admin" in str(exc.value)


def test_orphan_sweep_deletes_stale_staging_dir(backend_main, tmp_path, monkeypatch):
    """A staging dir stranded by a killed refresh must be reclaimed."""
    api_main = backend_main
    data_dir = tmp_path / "data"
    (data_dir / "tmpabc123").mkdir(parents=True)
    (data_dir / "tmpabc123" / "part.gz").write_bytes(b"x" * 1024)
    monkeypatch.setattr(api_main, "get_data_dir", lambda: data_dir)
    old = time.time() - 7200
    os.utime(data_dir / "tmpabc123", (old, old))

    api_main._sweep_orphaned_refresh_tmpdirs()
    assert not (data_dir / "tmpabc123").exists()


def test_orphan_sweep_spares_fresh_staging_dir(backend_main, tmp_path, monkeypatch):
    """A refresh launched outside this process must not have its dir deleted."""
    api_main = backend_main
    data_dir = tmp_path / "data"
    (data_dir / "tmpfresh").mkdir(parents=True)
    monkeypatch.setattr(api_main, "get_data_dir", lambda: data_dir)

    api_main._sweep_orphaned_refresh_tmpdirs()
    assert (data_dir / "tmpfresh").exists()


def test_orphan_sweep_finishes_condemned_dir_regardless_of_age(
    backend_main, tmp_path, monkeypatch
):
    """A partial rmtree refreshes mtime; the retry must not be age-deferred."""
    api_main = backend_main
    data_dir = tmp_path / "data"
    condemned = data_dir / f"{api_main._ORPHAN_SWEEP_PREFIX}tmpabc123"
    condemned.mkdir(parents=True)
    (condemned / "part.gz").write_bytes(b"x" * 1024)
    monkeypatch.setattr(api_main, "get_data_dir", lambda: data_dir)

    api_main._sweep_orphaned_refresh_tmpdirs()
    assert not condemned.exists()


def test_startup_does_not_block_on_sweep(backend_main, tmp_path, monkeypatch):
    """Startup must not await the sweep: a slow disk would fail health checks."""
    api_main = backend_main
    started = asyncio.Event()

    def _slow_sweep():
        time.sleep(0.5)

    monkeypatch.setattr(api_main, "_sweep_orphaned_refresh_tmpdirs", _slow_sweep)

    async def _scenario():
        task = asyncio.create_task(api_main._sweep_orphaned_refresh_tmpdirs_async())
        started.set()
        await asyncio.sleep(0)
        assert not task.done()
        await task

    _run(_scenario())


def test_status_endpoint_flags_a_stale_snapshot(backend_main, tmp_path, monkeypatch):
    """A database that stopped receiving updates still looks healthy by size and
    mtime, so the snapshot release date is what has to surface the problem."""
    api_main = backend_main
    db_file = tmp_path / "data" / "semantic_scholar.db"
    db_file.parent.mkdir()
    stale = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%d")
    _make_s2_db(db_file, snapshot=stale)
    monkeypatch.setenv("REFCHECKER_DB_PATH", str(db_file))
    admin = api_main.UserInfo(
        id=1, email="a@example.com", name="a", provider="github", is_admin=True
    )

    s2 = next(
        d
        for d in _run(api_main.get_local_database_status(admin))["databases"]
        if d["database"] == "s2"
    )
    assert s2["snapshot_stale"] is True
    assert s2["snapshot_age_days"] > 399


def test_status_endpoint_accepts_a_recent_snapshot(backend_main, tmp_path, monkeypatch):
    api_main = backend_main
    db_file = tmp_path / "data" / "semantic_scholar.db"
    db_file.parent.mkdir()
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    _make_s2_db(db_file, snapshot=recent)
    monkeypatch.setenv("REFCHECKER_DB_PATH", str(db_file))
    admin = api_main.UserInfo(
        id=1, email="a@example.com", name="a", provider="github", is_admin=True
    )

    s2 = next(
        d
        for d in _run(api_main.get_local_database_status(admin))["databases"]
        if d["database"] == "s2"
    )
    assert s2["snapshot_stale"] is False
    assert s2["snapshot_age_days"] < 4


def test_refreshes_do_not_run_concurrently(backend_main, tmp_path, monkeypatch):
    """Each refresh stages multi-GB downloads onto the same disk, so overlapping
    them multiplies the peak free space needed and fills the data disk."""
    api_main = backend_main
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in ("semantic_scholar.db", "dblp.db", "acl_anthology.db"):
        _make_s2_db(data_dir / name)
    monkeypatch.setenv("REFCHECKER_DATABASE_DIRECTORY", str(data_dir))

    live = 0
    max_live = 0

    async def _slow_refresh(db_name, db_path):
        nonlocal live, max_live
        live += 1
        max_live = max(max_live, live)
        await asyncio.sleep(0)
        live -= 1

    monkeypatch.setattr(api_main, "_run_database_refresh_subprocess", _slow_refresh)

    async def _drive():
        tasks = await api_main._schedule_database_refreshes()
        await asyncio.gather(*tasks.values())
        return tasks

    tasks = _run(_drive())
    assert len(tasks) >= 2
    assert max_live == 1


def test_status_endpoint_reports_disk_and_refresh_leftovers(backend_main, tmp_path, monkeypatch):
    """Refreshes stop landing when the disk fills, and a killed refresh leaves a
    staging dir behind -- neither is visible without shell access to the host."""
    api_main = backend_main
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_file = data_dir / "semantic_scholar.db"
    _make_s2_db(db_file)
    (data_dir / "tmpabcd1234").mkdir()
    monkeypatch.setenv("REFCHECKER_DB_PATH", str(db_file))
    admin = api_main.UserInfo(
        id=1, email="a@example.com", name="a", provider="github", is_admin=True
    )

    disk = _run(api_main.get_local_database_status(admin))["disk"]
    assert disk["total_bytes"] > 0
    assert disk["free_bytes"] >= 0
    assert disk["orphaned_staging_dirs"] == ["tmpabcd1234"]
