"""
Authentication module for RefChecker multi-user web application.

Provides:
- JWT token creation and validation (using PyJWT)
- Google OAuth 2.0 Authorization Code flow
- GitHub OAuth flow
- FastAPI dependency for protecting endpoints
- In-memory API key storage (keys are never persisted to database)
"""
import os
import secrets
import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone

import jwt
import httpx
from fastapi import Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


AUTH_ENABLED: bool = os.environ.get("AUTH_ENABLED", "false").lower() in ("1", "true", "yes")

# JWT settings
JWT_SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", secrets.token_hex(32))
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_SECONDS: int = int(os.environ.get("JWT_EXPIRE_SECONDS", str(7 * 24 * 3600)))  # 7 days

# Google OAuth
GOOGLE_CLIENT_ID: str = _get_env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET: str = _get_env("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI: str = _get_env("GOOGLE_REDIRECT_URI", "")  # set at runtime if empty
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# GitHub OAuth
GITHUB_CLIENT_ID: str = _get_env("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET: str = _get_env("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI: str = _get_env("GITHUB_REDIRECT_URI", "")  # set at runtime if empty
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USERINFO_URL = "https://api.github.com/user"
GITHUB_EMAIL_URL = "https://api.github.com/user/emails"

# Frontend redirect destination after OAuth success/failure
FRONTEND_REDIRECT_BASE: str = _get_env("FRONTEND_REDIRECT_BASE", "/")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

# CSRF state tokens for OAuth: {state_token: {"provider": ..., "created_at": ...}}
_oauth_states: Dict[str, Dict[str, Any]] = {}

# In-memory API keys per user: {user_id: {"provider": api_key, ...}}
# Keys are NEVER written to the database.
_user_api_keys: Dict[int, Dict[str, str]] = {}

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class UserInfo(BaseModel):
    id: int
    provider: str
    provider_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None


class TokenData(BaseModel):
    user_id: int
    email: Optional[str] = None
    name: Optional[str] = None


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(user_id: int, email: Optional[str], name: Optional[str]) -> str:
    """Create a signed JWT access token."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "iat": now,
        "exp": now + JWT_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[TokenData]:
    """Decode and validate a JWT token. Returns None on failure."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
        return TokenData(
            user_id=user_id,
            email=payload.get("email"),
            name=payload.get("name"),
        )
    except jwt.ExpiredSignatureError:
        logger.debug("JWT token expired")
        return None
    except Exception as exc:
        logger.debug(f"JWT decode error: {exc}")
        return None


# ---------------------------------------------------------------------------
# OAuth state helpers (CSRF protection)
# ---------------------------------------------------------------------------

def _generate_oauth_state(provider: str) -> str:
    """Generate a random CSRF state token for an OAuth flow."""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"provider": provider, "created_at": time.time()}
    # Clean up old states (older than 10 minutes)
    cutoff = time.time() - 600
    expired = [k for k, v in _oauth_states.items() if v["created_at"] < cutoff]
    for k in expired:
        del _oauth_states[k]
    return state


def _validate_oauth_state(state: str, provider: str) -> bool:
    """Validate and consume an OAuth state token."""
    entry = _oauth_states.pop(state, None)
    if not entry:
        return False
    if entry["provider"] != provider:
        return False
    if time.time() - entry["created_at"] > 600:
        return False
    return True


# ---------------------------------------------------------------------------
# OAuth URL builders
# ---------------------------------------------------------------------------

def get_google_auth_url(request: Request) -> str:
    """Build the Google OAuth authorization URL."""
    state = _generate_oauth_state("google")
    redirect_uri = GOOGLE_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/auth/google/callback"
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GOOGLE_AUTH_URL}?{query}"


def get_github_auth_url(request: Request) -> str:
    """Build the GitHub OAuth authorization URL."""
    state = _generate_oauth_state("github")
    redirect_uri = GITHUB_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/auth/github/callback"
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GITHUB_AUTH_URL}?{query}"


# ---------------------------------------------------------------------------
# OAuth token exchange and user info
# ---------------------------------------------------------------------------

async def exchange_google_code(code: str, request: Request) -> Optional[Dict[str, Any]]:
    """Exchange Google auth code for user info."""
    redirect_uri = GOOGLE_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/auth/google/callback"
    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        if token_resp.status_code != 200:
            logger.error(f"Google token exchange failed: {token_resp.text}")
            return None
        tokens = token_resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            return None

        # Get user info
        user_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            logger.error(f"Google userinfo failed: {user_resp.text}")
            return None
        user_data = user_resp.json()
        return {
            "provider": "google",
            "provider_id": user_data.get("sub"),
            "email": user_data.get("email"),
            "name": user_data.get("name"),
            "avatar_url": user_data.get("picture"),
        }


