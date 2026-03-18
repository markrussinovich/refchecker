import asyncio
import importlib.util
import sqlite3
from pathlib import Path

import pytest


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def database_module(tmp_path, monkeypatch):
    monkeypatch.setenv("REFCHECKER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REFCHECKER_SECRET_KEY", "test-secret-key")
    module_path = Path(__file__).resolve().parents[2] / "backend" / "database.py"
    spec = importlib.util.spec_from_file_location(f"test_backend_database_{id(tmp_path)}", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._fernet_instance = None
    return module


def test_llm_config_keys_are_encrypted_at_rest(database_module, tmp_path):
    db_path = tmp_path / "secrets.db"
    db = database_module.Database(str(db_path))
    _run(db.init_db())

    config_id = _run(db.create_llm_config(
        name="Local config",
        provider="anthropic",
        api_key="super-secret-key",
    ))

    with sqlite3.connect(db_path) as conn:
        stored_value = conn.execute(
            "SELECT api_key_encrypted FROM llm_configs WHERE id = ?",
            (config_id,),
        ).fetchone()[0]

    assert stored_value != "super-secret-key"
    assert stored_value.startswith(database_module.SECRET_VALUE_PREFIX)

    config = _run(db.get_llm_config_by_id(config_id))
    assert config["api_key"] == "super-secret-key"


def test_app_settings_are_encrypted_at_rest(database_module, tmp_path):
    db_path = tmp_path / "settings.db"
    db = database_module.Database(str(db_path))
    _run(db.init_db())

    _run(db.set_setting("semantic_scholar_api_key", "ss-secret"))

    with sqlite3.connect(db_path) as conn:
        stored_value = conn.execute(
            "SELECT value_encrypted FROM app_settings WHERE key = ?",
            ("semantic_scholar_api_key",),
        ).fetchone()[0]

    assert stored_value != "ss-secret"
    assert stored_value.startswith(database_module.SECRET_VALUE_PREFIX)
    assert _run(db.get_setting("semantic_scholar_api_key")) == "ss-secret"


def test_init_db_migrates_legacy_plaintext_secrets(database_module, tmp_path):
    db_path = tmp_path / "legacy.db"
    db = database_module.Database(str(db_path))
    _run(db.init_db())

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO llm_configs (name, provider, api_key_encrypted) VALUES (?, ?, ?)",
            ("Legacy config", "anthropic", "legacy-key"),
        )
        conn.execute(
            "INSERT INTO app_settings (key, value_encrypted) VALUES (?, ?)",
            ("semantic_scholar_api_key", "legacy-setting"),
        )
        conn.commit()

    _run(db.init_db())

    with sqlite3.connect(db_path) as conn:
        config_secret = conn.execute(
            "SELECT api_key_encrypted FROM llm_configs WHERE name = ?",
            ("Legacy config",),
        ).fetchone()[0]
        setting_secret = conn.execute(
            "SELECT value_encrypted FROM app_settings WHERE key = ?",
            ("semantic_scholar_api_key",),
        ).fetchone()[0]

    assert config_secret.startswith(database_module.SECRET_VALUE_PREFIX)
    assert setting_secret.startswith(database_module.SECRET_VALUE_PREFIX)

    legacy_config = _run(db.get_llm_config_by_id(1))
    assert legacy_config["api_key"] == "legacy-key"
    assert _run(db.get_setting("semantic_scholar_api_key")) == "legacy-setting"