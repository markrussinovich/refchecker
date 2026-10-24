"""Identity-only ChatGPT authentication, tested with real signed ID tokens."""
import ast
import asyncio
import base64
import hashlib
import importlib.util
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from jose.backends.cryptography_backend import CryptographyRSAKey
from starlette.requests import Request
from starlette.responses import RedirectResponse

from refchecker.llm import chatgpt_auth

ROOT = Path(__file__).resolve().parents[2]


def request(query=None, cookie=None):
    headers = [(b"host", b"testserver")]
    if cookie:
        headers.append((b"cookie", f"rc_chatgpt_state={cookie}".encode()))
    return Request({
        "type": "http", "method": "GET", "scheme": "https",
        "path": "/api/auth/callback/chatgpt",
        "query_string": urlencode(query or {}).encode(),
        "headers": headers, "server": ("testserver", 443),
    })


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setenv("REFCHECKER_MULTIUSER", "true")
    monkeypatch.setenv("CHATGPT_CLIENT_ID", "registered-client")
    monkeypatch.delenv("CHATGPT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("CHATGPT_REDIRECT_URI", raising=False)
    spec = importlib.util.spec_from_file_location("identity_auth_test", ROOT / "backend" / "auth.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def flow(auth, monkeypatch):
    params = parse_qs(urlparse(auth.get_chatgpt_auth_url(request())).query)
    state = params["state"][0]
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = CryptographyRSAKey(private.public_key(), "RS256").to_dict()
    jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
    claims = {
        "iss": "https://auth.openai.com", "aud": "registered-client",
        "sub": "stable-subject", "exp": int(time.time()) + 300,
        "nonce": params["nonce"][0], "email": "person@example.com",
        "email_verified": True, "name": "Person",
    }
    recorded = []
    payload = {}

    def token_handler(req):
        recorded.append(parse_qs(req.content.decode()))
        return httpx.Response(200, json=payload)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(token_handler), **kw,
    ))

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, url, timeout):
            if url == chatgpt_auth.OIDC_CONFIGURATION_URL:
                return httpx.Response(200, request=httpx.Request("GET", url), json={
                    "issuer": "https://auth.openai.com", "jwks_uri": "https://auth.openai.com/keys",
                })
            return httpx.Response(200, request=httpx.Request("GET", url), json={"keys": [jwk]})

    monkeypatch.setattr(chatgpt_auth.requests, "Session", Session)

    def sign(changes=None):
        actual = {**claims, **(changes or {})}
        payload["id_token"] = jwt.encode(actual, private, algorithm="RS256", headers={"kid": "test-key"})
        payload["access_token"] = "access"

    sign()
    return state, params, recorded, sign, payload


def test_identity_scope_and_pkce(auth, flow):
    state, params, _, _, _ = flow
    assert params["scope"] == ["openid profile email"]
    assert "resource" not in params
    assert params["client_id"] == ["registered-client"]
    verifier = auth._oauth_states[state]["code_verifier"]
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == [expected]
    assert params["code_challenge_method"] == ["S256"]


def test_signed_identity_and_one_time_state(auth, flow, tmp_path, monkeypatch):
    state, _, recorded, _, _ = flow
    store = tmp_path / "plan-credentials.json"
    monkeypatch.setenv("REFCHECKER_CHATGPT_AUTH_FILE", str(store))
    req = request({"state": state}, state)
    result = asyncio.run(auth.exchange_chatgpt_code("code", req))
    assert result == {
        "provider": "chatgpt", "provider_id": "stable-subject",
        "email": "person@example.com", "name": "Person", "avatar_url": None,
    }
    assert "resource" not in recorded[0]
    assert recorded[0]["code_verifier"]
    assert not store.exists()
    assert asyncio.run(auth.exchange_chatgpt_code("code", req)) is None
    assert len(recorded) == 1


