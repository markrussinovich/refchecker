"""
Database module for storing check history and LLM configurations
"""
import aiosqlite
import base64
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

# Module logger. Several call sites in this file (Seen-Refs backstop,
# fernet decrypt warnings, etc.) reference `logger` directly; without
# this definition any check that hits those paths crashes with
# `NameError: name 'logger' is not defined` — surfaced especially on
# LLM-extracted runs where the Seen-Refs backstop fires.
logger = logging.getLogger(__name__)


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


def get_logs_dir() -> Path:
    """Get directory for refchecker log files.

    Honors REFCHECKER_LOG_DIR for installs that want logs on a different
    volume than the SQLite DB / uploads (e.g. background database-refresh
    logs that can grow into the tens of gigabytes).  Falls back to
    ``get_data_dir() / "logs"``.
    """
    env_log_dir = os.environ.get("REFCHECKER_LOG_DIR")
    if env_log_dir:
        log_dir = Path(env_log_dir)
    else:
        log_dir = get_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


_FINAL_REFERENCE_STATUSES = {"error", "warning", "suggestion", "unverified", "verified", "hallucination"}


def _normalize_for_metadata_comparison(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _normalize_author_tokens(value: Any) -> List[str]:
    return [token for token in _normalize_for_metadata_comparison(value).split(" ") if token]


def _parse_found_authors(value: Any) -> List[str]:
    text = str(value or "").strip()
    if not text or text.upper() == "NONE":
        return []
    separator = ";" if ";" in text else ","
    return [author.strip() for author in text.split(separator) if author.strip()]


def _author_matches(cited_author: Any, found_author: Any) -> bool:
    cited_tokens = _normalize_author_tokens(cited_author)
    found_tokens = _normalize_author_tokens(found_author)
    if not cited_tokens or not found_tokens:
        return False

    cited_last = cited_tokens[-1]
    found_last = found_tokens[-1]
    if cited_last != found_last:
        return False

    cited = " ".join(cited_tokens)
    found = " ".join(found_tokens)
    if cited == found or cited in found or found in cited:
        return True

    cited_given_tokens = [token for token in cited_tokens[:-1] if len(token) > 1]
    found_given_tokens = {token for token in found_tokens[:-1] if len(token) > 1}
    return any(token in found_given_tokens for token in cited_given_tokens)


def _authors_substantially_match(cited_authors: Any, found_authors_text: Any) -> bool:
    cited = [author for author in (cited_authors or []) if author]
    found = _parse_found_authors(found_authors_text)
    if not cited or not found:
        return False

    matched_count = sum(
        1 for cited_author in cited
        if any(_author_matches(cited_author, found_author) for found_author in found)
    )
    required_matches = len(cited) - 1 if len(cited) >= 3 else len(cited)
    return matched_count >= required_matches


def _llm_found_metadata_matches_citation(ref: Dict[str, Any]) -> bool:
    assessment = ref.get("hallucination_assessment") or {}
    return (
        assessment.get("verdict") == "LIKELY"
        and bool(assessment.get("link"))
        and _normalize_for_metadata_comparison(assessment.get("found_title"))
            == _normalize_for_metadata_comparison(ref.get("title"))
        and _authors_substantially_match(ref.get("authors"), assessment.get("found_authors"))
        and (not ref.get("year") or str(ref.get("year")) in str(assessment.get("found_year") or ""))
    )


def _get_effective_reference_status(ref: Dict[str, Any], is_complete: bool) -> str:
    base_status = str(ref.get("status") or "").strip().lower()
    llm_match = _llm_found_metadata_matches_citation(ref)

    if ref.get("hallucination_check_pending") and not ref.get("hallucination_assessment"):
        return "checking"
    if base_status == "unverified" and not ref.get("hallucination_assessment") and not is_complete:
        return "checking"
    if base_status == "hallucination" and llm_match:
        return "verified"
    if base_status == "hallucination":
        return "hallucination"
    if llm_match:
        return "suggestion" if ref.get("suggestions") else "verified"

    errors = ref.get("errors") or []
    warnings = ref.get("warnings") or []
    suggestions = ref.get("suggestions") or []
    has_errors = any(str((error or {}).get("error_type") or "").lower() != "unverified" for error in errors)
    if has_errors:
        return "error"
    if warnings:
        return "warning"
    if suggestions:
        return "suggestion"
    if base_status in {"error", "warning", "suggestion"}:
        return "verified"
    if base_status in _FINAL_REFERENCE_STATUSES:
        return base_status
    if base_status in {"pending", "checking", "in_progress", "queued", "processing", "started"}:
        return "unchecked" if is_complete else ("pending" if base_status == "pending" else "checking")
    return "verified"


def _compute_reference_buckets_from_results(
    results: List[Dict[str, Any]],
    is_complete: bool,
    stored_total_refs: Optional[int] = None,
) -> Dict[str, int]:
    """Compute summary counters from stored check results.

    This mirrors ``web-ui/src/utils/referenceStatus.js`` so history cards and
    the selected-check Summary render the same numbers even if persisted
    aggregate columns are stale from an older run.

    ``processed_refs`` is the count of distinct, non-pending reference results
    actually present in ``results``. The persisted ``total_refs`` column is an
    EARLY estimate (taken right after the first extraction); de-dup / merge /
    re-extraction can land MORE references than that estimate, which made
    ``processed_refs`` exceed ``total_refs`` and the UI render >100% ("28/23 ·
    122%"). We therefore also return a reconciled ``total_refs`` that is never
    below ``processed_refs`` — the real final count — so progress can never
    overshoot. When ``stored_total_refs`` is None we fall back to
    ``processed_refs`` as the total.
    """
    errors_count = 0
    warnings_count = 0
    suggestions_count = 0
    refs_with_errors = 0
    refs_with_warnings_only = 0
    refs_with_suggestions_only = 0
    unverified_count = 0
    hallucination_count = 0
    refs_verified = 0
    latest_results_by_index: Dict[Any, Dict[str, Any]] = {}

    for fallback_index, ref in enumerate(results):
        status = str(ref.get("status") or "").strip().lower()
        if not status or status in {"pending", "checking", "in_progress", "queued", "processing", "started"}:
            continue
        ref_index = ref.get("index")
        if ref_index is None:
            ref_index = fallback_index
        latest_results_by_index[ref_index] = ref

    for ref in latest_results_by_index.values():
        status = str(ref.get("status") or "").strip().lower()
        effective_status = _get_effective_reference_status(ref, is_complete)
        llm_match = _llm_found_metadata_matches_citation(ref)
        assessment = ref.get("hallucination_assessment") or {}
        likely_hallucinated = assessment.get("verdict") == "LIKELY" and not llm_match
        errors = ref.get("errors") or []
        warnings = ref.get("warnings") or []
        suggestions = ref.get("suggestions") or []

        if effective_status != "hallucination" and not llm_match:
            errors_count += sum(
                1 for error in errors
                if str((error or {}).get("error_type") or "").lower() != "unverified"
            )
            warnings_count += len(warnings)
        if effective_status != "hallucination":
            suggestions_count += len(suggestions)

        if effective_status == "error":
            refs_with_errors += 1
        elif effective_status == "warning":
            refs_with_warnings_only += 1
        elif effective_status == "suggestion":
            refs_with_suggestions_only += 1

        if (
            effective_status in {"unverified", "hallucination"}
            or (
                effective_status != "checking"
                and any(str((error or {}).get("error_type") or "").lower() == "unverified" for error in errors)
            )
            or likely_hallucinated
        ):
            unverified_count += 1
        if effective_status == "hallucination" or likely_hallucinated:
            hallucination_count += 1
        if effective_status in {"verified", "suggestion"}:
            refs_verified += 1

    processed_refs = len(latest_results_by_index)
    # Reconcile the total against the REAL processed count so progress never
    # exceeds 100%. The stored total is an early extraction estimate; the
    # actual reference set can be larger after de-dup/merge/re-extraction.
    try:
        _stored_total = int(stored_total_refs) if stored_total_refs is not None else 0
    except (TypeError, ValueError):
        _stored_total = 0
    reconciled_total_refs = max(_stored_total, processed_refs)

    return {
        "processed_refs": processed_refs,
        "total_refs": reconciled_total_refs,
        "errors_count": errors_count,
        "warnings_count": warnings_count,
        "suggestions_count": suggestions_count,
        "refs_with_errors": refs_with_errors,
        "refs_with_warnings_only": refs_with_warnings_only,
        "refs_with_suggestions_only": refs_with_suggestions_only,
        "unverified_count": unverified_count,
        "hallucination_count": hallucination_count,
        "verified_count": refs_verified,
        "refs_verified": refs_verified,
    }


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
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    duration_ms INTEGER,
                    input_bytes INTEGER,
                    source_host TEXT,
                    paper_identifier_type TEXT,
                    paper_identifier_value TEXT,
                    paper_key TEXT,
                    issue_type_counts_json TEXT,
                    cache_hit BOOLEAN DEFAULT 0,
                    bibliography_source_kind TEXT,
                    failure_class TEXT,
                    cancel_reason TEXT,
                    batch_size INTEGER,
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
                    hallucination_provider TEXT,
                    hallucination_model TEXT,
                    extraction_method TEXT,
                    status TEXT DEFAULT 'completed',
                    team_id INTEGER REFERENCES teams(id)
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

            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, key)
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

            # Identity-keyed reference table. The verification_cache above is
            # keyed by the verbatim reference string a paper used; this one
            # lives alongside it, keyed by canonical identifiers (DOI / ArXiv
            # ID / normalized title). Lets the app reuse verifications across
            # checks regardless of how a given paper happened to cite the
            # source, and powers the "Seen References" tab.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS verified_reference_identity (
                    identity_key TEXT PRIMARY KEY,
                    title TEXT,
                    authors TEXT,
                    year INTEGER,
                    doi TEXT,
                    arxiv_id TEXT,
                    venue TEXT,
                    verified_url TEXT,
                    matched_db TEXT,
                    status TEXT,
                    result_json TEXT NOT NULL,
                    times_seen INTEGER DEFAULT 1,
                    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_seen_check_id INTEGER,
                    last_seen_paper_title TEXT
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_vri_doi ON verified_reference_identity(doi)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_vri_arxiv ON verified_reference_identity(arxiv_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_vri_last_seen ON verified_reference_identity(last_seen DESC)")
            # Best-effort column add for existing installs — ignore errors
            # since the columns may already exist from a previous startup.
            for ddl in (
                "ALTER TABLE verified_reference_identity ADD COLUMN last_seen_check_id INTEGER",
                "ALTER TABLE verified_reference_identity ADD COLUMN last_seen_paper_title TEXT",
            ):
                try:
                    await db.execute(ddl)
                except Exception:
                    pass

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

            # Teams (issue #66). A team is owned by one user and groups any
            # number of member users. Owner-gated mutations live in main.py;
            # the schema is idempotent (CREATE TABLE IF NOT EXISTS) and mirrors
            # the migration style used by users/oauth_accounts above.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS teams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    owner_user_id INTEGER NOT NULL REFERENCES users(id),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS team_members (
                    team_id INTEGER NOT NULL REFERENCES teams(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    role TEXT NOT NULL DEFAULT 'member',
                    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (team_id, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_teams_owner ON teams(owner_user_id)"
            )
            # Per-team audit log: who added/removed whom (and other team changes),
            # so the team view can show an activity feed. actor/target emails are
            # denormalised so the log stays readable even if a user later leaves.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS team_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id INTEGER NOT NULL REFERENCES teams(id),
                    actor_user_id INTEGER REFERENCES users(id),
                    actor_email TEXT,
                    action TEXT NOT NULL,
                    target_user_id INTEGER,
                    target_email TEXT,
                    detail TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_team_activity_team ON team_activity(team_id, id)"
            )

            # Tiny key/value store for one-time migrations. Keeps the
            # bump-schema-and-clean-stale-rows logic out of the column
            # additions in `_ensure_columns` so each migration is a
            # named step we can extend later.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            await self._ensure_columns(db)
            await self._migrate_plaintext_secrets(db)
            await self._migrate_stale_verified_identity(db)
            
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
            # v0.7.46: composite index on (user_id, timestamp DESC) and
            # raw (timestamp DESC) so the `ORDER BY timestamp DESC LIMIT N`
            # query the sidebar fires on every page load doesn't scan the
            # whole table. After the 800-paper batch landed users had
            # 1600+ rows and /history timed out at 30s because the planner
            # was doing a full sort.
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_check_history_timestamp
                ON check_history(timestamp DESC)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_check_history_user_timestamp
                ON check_history(user_id, timestamp DESC)
            """)
            # R26: index team-shared checks so get_team_checks /
            # team-member batch reads don't scan the whole table.
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_check_history_team_id
                ON check_history(team_id)
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
        recompute_history_counts = False
        if "refs_with_suggestions_only" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN refs_with_suggestions_only INTEGER DEFAULT 0")
            recompute_history_counts = True
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
        if "hallucination_provider" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN hallucination_provider TEXT")
        if "hallucination_model" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN hallucination_model TEXT")
        if "started_at" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN started_at DATETIME")
        if "completed_at" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN completed_at DATETIME")
        if "duration_ms" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN duration_ms INTEGER")
        if "input_bytes" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN input_bytes INTEGER")
        if "source_host" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN source_host TEXT")
        if "paper_identifier_type" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN paper_identifier_type TEXT")
        if "paper_identifier_value" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN paper_identifier_value TEXT")
        if "paper_key" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN paper_key TEXT")
        if "issue_type_counts_json" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN issue_type_counts_json TEXT")
        if "cache_hit" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN cache_hit BOOLEAN DEFAULT 0")
        if "bibliography_source_kind" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN bibliography_source_kind TEXT")
        if "failure_class" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN failure_class TEXT")
        if "cancel_reason" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN cancel_reason TEXT")
        if "batch_size" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN batch_size INTEGER")
        # AI-generated-text detection (opt-in). The full result blob lives in
        # ai_detection_json (for the single-check detail view); score + band
        # are promoted to scalar columns so batch aggregation — which reads
        # scalar columns, not the JSON blob — can tally per-paper bands.
        if "ai_detection_json" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN ai_detection_json TEXT")
        if "ai_detection_score" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN ai_detection_score REAL")
        if "ai_detection_band" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN ai_detection_band TEXT")
        # Team-scoped sharing (issue #66 / R26). A check (and therefore its
        # batch) can be shared with one team; non-null means members of that
        # team may read it in addition to the owner. Nullable so single-user
        # mode and unshared checks behave exactly as before.
        if "team_id" not in columns:
            await db.execute("ALTER TABLE check_history ADD COLUMN team_id INTEGER REFERENCES teams(id)")

        await db.execute(
            "UPDATE check_history SET started_at = COALESCE(started_at, timestamp) WHERE started_at IS NULL"
        )

        if recompute_history_counts:
            await self._recompute_history_counts(db)

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

    async def _recompute_history_counts(self, db: aiosqlite.Connection):
        """Recompute aggregate count columns for existing check_history rows.

        Used as a one-time migration when a new bucket column is added so that
        previously saved entries match the reference-level totals derived from
        their stored ``results_json``.
        """
        async with db.execute(
            "SELECT id, status, total_refs, results_json FROM check_history WHERE results_json IS NOT NULL AND results_json != ''"
        ) as cursor:
            rows = await cursor.fetchall()

        for row in rows:
            check_id, status, stored_total, raw_results = row
            if not raw_results:
                continue
            try:
                parsed = json.loads(raw_results)
            except Exception:
                continue
            if not isinstance(parsed, list) or not parsed:
                continue
            buckets = _compute_reference_buckets_from_results(
                parsed,
                is_complete=status in {"completed", "cancelled", "error"},
                stored_total_refs=stored_total,
            )
            await db.execute(
                """
                UPDATE check_history
                   SET total_refs = ?,
                       errors_count = ?,
                       warnings_count = ?,
                       suggestions_count = ?,
                       unverified_count = ?,
                       refs_with_errors = ?,
                       refs_with_warnings_only = ?,
                       refs_with_suggestions_only = ?,
                       refs_verified = ?,
                       hallucination_count = ?
                 WHERE id = ?
                """,
                (
                    buckets["total_refs"],
                    buckets["errors_count"],
                    buckets["warnings_count"],
                    buckets["suggestions_count"],
                    buckets["unverified_count"],
                    buckets["refs_with_errors"],
                    buckets["refs_with_warnings_only"],
                    buckets["refs_with_suggestions_only"],
                    buckets["refs_verified"],
                    buckets["hallucination_count"],
                    check_id,
                ),
            )

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

    async def _migrate_stale_verified_identity(self, db: aiosqlite.Connection):
        """Drop pre-fix rows from the Seen-Refs cache.

        Rows written before the v0.7 bug round had two issues that the
        per-read code can't fully cover:

        1. Identity keys were computed from cited fields only, so the
           same paper could appear under multiple keys depending on
           which version of the cascade saw it first. New writes use a
           cascade that prefers DOI/arXiv from authoritative_urls, so
           old keys are inconsistent with the new ones.
        2. result_json carried the pre-split shape (verified canonical
           values overwrote cited title/authors/year) — replaying those
           through the verify endpoint would re-introduce the "mixed
           up" metadata that #13 fixed.

        Migration is one-shot, gated on `schema_meta.key = 'seen_refs_v'`.
        We DELETE rows whose result_json is missing every `verified_*`
        sibling AND has a status of verified/warning (i.e. they came
        from a real verification, not a bare insert). Bare-insert rows
        with status=unverified are left alone — they don't carry stale
        canonical metadata.
        """
        async with db.execute(
            "SELECT value FROM schema_meta WHERE key = 'seen_refs_v'"
        ) as cursor:
            row = await cursor.fetchone()
        current_version = int(row[0]) if row and row[0] else 0
        # v3 forces a backfill from every completed check_history row.
        # Reason: v0.7.7 - v0.7.10 had a latent NameError in the
        # Seen-Refs backstop (database.py used `logger` without
        # importing logging). New checks failed to populate the
        # library silently. v0.7.11 fixed the logger but a user
        # who'd already installed an earlier version would still see
        # an empty library. This migration sweeps every persisted
        # check result and re-upserts so the library catches up.
        TARGET_VERSION = 3
        if current_version >= TARGET_VERSION:
            return

        # Inspect rows whose status was a real verification. Sample
        # cheaply by checking the result_json text — full JSON parsing
        # per row would balloon for big caches.
        async with db.execute(
            """
            SELECT identity_key, result_json
            FROM verified_reference_identity
            WHERE status IN ('verified', 'warning')
            """
        ) as cursor:
            stale_keys = []
            async for ikey, result_json in cursor:
                if not result_json:
                    continue
                # Fast path: a pre-split row has none of the new keys.
                if (
                    'verified_title' not in result_json
                    and 'verified_authors' not in result_json
                    and 'verified_year' not in result_json
                    and 'verified_doi' not in result_json
                    and 'verified_arxiv_id' not in result_json
                ):
                    stale_keys.append(ikey)
        if stale_keys:
            logger.info(
                "seen-refs migration: deleting %d pre-fix verified rows so the cache repopulates with the new identity-key cascade",
                len(stale_keys),
            )
            # Chunk the delete to keep SQL params under the 999 SQLite limit.
            for i in range(0, len(stale_keys), 500):
                chunk = stale_keys[i:i + 500]
                placeholders = ",".join(["?"] * len(chunk))
                await db.execute(
                    f"DELETE FROM verified_reference_identity WHERE identity_key IN ({placeholders})",
                    chunk,
                )
        # v3 backfill: walk every completed check's results_json and
        # upsert each ref. Idempotent — repeated keys just bump
        # times_seen. Cheap: SQLite indexed reads + one INSERT per ref.
        if current_version < 3:
            try:
                async with db.execute(
                    "SELECT id, paper_title, results_json FROM check_history "
                    "WHERE status IN ('completed', 'cancelled') AND results_json IS NOT NULL"
                ) as ch_cur:
                    backfilled = 0
                    skipped = 0
                    async for check_id, paper_title, results_json in ch_cur:
                        if not results_json:
                            continue
                        try:
                            results = json.loads(results_json)
                        except Exception:
                            continue
                        if not isinstance(results, list):
                            continue
                        for ref in results:
                            if not isinstance(ref, dict):
                                continue
                            ident = self.reference_identity_key(ref)
                            if not ident:
                                skipped += 1
                                continue
                            try:
                                authors_field = (
                                    ref.get("authors") if isinstance(ref.get("authors"), str)
                                    else json.dumps(ref.get("authors") or [], default=str)
                                )
                                year_val = (
                                    int(ref.get("year")) if str(ref.get("year") or "").isdigit() else None
                                )
                                await db.execute(
                                    """
                                    INSERT INTO verified_reference_identity
                                        (identity_key, title, authors, year, doi, arxiv_id, venue,
                                         verified_url, matched_db, status, result_json,
                                         times_seen, first_seen, last_seen,
                                         last_seen_check_id, last_seen_paper_title)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?)
                                    ON CONFLICT(identity_key) DO UPDATE SET
                                        times_seen = verified_reference_identity.times_seen + 1,
                                        last_seen = CURRENT_TIMESTAMP,
                                        last_seen_check_id = COALESCE(excluded.last_seen_check_id, verified_reference_identity.last_seen_check_id),
                                        last_seen_paper_title = COALESCE(excluded.last_seen_paper_title, verified_reference_identity.last_seen_paper_title)
                                    """,
                                    (
                                        ident,
                                        ref.get("title"),
                                        authors_field,
                                        year_val,
                                        (ref.get("doi") or "").strip() or None,
                                        (ref.get("arxiv_id") or "").strip() or None,
                                        ref.get("venue"),
                                        ref.get("verified_url"),
                                        ref.get("matched_db") or ref.get("_matched_database"),
                                        ref.get("status") or "",
                                        json.dumps(ref, default=str),
                                        check_id,
                                        paper_title,
                                    ),
                                )
                                backfilled += 1
                            except Exception:
                                skipped += 1
                logger.info(
                    "seen-refs backfill (v3): wrote %d refs, skipped %d (no identity key)",
                    backfilled, skipped,
                )
            except Exception as e:
                logger.warning("seen-refs v3 backfill failed: %s", e)

        await db.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('seen_refs_v', ?)",
            (str(TARGET_VERSION),),
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
                         hallucination_count: int = 0,
                         refs_with_suggestions_only: int = 0) -> int:
        """Save a check result to database"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO check_history
                (paper_title, paper_source, source_type, total_refs, errors_count, warnings_count,
                 suggestions_count, unverified_count, refs_with_errors, refs_with_warnings_only,
                 refs_with_suggestions_only,
                 refs_verified, hallucination_count, results_json, llm_provider, llm_model, extraction_method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                refs_with_suggestions_only,
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
        """Get recent check history, optionally filtered by user.

        v0.7.46: results_json is pulled but bounded by ``limit`` (50 by
        default) to keep /history snappy. v0.7.46's blanket removal of
        results_json broke the recompute path: ``processed_refs`` and
        the stat buckets all live in results_json (the persisted column
        values reflect the LAST upsert and can be stale during an
        in-progress run, or carry sentinel 99s during partial writes).
        v0.7.65 restores the recompute so history rows match the
        Summary view and the unit tests' processed_refs expectation.
        The 800-paper-batch case that motivated v0.7.46 is unaffected
        because the FE still requests LIMIT 50 — fewer rows means
        bounded JSON parse cost.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            select_cols = (
                "id, paper_title, paper_source, custom_label, timestamp, "
                "total_refs, errors_count, warnings_count, suggestions_count, unverified_count, "
                "hallucination_count, "
                "refs_with_errors, refs_with_warnings_only, refs_with_suggestions_only, refs_verified, "
                "llm_provider, llm_model, hallucination_provider, hallucination_model, "
                "status, source_type, batch_id, batch_label, "
                "bibliography_source_kind, original_filename, results_json"
            )
            if user_id is not None:
                query = f"""
                    SELECT {select_cols}
                    FROM check_history
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                params = (user_id, limit)
            else:
                query = f"""
                    SELECT {select_cols}
                    FROM check_history
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                params = (limit,)
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                history = []
                for row in rows:
                    item = dict(row)
                    raw_results = item.pop('results_json', None)
                    item.setdefault('refs_with_suggestions_only', 0)
                    # v0.7.65: recompute display stats from results_json
                    # so processed_refs / unverified_count reflect the
                    # actual reference array (the persisted aggregate
                    # columns can be stale during in-progress runs).
                    if raw_results:
                        try:
                            parsed_results = json.loads(raw_results)
                        except Exception:
                            parsed_results = []
                        if isinstance(parsed_results, list) and parsed_results:
                            buckets = _compute_reference_buckets_from_results(
                                parsed_results,
                                is_complete=item.get('status') in {'completed', 'cancelled', 'error'},
                                stored_total_refs=item.get('total_refs'),
                            )
                            # buckets carries a reconciled total_refs (>= processed_refs)
                            # so the sidebar card never renders "59/43".
                            item.update(buckets)
                    history.append(item)
                return history

    async def get_check_by_id(
        self,
        check_id: int,
        user_id: Optional[int] = None,
        team_ids: Optional[List[int]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get specific check result by ID, optionally enforcing user ownership.

        When ``team_ids`` is provided alongside ``user_id``, a check is also
        visible if it is shared with one of those teams (``team_id`` in
        ``team_ids``) — the single-check counterpart of the team-aware batch
        reads, so a team member can open a check shared with them (R26). With
        ``user_id`` None there is no scoping (single-user mode)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            if user_id is not None:
                clauses = ["user_id = ?"]
                params = [check_id, user_id]
                for tid in (team_ids or []):
                    clauses.append("team_id = ?")
                    params.append(tid)
                query = (
                    "SELECT * FROM check_history WHERE id = ? AND ("
                    + " OR ".join(clauses) + ")"
                )
                params = tuple(params)
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
                        if isinstance(result['results'], list) and result['results']:
                            # Pass the stored total so the recompute reconciles it
                            # up to the real processed count (never < processed_refs),
                            # keeping the selected-check Summary <= 100%.
                            result.update(_compute_reference_buckets_from_results(
                                result['results'],
                                is_complete=result.get('status') in {'completed', 'cancelled', 'error'},
                                stored_total_refs=result.get('total_refs'),
                            ))
                    if result.get('issue_type_counts_json'):
                        result['issue_type_counts'] = json.loads(result['issue_type_counts_json'])
                    if result.get('ai_detection_json'):
                        try:
                            result['ai_detection'] = json.loads(result['ai_detection_json'])
                        except (ValueError, TypeError):
                            pass
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
                                    hallucination_provider: Optional[str] = None,
                                    hallucination_model: Optional[str] = None,
                                    batch_id: Optional[str] = None,
                                    batch_label: Optional[str] = None,
                                    original_filename: Optional[str] = None,
                                    user_id: Optional[int] = None,
                                    started_at: Optional[str] = None,
                                    input_bytes: Optional[int] = None,
                                    source_host: Optional[str] = None,
                                    paper_identifier_type: Optional[str] = None,
                                    paper_identifier_value: Optional[str] = None,
                                    paper_key: Optional[str] = None,
                                    batch_size: Optional[int] = None) -> int:
        """Create a pending check entry before verification starts"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO check_history
                (paper_title, paper_source, source_type, total_refs, errors_count, warnings_count,
                 suggestions_count, unverified_count, results_json, llm_provider, llm_model,
                 hallucination_provider, hallucination_model, status,
                 batch_id, batch_label, original_filename, user_id, started_at, input_bytes,
                 source_host, paper_identifier_type, paper_identifier_value, paper_key, batch_size)
                VALUES (?, ?, ?, 0, 0, 0, 0, 0, '[]', ?, ?, ?, ?, 'in_progress', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                paper_title,
                paper_source,
                source_type,
                llm_provider,
                llm_model,
                hallucination_provider,
                hallucination_model,
                batch_id,
                batch_label,
                original_filename,
                user_id,
                started_at,
                input_bytes,
                source_host,
                paper_identifier_type,
                paper_identifier_value,
                paper_key,
                batch_size,
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
                                    hallucination_count: int = 0,
                                    completed_at: Optional[str] = None,
                                    duration_ms: Optional[int] = None,
                                    paper_identifier_type: Optional[str] = None,
                                    paper_identifier_value: Optional[str] = None,
                                    paper_key: Optional[str] = None,
                                    issue_type_counts: Optional[Dict[str, int]] = None,
                                    cache_hit: Optional[bool] = None,
                                    bibliography_source_kind: Optional[str] = None,
                                    failure_class: Optional[str] = None,
                                    refs_with_suggestions_only: int = 0,
                                    ai_detection: Optional[Dict[str, Any]] = None) -> bool:
        """Update a check with its results. If paper_title is None, don't update it."""
        async with aiosqlite.connect(self.db_path) as db:
            updates = []
            params: List[Any] = []

            if paper_title is not None:
                updates.append("paper_title = ?")
                params.append(paper_title)

            updates.extend([
                "total_refs = ?",
                "errors_count = ?",
                "warnings_count = ?",
                "suggestions_count = ?",
                "unverified_count = ?",
                "hallucination_count = ?",
                "refs_with_errors = ?",
                "refs_with_warnings_only = ?",
                "refs_with_suggestions_only = ?",
                "refs_verified = ?",
                "results_json = ?",
                "status = ?",
                "extraction_method = ?",
            ])
            params.extend([
                total_refs,
                errors_count,
                warnings_count,
                suggestions_count,
                unverified_count,
                hallucination_count,
                refs_with_errors,
                refs_with_warnings_only,
                refs_with_suggestions_only,
                refs_verified,
                json.dumps(results),
                status,
                extraction_method,
            ])

            if completed_at is not None:
                updates.append("completed_at = ?")
                params.append(completed_at)
            if duration_ms is not None:
                updates.append("duration_ms = ?")
                params.append(duration_ms)
            if paper_identifier_type is not None:
                updates.append("paper_identifier_type = ?")
                params.append(paper_identifier_type)
            if paper_identifier_value is not None:
                updates.append("paper_identifier_value = ?")
                params.append(paper_identifier_value)
            if paper_key is not None:
                updates.append("paper_key = ?")
                params.append(paper_key)
            if issue_type_counts is not None:
                updates.append("issue_type_counts_json = ?")
                params.append(json.dumps(issue_type_counts, sort_keys=True))
            if cache_hit is not None:
                updates.append("cache_hit = ?")
                params.append(1 if cache_hit else 0)
            if bibliography_source_kind is not None:
                updates.append("bibliography_source_kind = ?")
                params.append(bibliography_source_kind)
            if failure_class is not None:
                updates.append("failure_class = ?")
                params.append(failure_class)
            if ai_detection is not None:
                updates.append("ai_detection_json = ?")
                params.append(json.dumps(ai_detection))
                updates.append("ai_detection_score = ?")
                params.append(ai_detection.get("overall_score"))
                updates.append("ai_detection_band = ?")
                params.append(ai_detection.get("band"))

            params.append(check_id)
            await db.execute(
                f"UPDATE check_history SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            await db.commit()

        # Backstop: when a check finishes, walk every result and upsert
        # it into the Seen-Refs library. Without this, refs that didn't
        # flow through the per-emit hook (cache hits, manually added
        # refs, follow-up re-verifies that mutated state) silently
        # missed the library. Errors here mustn't block the check write
        # we just committed.
        if status in ("completed", "cancelled"):
            # v0.7.69: capture before-count so we can report NEW rows
            # added separately from existing-row updates. The "120
            # plateau" symptom is that every upsert hits ON CONFLICT
            # and bumps times_seen but never INSERTs — without this
            # diagnostic the user can't tell whether identity-key
            # collisions are stranding new refs.
            before_count = 0
            try:
                async with aiosqlite.connect(self.db_path) as _diag_db:
                    cur = await _diag_db.execute("SELECT COUNT(*) FROM verified_reference_identity")
                    row = await cur.fetchone()
                    before_count = int(row[0] if row else 0)
            except Exception:
                pass
            written = 0
            for ref in (results or []):
                try:
                    # Stamp the source check_id + paper_title on each
                    # backstop write so Seen Refs rows link back to
                    # the originating check.
                    key = await self.upsert_verified_reference(
                        ref, check_id=check_id, paper_title=paper_title,
                    )
                    if key is not None:
                        written += 1
                except Exception as e:
                    # Promoted DEBUG→WARNING in v0.7.69 so user logs
                    # surface backstop failures (silent DEBUG-level
                    # failures hid the v0.7.64 incomplete fix for
                    # months).
                    logger.warning("Seen-Refs backstop upsert failed for ref: %s", e)
            after_count = before_count
            try:
                async with aiosqlite.connect(self.db_path) as _diag_db:
                    cur = await _diag_db.execute("SELECT COUNT(*) FROM verified_reference_identity")
                    row = await cur.fetchone()
                    after_count = int(row[0] if row else 0)
            except Exception:
                pass
            new_rows = max(0, after_count - before_count)
            logger.info(
                "Seen-Refs backstop: wrote %d/%d refs for check %d (%d NEW, %d updated, total now %d)",
                written, len(results or []), check_id,
                new_rows, max(0, written - new_rows), after_count,
            )
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
                                     results: List[Dict[str, Any]] = None,
                                     refs_with_suggestions_only: int = 0) -> bool:
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
                    refs_with_warnings_only = ?,
                    refs_with_suggestions_only = ?,
                    refs_verified = ?, results_json = ?
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
                refs_with_suggestions_only,
                refs_verified,
                json.dumps(results or []),
                check_id
            ))
            await db.commit()
            return True

    async def update_check_status(self,
                                  check_id: int,
                                  status: str,
                                  failure_class: Optional[str] = None,
                                  cancel_reason: Optional[str] = None,
                                  completed_at: Optional[str] = None,
                                  duration_ms: Optional[int] = None) -> bool:
        """Update just the status of a check"""
        async with aiosqlite.connect(self.db_path) as db:
            updates = ["status = ?"]
            params: List[Any] = [status]
            if failure_class is not None:
                updates.append("failure_class = ?")
                params.append(failure_class)
            if cancel_reason is not None:
                updates.append("cancel_reason = ?")
                params.append(cancel_reason)
            if completed_at is not None:
                updates.append("completed_at = ?")
                params.append(completed_at)
            if duration_ms is not None:
                updates.append("duration_ms = ?")
                params.append(duration_ms)
            params.append(check_id)
            await db.execute(
                f"UPDATE check_history SET {', '.join(updates)} WHERE id = ?",
                params,
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

    @staticmethod
    def _is_check_stale(
        results: List[Dict[str, Any]],
        total_refs: int,
        last_activity: Optional[str],
        stale_after_seconds: float,
    ) -> bool:
        """Decide whether an orphaned in_progress row is safe to finalize.

        A row is stale when either:
          • its references are all in (processed >= total_refs > 0) — the run
            finished the work but never wrote the terminal status (the classic
            "59/43 stuck forever" symptom, where the AI-detection await or a
            server restart killed run_check between the last ref and the
            'completed' emit); OR
          • its last-activity timestamp is older than ``stale_after_seconds``
            — covers checks that died mid-extraction with no usable refs.

        Time is the *fallback*, never the only signal, so a finished-but-stuck
        check unsticks immediately on the next poll instead of waiting out the
        clock. Callers MUST already have excluded rows present in the live
        active_checks map — those are genuinely running and must be left alone.
        """
        processed = 0
        if isinstance(results, list):
            for fallback_index, ref in enumerate(results):
                status = str((ref or {}).get("status") or "").strip().lower()
                if not status or status in {
                    "pending", "checking", "in_progress", "queued", "processing", "started"
                }:
                    continue
                processed += 1
        if total_refs and processed >= total_refs:
            return True

        if not last_activity:
            # No timestamp to reason about — only the processed-count signal
            # above can finalize it; otherwise leave it alone.
            return False
        from datetime import timezone as _tz
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                ts = datetime.strptime(str(last_activity)[:26], fmt)
                break
            except ValueError:
                continue
        else:
            return False
        now = datetime.now(_tz.utc).replace(tzinfo=None)
        return (now - ts).total_seconds() >= stale_after_seconds

    async def find_stale_in_progress_checks(
        self,
        active_check_ids: Optional[set] = None,
        stale_after_seconds: float = 180.0,
    ) -> List[Dict[str, Any]]:
        """Find orphaned in_progress checks that are safe to finalize.

        Returns rows whose status is ``in_progress``, whose id is NOT in the
        live ``active_check_ids`` set (so a genuinely-running check is never
        returned), and that are stale per :meth:`_is_check_stale`. Used by the
        reconciler at startup (sweep all) and on the /history/{id} GET path
        (unstick a single polling check on demand)."""
        active = {int(cid) for cid in (active_check_ids or set())}
        candidates: List[Dict[str, Any]] = []
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, total_refs, results_json, ai_detection_json, "
                "COALESCE(completed_at, started_at, timestamp) AS last_activity "
                "FROM check_history WHERE status = 'in_progress'"
            ) as cursor:
                rows = [dict(r) async for r in cursor]

        for row in rows:
            if int(row["id"]) in active:
                continue
            try:
                results = json.loads(row.get("results_json") or "[]")
            except (ValueError, TypeError):
                results = []
            if not isinstance(results, list):
                results = []
            if self._is_check_stale(
                results,
                int(row.get("total_refs") or 0),
                row.get("last_activity"),
                stale_after_seconds,
            ):
                candidates.append(row)
        return candidates

    async def finalize_stale_check(
        self,
        check_id: int,
        reason: str = "reconciled (orphaned session)",
    ) -> Optional[str]:
        """Finalize a single orphaned in_progress check to a terminal status.

        Computes the terminal status from the stored references (reusing the
        same bucket logic the live path uses): ``completed`` when there is at
        least one processed reference, ``error`` when there are none (the run
        died before producing any usable result). Writes ``completed_at``, a
        ``cancel_reason`` of ``reason``, and the recomputed aggregate count
        columns so history cards/Summary render correct numbers. If
        AI-detection was never attached, marks it ``unavailable`` so the FE
        stops waiting for an analysis that will never arrive.

        Idempotent and race-safe: returns ``None`` (no-op) if the row is not
        (or no longer) ``in_progress`` — so it can never clobber a check that
        a concurrent live run just finalized, or downgrade an already-terminal
        row. Returns the terminal status string on success."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT status, total_refs, results_json, ai_detection_json "
                "FROM check_history WHERE id = ?",
                (check_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return None
            if str(row["status"] or "").strip().lower() != "in_progress":
                # Already terminal (or a live run finalized it first) — never
                # overwrite a genuine terminal status.
                return None

            try:
                results = json.loads(row["results_json"] or "[]")
            except (ValueError, TypeError):
                results = []
            if not isinstance(results, list):
                results = []

            buckets = _compute_reference_buckets_from_results(
                results, is_complete=True, stored_total_refs=row["total_refs"],
            )
            terminal_status = "completed" if buckets["processed_refs"] > 0 else "error"
            # Reconciled total never sits below the real processed count, so a
            # finalized orphan can't persist "processed > total" (>100% progress).
            total_refs = buckets["total_refs"]

            from datetime import timezone as _tz
            completed_at = datetime.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S")

            updates = [
                "status = ?",
                "completed_at = ?",
                "cancel_reason = ?",
                "total_refs = ?",
                "errors_count = ?",
                "warnings_count = ?",
                "suggestions_count = ?",
                "unverified_count = ?",
                "hallucination_count = ?",
                "refs_with_errors = ?",
                "refs_with_warnings_only = ?",
                "refs_with_suggestions_only = ?",
                "refs_verified = ?",
            ]
            params: List[Any] = [
                terminal_status,
                completed_at,
                reason,
                total_refs,
                buckets["errors_count"],
                buckets["warnings_count"],
                buckets["suggestions_count"],
                buckets["unverified_count"],
                buckets["hallucination_count"],
                buckets["refs_with_errors"],
                buckets["refs_with_warnings_only"],
                buckets["refs_with_suggestions_only"],
                buckets["refs_verified"],
            ]

            # AI detection never attached → record an honest 'unavailable' so a
            # polling FE stops waiting for an analysis the dead run never made.
            if not (row["ai_detection_json"] or "").strip():
                try:
                    from refchecker.ai_detection.base import make_unavailable
                    ai_payload = make_unavailable("reconciled", "local").to_dict()
                except Exception:  # noqa: BLE001 — ai_detection is optional
                    ai_payload = {"status": "unavailable", "reason": "reconciled"}
                updates.append("ai_detection_json = ?")
                params.append(json.dumps(ai_payload))
                updates.append("ai_detection_band = ?")
                params.append(ai_payload.get("band"))

            params.append(check_id)
            await db.execute(
                f"UPDATE check_history SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            await db.commit()
            return terminal_status

    async def reconcile_stale_in_progress(
        self,
        active_check_ids: Optional[set] = None,
        stale_after_seconds: float = 180.0,
        reason: str = "reconciled (orphaned session)",
    ) -> int:
        """Sweep all orphaned in_progress checks and finalize each.

        Returns the number of rows actually finalized. Safe to call repeatedly
        (each finalize is idempotent and guards on still being in_progress)."""
        stale = await self.find_stale_in_progress_checks(
            active_check_ids=active_check_ids,
            stale_after_seconds=stale_after_seconds,
        )
        finalized = 0
        for row in stale:
            try:
                if await self.finalize_stale_check(int(row["id"]), reason=reason):
                    finalized += 1
            except Exception as e:  # noqa: BLE001 — one bad row mustn't abort the sweep
                logger.warning("Failed to finalize stale check %s: %s", row.get("id"), e)
        return finalized

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
                                     avatar_url: Optional[str] = None,
                                     login: Optional[str] = None) -> int:
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
                # Re-evaluate admin status on every login so config changes take effect
                is_admin = await self._should_be_admin(db, email, login, provider)
                await db.execute("""
                    UPDATE users SET email = ?, name = ?, avatar_url = ?, is_admin = ?
                    WHERE id = ?
                """, (email, name, avatar_url, 1 if is_admin else 0, user_id))
            else:
                # Try the legacy users unique constraint (existing rows pre-migration)
                async with db.execute(
                    "SELECT id FROM users WHERE provider = ? AND provider_id = ?",
                    (provider, provider_id)
                ) as cursor:
                    legacy_row = await cursor.fetchone()

                if legacy_row:
                    user_id = legacy_row[0]
                    is_admin = await self._should_be_admin(db, email, login, provider)
                    await db.execute("""
                        UPDATE users SET email = ?, name = ?, avatar_url = ?, is_admin = ?
                        WHERE id = ?
                    """, (email, name, avatar_url, 1 if is_admin else 0, user_id))
                else:
                    is_admin = await self._should_be_admin(db, email, login, provider)
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

    @staticmethod
    def _load_admin_users() -> tuple:
        """Load admin identifiers from config file + env vars.

        Returns ``(qualified, unqualified)`` where *qualified* is a set of
        ``"provider:identity"`` strings and *unqualified* is a set of bare
        identities (email or username) that match any provider.

        Entries support two formats:
        - ``github:markrussinovich`` — provider-qualified (recommended)
        - ``user@example.com`` — bare email / username, matches any provider

        Sources:
        1. ``admin_users.conf`` file (one entry per line, ``#`` comments).
        2. ``REFCHECKER_ADMINS`` env var (comma-separated).
        """
        import os, pathlib
        qualified: set = set()    # e.g. {"github:markrussinovich"}
        unqualified: set = set()  # e.g. {"user@example.com"}

        def _add(raw: str) -> None:
            raw = raw.lstrip("@").lower()
            if ":" in raw:
                qualified.add(raw)  # already provider:identity
            else:
                unqualified.add(raw)

        # 1. Config file
        for candidate in [
            pathlib.Path(__file__).resolve().parent.parent / "admin_users.conf",
            pathlib.Path("admin_users.conf"),
        ]:
            if candidate.is_file():
                try:
                    for line in candidate.read_text().splitlines():
                        entry = line.strip()
                        if entry and not entry.startswith("#"):
                            _add(entry)
                except OSError:
                    pass
                break

        # 2. REFCHECKER_ADMINS env var
        for val in os.environ.get("REFCHECKER_ADMINS", "").split(","):
            val = val.strip()
            if val:
                _add(val)

        return qualified, unqualified

    async def _should_be_admin(self, db: aiosqlite.Connection,
                               email: Optional[str],
                               login: Optional[str] = None,
                               provider: Optional[str] = None) -> bool:
        """Return True if the user should be granted admin rights.

        A user is an admin if:
        1. They are the very first user in the database, OR
        2. Their provider-qualified identity (e.g. ``github:markrussinovich``)
           or bare email/username is in the admin users list.
        """
        qualified, unqualified = self._load_admin_users()
        if qualified or unqualified:
            # Check provider-qualified entries first (most specific)
            if provider and login:
                if f"{provider}:{login.lower()}" in qualified:
                    return True
            if provider and email:
                if f"{provider}:{email.lower()}" in qualified:
                    return True
            # Then check unqualified entries
            if email and email.lower() in unqualified:
                return True
            if login and login.lower() in unqualified:
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

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get a user by email (case-insensitive). Used to add members by email."""
        if not email:
            return None
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, provider, provider_id, email, name, avatar_url, is_admin, created_at "
                "FROM users WHERE email IS NOT NULL AND LOWER(email) = LOWER(?)",
                (email.strip(),)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    # ------------------------------------------------------------------
    # Teams (issue #66)
    # ------------------------------------------------------------------

    async def create_team(self, name: str, owner_user_id: int) -> Dict[str, Any]:
        """Create a team owned by ``owner_user_id`` and add the owner as a member.

        Returns the created team row (with id, name, owner_user_id, created_at).
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "INSERT INTO teams (name, owner_user_id) VALUES (?, ?)",
                (name, owner_user_id),
            )
            team_id = cursor.lastrowid
            # Owner is always a member with the 'owner' role.
            await db.execute(
                "INSERT OR IGNORE INTO team_members (team_id, user_id, role) VALUES (?, ?, 'owner')",
                (team_id, owner_user_id),
            )
            await db.commit()
            async with db.execute(
                "SELECT id, name, owner_user_id, created_at FROM teams WHERE id = ?",
                (team_id,),
            ) as c:
                row = await c.fetchone()
                return dict(row)

    async def get_team(self, team_id: int) -> Optional[Dict[str, Any]]:
        """Get a single team by id, or None."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, name, owner_user_id, created_at FROM teams WHERE id = ?",
                (team_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_teams_for_user(self, user_id: int) -> List[Dict[str, Any]]:
        """List teams the user owns or is a member of, with member counts."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT t.id, t.name, t.owner_user_id, t.created_at,
                       tm.role AS my_role,
                       (SELECT COUNT(*) FROM team_members m WHERE m.team_id = t.id) AS member_count
                FROM teams t
                JOIN team_members tm ON tm.team_id = t.id
                WHERE tm.user_id = ?
                ORDER BY t.created_at DESC, t.id DESC
                """,
                (user_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def is_team_member(self, team_id: int, user_id: int) -> bool:
        """Return whether the user belongs to the team."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?",
                (team_id, user_id),
            ) as cursor:
                return await cursor.fetchone() is not None

    async def get_user_team_ids(self, user_id: int) -> List[int]:
        """Return the ids of every team the user belongs to.

        Used to widen batch/check visibility so a team member can read a check
        shared with a team they belong to (R26). Returns [] for users in no
        team (and for the single-user pseudo-user, which has no rows)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT team_id FROM team_members WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [int(row[0]) for row in rows]

    async def get_team_members(self, team_id: int) -> List[Dict[str, Any]]:
        """List members of a team joined with their user profile fields."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT tm.user_id, tm.role, tm.joined_at,
                       u.email, u.name, u.avatar_url
                FROM team_members tm
                JOIN users u ON u.id = tm.user_id
                WHERE tm.team_id = ?
                ORDER BY tm.joined_at ASC, tm.user_id ASC
                """,
                (team_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def add_team_member(self, team_id: int, user_id: int, role: str = "member") -> bool:
        """Add a user to a team. Idempotent: returns True if a new row was added."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            cursor = await db.execute(
                "INSERT OR IGNORE INTO team_members (team_id, user_id, role) VALUES (?, ?, ?)",
                (team_id, user_id, role),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def remove_team_member(self, team_id: int, user_id: int) -> bool:
        """Remove a user from a team. Returns True if a membership row was deleted."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            cursor = await db.execute(
                "DELETE FROM team_members WHERE team_id = ? AND user_id = ?",
                (team_id, user_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def count_team_members(self, team_id: int) -> int:
        """Return the number of members in a team."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM team_members WHERE team_id = ?",
                (team_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return int(row[0]) if row else 0

    async def log_team_activity(
        self,
        team_id: int,
        actor_user_id: Optional[int],
        actor_email: Optional[str],
        action: str,
        target_user_id: Optional[int] = None,
        target_email: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        """Append one entry to a team's activity/audit log.

        Best-effort: never raises (an audit-log failure must not break the
        underlying team operation)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA busy_timeout=5000")
                await db.execute(
                    """INSERT INTO team_activity
                       (team_id, actor_user_id, actor_email, action,
                        target_user_id, target_email, detail)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (team_id, actor_user_id, actor_email, action,
                     target_user_id, target_email, detail),
                )
                await db.commit()
        except Exception as e:  # noqa: BLE001
            logger.debug("log_team_activity failed: %s", e)

    async def get_team_activity(self, team_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Return a team's activity log, newest first."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT id, team_id, actor_user_id, actor_email, action,
                          target_user_id, target_email, detail, created_at
                   FROM team_activity
                   WHERE team_id = ?
                   ORDER BY id DESC
                   LIMIT ?""",
                (team_id, int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]


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

    async def get_user_preference(self, user_id: int, key: str) -> Optional[str]:
        """Get a per-user preference value."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT value FROM user_preferences WHERE user_id = ? AND key = ?",
                (user_id, key),
            ) as cursor:
                row = await cursor.fetchone()
                return row["value"] if row else None

    async def set_user_preference(self, user_id: int, key: str, value: str) -> bool:
        """Set a per-user preference value."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_preferences (user_id, key, value, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, key, value))
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
        
        # Don't cache timeout results that slipped through as 'unverified'
        for err in result.get('errors', []):
            if 'timed out' in (err.get('error_details') or '').lower():
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

    async def get_check_references(self, check_id: int, user_id: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if user_id is None:
                cursor = await db.execute("SELECT results_json FROM check_history WHERE id = ?", (check_id,))
            else:
                cursor = await db.execute("SELECT results_json FROM check_history WHERE id = ? AND user_id = ?", (check_id, user_id))
            row = await cursor.fetchone()
            if not row:
                return None
            try:
                return json.loads(row["results_json"] or "[]")
            except Exception:
                return []

    async def replace_check_references(self, check_id: int, results: List[Dict[str, Any]], user_id: Optional[int] = None) -> bool:
        """Persist a mutated reference list back into a check_history row,
        recomputing the rolled-up counters in lockstep so the history
        sidebar / Seen Refs tab don't drift from the actual results."""
        total = len(results)
        refs_with_errors = sum(1 for r in results if (r.get("errors") or []))
        refs_with_warnings_only = sum(1 for r in results if not (r.get("errors") or []) and (r.get("warnings") or []))
        refs_with_suggestions_only = sum(1 for r in results if not (r.get("errors") or []) and not (r.get("warnings") or []) and (r.get("suggestions") or []))
        refs_verified = sum(1 for r in results if (r.get("status") == "verified"))
        errors_count = sum(len(r.get("errors") or []) for r in results)
        warnings_count = sum(len(r.get("warnings") or []) for r in results)
        suggestions_count = sum(len(r.get("suggestions") or []) for r in results)
        unverified_count = sum(1 for r in results if r.get("status") == "unverified")
        hallucination_count = sum(1 for r in results if r.get("status") == "hallucinated" or (r.get("hallucination_assessment") or {}).get("verdict", "").upper() == "LIKELY")

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            params = [
                json.dumps(results, default=str),
                total, errors_count, warnings_count, suggestions_count, unverified_count,
                refs_with_errors, refs_with_warnings_only, refs_with_suggestions_only,
                refs_verified, hallucination_count,
                check_id,
            ]
            if user_id is None:
                cursor = await db.execute(
                    """UPDATE check_history SET results_json = ?, total_refs = ?, errors_count = ?,
                       warnings_count = ?, suggestions_count = ?, unverified_count = ?,
                       refs_with_errors = ?, refs_with_warnings_only = ?, refs_with_suggestions_only = ?,
                       refs_verified = ?, hallucination_count = ?
                       WHERE id = ?""",
                    params,
                )
            else:
                params.append(user_id)
                cursor = await db.execute(
                    """UPDATE check_history SET results_json = ?, total_refs = ?, errors_count = ?,
                       warnings_count = ?, suggestions_count = ?, unverified_count = ?,
                       refs_with_errors = ?, refs_with_warnings_only = ?, refs_with_suggestions_only = ?,
                       refs_verified = ?, hallucination_count = ?
                       WHERE id = ? AND user_id = ?""",
                    params,
                )
            await db.commit()
            return cursor.rowcount > 0

    async def clear_verification_cache(self) -> int:
        """Clear all cached verification results. Returns count of deleted entries."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM verification_cache")
            await db.commit()
            return cursor.rowcount

    # ---------------------------------------------------------------
    # Identity-keyed reference cache (DOI / ArXiv / normalized title)
    # ---------------------------------------------------------------

    @staticmethod
    def _normalize_title(title: Optional[str]) -> str:
        if not title:
            return ""
        # Collapse whitespace, lowercase, strip non-alphanumerics for fuzzy
        # equivalence ("BERT: Pre-training..." == "BERT Pre training").
        import re
        return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()

    @staticmethod
    def _doi_from_authoritative_urls(ref: Dict[str, Any]) -> Optional[str]:
        """Pull a canonical DOI out of the result's authoritative_urls list.
        The main check pipeline writes verified DOIs there (not into
        ``ref["doi"]``), so without this the identity key can't see them
        and the reference is silently dropped from the Seen Refs cache.
        URL-decode so the same DOI cited as percent-encoded and decoded
        ("10.1000%2Ffoo" vs "10.1000/foo") collapses to one identity.
        """
        from urllib.parse import unquote
        for u in (ref.get("authoritative_urls") or []):
            url = (u or {}).get("url") or ""
            if "doi.org/" in url:
                doi = url.split("doi.org/", 1)[1].split("?", 1)[0].split("#", 1)[0]
                return unquote(doi).strip().lower()
        return None

    @staticmethod
    def _arxiv_from_authoritative_urls(ref: Dict[str, Any]) -> Optional[str]:
        """Pull a canonical arXiv id out of authoritative_urls. Strips
        query, fragment, and trailing version suffix so 2310.02238v1 and
        2310.02238v2 dedupe to the same paper (versions are listed by
        arXiv as updates to one record, not distinct papers)."""
        import re as _re
        for u in (ref.get("authoritative_urls") or []):
            url = (u or {}).get("url") or ""
            if "arxiv.org/abs/" in url:
                aid = url.split("arxiv.org/abs/", 1)[1]
                aid = aid.split("?", 1)[0].split("#", 1)[0].strip().lower()
                # Drop the version tag (vN) so all versions cache as one.
                return _re.sub(r"v\d+$", "", aid)
        return None

    @classmethod
    def reference_identity_key(cls, ref: Dict[str, Any]) -> Optional[str]:
        """Pick the canonical identity key for a reference.

        Order: DOI -> ArXiv ID -> (normalized title + year) ->
        (normalized title alone) -> (title+authors+year hash).

        Falls back to ``authoritative_urls`` when the result dict
        doesn't carry top-level doi/arxiv_id, since the main check
        pipeline only surfaces verified ids through that list.

        Threshold for title-only was relaxed from 30 chars to 12 (and
        the 3-token requirement dropped) so single-author medical /
        humanities papers like "TNM Staging Atlas" or "Vesalius 1543"
        still produce a usable key. False-dedupe is still avoided by
        the title+year preferred path; this only fires when year is
        missing entirely.
        """
        if not isinstance(ref, dict):
            return None
        doi = (
            (ref.get("doi") or "").strip().lower()
            or (ref.get("verified_doi") or "").strip().lower()
            or (cls._doi_from_authoritative_urls(ref) or "")
        )
        if doi:
            return f"doi:{doi}"
        arxiv = (
            (ref.get("arxiv_id") or "").strip().lower()
            or (ref.get("verified_arxiv_id") or "").strip().lower()
            or (cls._arxiv_from_authoritative_urls(ref) or "")
        )
        if arxiv:
            return f"arxiv:{arxiv}"
        title = cls._normalize_title(ref.get("title") or ref.get("verified_title"))
        year = ref.get("year") or ref.get("verified_year")
        if title and year:
            return f"title:{title}:{year}"
        # Title-only fallback for refs without a year. Mix in the
        # normalized first-author surname so distinct refs that happen to
        # share an identical title (review titles, generic "Introduction"
        # entries, multi-author book chapters with different authors) do
        # NOT collapse onto the same key. Without this the Seen-Refs
        # counter plateaus around the unique-title floor instead of
        # tracking distinct refs.
        if title and len(title) >= 12:
            first_surname = ""
            authors = ref.get("authors") or []
            if isinstance(authors, list) and authors:
                first = str(authors[0] or "")
                if first:
                    tokens = first.split()
                    last = tokens[-1] if tokens else ""
                    first_surname = re.sub(r"[^a-z]", "", last.lower())
            return f"title:{title}:_:{first_surname}" if first_surname else f"title:{title}:_"
        # Hash-of-everything last resort, so refs without title still
        # land in the Seen-Refs library (manual entries, etc.). Uses
        # the ref's id when present + a hash of its identifying bits.
        import hashlib
        bits = "|".join(str(v) for v in [
            ref.get("id"),
            (ref.get("title") or "")[:200],
            (ref.get("authors") or [""])[0] if isinstance(ref.get("authors"), list) else (ref.get("authors") or "")[:80],
            ref.get("year"),
        ] if v)
        if bits:
            digest = hashlib.sha1(bits.encode("utf-8", errors="ignore")).hexdigest()[:16]
            return f"hash:{digest}"
        return None

    async def upsert_verified_reference(
        self,
        ref: Dict[str, Any],
        check_id: Optional[int] = None,
        paper_title: Optional[str] = None,
    ) -> Optional[str]:
        """Persist a single verified reference into the global identity index.

        Idempotent — repeated calls for the same identity bump `times_seen`
        and refresh `last_seen` without touching first_seen. Skips refs
        without a safe identity key.

        ``check_id`` and ``paper_title`` (when provided) are stored as
        ``last_seen_check_id`` / ``last_seen_paper_title`` so the Seen
        Refs view can link each row back to the most recent check that
        produced it.
        """
        ident = self.reference_identity_key(ref)
        if not ident:
            # Promoted DEBUG→WARNING in v0.7.69 — silent drops here are
            # the root cause of the "120 plateau". Surfaces title +
            # first author so the user can spot patterns (e.g. all
            # Vancouver-style refs missing DOIs).
            _authors = ref.get("authors") or []
            _first_author = ""
            if isinstance(_authors, list) and _authors:
                _first_author = str(_authors[0])[:60]
            elif isinstance(_authors, str):
                _first_author = _authors[:60]
            logger.warning(
                "Seen-Refs upsert skipped (no identity key): title=%r author=%r doi=%r arxiv=%r",
                (ref.get("title") or "")[:80], _first_author,
                ref.get("doi"), ref.get("arxiv_id"),
            )
            return None
        status = ref.get("status") or ""
        # Cache every ref the user has checked, regardless of verdict.
        # Previously hallucinated/error refs were skipped — but the user
        # wants to see EVERYTHING that has flowed through a check, so the
        # Seen Refs library doubles as a curation log. The status column
        # records the verdict; the UI can filter by status to hide
        # unverified ones when desired.
        result_json = json.dumps(ref, default=str)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                """
                INSERT INTO verified_reference_identity
                    (identity_key, title, authors, year, doi, arxiv_id, venue,
                     verified_url, matched_db, status, result_json,
                     times_seen, first_seen, last_seen,
                     last_seen_check_id, last_seen_paper_title)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(identity_key) DO UPDATE SET
                    title = excluded.title,
                    authors = excluded.authors,
                    year = excluded.year,
                    venue = excluded.venue,
                    verified_url = excluded.verified_url,
                    matched_db = excluded.matched_db,
                    status = excluded.status,
                    result_json = excluded.result_json,
                    times_seen = verified_reference_identity.times_seen + 1,
                    last_seen = CURRENT_TIMESTAMP,
                    last_seen_check_id = COALESCE(excluded.last_seen_check_id, verified_reference_identity.last_seen_check_id),
                    last_seen_paper_title = COALESCE(excluded.last_seen_paper_title, verified_reference_identity.last_seen_paper_title)
                """,
                (
                    ident,
                    ref.get("title"),
                    ref.get("authors") if isinstance(ref.get("authors"), str) else json.dumps(ref.get("authors") or [], default=str),
                    int(ref.get("year")) if str(ref.get("year") or "").isdigit() else None,
                    (ref.get("doi") or "").strip() or None,
                    (ref.get("arxiv_id") or "").strip() or None,
                    ref.get("venue"),
                    ref.get("verified_url"),
                    ref.get("matched_db"),
                    status,
                    result_json,
                    check_id,
                    paper_title,
                ),
            )
            await db.commit()
        return ident

    async def lookup_verified_reference(self, ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the cached identity record for a reference, or None."""
        ident = self.reference_identity_key(ref)
        if not ident:
            return None
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM verified_reference_identity WHERE identity_key = ?",
                (ident,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            data = dict(row)
            try:
                data["result"] = json.loads(data.get("result_json") or "{}")
            except Exception:
                data["result"] = {}
            return data

    async def find_verified_by_fuzzy(self, ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Pre-LLM fuzzy cache lookup against Seen-Refs.

        v0.7.48: complementary to the strict `lookup_verified_reference`
        — that one keys on exact DOI / arXiv / normalized title+year and
        misses any cited ref with a minor formatting difference. This
        looser lookup hits when:
          - normalized-title prefix (60 chars) matches a cached entry
          - first-author surname matches that entry
          - year is identical OR within ±1

        Returns the cached entry's full row + its `result` JSON so the
        caller can short-circuit the LLM and network checks entirely.
        Drops LLM bills materially on bibliographies that re-cite the
        same handful of seminal papers across many documents — the
        user's 800-paper batch was the trigger.

        None when no confident match was found.
        """
        import re as _re
        title = (ref.get("title") or "").strip().lower()
        if len(title) < 12:
            return None
        norm = _re.sub(r"[^a-z0-9 ]+", " ", title)
        norm = _re.sub(r"\s+", " ", norm).strip()
        if len(norm) < 12:
            return None
        # v0.7.54 (per ML review): reject corrections/errata in the
        # PRE-LLM fuzzy lookup so a citation matching a Correction
        # record doesn't inherit the original paper's clean status.
        _correction_markers = (
            "correction to", "correction:", "erratum",
            "retraction", "retracted", "withdrawn",
            "author correction", "publisher correction",
            "reply to", "comment on", "response to", "addendum",
        )
        if any(norm.startswith(marker) for marker in _correction_markers):
            return None
        # Longer prefix on long medical titles — 60 chars collide for
        # NEJM/Lancet review titles that share the first sentence.
        prefix = norm[:80] if len(norm) >= 100 else norm[:60]
        ref_authors = ref.get("authors") or []
        if isinstance(ref_authors, list):
            ref_authors_str = ", ".join(a for a in ref_authors if a)
        else:
            ref_authors_str = str(ref_authors or "")
        # First-author surname extractor — same logic as cross_check
        def _first_surname(s: str) -> str:
            s = (s or "").split(",")[0].split(";")[0].strip()
            parts = s.split()
            return parts[-1].lower() if parts else ""
        ref_surname = _first_surname(ref_authors_str)
        try:
            ref_year = int(ref.get("year")) if ref.get("year") else None
        except Exception:
            ref_year = None
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA busy_timeout=5000")
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT identity_key, title, authors, year, doi, arxiv_id, venue,
                           verified_url, matched_db, status, result_json,
                           times_seen
                    FROM verified_reference_identity
                    WHERE LOWER(title) LIKE ?
                    LIMIT 25
                    """,
                    (f"{prefix}%",),
                )
                rows = await cursor.fetchall()
        except Exception:
            return None
        # Pick the BEST candidate. Score by year match + author surname
        # match, prefer entries with verified status.
        best = None
        best_score = 0
        for r in rows:
            cached_surname = _first_surname(r["authors"] or "")
            try:
                cached_year = int(r["year"]) if r["year"] else None
            except Exception:
                cached_year = None
            # Author surname must match — too risky to accept a fuzzy
            # title with a totally different first author.
            if not cached_surname or not ref_surname or cached_surname != ref_surname:
                continue
            # v0.7.55 (per ML review): DOI mismatch guard. If both
            # sides have a DOI, they MUST agree, otherwise we'd accept
            # a different paper with the same surname + year + title
            # prefix (the Round 2 example: 10.X/abc vs 10.X/xyz).
            cached_doi_raw = (r["doi"] or "").strip().lower()
            if cached_doi_raw and ref_doi and cached_doi_raw != ref_doi:
                continue
            score = 1
            # Year exact match is the strongest signal; ±1 is acceptable
            # for accepted-vs-published year drift.
            if cached_year is not None and ref_year is not None:
                if cached_year == ref_year:
                    score += 2
                elif abs(cached_year - ref_year) == 1:
                    score += 1
                else:
                    # Year is way off — likely a different paper with
                    # similar title (review of the same topic, etc.).
                    continue
            elif cached_year != ref_year:
                # One side has year, the other doesn't — accept with
                # lower confidence but only when there's a DOI or arXiv
                # on the cached side to anchor the identity.
                if not (r["doi"] or r["arxiv_id"]):
                    continue
            # Verified status > unverified status in the tiebreak.
            if r["status"] == "verified":
                score += 1
            if score > best_score:
                best = r
                best_score = score
        if best is None:
            return None
        data = dict(best)
        try:
            data["result"] = json.loads(data.get("result_json") or "{}")
        except Exception:
            data["result"] = {}
        data.pop("result_json", None)
        data["_fuzzy_match_score"] = best_score
        return data

    async def cross_check_seen_refs(self, ref: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Cross-reference a cited ref against the Seen-Refs cache.

        Detects citation inconsistencies across uploads — e.g. when the
        same paper title appears in a new document with different
        authors, year, venue, or DOI compared to the metadata we
        verified for that title previously. Returns one entry per
        cached row that matched the title but disagreed on at least one
        identifying field. Each entry carries the diffs so the FE can
        render them as a "potential mismatch / hallucination" signal.

        Title match is normalized prefix LIKE (case-insensitive,
        non-alphanumeric stripped) to catch typos and punctuation
        differences without enumerating fuzzy distances. Identity-key
        equal-DOI / equal-arXiv matches are skipped — those go through
        the regular cache-hit path with no need to flag a discrepancy.
        """
        import re as _re
        title = (ref.get("title") or "").strip().lower()
        if len(title) < 12:
            return []
        norm = _re.sub(r"[^a-z0-9 ]+", " ", title)
        norm = _re.sub(r"\s+", " ", norm).strip()
        if len(norm) < 12:
            return []
        # Use the first 60 chars of normalized title for the LIKE prefix.
        # Longer than 60 risks LIKE failing on truncated cache rows;
        # shorter risks collisions across unrelated papers.
        prefix = norm[:60]
        ident_self = self.reference_identity_key(ref)
        out: List[Dict[str, Any]] = []
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT identity_key, title, authors, year, doi, arxiv_id, venue
                    FROM verified_reference_identity
                    WHERE LOWER(title) LIKE ?
                    LIMIT 10
                    """,
                    (f"{prefix}%",),
                )
                rows = await cursor.fetchall()
        except Exception:
            return []
        ref_authors = ref.get("authors") or []
        if isinstance(ref_authors, list):
            ref_authors_str = ", ".join(a for a in ref_authors if a)
        else:
            ref_authors_str = str(ref_authors or "")
        ref_doi = (ref.get("doi") or "").strip().lower()
        ref_arxiv = (ref.get("arxiv_id") or "").strip().lower()
        ref_year = str(ref.get("year") or "").strip()
        ref_venue = (ref.get("venue") or "").strip().lower()
        for r in rows:
            cached_ident = r["identity_key"] or ""
            if ident_self and cached_ident == ident_self:
                # Same identity — handled by the regular cache-hit
                # path, not a discrepancy.
                continue
            diffs: List[Dict[str, str]] = []
            # DOI mismatch is the strongest signal — if the same title
            # already maps to a verified DOI, a new citation with a
            # different DOI is likely a typo or fabrication.
            cached_doi = (r["doi"] or "").strip().lower()
            if cached_doi and ref_doi and cached_doi != ref_doi:
                diffs.append({"field": "doi", "cached": r["doi"], "cited": ref.get("doi")})
            cached_arxiv = (r["arxiv_id"] or "").strip().lower()
            if cached_arxiv and ref_arxiv and cached_arxiv != ref_arxiv:
                diffs.append({"field": "arxiv_id", "cached": r["arxiv_id"], "cited": ref.get("arxiv_id")})
            cached_year = str(r["year"] or "").strip()
            if cached_year and ref_year and cached_year != ref_year:
                diffs.append({"field": "year", "cached": r["year"], "cited": ref.get("year")})
            cached_authors = (r["authors"] or "").strip().lower()
            if cached_authors and ref_authors_str and cached_authors != ref_authors_str.lower():
                # Only flag if the FIRST author's surname differs —
                # author-order / et-al / formatting differences shouldn't
                # trigger noise. Pull the first surname of each side.
                def _first_surname(s: str) -> str:
                    s = (s or "").split(",")[0].split(";")[0].strip()
                    parts = s.split()
                    return parts[-1].lower() if parts else ""
                if _first_surname(r["authors"] or "") != _first_surname(ref_authors_str):
                    diffs.append({
                        "field": "authors",
                        "cached": (r["authors"] or "")[:120],
                        "cited": ref_authors_str[:120],
                    })
            cached_venue = (r["venue"] or "").strip().lower()
            if cached_venue and ref_venue and cached_venue != ref_venue:
                diffs.append({"field": "venue", "cached": r["venue"], "cited": ref.get("venue")})
            if diffs:
                out.append({
                    "cached_title": r["title"],
                    "cached_identity": cached_ident,
                    "diffs": diffs,
                })
        return out

    async def list_verified_references(self, limit: int = 200, offset: int = 0, q: Optional[str] = None) -> List[Dict[str, Any]]:
        """Page through the identity-keyed reference table for the Seen Refs tab."""
        # Pull last_seen_check_id / last_seen_paper_title via safe column
        # references — the columns may not exist on very old DBs since
        # they were added in v0.7.27. SELECT lists them; the ALTER
        # path in init runs first so on a real install they're present.
        select_cols = (
            "identity_key, title, authors, year, doi, arxiv_id, venue, "
            "verified_url, matched_db, status, times_seen, "
            "first_seen, last_seen, last_seen_check_id, last_seen_paper_title"
        )
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if q:
                like = f"%{q.lower()}%"
                cursor = await db.execute(
                    f"""
                    SELECT {select_cols}
                    FROM verified_reference_identity
                    WHERE LOWER(title) LIKE ? OR LOWER(authors) LIKE ? OR LOWER(doi) LIKE ?
                    ORDER BY last_seen DESC
                    LIMIT ? OFFSET ?
                    """,
                    (like, like, like, limit, offset),
                )
            else:
                cursor = await db.execute(
                    f"""
                    SELECT {select_cols}
                    FROM verified_reference_identity
                    ORDER BY last_seen DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def count_verified_references(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM verified_reference_identity")
            row = await cursor.fetchone()
            return int(row[0] if row else 0)

    async def build_reference_graph_data(
        self,
        limit: int = 400,
        min_times_seen: int = 1,
        edge_strategy: str = "shared-authors",
        max_edges: int = 4000,
    ) -> Dict[str, Any]:
        """Build {nodes, links, meta} for the 3D Seen-References library graph.

        Nodes are the deduped verified references (size ∝ times_seen, colour by
        status). Edges connect references that share a derivation signal:
          - 'shared-authors'  : ≥1 normalized surname in common
          - 'shared-venue'    : same normalized venue
        Cliques per author/venue are capped and the lowest-weight edges culled
        past ``max_edges`` so a huge library can't produce an unrenderable hairball.
        """
        import json as _json
        import re as _re

        limit = max(1, min(2000, int(limit or 400)))
        min_times_seen = max(1, int(min_times_seen or 1))

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT identity_key, title, authors, year, venue, status,
                       times_seen, doi, arxiv_id
                FROM verified_reference_identity
                WHERE times_seen >= ?
                ORDER BY times_seen DESC, last_seen DESC
                LIMIT ?
                """,
                (min_times_seen, limit),
            )
            rows = [dict(r) for r in await cursor.fetchall()]

        def _surnames(raw):
            if not raw:
                return []
            names = []
            parsed = None
            if isinstance(raw, str):
                s = raw.strip()
                if s.startswith("[") or s.startswith("{"):
                    try:
                        parsed = _json.loads(s)
                    except Exception:
                        parsed = None
                if parsed is None:
                    parsed = _re.split(r";|,| and | & ", s)
            elif isinstance(raw, list):
                parsed = raw
            out = []
            for a in (parsed or []):
                name = a.get("name") if isinstance(a, dict) else str(a)
                if not name:
                    continue
                toks = _re.sub(r"[^a-z\s\-]", "", name.lower()).split()
                toks = [t for t in toks if len(t) > 1]
                if toks:
                    out.append(toks[-1])  # surname = last token
            return out

        def _norm_venue(v):
            if not v:
                return ""
            return _re.sub(r"[^a-z0-9]", "", str(v).lower())

        nodes = []
        author_index: Dict[str, list] = {}
        venue_index: Dict[str, list] = {}
        for i, r in enumerate(rows):
            nid = r["identity_key"] or f"ref-{i}"
            nodes.append({
                "id": nid,
                "label": (r.get("title") or "(untitled)")[:120],
                "times_seen": int(r.get("times_seen") or 1),
                "status": r.get("status") or "unverified",
                "year": r.get("year"),
                "venue": r.get("venue"),
                "doi": r.get("doi"),
                "arxiv_id": r.get("arxiv_id"),
            })
            for sn in set(_surnames(r.get("authors"))):
                author_index.setdefault(sn, []).append(nid)
            nv = _norm_venue(r.get("venue"))
            if nv:
                venue_index.setdefault(nv, []).append(nid)

        # Accumulate edge weights between node pairs.
        weights: Dict[tuple, float] = {}

        def _add_clique(members, w, cap=40):
            members = members[:cap]
            for a in range(len(members)):
                for b in range(a + 1, len(members)):
                    key = (members[a], members[b]) if members[a] < members[b] else (members[b], members[a])
                    if key[0] == key[1]:
                        continue
                    weights[key] = weights.get(key, 0.0) + w

        want_authors = edge_strategy in ("shared-authors", "both", "all")
        want_venue = edge_strategy in ("shared-venue", "both", "all")
        if want_authors:
            for members in author_index.values():
                if len(members) > 1:
                    _add_clique(members, 1.0)
        if want_venue:
            for members in venue_index.values():
                if len(members) > 1:
                    _add_clique(members, 0.4)

        links = [
            {"source": k[0], "target": k[1], "weight": round(w, 2)}
            for k, w in weights.items()
        ]
        culled = 0
        if len(links) > max_edges:
            links.sort(key=lambda e: e["weight"], reverse=True)
            culled = len(links) - max_edges
            links = links[:max_edges]

        total = await self.count_verified_references()
        return {
            "nodes": nodes,
            "links": links,
            "meta": {
                "total_refs": total,
                "shown_refs": len(nodes),
                "total_edges": len(links),
                "culled_edges": culled,
                "edge_strategy": edge_strategy,
                "min_times_seen": min_times_seen,
            },
        }

    async def verified_references_recent_growth(self) -> Dict[str, int]:
        """Return how many NEW Seen-Refs rows landed in the last 24h / 7d.

        Powers the FE growth chip on the Seen References tab. Without this,
        users staring at "120 unique references seen" can't tell whether
        the count is genuinely stuck (identity-key collision bug upstream)
        or whether new refs ARE flowing in and 120 is just an old snapshot.
        Reads against existing `first_seen` column — no schema change.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cur = await db.execute(
                    "SELECT COUNT(*) FROM verified_reference_identity "
                    "WHERE first_seen >= datetime('now', '-1 day')"
                )
                row = await cur.fetchone()
                last_24h = int(row[0] if row else 0)
                cur = await db.execute(
                    "SELECT COUNT(*) FROM verified_reference_identity "
                    "WHERE first_seen >= datetime('now', '-7 days')"
                )
                row = await cur.fetchone()
                last_7d = int(row[0] if row else 0)
                return {"last_24_hours": last_24h, "last_7_days": last_7d}
        except Exception as e:
            logger.warning("verified_references_recent_growth failed: %s", e)
            return {"last_24_hours": 0, "last_7_days": 0}

    async def clear_verified_references(self) -> int:
        """Empty the global identity-keyed reference cache. Returns the
        number of rows that existed before the wipe."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            cursor = await db.execute("SELECT COUNT(*) FROM verified_reference_identity")
            row = await cursor.fetchone()
            before = int(row[0] if row else 0)
            await db.execute("DELETE FROM verified_reference_identity")
            await db.commit()
        return before

    async def delete_verified_reference(self, identity_key: str) -> bool:
        """Remove a single reference from the global identity-keyed cache.

        Counterpart to :meth:`upsert_verified_reference` — deletes just the
        one row whose ``identity_key`` matches (the same column the upsert
        keys on via ``ON CONFLICT(identity_key)``). Powers the per-reference
        'Remove from Library' control, complementing the whole-library
        :meth:`clear_verified_references` wipe.

        Idempotent / no-op safe: returns ``False`` when ``identity_key`` is
        blank or no matching row exists, ``True`` when a row was removed.
        """
        if not identity_key:
            return False
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            cursor = await db.execute(
                "DELETE FROM verified_reference_identity WHERE identity_key = ?",
                (identity_key,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def backfill_seen_references(self) -> Dict[str, Any]:
        """Manually re-run the Seen-Refs backfill on demand.

        Walks every completed/cancelled `check_history` row that has a
        `results_json` payload and upserts every reference into the global
        identity index via :meth:`upsert_verified_reference`. The upsert is
        idempotent (ON CONFLICT bumps `times_seen`), so this is safe to
        invoke repeatedly — duplicates merge, only genuinely new identity
        keys grow the count.

        Used as a recovery workaround when the per-emit hook + post-check
        backstop silently dropped references in earlier versions (the
        "120 plateau" bug). The diagnostic counters returned by this method
        also let the user see, from the FE, whether their recent checks
        legitimately produce new identity keys or whether everything is
        being treated as a duplicate.

        Returns a dict with: ``before_count``, ``after_count``,
        ``walked_checks``, ``walked_refs``, ``inserted``, ``updated``,
        ``skipped_no_identity``, ``duration_seconds``.
        """
        import time as _time
        t0 = _time.perf_counter()
        before_count = await self.count_verified_references()
        walked_checks = 0
        walked_refs = 0
        skipped_no_identity = 0
        errors = 0
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA busy_timeout=5000")
                async with db.execute(
                    "SELECT id, paper_title, results_json FROM check_history "
                    "WHERE status IN ('completed', 'cancelled') AND results_json IS NOT NULL"
                ) as ch_cur:
                    async for check_id, paper_title, results_json in ch_cur:
                        walked_checks += 1
                        if walked_checks % 100 == 0:
                            logger.info(
                                "backfill_seen_references: walked %d checks (%d refs so far)",
                                walked_checks, walked_refs,
                            )
                        if not results_json:
                            continue
                        try:
                            results = json.loads(results_json)
                        except Exception:
                            continue
                        if not isinstance(results, list):
                            continue
                        for ref in results:
                            if not isinstance(ref, dict):
                                continue
                            walked_refs += 1
                            # Pre-check the identity key so we can count
                            # "skipped" without paying the upsert's open/
                            # commit overhead for refs that would no-op
                            # anyway.
                            if not self.reference_identity_key(ref):
                                skipped_no_identity += 1
                                continue
                            try:
                                await self.upsert_verified_reference(
                                    ref,
                                    check_id=check_id,
                                    paper_title=paper_title,
                                )
                            except Exception as e:
                                # One bad ref must not abort the rest.
                                errors += 1
                                logger.debug(
                                    "backfill_seen_references: upsert failed for one ref: %s",
                                    e,
                                )
        except Exception as e:
            logger.warning("backfill_seen_references walk failed: %s", e)
        after_count = await self.count_verified_references()
        inserted = max(0, after_count - before_count)
        # "updated" = refs that had a valid identity key but didn't grow
        # the table (i.e. ON CONFLICT path). Errors are excluded so the
        # numbers add up to walked_refs cleanly.
        updated = max(
            0,
            walked_refs - skipped_no_identity - inserted - errors,
        )
        duration = _time.perf_counter() - t0
        logger.info(
            "backfill_seen_references: walked %d checks / %d refs in %.2fs "
            "(+%d new, %d updated, %d skipped no-identity, %d errors)",
            walked_checks, walked_refs, duration,
            inserted, updated, skipped_no_identity, errors,
        )
        return {
            "before_count": before_count,
            "after_count": after_count,
            "walked_checks": walked_checks,
            "walked_refs": walked_refs,
            "inserted": inserted,
            "updated": updated,
            "skipped_no_identity": skipped_no_identity,
            "errors": errors,
            "duration_seconds": round(duration, 3),
        }

    # Batch operations

    async def get_batch_checks(self, batch_id: str, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all checks belonging to a batch, optionally filtered by user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            query = """
                SELECT id, paper_title, paper_source, custom_label, timestamp,
                       total_refs, errors_count, warnings_count, suggestions_count, unverified_count,
                       hallucination_count,
                       refs_with_errors, refs_with_warnings_only, refs_verified,
                      llm_provider, llm_model, hallucination_provider, hallucination_model,
                      status, source_type, batch_id, batch_label,
                      bibliography_source_kind, original_filename,
                      ai_detection_score, ai_detection_band
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
                    SUM(hallucination_count) as total_hallucinated,
                    SUM(CASE WHEN ai_detection_band = 'high' THEN 1 ELSE 0 END) as ai_detection_high,
                    SUM(CASE WHEN ai_detection_band = 'medium' THEN 1 ELSE 0 END) as ai_detection_medium,
                    SUM(CASE WHEN ai_detection_band = 'low' THEN 1 ELSE 0 END) as ai_detection_low,
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

    @staticmethod
    def _batch_access_clause(user_id: Optional[int], team_ids: Optional[List[int]]) -> tuple[str, list]:
        """Build the WHERE fragment + params for an access-scoped batch read.

        When ``user_id`` is None (single-user mode) there is no scoping. When it
        is set, a row is visible if the requester owns it OR it is shared with a
        team the requester belongs to (``team_id`` in ``team_ids``). Mirrors the
        owner-only ``user_id = ?`` filter used by the non-team variants (R26)."""
        if user_id is None:
            return "", []
        clauses = ["user_id = ?"]
        params: list = [user_id]
        for tid in (team_ids or []):
            clauses.append("team_id = ?")
            params.append(tid)
        return " AND (" + " OR ".join(clauses) + ")", params

    async def get_batch_checks_accessible(
        self, batch_id: str, user_id: Optional[int], team_ids: Optional[List[int]] = None
    ) -> List[Dict[str, Any]]:
        """Like ``get_batch_checks`` but also returns rows shared with one of the
        requester's teams (R26). Owner rows + team-shared rows, deduped by id."""
        access_sql, access_params = self._batch_access_clause(user_id, team_ids)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            query = (
                """
                SELECT id, paper_title, paper_source, custom_label, timestamp,
                       total_refs, errors_count, warnings_count, suggestions_count, unverified_count,
                       hallucination_count,
                       refs_with_errors, refs_with_warnings_only, refs_verified,
                      llm_provider, llm_model, hallucination_provider, hallucination_model,
                      status, source_type, batch_id, batch_label, team_id,
                      bibliography_source_kind, original_filename,
                      ai_detection_score, ai_detection_band
                FROM check_history
                WHERE batch_id = ?
                """
                + access_sql
                + " ORDER BY timestamp ASC"
            )
            async with db.execute(query, (batch_id, *access_params)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_batch_summary_accessible(
        self, batch_id: str, user_id: Optional[int], team_ids: Optional[List[int]] = None
    ) -> Optional[Dict[str, Any]]:
        """Like ``get_batch_summary`` but also returns a batch shared with one of
        the requester's teams (R26)."""
        access_sql, access_params = self._batch_access_clause(user_id, team_ids)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            query = (
                """
                SELECT
                    batch_id,
                    batch_label,
                    MAX(team_id) as team_id,
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
                    SUM(hallucination_count) as total_hallucinated,
                    SUM(CASE WHEN ai_detection_band = 'high' THEN 1 ELSE 0 END) as ai_detection_high,
                    SUM(CASE WHEN ai_detection_band = 'medium' THEN 1 ELSE 0 END) as ai_detection_medium,
                    SUM(CASE WHEN ai_detection_band = 'low' THEN 1 ELSE 0 END) as ai_detection_low,
                    MIN(timestamp) as started_at
                FROM check_history
                WHERE batch_id = ?
                """
                + access_sql
                + " GROUP BY batch_id"
            )
            async with db.execute(query, (batch_id, *access_params)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def set_check_team(self, check_id: int, team_id: Optional[int]) -> bool:
        """Share (or unshare with ``None``) a check with a team. Returns True if
        a row was updated. The caller is responsible for verifying that the
        requester owns the check and belongs to the team (R26)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            cursor = await db.execute(
                "UPDATE check_history SET team_id = ? WHERE id = ?",
                (team_id, check_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def set_batch_team(
        self, batch_id: str, team_id: Optional[int], user_id: Optional[int] = None
    ) -> int:
        """Share every check in a batch with a team (or unshare with ``None``).

        Owner-scoped when ``user_id`` is set so a member can't reassign a batch
        they only have read access to. Returns the number of rows updated (R26)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            if user_id is not None:
                cursor = await db.execute(
                    "UPDATE check_history SET team_id = ? WHERE batch_id = ? AND user_id = ?",
                    (team_id, batch_id, user_id),
                )
            else:
                cursor = await db.execute(
                    "UPDATE check_history SET team_id = ? WHERE batch_id = ?",
                    (team_id, batch_id),
                )
            await db.commit()
            return cursor.rowcount

    async def get_team_checks(self, team_id: int) -> List[Dict[str, Any]]:
        """List checks shared with a team, newest first (R26)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, paper_title, paper_source, custom_label, timestamp,
                       total_refs, errors_count, warnings_count, suggestions_count, unverified_count,
                       hallucination_count,
                       refs_with_errors, refs_with_warnings_only, refs_verified,
                       status, source_type, batch_id, batch_label, team_id, user_id,
                       ai_detection_score, ai_detection_band
                FROM check_history
                WHERE team_id = ?
                ORDER BY timestamp DESC
                """,
                (team_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_check_batch_team(self, check_id: int) -> Optional[Dict[str, Any]]:
        """Return ``{batch_id, team_id}`` for a check, or None if it doesn't
        exist. Used by the realtime layer to fan a per-check result out to the
        batch's presence room (R26)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT batch_id, team_id FROM check_history WHERE id = ?",
                (check_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def cancel_batch(self, batch_id: str, user_id: Optional[int] = None) -> int:
        """Cancel every non-terminal check in a batch (in_progress, pending,
        queued, etc.). Returns count of cancelled checks.

        v0.7.51: previously this only flipped `status = 'in_progress'`
        rows. Children queued behind the concurrency limiter sat as
        `pending` and got missed — the user saw "Cancel doesn't kill
        them all at once" because the limiter then released them one
        by one, each running through extraction + verification before
        observing the cancel. Now we cancel ANYTHING that isn't
        already in a terminal state (completed, cancelled, error),
        so a Cancel All immediately stops the entire pipeline.
        """
        terminal = ("completed", "cancelled", "error")
        placeholders = ",".join("?" for _ in terminal)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            if user_id is not None:
                cursor = await db.execute(
                    f"""
                    UPDATE check_history
                    SET status = 'cancelled'
                    WHERE batch_id = ? AND user_id = ?
                          AND status NOT IN ({placeholders})
                    """,
                    (batch_id, user_id, *terminal),
                )
            else:
                cursor = await db.execute(
                    f"""
                    UPDATE check_history
                    SET status = 'cancelled'
                    WHERE batch_id = ?
                          AND status NOT IN ({placeholders})
                    """,
                    (batch_id, *terminal),
                )
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
