"""
Auth module for RefChecker multi-user web app.
- JWT via python-jose stored as HttpOnly cookies
- OAuth flows: Google, GitHub, Microsoft
- No AUTH_ENABLED toggle - auth always required
- No in-memory API keys (keys live in browser localStorage, sent per-request)
"""
import os
import secrets
import time
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlencode

from jose import jwt, JWTError
import httpx
from fastapi import Depends, HTTPException, status, Request, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# JWT settings
JWT_SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", secrets.token_hex(32))
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_SECONDS: int = int(os.environ.get("JWT_EXPIRE_SECONDS", str(7 * 24 * 3600)))  # 7 days

# Cookie settings
COOKIE_NAME = "rc_auth"
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = "lax"
COOKIE_SECURE: bool = os.environ.get("HTTPS_ONLY", "false").lower() in ("1", "true", "yes")

# Google OAuth
GOOGLE_CLIENT_ID: str = _get_env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET: str = _get_env("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI: str = _get_env("GOOGLE_REDIRECT_URI", "")
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# GitHub OAuth
GITHUB_CLIENT_ID: str = _get_env("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET: str = _get_env("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI: str = _get_env("GITHUB_REDIRECT_URI", "")
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USERINFO_URL = "https://api.github.com/user"
GITHUB_EMAIL_URL = "https://api.github.com/user/emails"

# Microsoft OAuth
MS_CLIENT_ID: str = _get_env("MS_CLIENT_ID")
MS_CLIENT_SECRET: str = _get_env("MS_CLIENT_SECRET")
MS_REDIRECT_URI: str = _get_env("MS_REDIRECT_URI", "")
MS_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"

# Redirect destination after login (default: root)
SITE_URL: str = _get_env("SITE_URL", "/")

# ---------------------------------------------------------------------------
# In-memory OAuth CSRF state store
# ---------------------------------------------------------------------------

# {state_token: {"provider": ..., "created_at": ...}}
_oauth_states: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class UserInfo(BaseModel):
    id: int
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    provider: str
    is_admin: bool = False


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
    except JWTError as exc:
        logger.debug(f"JWT decode error: {exc}")
        return None
    except Exception as exc:
        logger.debug(f"JWT decode error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def set_auth_cookie(response: Response, token: str) -> None:
    """Set the HttpOnly auth cookie on a response."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=COOKIE_HTTPONLY,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        max_age=JWT_EXPIRE_SECONDS,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Expire the auth cookie (logout)."""
    response.delete_cookie(key=COOKIE_NAME, path="/")


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
    redirect_uri = GOOGLE_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/auth/callback/google"
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def get_github_auth_url(request: Request) -> str:
    """Build the GitHub OAuth authorization URL."""
    state = _generate_oauth_state("github")
    redirect_uri = GITHUB_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/auth/callback/github"
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
        "state": state,
    }
    return f"{GITHUB_AUTH_URL}?{urlencode(params)}"


def get_microsoft_auth_url(request: Request) -> str:
    """Build the Microsoft OAuth authorization URL."""
    state = _generate_oauth_state("microsoft")
    redirect_uri = MS_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/auth/callback/microsoft"
    params = {
        "client_id": MS_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    }
    return f"{MS_AUTH_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# OAuth token exchange and user info
# ---------------------------------------------------------------------------

async def exchange_google_code(code: str, request: Request) -> Optional[Dict[str, Any]]:
    """Exchange Google auth code for user info."""
    redirect_uri = GOOGLE_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/auth/callback/google"
    async with httpx.AsyncClient() as client:
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
    redirect_uri = GITHUB_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/auth/callback/github"
    async with httpx.AsyncClient() as client:
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


async def exchange_microsoft_code(code: str, request: Request) -> Optional[Dict[str, Any]]:
    """Exchange Microsoft auth code for user info."""
    redirect_uri = MS_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/auth/callback/microsoft"
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            MS_TOKEN_URL,
            data={
                "client_id": MS_CLIENT_ID,
                "client_secret": MS_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": "openid email profile",
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            logger.error(f"Microsoft token exchange failed: {token_resp.text}")
            return None
        tokens = token_resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            logger.error(f"Microsoft: no access_token in response: {tokens}")
            return None

        # Try to get user info from id_token claims first, fall back to Graph API
        id_token = tokens.get("id_token")
        email = None
        name = None
        provider_id = None
        avatar_url = None

        if id_token:
            try:
                # Decode without verification to extract claims (already verified by token exchange)
                claims = jwt.get_unverified_claims(id_token)
                email = claims.get("email") or claims.get("preferred_username")
                name = claims.get("name")
                provider_id = claims.get("oid") or claims.get("sub")
            except Exception as exc:
                logger.debug(f"Failed to decode MS id_token claims: {exc}")

        if not provider_id:
            # Fall back to Microsoft Graph API
            me_resp = await client.get(
                MS_GRAPH_ME_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if me_resp.status_code != 200:
                logger.error(f"Microsoft Graph /me failed: {me_resp.text}")
                return None
            me_data = me_resp.json()
            provider_id = me_data.get("id")
            email = email or me_data.get("mail") or me_data.get("userPrincipalName")
            name = name or me_data.get("displayName")

        return {
            "provider": "microsoft",
            "provider_id": str(provider_id),
            "email": email,
            "name": name,
            "avatar_url": avatar_url,
        }


# ---------------------------------------------------------------------------
# FastAPI dependency: get current authenticated user
# ---------------------------------------------------------------------------

async def get_current_user(request: Request) -> UserInfo:
    """
    FastAPI dependency. Reads JWT from the HttpOnly cookie ``rc_auth``.
    Always raises HTTP 401 if no valid cookie is present.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token_data = decode_access_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
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
    current_user: UserInfo = Depends(get_current_user),
) -> UserInfo:
    """Dependency alias for get_current_user (always requires auth)."""
    return current_user


def get_user_id_filter(user: UserInfo) -> int:
    """Return the user_id to filter DB queries by."""
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
    if MS_CLIENT_ID and MS_CLIENT_SECRET:
        providers.append("microsoft")
    return providers
