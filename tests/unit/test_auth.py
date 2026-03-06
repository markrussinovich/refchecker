"""
Unit tests for the authentication module (backend/auth.py).
These tests verify JWT token handling, OAuth state management,
and in-memory API key storage.
"""
import os
import sys
import time
import importlib
import importlib.util
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# ---------------------------------------------------------------------------
# Import auth module directly (bypass backend/__init__.py which pulls in
# the full FastAPI app and its many transitive deps)
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).parent.parent.parent / "backend"


def _import_auth_direct(env_overrides=None):
    """
    Import backend/auth.py in isolation, with optional env var overrides.
    We inject a stub `backend.database` into sys.modules so the circular
    import path `auth → database` doesn't cascade into FastAPI/refchecker.
    """
    env_overrides = env_overrides or {}
    original_env = {}
    for k, v in env_overrides.items():
        original_env[k] = os.environ.get(k)
        if v == "":
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    # Stub out backend.database so auth.py's `from .database import db` works
    stub_db = MagicMock()
    sys.modules.setdefault("backend", MagicMock(__path__=[str(_BACKEND_DIR)]))
    sys.modules["backend.database"] = MagicMock(db=stub_db)

    # Remove any previously cached version so env changes take effect
    sys.modules.pop("backend.auth", None)

    spec = importlib.util.spec_from_file_location(
        "backend.auth",
        _BACKEND_DIR / "auth.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["backend.auth"] = module
    spec.loader.exec_module(module)

    # Restore env
    for k, orig in original_env.items():
        if orig is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = orig

    return module


# ---------------------------------------------------------------------------
# JWT tests
# ---------------------------------------------------------------------------

class TestJWTTokens:
    """Tests for JWT creation and decoding."""

    def test_create_and_decode_token(self):
        auth = _import_auth_direct({"JWT_SECRET_KEY": "test-secret-key-abc123"})
        token = auth.create_access_token(42, "user@example.com", "Test User")
        assert isinstance(token, str)
        assert len(token) > 20

        data = auth.decode_access_token(token)
        assert data is not None
        assert data.user_id == 42
        assert data.email == "user@example.com"
        assert data.name == "Test User"

    def test_decode_invalid_token_returns_none(self):
        auth = _import_auth_direct({"JWT_SECRET_KEY": "test-secret-key-abc123"})
        result = auth.decode_access_token("not.a.valid.token")
        assert result is None

    def test_decode_expired_token_returns_none(self):
        import jwt as pyjwt
        auth = _import_auth_direct({"JWT_SECRET_KEY": "test-secret-key-abc123"})
        payload = {
            "sub": "1",
            "email": "x@x.com",
            "name": "X",
            "iat": int(time.time()) - 3600,
            "exp": int(time.time()) - 1,  # expired 1 second ago
        }
        expired_token = pyjwt.encode(payload, "test-secret-key-abc123", algorithm="HS256")
        result = auth.decode_access_token(expired_token)
        assert result is None

    def test_token_uses_correct_expiry(self):
        import jwt as pyjwt
        auth = _import_auth_direct({"JWT_SECRET_KEY": "test-secret-key-abc123", "JWT_EXPIRE_SECONDS": "3600"})
        before = int(time.time())
        token = auth.create_access_token(1, "a@b.com", "A")
        payload = pyjwt.decode(token, "test-secret-key-abc123", algorithms=["HS256"])
        after = int(time.time())
        assert before + 3600 <= payload["exp"] <= after + 3600 + 5


# ---------------------------------------------------------------------------
# OAuth state tests
# ---------------------------------------------------------------------------

class TestOAuthState:
    """Tests for CSRF state token generation and validation."""

    def test_generate_and_validate_state(self):
        auth = _import_auth_direct()
        state = auth._generate_oauth_state("google")
        assert isinstance(state, str)
        assert len(state) > 20
        assert auth._validate_oauth_state(state, "google") is True

    def test_state_cannot_be_reused(self):
        auth = _import_auth_direct()
        state = auth._generate_oauth_state("github")
        assert auth._validate_oauth_state(state, "github") is True
        # Second call should fail (consumed)
        assert auth._validate_oauth_state(state, "github") is False

    def test_wrong_provider_fails(self):
        auth = _import_auth_direct()
        state = auth._generate_oauth_state("google")
        assert auth._validate_oauth_state(state, "github") is False

    def test_nonexistent_state_fails(self):
        auth = _import_auth_direct()
        assert auth._validate_oauth_state("nonexistent-state", "google") is False


# ---------------------------------------------------------------------------
# In-memory API key storage tests
# ---------------------------------------------------------------------------

class TestInMemoryApiKeys:
    """Tests for in-memory (never persisted) API key storage."""

    def setup_method(self):
        """Clear in-memory key store before each test."""
        self.auth = _import_auth_direct()
        self.auth._user_api_keys.clear()

    def test_store_and_retrieve_api_key(self):
        self.auth.store_user_api_key(99, "anthropic", "sk-ant-123")
        key = self.auth.get_user_api_key(99, "anthropic")
        assert key == "sk-ant-123"

    def test_delete_api_key(self):
        self.auth.store_user_api_key(99, "openai", "sk-openai-456")
        self.auth.delete_user_api_key(99, "openai")
        assert self.auth.get_user_api_key(99, "openai") is None

    def test_has_api_key(self):
        assert not self.auth.has_user_api_key(99, "google")
        self.auth.store_user_api_key(99, "google", "key-value")
        assert self.auth.has_user_api_key(99, "google")

    def test_api_keys_are_isolated_per_user(self):
        self.auth.store_user_api_key(1, "anthropic", "user1-key")
        self.auth.store_user_api_key(2, "anthropic", "user2-key")
        assert self.auth.get_user_api_key(1, "anthropic") == "user1-key"
        assert self.auth.get_user_api_key(2, "anthropic") == "user2-key"

    def test_get_user_api_key_providers(self):
        self.auth.store_user_api_key(7, "anthropic", "k1")
        self.auth.store_user_api_key(7, "openai", "k2")
        providers = self.auth.get_user_api_key_providers(7)
        assert set(providers) == {"anthropic", "openai"}

    def test_get_missing_user_returns_none(self):
        assert self.auth.get_user_api_key(9999, "anthropic") is None


# ---------------------------------------------------------------------------
# Auth config / providers
# ---------------------------------------------------------------------------

class TestAvailableProviders:
    """Tests for provider availability detection."""

    def test_no_providers_when_unconfigured(self):
        auth = _import_auth_direct({
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
            "GITHUB_CLIENT_ID": "",
            "GITHUB_CLIENT_SECRET": "",
        })
        assert auth.get_available_providers() == []

    def test_google_provider_when_configured(self):
        auth = _import_auth_direct({
            "GOOGLE_CLIENT_ID": "google-client-id",
            "GOOGLE_CLIENT_SECRET": "google-client-secret",
            "GITHUB_CLIENT_ID": "",
            "GITHUB_CLIENT_SECRET": "",
        })
        providers = auth.get_available_providers()
        assert "google" in providers
        assert "github" not in providers

    def test_both_providers_when_configured(self):
        auth = _import_auth_direct({
            "GOOGLE_CLIENT_ID": "gid",
            "GOOGLE_CLIENT_SECRET": "gsec",
            "GITHUB_CLIENT_ID": "ghid",
            "GITHUB_CLIENT_SECRET": "ghsec",
        })
        providers = auth.get_available_providers()
        assert "google" in providers
        assert "github" in providers

    def test_auth_disabled_by_default(self):
        # Remove the variable so it's not set at all
        auth = _import_auth_direct({"AUTH_ENABLED": ""})
        assert auth.AUTH_ENABLED is False

    def test_auth_enabled_via_env_var(self):
        auth = _import_auth_direct({"AUTH_ENABLED": "true"})
        assert auth.AUTH_ENABLED is True
