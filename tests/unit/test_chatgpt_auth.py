from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from refchecker.llm import chatgpt_auth


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = "" if self.ok else "request failed"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.text)


@pytest.fixture(autouse=True)
def isolated_auth_store(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "REFCHECKER_CHATGPT_AUTH_FILE",
        str(tmp_path / "chatgpt_auth.json"),
    )
    chatgpt_auth._PENDING_ATTEMPTS.clear()
    chatgpt_auth._REFRESH_LOCKS.clear()
    yield
    chatgpt_auth._PENDING_ATTEMPTS.clear()
    chatgpt_auth._REFRESH_LOCKS.clear()


def test_start_authorization_uses_dynamic_registration_and_pkce():
    url = chatgpt_auth.start_authorization(
        "local",
        "http://127.0.0.1:8123/auth/callback",
    )
    query = parse_qs(urlparse(url).query)

    assert query["client_id"] == [chatgpt_auth.DYNAMIC_CLIENT_ID]
    assert query["agent_name_hint"] == ["RefChecker"]
    assert query["resource"] == [chatgpt_auth.RESOURCE]
    assert query["code_challenge_method"] == ["S256"]
    assert chatgpt_auth.REQUIRED_PLAN_SCOPE in query["scope"][0]
    assert query["ext_agent_host_id"][0].startswith("urn:uuid:")


def test_complete_authorization_saves_validated_renewable_credentials(monkeypatch):
    url = chatgpt_auth.start_authorization(
        "user:7",
        "http://127.0.0.1:8123/auth/callback",
    )
    state = parse_qs(urlparse(url).query)["state"][0]

    class _Session:
        def post(self, *args, **kwargs):
            return _Response({
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "id_token": "id-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": chatgpt_auth.SCOPES,
            })

    monkeypatch.setattr(chatgpt_auth.requests, "Session", _Session)
    monkeypatch.setattr(
        chatgpt_auth,
        "_validate_id_token",
        lambda id_token, client_id, nonce, access_token, session: {
            "sub": "account-subject",
            "iss": "https://auth.openai.com",
            "email": "person@example.com",
            "name": "Person",
        },
    )

    status = chatgpt_auth.complete_authorization({
        "code": "authorization-code",
        "state": state,
        "client_id": "oaiapp_registered",
        "scope": chatgpt_auth.SCOPES,
    })

    assert status == {
        "connected": True,
        "email": "person@example.com",
        "name": "Person",
        "picture": None,
        "client_id": "oaiapp_registered",
    }
    assert chatgpt_auth.get_access_token("user:7") == "access-token"


def test_id_token_validation_passes_access_token_for_at_hash(monkeypatch):
    captured = {}

    class _JWT:
        @staticmethod
        def get_unverified_header(_token):
            return {"kid": "signing-key"}

        @staticmethod
        def decode(_token, _key, **kwargs):
            captured.update(kwargs)
            return {
                "sub": "account-subject",
                "nonce": "expected-nonce",
            }

    monkeypatch.setitem(__import__("sys").modules, "jose", SimpleNamespace(jwt=_JWT))
    session = SimpleNamespace(
        get=lambda url, timeout: _Response(
            {"issuer": "https://auth.openai.com", "jwks_uri": "https://auth.openai.com/jwks"}
            if "well-known" in url
            else {"keys": [{"kid": "signing-key", "alg": "RS256"}]}
        )
    )

    claims = chatgpt_auth._validate_id_token(
        "id-token",
        "oaiapp_registered",
        "expected-nonce",
        "access-token",
        session,
    )

    assert claims["sub"] == "account-subject"
    assert captured["access_token"] == "access-token"


def test_expired_access_token_is_refreshed_and_rotated(monkeypatch):
    store = {
        "version": 1,
        "ext_agent_host_id": "urn:uuid:test",
        "owners": {
            "local": {
                "client_id": "oaiapp_registered",
                "access_token": "expired",
                "refresh_token": "old-refresh",
                "expires_at": 0,
                "scopes": chatgpt_auth.SCOPES.split(),
            },
        },
    }
    chatgpt_auth._save_store(store)
    monkeypatch.setattr(
        chatgpt_auth.requests,
        "post",
        lambda *args, **kwargs: _Response({
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "scope": chatgpt_auth.SCOPES,
        }),
    )

    assert chatgpt_auth.get_access_token("local") == "new-access"
    saved = chatgpt_auth._load_store()["owners"]["local"]
    assert saved["refresh_token"] == "new-refresh"
    assert saved["access_token"] == "new-access"


def test_stream_responses_call_requires_completed_terminal_event():
    completed = SimpleNamespace(
        output=[
            SimpleNamespace(
                content=[
                    SimpleNamespace(
                        annotations=[SimpleNamespace(url="https://example.com/paper")]
                    )
                ]
            )
        ],
        usage=SimpleNamespace(input_tokens=10, output_tokens=3),
    )
    events = [
        SimpleNamespace(type="response.output_text.delta", delta="hel"),
        SimpleNamespace(type="response.output_text.delta", delta="lo"),
        SimpleNamespace(type="response.completed", response=completed),
    ]
    request = {}

    def create(**kwargs):
        request.update(kwargs)
        return iter(events)

    client = SimpleNamespace(responses=SimpleNamespace(create=create))

    text, response, urls = chatgpt_auth.stream_responses_call(
        client,
        model="gpt-test",
        instructions="Be concise.",
        input_text="Say hello.",
    )

    assert text == "hello"
    assert response is completed
    assert urls == ["https://example.com/paper"]
    assert request["store"] is False
    assert request["stream"] is True
    assert "temperature" not in request
    assert "max_output_tokens" not in request


def test_stream_responses_call_rejects_interrupted_stream():
    client = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kwargs: iter([
                SimpleNamespace(type="response.output_text.delta", delta="partial")
            ])
        )
    )

    with pytest.raises(chatgpt_auth.ChatGPTAuthError, match="without response.completed"):
        chatgpt_auth.stream_responses_call(
            client,
            model="gpt-test",
            instructions="Be concise.",
            input_text="Say hello.",
        )
