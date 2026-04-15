import asyncio
import importlib

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.database import Database


def _run(coro):
    return asyncio.run(coro)


class _DummyTask:
    def __init__(self):
        self.cancel_called = False

    def cancel(self):
        self.cancel_called = True


class _StubChecker:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def check_paper(self, paper_source, source_type):
        return {
            "paper_title": "Attention Is All You Need",
            "paper_source": paper_source,
            "extraction_method": "bib",
            "references": [
                {
                    "status": "error",
                    "errors": [{"error_type": "author"}],
                    "warnings": [],
                },
                {
                    "status": "warning",
                    "errors": [],
                    "warnings": [{"error_type": "year"}],
                },
                {
                    "status": "verified",
                    "errors": [],
                    "warnings": [],
                },
            ],
            "summary": {
                "total_refs": 3,
                "processed_refs": 3,
                "errors_count": 1,
                "warnings_count": 1,
                "suggestions_count": 0,
                "unverified_count": 0,
                "hallucination_count": 0,
                "verified_count": 1,
                "refs_with_errors": 1,
                "refs_with_warnings_only": 1,
                "refs_verified": 1,
                "progress_percent": 100.0,
            },
        }


def _make_request(path: str = "/") -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [
            (b"user-agent", b"pytest-agent"),
            (b"x-request-id", b"req-123"),
            (b"x-forwarded-for", b"203.0.113.10"),
        ],
        "client": ("203.0.113.10", 12345),
        "server": ("testserver", 80),
    })


async def _create_user(api_main, db: Database, provider_id: str, is_admin: bool = False):
    user_id = await db.create_or_update_user(
        provider="github",
        provider_id=provider_id,
        email=f"{provider_id}@example.com",
        name=provider_id,
    )
    return api_main.UserInfo(
        id=user_id,
        email=f"{provider_id}@example.com",
        name=provider_id,
        provider="github",
        is_admin=is_admin,
    )


@pytest.fixture
def telemetry_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_usage_logging")
    monkeypatch.setenv("REFCHECKER_MULTIUSER", "true")
    monkeypatch.setenv("REFCHECKER_USAGE_LOG_PATH", str(tmp_path / "usage-events.jsonl"))
    api_main = importlib.import_module("backend.main")
    api_main = importlib.reload(api_main)
    temp_db = Database(str(tmp_path / "telemetry.db"))
    _run(temp_db.init_db())
    api_main.active_checks.clear()
    monkeypatch.setattr(api_main, "db", temp_db)
    yield api_main, temp_db
    api_main.active_checks.clear()


def test_start_check_logs_started_event_and_metadata(telemetry_db, monkeypatch):
    api_main, db = telemetry_db
    owner = _run(_create_user(api_main, db, "usage-start"))

    def _fake_create_task(coro):
        coro.close()
        return _DummyTask()

    monkeypatch.setattr(api_main.asyncio, "create_task", _fake_create_task)

    result = _run(api_main.start_check(
        source_type="url",
        source_value="https://arxiv.org/abs/1706.03762",
        file=None,
        source_text=None,
        llm_config_id=None,
        llm_provider="anthropic",
        llm_model="claude-3-5-sonnet",
        use_llm=True,
        api_key=None,
        semantic_scholar_api_key=None,
        current_user=owner,
        http_request=_make_request("/api/check"),
    ))

    check = _run(db.get_check_by_id(result["check_id"], user_id=owner.id))
    assert check["source_host"] == "arxiv.org"
    assert check["paper_identifier_type"] == "arxiv"
    assert check["paper_key"] == "arxiv:1706.03762"
    assert check["input_bytes"] == len("https://arxiv.org/abs/1706.03762".encode("utf-8"))

    events = _run(api_main.get_usage_events(limit=10, user_id=owner.id))
    started = next(event for event in events if event["event_type"] == "check.started")
    assert started["check_id"] == result["check_id"]
    assert started["source_host"] == "arxiv.org"
    assert started["paper_key"] == "arxiv:1706.03762"
    assert started["payload"]["llm_model"] == "claude-3-5-sonnet"


def test_start_check_rate_limit_logs_usage_event(telemetry_db, monkeypatch):
    api_main, db = telemetry_db
    owner = _run(_create_user(api_main, db, "usage-rate-limit"))

    async def _always_deny(_user_id):
        return False

    monkeypatch.setattr(api_main, "_acquire_user_check_slot", _always_deny)

    with pytest.raises(HTTPException) as exc:
        _run(api_main.start_check(
            source_type="url",
            source_value="https://arxiv.org/abs/1706.03762",
            file=None,
            source_text=None,
            llm_config_id=None,
            llm_provider="anthropic",
            llm_model=None,
            use_llm=True,
            api_key=None,
            semantic_scholar_api_key=None,
            current_user=owner,
            http_request=_make_request("/api/check"),
        ))
    assert exc.value.status_code == 429

    events = _run(api_main.get_usage_events(limit=10, user_id=owner.id))
    denied = next(event for event in events if event["event_type"] == "check.rate_limited")
    assert denied["reason_code"] == "max_concurrent_checks_reached"
    assert denied["source_host"] == "arxiv.org"
    assert denied["status_code"] == 429