@pytest.mark.parametrize("changes", [
    {"iss": "https://wrong.example"}, {"aud": "other-client"}, {"exp": 1},
    {"nonce": "wrong"}, {"sub": ""}, {"exp": None}, {"email_verified": False},
])
def test_invalid_identity_is_rejected(auth, flow, changes):
    state, _, _, sign, _ = flow
    sign(changes)
    assert asyncio.run(auth.exchange_chatgpt_code("code", request({"state": state}, state))) is None


@pytest.mark.parametrize("cookie", [None, "wrong-state"])
def test_callback_requires_initiating_browser(auth, flow, cookie):
    state, _, recorded, _, _ = flow
    assert asyncio.run(auth.exchange_chatgpt_code("code", request({"state": state}, cookie))) is None
    assert recorded == []


def test_expired_state_does_not_exchange(auth, flow):
    state, _, recorded, _, _ = flow
    auth._oauth_states[state]["created_at"] = time.time() - 601
    assert asyncio.run(auth.exchange_chatgpt_code("code", request({"state": state}, state))) is None
    assert not recorded


def test_provider_registration_hot_reload(auth):
    assert "chatgpt" in auth.get_available_providers()
    auth.reload_config({"CHATGPT_CLIENT_ID": "", "REFCHECKER_MULTIUSER": "true"})
    assert "chatgpt" not in auth.get_available_providers()
    auth.reload_config({"CHATGPT_CLIENT_ID": "registered-client"})
    assert "chatgpt" in auth.get_available_providers()


def test_login_route_sets_browser_state_cookie(auth):
    tree = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "auth_login")
    node.decorator_list = []
    ns = {
        "Request": Request, "_EXCHANGE_FNS": {"chatgpt": (auth.get_chatgpt_auth_url, None)},
        "_log_usage_event_safe": AsyncMock(), "is_multiuser_mode": lambda: True,
        "RedirectResponse": RedirectResponse, "CHATGPT_STATE_COOKIE": auth.CHATGPT_STATE_COOKIE,
        "COOKIE_SECURE": True,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "auth_login", "exec"), ns)
    response = asyncio.run(ns["auth_login"]("chatgpt", request()))
    cookie = response.headers["set-cookie"]
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    assert state in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie


@pytest.mark.parametrize("succeeded", [True, False])
def test_callback_creates_only_local_session_and_clears_state_cookie(auth, succeeded):
    from types import SimpleNamespace
    tree = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "auth_callback")
    node.decorator_list = []
    account = {
        "provider": "chatgpt", "provider_id": "subject",
        "email": "person@example.com", "name": "Person", "avatar_url": None,
    }
    database = SimpleNamespace(
        create_or_update_user=AsyncMock(return_value=7),
        get_user_by_id=AsyncMock(return_value={"is_admin": False}),
    )
    ns = {
        "Request": Request, "Optional": __import__("typing").Optional,
        "SITE_URL": "/", "RedirectResponse": RedirectResponse,
        "CHATGPT_STATE_COOKIE": auth.CHATGPT_STATE_COOKIE,
        "_EXCHANGE_FNS": {"chatgpt": (None, AsyncMock(return_value=account if succeeded else None))},
        "_log_usage_event_safe": AsyncMock(), "db": database,
        "extract_email_domain": lambda email: "example.com",
        "create_access_token": lambda *_args: "local-session",
        "set_auth_cookie": auth.set_auth_cookie,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "auth_callback", "exec"), ns)
    response = asyncio.run(ns["auth_callback"]("chatgpt", request(), code="code", state="state"))
    assert any('rc_chatgpt_state=""' in cookie and "Max-Age=0" in cookie
               for cookie in response.headers.getlist("set-cookie"))
    if succeeded:
        database.create_or_update_user.assert_awaited_once_with(**account)
        assert any("local-session" in cookie for cookie in response.headers.getlist("set-cookie"))
    else:
        database.create_or_update_user.assert_not_awaited()
        assert "auth_error=exchange_failed" in response.headers["location"]
