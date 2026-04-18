"""
FastAPI application for RefChecker Web UI
"""
from contextlib import asynccontextmanager
import asyncio
import time
import uuid
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional, Dict, Tuple
from urllib.parse import urlparse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Body, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import logging
from refchecker.__version__ import __version__
from refchecker.utils.database_config import DATABASE_BUILD_DEPENDENCIES, DATABASE_FILE_ALIASES, DATABASE_LABELS, DATABASE_UPDATE_ORDER, resolve_database_paths

# Fix Windows encoding issues with Unicode characters (e.g., Greek letters in paper titles).
# Skip this when running under pytest so we don't replace pytest's capture streams, which can
# lead to closed-file errors during teardown.
if sys.platform == 'win32' and not os.environ.get("PYTEST_CURRENT_TEST"):
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import aiosqlite
from .database import db, get_data_dir
from .websocket_manager import manager
from .refchecker_wrapper import ProgressRefChecker
from .models import CheckRequest, CheckHistoryItem
from .concurrency import init_limiter, get_limiter, set_default_max_concurrent, DEFAULT_MAX_CONCURRENT
from .auth import (
    SITE_URL,
    is_multiuser_mode,
    require_user,
    get_current_user,
    get_user_id_filter,
    get_available_providers,
    get_google_auth_url,
    get_github_auth_url,
    get_microsoft_auth_url,
    exchange_google_code,
    exchange_github_code,
    exchange_microsoft_code,
    create_access_token,
    decode_access_token,
    set_auth_cookie,
    clear_auth_cookie,
    UserInfo,
    _validate_oauth_state,
)
from .thumbnail import (
    generate_arxiv_thumbnail_async,
    generate_arxiv_preview_async,
    generate_pdf_thumbnail_async,
    generate_pdf_preview_async,
    get_pdf_storage_path,
    get_text_thumbnail_async,
    get_text_preview_async,
    get_thumbnail_cache_path,
    get_preview_cache_path
)
from .usage_tracking import (
    append_usage_event,
    build_issue_type_counts,
    clear_usage_log,
    extract_email_domain,
    get_usage_events,
    get_usage_log_path,
    get_request_metadata,
    get_usage_summary,
    infer_bibliography_source_kind,
    infer_paper_identity,
    infer_source_host,
    utcnow_sqlite,
)
from refchecker.utils.url_utils import validate_remote_fetch_url

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_FILE_BYTES = int(os.environ.get("MAX_UPLOAD_FILE_BYTES", str(25 * 1024 * 1024)))
MAX_BATCH_UPLOAD_TOTAL_BYTES = int(os.environ.get("MAX_BATCH_UPLOAD_TOTAL_BYTES", str(100 * 1024 * 1024)))
MAX_BATCH_ARCHIVE_BYTES = int(os.environ.get("MAX_BATCH_ARCHIVE_BYTES", str(50 * 1024 * 1024)))


