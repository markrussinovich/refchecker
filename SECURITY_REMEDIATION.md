# Security Remediation Summary

This document explains the six security issues identified in the targeted review, why each issue mattered, and how each one was addressed in the codebase. The issues are listed in severity order from the original review.

## 1. Broken Object-Level Authorization

### Why it mattered

In multi-user deployments, check IDs, batch IDs, and configuration IDs were being accepted by routes that did not consistently verify ownership. That meant one authenticated user could potentially read, modify, cancel, or delete another user's work if they could guess or obtain identifiers.

### How it was addressed

Ownership checks were centralized and pushed down into both the API layer and the database layer:

- check and batch reads now go through ownership-aware helpers
- mutating routes pass the current `user_id` into database updates/deletes
- active WebSocket sessions are bound to the owning user
- in-progress session metadata stores `user_id` so reconnect and cancel flows can be scoped correctly

### Example fragments

API-level ownership gate:

```python
async def _get_owned_check_or_404(check_id: int, current_user: UserInfo) -> dict:
    user_id = get_user_id_filter(current_user)
    check = await db.get_check_by_id(check_id, user_id=user_id)
    if not check:
        raise HTTPException(status_code=404, detail="Check not found")
    return check
```

WebSocket session binding:

```python
active = active_checks.get(session_id)
if not active or active.get("user_id") != token_data.user_id:
    await websocket.close(code=4001, reason="Unauthorized")
    return
```

Per-session ownership persisted for running jobs:

```python
active_checks[session_id] = {
    "task": task,
    "cancel_event": cancel_event,
    "check_id": check_id,
    "user_id": user_id,
}
```

Database mutation scoped by owner:

```python
if user_id is not None:
    cursor = await db.execute(
        "DELETE FROM llm_configs WHERE id = ? AND user_id = ?",
        (config_id, user_id),
    )
```

### Verification

- Regression tests added in `tests/unit/test_api_authorization.py`
- Full suite passed after the fix and before commit `39e2bc2`

## 2. Server-Side Request Forgery in Remote PDF Fetching

### Why it mattered

The hosted service allowed attacker-controlled URLs to flow into server-side fetch logic. Without host/IP validation, that can be used to target internal network services, cloud metadata endpoints, or loopback-only interfaces.

### How it was addressed

Remote fetch validation was centralized in `src/refchecker/utils/url_utils.py`:

- only `http` and `https` URLs are allowed
- URLs with embedded credentials are rejected
- blocked hostnames such as `localhost` and metadata endpoints are rejected
- DNS resolutions are checked to ensure all resolved addresses are public
- redirects are followed manually and revalidated at each hop
- the `/api/check` route now rejects unsafe URLs before starting work

### Example fragments

URL validation:

```python
def validate_remote_fetch_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = (parsed.scheme or '').lower()
    if scheme not in {'http', 'https'}:
        raise ValueError("Only HTTP(S) URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")
```

Public-IP enforcement:

```python
def _ensure_public_ip(ip_text: str) -> None:
    ip_obj = ipaddress.ip_address(ip_text)
    if not ip_obj.is_global:
        raise ValueError(f"Refusing to fetch non-public address: {ip_text}")
```

Redirect revalidation:

```python
for _ in range(_MAX_REDIRECTS + 1):
    validate_remote_fetch_url(current_url)
    response = session.get(current_url, timeout=timeout, headers=headers, allow_redirects=False)
    if _is_redirect_response(response.status_code):
        location = response.headers.get('location')
        current_url = urljoin(current_url, location)
        continue
    break
```

Early reject at API boundary:

