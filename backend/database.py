"""
Database module for storing check history and LLM configurations
"""
import aiosqlite
import base64
import hashlib
import json
import os
import sys
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken


SECRET_VALUE_PREFIX = "enc:"
SECRET_KEY_ENV_VAR = "REFCHECKER_SECRET_KEY"
SECRET_KEY_FILE_NAME = ".secret.key"
_fernet_instance: Optional[Fernet] = None


def _normalize_secret_key(raw_value: str) -> bytes:
    """Normalize environment-provided key material into a Fernet key."""
    candidate = raw_value.strip().encode("utf-8")
    try:
        decoded = base64.urlsafe_b64decode(candidate)
        if len(decoded) == 32:
            return candidate
    except Exception:
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(candidate).digest())


def _get_secret_key_path() -> Path:
    return get_data_dir() / SECRET_KEY_FILE_NAME


def _get_or_create_secret_key() -> bytes:
    configured_key = os.environ.get(SECRET_KEY_ENV_VAR, "").strip()
    if configured_key:
        return _normalize_secret_key(configured_key)

    key_path = _get_secret_key_path()
    if key_path.exists():
        return key_path.read_bytes().strip()

    key = Fernet.generate_key()
    key_path.write_bytes(key)
    if os.name != "nt":
        os.chmod(key_path, 0o600)
    return key


def _get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        _fernet_instance = Fernet(_get_or_create_secret_key())
    return _fernet_instance


def _is_encrypted_secret(value: Optional[str]) -> bool:
    return bool(value and value.startswith(SECRET_VALUE_PREFIX))


def _is_legacy_fernet_token(value: str) -> bool:
    """Check if a value looks like a bare Fernet token (no enc: prefix)."""
    return bool(value and value.startswith('gAAAAA') and len(value) > 40)


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value == "" or _is_encrypted_secret(value):
        return value
    # If it's already a legacy Fernet token, just add the prefix
    if _is_legacy_fernet_token(value):
        return f"{SECRET_VALUE_PREFIX}{value}"
    token = _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{SECRET_VALUE_PREFIX}{token}"


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value == "":
        return value
    if _is_encrypted_secret(value):
        token = value[len(SECRET_VALUE_PREFIX):].encode("ascii")
        try:
            return _get_fernet().decrypt(token).decode("utf-8")
        except Exception:
            logger.warning("Failed to decrypt stored secret (encryption key may have changed)")
            return None
    # Handle legacy Fernet tokens without the enc: prefix
    if _is_legacy_fernet_token(value):
        try:
            return _get_fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except Exception:
            pass
    return value