def get_uploads_dir() -> Path:
    """Return the base uploads directory, inside the persistent data dir."""
    d = get_data_dir() / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _private_artifact_headers(extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Prevent shared caches from storing authenticated user content."""
    headers = {
        "Cache-Control": "private, no-store, max-age=0",
        "Pragma": "no-cache",
        "Vary": "Cookie",
    }
    if extra_headers:
        headers.update(extra_headers)
    return headers


def _resolve_semantic_scholar_db_path(path_value: Optional[str]) -> Optional[Path]:
    """Resolve a configured local Semantic Scholar DB path to a concrete SQLite file."""
    if not path_value:
        return None

    resolved_path = Path(path_value).expanduser()
    if resolved_path.is_dir():
        for filename in DATABASE_FILE_ALIASES["s2"]:
            default_db = resolved_path / filename
            if default_db.is_file():
                return default_db
        return None

    return resolved_path


def _resolve_local_database_directory(path_value: Optional[str]) -> Optional[Path]:
    """Resolve a shared local database directory from a configured file or directory path."""
    if not path_value:
        return None

    resolved_path = Path(path_value).expanduser()
    if resolved_path.is_dir():
        return resolved_path
    if resolved_path.suffix.lower() == ".db" and resolved_path.parent.is_dir():
        return resolved_path.parent
    return None


def _validate_local_reference_database_file(db_path: Path) -> Dict[str, object]:
    """Validate a local reference database file and return summary metadata."""
    import sqlite3

    required = {
        "paperId",
        "title",
        "normalized_paper_title",
        "authors",
        "year",
        "externalIds_DOI",
        "externalIds_ArXiv",
    }

    try:
        with sqlite3.connect(str(db_path)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(papers)").fetchall()}
            missing = required - cols
            if missing:
                raise HTTPException(status_code=400, detail=f"Database missing required columns: {', '.join(sorted(missing))}")

            indexes = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
            }
            row_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid database: {e}")

    warnings = []
    has_title_idx = any("title" in index_name.lower() for index_name in indexes)
    if not has_title_idx:
        warnings.append("No title index found — queries may be slow")

    return {
        "columns": cols,
        "row_count": row_count,
        "warnings": warnings,
    }


def _summarize_local_database_directory(directory_path: Path) -> Dict[str, object]:
    """Validate recognized local DB files in a directory and return a summary."""
    db_paths = resolve_database_paths(database_directory=str(directory_path))
    validated = {
        db_name: _validate_local_reference_database_file(Path(db_path))
        for db_name, db_path in db_paths.items()
    }
    return {
        "db_paths": db_paths,
        "validated": validated,
    }


def _read_semantic_scholar_db_snapshot(db_path: Optional[Path]) -> Optional[str]:
    """Read the stored Semantic Scholar snapshot release ID from local DB metadata."""
    if not db_path or not db_path.is_file():
        return None

    import sqlite3

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM metadata WHERE key = 'last_release_id'"
            ).fetchone()
            return row[0] if row and row[0] else None
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to read Semantic Scholar snapshot metadata from {db_path}: {e}")
        return None


async def _get_configured_semantic_scholar_db_path() -> Optional[Path]:
    """Return the configured local Semantic Scholar DB path, if any."""
    configured_path = (
        os.environ.get("REFCHECKER_DB_PATH")
        or os.environ.get("REFCHECKER_DATABASE_DIRECTORY")
        or await db.get_setting("db_path")
        or None
    )
    db_path = _resolve_semantic_scholar_db_path(configured_path)
    if not db_path:
        return None
    if not db_path.is_file():
        logger.warning(f"Skipping Semantic Scholar refresh because the configured DB was not found: {db_path}")
        return None
    return db_path


async def _get_configured_database_paths() -> Dict[str, str]:
    """Return configured local DB paths (S2 + optional DBs discovered from directory)."""
    configured_setting = os.environ.get("REFCHECKER_DB_PATH") or await db.get_setting("db_path") or None
    s2_path = await _get_configured_semantic_scholar_db_path()
    configured_s2 = str(s2_path) if s2_path else None
    database_directory = os.environ.get("REFCHECKER_DATABASE_DIRECTORY")
    if not database_directory:
        resolved_directory = _resolve_local_database_directory(configured_setting)
        database_directory = str(resolved_directory) if resolved_directory else None
    db_paths = resolve_database_paths(
        explicit_paths={
            "s2": configured_s2,
            "openalex": os.environ.get("REFCHECKER_OPENALEX_DB_PATH"),
            "crossref": os.environ.get("REFCHECKER_CROSSREF_DB_PATH"),
            "dblp": os.environ.get("REFCHECKER_DBLP_DB_PATH"),
            "acl": os.environ.get("REFCHECKER_ACL_DB_PATH"),
        },
        database_directory=database_directory,
    )
    filtered: Dict[str, str] = {}
    for name, path in db_paths.items():
        if os.path.isfile(path):
            filtered[name] = path
        else:
            logger.warning(
                "Configured local %s DB path was not found: %s",
                DATABASE_LABELS.get(name, name),
                path,
            )
    return filtered


async def _get_configured_cache_dir() -> Optional[str]:
    """Return the configured shared cache directory, if any."""
    configured_dir = os.environ.get('REFCHECKER_CACHE_DIR') or await db.get_setting("cache_dir")
    cache_dir = Path(configured_dir).expanduser() if configured_dir else get_data_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir)


async def _run_semantic_scholar_refresh_subprocess(db_path: Path) -> None:
    """Refresh the configured local Semantic Scholar DB in a background subprocess."""
    await _run_database_refresh_subprocess('s2', db_path)


async def _run_database_refresh_subprocess(db_name: str, db_path: Path) -> None:
    """Refresh a configured local database in a background subprocess when supported."""
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "update_local_database.py"
    if not script_path.is_file():
        logger.error(f"Local database refresh script not found: {script_path}")
        return

    command = [
        sys.executable,
        str(script_path),
        "--database",
        db_name,
        "--db-path",
        str(db_path),
    ]
    api_key = os.environ.get('SEMANTIC_SCHOLAR_API_KEY')
    if db_name == 's2' and api_key:
        command.extend(["--api-key", api_key])
    openalex_since = os.environ.get('REFCHECKER_OPENALEX_SINCE')
    if db_name == 'openalex' and openalex_since:
        command.extend(['--openalex-since', openalex_since])
    openalex_min_year = os.environ.get('REFCHECKER_OPENALEX_MIN_YEAR')
    if db_name == 'openalex' and openalex_min_year:
        command.extend(['--openalex-min-year', openalex_min_year])

    logger.info(f"Launching background {DATABASE_LABELS.get(db_name, db_name)} refresh for {db_path}")
    process = await asyncio.create_subprocess_exec(*command, cwd=str(repo_root))
    return_code = await process.wait()
    if return_code == 0:
        logger.info(f"Background {DATABASE_LABELS.get(db_name, db_name)} refresh completed successfully for {db_path}")
        return
    logger.error(f"Background {DATABASE_LABELS.get(db_name, db_name)} refresh failed for {db_path} with exit code {return_code}")


async def _schedule_semantic_scholar_refresh() -> Optional[asyncio.Task]:
    """Schedule a non-blocking local Semantic Scholar DB refresh when configured."""
    db_path = await _get_configured_semantic_scholar_db_path()
    if not db_path:
        return None

    task = asyncio.create_task(
        _run_semantic_scholar_refresh_subprocess(db_path),
        name="semantic-scholar-db-refresh",
    )
    logger.info(f"Scheduled background Semantic Scholar refresh for {db_path}")
    return task


async def _schedule_database_refreshes() -> Dict[str, asyncio.Task]:
    """Schedule non-blocking refreshes for all discovered local databases."""
    db_paths = await _get_configured_database_paths()
    tasks: Dict[str, asyncio.Task] = {}

    async def run_with_dependencies(
        db_name: str,
        db_path: str,
        dependency_names: Tuple[str, ...],
    ) -> None:
        for dependency_name in dependency_names:
            dependency_task = tasks.get(dependency_name)
            if dependency_task is None:
                continue
            try:
                await dependency_task
            except Exception as exc:
                logger.warning(
                    "Background refresh dependency %s failed before %s: %s",
                    dependency_name,
                    db_name,
                    exc,
                )
        await _run_database_refresh_subprocess(db_name, Path(db_path))

    scheduled_names = set()
    for db_name in DATABASE_UPDATE_ORDER:
        db_path = db_paths.get(db_name)
        if not db_path:
            continue
        dependency_names = tuple(
            dependency_name
            for dependency_name in DATABASE_BUILD_DEPENDENCIES.get(db_name, ())
            if dependency_name in db_paths
        )
        task = asyncio.create_task(
            run_with_dependencies(db_name, db_path, dependency_names),
            name=f"db-refresh-{db_name}",
        )
        tasks[db_name] = task
        scheduled_names.add(db_name)
        if dependency_names:
            logger.info(
                "Scheduled background refresh for %s DB at %s after %s",
                DATABASE_LABELS.get(db_name, db_name),
                db_path,
                ", ".join(DATABASE_LABELS.get(name, name) for name in dependency_names),
            )
        else:
            logger.info(f"Scheduled background refresh for {DATABASE_LABELS.get(db_name, db_name)} DB at {db_path}")

    for db_name, db_path in sorted(db_paths.items()):
        if db_name in scheduled_names:
            continue
        task = asyncio.create_task(
            run_with_dependencies(db_name, db_path, ()),
            name=f"db-refresh-{db_name}",
        )
        tasks[db_name] = task
        logger.info(f"Scheduled background refresh for {DATABASE_LABELS.get(db_name, db_name)} DB at {db_path}")
    return tasks


def _ensure_allowed_web_llm_provider(provider_name: Optional[str]) -> None:
    """Reject web-only providers that are unsafe in multi-user deployments."""
    normalized = (provider_name or "").strip().lower()
    if is_multiuser_mode() and normalized == "vllm":
        raise HTTPException(
            status_code=403,
            detail="vLLM is only supported in single-user local deployments",
        )


def _require_admin(current_user: UserInfo) -> None:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")


async def _save_upload_file(upload: UploadFile, dest_path: Path, max_bytes: int) -> int:
    """Persist an uploaded file with a hard byte cap enforced while streaming."""
    total_bytes = 0
    try:
        with open(dest_path, "wb") as out_file:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds maximum size of {max_bytes // (1024 * 1024)} MB",
                    )
                out_file.write(chunk)
    except Exception:
        if dest_path.exists():
            dest_path.unlink()
        raise
    return total_bytes


def _extract_zip_batch_files(zip_path: Path, uploads_dir: Path, batch_id: str, max_batch_size: int) -> list[dict[str, str]]:
    """Extract supported files from a ZIP archive with strict file-count and byte caps."""
    import zipfile

    files_to_process: list[dict[str, str]] = []
    created_paths: list[Path] = []
    total_bytes = 0
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for member in zf.infolist():
                name = member.filename
                if member.is_dir() or name.startswith('__') or '/.' in name or '\\.' in name:
                    continue

                lower_name = name.lower()
                if not any(lower_name.endswith(ext) for ext in ['.pdf', '.txt', '.tex', '.bib', '.bbl']):
                    continue
                if len(files_to_process) >= max_batch_size:
                    break
                if member.file_size > MAX_UPLOAD_FILE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Archive entry '{os.path.basename(name)}' exceeds maximum size of {MAX_UPLOAD_FILE_BYTES // (1024 * 1024)} MB",
                    )

                total_bytes += member.file_size
                if total_bytes > MAX_BATCH_UPLOAD_TOTAL_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Extracted archive content exceeds maximum size of {MAX_BATCH_UPLOAD_TOTAL_BYTES // (1024 * 1024)} MB",
                    )

                filename = os.path.basename(name)
                dest_path = uploads_dir / f"{batch_id}_{len(files_to_process) + 1}_{filename}"
                extracted_bytes = 0
                try:
                    with zf.open(member, 'r') as src, open(dest_path, 'wb') as dest:
                        while True:
                            chunk = src.read(UPLOAD_CHUNK_SIZE)
                            if not chunk:
                                break
                            extracted_bytes += len(chunk)
                            if extracted_bytes > MAX_UPLOAD_FILE_BYTES:
                                raise HTTPException(
                                    status_code=413,
                                    detail=f"Archive entry '{filename}' exceeds maximum size of {MAX_UPLOAD_FILE_BYTES // (1024 * 1024)} MB",
                                )
                            dest.write(chunk)
                except Exception:
                    if dest_path.exists():
                        dest_path.unlink()
                    raise

                created_paths.append(dest_path)
                files_to_process.append({
                    'path': str(dest_path),
                    'filename': filename,
                })
    except Exception:
        for path in created_paths:
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        raise

    return files_to_process


# Pydantic models for requests
class LLMConfigCreate(BaseModel):
    name: str
    provider: str
    model: Optional[str] = None
    api_key: Optional[str] = None
    endpoint: Optional[str] = None


class LLMConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    endpoint: Optional[str] = None


class LLMConfigValidate(BaseModel):
    """Model for validating LLM config without requiring name"""
    provider: str
    model: Optional[str] = None
    api_key: Optional[str] = None
    endpoint: Optional[str] = None


class CheckLabelUpdate(BaseModel):
    custom_label: str


class BatchLabelUpdate(BaseModel):
    batch_label: str


class BatchUrlsRequest(BaseModel):
    """Request model for batch URL submission"""
    urls: list[str]
    batch_label: Optional[str] = None
    llm_config_id: Optional[int] = None
    llm_provider: str = "anthropic"
    llm_model: Optional[str] = None
    use_llm: bool = True
    api_key: Optional[str] = None
    semantic_scholar_api_key: Optional[str] = None


# Create FastAPI app
async def _run_startup_tasks() -> None:
    """Initialize persistent services used by the API."""
    await db.init_db()
    logger.info(f"Usage telemetry log file: {get_usage_log_path()}")

    try:
        if await db.has_setting("semantic_scholar_api_key"):
            await db.delete_setting("semantic_scholar_api_key")
            logger.info("Removed deprecated server-side Semantic Scholar API key")
    except Exception as e:
        logger.warning(f"Failed to clear deprecated Semantic Scholar key: {e}")

    try:
        concurrency_setting = await db.get_setting("max_concurrent_checks")
        if concurrency_setting and concurrency_setting.isdigit():
            max_concurrent = int(concurrency_setting)
        else:
            max_concurrent = DEFAULT_MAX_CONCURRENT
            if concurrency_setting:
                logger.warning(f"Resetting corrupt concurrency setting to default ({DEFAULT_MAX_CONCURRENT})")
                await db.set_setting("max_concurrent_checks", str(DEFAULT_MAX_CONCURRENT))
        await init_limiter(max_concurrent)
        logger.info(f"Initialized global concurrency limiter with max={max_concurrent}")
    except Exception as e:
        logger.warning(f"Failed to load concurrency setting, using default: {e}")
        await init_limiter(DEFAULT_MAX_CONCURRENT)

    try:
        stale = await db.cancel_stale_in_progress()
        if stale:
            logger.info(f"Cancelled {stale} stale in-progress checks on startup")
    except Exception as e:
        logger.error(f"Failed to cancel stale checks: {e}")
    logger.info("Database initialized")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _run_startup_tasks()

    # In multiuser mode, pre-start GROBID so users without LLM keys can extract refs
    if is_multiuser_mode():
        try:
            from refchecker.utils.grobid import ensure_grobid_running
            grobid_ok = await asyncio.to_thread(ensure_grobid_running)
            if grobid_ok:
                logger.info("GROBID is available for users without LLM keys")
            else:
                logger.warning("GROBID not available — users without LLM keys will not be able to extract PDF references")
        except Exception as e:
            logger.warning(f"Failed to start GROBID: {e}")

    refresh_tasks = await _schedule_database_refreshes()
    app.state.database_refresh_tasks = refresh_tasks
    app.state.semantic_scholar_refresh_task = refresh_tasks.get("s2")
    yield


app = FastAPI(title="RefChecker Web UI API", version="1.0.0", lifespan=lifespan)

# Static files directory for bundled frontend
STATIC_DIR = Path(__file__).parent / "static"

# Configure CORS — include SITE_URL origin plus standard dev origins
_SITE_URL = os.environ.get("SITE_URL", "")
_cors_origins = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:5174", "http://localhost:5175",
    "http://127.0.0.1:5174", "http://127.0.0.1:5175",
    "http://localhost:8000", "http://127.0.0.1:8000",
]
if _SITE_URL and _SITE_URL not in _cors_origins:
    _cors_origins.append(_SITE_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Track active check sessions
active_checks = {}

# Per-user concurrent check tracking
_user_active_checks: Dict[int, int] = {}
_user_active_checks_lock = asyncio.Lock()
MAX_CHECKS_PER_USER = int(os.environ.get("MAX_CHECKS_PER_USER", "3"))


async def _acquire_user_check_slot(user_id: int) -> bool:
    if user_id is None or user_id == 0:
        return True  # opt-out sentinel: single-user mode (None) or unauthenticated recheck (0)
    async with _user_active_checks_lock:
        current = _user_active_checks.get(user_id, 0)
        if current >= MAX_CHECKS_PER_USER:
            return False
        _user_active_checks[user_id] = current + 1
        return True


async def _release_user_check_slot(user_id: int) -> None:
    if user_id is None or user_id == 0:
        return  # opt-out sentinel: single-user mode (None) or unauthenticated recheck (0)
    async with _user_active_checks_lock:
        current = _user_active_checks.get(user_id, 0)
        _user_active_checks[user_id] = max(0, current - 1)


def _session_id_for_check(check_id: int) -> Optional[str]:
    """Helper to find the session_id for an in-progress check."""
    for session_id, meta in active_checks.items():
        if meta.get("check_id") == check_id:
            return session_id
    return None


async def _log_usage_event_safe(
    event_type: str,
    *,
    current_user: Optional[UserInfo] = None,
    user_id: Optional[int] = None,
    provider: Optional[str] = None,
    email_domain: Optional[str] = None,
    connection=None,
    check_id: Optional[int] = None,
    session_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    source_type: Optional[str] = None,
    source_value: Optional[str] = None,
    paper_title: Optional[str] = None,
    paper_key: Optional[str] = None,
    source_host: Optional[str] = None,
    status_code: Optional[int] = None,
    reason_code: Optional[str] = None,
    payload: Optional[dict] = None,
) -> None:
    """Best-effort wrapper around the structured usage event logger."""
    try:
        request_metadata = get_request_metadata(connection)
        identity = infer_paper_identity(source_value, paper_title=paper_title, source_type=source_type)
        resolved_user_id = user_id
        resolved_provider = provider
        resolved_email_domain = email_domain

        if current_user is not None:
            if resolved_user_id is None:
                resolved_user_id = get_user_id_filter(current_user)
            if resolved_provider is None:
                resolved_provider = current_user.provider
            if resolved_email_domain is None:
                resolved_email_domain = extract_email_domain(current_user.email)

        await append_usage_event({
            "event_type": event_type,
            "occurred_at": utcnow_sqlite(),
            "user_id": resolved_user_id,
            "check_id": check_id,
            "session_id": session_id,
            "batch_id": batch_id,
            "provider": resolved_provider,
            "source_type": source_type,
            "source_host": source_host or identity.get("source_host"),
            "paper_title": paper_title,
            "paper_identifier_type": identity.get("paper_identifier_type"),
            "paper_identifier_value": identity.get("paper_identifier_value"),
            "paper_key": paper_key or identity.get("paper_key"),
            "request_id": request_metadata.get("request_id"),
            "email_domain": resolved_email_domain,
            "client_ip_hash": request_metadata.get("client_ip_hash"),
            "user_agent_hash": request_metadata.get("user_agent_hash"),
            "status_code": status_code,
            "reason_code": reason_code,
            "payload": payload or {},
        })
    except Exception as exc:
        logger.warning("Failed to write usage event %s: %s", event_type, exc)


async def _get_owned_check_or_404(check_id: int, current_user: UserInfo) -> dict:
    """Return a check only if it belongs to the current user in multi-user mode."""
    user_id = get_user_id_filter(current_user)
    check = await db.get_check_by_id(check_id, user_id=user_id)
    if not check:
        raise HTTPException(status_code=404, detail="Check not found")
    return check


async def _get_owned_batch_or_404(batch_id: str, current_user: UserInfo) -> tuple[dict, list[dict]]:
    """Return a batch summary and checks only if they belong to the current user."""
    user_id = get_user_id_filter(current_user)
    summary = await db.get_batch_summary(batch_id, user_id=user_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Batch not found")
    checks = await db.get_batch_checks(batch_id, user_id=user_id)
    return summary, checks


@app.get("/")
async def root():
    """Serve frontend if available, otherwise return API health check"""
    # If static frontend is bundled, serve it
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(
            str(index_path),
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )
    # Otherwise return API health check
    return {"status": "ok", "message": "RefChecker Web UI API"}


@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/api/version")
async def version():
    """Return server/CLI version from refchecker package."""
    return {"version": __version__}


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

_EXCHANGE_FNS = {
    "google": (get_google_auth_url, exchange_google_code),
    "github": (get_github_auth_url, exchange_github_code),
    "microsoft": (get_microsoft_auth_url, exchange_microsoft_code),
}


@app.get("/api/auth/providers")
async def auth_providers():
    """Return which OAuth providers are configured."""
    return {"providers": get_available_providers(), "multiuser": is_multiuser_mode()}


@app.get("/api/auth/login/{provider}")
async def auth_login(provider: str, request: Request):
    """Redirect to the OAuth authorization URL for the given provider."""
    entry = _EXCHANGE_FNS.get(provider)
    if not entry:
        await _log_usage_event_safe(
            "auth.login_failed",
            connection=request,
            provider=provider,
            status_code=404,
            reason_code="unknown_provider",
        )
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    url_fn, _ = entry
    await _log_usage_event_safe(
        "auth.login_started",
        connection=request,
        provider=provider,
        payload={"multiuser": is_multiuser_mode()},
    )
    return RedirectResponse(url=url_fn(request))


@app.get("/api/auth/callback/{provider}")
async def auth_callback(
    provider: str,
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Handle OAuth callback: exchange code, set cookie, redirect to SITE_URL."""
    site = SITE_URL or "/"
    entry = _EXCHANGE_FNS.get(provider)
    if not entry:
        await _log_usage_event_safe(
            "auth.login_failed",
            connection=request,
            provider=provider,
            status_code=404,
            reason_code="unknown_provider",
        )
        return RedirectResponse(url=f"{site}?auth_error=unknown_provider")

    if error or not code or not state:
        await _log_usage_event_safe(
            "auth.login_failed",
            connection=request,
            provider=provider,
            status_code=400,
            reason_code=error or "missing_code",
        )
        return RedirectResponse(url=f"{site}?auth_error={error or 'missing_code'}")
    if not _validate_oauth_state(state, provider):
        await _log_usage_event_safe(
            "auth.login_failed",
            connection=request,
            provider=provider,
            status_code=400,
            reason_code="invalid_state",
        )
        return RedirectResponse(url=f"{site}?auth_error=invalid_state")

    _, exchange_fn = entry
    user_data = await exchange_fn(code, request)
    if not user_data:
        await _log_usage_event_safe(
            "auth.login_failed",
            connection=request,
            provider=provider,
            status_code=502,
            reason_code="exchange_failed",
        )
        return RedirectResponse(url=f"{site}?auth_error=exchange_failed")

    user_id = await db.create_or_update_user(**user_data)
    await _log_usage_event_safe(
        "auth.login_succeeded",
        connection=request,
        user_id=user_id,
        provider=user_data.get("provider") or provider,
        email_domain=extract_email_domain(user_data.get("email")),
        status_code=200,
        payload={"is_admin": bool((await db.get_user_by_id(user_id) or {}).get("is_admin"))},
    )
    token = create_access_token(user_id, user_data.get("email"), user_data.get("name"))
    response = RedirectResponse(url=site)
    set_auth_cookie(response, token)
    return response


@app.get("/api/auth/me")
async def auth_me(current_user: UserInfo = Depends(require_user)):
    """Return the currently authenticated user."""
    return {
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name,
            "avatar_url": current_user.avatar_url,
            "provider": current_user.provider,
            "is_admin": current_user.is_admin,
        }
    }