```python
if parsed_source.scheme or parsed_source.netloc:
    try:
        validate_remote_fetch_url(source_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

### Verification

- Regression tests added in `tests/unit/test_url_fetch_security.py`
- Full suite passed after the fix and before commit `ebb9a1c`

## 3. Unbounded Upload and Archive Processing

### Why it mattered

Single uploads, bulk uploads, and ZIP extraction paths could consume large amounts of memory or disk if an attacker submitted oversized inputs. On a public instance, that is a practical denial-of-service vector.

### How it was addressed

The upload path was changed from whole-file reads to bounded streaming and the archive path was hardened with strict caps:

- single-file uploads are streamed in chunks
- per-file size caps are enforced while streaming
- total batch size is capped
- ZIP archive size and extracted member sizes are capped
- partial files are deleted when a limit is exceeded
- ZIP extraction ignores directories and unsupported file types

### Example fragments

Configured limits:

```python
UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_FILE_BYTES = int(os.environ.get("MAX_UPLOAD_FILE_BYTES", str(25 * 1024 * 1024)))
MAX_BATCH_UPLOAD_TOTAL_BYTES = int(os.environ.get("MAX_BATCH_UPLOAD_TOTAL_BYTES", str(100 * 1024 * 1024)))
MAX_BATCH_ARCHIVE_BYTES = int(os.environ.get("MAX_BATCH_ARCHIVE_BYTES", str(50 * 1024 * 1024)))
```

Streaming write with hard cap:

```python
async def _save_upload_file(upload: UploadFile, dest_path: Path, max_bytes: int) -> int:
    total_bytes = 0
    try:
        with open(dest_path, "wb") as out_file:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(status_code=413, detail=f"Upload exceeds maximum size of {max_bytes // (1024 * 1024)} MB")
                out_file.write(chunk)
    except Exception:
        if dest_path.exists():
            dest_path.unlink()
        raise
```

ZIP extraction with cumulative limits and cleanup:

```python
if member.file_size > MAX_UPLOAD_FILE_BYTES:
    raise HTTPException(status_code=413, detail=f"Archive entry '{os.path.basename(name)}' exceeds maximum size...")

total_bytes += member.file_size
if total_bytes > MAX_BATCH_UPLOAD_TOTAL_BYTES:
    raise HTTPException(status_code=413, detail="Extracted archive content exceeds maximum size...")
```

### Verification

- Regression tests added in `tests/unit/test_upload_limits.py`
- Full suite passed after the fix and before commit `727fb96`
- One external integration test was flaky on an earlier run and passed on rerun; the upload changes were not the cause

## 4. Plaintext-at-Rest Secret Storage

### Why it mattered

The database columns `api_key_encrypted` and `value_encrypted` were storing plaintext values despite their names. That meant any local database read or backup leak exposed provider API keys and application secrets directly.

### How it was addressed

Real encryption-at-rest was added using Fernet:

- secrets are encrypted before being written to `llm_configs` and `app_settings`
- secrets are transparently decrypted on read
- the key can come from `REFCHECKER_SECRET_KEY` or a generated local key file
- legacy plaintext rows are migrated automatically at startup

### Example fragments

Secret encryption helpers:

```python
SECRET_VALUE_PREFIX = "enc:"

def encrypt_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value == "" or _is_encrypted_secret(value):
        return value
    token = _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{SECRET_VALUE_PREFIX}{token}"
```

Legacy migration:

```python
async def _migrate_plaintext_secrets(self, db: aiosqlite.Connection):
    async with db.execute(
        "SELECT id, api_key_encrypted FROM llm_configs WHERE api_key_encrypted IS NOT NULL AND api_key_encrypted != ''"
    ) as cursor:
        llm_rows = await cursor.fetchall()
    for config_id, api_key in llm_rows:
        encrypted = encrypt_secret(api_key)
        if encrypted != api_key:
            await db.execute(
                "UPDATE llm_configs SET api_key_encrypted = ? WHERE id = ?",
                (encrypted, config_id),
            )
```

Encrypted write and decrypted read:

```python
await db.execute(
    """
    INSERT INTO app_settings (key, value_encrypted, updated_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(key) DO UPDATE SET
        value_encrypted = excluded.value_encrypted,
        updated_at = CURRENT_TIMESTAMP
    """,
    (key, encrypt_secret(value)),
)
```

```python
if row and row['value_encrypted']:
    value = row['value_encrypted']
    return decrypt_secret(value) if decrypt else value
```

### Verification

- Regression tests added in `tests/unit/test_secret_encryption.py`
- Full suite passed after the fix and before commit `c08405a`

## 5. Hosted-Mode Secrets Persisted in Browser Storage

### Why it mattered

In hosted multi-user mode, LLM and Semantic Scholar keys were being stored in browser `localStorage`. That made the secrets long-lived and available to any script executing in the page origin. It also meant keys persisted across browser restarts and account switches.

### How it was addressed

The browser-side key store was changed to in-memory only:

- `localStorage` persistence was removed from the key store
- legacy persisted keys are deleted on store initialization
- keys now exist only for the lifetime of the current tab
- logout clears all in-memory keys
- UI copy was updated so hosted users are told keys are cleared on refresh/logout

This does not make secrets invisible to malicious in-page script, but it removes long-term persistence and reduces the blast radius of a browser compromise.

### Example fragments

In-memory-only key store:

```javascript
const LEGACY_STORAGE_KEY = 'refchecker_llm_keys'

