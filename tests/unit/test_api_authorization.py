import asyncio
import importlib
import sqlite3

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


def test_single_user_llm_config_update_validates_model_with_stored_key(tmp_path, monkeypatch):
    monkeypatch.delenv("REFCHECKER_MULTIUSER", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_api_authorization")
    api_main = importlib.import_module("backend.main")
    api_main = importlib.reload(api_main)
    temp_db = Database(str(tmp_path / "local.db"))
    _run(temp_db.init_db())
    monkeypatch.setattr(api_main, "db", temp_db)

    config_id = _run(temp_db.create_llm_config(
        name="Anthropic",
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key="stored-key",
        user_id=None,
    ))

    async def reject_invalid_model(**kwargs):
        raise HTTPException(status_code=400, detail="Invalid model name")

    monkeypatch.setattr(api_main, "_validate_llm_connection_or_raise", reject_invalid_model)

    with pytest.raises(HTTPException) as exc:
        _run(api_main.update_llm_config(
            config_id,
            api_main.LLMConfigUpdate(model="claude-does-not-exist"),
            api_main.UserInfo(id=0, name="Local User", provider="local", is_admin=True),
        ))

    assert exc.value.status_code == 400
    stored = _run(temp_db.get_llm_config_by_id(config_id))
    assert stored["model"] == "claude-sonnet-4-6"


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
    """Semantic Scholar keys are managed in browser memory, not stored on server."""
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-ss"))

    status = _run(api_main.get_semantic_scholar_key_status(owner))
    assert status["has_key"] is False
    assert status["storage"] == "browser-only"

    # POST and DELETE now return 410 Gone
    with pytest.raises(HTTPException) as exc_info:
        _run(api_main.set_semantic_scholar_key(
            api_main.SemanticScholarKeyUpdate(api_key="ss-key"),
            owner,
        ))
    assert exc_info.value.status_code == 410

    with pytest.raises(HTTPException) as exc_info:
        _run(api_main.delete_semantic_scholar_key(owner))
    assert exc_info.value.status_code == 410

    status3 = _run(api_main.get_semantic_scholar_key_status(owner))
    assert status3["has_key"] is False


def _create_local_reference_db(path, *, with_snapshot=False):
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
        conn.execute(
            "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "paper-1",
                "Test Paper",
                "testpaper",
                "TestConf",
                2024,
                "10.1000/test",
                None,
                '["Author One"]',
            ),
        )
        conn.execute("CREATE INDEX idx_papers_normalized_title ON papers(normalized_paper_title)")
        if with_snapshot:
            conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                "INSERT INTO metadata VALUES (?, ?)",
                ("last_release_id", "2025-01-15"),
            )


@pytest.fixture
def single_user_settings_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_api_authorization_single_user")
    monkeypatch.delenv("REFCHECKER_MULTIUSER", raising=False)
    for env_name in (
        "REFCHECKER_DATABASE_DIRECTORY",
        "REFCHECKER_DB_PATH",
        "REFCHECKER_OPENALEX_DB_PATH",
        "REFCHECKER_CROSSREF_DB_PATH",
        "REFCHECKER_DBLP_DB_PATH",
        "REFCHECKER_ACL_DB_PATH",
    ):
        monkeypatch.delenv(env_name, raising=False)
    api_main = importlib.import_module("backend.main")
    api_main = importlib.reload(api_main)
    temp_db = Database(str(tmp_path / "single-user.db"))
    _run(temp_db.init_db())
    monkeypatch.setattr(api_main, "db", temp_db)
    yield api_main, temp_db


def test_single_user_db_setting_accepts_database_directory(single_user_settings_db, tmp_path):
    api_main, db = single_user_settings_db
    admin = api_main.UserInfo(
        id=1,
        email="admin@example.com",
        name="admin",
        provider="github",
        is_admin=True,
    )

    db_dir = tmp_path / "local-dbs"
    db_dir.mkdir()
    _create_local_reference_db(db_dir / "semantic_scholar.db", with_snapshot=True)
    _create_local_reference_db(db_dir / "openalex.db")

    result = _run(api_main.update_setting(
        "db_path",
        api_main.SettingUpdate(value=str(db_dir)),
        admin,
    ))

    assert result["value"] == str(db_dir)
    assert "Local database directory configured" in result["message"]
    assert "Semantic Scholar" in result["message"]
    assert "OpenAlex" in result["message"]
    assert result["current_snapshot"] == "2025-01-15"

    configured_paths = _run(api_main._get_configured_database_paths())
    assert configured_paths["s2"] == str(db_dir / "semantic_scholar.db")
    assert configured_paths["openalex"] == str(db_dir / "openalex.db")

    settings = _run(api_main.get_all_settings(admin))
    assert settings["db_path"]["label"] == "Local Database Directory"


def test_multiuser_create_llm_config_does_not_store_api_key(auth_db):
    """Regression: in multi-user mode, API keys must never be persisted server-side."""
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-key-nostore"))

    result = _run(api_main.create_llm_config(
        api_main.LLMConfigCreate(
            name="Anthropic",
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key="sk-secret-key-12345",
        ),
        owner,
    ))
    config_id = result["id"]

    # The response should indicate no key is stored
    assert result["has_key"] is False

    # Verify the database has no key
    stored = _run(db.get_llm_config_by_id(config_id, user_id=owner.id))
    assert stored["api_key"] is None or stored["api_key"] == ""


def test_multiuser_update_llm_config_does_not_store_api_key(auth_db):
    """Regression: updating a config in multi-user mode must not persist the API key."""
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-key-noupdate"))

    result = _run(api_main.create_llm_config(
        api_main.LLMConfigCreate(name="OpenAI", provider="openai", model="gpt-4.1"),
        owner,
    ))
    config_id = result["id"]

    _run(api_main.update_llm_config(
        config_id,
        api_main.LLMConfigUpdate(name="OpenAI Updated", api_key="sk-updated-secret"),
        owner,
    ))

    stored = _run(db.get_llm_config_by_id(config_id, user_id=owner.id))
    assert stored["api_key"] is None or stored["api_key"] == ""
