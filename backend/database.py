"""
Database module for storing check history and LLM configurations
"""
import aiosqlite
import json
import os
import sys
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path
from cryptography.fernet import Fernet


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


def get_encryption_key() -> bytes:
    """Get or create encryption key for API keys"""
    key_file = get_data_dir() / ".encryption_key"
    if key_file.exists():
        return key_file.read_bytes()
    else:
        key = Fernet.generate_key()
        key_file.write_bytes(key)
        return key


class Database:
    """Handles SQLite database operations for check history and LLM configs"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(get_data_dir() / "refchecker_history.db")
        self.db_path = db_path
        self._fernet = Fernet(get_encryption_key())

    def _encrypt(self, value: str) -> str:
        """Encrypt a string value"""
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> str:
        """Decrypt a string value"""
        return self._fernet.decrypt(value.encode()).decode()

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
                    api_key_encrypted TEXT,
                    endpoint TEXT,
                    is_default BOOLEAN DEFAULT 0,
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

            await self._ensure_columns(db)
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
                         extraction_method: Optional[str] = None) -> int:
        """Save a check result to database"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO check_history
                (paper_title, paper_source, source_type, total_refs, errors_count, warnings_count,
                 suggestions_count, unverified_count, refs_with_errors, refs_with_warnings_only,
                 refs_verified, results_json, llm_provider, llm_model, extraction_method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(results),
                llm_provider,
                llm_model,
                extraction_method
            ))
            await db.commit()
            return cursor.lastrowid

    async def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent check history"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT id, paper_title, paper_source, custom_label, timestamp,
                       total_refs, errors_count, warnings_count, suggestions_count, unverified_count,
                       refs_with_errors, refs_with_warnings_only, refs_verified,
                       llm_provider, llm_model, status, source_type
                FROM check_history
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_check_by_id(self, check_id: int) -> Optional[Dict[str, Any]]:
        """Get specific check result by ID"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM check_history WHERE id = ?
            """, (check_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    result = dict(row)
                    # Parse JSON results
                    if result['results_json']:
                        result['results'] = json.loads(result['results_json'])
                    return result
                return None

    async def delete_check(self, check_id: int) -> bool:
        """Delete a check from history"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("DELETE FROM check_history WHERE id = ?", (check_id,))
            await db.commit()
            return True

    async def update_check_label(self, check_id: int, label: str) -> bool:
        """Update the custom label for a check"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                "UPDATE check_history SET custom_label = ? WHERE id = ?",
                (label, check_id)
            )
            await db.commit()
            return True

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
                                    llm_model: Optional[str] = None) -> int:
        """Create a pending check entry before verification starts"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO check_history
                (paper_title, paper_source, source_type, total_refs, errors_count, warnings_count,
                 suggestions_count, unverified_count, results_json, llm_provider, llm_model, status)
                VALUES (?, ?, ?, 0, 0, 0, 0, 0, '[]', ?, ?, 'in_progress')
            """, (
                paper_title,
                paper_source,
                source_type,
                llm_provider,
                llm_model
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
                                    extraction_method: Optional[str] = None) -> bool:
        """Update a check with its results. If paper_title is None, don't update it."""
        async with aiosqlite.connect(self.db_path) as db:
            if paper_title is not None:
                await db.execute("""
                    UPDATE check_history
                    SET paper_title = ?, total_refs = ?, errors_count = ?, warnings_count = ?,
                        suggestions_count = ?, unverified_count = ?, refs_with_errors = ?,
                        refs_with_warnings_only = ?, refs_verified = ?, results_json = ?, status = ?,
                        extraction_method = ?
                    WHERE id = ?
                """, (
                    paper_title,
                    total_refs,
                    errors_count,
                    warnings_count,
                    suggestions_count,
                    unverified_count,
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
                        suggestions_count = ?, unverified_count = ?, refs_with_errors = ?,
                        refs_with_warnings_only = ?, refs_verified = ?, results_json = ?, status = ?,
                        extraction_method = ?
                    WHERE id = ?
                """, (
                    total_refs,
                    errors_count,
                    warnings_count,
                    suggestions_count,
                    unverified_count,
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
                                     refs_with_errors: int,
                                     refs_with_warnings_only: int,
                                     refs_verified: int,
                                     results: List[Dict[str, Any]]) -> bool:
        """Incrementally update a check's results as references are verified.
        
        This is called after each reference is checked to persist progress,
        so interrupted checks retain their partial results.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("""
                UPDATE check_history
                SET total_refs = ?, errors_count = ?, warnings_count = ?,
                    suggestions_count = ?, unverified_count = ?, refs_with_errors = ?,
                    refs_with_warnings_only = ?, refs_verified = ?, results_json = ?
                WHERE id = ?
            """, (
                total_refs,
                errors_count,
                warnings_count,
                suggestions_count,
                unverified_count,
                refs_with_errors,
                refs_with_warnings_only,
                refs_verified,
                json.dumps(results),
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

    async def get_llm_configs(self) -> List[Dict[str, Any]]:
        """Get all LLM configurations (API keys redacted)"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT id, name, provider, model, endpoint, is_default, created_at
                FROM llm_configs
                ORDER BY created_at DESC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_llm_config_by_id(self, config_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific LLM config by ID (includes decrypted API key)"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM llm_configs WHERE id = ?
            """, (config_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    result = dict(row)
                    # Decrypt API key if present
                    if result.get('api_key_encrypted'):
                        try:
                            result['api_key'] = self._decrypt(result['api_key_encrypted'])
                        except Exception:
                            result['api_key'] = None
                    del result['api_key_encrypted']
                    return result
                return None

    async def create_llm_config(self,
                                 name: str,
                                 provider: str,
                                 model: Optional[str] = None,
                                 api_key: Optional[str] = None,
                                 endpoint: Optional[str] = None) -> int:
        """Create a new LLM configuration"""
        encrypted_key = self._encrypt(api_key) if api_key else None

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO llm_configs (name, provider, model, api_key_encrypted, endpoint)
                VALUES (?, ?, ?, ?, ?)
            """, (name, provider, model, encrypted_key, endpoint))
            await db.commit()
            return cursor.lastrowid

    async def update_llm_config(self,
                                 config_id: int,
                                 name: Optional[str] = None,
                                 provider: Optional[str] = None,
                                 model: Optional[str] = None,
                                 api_key: Optional[str] = None,
                                 endpoint: Optional[str] = None) -> bool:
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
        if api_key is not None:
            updates.append("api_key_encrypted = ?")
            params.append(self._encrypt(api_key))
        if endpoint is not None:
            updates.append("endpoint = ?")
            params.append(endpoint)

        if not updates:
            return False

        params.append(config_id)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE llm_configs SET {', '.join(updates)} WHERE id = ?",
                params
            )
            await db.commit()
            return True

    async def delete_llm_config(self, config_id: int) -> bool:
        """Delete an LLM configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM llm_configs WHERE id = ?", (config_id,))
            await db.commit()
            return True

    async def set_default_llm_config(self, config_id: int) -> bool:
        """Set an LLM config as the default (unsets others)"""
        async with aiosqlite.connect(self.db_path) as db:
            # Unset all defaults
            await db.execute("UPDATE llm_configs SET is_default = 0")
            # Set the new default
            await db.execute(
                "UPDATE llm_configs SET is_default = 1 WHERE id = ?",
                (config_id,)
            )
            await db.commit()
            return True

    async def get_default_llm_config(self) -> Optional[Dict[str, Any]]:
        """Get the default LLM configuration (with decrypted API key)"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM llm_configs WHERE is_default = 1
            """) as cursor:
                row = await cursor.fetchone()
                if row:
                    result = dict(row)
                    if result.get('api_key_encrypted'):
                        try:
                            result['api_key'] = self._decrypt(result['api_key_encrypted'])
                        except Exception:
                            result['api_key'] = None
                    if 'api_key_encrypted' in result:
                        del result['api_key_encrypted']
                    return result
                return None

    # App Settings methods (for Semantic Scholar key, etc.)

    async def get_setting(self, key: str, decrypt: bool = True) -> Optional[str]:
        """Get an app setting value (optionally decrypted)"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT value_encrypted FROM app_settings WHERE key = ?",
                (key,)
            ) as cursor:
                row = await cursor.fetchone()
                if row and row['value_encrypted']:
                    if decrypt:
                        try:
                            return self._decrypt(row['value_encrypted'])
                        except Exception:
                            return None
                    return row['value_encrypted']
                return None

    async def set_setting(self, key: str, value: str) -> bool:
        """Set an app setting value (encrypted)"""
        encrypted = self._encrypt(value) if value else None
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO app_settings (key, value_encrypted, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value_encrypted = excluded.value_encrypted,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, encrypted))
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
        cache_key = self._compute_reference_cache_key(reference)
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT result_json FROM verification_cache WHERE cache_key = ?",
                (cache_key,)
            ) as cursor:
                row = await cursor.fetchone()
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


# Global database instance
db = Database()
