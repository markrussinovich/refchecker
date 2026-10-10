"""Sign in with ChatGPT for local and open-source RefChecker clients."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
import uuid
import webbrowser
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests


AUTHORIZATION_ENDPOINT = "https://auth.openai.com/api/accounts/authorize"
TOKEN_ENDPOINT = "https://auth.openai.com/api/accounts/oauth/token"
OIDC_CONFIGURATION_URL = "https://auth.openai.com/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DYNAMIC_CLIENT_ID = "dynamic_agent_client"
AGENT_NAME = "RefChecker"
REQUIRED_PLAN_SCOPE = "chatgpt.tokens.use.direct"

_STORE_LOCK = threading.RLock()
_REFRESH_LOCKS: Dict[str, threading.Lock] = {}
_PENDING_LOCK = threading.Lock()
_PENDING_ATTEMPTS: Dict[str, Dict[str, Any]] = {}
_ATTEMPT_TTL_SECONDS = 10 * 60


class ChatGPTAuthError(RuntimeError):
    """Raised when ChatGPT authorization or token renewal fails."""


@contextmanager
def _process_lock():
    """Serialize credential rotation across CLI and WebUI processes."""
    lock_path = _credentials_path().with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _credentials_path() -> Path:
    override = os.environ.get("REFCHECKER_CHATGPT_AUTH_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".refchecker" / "chatgpt_auth.json"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _load_store() -> Dict[str, Any]:
    path = _credentials_path()
    if not path.exists():
        return {"version": 1, "ext_agent_host_id": f"urn:uuid:{uuid.uuid4()}", "owners": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChatGPTAuthError(f"Unable to read ChatGPT credentials: {exc}") from exc
    data.setdefault("version", 1)
    data.setdefault("ext_agent_host_id", f"urn:uuid:{uuid.uuid4()}")
    data.setdefault("owners", {})
    return data


def _save_store(data: Dict[str, Any]) -> None:
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    payload = json.dumps(data, indent=2, sort_keys=True)
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _owner_record(owner: str) -> Optional[Dict[str, Any]]:
    with _STORE_LOCK:
        return _load_store().get("owners", {}).get(owner)


def _prune_attempts() -> None:
    cutoff = time.time() - _ATTEMPT_TTL_SECONDS
    for state in [
        key for key, value in _PENDING_ATTEMPTS.items()
        if value.get("created_at", 0) < cutoff
    ]:
        _PENDING_ATTEMPTS.pop(state, None)


def start_authorization(owner: str, redirect_uri: str) -> str:
    """Create an OAuth attempt and return the OpenAI authorization URL."""
    if not redirect_uri.startswith("http://127.0.0.1:"):
        raise ChatGPTAuthError("ChatGPT OAuth requires a 127.0.0.1 loopback callback")

    with _process_lock(), _STORE_LOCK:
        store = _load_store()
        if not _credentials_path().exists():
            _save_store(store)
        record = store["owners"].get(owner) or {}

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    issued_client_id = record.get("client_id")
    client_id = issued_client_id or DYNAMIC_CLIENT_ID

    attempt = {
        "owner": owner,
        "state": state,
        "nonce": nonce,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "issued_client_id": issued_client_id,
        "expected_subject": record.get("subject"),
        "created_at": time.time(),
    }
    with _PENDING_LOCK:
        _prune_attempts()
        _PENDING_ATTEMPTS[state] = attempt

    params = {
        "client_id": client_id,
        "ext_agent_host_id": store["ext_agent_host_id"],
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if not issued_client_id:
        params["agent_name_hint"] = AGENT_NAME
    else:
        if record.get("id_token"):
            params["id_token_hint"] = record["id_token"]
        if record.get("email"):
            params["login_hint"] = record["email"]
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


def _select_jwk(jwks: Dict[str, Any], kid: str) -> Dict[str, Any]:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    raise ChatGPTAuthError("OpenAI ID token used an unknown signing key")


def _validate_id_token(
    id_token: str,
    client_id: str,
    nonce: str,
    access_token: str,
    session: requests.Session,
) -> Dict[str, Any]:
    try:
        from jose import jwt
    except ImportError as exc:
        raise ChatGPTAuthError(
            "ChatGPT sign-in requires python-jose; install academic-refchecker[webui]"
        ) from exc

    discovery_response = session.get(OIDC_CONFIGURATION_URL, timeout=15)
    discovery_response.raise_for_status()
    discovery = discovery_response.json()
    jwks_response = session.get(discovery["jwks_uri"], timeout=15)
    jwks_response.raise_for_status()
    jwk = _select_jwk(jwks_response.json(), jwt.get_unverified_header(id_token).get("kid"))
    try:
        claims = jwt.decode(
            id_token,
            jwk,
            algorithms=[jwk.get("alg", "RS256")],
            audience=client_id,
            issuer=discovery["issuer"],
            access_token=access_token,
        )
    except Exception as exc:
        raise ChatGPTAuthError(f"OpenAI ID token validation failed: {exc}") from exc
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ChatGPTAuthError("OpenAI ID token nonce did not match the authorization request")
    if not claims.get("sub"):
        raise ChatGPTAuthError("OpenAI ID token did not contain an account subject")
    return claims


def complete_authorization(params: Dict[str, str]) -> Dict[str, Any]:
    """Validate an OAuth callback, exchange its code, and persist credentials."""
    state = params.get("state", "")
    with _PENDING_LOCK:
        _prune_attempts()
        attempt = _PENDING_ATTEMPTS.pop(state, None)
    if not attempt:
        raise ChatGPTAuthError("ChatGPT authorization state is missing or expired")
    if params.get("error"):
        detail = params.get("error_description") or params["error"]
        raise ChatGPTAuthError(f"ChatGPT authorization was not completed: {detail}")
    code = params.get("code")
    if not code:
        raise ChatGPTAuthError("ChatGPT authorization callback did not include a code")

    callback_client_id = params.get("client_id")
    if attempt["issued_client_id"]:
        if callback_client_id and callback_client_id != attempt["issued_client_id"]:
            raise ChatGPTAuthError("ChatGPT returned a different client registration")
        client_id = attempt["issued_client_id"]
    else:
        client_id = callback_client_id or ""
        if not client_id or client_id == DYNAMIC_CLIENT_ID:
            raise ChatGPTAuthError("ChatGPT dynamic client registration was incomplete")

    session = requests.Session()
    token_response = session.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": attempt["code_verifier"],
            "redirect_uri": attempt["redirect_uri"],
            "resource": RESOURCE,
        },
        timeout=30,
    )
    if not token_response.ok:
        raise ChatGPTAuthError(
            f"ChatGPT token exchange failed ({token_response.status_code}): "
            f"{token_response.text[:300]}"
        )
    tokens = token_response.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise ChatGPTAuthError("ChatGPT token response did not include an ID token")
    access_token = tokens.get("access_token")
    if not access_token:
        raise ChatGPTAuthError("ChatGPT token response did not include an access token")
    claims = _validate_id_token(
        id_token,
        client_id,
        attempt["nonce"],
        access_token,
        session,
    )
    if attempt.get("expected_subject") and claims["sub"] != attempt["expected_subject"]:
        raise ChatGPTAuthError("The selected ChatGPT account does not match this registration")

    scopes = (tokens.get("scope") or "").split()
    if REQUIRED_PLAN_SCOPE not in scopes:
        raise ChatGPTAuthError("ChatGPT plan usage permission was not granted")
    expires_in = int(tokens.get("expires_in") or 3600)
    now = time.time()
    record = {
        "email": claims.get("email"),
        "name": claims.get("name"),
        "picture": claims.get("picture"),
        "issuer": claims.get("iss"),
        "subject": claims["sub"],
        "client_id": client_id,
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": tokens.get("refresh_token"),
        "token_type": tokens.get("token_type", "Bearer"),
        "expires_in": expires_in,
        "expires_at": now + expires_in,
        "scopes": scopes,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    if not record["access_token"] or not record["refresh_token"]:
        raise ChatGPTAuthError("ChatGPT token response was missing renewable credentials")

    with _process_lock(), _STORE_LOCK:
        store = _load_store()
        store["owners"][attempt["owner"]] = record
        _save_store(store)
    return public_status(attempt["owner"])


def public_status(owner: str) -> Dict[str, Any]:
    """Return non-secret account state suitable for a UI or API response."""
    record = _owner_record(owner)
    connected = bool(
        record
        and record.get("refresh_token")
        and REQUIRED_PLAN_SCOPE in record.get("scopes", [])
    )
    return {
        "connected": connected,
        "email": record.get("email") if connected else None,
        "name": record.get("name") if connected else None,
        "picture": record.get("picture") if connected else None,
        "client_id": record.get("client_id") if connected else None,
    }


def _refresh_access_token(owner: str, record: Dict[str, Any]) -> str:
    response = requests.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "refresh_token",
            "client_id": record["client_id"],
            "refresh_token": record["refresh_token"],
            "resource": RESOURCE,
        },
        timeout=30,
    )
    if not response.ok:
        raise ChatGPTAuthError(
            f"ChatGPT session refresh failed ({response.status_code}); sign in again"
        )
    tokens = response.json()
    access_token = tokens.get("access_token")
    if not access_token:
        raise ChatGPTAuthError("ChatGPT refresh response did not include an access token")
    expires_in = int(tokens.get("expires_in") or 3600)

    with _STORE_LOCK:
        store = _load_store()
        current = store["owners"].get(owner)
        if (
            not current
            or current.get("client_id") != record.get("client_id")
            or current.get("refresh_token") != record.get("refresh_token")
        ):
            raise ChatGPTAuthError("ChatGPT account changed while its token was refreshing")
        current.update({
            "access_token": access_token,
            "refresh_token": tokens.get("refresh_token") or current["refresh_token"],
            "id_token": tokens.get("id_token") or current.get("id_token"),
            "token_type": tokens.get("token_type", current.get("token_type", "Bearer")),
            "expires_in": expires_in,
            "expires_at": time.time() + expires_in,
            "scopes": (tokens.get("scope") or " ".join(current.get("scopes", []))).split(),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        })
        _save_store(store)
    return access_token


def get_access_token(owner: str = "local") -> str:
    """Return a current access token, refreshing it when necessary."""
    lock = _REFRESH_LOCKS.setdefault(owner, threading.Lock())
    with lock:
        with _process_lock():
            record = _owner_record(owner)
            if not record or not record.get("refresh_token"):
                raise ChatGPTAuthError("No ChatGPT account is connected")
            if REQUIRED_PLAN_SCOPE not in record.get("scopes", []):
                raise ChatGPTAuthError("ChatGPT plan usage permission is not available")
            if record.get("access_token") and float(record.get("expires_at", 0)) > time.time() + 60:
                return record["access_token"]
            return _refresh_access_token(owner, record)


def list_models(owner: str = "local") -> list[Dict[str, str]]:
    """List the displayable model catalog for the selected ChatGPT account."""
    response = requests.get(
        f"{RESOURCE}/models",
        headers={"Authorization": f"Bearer {get_access_token(owner)}"},
        timeout=20,
    )
    if not response.ok:
        raise ChatGPTAuthError(
            f"Unable to list ChatGPT models ({response.status_code}): {response.text[:300]}"
        )
    raw_models = response.json().get("models", [])
    return [
        {"slug": model["slug"], "display_name": model.get("display_name") or model["slug"]}
        for model in raw_models
        if model.get("visibility") == "list" and model.get("slug")
    ]


def disconnect(owner: str = "local") -> bool:
    """Revoke the renewable session and clear its local tokens."""
    with _process_lock():
        with _STORE_LOCK:
            store = _load_store()
            record = store["owners"].get(owner)
        if not record:
            return True

        revoked = False
        refresh_token = record.get("refresh_token")
        if refresh_token:
            try:
                discovery = requests.get(OIDC_CONFIGURATION_URL, timeout=15)
                discovery.raise_for_status()
                endpoint = discovery.json()["revocation_endpoint"]
                response = requests.post(
                    endpoint,
                    data={
                        "token": refresh_token,
                        "token_type_hint": "refresh_token",
                        "client_id": record["client_id"],
                    },
                    timeout=15,
                )
                revoked = response.status_code == 200
            except requests.RequestException:
                revoked = False

        with _STORE_LOCK:
            store = _load_store()
            current = store["owners"].get(owner)
            if current and current.get("refresh_token") == refresh_token:
                for key in ("access_token", "refresh_token", "id_token", "expires_at"):
                    current.pop(key, None)
                _save_store(store)
    return revoked


def login_interactive(owner: str = "local") -> Dict[str, Any]:
    """Complete the loopback OAuth flow in a system browser for CLI use."""
    result: Dict[str, Any] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            try:
                query = {
                    key: values[0]
                    for key, values in parse_qs(urlparse(self.path).query).items()
                    if values
                }
                result["status"] = complete_authorization(query)
                heading = "ChatGPT connected"
                message = "You can close this window and return to RefChecker."
                status_code = 200
            except Exception as exc:
                result["error"] = exc
                heading = "ChatGPT connection failed"
                message = html.escape(str(exc))
                status_code = 400
            body = (
                "<!doctype html><meta charset='utf-8'><title>RefChecker</title>"
                f"<h1>{heading}</h1><p>{message}</p>"
            ).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: Any) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_port}/api/chatgpt/auth/callback"
    authorization_url = start_authorization(owner, redirect_uri)
    if not webbrowser.open(authorization_url):
        print(f"Open this URL to continue with ChatGPT:\n{authorization_url}")
    deadline = time.monotonic() + _ATTEMPT_TTL_SECONDS
    while "status" not in result and "error" not in result and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()
    if "error" in result:
        raise ChatGPTAuthError(str(result["error"]))
    if "status" not in result:
        raise ChatGPTAuthError("Timed out waiting for ChatGPT authorization")
    return result["status"]


def stream_responses_call(
    client: Any,
    *,
    model: str,
    instructions: str,
    input_text: str,
    tools: Optional[list[Dict[str, Any]]] = None,
) -> tuple[str, Any, list[str]]:
    """Run a SIWC-compatible streaming Responses call to completion."""
    kwargs: Dict[str, Any] = {
        "model": model,
        "instructions": instructions,
        "input": [{"role": "user", "content": input_text}],
        "store": False,
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools
    stream = client.responses.create(**kwargs)
    text_parts: list[str] = []
    completed_response = None
    context = stream if hasattr(stream, "__enter__") else nullcontext(stream)
    with context as events:
        for event in events:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                text_parts.append(getattr(event, "delta", "") or "")
            elif event_type == "response.failed":
                error = getattr(getattr(event, "response", None), "error", None)
                code = getattr(error, "code", None) or "unknown_error"
                message = getattr(error, "message", None) or "ChatGPT request failed"
                raise ChatGPTAuthError(f"{message} ({code})")
            elif event_type == "response.incomplete":
                raise ChatGPTAuthError("ChatGPT response was incomplete")
            elif event_type == "response.completed":
                completed_response = getattr(event, "response", None)
    if completed_response is None:
        raise ChatGPTAuthError("ChatGPT stream ended without response.completed")

    urls: list[str] = []
    seen_urls: set[str] = set()
    for item in getattr(completed_response, "output", []) or []:
        for block in getattr(item, "content", []) or []:
            for annotation in getattr(block, "annotations", []) or []:
                url = getattr(annotation, "url", "") or ""
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    urls.append(url)
    return "".join(text_parts).strip(), completed_response, urls