function clearLegacyKeys() {
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY)
  } catch {}
}

export const useKeyStore = create((set, get) => ({
  keys: {},
  setKey: (provider, key) => {
    const keys = { ...get().keys, [provider]: key }
    set({ keys })
  },
  clearAll: () => set({ keys: {} }),
}))
```

Keys cleared on logout:

```javascript
logout: async () => {
  try {
    await api.authLogout()
  } catch (_) { /* ignore server-side logout errors */ }
  useKeyStore.getState().clearAll()
  set({ user: null })
}
```

Updated hosted-mode UI messaging:

```jsx
{multiuser && (
  <div className="text-sm mb-3" style={{ color: 'var(--color-text-secondary)' }}>
    Keys stay in memory for this tab only and are cleared on refresh or logout.
  </div>
)}
```

### Verification

- Regression tests added in `web-ui/src/stores/useKeyStore.test.js`
- Frontend Vitest run passed after the change
- Change committed as `6073c75`

## 6. OAuth Failure Logging Could Expose Tokens

### Why it mattered

OAuth provider failures were being logged using raw response bodies and, in some cases, whole token response objects. Those payloads can contain `access_token`, `id_token`, or other sensitive values. On a hosted deployment, log access becomes a secret-exposure path.

### How it was addressed

OAuth logging was reduced to sanitized metadata:

- only safe error fields such as `error`, `error_description`, `error_code`, and `message` are extracted
- raw response bodies are no longer logged
- when `access_token` is missing, only non-sensitive response keys are logged
- provider, stage, and status code are still logged so operational debugging remains possible

### Example fragments

Sanitized HTTP failure logging:

```python
def _log_oauth_http_failure(provider: str, stage: str, response: httpx.Response) -> None:
    details = _extract_oauth_error_details(response)
    if details:
        logger.error("%s %s failed with status %s: %s", provider, stage, response.status_code, details)
        return
    logger.error("%s %s failed with status %s", provider, stage, response.status_code)
```

Logging only safe keys when `access_token` is absent:

```python
def _log_missing_access_token(provider: str, tokens: Dict[str, Any]) -> None:
    safe_keys = sorted(key for key in tokens.keys() if key not in _SENSITIVE_OAUTH_KEYS)
    logger.error("%s token response missing access_token; non-sensitive keys=%s", provider, safe_keys)
```

Provider flow updated to use the sanitizer:

```python
if token_resp.status_code != 200:
    _log_oauth_http_failure("Google", "token exchange", token_resp)
    return None

tokens = token_resp.json()
access_token = tokens.get("access_token")
if not access_token:
    _log_missing_access_token("GitHub", tokens)
    return None
```

### Verification

- Regression tests added in `tests/unit/test_auth.py`
- Added explicit checks that token strings do not appear in captured logs
- Targeted auth tests passed, then the full suite passed on rerun after a known flaky external integration test
- Change committed as `d4f4242`

## Validation Summary

The remediation work was verified incrementally after each issue was fixed:

- API authorization regression coverage added and full suite passed
- SSRF regression coverage added and full suite passed
- upload/archive limit regression coverage added and full suite passed
- secret encryption regression coverage added and full suite passed
- frontend key-store regression coverage added and Vitest passed
- OAuth log-sanitization regression coverage added and full Python suite passed

Final validation status from the last full Python run:

- `712 passed`
- `1 skipped`
- known warnings remained, but no failures were attributable to the remediation set

## Commit Sequence

1. `39e2bc2` Fix multi-user object authorization
2. `ebb9a1c` Block SSRF in remote PDF fetches
3. `727fb96` Bound upload and archive resource usage
4. `c08405a` Encrypt stored API secrets at rest
5. `6073c75` Remove hosted browser key persistence
6. `d4f4242` Sanitize OAuth failure logging