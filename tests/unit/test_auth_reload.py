#!/usr/bin/env python3
"""Hot-reload of the auth config (R27).

``auth.reload_config()`` re-reads credentials + the multi-user flag into the
module globals so enabling accounts/providers from inside the app takes effect
without a backend restart. These tests assert that after a reload:

  - ``is_multiuser_mode()`` flips on/off with the env value,
  - ``get_available_providers()`` reflects newly-supplied client id/secret pairs,
  - single-user mode (no override / multiuser=false) yields no providers.

Pure-stdlib (no aiosqlite) so it runs in the local sandbox too. Each test
snapshots and restores the relevant env keys so it can't leak into siblings.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


_AUTH_ENV_KEYS = (
    "REFCHECKER_MULTIUSER",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET",
    "MS_CLIENT_ID", "MS_CLIENT_SECRET",
)


def _snapshot_env():
    return {k: os.environ.get(k) for k in _AUTH_ENV_KEYS}


def _restore_env(snapshot):
    for k, v in snapshot.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _fresh_auth_single_user():
    """Import the real ``backend.auth`` with a clean single-user environment.

    Other tests (test_auth.py) load auth.py in isolation by stubbing
    ``sys.modules['backend']`` / ``backend.database`` and replacing
    ``backend.auth`` with a bare standalone module. Drop any such polluted
    entries (and an auth module missing our new ``reload_config``) so we
    re-import the genuine package module, then reload it under a cleared env."""
    for k in _AUTH_ENV_KEYS:
        os.environ.pop(k, None)
    import types
    backend_mod = sys.modules.get("backend")
    if backend_mod is not None and not isinstance(backend_mod, types.ModuleType):
        # MagicMock stub left by test_auth.py — drop the whole subtree.
        for name in list(sys.modules):
            if name == "backend" or name.startswith("backend."):
                sys.modules.pop(name, None)
    else:
        auth_mod = sys.modules.get("backend.auth")
        if auth_mod is not None and not hasattr(auth_mod, "reload_config"):
            sys.modules.pop("backend.auth", None)
    auth = importlib.import_module("backend.auth")
    # Reload to re-run the import-time credential block under the cleared env.
    return importlib.reload(auth)


def test_reload_enables_multiuser_and_providers():
    snapshot = _snapshot_env()
    try:
        auth = _fresh_auth_single_user()

        # Baseline: single-user, no providers.
        assert auth.is_multiuser_mode() is False
        assert auth.get_available_providers() == []

        # Simulate Settings -> Enable accounts: write the env overrides and
        # hot-reload (exactly what set_auth_config does).
        auth.reload_config({
            "REFCHECKER_MULTIUSER": "true",
            "GITHUB_CLIENT_ID": "gh-id",
            "GITHUB_CLIENT_SECRET": "gh-secret",
        })

        assert auth.is_multiuser_mode() is True
        assert auth.MULTIUSER_MODE is True
        assert auth.get_available_providers() == ["github"]
    finally:
        _restore_env(snapshot)
        try:
            importlib.reload(importlib.import_module("backend.auth"))
        except Exception:
            pass


def test_reload_multiple_providers_and_partial_pairs_excluded():
    snapshot = _snapshot_env()
    try:
        auth = _fresh_auth_single_user()

        # Google has both halves; Microsoft only an id -> excluded; multiuser on.
        auth.reload_config({
            "REFCHECKER_MULTIUSER": "true",
            "GOOGLE_CLIENT_ID": "g-id",
            "GOOGLE_CLIENT_SECRET": "g-secret",
            "MS_CLIENT_ID": "ms-id-only",
        })

        providers = auth.get_available_providers()
        assert "google" in providers
        assert "microsoft" not in providers  # secret missing -> not advertised
    finally:
        _restore_env(snapshot)
        try:
            importlib.reload(importlib.import_module("backend.auth"))
        except Exception:
            pass


def test_reload_can_disable_multiuser():
    snapshot = _snapshot_env()
    try:
        auth = _fresh_auth_single_user()
        auth.reload_config({
            "REFCHECKER_MULTIUSER": "true",
            "GITHUB_CLIENT_ID": "gh-id",
            "GITHUB_CLIENT_SECRET": "gh-secret",
        })
        assert auth.is_multiuser_mode() is True

        # Turn it back off; providers must go away even though creds remain.
        auth.reload_config({"REFCHECKER_MULTIUSER": "false"})
        assert auth.is_multiuser_mode() is False
        assert auth.get_available_providers() == []
    finally:
        _restore_env(snapshot)
        try:
            importlib.reload(importlib.import_module("backend.auth"))
        except Exception:
            pass


if __name__ == "__main__":
    test_reload_enables_multiuser_and_providers()
    test_reload_multiple_providers_and_partial_pairs_excluded()
    test_reload_can_disable_multiuser()
    print("ok")
