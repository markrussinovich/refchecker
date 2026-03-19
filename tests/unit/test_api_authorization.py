import asyncio
import importlib

import pytest
from fastapi import HTTPException

from backend.database import Database


class _DummyTask:
    def __init__(self):
        self.cancel_called = False

    def cancel(self):
        self.cancel_called = True


def _run(coro):
    return asyncio.run(coro)


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
def auth_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_api_authorization")
    monkeypatch.setenv("REFCHECKER_MULTIUSER", "true")
    api_main = importlib.import_module("backend.main")
    api_main = importlib.reload(api_main)
    temp_db = Database(str(tmp_path / "authz.db"))
    _run(temp_db.init_db())
    api_main.active_checks.clear()
    monkeypatch.setattr(api_main, "db", temp_db)
    yield api_main, temp_db
    api_main.active_checks.clear()


def test_uploaded_file_access_is_user_scoped(auth_db, tmp_path):
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner"))
    other = _run(_create_user(api_main, db, "other"))

    uploaded_file = tmp_path / "paper.pdf"
    uploaded_file.write_bytes(b"%PDF-1.4 test")

    check_id = _run(db.create_pending_check(
        paper_title="Owner file",
        paper_source=str(uploaded_file),
        source_type="file",
        user_id=owner.id,
    ))

    response = _run(api_main.get_uploaded_file(check_id, owner))
    assert response.path == str(uploaded_file)

    with pytest.raises(HTTPException) as exc:
        _run(api_main.get_uploaded_file(check_id, other))
    assert exc.value.status_code == 404


def test_check_mutations_are_user_scoped(auth_db):
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-check"))
    other = _run(_create_user(api_main, db, "other-check"))

    check_id = _run(db.create_pending_check(
        paper_title="Owner check",
        paper_source="https://arxiv.org/abs/1706.03762",
        source_type="url",
        user_id=owner.id,
    ))

    with pytest.raises(HTTPException) as exc:
        _run(api_main.update_check_label(check_id, api_main.CheckLabelUpdate(custom_label="hijack"), other))
    assert exc.value.status_code == 404

    result = _run(api_main.update_check_label(check_id, api_main.CheckLabelUpdate(custom_label="owner-label"), owner))
    assert result["message"] == "Label updated successfully"

    updated = _run(db.get_check_by_id(check_id, user_id=owner.id))
    assert updated["custom_label"] == "owner-label"

    cancel_event = asyncio.Event()
    task = _DummyTask()
    api_main.active_checks["session-owner"] = {
        "task": task,
        "cancel_event": cancel_event,
        "check_id": check_id,
        "user_id": owner.id,
    }

    with pytest.raises(HTTPException) as exc:
        _run(api_main.cancel_check("session-owner", other))
    assert exc.value.status_code == 404
    assert not task.cancel_called
    assert not cancel_event.is_set()

    result = _run(api_main.cancel_check("session-owner", owner))
    assert result["message"] == "Cancellation requested"
    assert task.cancel_called
    assert cancel_event.is_set()


def test_batch_routes_are_user_scoped(auth_db):
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-batch"))
    other = _run(_create_user(api_main, db, "other-batch"))
    batch_id = "batch-123"

    first_check_id = _run(db.create_pending_check(
        paper_title="Batch one",
        paper_source="https://arxiv.org/abs/1706.03762",
        source_type="url",
        batch_id=batch_id,
        batch_label="Owner batch",
        user_id=owner.id,
    ))
    _run(db.create_pending_check(
        paper_title="Batch two",
        paper_source="https://arxiv.org/abs/1810.04805",
        source_type="url",
        batch_id=batch_id,
        batch_label="Owner batch",
        user_id=owner.id,
    ))

    batch_task = _DummyTask()
    batch_event = asyncio.Event()
    api_main.active_checks["batch-session"] = {
        "task": batch_task,
        "cancel_event": batch_event,
        "check_id": first_check_id,
        "batch_id": batch_id,
        "user_id": owner.id,
    }

    with pytest.raises(HTTPException) as exc:
        _run(api_main.get_batch(batch_id, other))
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        _run(api_main.update_batch_label(batch_id, api_main.BatchLabelUpdate(batch_label="stolen"), other))
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        _run(api_main.cancel_batch(batch_id, other))
    assert exc.value.status_code == 404
    assert not batch_task.cancel_called
    assert not batch_event.is_set()

    result = _run(api_main.update_batch_label(batch_id, api_main.BatchLabelUpdate(batch_label="owner-updated"), owner))
    assert result["message"] == "Batch label updated successfully"

    summary = _run(api_main.get_batch(batch_id, owner))
    assert summary["batch_label"] == "owner-updated"

    result = _run(api_main.cancel_batch(batch_id, owner))
    assert result["message"] == "Batch cancellation requested"
    assert batch_task.cancel_called
    assert batch_event.is_set()