def test_run_check_logs_completion_and_issue_histogram(telemetry_db, monkeypatch):
    api_main, db = telemetry_db
    owner = _run(_create_user(api_main, db, "usage-complete"))

    check_id = _run(db.create_pending_check(
        paper_title="Processing...",
        paper_source="https://example.com/paper.pdf",
        source_type="url",
        user_id=owner.id,
        started_at=api_main.utcnow_sqlite(),
        source_host="example.com",
        batch_size=1,
    ))

    async def _noop_send_message(*args, **kwargs):
        return None

    monkeypatch.setattr(api_main, "ProgressRefChecker", _StubChecker)
    monkeypatch.setattr(api_main.manager, "send_message", _noop_send_message)
    monkeypatch.setattr(api_main.manager, "active_connections", {"session-123": []}, raising=False)

    _run(api_main.run_check(
        session_id="session-123",
        check_id=check_id,
        paper_source="https://example.com/paper.pdf",
        source_type="url",
        llm_provider="anthropic",
        llm_model="claude-3-5-sonnet",
        api_key=None,
        endpoint=None,
        use_llm=True,
        cancel_event=asyncio.Event(),
        user_id=owner.id,
    ))

    check = _run(db.get_check_by_id(check_id, user_id=owner.id))
    assert check["status"] == "completed"
    assert check["paper_key"] == "title:attention-is-all-you-need"
    assert check["bibliography_source_kind"] == "bib"
    assert check["cache_hit"] == 0
    assert check["duration_ms"] is not None and check["duration_ms"] >= 0
    assert check["issue_type_counts"]["error:author"] == 1
    assert check["issue_type_counts"]["warning:year"] == 1
    assert check["issue_type_counts"]["status:verified"] == 1

    events = _run(api_main.get_usage_events(limit=10, user_id=owner.id))
    completed = next(event for event in events if event["event_type"] == "check.completed")
    assert completed["paper_key"] == "title:attention-is-all-you-need"
    assert completed["payload"]["total_refs"] == 3
    assert completed["payload"]["errors_count"] == 1
    assert completed["payload"]["issue_type_counts"]["error:author"] == 1


def test_auth_callback_invalid_state_logs_failure_event(telemetry_db):
    api_main, db = telemetry_db

    response = _run(api_main.auth_callback(
        provider="github",
        request=_make_request("/api/auth/callback/github"),
        code="code-123",
        state="invalid-state",
        error=None,
    ))

    assert response.headers["location"].endswith("auth_error=invalid_state")
    events = _run(api_main.get_usage_events(limit=10))
    failed = next(event for event in events if event["event_type"] == "auth.login_failed")
    assert failed["reason_code"] == "invalid_state"
    assert failed["provider"] == "github"


def test_admin_analytics_summary_includes_logged_activity(telemetry_db, monkeypatch):
    api_main, db = telemetry_db
    owner = _run(_create_user(api_main, db, "usage-summary", is_admin=True))

    check_id = _run(db.create_pending_check(
        paper_title="Attention Is All You Need",
        paper_source="https://arxiv.org/abs/1706.03762",
        source_type="url",
        user_id=owner.id,
        started_at=api_main.utcnow_sqlite(),
        source_host="arxiv.org",
        paper_identifier_type="arxiv",
        paper_identifier_value="1706.03762",
        paper_key="arxiv:1706.03762",
        batch_size=1,
    ))
    _run(db.update_check_results(
        check_id=check_id,
        paper_title="Attention Is All You Need",
        total_refs=2,
        errors_count=1,
        warnings_count=0,
        suggestions_count=0,
        unverified_count=0,
        refs_with_errors=1,
        refs_with_warnings_only=0,
        refs_verified=1,
        results=[{"status": "error", "errors": [{"error_type": "author"}], "warnings": []}],
        status="completed",
        extraction_method="bib",
        completed_at=api_main.utcnow_sqlite(),
        duration_ms=25,
        paper_identifier_type="arxiv",
        paper_identifier_value="1706.03762",
        paper_key="arxiv:1706.03762",
        issue_type_counts={"error:author": 1, "status:error": 1},
        bibliography_source_kind="bib",
    ))
    _run(api_main.append_usage_event({
        "event_type": "check.started",
        "occurred_at": api_main.utcnow_sqlite(),
        "user_id": owner.id,
        "check_id": check_id,
        "provider": "github",
        "source_type": "url",
        "source_host": "arxiv.org",
        "paper_title": "Attention Is All You Need",
        "paper_key": "arxiv:1706.03762",
        "payload": {"use_llm": True},
    }))
    _run(api_main.append_usage_event({
        "event_type": "check.completed",
        "occurred_at": api_main.utcnow_sqlite(),
        "user_id": owner.id,
        "check_id": check_id,
        "provider": "github",
        "source_type": "url",
        "source_host": "arxiv.org",
        "paper_title": "Attention Is All You Need",
        "paper_key": "arxiv:1706.03762",
        "payload": {
            "total_refs": 2,
            "errors_count": 1,
            "issue_type_counts": {"error:author": 1},
        },
    }))

    summary = _run(api_main.get_admin_analytics_summary(days=30, current_user=owner))
    assert summary["totals"]["total_checks"] >= 1
    assert any(item["paper_group"] == "arxiv:1706.03762" for item in summary["top_papers"])
    assert any(item["issue_type"] == "error:author" for item in summary["top_issue_types"])