"""Regression tests for the /api/check URL/identifier acceptance gate.

The WebUI "URL / ArXiv ID" field forwards its raw value with
source_type="url". Bare and "arXiv:"-prefixed IDs must be accepted (the
CLI/bulk paths accept them too, and the core resolver handles them), while
genuine non-HTTP(S) URL schemes (file:, ftp:, …) must still be rejected to
preserve SSRF/LFI protection. urlparse("arXiv:2303.18223") reads "arxiv" as a
URL scheme, which previously tripped the SSRF guard and 400'd the check.
"""

import asyncio
import importlib

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.database import Database


def _run(coro):
    return asyncio.run(coro)


class _DummyTask:
    def cancel(self):
        pass


def _make_request(path: str = "/api/check") -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(b"user-agent", b"pytest-agent")],
        "client": ("203.0.113.10", 12345),
        "server": ("testserver", 80),
    })


async def _create_user(api_main, db: Database, provider_id: str):
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
        is_admin=False,
    )


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_check_url_gate")
    monkeypatch.setenv("REFCHECKER_MULTIUSER", "true")
    monkeypatch.setenv("REFCHECKER_USAGE_LOG_PATH", str(tmp_path / "usage-events.jsonl"))
    api_main = importlib.import_module("backend.main")
    api_main = importlib.reload(api_main)
    temp_db = Database(str(tmp_path / "gate.db"))
    _run(temp_db.init_db())
    api_main.active_checks.clear()
    monkeypatch.setattr(api_main, "db", temp_db)

    # Don't actually launch the background check coroutine.
    def _fake_create_task(coro):
        coro.close()
        return _DummyTask()

    monkeypatch.setattr(api_main.asyncio, "create_task", _fake_create_task)

    yield api_main, temp_db
    api_main.active_checks.clear()


def _start(api_main, owner, source_value):
    return _run(api_main.start_check(
        source_type="url",
        source_value=source_value,
        file=None,
        source_text=None,
        llm_config_id=None,
        llm_provider="anthropic",
        llm_model=None,
        use_llm=True,
        api_key=None,
        semantic_scholar_api_key=None,
        current_user=owner,
        http_request=_make_request(),
    ))


@pytest.mark.parametrize("source_value", [
    "arXiv:2303.18223",
    "arxiv:2303.18223",
    "2303.18223",
])
def test_arxiv_identifier_is_accepted(api_env, source_value):
    api_main, db = api_env
    owner = _run(_create_user(api_main, db, f"gate-ok-{source_value}"))

    result = _start(api_main, owner, source_value)

    assert "check_id" in result
    check = _run(db.get_check_by_id(result["check_id"], user_id=owner.id))
    assert check["paper_identifier_type"] == "arxiv"
    assert check["paper_key"] == "arxiv:2303.18223"


def test_http_url_still_accepted(api_env):
    api_main, db = api_env
    owner = _run(_create_user(api_main, db, "gate-http"))

    result = _start(api_main, owner, "https://arxiv.org/abs/2303.18223")
    assert "check_id" in result


@pytest.mark.parametrize("source_value", [
    "file:///etc/passwd",
    "ftp://example.com/paper.pdf",
])
def test_unsupported_scheme_is_rejected(api_env, source_value):
    api_main, db = api_env
    owner = _run(_create_user(api_main, db, f"gate-bad-{source_value[:4]}"))

    with pytest.raises(HTTPException) as exc:
        _start(api_main, owner, source_value)
    assert exc.value.status_code == 400
    assert "HTTP(S)" in str(exc.value.detail)