@app.post("/api/auth/logout")
async def auth_logout(
    request: Request = None,
    current_user: UserInfo = Depends(require_user),
):
    """Clear the auth cookie and log out."""
    from fastapi.responses import JSONResponse
    await _log_usage_event_safe(
        "auth.logout",
        current_user=current_user,
        connection=request,
        status_code=200,
    )
    response = JSONResponse(content={"ok": True})
    clear_auth_cookie(response)
    return response


@app.websocket("/api/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time updates"""
    # In single-user mode (no OAuth providers), skip auth check
    if get_available_providers():
        token = websocket.cookies.get("rc_auth")
        if not token:
            await _log_usage_event_safe(
                "auth.websocket_denied",
                connection=websocket,
                session_id=session_id,
                status_code=4001,
                reason_code="missing_token",
            )
            await websocket.close(code=4001, reason="Unauthorized")
            return
        token_data = decode_access_token(token)
        if not token_data:
            await _log_usage_event_safe(
                "auth.websocket_denied",
                connection=websocket,
                session_id=session_id,
                status_code=4001,
                reason_code="invalid_token",
            )
            await websocket.close(code=4001, reason="Invalid token")
            return
        active = active_checks.get(session_id)
        if not active:
            # Session no longer exists (already completed/cancelled) — close
            # silently without logging a usage event to avoid log spam from
            # stale frontend reconnection attempts.
            await websocket.close(code=4003, reason="Session not found")
            return
        if active.get("user_id") != token_data.user_id:
            await _log_usage_event_safe(
                "auth.websocket_denied",
                connection=websocket,
                user_id=token_data.user_id,
                session_id=session_id,
                status_code=4001,
                reason_code="wrong_user",
            )
            await websocket.close(code=4001, reason="Unauthorized")
            return
    await manager.connect(websocket, session_id)
    try:
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            # Echo back or handle commands if needed
            logger.debug(f"Received WebSocket message: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
        logger.info(f"WebSocket disconnected: {session_id}")


@app.post("/api/check")
async def start_check(
    source_type: str = Form(...),
    source_value: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    source_text: Optional[str] = Form(None),
    llm_config_id: Optional[int] = Form(None),
    llm_provider: str = Form("anthropic"),
    llm_model: Optional[str] = Form(None),
    use_llm: bool = Form(True),
    api_key: Optional[str] = Form(None),
    semantic_scholar_api_key: Optional[str] = Form(None),
    current_user: UserInfo = Depends(require_user),
    http_request: Request = None,
):
    """
    Start a new reference check

    Args:
        source_type: 'url' or 'file'
        source_value: URL or ArXiv ID (for url type)
        file: Uploaded file (for file type)
        api_key: API key from client (sent per-request, never stored)
        semantic_scholar_api_key: SS API key from client (sent per-request, never stored)
        llm_config_id: ID of the LLM config to use (for provider/model/endpoint)
        llm_provider: LLM provider to use
        llm_model: Specific model to use
        use_llm: Whether to use LLM for extraction

    Returns:
        Session ID for tracking progress via WebSocket
    """
    slot_acquired = False
    try:
        # Generate session ID
        session_id = str(uuid.uuid4())
        check_started_at = utcnow_sqlite()

        user_id = get_user_id_filter(current_user)

        # api_key from form (client localStorage) takes precedence over config stored key
        effective_api_key = api_key
        endpoint = None
        logger.info(f"API key from form: {'present' if api_key else 'MISSING'}, use_llm={use_llm}, provider={llm_provider}")
        if llm_config_id and use_llm:
            config = await db.get_llm_config_by_id(llm_config_id, user_id=user_id)
            if config:
                if not effective_api_key:
                    effective_api_key = config.get('api_key')
                    logger.info(f"API key from DB config: {'present' if effective_api_key else 'MISSING'}")
                endpoint = config.get('endpoint')
                llm_provider = config.get('provider', llm_provider)
                llm_model = config.get('model') or llm_model
                logger.info(f"Using LLM config {llm_config_id}: {llm_provider}/{llm_model}")
            else:
                logger.warning(f"LLM config {llm_config_id} not found")
        if use_llm:
            _ensure_allowed_web_llm_provider(llm_provider)
        logger.info(f"Effective API key resolved: {'present' if effective_api_key else 'MISSING'}, SS key: {'present' if semantic_scholar_api_key else 'MISSING'}")

        # Handle file upload or pasted text
        paper_source = source_value
        paper_title = "Processing..."  # Placeholder title until we parse the paper
        original_filename = None  # Only set for file uploads
        input_bytes = None
        if source_type == "file" and file:
            # Save uploaded file to user-isolated uploads directory
            uploads_dir = get_uploads_dir() / str(user_id)
            uploads_dir.mkdir(parents=True, exist_ok=True)
            # Use check-specific naming to avoid conflicts
            safe_filename = file.filename.replace("/", "_").replace("\\", "_")
            file_path = uploads_dir / f"{session_id}_{safe_filename}"
            input_bytes = await _save_upload_file(file, file_path, MAX_UPLOAD_FILE_BYTES)
            paper_source = str(file_path)
            paper_title = file.filename
            original_filename = file.filename  # Store original filename
        elif source_type == "text":
            if not source_text:
                raise HTTPException(status_code=400, detail="No text provided")
            # Normalize line endings - remove all \r to prevent double carriage returns
            # Browser may send \r\n, and Windows file writing can add extra \r
            normalized_text = source_text.replace('\r\n', '\n').replace('\r', '\n')
            # Save pasted text to a file for later retrieval and thumbnail generation
            text_dir = Path(tempfile.gettempdir()) / "refchecker_texts"
            text_dir.mkdir(parents=True, exist_ok=True)
            text_file_path = text_dir / f"pasted_{session_id}.txt"
            with open(text_file_path, "w", encoding="utf-8", newline='\n') as f:
                f.write(normalized_text)
            paper_source = str(text_file_path)
            paper_title = "Pasted Text"
            input_bytes = len(normalized_text.encode("utf-8"))
        elif source_type == "url":
            parsed_source = urlparse(source_value or "")
            if parsed_source.scheme or parsed_source.netloc:
                try:
                    validate_remote_fetch_url(source_value)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            paper_title = source_value
            input_bytes = len((source_value or "").encode("utf-8"))

        if not paper_source:
            raise HTTPException(status_code=400, detail="No source provided")

        source_identity = infer_paper_identity(
            source_value if source_type == "url" else None,
            paper_title=paper_title,
            source_type=source_type,
        )

        # Rate limiting: enforce per-user concurrent check limit
        if not await _acquire_user_check_slot(user_id):
            await _log_usage_event_safe(
                "check.rate_limited",
                current_user=current_user,
                connection=http_request,
                session_id=session_id,
                source_type=source_type,
                source_value=source_value if source_type == "url" else None,
                source_host=source_identity.get("source_host"),
                status_code=429,
                reason_code="max_concurrent_checks_reached",
                payload={
                    "max_checks_per_user": MAX_CHECKS_PER_USER,
                    "use_llm": use_llm,
                },
            )
            raise HTTPException(
                status_code=429,
                detail=f"Maximum concurrent checks ({MAX_CHECKS_PER_USER}) reached"
            )
        slot_acquired = True

        # Create history entry immediately (in_progress status)
        check_id = await db.create_pending_check(
            paper_title=paper_title,
            paper_source=paper_source,
            source_type=source_type,
            llm_provider=llm_provider if use_llm else None,
            llm_model=llm_model if use_llm else None,
            original_filename=original_filename,
            user_id=user_id,
            started_at=check_started_at,
            input_bytes=input_bytes,
            source_host=source_identity.get("source_host"),
            paper_identifier_type=source_identity.get("paper_identifier_type"),
            paper_identifier_value=source_identity.get("paper_identifier_value"),
            paper_key=source_identity.get("paper_key"),
            batch_size=1,
        )
        logger.info(f"Created pending check with ID {check_id}")

        await _log_usage_event_safe(
            "check.started",
            current_user=current_user,
            connection=http_request,
            check_id=check_id,
            session_id=session_id,
            source_type=source_type,
            source_value=source_value if source_type == "url" else None,
            paper_title=paper_title,
            source_host=source_identity.get("source_host"),
            paper_key=source_identity.get("paper_key"),
            status_code=202,
            payload={
                "use_llm": use_llm,
                "llm_provider": llm_provider if use_llm else None,
                "llm_model": llm_model if use_llm else None,
                "input_bytes": input_bytes,
                "semantic_scholar_key_present": bool(semantic_scholar_api_key),
                "original_filename_ext": Path(original_filename).suffix.lower() if original_filename else None,
            },
        )

        # Start check in background
        cancel_event = asyncio.Event()
        task = asyncio.create_task(
            run_check(session_id, check_id, paper_source, source_type, llm_provider, llm_model, effective_api_key, endpoint, use_llm, cancel_event, user_id, semantic_scholar_api_key=semantic_scholar_api_key)
        )
        slot_acquired = False  # ownership transferred to run_check's finally block
        active_checks[session_id] = {"task": task, "cancel_event": cancel_event, "check_id": check_id, "user_id": user_id}

        return {
            "session_id": session_id,
            "check_id": check_id,
            "message": "Check started",
            "source": paper_source
        }

    except HTTPException:
        if slot_acquired:
            await _release_user_check_slot(user_id)
        raise
    except Exception as e:
        if slot_acquired:
            await _release_user_check_slot(user_id)
        logger.error(f"Error starting check: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def run_check(
    session_id: str,
    check_id: int,
    paper_source: str,
    source_type: str,
    llm_provider: str,
    llm_model: Optional[str],
    api_key: Optional[str],
    endpoint: Optional[str],
    use_llm: bool,
    cancel_event: asyncio.Event,
    user_id: int = 0,
    semantic_scholar_api_key: Optional[str] = None,
):
    """
    Run reference check in background and emit progress updates

    Args:
        session_id: Unique session ID
        check_id: Database ID for this check
        paper_source: Paper URL, ArXiv ID, or file path
        source_type: 'url' or 'file'
        llm_provider: LLM provider
        llm_model: Specific model
        api_key: API key for the LLM provider
        use_llm: Whether to use LLM
        semantic_scholar_api_key: Semantic Scholar API key (sent per-request from client)
    """
    user_row = await db.get_user_by_id(user_id) if user_id else None
    provider = user_row.get("provider") if user_row else None
    email_domain = extract_email_domain(user_row.get("email")) if user_row else None
    start_monotonic = time.perf_counter()
    try:
        # Resolve local checker database paths from environment/settings
        db_paths = await _get_configured_database_paths()
        db_path = db_paths.get("s2")

        # Resolve cache directory from environment or settings
        cache_dir = await _get_configured_cache_dir()

        # Wait for WebSocket to connect (give client time to establish connection)
        logger.info(f"Waiting for WebSocket connection for session {session_id}...")
        for _ in range(30):  # Wait up to 3 seconds
            if session_id in manager.active_connections:
                logger.info(f"WebSocket connected for session {session_id}")
                break
            await asyncio.sleep(0.1)
        else:
            logger.warning(f"WebSocket not connected after 3s for session {session_id}, proceeding anyway")

        # Track accumulated results for incremental saving
        accumulated_results = []
        last_save_count = 0  # Track when we last saved to reduce lock contention

        # Create progress callback that also saves to DB
        async def progress_callback(event_type: str, data: dict):
            nonlocal accumulated_results, last_save_count
            # Always include check_id so the frontend can reliably route messages
            data_with_id = {**data, "check_id": check_id}
            await manager.send_message(session_id, event_type, data_with_id)
            
            # Save reference results to DB as they come in
            if event_type == "reference_result":
                accumulated_results.append(data)
            
            # Save progress to DB every 3 references to reduce lock contention
            if event_type == "summary_update":
                current_count = len(accumulated_results)
                # Save every 3 references, or on first result
                if current_count - last_save_count >= 3 or (current_count == 1 and last_save_count == 0):
                    try:
                        await db.update_check_progress(
                            check_id=check_id,
                            total_refs=data.get("total_refs", 0),
                            errors_count=data.get("errors_count", 0),
                            warnings_count=data.get("warnings_count", 0),
                            suggestions_count=data.get("suggestions_count", 0),
                            unverified_count=data.get("unverified_count", 0),
                            hallucination_count=data.get("hallucination_count", 0),
                            refs_with_errors=data.get("refs_with_errors", 0),
                            refs_with_warnings_only=data.get("refs_with_warnings_only", 0),
                            refs_verified=data.get("refs_verified", 0),
                            results=accumulated_results
                        )
                        last_save_count = current_count
                    except Exception as e:
                        logger.warning(f"Failed to save progress: {e}")

        # Create title update callback
        async def title_update_callback(check_id: int, paper_title: str):
            await db.update_check_title(check_id, paper_title)
            logger.info(f"Updated paper title for check {check_id}: {paper_title}")

        # Create bibliography source callback to save bbl/bib content
        async def bibliography_source_callback(check_id: int, content: str, arxiv_id: str):
            try:
                # Save the bibliography content to a file
                bib_dir = get_uploads_dir() / "bibliography"
                bib_dir.mkdir(parents=True, exist_ok=True)
                bib_path = bib_dir / f"{check_id}_{arxiv_id}_bibliography.txt"
                with open(bib_path, "w", encoding="utf-8") as f:
                    f.write(content)
                # Update the database with the path
                await db.update_check_bibliography_source(check_id, str(bib_path))
                logger.info(f"Saved bibliography source for check {check_id}: {bib_path}")
            except Exception as e:
                logger.warning(f"Failed to save bibliography source: {e}")

        # Create checker with progress callback
        checker = ProgressRefChecker(
            llm_provider=llm_provider,
            llm_model=llm_model,
            api_key=api_key,
            endpoint=endpoint,
            use_llm=use_llm,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            check_id=check_id,
            title_update_callback=title_update_callback,
            bibliography_source_callback=bibliography_source_callback,
            semantic_scholar_api_key=semantic_scholar_api_key,
            db_path=db_path,
            db_paths=db_paths,
            cache_dir=cache_dir,
        )

        # Run the check
        result = await checker.check_paper(paper_source, source_type)

        # For file uploads, don't overwrite the original filename with "Unknown Paper"
        # The correct title was already set in the database when the check was created
        result_title = result["paper_title"]
        if source_type == "file" and result_title == "Unknown Paper":
            result_title = None  # Don't update title
        
        # Update the existing check entry with results
        completed_at = utcnow_sqlite()
        duration_ms = int((time.perf_counter() - start_monotonic) * 1000)
        issue_type_counts = build_issue_type_counts(result["references"])
        paper_identity = infer_paper_identity(
            result.get("paper_source") or paper_source,
            paper_title=result.get("paper_title"),
            source_type=source_type,
        )
        cache_hit = result.get("extraction_method") == "cache"
        bibliography_source_kind = infer_bibliography_source_kind(result.get("extraction_method"))
        await db.update_check_results(
            check_id=check_id,
            paper_title=result_title,
            total_refs=result["summary"]["total_refs"],
            errors_count=result["summary"]["errors_count"],
            warnings_count=result["summary"]["warnings_count"],
            suggestions_count=result["summary"].get("suggestions_count", 0),
            unverified_count=result["summary"]["unverified_count"],
            hallucination_count=result["summary"].get("hallucination_count", 0),
            refs_with_errors=result["summary"].get("refs_with_errors", 0),
            refs_with_warnings_only=result["summary"].get("refs_with_warnings_only", 0),
            refs_verified=result["summary"].get("refs_verified", 0),
            results=result["references"],
            status='completed',
            extraction_method=result.get("extraction_method"),
            completed_at=completed_at,
            duration_ms=duration_ms,
            paper_identifier_type=paper_identity.get("paper_identifier_type"),
            paper_identifier_value=paper_identity.get("paper_identifier_value"),
            paper_key=paper_identity.get("paper_key"),
            issue_type_counts=issue_type_counts,
            cache_hit=cache_hit,
            bibliography_source_kind=bibliography_source_kind,
        )

        await _log_usage_event_safe(
            "check.completed",
            user_id=user_id,
            provider=provider,
            email_domain=email_domain,
            check_id=check_id,
            session_id=session_id,
            source_type=source_type,
            source_value=paper_source if source_type == "url" else None,
            paper_title=result.get("paper_title"),
            paper_key=paper_identity.get("paper_key"),
            source_host=paper_identity.get("source_host"),
            status_code=200,
            payload={
                "duration_ms": duration_ms,
                "total_refs": result["summary"]["total_refs"],
                "errors_count": result["summary"]["errors_count"],
                "warnings_count": result["summary"]["warnings_count"],
                "suggestions_count": result["summary"].get("suggestions_count", 0),
                "unverified_count": result["summary"]["unverified_count"],
                "hallucination_count": result["summary"].get("hallucination_count", 0),
                "refs_with_errors": result["summary"].get("refs_with_errors", 0),
                "refs_with_warnings_only": result["summary"].get("refs_with_warnings_only", 0),
                "refs_verified": result["summary"].get("refs_verified", 0),
                "extraction_method": result.get("extraction_method"),
                "bibliography_source_kind": bibliography_source_kind,
                "cache_hit": cache_hit,
                "issue_type_counts": issue_type_counts,
            },
        )

        # Generate thumbnail for file uploads
        if source_type == "file":
            try:
                # Generate and cache thumbnail
                if paper_source.lower().endswith('.pdf'):
                    thumbnail_path = await generate_pdf_thumbnail_async(
                        paper_source,
                        source_identifier=paper_source,
                        cache_dir=cache_dir,
                    )
                else:
                    thumbnail_path = await get_text_thumbnail_async(
                        check_id,
                        "",
                        paper_source,
                        source_identifier=paper_source,
                        cache_dir=cache_dir,
                    )
                if thumbnail_path:
                    await db.update_check_thumbnail(check_id, thumbnail_path)
                    logger.info(f"Generated thumbnail for check {check_id}: {thumbnail_path}")
            except Exception as thumb_error:
                logger.warning(f"Failed to generate thumbnail for check {check_id}: {thumb_error}")
            
            # Note: We keep uploaded files for later access via /api/file/{check_id}

    except asyncio.CancelledError:
        logger.info(f"Check cancelled: {session_id}")
        completed_at = utcnow_sqlite()
        duration_ms = int((time.perf_counter() - start_monotonic) * 1000)
        await db.update_check_status(
            check_id,
            'cancelled',
            cancel_reason='user_requested',
            completed_at=completed_at,
            duration_ms=duration_ms,
        )
        await _log_usage_event_safe(
            "check.cancelled",
            user_id=user_id,
            provider=provider,
            email_domain=email_domain,
            check_id=check_id,
            session_id=session_id,
            source_type=source_type,
            source_value=paper_source if source_type == "url" else None,
            status_code=499,
            reason_code="user_requested",
            payload={"duration_ms": duration_ms},
        )
        await manager.send_message(session_id, "cancelled", {"message": "Check cancelled", "check_id": check_id})
    except Exception as e:
        logger.error(f"Error in run_check: {e}", exc_info=True)
        completed_at = utcnow_sqlite()
        duration_ms = int((time.perf_counter() - start_monotonic) * 1000)
        await db.update_check_status(
            check_id,
            'error',
            failure_class=type(e).__name__,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )
        await _log_usage_event_safe(
            "check.failed",
            user_id=user_id,
            provider=provider,
            email_domain=email_domain,
            check_id=check_id,
            session_id=session_id,
            source_type=source_type,
            source_value=paper_source if source_type == "url" else None,
            status_code=500,
            reason_code=type(e).__name__.lower(),
            payload={
                "duration_ms": duration_ms,
                "failure_class": type(e).__name__,
            },
        )
        await manager.send_message(session_id, "error", {
            "message": f"Check failed: {str(e)}",
            "details": type(e).__name__,
            "check_id": check_id
        })
    finally:
        active_checks.pop(session_id, None)
        await _release_user_check_slot(user_id)


@app.get("/api/history")
async def get_history(
    limit: int = 50,
    current_user: UserInfo = Depends(require_user),
):
    """Get check history (filtered by the authenticated user when auth is enabled)"""
    try:
        user_id = get_user_id_filter(current_user)
        history = await db.get_history(limit, user_id=user_id)

        enriched = []
        for item in history:
            if item.get("status") == "in_progress":
                session_id = _session_id_for_check(item["id"])
                if session_id:
                    item["session_id"] = session_id
            enriched.append(item)

        return enriched  # Return array directly
    except Exception as e:
        logger.error(f"Error getting history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/{check_id}")
async def get_check_detail(
    check_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """Get detailed results for a specific check"""
    try:
        user_id = get_user_id_filter(current_user)
        check = await db.get_check_by_id(check_id, user_id=user_id)
        if not check:
            raise HTTPException(status_code=404, detail="Check not found")

        if check.get("status") == "in_progress":
            session_id = _session_id_for_check(check_id)
            if session_id:
                check["session_id"] = session_id
        return check
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting check detail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/thumbnail/{check_id}")
async def get_thumbnail(check_id: int, current_user: UserInfo = Depends(require_user)):
    """
    Get or generate a thumbnail for a check.
    
    Returns the thumbnail image file if available, or generates one on-demand.
    For ArXiv papers, downloads the PDF and generates a thumbnail of the first page.
    For uploaded PDFs, generates a thumbnail from the file.
    For pasted text, returns a placeholder thumbnail.
    """
    try:
        check = await _get_owned_check_or_404(check_id, current_user)
        
        # Check if we already have a cached thumbnail path
        thumbnail_path = check.get('thumbnail_path')
        if thumbnail_path and os.path.exists(thumbnail_path):
            return FileResponse(
                thumbnail_path,
                media_type="image/png",
                headers=_private_artifact_headers(),
            )
        
        # Stale thumbnail path — clear it from DB so we regenerate cleanly
        if thumbnail_path:
            logger.info(f"Thumbnail file missing for check {check_id}, regenerating: {thumbnail_path}")
            await db.update_check_thumbnail(check_id, "")
        
        cache_dir = await _get_configured_cache_dir()

        # Generate thumbnail based on source type
        paper_source = check.get('paper_source', '')
        source_type = check.get('source_type', 'url')
        
        # Convert OpenReview forum URLs to PDF URLs
        if 'openreview.net/forum' in (paper_source or '').lower():
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(paper_source)
            params = parse_qs(parsed.query)
            or_id = params.get('id', [None])[0]
            if or_id:
                paper_source = f"https://openreview.net/pdf?id={or_id}"

        # Try to extract ArXiv ID
        import re
        arxiv_id_pattern = r'(\d{4}\.\d{4,5})(v\d+)?'
        arxiv_match = re.search(arxiv_id_pattern, paper_source)
        
        # Check if this is a direct PDF URL (not ArXiv)
        is_direct_pdf_url = (
            source_type == 'url' and
            (paper_source.lower().endswith('.pdf') or 'openreview.net/pdf' in paper_source.lower()) and 
            'arxiv.org' not in paper_source.lower()
        )
        
        if is_direct_pdf_url:
            # Generate thumbnail from direct PDF URL
            logger.info(f"Generating thumbnail from PDF URL: {paper_source}")
            from backend.refchecker_wrapper import download_pdf

            pdf_path = get_pdf_storage_path(paper_source, cache_dir=cache_dir)
            
            # Download PDF if not already cached (or if cached file is empty/corrupt)
            if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                try:
                    await asyncio.to_thread(download_pdf, paper_source, pdf_path)
                except Exception as e:
                    logger.error(f"Failed to download PDF for thumbnail: {e}")
                    thumbnail_path = await get_text_thumbnail_async(
                        check_id,
                        "PDF",
                        source_identifier=paper_source,
                        cache_dir=cache_dir,
                    )
                    pdf_path = None
            
            if pdf_path and os.path.exists(pdf_path):
                thumbnail_path = await generate_pdf_thumbnail_async(
                    pdf_path,
                    source_identifier=paper_source,
                    cache_dir=cache_dir,
                )
            else:
                thumbnail_path = await get_text_thumbnail_async(
                    check_id,
                    "PDF",
                    source_identifier=paper_source,
                    cache_dir=cache_dir,
                )
        elif arxiv_match:
            # Generate thumbnail from ArXiv paper
            arxiv_id = arxiv_match.group(1)
            logger.info(f"Generating thumbnail for ArXiv paper: {arxiv_id}")
            thumbnail_path = await generate_arxiv_thumbnail_async(arxiv_id, check_id, cache_dir=cache_dir)
            if not thumbnail_path:
                thumbnail_path = await get_text_thumbnail_async(
                    check_id,
                    f"ArXiv: {arxiv_id}",
                    source_identifier=paper_source,
                    cache_dir=cache_dir,
                )
        elif source_type == 'file' and paper_source.lower().endswith('.pdf'):
            # Generate thumbnail from uploaded PDF
            if os.path.exists(paper_source):
                logger.info(f"Generating thumbnail from PDF: {paper_source}")
                thumbnail_path = await generate_pdf_thumbnail_async(
                    paper_source,
                    source_identifier=paper_source,
                    cache_dir=cache_dir,
                )
            else:
                # PDF file no longer exists, use placeholder
                thumbnail_path = await get_text_thumbnail_async(
                    check_id,
                    "PDF",
                    source_identifier=paper_source,
                    cache_dir=cache_dir,
                )
        elif source_type == 'file':
            # For non-PDF file uploads, generate thumbnail with file content
            logger.info(f"Generating text content thumbnail for uploaded file check {check_id}")
            if os.path.exists(paper_source):
                thumbnail_path = await get_text_thumbnail_async(
                    check_id,
                    "",
                    paper_source,
                    source_identifier=paper_source,
                    cache_dir=cache_dir,
                )
            else:
                thumbnail_path = await get_text_thumbnail_async(
                    check_id,
                    "Uploaded file",
                    source_identifier=f"check_{check_id}_file",
                    cache_dir=cache_dir,
                )
        elif source_type == 'text':
            # Generate thumbnail with actual text content for pasted text
            logger.info(f"Generating text content thumbnail for check {check_id}")
            # paper_source is now a file path for text sources
            thumbnail_path = await get_text_thumbnail_async(
                check_id,
                "",
                paper_source,
                source_identifier=paper_source,
                cache_dir=cache_dir,
            )
        else:
            # Default placeholder for other sources
            thumbnail_path = await get_text_thumbnail_async(
                check_id,
                source_type,
                source_identifier=f"check_{check_id}_{source_type}",
                cache_dir=cache_dir,
            )
        
        if thumbnail_path and os.path.exists(thumbnail_path):
            # Cache the thumbnail path in the database
            await db.update_check_thumbnail(check_id, thumbnail_path)
            
            return FileResponse(
                thumbnail_path,
                media_type="image/png",
                headers=_private_artifact_headers(),
            )
        else:
            raise HTTPException(status_code=404, detail="Could not generate thumbnail")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting thumbnail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/preview/{check_id}")
async def get_preview(check_id: int, current_user: UserInfo = Depends(require_user)):
    """
    Get or generate a high-resolution preview for a check.
    
    Returns a larger preview image suitable for overlay display.
    For ArXiv papers, downloads the PDF and generates a preview of the first page.
    For uploaded PDFs, generates a preview from the file.
    """
    try:
        check = await _get_owned_check_or_404(check_id, current_user)
        
        cache_dir = await _get_configured_cache_dir()

        # Generate preview based on source type
        paper_source = check.get('paper_source', '')
        source_type = check.get('source_type', 'url')
        
        # Convert OpenReview forum URLs to PDF URLs
        if 'openreview.net/forum' in (paper_source or '').lower():
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(paper_source)
            params = parse_qs(parsed.query)
            or_id = params.get('id', [None])[0]
            if or_id:
                paper_source = f"https://openreview.net/pdf?id={or_id}"

        # Try to extract ArXiv ID
        import re
        arxiv_id_pattern = r'(\d{4}\.\d{4,5})(v\d+)?'
        arxiv_match = re.search(arxiv_id_pattern, paper_source)
        
        # Check if this is a direct PDF URL (not ArXiv)
        is_direct_pdf_url = (
            source_type == 'url' and
            (paper_source.lower().endswith('.pdf') or 'openreview.net/pdf' in paper_source.lower()) and 
            'arxiv.org' not in paper_source.lower()
        )
        
        preview_path = None
        
        if is_direct_pdf_url:
            # Generate preview from direct PDF URL
            logger.info(f"Generating preview from PDF URL: {paper_source}")
            from backend.refchecker_wrapper import download_pdf

            pdf_path = get_pdf_storage_path(paper_source, cache_dir=cache_dir)
            
            # Download PDF if not already cached (or if cached file is empty/corrupt)
            if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                try:
                    await asyncio.to_thread(download_pdf, paper_source, pdf_path)
                except Exception as e:
                    logger.error(f"Failed to download PDF for preview: {e}")
                    pdf_path = None
            
            if pdf_path and os.path.exists(pdf_path):
                preview_path = await generate_pdf_preview_async(
                    pdf_path,
                    source_identifier=paper_source,
                    cache_dir=cache_dir,
                )
        elif arxiv_match:
            # Generate preview from ArXiv paper
            arxiv_id = arxiv_match.group(1)
            logger.info(f"Generating preview for ArXiv paper: {arxiv_id}")
            preview_path = await generate_arxiv_preview_async(arxiv_id, check_id, cache_dir=cache_dir)
        elif source_type == 'file' and paper_source.lower().endswith('.pdf'):
            # Generate preview from uploaded PDF
            if os.path.exists(paper_source):
                logger.info(f"Generating preview from PDF: {paper_source}")
                preview_path = await generate_pdf_preview_async(
                    paper_source,
                    source_identifier=paper_source,
                    cache_dir=cache_dir,
                )
        
        if preview_path and os.path.exists(preview_path):
            return FileResponse(
                preview_path,
                media_type="image/png",
                headers=_private_artifact_headers(),
            )
        
        # For text sources, generate a high-resolution text preview for overlay display
        if source_type == 'text':
            logger.info(f"Generating text preview for check {check_id}")
            preview_path = await get_text_preview_async(
                check_id,
                "",
                paper_source,
                source_identifier=paper_source,
                cache_dir=cache_dir,
            )
            if preview_path and os.path.exists(preview_path):
                return FileResponse(
                    preview_path,
                    media_type="image/png",
                    headers=_private_artifact_headers(),
                )
        
        # For non-PDF file uploads, also generate a text preview
        if source_type == 'file' and not paper_source.lower().endswith('.pdf'):
            logger.info(f"Generating text preview for uploaded file check {check_id}")
            if os.path.exists(paper_source):
                preview_path = await get_text_preview_async(
                    check_id,
                    "",
                    paper_source,
                    source_identifier=paper_source,
                    cache_dir=cache_dir,
                )
            else:
                preview_path = await get_text_preview_async(
                    check_id,
                    "Uploaded file",
                    source_identifier=f"check_{check_id}_file",
                    cache_dir=cache_dir,
                )
            if preview_path and os.path.exists(preview_path):
                return FileResponse(
                    preview_path,
                    media_type="image/png",
                    headers=_private_artifact_headers(),
                )
        
        raise HTTPException(status_code=404, detail="Could not generate preview")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting preview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/text/{check_id}")
async def get_pasted_text(check_id: int, current_user: UserInfo = Depends(require_user)):
    """
    Get the pasted text content for a check.
    
    Returns the text file content as plain text for viewing.
    """
    try:
        check = await _get_owned_check_or_404(check_id, current_user)
        
        source_type = check.get('source_type', '')
        paper_source = check.get('paper_source', '')
        
        if source_type != 'text':
            raise HTTPException(status_code=400, detail="This check is not from pasted text")
        
        # paper_source should now be a file path
        if os.path.exists(paper_source):
            return FileResponse(
                paper_source,
                media_type="text/plain; charset=utf-8",
                filename="pasted_bibliography.txt",
                headers=_private_artifact_headers({
                    "Content-Type": "text/plain; charset=utf-8",
                }),
            )
        else:
            # Fallback: if paper_source is the actual text content (legacy)
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(
                paper_source,
                headers=_private_artifact_headers(),
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pasted text: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/file/{check_id}")
async def get_uploaded_file(check_id: int, current_user: UserInfo = Depends(require_user)):
    """
    Get the uploaded file content for a check.
    
    Returns the file for viewing/download.
    """
    try:
        check = await _get_owned_check_or_404(check_id, current_user)
        
        source_type = check.get('source_type', '')
        paper_source = check.get('paper_source', '')
        paper_title = check.get('paper_title', 'uploaded_file')
        
        if source_type != 'file':
            raise HTTPException(status_code=400, detail="This check is not from an uploaded file")
        
        if os.path.exists(paper_source):
            # Determine media type based on file extension
            media_type = "application/octet-stream"
            if paper_source.lower().endswith('.pdf'):
                media_type = "application/pdf"
            elif paper_source.lower().endswith('.txt'):
                media_type = "text/plain; charset=utf-8"
            elif paper_source.lower().endswith('.bib'):
                media_type = "text/plain; charset=utf-8"
            elif paper_source.lower().endswith('.tex'):
                media_type = "text/plain; charset=utf-8"
            
            return FileResponse(
                paper_source,
                media_type=media_type,
                filename=paper_title,
                headers=_private_artifact_headers(),
            )
        else:
            raise HTTPException(status_code=404, detail="File no longer exists")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting uploaded file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bibliography/{check_id}")
async def get_bibliography_source(check_id: int, current_user: UserInfo = Depends(require_user)):
    """
    Get the bibliography source content (bbl/bib file) for a check.
    
    Returns the bibliography file content as plain text for viewing.
    This is the actual source file used to extract references (from ArXiv source or pasted text).
    """
    try:
        check = await _get_owned_check_or_404(check_id, current_user)
        
        bibliography_source_path = check.get('bibliography_source_path', '')
        extraction_method = check.get('extraction_method', '')
        source_type = check.get('source_type', '')
        paper_source = check.get('paper_source', '')
        
        # First check if we have a saved bibliography source file
        if bibliography_source_path and os.path.exists(bibliography_source_path):
            return FileResponse(
                bibliography_source_path,
                media_type="text/plain; charset=utf-8",
                filename=f"bibliography_{check_id}.{extraction_method or 'txt'}",
                headers=_private_artifact_headers({
                    "Content-Type": "text/plain; charset=utf-8",
                }),
            )
        
        # Fall back to pasted text source if source_type is 'text' and it's bbl/bib
        if source_type == 'text' and extraction_method in ['bbl', 'bib'] and os.path.exists(paper_source):
            return FileResponse(
                paper_source,
                media_type="text/plain; charset=utf-8",
                filename=f"bibliography_{check_id}.{extraction_method}",
                headers=_private_artifact_headers({
                    "Content-Type": "text/plain; charset=utf-8",
                }),
            )
        
        raise HTTPException(status_code=404, detail="Bibliography source not available for this check")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting bibliography source: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/recheck/{check_id}")
async def recheck(
    check_id: int,
    current_user: UserInfo = Depends(require_user),
    http_request: Request = None,
):
    """Re-run a previous check"""
    slot_acquired = False
    try:
        # Get original check
        original = await _get_owned_check_or_404(check_id, current_user)
        user_id = get_user_id_filter(current_user)

        # Generate new session ID
        session_id = str(uuid.uuid4())

        # Determine source type
        source = original["paper_source"]
        source_type = original.get("source_type") or (
            "url" if source.startswith("http") or "arxiv" in source.lower() else "file"
        )
        
        llm_provider = original.get("llm_provider", "anthropic")
        llm_model = original.get("llm_model")

        if not await _acquire_user_check_slot(user_id):
            await _log_usage_event_safe(
                "check.rate_limited",
                current_user=current_user,
                connection=http_request,
                source_type=source_type,
                source_value=source if source_type == "url" else None,
                paper_title=original.get("paper_title"),
                paper_key=original.get("paper_key"),
                source_host=original.get("source_host"),
                status_code=429,
                reason_code="max_concurrent_checks_reached",
                payload={
                    "recheck_of": check_id,
                    "max_checks_per_user": MAX_CHECKS_PER_USER,
                },
            )
            raise HTTPException(
                status_code=429,
                detail=f"Maximum concurrent checks ({MAX_CHECKS_PER_USER}) reached"
            )
        slot_acquired = True
        
        # Create history entry immediately
        new_check_id = await db.create_pending_check(
            paper_title=original.get("paper_title", "Re-checking..."),
            paper_source=source,
            source_type=source_type,
            llm_provider=llm_provider,
            llm_model=llm_model,
            original_filename=original.get("original_filename"),
            user_id=user_id,
            started_at=utcnow_sqlite(),
            input_bytes=original.get("input_bytes"),
            source_host=original.get("source_host"),
            paper_identifier_type=original.get("paper_identifier_type"),
            paper_identifier_value=original.get("paper_identifier_value"),
            paper_key=original.get("paper_key"),
            batch_size=1,
        )

        await _log_usage_event_safe(
            "check.started",
            current_user=current_user,
            connection=http_request,
            check_id=new_check_id,
            session_id=session_id,
            source_type=source_type,
            source_value=source if source_type == "url" else None,
            paper_title=original.get("paper_title"),
            paper_key=original.get("paper_key"),
            source_host=original.get("source_host"),
            status_code=202,
            payload={
                "recheck_of": check_id,
                "use_llm": True,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            },
        )

        # Start check in background
        cancel_event = asyncio.Event()
        task = asyncio.create_task(
            run_check(
                session_id,
                new_check_id,
                source,
                source_type,
                llm_provider,
                llm_model,
                None,  # no API key for recheck (not available without re-auth)
                None,  # no endpoint for recheck
                True,
                cancel_event,
                user_id,
            )
        )
        slot_acquired = False
        active_checks[session_id] = {"task": task, "cancel_event": cancel_event, "check_id": new_check_id, "user_id": user_id}

        return {
            "session_id": session_id,
            "check_id": new_check_id,
            "message": "Re-check started",
            "original_id": check_id
        }

    except HTTPException:
        if slot_acquired:
            await _release_user_check_slot(user_id)
        raise
    except Exception as e:
        if slot_acquired:
            await _release_user_check_slot(user_id)
        logger.error(f"Error rechecking: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cancel/{session_id}")
async def cancel_check(
    session_id: str,
    current_user: UserInfo = Depends(require_user),
    http_request: Request = None,
):
    """Cancel an active check"""
    active = active_checks.get(session_id)
    if not active:
        raise HTTPException(status_code=404, detail="Active check not found")
    user_id = get_user_id_filter(current_user)
    if user_id is not None and active.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Active check not found")
    active["cancel_event"].set()
    active["task"].cancel()
    await _log_usage_event_safe(
        "check.cancel_requested",
        current_user=current_user,
        connection=http_request,
        check_id=active.get("check_id"),
        session_id=session_id,
        batch_id=active.get("batch_id"),
        status_code=202,
        reason_code="user_requested",
    )
    return {"message": "Cancellation requested"}


# ============ Batch Operations ============

@app.post("/api/check/batch")
async def start_batch_check(
    request: BatchUrlsRequest,
    current_user: UserInfo = Depends(require_user),
    http_request: Request = None,
):
    """
    Start a batch of reference checks from a list of URLs/ArXiv IDs.
    
    Returns batch_id and list of individual check sessions.
    """
    try:
        if not request.urls or len(request.urls) == 0:
            raise HTTPException(status_code=400, detail="No URLs provided")
        
        # Limit batch size to prevent abuse
        MAX_BATCH_SIZE = 50
        if len(request.urls) > MAX_BATCH_SIZE:
            raise HTTPException(
                status_code=400, 
                detail=f"Batch size exceeds maximum of {MAX_BATCH_SIZE} papers"
            )
        
        # Generate unique batch ID
        batch_id = str(uuid.uuid4())
        batch_label = request.batch_label or f"Batch of {len(request.urls)} papers"
        started_at = utcnow_sqlite()
        
        user_id = get_user_id_filter(current_user)

        # api_key from request body takes precedence over config stored key
        effective_api_key = request.api_key
        endpoint = None
        llm_provider = request.llm_provider
        llm_model = request.llm_model
        
        if request.llm_config_id and request.use_llm:
            config = await db.get_llm_config_by_id(request.llm_config_id, user_id=user_id)
            if config:
                if not effective_api_key:
                    effective_api_key = config.get('api_key')
                endpoint = config.get('endpoint')
                llm_provider = config.get('provider', llm_provider)
                llm_model = config.get('model') or llm_model
        if request.use_llm:
            _ensure_allowed_web_llm_provider(llm_provider)

        valid_urls = [u.strip() for u in request.urls if u.strip()]

        # Pre-acquire one slot per URL to enforce per-user rate limit atomically
        slots_needed = len(valid_urls)
        slots_acquired = 0
        for _ in range(slots_needed):
            if not await _acquire_user_check_slot(user_id):
                # Release slots already acquired
                for _ in range(slots_acquired):
                    await _release_user_check_slot(user_id)
                await _log_usage_event_safe(
                    "batch.rate_limited",
                    current_user=current_user,
                    connection=http_request,
                    batch_id=batch_id,
                    source_type="url",
                    status_code=429,
                    reason_code="max_concurrent_checks_reached",
                    payload={
                        "requested_batch_size": slots_needed,
                        "max_checks_per_user": MAX_CHECKS_PER_USER,
                    },
                )
                raise HTTPException(
                    status_code=429,
                    detail=f"Maximum concurrent checks ({MAX_CHECKS_PER_USER}) reached"
                )
            slots_acquired += 1

        await _log_usage_event_safe(
            "batch.started",
            current_user=current_user,
            connection=http_request,
            batch_id=batch_id,
            source_type="url",
            status_code=202,
            payload={
                "batch_size": len(valid_urls),
                "use_llm": request.use_llm,
                "llm_provider": llm_provider if request.use_llm else None,
                "llm_model": llm_model if request.use_llm else None,
                "semantic_scholar_key_present": bool(request.semantic_scholar_api_key),
            },
        )

        checks = []
        
        for url in valid_urls:
            session_id = str(uuid.uuid4())
            source_identity = infer_paper_identity(url, source_type='url')
            
            # Create pending check entry with batch info
            check_id = await db.create_pending_check(
                paper_title=url,  # Will be updated during processing
                paper_source=url,
                source_type='url',
                llm_provider=llm_provider if request.use_llm else None,
                llm_model=llm_model if request.use_llm else None,
                batch_id=batch_id,
                batch_label=batch_label,
                user_id=user_id,
                started_at=started_at,
                input_bytes=len(url.encode("utf-8")),
                source_host=source_identity.get("source_host"),
                paper_identifier_type=source_identity.get("paper_identifier_type"),
                paper_identifier_value=source_identity.get("paper_identifier_value"),
                paper_key=source_identity.get("paper_key"),
                batch_size=len(valid_urls),
            )

            await _log_usage_event_safe(
                "check.started",
                current_user=current_user,
                connection=http_request,
                check_id=check_id,
                session_id=session_id,
                batch_id=batch_id,
                source_type="url",
                source_value=url,
                paper_title=url,
                paper_key=source_identity.get("paper_key"),
                source_host=source_identity.get("source_host"),
                status_code=202,
                payload={
                    "batch_size": len(valid_urls),
                    "use_llm": request.use_llm,
                    "llm_provider": llm_provider if request.use_llm else None,
                    "llm_model": llm_model if request.use_llm else None,
                },
            )
            
            # Start check in background (run_check's finally will release the slot)
            cancel_event = asyncio.Event()
            task = asyncio.create_task(
                run_check(
                    session_id, check_id, url, 'url',
                    llm_provider, llm_model, effective_api_key, endpoint,
                    request.use_llm, cancel_event, user_id,
                    semantic_scholar_api_key=request.semantic_scholar_api_key,
                )
            )
            active_checks[session_id] = {
                "task": task, 
                "cancel_event": cancel_event, 
                "check_id": check_id,
                "batch_id": batch_id,
                "user_id": user_id,
            }
            
            checks.append({
                "session_id": session_id,
                "check_id": check_id,
                "source": url
            })
        
        logger.info(f"Started batch {batch_id} with {len(checks)} papers")
        
        return {
            "batch_id": batch_id,
            "batch_label": batch_label,
            "total_papers": len(checks),
            "checks": checks
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting batch check: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/check/batch/files")
async def start_batch_check_files(
    files: list[UploadFile] = File(...),
    batch_label: Optional[str] = Form(None),
    llm_config_id: Optional[int] = Form(None),
    llm_provider: str = Form("anthropic"),
    llm_model: Optional[str] = Form(None),
    use_llm: bool = Form(True),
    api_key: Optional[str] = Form(None),
    current_user: UserInfo = Depends(require_user),
    http_request: Request = None,
):
    """
    Start a batch of reference checks from uploaded files.
    
    Accepts multiple files or a single ZIP file containing documents.
    """
    try:
        if not files or len(files) == 0:
            raise HTTPException(status_code=400, detail="No files provided")
        
        MAX_BATCH_SIZE = 50
        
        # Generate unique batch ID
        batch_id = str(uuid.uuid4())
        started_at = utcnow_sqlite()

        user_id = get_user_id_filter(current_user)
        uploads_dir = get_uploads_dir() / str(user_id)
        uploads_dir.mkdir(parents=True, exist_ok=True)
        
        # api_key from form takes precedence over config stored key
        effective_api_key = api_key
        endpoint = None

        if llm_config_id and use_llm:
            config = await db.get_llm_config_by_id(llm_config_id, user_id=user_id)
            if config:
                if not effective_api_key:
                    effective_api_key = config.get('api_key')
                endpoint = config.get('endpoint')
                llm_provider = config.get('provider', llm_provider)
                llm_model = config.get('model') or llm_model
        if use_llm:
            _ensure_allowed_web_llm_provider(llm_provider)
        
        files_to_process = []
        created_paths: list[Path] = []
        
        # Check if single ZIP file
        if len(files) == 1 and files[0].filename.lower().endswith('.zip'):
            zip_name = files[0].filename.replace("/", "_").replace("\\", "_")
            zip_path = uploads_dir / f"{batch_id}_{zip_name}"
            await _save_upload_file(files[0], zip_path, MAX_BATCH_ARCHIVE_BYTES)
            created_paths.append(zip_path)
            files_to_process = _extract_zip_batch_files(zip_path, uploads_dir, batch_id, MAX_BATCH_SIZE)
            created_paths.extend(Path(file_info['path']) for file_info in files_to_process)
            zip_path.unlink(missing_ok=True)
            created_paths.remove(zip_path)
        else:
            # Process individual files
            total_uploaded_bytes = 0
            for file in files[:MAX_BATCH_SIZE]:
                safe_filename = file.filename.replace("/", "_").replace("\\", "_")
                file_path = uploads_dir / f"{batch_id}_{len(files_to_process) + 1}_{safe_filename}"
                uploaded_bytes = await _save_upload_file(file, file_path, MAX_UPLOAD_FILE_BYTES)
                total_uploaded_bytes += uploaded_bytes
                if total_uploaded_bytes > MAX_BATCH_UPLOAD_TOTAL_BYTES:
                    if file_path.exists():
                        file_path.unlink()
                    raise HTTPException(
                        status_code=413,
                        detail=f"Batch upload exceeds maximum total size of {MAX_BATCH_UPLOAD_TOTAL_BYTES // (1024 * 1024)} MB",
                    )
                created_paths.append(file_path)
                
                files_to_process.append({
                    'path': str(file_path),
                    'filename': file.filename
                })
        
        if not files_to_process:
            raise HTTPException(status_code=400, detail="No valid files found")
        
        label = batch_label or f"Batch of {len(files_to_process)} files"

        # Pre-acquire one slot per file to enforce per-user rate limit atomically
        slots_needed = len(files_to_process)
        slots_acquired = 0
        for _ in range(slots_needed):
            if not await _acquire_user_check_slot(user_id):
                for _ in range(slots_acquired):
                    await _release_user_check_slot(user_id)
                await _log_usage_event_safe(
                    "batch.rate_limited",
                    current_user=current_user,
                    connection=http_request,
                    batch_id=batch_id,
                    source_type="file",
                    status_code=429,
                    reason_code="max_concurrent_checks_reached",
                    payload={
                        "requested_batch_size": slots_needed,
                        "max_checks_per_user": MAX_CHECKS_PER_USER,
                    },
                )
                raise HTTPException(
                    status_code=429,
                    detail=f"Maximum concurrent checks ({MAX_CHECKS_PER_USER}) reached"
                )
            slots_acquired += 1

        await _log_usage_event_safe(
            "batch.started",
            current_user=current_user,
            connection=http_request,
            batch_id=batch_id,
            source_type="file",
            status_code=202,
            payload={
                "batch_size": len(files_to_process),
                "use_llm": use_llm,
                "llm_provider": llm_provider if use_llm else None,
                "llm_model": llm_model if use_llm else None,
                "uploaded_bytes": sum(Path(item['path']).stat().st_size for item in files_to_process if Path(item['path']).exists()),
            },
        )
        
        checks = []
        for file_info in files_to_process:
            session_id = str(uuid.uuid4())
            file_size = Path(file_info['path']).stat().st_size if Path(file_info['path']).exists() else None
            
            check_id = await db.create_pending_check(
                paper_title=file_info['filename'],
                paper_source=file_info['path'],
                source_type='file',
                llm_provider=llm_provider if use_llm else None,
                llm_model=llm_model if use_llm else None,
                batch_id=batch_id,
                batch_label=label,
                original_filename=file_info['filename'],
                user_id=user_id,
                started_at=started_at,
                input_bytes=file_size,
                batch_size=len(files_to_process),
            )

            await _log_usage_event_safe(
                "check.started",
                current_user=current_user,
                connection=http_request,
                check_id=check_id,
                session_id=session_id,
                batch_id=batch_id,
                source_type="file",
                paper_title=file_info['filename'],
                status_code=202,
                payload={
                    "batch_size": len(files_to_process),
                    "use_llm": use_llm,
                    "llm_provider": llm_provider if use_llm else None,
                    "llm_model": llm_model if use_llm else None,
                    "input_bytes": file_size,
                    "original_filename_ext": Path(file_info['filename']).suffix.lower(),
                },
            )
            
            cancel_event = asyncio.Event()
            task = asyncio.create_task(
                run_check(
                    session_id, check_id, file_info['path'], 'file',
                    llm_provider, llm_model, effective_api_key, endpoint,
                    use_llm, cancel_event, user_id
                )
            )
            active_checks[session_id] = {
                "task": task,
                "cancel_event": cancel_event,
                "check_id": check_id,
                "batch_id": batch_id,
                "user_id": user_id,
            }
            
            checks.append({
                "session_id": session_id,
                "check_id": check_id,
                "source": file_info['filename']
            })
        
        logger.info(f"Started file batch {batch_id} with {len(checks)} files")
        
        return {
            "batch_id": batch_id,
            "batch_label": label,
            "total_papers": len(checks),
            "checks": checks
        }
    
    except HTTPException:
        for path in locals().get('created_paths', []):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        raise
    except Exception as e:
        for path in locals().get('created_paths', []):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        logger.error(f"Error starting batch file check: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/batch/{batch_id}")
async def get_batch(batch_id: str, current_user: UserInfo = Depends(require_user)):
    """Get batch summary and all checks in the batch"""
    try:
        summary, checks = await _get_owned_batch_or_404(batch_id, current_user)
        
        # Add session_id for in-progress checks
        for check in checks:
            if check.get("status") == "in_progress":
                session_id = _session_id_for_check(check["id"])
                if session_id:
                    check["session_id"] = session_id
        
        return {
            **summary,
            "checks": checks
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting batch: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cancel/batch/{batch_id}")
async def cancel_batch(
    batch_id: str,
    current_user: UserInfo = Depends(require_user),
    http_request: Request = None,
):
    """Cancel all active checks in a batch"""
    try:
        user_id = get_user_id_filter(current_user)
        await _get_owned_batch_or_404(batch_id, current_user)
        # Cancel active tasks
        cancelled_sessions = 0
        for session_id, meta in list(active_checks.items()):
            if meta.get("batch_id") == batch_id and (user_id is None or meta.get("user_id") == user_id):
                meta["cancel_event"].set()
                meta["task"].cancel()
                cancelled_sessions += 1
        
        # Update database status for any remaining in-progress
        db_cancelled = await db.cancel_batch(batch_id, user_id=user_id)
        
        logger.info(f"Cancelled batch {batch_id}: {cancelled_sessions} active, {db_cancelled} in DB")
        await _log_usage_event_safe(
            "batch.cancel_requested",
            current_user=current_user,
            connection=http_request,
            batch_id=batch_id,
            status_code=202,
            reason_code="user_requested",
            payload={
                "cancelled_active": cancelled_sessions,
                "cancelled_pending": db_cancelled,
            },
        )
        
        return {
            "message": "Batch cancellation requested",
            "batch_id": batch_id,
            "cancelled_active": cancelled_sessions,
            "cancelled_pending": db_cancelled
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling batch: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/batch/{batch_id}")
async def delete_batch(batch_id: str, current_user: UserInfo = Depends(require_user)):
    """Delete all checks in a batch"""
    try:
        user_id = get_user_id_filter(current_user)
        await _get_owned_batch_or_404(batch_id, current_user)
        # First cancel any active checks
        for session_id, meta in list(active_checks.items()):
            if meta.get("batch_id") == batch_id and (user_id is None or meta.get("user_id") == user_id):
                meta["cancel_event"].set()
                meta["task"].cancel()
                active_checks.pop(session_id, None)
        
        # Delete from database
        deleted_count = await db.delete_batch(batch_id, user_id=user_id)
        
        if deleted_count == 0:
            raise HTTPException(status_code=404, detail="Batch not found")
        
        logger.info(f"Deleted batch {batch_id}: {deleted_count} checks")
        
        return {
            "message": "Batch deleted successfully",
            "batch_id": batch_id,
            "deleted_count": deleted_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting batch: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/batch/{batch_id}")
async def update_batch_label(batch_id: str, update: BatchLabelUpdate, current_user: UserInfo = Depends(require_user)):
    """Update the label for a batch"""
    try:
        user_id = get_user_id_filter(current_user)
        success = await db.update_batch_label(batch_id, update.batch_label, user_id=user_id)
        if success:
            return {"message": "Batch label updated successfully"}
        else:
            raise HTTPException(status_code=404, detail="Batch not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating batch label: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/recheck/batch/{batch_id}")
async def recheck_batch(batch_id: str, current_user: UserInfo = Depends(require_user)):
    """Re-run all checks in a batch"""
    try:
        # Get original batch checks
        user_id = get_user_id_filter(current_user)
        original_checks = await db.get_batch_checks(batch_id, user_id=user_id)
        if not original_checks:
            raise HTTPException(status_code=404, detail="Batch not found")
        
        # Create new batch
        new_batch_id = str(uuid.uuid4())
        original_label = original_checks[0].get("batch_label", "Re-checked batch")
        new_label = f"Re-check: {original_label}"
        
        checks = []
        for original in original_checks:
            session_id = str(uuid.uuid4())
            source = original["paper_source"]
            source_type = original.get("source_type", "url")
            llm_provider = original.get("llm_provider", "anthropic")
            llm_model = original.get("llm_model")
            
            check_id = await db.create_pending_check(
                paper_title=original.get("paper_title", "Re-checking..."),
                paper_source=source,
                source_type=source_type,
                llm_provider=llm_provider,
                llm_model=llm_model,
                batch_id=new_batch_id,
                batch_label=new_label,
                original_filename=original.get("original_filename"),
                user_id=user_id,
            )
            
            cancel_event = asyncio.Event()
            task = asyncio.create_task(
                run_check(
                    session_id, check_id, source, source_type,
                    llm_provider, llm_model, None, None, True, cancel_event, user_id
                )
            )
            active_checks[session_id] = {
                "task": task,
                "cancel_event": cancel_event,
                "check_id": check_id,
                "batch_id": new_batch_id,
                "user_id": user_id,
            }
            
            checks.append({
                "session_id": session_id,
                "check_id": check_id,
                "original_id": original["id"],
                "source": source
            })
        
        logger.info(f"Re-started batch {batch_id} as {new_batch_id} with {len(checks)} papers")
        
        return {
            "batch_id": new_batch_id,
            "batch_label": new_label,
            "original_batch_id": batch_id,
            "total_papers": len(checks),
            "checks": checks
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rechecking batch: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============ End Batch Operations ============


@app.delete("/api/history/{check_id}")
async def delete_check(
    check_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """Delete a check from history"""
    try:
        user_id = get_user_id_filter(current_user)
        success = await db.delete_check(check_id, user_id=user_id)
        if success:
            return {"message": "Check deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Check not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting check: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/history/{check_id}")
async def update_check_label(
    check_id: int,
    update: CheckLabelUpdate,
    current_user: UserInfo = Depends(require_user),
):
    """Update the custom label for a check"""
    try:
        user_id = get_user_id_filter(current_user)
        success = await db.update_check_label(check_id, update.custom_label, user_id=user_id)
        if success:
            return {"message": "Label updated successfully"}
        else:
            raise HTTPException(status_code=404, detail="Check not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating label: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# LLM Configuration endpoints

@app.get("/api/llm-configs")
async def get_llm_configs(current_user: UserInfo = Depends(require_user)):
    """Get all LLM configurations (API keys are not returned)"""
    try:
        user_id = get_user_id_filter(current_user)
        configs = await db.get_llm_configs(user_id=user_id)
        return configs
    except Exception as e:
        logger.error(f"Error getting LLM configs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm-configs")
async def create_llm_config(
    config: LLMConfigCreate,
    current_user: UserInfo = Depends(require_user),
):
    """Create a new LLM configuration"""
    try:
        user_id = get_user_id_filter(current_user)
        _ensure_allowed_web_llm_provider(config.provider)
        # In single-user mode, store the API key in the database
        store_key = config.api_key if not is_multiuser_mode() else None
        config_id = await db.create_llm_config(
            name=config.name,
            provider=config.provider,
            model=config.model,
            endpoint=config.endpoint,
            api_key=store_key,
            user_id=user_id,
        )
        return {
            "id": config_id,
            "name": config.name,
            "provider": config.provider,
            "model": config.model,
            "endpoint": config.endpoint,
            "is_default": False,
            "has_key": bool(store_key),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating LLM config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/llm-configs/{config_id}")
async def update_llm_config(
    config_id: int,
    config: LLMConfigUpdate,
    current_user: UserInfo = Depends(require_user),
):
    """Update an existing LLM configuration"""
    try:
        user_id = get_user_id_filter(current_user)
        if config.provider is not None:
            _ensure_allowed_web_llm_provider(config.provider)
        # In single-user mode, store the API key in the database
        store_key = config.api_key if not is_multiuser_mode() else None
        success = await db.update_llm_config(
            config_id=config_id,
            name=config.name,
            provider=config.provider,
            model=config.model,
            endpoint=config.endpoint,
            api_key=store_key,
            user_id=user_id,
        )
        if success:
            # Get updated config
            updated = await db.get_llm_configs(user_id=user_id)
            updated_config = next((c for c in updated if c["id"] == config_id), None)
            return updated_config or {"id": config_id, "message": "Updated"}
        else:
            raise HTTPException(status_code=404, detail="Config not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating LLM config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/llm-configs/{config_id}")
async def delete_llm_config(
    config_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """Delete an LLM configuration"""
    try:
        user_id = get_user_id_filter(current_user)
        success = await db.delete_llm_config(config_id, user_id=user_id)
        if success:
            return {"message": "Config deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Config not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting LLM config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm-configs/{config_id}/set-default")
async def set_default_llm_config(
    config_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """Set an LLM configuration as the default"""
    try:
        user_id = get_user_id_filter(current_user)
        success = await db.set_default_llm_config(config_id, user_id=user_id)
        if success:
            return {"message": "Default config set successfully"}
        else:
            raise HTTPException(status_code=404, detail="Config not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting default config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm-configs/validate")
async def validate_llm_config(
    config: LLMConfigValidate,
    current_user: UserInfo = Depends(require_user),
):
    """
    Validate an LLM configuration by making a test API call.
    Returns success or error message.
    """
    _ensure_allowed_web_llm_provider(config.provider)

    # Map providers to their required packages
    PROVIDER_PACKAGES = {
        "anthropic": ("anthropic", "pip install anthropic"),
        "openai": ("openai", "pip install openai"),
        "google": ("google.genai", "pip install google-genai"),
        "gemini": ("google.genai", "pip install google-genai"),
    }
    
    # Check if required package is installed for this provider
    provider_lower = config.provider.lower()
    if provider_lower in PROVIDER_PACKAGES:
        module_name, install_cmd = PROVIDER_PACKAGES[provider_lower]
        try:
            __import__(module_name.split('.')[0])
        except ImportError:
            raise HTTPException(
                status_code=400, 
                detail=f"The '{config.provider}' provider requires the '{module_name.split('.')[0]}' package. "
                       f"Please install it with: {install_cmd}"
            )
    
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from refchecker.llm.base import create_llm_provider
        
        # Build config
        llm_config = {}
        if config.model:
            llm_config['model'] = config.model
        if config.api_key:
            llm_config['api_key'] = config.api_key
        if config.endpoint:
            llm_config['endpoint'] = config.endpoint
        
        # Try to create provider
        provider = create_llm_provider(config.provider, llm_config)
        if not provider:
            raise HTTPException(status_code=400, detail=f"Failed to create {config.provider} provider")
        
        # Check if provider is available (has required client initialized)
        if hasattr(provider, 'is_available') and not provider.is_available():
            # Provider was created but client failed to initialize
            if provider_lower in PROVIDER_PACKAGES:
                _, install_cmd = PROVIDER_PACKAGES[provider_lower]
                raise HTTPException(
                    status_code=400,
                    detail=f"Provider '{config.provider}' is not available. "
                           f"Make sure the required package is installed: {install_cmd}"
                )
            raise HTTPException(status_code=400, detail=f"Provider '{config.provider}' is not available")
        
        # Make a simple test call using _call_llm
        test_response = provider._call_llm("Say 'ok' if you can hear me.")
        
        if test_response:
            return {"valid": True, "message": "Connection successful"}
        else:
            raise HTTPException(status_code=400, detail="Provider returned empty response")
            
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        error_lower = error_msg.lower()
        logger.error(f"LLM validation failed: {error_msg}")

        # 429 / quota / rate-limit errors mean the key IS valid but the
        # account has a billing or rate issue.  Return success with a warning
        # so the user can still save the config.
        if "429" in error_msg or "quota" in error_lower or "exceeded" in error_lower or "rate" in error_lower or "billing" in error_lower:
            warning = "API key is valid, but the account has a quota or rate-limit issue. Check your plan and billing details."
            logger.info(f"LLM validation passed with warning: {warning}")
            return {"valid": True, "message": "Connection validated (with warning)", "warning": warning}
        elif "404" in error_msg and "model" in error_lower:
            raise HTTPException(status_code=400, detail=f"Invalid model name. The model '{config.model}' was not found.")
        elif "401" in error_msg or "unauthorized" in error_lower or "invalid" in error_lower and "api" in error_lower and "key" in error_lower:
            raise HTTPException(status_code=400, detail="Invalid API key")
        elif "'NoneType'" in error_msg:
            # This usually means the provider library isn't installed
            if provider_lower in PROVIDER_PACKAGES:
                _, install_cmd = PROVIDER_PACKAGES[provider_lower]
                raise HTTPException(
                    status_code=400,
                    detail=f"The '{config.provider}' provider requires additional packages. "
                           f"Please install with: {install_cmd}"
                )
            raise HTTPException(status_code=400, detail=f"Provider initialization failed. Check that required packages are installed.")
        else:
            raise HTTPException(status_code=400, detail=f"Validation failed: {error_msg}")


# Semantic Scholar API Key endpoints

class SemanticScholarKeyUpdate(BaseModel):
    api_key: str


class SemanticScholarKeyValidate(BaseModel):
    api_key: str


@app.post("/api/settings/semantic-scholar/validate")
async def validate_semantic_scholar_key(
    data: SemanticScholarKeyValidate,
    current_user: UserInfo = Depends(require_user),
):
    """
    Validate a Semantic Scholar API key by making a test API call.
    Returns success or error message.
    """
    import httpx
    
    try:
        if not data.api_key or not data.api_key.strip():
            raise HTTPException(status_code=400, detail="API key cannot be empty")
        
        api_key = data.api_key.strip()
        
        # Test the API key by making a simple search query
        # Using the paper search endpoint with a minimal query
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        headers = {
            "Accept": "application/json",
            "x-api-key": api_key
        }
        params = {
            "query": "test",
            "limit": 1,
            "fields": "title"
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            return {"valid": True, "message": "API key is valid"}
        elif response.status_code == 401 or response.status_code == 403:
            raise HTTPException(status_code=400, detail="Invalid API key")
        elif response.status_code == 429:
            # Rate limited but key is valid
            return {"valid": True, "message": "API key is valid (rate limited)"}
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"API validation failed with status {response.status_code}"
            )
            
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=400, detail="Connection timed out. Please try again.")
    except httpx.RequestError as e:
        logger.error(f"Semantic Scholar validation request error: {e}")
        raise HTTPException(status_code=400, detail=f"Connection error: {str(e)}")
    except Exception as e:
        logger.error(f"Semantic Scholar validation failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Validation failed: {str(e)}")


@app.get("/api/settings/semantic-scholar")
async def get_semantic_scholar_key_status(current_user: UserInfo = Depends(require_user)):
    """Semantic Scholar keys are now browser-only for the current tab."""
    return {
        "has_key": False,
        "storage": "browser-only",
        "message": "Semantic Scholar API keys are managed in browser memory for the current tab only",
    }


@app.put("/api/settings/semantic-scholar")
async def set_semantic_scholar_key(
    data: SemanticScholarKeyUpdate,
    current_user: UserInfo = Depends(require_user),
):
    """Deprecated: Semantic Scholar keys are no longer stored on the server."""
    raise HTTPException(
        status_code=410,
        detail="Semantic Scholar API keys are managed in browser memory and are not stored on the server",
    )


@app.delete("/api/settings/semantic-scholar")
async def delete_semantic_scholar_key(current_user: UserInfo = Depends(require_user)):
    """Deprecated: Semantic Scholar keys are no longer stored on the server."""
    raise HTTPException(
        status_code=410,
        detail="Semantic Scholar API keys are managed in browser memory and are not stored on the server",
    )


# General Settings endpoints

class SettingUpdate(BaseModel):
    value: str


@app.get("/api/settings")
async def get_all_settings(current_user: UserInfo = Depends(require_user)):
    """Get all application settings"""
    try:
        # Define all settings with their defaults and metadata
        settings_config = {
            "max_concurrent_checks": {
                "default": str(DEFAULT_MAX_CONCURRENT),
                "type": "number",
                "label": "Max Concurrent Checks",
                "description": "Maximum number of references to check simultaneously across all papers",
                "min": 1,
                "max": 20,
                "section": "Performance"
            },
        }

        # db_path and cache_dir are only available in single-user mode (server-local resources)
        if not is_multiuser_mode():
            settings_config["db_path"] = {
                "default": "",
                "type": "text",
                "label": "Local Database Directory",
                "description": "Directory containing local databases such as semantic_scholar.db, openalex.db, crossref.db, dblp.db, and acl_anthology.db",
                "section": "Database"
            }
            settings_config["cache_dir"] = {
                "default": "",
                "type": "text",
                "label": "Cache Directory",
                "description": "Directory for caching PDFs, extracted bibliographies, and LLM responses to speed up repeated checks",
                "section": "Database"
            }
        
        # Get current values from database
        settings = {}
        for key, config in settings_config.items():
            if key == "db_path":
                value = (
                    os.environ.get("REFCHECKER_DATABASE_DIRECTORY")
                    or os.environ.get("REFCHECKER_DB_PATH")
                    or await db.get_setting(key)
                )
            elif key == "cache_dir":
                value = os.environ.get("REFCHECKER_CACHE_DIR") or await db.get_setting(key)
            else:
                value = await db.get_setting(key)
            settings[key] = {
                "value": value if value is not None else config["default"],
                "default": config["default"],
                "type": config["type"],
                "label": config["label"],
                "description": config["description"],
                "section": config["section"]
            }
            # Include extra metadata for number types
            if config["type"] == "number":
                settings[key]["min"] = config.get("min")
                settings[key]["max"] = config.get("max")
            if key == "db_path":
                resolved_db_path = await _get_configured_semantic_scholar_db_path()
                settings[key]["current_snapshot"] = _read_semantic_scholar_db_snapshot(resolved_db_path)
        
        return settings
    except Exception as e:
        logger.error(f"Error getting settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/settings/{setting_key}")
async def update_setting(
    setting_key: str,
    update: SettingUpdate,
    current_user: UserInfo = Depends(require_user),
):
    """Update a specific setting"""
    try:
        _require_admin(current_user)
        # Validate the setting key
        valid_keys = {"max_concurrent_checks", "db_path", "cache_dir"}
        if setting_key not in valid_keys:
            raise HTTPException(status_code=400, detail=f"Unknown setting: {setting_key}")
        
        # Apply setting-specific validation
        if setting_key == "max_concurrent_checks":
            try:
                value = int(update.value)
                if value < 1:
                    value = 1
                if value > 50:
                    value = 50
                
                # Update the default limit for new sessions
                await set_default_max_concurrent(value)
                logger.info(f"Updated per-session concurrency limit to {value}")
                
                # Store the validated value
                await db.set_setting(setting_key, str(value))
                
                return {"key": setting_key, "value": str(value), "message": "Setting updated"}
            except ValueError:
                raise HTTPException(status_code=400, detail="max_concurrent_checks must be a number")
        
        if setting_key == "db_path":
            path = update.value.strip()
            if not path:
                await db.set_setting(setting_key, "")
                logger.info("Cleared db_path setting")
                return {
                    "key": setting_key,
                    "value": "",
                    "message": "Local database configuration cleared",
                    "current_snapshot": None,
                }

            path_obj = Path(path).expanduser()
            if path_obj.is_dir():
                summary = _summarize_local_database_directory(path_obj)
                detected_names = [
                    DATABASE_LABELS.get(db_name, db_name)
                    for db_name in summary["db_paths"]
                ]
                warning_messages = [
                    f"{DATABASE_LABELS.get(db_name, db_name)}: {warning}"
                    for db_name, db_summary in summary["validated"].items()
                    for warning in db_summary["warnings"]
                ]

                await db.set_setting(setting_key, str(path_obj))
                logger.info(
                    "Updated db_path to local database directory: %s (%d detected DBs)",
                    path_obj,
                    len(detected_names),
                )

                if detected_names:
                    msg = f"Local database directory configured: {', '.join(detected_names)}"
                else:
                    msg = "Local database directory configured. No recognized database files found yet"
                if warning_messages:
                    msg += f" (⚠ {'; '.join(warning_messages)})"

                s2_path = summary["db_paths"].get("s2")
                current_snapshot = _read_semantic_scholar_db_snapshot(Path(s2_path)) if s2_path else None
                return {
                    "key": setting_key,
                    "value": str(path_obj),
                    "message": msg,
                    "current_snapshot": current_snapshot,
                }

            if not path_obj.is_file():
                raise HTTPException(status_code=400, detail=f"Path not found: {path}")

            db_summary = _validate_local_reference_database_file(path_obj)
            await db.set_setting(setting_key, str(path_obj))
            logger.info(f"Updated db_path to database file: {path_obj} ({db_summary['row_count']:,} papers)")
            msg = f"Database file validated: {db_summary['row_count']:,} papers, {len(db_summary['columns'])} columns"
            if db_summary["warnings"]:
                msg += f" (⚠ {'; '.join(db_summary['warnings'])})"
            return {
                "key": setting_key,
                "value": str(path_obj),
                "message": msg,
                "papers": db_summary["row_count"],
                "current_snapshot": _read_semantic_scholar_db_snapshot(path_obj),
            }
        
        if setting_key == "cache_dir":
            path = update.value.strip()
            if not path:
                await db.set_setting(setting_key, "")
                logger.info("Cleared cache_dir setting")
                return {"key": setting_key, "value": "", "message": "Cache disabled"}
            # Create the directory if it doesn't exist
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Cannot create cache directory: {e}")
            if not os.access(path, os.W_OK):
                raise HTTPException(status_code=400, detail=f"Cache directory is not writable: {path}")
            await db.set_setting(setting_key, path)
            logger.info(f"Updated cache_dir to: {path}")
            return {"key": setting_key, "value": path, "message": "Cache directory configured"}

        # For other settings, just store the value
        await db.set_setting(setting_key, update.value)
        return {"key": setting_key, "value": update.value, "message": "Setting updated"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating setting: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Debug/Admin endpoints

@app.get("/api/admin/analytics/summary")
async def get_admin_analytics_summary(
    days: int = 30,
    current_user: UserInfo = Depends(require_user),
):
    """Return an admin-only analytics summary for recent usage."""
    _require_admin(current_user)
    try:
        return await get_usage_summary(days=days)
    except Exception as e:
        logger.error(f"Error getting analytics summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/analytics/events")
async def get_admin_usage_events(
    limit: int = 100,
    event_type: Optional[str] = None,
    current_user: UserInfo = Depends(require_user),
):
    """Return recent raw usage events for admin inspection."""
    _require_admin(current_user)
    try:
        return await get_usage_events(limit=limit, event_type=event_type)
    except Exception as e:
        logger.error(f"Error getting analytics events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/analytics/events/download")
async def download_usage_events(current_user: UserInfo = Depends(require_user)):
    """Download the raw usage-events JSONL file."""
    _require_admin(current_user)
    log_path = get_usage_log_path()
    if not log_path.is_file():
        raise HTTPException(status_code=404, detail="Usage log file not found")
    return FileResponse(
        str(log_path),
        media_type="application/x-ndjson",
        filename=log_path.name,
    )


@app.get("/api/admin/activity")
async def get_admin_activity(
    limit: int = 200,
    current_user: UserInfo = Depends(require_user),
):
    """Return anonymised user + check activity for admin inspection.

    Each row contains:
    - user_id, provider, email_domain, is_admin, created_at
    - check id, paper_title, paper_source, source_type, status,
      started_at, completed_at, duration_ms, total_refs, errors_count,
      warnings_count, suggestions_count, unverified_count, hallucination_count,
      llm_provider, llm_model, extraction_method, cache_hit
    """
    _require_admin(current_user)
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = aiosqlite.Row

            # Users summary (anonymised: no name/email/avatar, only domain)
            users = []
            async with conn.execute(
                "SELECT id, provider, email, is_admin, created_at FROM users ORDER BY id"
            ) as cursor:
                async for row in cursor:
                    r = dict(row)
                    email = r.pop("email", None)
                    r["email_domain"] = email.split("@", 1)[1] if email and "@" in email else None
                    users.append(r)

            # Recent checks (no results_json to keep response small)
            checks = []
            async with conn.execute(
                """SELECT id, user_id, paper_title, paper_source, source_type,
                          status, started_at, completed_at, duration_ms,
                          total_refs, errors_count, warnings_count,
                          suggestions_count, unverified_count,
                          hallucination_count, refs_with_errors,
                          refs_with_warnings_only, refs_verified,
                          llm_provider, llm_model, extraction_method,
                          cache_hit, original_filename
                   FROM check_history
                   ORDER BY id DESC
                   LIMIT ?""",
                (limit,),
            ) as cursor:
                async for row in cursor:
                    checks.append(dict(row))

        return {"users": users, "checks": checks}
    except Exception as e:
        logger.error(f"Error getting admin activity: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/cache")
async def clear_verification_cache(current_user: UserInfo = Depends(require_user)):
    """Clear the verification cache"""
    _require_admin(current_user)
    try:
        count = await db.clear_verification_cache()
        logger.info(f"Cleared {count} entries from verification cache")
        return {"message": f"Cleared {count} cached verification results", "count": count}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/database")
async def clear_database(current_user: UserInfo = Depends(require_user)):
    """Clear all data (cache + history + usage log file) but keep settings and LLM configs"""
    _require_admin(current_user)
    try:
        # Clear verification cache
        cache_count = await db.clear_verification_cache()
        usage_event_count = await clear_usage_log()
        
        # Clear check history
        async with aiosqlite.connect(db.db_path) as conn:
            history_cursor = await conn.execute("DELETE FROM check_history")
            await conn.commit()
            history_count = history_cursor.rowcount if history_cursor.rowcount != -1 else 0
        
        logger.info(f"Cleared database: {cache_count} cache entries, {history_count} history entries, {usage_event_count} usage events")
        return {
            "message": f"Cleared {cache_count} cache entries, {history_count} history entries, and {usage_event_count} usage events",
            "cache_count": cache_count,
            "history_count": history_count,
            "usage_event_count": usage_event_count,
        }
    except Exception as e:
        logger.error(f"Error clearing database: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Mount static files for bundled frontend (if available)
# This must be after all API routes to avoid conflicts
if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    # Mount assets directory for JS/CSS files
    if (STATIC_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")
    
    @app.get("/favicon.svg")
    async def favicon():
        """Serve favicon"""
        favicon_path = STATIC_DIR / "favicon.svg"
        if favicon_path.exists():
            return FileResponse(str(favicon_path), media_type="image/svg+xml")
        raise HTTPException(status_code=404)
    
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """
        Serve the SPA frontend for all non-API routes.
        This enables client-side routing.
        """
        # Don't serve SPA for API routes (they're handled above)
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        
        # Try to serve the exact file if it exists
        file_path = STATIC_DIR / full_path
        if file_path.exists() and file_path.is_file():
            # Determine content type
            suffix = file_path.suffix.lower()
            media_types = {
                ".html": "text/html",
                ".css": "text/css",
                ".js": "application/javascript",
                ".json": "application/json",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".svg": "image/svg+xml",
                ".ico": "image/x-icon",
            }
            media_type = media_types.get(suffix, "application/octet-stream")
            return FileResponse(str(file_path), media_type=media_type)
        
        # For all other paths, serve index.html (SPA routing)
        index_path = STATIC_DIR / "index.html"
        return FileResponse(
            str(index_path),
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