async def exchange_github_code(code: str, request: Request) -> Optional[Dict[str, Any]]:
    """Exchange GitHub auth code for user info."""
    redirect_uri = GITHUB_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/auth/github/callback"
    async with httpx.AsyncClient() as client:
        # Exchange code for access token
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            logger.error(f"GitHub token exchange failed: {token_resp.text}")
            return None
        tokens = token_resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            logger.error(f"GitHub: no access_token in response: {tokens}")
            return None

        # Get user info
        user_resp = await client.get(
            GITHUB_USERINFO_URL,
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/json",
            },
        )
        if user_resp.status_code != 200:
            logger.error(f"GitHub user info failed: {user_resp.text}")
            return None
        user_data = user_resp.json()

        # Get primary email (may not be public in /user)
        email = user_data.get("email")
        if not email:
            email_resp = await client.get(
                GITHUB_EMAIL_URL,
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/json",
                },
            )
            if email_resp.status_code == 200:
                emails = email_resp.json()
                primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
                if primary:
                    email = primary.get("email")

        return {
            "provider": "github",
            "provider_id": str(user_data.get("id")),
            "email": email,
            "name": user_data.get("name") or user_data.get("login"),
            "avatar_url": user_data.get("avatar_url"),
        }


# ---------------------------------------------------------------------------
# In-memory API key management
# ---------------------------------------------------------------------------

def store_user_api_key(user_id: int, provider: str, api_key: str) -> None:
    """Store an API key in memory for the given user. Never persisted."""
    if user_id not in _user_api_keys:
        _user_api_keys[user_id] = {}
    _user_api_keys[user_id][provider] = api_key


def get_user_api_key(user_id: int, provider: str) -> Optional[str]:
    """Retrieve an in-memory API key for the given user and provider."""
    return _user_api_keys.get(user_id, {}).get(provider)


def delete_user_api_key(user_id: int, provider: str) -> None:
    """Remove an API key from memory."""
    if user_id in _user_api_keys:
        _user_api_keys[user_id].pop(provider, None)


def has_user_api_key(user_id: int, provider: str) -> bool:
    """Check whether the user has an in-memory API key for the provider."""
    return bool(_user_api_keys.get(user_id, {}).get(provider))


def get_user_api_key_providers(user_id: int) -> list[str]:
    """List provider names for which the user has stored an in-memory key."""
    return list(_user_api_keys.get(user_id, {}).keys())


# ---------------------------------------------------------------------------
# FastAPI dependency: get current authenticated user
# ---------------------------------------------------------------------------

def _extract_token(request: Request) -> Optional[str]:
    """Extract bearer token from Authorization header or ws query param."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    # Allow token in query string for WebSocket connections
    return request.query_params.get("token")


async def get_current_user(request: Request) -> Optional[UserInfo]:
    """
    FastAPI dependency.  Returns the authenticated UserInfo, or None when
    AUTH_ENABLED is false (anonymous / single-user mode).

    Raises HTTP 401 when AUTH_ENABLED is true and no valid token is present.
    """
    if not AUTH_ENABLED:
        return None  # auth disabled – all requests allowed

    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = decode_access_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Import here to avoid circular imports
    from .database import db as _db
    user_row = await _db.get_user_by_id(token_data.user_id)
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return UserInfo(**user_row)


async def require_user(
    current_user: Optional[UserInfo] = Depends(get_current_user),
) -> Optional[UserInfo]:
    """
    Dependency alias.  When AUTH_ENABLED is true this is the same as
    get_current_user (raises 401 if not authenticated).  When AUTH_ENABLED is
    false it is a no-op and returns None.
    """
    return current_user


def get_user_id_filter(user: Optional[UserInfo]) -> Optional[int]:
    """Return the user_id to filter DB queries by, or None for no filter."""
    if user is None:
        return None
    return user.id


# ---------------------------------------------------------------------------
# Available providers helper
# ---------------------------------------------------------------------------

def get_available_providers() -> list[str]:
    """Return the list of configured OAuth providers."""
    providers = []
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        providers.append("google")
    if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET:
        providers.append("github")
    return providers