def test_llm_config_mutations_are_user_scoped(auth_db):
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-config"))
    other = _run(_create_user(api_main, db, "other-config"))

    config_id = _run(db.create_llm_config(
        name="Owner config",
        provider="anthropic",
        model="claude-3-5-sonnet",
        api_key=None,
        user_id=owner.id,
    ))

    with pytest.raises(HTTPException) as exc:
        _run(api_main.update_llm_config(config_id, api_main.LLMConfigUpdate(name="hijacked"), other))
    assert exc.value.status_code == 404

    result = _run(api_main.update_llm_config(config_id, api_main.LLMConfigUpdate(name="owner-updated"), owner))
    assert result["id"] == config_id
    assert result["name"] == "owner-updated"

    with pytest.raises(HTTPException) as exc:
        _run(api_main.delete_llm_config(config_id, other))
    assert exc.value.status_code == 404

    delete_result = _run(api_main.delete_llm_config(config_id, owner))
    assert delete_result["message"] == "Config deleted successfully"
    assert _run(db.get_llm_config_by_id(config_id, user_id=owner.id)) is None


def test_multiuser_rejects_vllm_config_creation_and_validation(auth_db):
    api_main, _db = auth_db
    owner = _run(_create_user(api_main, _db, "owner-vllm"))

    with pytest.raises(HTTPException) as exc:
        _run(api_main.create_llm_config(
            api_main.LLMConfigCreate(name="Local vLLM", provider="vllm", endpoint="http://localhost:8000"),
            owner,
        ))
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        _run(api_main.validate_llm_config(
            api_main.LLMConfigValidate(provider="vllm", endpoint="http://localhost:8000"),
            owner,
        ))
    assert exc.value.status_code == 403


def test_private_artifact_routes_disable_shared_caching(auth_db, tmp_path):
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-cache"))

    uploaded_file = tmp_path / "paper.pdf"
    uploaded_file.write_bytes(b"%PDF-1.4 test")
    file_check_id = _run(db.create_pending_check(
        paper_title="Owner file",
        paper_source=str(uploaded_file),
        source_type="file",
        user_id=owner.id,
    ))
    file_response = _run(api_main.get_uploaded_file(file_check_id, owner))
    assert file_response.headers["cache-control"] == "private, no-store, max-age=0"
    assert file_response.headers["vary"] == "Cookie"

    text_file = tmp_path / "pasted.txt"
    text_file.write_text("reference text", encoding="utf-8")
    text_check_id = _run(db.create_pending_check(
        paper_title="Pasted Text",
        paper_source=str(text_file),
        source_type="text",
        user_id=owner.id,
    ))
    text_response = _run(api_main.get_pasted_text(text_check_id, owner))
    assert text_response.headers["cache-control"] == "private, no-store, max-age=0"
    assert text_response.headers["vary"] == "Cookie"


def test_settings_updates_require_admin(auth_db):
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-settings"))
    admin = api_main.UserInfo(
        id=owner.id,
        email=owner.email,
        name=owner.name,
        provider=owner.provider,
        is_admin=True,
    )

    with pytest.raises(HTTPException) as exc:
        _run(api_main.update_setting(
            "max_concurrent_checks",
            api_main.SettingUpdate(value="7"),
            owner,
        ))
    assert exc.value.status_code == 403

    result = _run(api_main.update_setting(
        "max_concurrent_checks",
        api_main.SettingUpdate(value="7"),
        admin,
    ))
    assert result["value"] == "7"


def test_semantic_scholar_keys_are_browser_only(auth_db):
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-ss"))

    status = _run(api_main.get_semantic_scholar_key_status(owner))
    assert status["has_key"] is False
    assert status["storage"] == "browser-only"

    with pytest.raises(HTTPException) as exc:
        _run(api_main.set_semantic_scholar_key(
            api_main.SemanticScholarKeyUpdate(api_key="ss-key"),
            owner,
        ))
    assert exc.value.status_code == 410

    with pytest.raises(HTTPException) as exc:
        _run(api_main.delete_semantic_scholar_key(owner))
    assert exc.value.status_code == 410