def get_data_dir() -> Path:
    """Get platform-appropriate user data directory for refchecker.
    
    If REFCHECKER_DATA_DIR environment variable is set, use that path.
    Otherwise, use platform-specific defaults:
    
    Windows: %LOCALAPPDATA%\refchecker
    macOS: ~/Library/Application Support/refchecker
    Linux: ~/.local/share/refchecker
    """
    # Check for environment variable override (useful for Docker)
    env_data_dir = os.environ.get("REFCHECKER_DATA_DIR")
    if env_data_dir:
        data_dir = Path(env_data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir
    
    if sys.platform == "win32":
        # Windows: use LOCALAPPDATA
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        # macOS: use Application Support
        base = Path.home() / "Library" / "Application Support"
    else:
        # Linux/Unix: use XDG_DATA_HOME or ~/.local/share
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    
    data_dir = base / "refchecker"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class Database:
    """Handles SQLite database operations for check history and LLM configs"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(get_data_dir() / "refchecker_history.db")
        self.db_path = db_path

    async def _get_connection(self):
        """Get a database connection with proper settings for concurrent access"""
        db = await aiosqlite.connect(self.db_path)
        # Enable WAL mode for better concurrent read/write
        await db.execute("PRAGMA journal_mode=WAL")
        # Set busy timeout to 5 seconds
        await db.execute("PRAGMA busy_timeout=5000")
        return db

    async def init_db(self):
        """Initialize database schema"""
        async with aiosqlite.connect(self.db_path) as db:
            # Enable WAL mode for better concurrent access
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            # Check history table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS check_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_title TEXT NOT NULL,
                    paper_source TEXT NOT NULL,
                    source_type TEXT DEFAULT 'url',
                    custom_label TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    total_refs INTEGER,
                    errors_count INTEGER,
                    warnings_count INTEGER,
                    suggestions_count INTEGER DEFAULT 0,
                    unverified_count INTEGER,
                    refs_with_errors INTEGER DEFAULT 0,
                    refs_with_warnings_only INTEGER DEFAULT 0,
                    refs_verified INTEGER DEFAULT 0,
                    hallucination_count INTEGER DEFAULT 0,
                    results_json TEXT,
                    llm_provider TEXT,
                    llm_model TEXT,
                    extraction_method TEXT,
                    status TEXT DEFAULT 'completed'
                )
            """)

            # LLM configurations table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS llm_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT,
                    endpoint TEXT,
                    api_key_encrypted TEXT,
                    is_default BOOLEAN DEFAULT 0,
                    user_id INTEGER REFERENCES users(id),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # App settings table (for Semantic Scholar key, etc.)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value_encrypted TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Verification cache table - stores results keyed by reference content hash
            await db.execute("""
                CREATE TABLE IF NOT EXISTS verification_cache (
                    cache_key TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Users table (for multi-user mode)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    email TEXT,
                    name TEXT,
                    avatar_url TEXT,
                    is_admin BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(provider, provider_id)
                )
            """)

            # OAuth accounts table (links OAuth identities to users)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS oauth_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    provider TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(provider, provider_id)
                )
            """)

            await self._ensure_columns(db)
            await self._migrate_plaintext_secrets(db)
            
            # Create index for batch queries
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_check_history_batch_id 
                ON check_history(batch_id)
            """)
            # Create index for per-user history queries
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_check_history_user_id 
                ON check_history(user_id)
            """)
            await db.commit()

    async def _ensure_columns(self, db: aiosqlite.Connection):
        """Ensure new columns exist for older databases."""
        async with db.execute("PRAGMA table_info(check_history)") as cursor:
            columns = {row[1] async for row in cursor}
        if "source_type" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN source_type TEXT DEFAULT 'url'")
        if "custom_label" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN custom_label TEXT")
        if "suggestions_count" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN suggestions_count INTEGER DEFAULT 0")
        if "refs_with_errors" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN refs_with_errors INTEGER DEFAULT 0")
        if "refs_with_warnings_only" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN refs_with_warnings_only INTEGER DEFAULT 0")
        if "refs_verified" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN refs_verified INTEGER DEFAULT 0")
        if "extraction_method" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN extraction_method TEXT")
        if "thumbnail_path" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN thumbnail_path TEXT")
        if "bibliography_source_path" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN bibliography_source_path TEXT")
        if "batch_id" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN batch_id TEXT")
        if "batch_label" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN batch_label TEXT")
        if "original_filename" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN original_filename TEXT")
        if "user_id" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN user_id INTEGER REFERENCES users(id)")
        if "hallucination_count" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN hallucination_count INTEGER DEFAULT 0")

        # Ensure user_id column in llm_configs
        async with db.execute("PRAGMA table_info(llm_configs)") as cursor:
            llm_columns = {row[1] async for row in cursor}
        if "user_id" not in llm_columns:
            await db.execute("ALTER TABLE llm_configs ADD COLUMN user_id INTEGER REFERENCES users(id)")
        if "api_key_encrypted" not in llm_columns:
            await db.execute("ALTER TABLE llm_configs ADD COLUMN api_key_encrypted TEXT")

        # Ensure is_admin column in users
        async with db.execute("PRAGMA table_info(users)") as cursor:
            user_columns = {row[1] async for row in cursor}
        if "is_admin" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")

    async def _migrate_plaintext_secrets(self, db: aiosqlite.Connection):
        """Encrypt any legacy plaintext values left in secret storage columns."""
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

        async with db.execute(
            "SELECT key, value_encrypted FROM app_settings WHERE value_encrypted IS NOT NULL AND value_encrypted != ''"
        ) as cursor:
            setting_rows = await cursor.fetchall()
        for key, value in setting_rows:
            encrypted = encrypt_secret(value)
            if encrypted != value:
                await db.execute(
                    "UPDATE app_settings SET value_encrypted = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                    (encrypted, key),
                )

    async def save_check(self,
                         paper_title: str,
                         paper_source: str,
                         source_type: str,
                         total_refs: int,
                         errors_count: int,
                         warnings_count: int,
                         suggestions_count: int,
                         unverified_count: int,
                         refs_with_errors: int,
                         refs_with_warnings_only: int,
                         refs_verified: int,
                         results: List[Dict[str, Any]],
                         llm_provider: Optional[str] = None,
                         llm_model: Optional[str] = None,
                         extraction_method: Optional[str] = None,
                         hallucination_count: int = 0) -> int:
        """Save a check result to database"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO check_history
                (paper_title, paper_source, source_type, total_refs, errors_count, warnings_count,
                 suggestions_count, unverified_count, refs_with_errors, refs_with_warnings_only,
                 refs_verified, hallucination_count, results_json, llm_provider, llm_model, extraction_method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                paper_title,
                paper_source,
                source_type,
                total_refs,
                errors_count,
                warnings_count,
                suggestions_count,
                unverified_count,
                refs_with_errors,
                refs_with_warnings_only,
                refs_verified,
                hallucination_count,
                json.dumps(results),
                llm_provider,
                llm_model,
                extraction_method
            ))
            await db.commit()
            return cursor.lastrowid

    async def get_history(self, limit: int = 50, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get recent check history, optionally filtered by user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            if user_id is not None:
                query = """
                    SELECT id, paper_title, paper_source, custom_label, timestamp,
                           total_refs, errors_count, warnings_count, suggestions_count, unverified_count,
                           hallucination_count,
                           refs_with_errors, refs_with_warnings_only, refs_verified,
                           llm_provider, llm_model, status, source_type, batch_id, batch_label,
                           original_filename
                    FROM check_history
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                params = (user_id, limit)
            else:
                query = """
                    SELECT id, paper_title, paper_source, custom_label, timestamp,
                           total_refs, errors_count, warnings_count, suggestions_count, unverified_count,
                           hallucination_count,
                           refs_with_errors, refs_with_warnings_only, refs_verified,
                           llm_provider, llm_model, status, source_type, batch_id, batch_label,
                           original_filename
                    FROM check_history
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                params = (limit,)
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_check_by_id(self, check_id: int, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get specific check result by ID, optionally enforcing user ownership."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            if user_id is not None:
                query = "SELECT * FROM check_history WHERE id = ? AND user_id = ?"
                params = (check_id, user_id)
            else:
                query = "SELECT * FROM check_history WHERE id = ?"
                params = (check_id,)
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                if row:
                    result = dict(row)
                    # Parse JSON results
                    if result['results_json']:
                        result['results'] = json.loads(result['results_json'])
                    return result
                return None

    async def delete_check(self, check_id: int, user_id: Optional[int] = None) -> bool:
        """Delete a check from history, optionally enforcing user ownership."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            if user_id is not None:
                cursor = await db.execute("DELETE FROM check_history WHERE id = ? AND user_id = ?", (check_id, user_id))
            else:
                cursor = await db.execute("DELETE FROM check_history WHERE id = ?", (check_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def update_check_label(self, check_id: int, label: str, user_id: Optional[int] = None) -> bool:
        """Update the custom label for a check, optionally enforcing user ownership."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            if user_id is not None:
                cursor = await db.execute(
                    "UPDATE check_history SET custom_label = ? WHERE id = ? AND user_id = ?",
                    (label, check_id, user_id)
                )
            else:
                cursor = await db.execute(
                    "UPDATE check_history SET custom_label = ? WHERE id = ?",
                    (label, check_id)
                )
            await db.commit()
            return cursor.rowcount > 0

    async def update_check_title(self, check_id: int, paper_title: str) -> bool:
        """Update the paper title for a check"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                "UPDATE check_history SET paper_title = ? WHERE id = ?",
                (paper_title, check_id)
            )
            await db.commit()
            return True

    async def create_pending_check(self,
                                    paper_title: str,
                                    paper_source: str,
                                    source_type: str,
                                    llm_provider: Optional[str] = None,
                                    llm_model: Optional[str] = None,
                                    batch_id: Optional[str] = None,
                                    batch_label: Optional[str] = None,
                                    original_filename: Optional[str] = None,
                                    user_id: Optional[int] = None) -> int:
        """Create a pending check entry before verification starts"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO check_history
                (paper_title, paper_source, source_type, total_refs, errors_count, warnings_count,
                 suggestions_count, unverified_count, results_json, llm_provider, llm_model, status,
                 batch_id, batch_label, original_filename, user_id)
                VALUES (?, ?, ?, 0, 0, 0, 0, 0, '[]', ?, ?, 'in_progress', ?, ?, ?, ?)
            """, (
                paper_title,
                paper_source,
                source_type,
                llm_provider,
                llm_model,
                batch_id,
                batch_label,
                original_filename,
                user_id
            ))
            await db.commit()
            return cursor.lastrowid

    async def update_check_results(self,
                                    check_id: int,
                                    paper_title: Optional[str],
                                    total_refs: int,
                                    errors_count: int,
                                    warnings_count: int,
                                    suggestions_count: int,
                                    unverified_count: int,
                                    refs_with_errors: int,
                                    refs_with_warnings_only: int,
                                    refs_verified: int,
                                    results: List[Dict[str, Any]],
                                    status: str = 'completed',
                                    extraction_method: Optional[str] = None,
                                    hallucination_count: int = 0) -> bool:
        """Update a check with its results. If paper_title is None, don't update it."""
        async with aiosqlite.connect(self.db_path) as db:
            if paper_title is not None:
                await db.execute("""
                    UPDATE check_history
                    SET paper_title = ?, total_refs = ?, errors_count = ?, warnings_count = ?,
                        suggestions_count = ?, unverified_count = ?, hallucination_count = ?,
                        refs_with_errors = ?, refs_with_warnings_only = ?, refs_verified = ?,
                        results_json = ?, status = ?, extraction_method = ?
                    WHERE id = ?
                """, (
                    paper_title,
                    total_refs,
                    errors_count,
                    warnings_count,
                    suggestions_count,
                    unverified_count,
                    hallucination_count,
                    refs_with_errors,
                    refs_with_warnings_only,
                    refs_verified,
                    json.dumps(results),
                    status,
                    extraction_method,
                    check_id
                ))
            else:
                # Don't update paper_title if None
                await db.execute("""
                    UPDATE check_history
                    SET total_refs = ?, errors_count = ?, warnings_count = ?,
                        suggestions_count = ?, unverified_count = ?, hallucination_count = ?,
                        refs_with_errors = ?, refs_with_warnings_only = ?, refs_verified = ?,
                        results_json = ?, status = ?, extraction_method = ?
                    WHERE id = ?
                """, (
                    total_refs,
                    errors_count,
                    warnings_count,
                    suggestions_count,
                    unverified_count,
                    hallucination_count,
                    refs_with_errors,
                    refs_with_warnings_only,
                    refs_verified,
                    json.dumps(results),
                    status,
                    extraction_method,
                    check_id
                ))
            await db.commit()
            return True

    async def update_check_progress(self,
                                     check_id: int,
                                     total_refs: int,
                                     errors_count: int,
                                     warnings_count: int,
                                     suggestions_count: int,
                                     unverified_count: int,
                                     hallucination_count: int = 0,
                                     refs_with_errors: int = 0,
                                     refs_with_warnings_only: int = 0,
                                     refs_verified: int = 0,
                                     results: List[Dict[str, Any]] = None) -> bool:
        """Incrementally update a check's results as references are verified.
        
        This is called after each reference is checked to persist progress,
        so interrupted checks retain their partial results.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("""
                UPDATE check_history
                SET total_refs = ?, errors_count = ?, warnings_count = ?,
                    suggestions_count = ?, unverified_count = ?, hallucination_count = ?,
                    refs_with_errors = ?,
                    refs_with_warnings_only = ?, refs_verified = ?, results_json = ?
                WHERE id = ?
            """, (
                total_refs,
                errors_count,
                warnings_count,
                suggestions_count,
                unverified_count,
                hallucination_count,
                refs_with_errors,
                refs_with_warnings_only,
                refs_verified,
                json.dumps(results or []),
                check_id
            ))
            await db.commit()
            return True

    async def update_check_status(self, check_id: int, status: str) -> bool:
        """Update just the status of a check"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE check_history SET status = ? WHERE id = ?",
                (status, check_id)
            )
            await db.commit()
            return True

    async def update_check_extraction_method(self, check_id: int, extraction_method: str) -> bool:
        """Update the extraction method for a check"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE check_history SET extraction_method = ? WHERE id = ?",
                (extraction_method, check_id)
            )
            await db.commit()
            return True

    async def update_check_thumbnail(self, check_id: int, thumbnail_path: str) -> bool:
        """Update the thumbnail path for a check"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE check_history SET thumbnail_path = ? WHERE id = ?",
                (thumbnail_path, check_id)
            )
            await db.commit()
            return True

    async def update_check_bibliography_source(self, check_id: int, bibliography_source_path: str) -> bool:
        """Update the bibliography source file path for a check"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE check_history SET bibliography_source_path = ? WHERE id = ?",
                (bibliography_source_path, check_id)
            )
            await db.commit()
            return True

    async def cancel_stale_in_progress(self) -> int:
        """Mark any in-progress checks as cancelled (e.g., after a server restart)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE check_history SET status = 'cancelled' WHERE status = 'in_progress'"
            )
            await db.commit()
            return cursor.rowcount

    # LLM Configuration methods

    async def get_llm_configs(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all LLM configurations with has_key flag, optionally filtered by user."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if user_id is not None:
                query = """
                    SELECT id, name, provider, model, endpoint, is_default, created_at,
                           (api_key_encrypted IS NOT NULL AND api_key_encrypted != '') AS has_key
                    FROM llm_configs
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                """
                params = (user_id,)
            else:
                query = """
                    SELECT id, name, provider, model, endpoint, is_default, created_at,
                           (api_key_encrypted IS NOT NULL AND api_key_encrypted != '') AS has_key
                    FROM llm_configs
                    ORDER BY created_at DESC
                """
                params = ()
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [{**dict(row), 'has_key': bool(row['has_key'])} for row in rows]

    async def get_llm_config_by_id(self, config_id: int, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get a specific LLM config by ID, optionally checking ownership."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if user_id is not None:
                query = "SELECT * FROM llm_configs WHERE id = ? AND user_id = ?"
                params = (config_id, user_id)
            else:
                query = "SELECT * FROM llm_configs WHERE id = ?"
                params = (config_id,)
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                if row:
                    result = dict(row)
                    # Expose stored key as api_key for use during checks
                    result['api_key'] = decrypt_secret(result.pop('api_key_encrypted', None))
                    return result
                return None

    async def create_llm_config(self,
                                 name: str,
                                 provider: str,
                                 model: Optional[str] = None,
                                 endpoint: Optional[str] = None,
                                 api_key: Optional[str] = None,
                                 user_id: Optional[int] = None) -> int:
        """Create a new LLM configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO llm_configs (name, provider, model, endpoint, api_key_encrypted, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, provider, model, endpoint, encrypt_secret(api_key), user_id))
            await db.commit()
            return cursor.lastrowid

    async def update_llm_config(self,
                                 config_id: int,
                                 name: Optional[str] = None,
                                 provider: Optional[str] = None,
                                 model: Optional[str] = None,
                                 endpoint: Optional[str] = None,
                                 api_key: Optional[str] = None,
                                 user_id: Optional[int] = None) -> bool:
        """Update an existing LLM configuration"""
        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if provider is not None:
            updates.append("provider = ?")
            params.append(provider)
        if model is not None:
            updates.append("model = ?")
            params.append(model)
        if endpoint is not None:
            updates.append("endpoint = ?")
            params.append(endpoint)
        if api_key is not None:
            updates.append("api_key_encrypted = ?")
            params.append(encrypt_secret(api_key))

        if not updates:
            return False

        params.append(config_id)
        where_clause = "id = ?"
        if user_id is not None:
            where_clause += " AND user_id = ?"
            params.append(user_id)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE llm_configs SET {', '.join(updates)} WHERE {where_clause}",
                params
            )
            await db.commit()
            return cursor.rowcount > 0

    async def delete_llm_config(self, config_id: int, user_id: Optional[int] = None) -> bool:
        """Delete an LLM configuration, optionally enforcing user ownership."""
        async with aiosqlite.connect(self.db_path) as db:
            if user_id is not None:
                cursor = await db.execute("DELETE FROM llm_configs WHERE id = ? AND user_id = ?", (config_id, user_id))
            else:
                cursor = await db.execute("DELETE FROM llm_configs WHERE id = ?", (config_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def set_default_llm_config(self, config_id: int, user_id: Optional[int] = None) -> bool:
        """Set an LLM config as the default (unsets others for the same user)"""
        async with aiosqlite.connect(self.db_path) as db:
            # Unset all defaults for this user (or globally if no user)
            if user_id is not None:
                await db.execute("UPDATE llm_configs SET is_default = 0 WHERE user_id = ?", (user_id,))
            else:
                await db.execute("UPDATE llm_configs SET is_default = 0")
            # Set the new default
            if user_id is not None:
                cursor = await db.execute(
                    "UPDATE llm_configs SET is_default = 1 WHERE id = ? AND user_id = ?",
                    (config_id, user_id)
                )
            else:
                cursor = await db.execute(
                    "UPDATE llm_configs SET is_default = 1 WHERE id = ?",
                    (config_id,)
                )
            await db.commit()
            return cursor.rowcount > 0

    async def get_default_llm_config(self, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get the default LLM configuration, optionally filtered by user."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if user_id is not None:
                query = "SELECT * FROM llm_configs WHERE is_default = 1 AND user_id = ?"
                params = (user_id,)
            else:
                query = "SELECT * FROM llm_configs WHERE is_default = 1"
                params = ()
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                if row:
                    result = dict(row)
                    result['api_key'] = decrypt_secret(result.pop('api_key_encrypted', None))
                    return result
                return None

    # App Settings methods (for Semantic Scholar key, etc.)

    # User management methods

    async def create_or_update_user(self,
                                     provider: str,
                                     provider_id: str,
                                     email: Optional[str] = None,
                                     name: Optional[str] = None,
                                     avatar_url: Optional[str] = None) -> int:
        """Create a new user or update an existing one. Returns the user's internal ID.

        Also upserts the matching row in ``oauth_accounts``.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Look up via oauth_accounts first (new schema), then fall back to
            # the legacy UNIQUE(provider, provider_id) on the users table.
            async with db.execute(
                "SELECT user_id FROM oauth_accounts WHERE provider = ? AND provider_id = ?",
                (provider, provider_id)
            ) as cursor:
                oa_row = await cursor.fetchone()

            if oa_row:
                user_id = oa_row[0]
                await db.execute("""
                    UPDATE users SET email = ?, name = ?, avatar_url = ?
                    WHERE id = ?
                """, (email, name, avatar_url, user_id))
            else:
                # Try the legacy users unique constraint (existing rows pre-migration)
                async with db.execute(
                    "SELECT id FROM users WHERE provider = ? AND provider_id = ?",
                    (provider, provider_id)
                ) as cursor:
                    legacy_row = await cursor.fetchone()

                if legacy_row:
                    user_id = legacy_row[0]
                    await db.execute("""
                        UPDATE users SET email = ?, name = ?, avatar_url = ?
                        WHERE id = ?
                    """, (email, name, avatar_url, user_id))
                else:
                    # Determine is_admin: first-ever user, or email in ADMIN_EMAILS
                    is_admin = await self._should_be_admin(db, email)
                    cursor = await db.execute("""
                        INSERT INTO users (provider, provider_id, email, name, avatar_url, is_admin)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (provider, provider_id, email, name, avatar_url, 1 if is_admin else 0))
                    user_id = cursor.lastrowid

            # Upsert oauth_accounts record
            await db.execute("""
                INSERT INTO oauth_accounts (user_id, provider, provider_id)
                VALUES (?, ?, ?)
                ON CONFLICT(provider, provider_id) DO UPDATE SET user_id = excluded.user_id
            """, (user_id, provider, provider_id))
            await db.commit()
            return user_id

    async def _should_be_admin(self, db: aiosqlite.Connection, email: Optional[str]) -> bool:
        """Return True if the new user should be granted admin rights.

        A user is an admin if:
        1. They are the very first user in the database, OR
        2. Their email is listed in the ADMIN_EMAILS env var
           (comma-separated, case-insensitive).
        """
        import os
        # Check ADMIN_EMAILS
        admin_emails_env = os.environ.get("ADMIN_EMAILS", "")
        if email and admin_emails_env:
            admin_list = [e.strip().lower() for e in admin_emails_env.split(",") if e.strip()]
            if email.lower() in admin_list:
                return True
        # First user heuristic: no existing users yet
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            user_count = row[0] if row else 0
        return user_count == 0

    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get a user by their internal ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, provider, provider_id, email, name, avatar_url, is_admin, created_at FROM users WHERE id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_user_by_provider(self, provider: str, provider_id: str) -> Optional[Dict[str, Any]]:
        """Get a user by OAuth provider and provider-specific ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, provider, provider_id, email, name, avatar_url, is_admin, created_at FROM users WHERE provider = ? AND provider_id = ?",
                (provider, provider_id)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None


    async def get_setting(self, key: str, decrypt: bool = True) -> Optional[str]:
        """Get an app setting value."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT value_encrypted FROM app_settings WHERE key = ?",
                (key,)
            ) as cursor:
                row = await cursor.fetchone()
                if row and row['value_encrypted']:
                    value = row['value_encrypted']
                    return decrypt_secret(value) if decrypt else value
                return None

    async def set_setting(self, key: str, value: str) -> bool:
        """Set an app setting value."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO app_settings (key, value_encrypted, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value_encrypted = excluded.value_encrypted,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, encrypt_secret(value)))
            await db.commit()
            return True

    async def delete_setting(self, key: str) -> bool:
        """Delete an app setting"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM app_settings WHERE key = ?", (key,))
            await db.commit()
            return True

    async def has_setting(self, key: str) -> bool:
        """Check if an app setting exists"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM app_settings WHERE key = ? AND value_encrypted IS NOT NULL",
                (key,)
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None

    # Verification cache methods

    def _compute_reference_cache_key(self, reference: Dict[str, Any]) -> str:
        """
        Compute a cache key from reference data.
        
        Key is based on: title, authors (sorted), year, venue, url
        All normalized to lowercase and stripped.
        """
        import hashlib
        
        title = (reference.get('title') or '').strip().lower()
        authors = reference.get('authors') or []
        # Normalize authors: lowercase, stripped, sorted for consistency
        authors_normalized = sorted([a.strip().lower() for a in authors if a])
        authors_str = '|'.join(authors_normalized)
        year = str(reference.get('year') or '')
        venue = (reference.get('venue') or '').strip().lower()
        url = (reference.get('url') or '').strip().lower()
        
        # Create a deterministic string from reference fields
        cache_input = f"title:{title}|authors:{authors_str}|year:{year}|venue:{venue}|url:{url}"
        
        # Hash it for a fixed-length key
        return hashlib.sha256(cache_input.encode('utf-8')).hexdigest()

    async def get_cached_verification(self, reference: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get cached verification result for a reference.
        
        Returns the cached result if found, None otherwise.
        """
        import time
        import tempfile
        from pathlib import Path
        
        debug_file = Path(tempfile.gettempdir()) / "refchecker_debug.log"
        
        start = time.time()
        cache_key = self._compute_reference_cache_key(reference)
        key_time = time.time() - start
        
        connect_start = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            connect_time = time.time() - connect_start
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            
            query_start = time.time()
            async with db.execute(
                "SELECT result_json FROM verification_cache WHERE cache_key = ?",
                (cache_key,)
            ) as cursor:
                row = await cursor.fetchone()
                query_time = time.time() - query_start
                
                total_time = time.time() - start
                if total_time > 0.05:
                    with open(debug_file, "a") as f:
                        f.write(f"[TIMING] Cache lookup: total={total_time:.3f}s, key={key_time:.3f}s, connect={connect_time:.3f}s, query={query_time:.3f}s\n")
                
                if row and row['result_json']:
                    try:
                        return json.loads(row['result_json'])
                    except json.JSONDecodeError:
                        return None
                return None

    async def store_cached_verification(self, reference: Dict[str, Any], result: Dict[str, Any]) -> bool:
        """
        Store a verification result in the cache.
        
        Only caches successful verifications (not errors/timeouts).
        """
        # Don't cache error results or timeouts - only cache verified/warning/suggestion/unverified
        status = result.get('status', '').lower()
        if status in ('error', 'cancelled', 'timeout', 'checking', 'pending'):
            return False
        
        cache_key = self._compute_reference_cache_key(reference)
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("""
                INSERT INTO verification_cache (cache_key, result_json, created_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(cache_key) DO UPDATE SET
                    result_json = excluded.result_json,
                    created_at = CURRENT_TIMESTAMP
            """, (cache_key, json.dumps(result)))
            await db.commit()
            return True

    async def clear_verification_cache(self) -> int:
        """Clear all cached verification results. Returns count of deleted entries."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM verification_cache")
            await db.commit()
            return cursor.rowcount

    # Batch operations

    async def get_batch_checks(self, batch_id: str, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all checks belonging to a batch, optionally filtered by user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            query = """
                SELECT id, paper_title, paper_source, custom_label, timestamp,
                       total_refs, errors_count, warnings_count, suggestions_count, unverified_count,
                       refs_with_errors, refs_with_warnings_only, refs_verified,
                       llm_provider, llm_model, status, source_type, batch_id, batch_label
                FROM check_history
                WHERE batch_id = ?
            """
            params: tuple[Any, ...]
            if user_id is not None:
                query += " AND user_id = ?"
                params = (batch_id, user_id)
            else:
                params = (batch_id,)
            query += " ORDER BY timestamp ASC"
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_batch_summary(self, batch_id: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get aggregated summary for a batch, optionally filtered by user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            query = """
                SELECT 
                    batch_id,
                    batch_label,
                    COUNT(*) as total_papers,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_papers,
                    SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_papers,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_papers,
                    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled_papers,
                    SUM(total_refs) as total_refs,
                    SUM(errors_count) as total_errors,
                    SUM(warnings_count) as total_warnings,
                    SUM(suggestions_count) as total_suggestions,
                    SUM(unverified_count) as total_unverified,
                    MIN(timestamp) as started_at
                FROM check_history
                WHERE batch_id = ?
            """
            params: tuple[Any, ...]
            if user_id is not None:
                query += " AND user_id = ?"
                params = (batch_id, user_id)
            else:
                params = (batch_id,)
            query += " GROUP BY batch_id"
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None

    async def cancel_batch(self, batch_id: str, user_id: Optional[int] = None) -> int:
        """Cancel all in-progress checks in a batch. Returns count of cancelled checks."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            if user_id is not None:
                cursor = await db.execute("""
                    UPDATE check_history 
                    SET status = 'cancelled' 
                    WHERE batch_id = ? AND user_id = ? AND status = 'in_progress'
                """, (batch_id, user_id))
            else:
                cursor = await db.execute("""
                    UPDATE check_history 
                    SET status = 'cancelled' 
                    WHERE batch_id = ? AND status = 'in_progress'
                """, (batch_id,))
            await db.commit()
            return cursor.rowcount

    async def delete_batch(self, batch_id: str, user_id: Optional[int] = None) -> int:
        """Delete all checks in a batch. Returns count of deleted checks."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            if user_id is not None:
                cursor = await db.execute(
                    "DELETE FROM check_history WHERE batch_id = ? AND user_id = ?",
                    (batch_id, user_id)
                )
            else:
                cursor = await db.execute(
                    "DELETE FROM check_history WHERE batch_id = ?",
                    (batch_id,)
                )
            await db.commit()
            return cursor.rowcount

    async def update_batch_label(self, batch_id: str, label: str, user_id: Optional[int] = None) -> bool:
        """Update the label for all checks in a batch, optionally enforcing user ownership."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            if user_id is not None:
                cursor = await db.execute(
                    "UPDATE check_history SET batch_label = ? WHERE batch_id = ? AND user_id = ?",
                    (label, batch_id, user_id)
                )
            else:
                cursor = await db.execute(
                    "UPDATE check_history SET batch_label = ? WHERE batch_id = ?",
                    (label, batch_id)
                )
            await db.commit()
            return cursor.rowcount > 0


# Global database instance
db = Database()
