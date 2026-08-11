"""Regression: a Semantic Scholar key rejected with HTTP 403 must not be
reported to the user as "Invalid API key".

BUG: a user entered a correct-looking S2 key and the Settings panel said
"invalid key". S2 fronts its API with AWS API Gateway, which answers 403
ForbiddenException for a key that is well-formed but not currently active on a
usage plan (revoked, regenerated, or still activating). The endpoint collapsed
401 and 403 into the same "Invalid API key" message, sending users off hunting
for a typo that wasn't there. 401 still means a bad key; 403 must explain that
the key is inactive and point at the S2 account page.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from backend import main as backend_main
from backend.auth import UserInfo, require_user


def _client_returning(status_code, monkeypatch):
    """TestClient whose outbound S2 call always answers with status_code."""
    app = backend_main.app
    app.dependency_overrides[require_user] = lambda: UserInfo(id=1, provider="test")

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, params=None):
            assert headers["x-api-key"] == "a-well-formed-looking-key"
            return httpx.Response(status_code, json={})

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return TestClient(app)


def _validate(client):
    return client.post(
        "/api/settings/semantic-scholar/validate",
        json={"api_key": "a-well-formed-looking-key"},
    )


def test_403_does_not_claim_the_key_is_invalid(monkeypatch):
    client = _client_returning(403, monkeypatch)
    try:
        resp = _validate(client)
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        # The whole point of the fix: don't tell the user their key is wrong.
        assert "Invalid API key" not in detail
        assert "403" in detail
        # Must be actionable — point at where to get/check the real key.
        assert "semanticscholar.org" in detail
    finally:
        backend_main.app.dependency_overrides.clear()


def test_401_still_reports_an_invalid_key(monkeypatch):
    client = _client_returning(401, monkeypatch)
    try:
        resp = _validate(client)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid API key"
    finally:
        backend_main.app.dependency_overrides.clear()


def test_200_is_valid(monkeypatch):
    client = _client_returning(200, monkeypatch)
    try:
        resp = _validate(client)
        assert resp.status_code == 200
        assert resp.json()["valid"] is True
    finally:
        backend_main.app.dependency_overrides.clear()
