"""
FastAPI application for RefChecker Web UI
"""
from contextlib import asynccontextmanager
import asyncio
import time
import uuid
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Body, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic.fields import FieldInfo
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
from .database import db, get_data_dir, get_logs_dir
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
    generate_pdf_page_preview_async,
    get_pdf_page_count_async,
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


def _form_default_value(value):
    if not isinstance(value, FieldInfo):
        return value
    default = value.default
    return None if str(default) == 'PydanticUndefined' else default

UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_FILE_BYTES = int(os.environ.get("MAX_UPLOAD_FILE_BYTES", str(25 * 1024 * 1024)))
# Bulk-mode caps. Defaults raised in v0.7.42 after a user reported a
# 796-paper batch being truncated to 50. The new defaults cover that
# case with headroom: 1000 papers, 500 MB total post-extract, 250 MB
# zip archive. All three remain env-overridable so larger fleets can
# tune further without code changes.
MAX_BATCH_UPLOAD_TOTAL_BYTES = int(os.environ.get("MAX_BATCH_UPLOAD_TOTAL_BYTES", str(500 * 1024 * 1024)))
MAX_BATCH_ARCHIVE_BYTES = int(os.environ.get("MAX_BATCH_ARCHIVE_BYTES", str(250 * 1024 * 1024)))
MAX_BATCH_SIZE = int(os.environ.get("MAX_BATCH_SIZE", "1000"))


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
    openalex_since = os.environ.get('REFCHECKER_OPENALEX_SINCE')
    if db_name == 'openalex' and openalex_since:
        command.extend(['--openalex-since', openalex_since])
    openalex_min_year = os.environ.get('REFCHECKER_OPENALEX_MIN_YEAR')
    if db_name == 'openalex' and openalex_min_year:
        command.extend(['--openalex-min-year', openalex_min_year])

    if db_name == 'openalex' and os.name != 'nt':
        priority_prefix = []
        ionice_path = shutil.which('ionice')
        nice_path = shutil.which('nice')
        if ionice_path:
            priority_prefix.extend([ionice_path, '-c', '3'])
        if nice_path:
            priority_prefix.extend([nice_path, '-n', '10'])
        command = priority_prefix + command

    log_dir = get_logs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"database-refresh-{db_name}.log"

    logger.info(
        "Launching background %s refresh for %s (log: %s)",
        DATABASE_LABELS.get(db_name, db_name),
        db_path,
        log_path,
    )
    log_handle = log_path.open("ab", buffering=0)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(repo_root),
        stdout=log_handle,
        stderr=asyncio.subprocess.STDOUT,
        env=os.environ.copy(),
    )
    try:
        return_code = await process.wait()
    except asyncio.CancelledError:
        if process.returncode is None:
            logger.info(
                "Terminating background %s refresh for %s",
                DATABASE_LABELS.get(db_name, db_name),
                db_path,
            )
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning(
                    "Killing unresponsive background %s refresh for %s",
                    DATABASE_LABELS.get(db_name, db_name),
                    db_path,
                )
                process.kill()
                await process.wait()
        raise
    finally:
        log_handle.close()
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


def _ensure_hallucination_capable_provider(provider_name: Optional[str]) -> None:
    """Reject providers that cannot perform hallucination checks."""
    from refchecker.config.settings import HALLUCINATION_CAPABLE_PROVIDERS

    normalized = (provider_name or "").strip().lower()
    if normalized and normalized not in HALLUCINATION_CAPABLE_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_name}' is only available for extraction, not hallucination checks",
        )


async def _resolve_llm_config_for_request(
    *,
    user_id: int,
    use_llm: bool,
    llm_config_id: Optional[int],
    llm_provider: Optional[str],
    llm_model: Optional[str],
    api_key: Optional[str],
    require_hallucination_capable: bool = False,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Resolve provider/model/key/endpoint from form fields plus a saved config."""
    if not use_llm:
        return llm_provider, llm_model, api_key, None

    effective_api_key = api_key
    endpoint = None
    provider = llm_provider
    model = llm_model

    if llm_config_id:
        config = await db.get_llm_config_by_id(llm_config_id, user_id=user_id)
        if config:
            if not effective_api_key:
                effective_api_key = config.get('api_key')
            endpoint = config.get('endpoint')
            provider = config.get('provider', provider)
            model = config.get('model') or model
            logger.info(f"Using LLM config {llm_config_id}: {provider}/{model}")
        else:
            logger.warning(f"LLM config {llm_config_id} not found")

    if not effective_api_key and provider:
        effective_api_key = await _reuse_provider_key_for_new_config(
            provider=provider,
            user_id=user_id,
        )

    _ensure_allowed_web_llm_provider(provider)
    if require_hallucination_capable:
        _ensure_hallucination_capable_provider(provider)

    return provider, model, effective_api_key, endpoint


async def _reuse_provider_key_for_new_config(
    *,
    provider: str,
    user_id: Optional[int],
) -> Optional[str]:
    """Return an existing same-provider key for single-user config creation."""
    if is_multiuser_mode():
        return None

    configs = await db.get_llm_configs(user_id=user_id)
    for existing in configs:
        if existing.get('provider') == provider and existing.get('has_key'):
            config = await db.get_llm_config_by_id(existing['id'], user_id=user_id)
            if config and config.get('api_key'):
                return config['api_key']
    return None


def _is_invalid_model_error(error: Exception) -> bool:
    """Return True for provider errors that mean the requested model is invalid."""
    message = str(error)
    error_lower = message.lower()
    status_code = getattr(error, 'status_code', None)
    if status_code is None and getattr(error, 'response', None) is not None:
        status_code = getattr(error.response, 'status_code', None)

    mentions_model = 'model' in error_lower
    invalid_model_terms = (
        'not found',
        'does not exist',
        'invalid model',
        'model_not_found',
        'not_found_error',
        'unsupported model',
    )
    return mentions_model and (
        status_code in (400, 404)
        or any(term in error_lower for term in invalid_model_terms)
    )


async def _validate_llm_connection_or_raise(
    *,
    provider: str,
    model: Optional[str],
    api_key: Optional[str],
    endpoint: Optional[str] = None,
) -> None:
    """Validate an LLM provider/model/key combination before persisting it."""
    _ensure_allowed_web_llm_provider(provider)

    try:
        from refchecker.llm.base import create_llm_provider

        llm_config = {}
        if model:
            llm_config['model'] = model
        if api_key:
            llm_config['api_key'] = api_key
        if endpoint:
            llm_config['endpoint'] = endpoint

        llm_provider = create_llm_provider(provider, llm_config)
        if not llm_provider:
            raise HTTPException(status_code=400, detail=f"Failed to create {provider} provider")
        if hasattr(llm_provider, 'is_available') and not llm_provider.is_available():
            raise HTTPException(status_code=400, detail=f"Provider '{provider}' is not available")

        llm_provider._call_llm("Respond with only the word 'ok'.")
    except HTTPException:
        raise
    except Exception as exc:
        error_msg = str(exc)
        error_lower = error_msg.lower()
        logger.error("LLM validation failed: %s", error_msg)

        if _is_invalid_model_error(exc):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid model name. The model '{model}' was not found for provider '{provider}'.",
            )
        if "401" in error_msg or "unauthorized" in error_lower or ("invalid" in error_lower and "api" in error_lower and "key" in error_lower):
            raise HTTPException(status_code=400, detail="Invalid API key")
        if "429" in error_msg or "quota" in error_lower or "rate limit" in error_lower or "rate-limit" in error_lower or "rate_limit" in error_lower or "billing" in error_lower:
            return
        raise HTTPException(status_code=400, detail=f"Validation failed: {error_msg}")


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


def _maybe_convert_to_text(source_path: Path) -> Optional[Path]:
    """Convert office/markup formats to plain text so the existing PDF /
    BibTeX / LaTeX / TXT pipeline can handle them.

    Returns the path to a sibling .txt file when conversion succeeded,
    or None when the file is already a supported native format (no
    conversion needed) OR the format isn't recognised (let the pipeline
    fail with a clearer error downstream).
    """
    suffix = source_path.suffix.lower()
    if suffix not in {".docx", ".odt", ".rtf", ".md", ".markdown", ".html", ".htm"}:
        return None
    out = source_path.with_suffix(source_path.suffix + ".txt")
    try:
        text: Optional[str] = None
        if suffix == ".docx":
            try:
                import zipfile
                import xml.etree.ElementTree as ET
                with zipfile.ZipFile(source_path) as zf:
                    with zf.open("word/document.xml") as f:
                        tree = ET.parse(f)
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                paras = []
                for p in tree.getroot().iter(f"{{{ns['w']}}}p"):
                    chunks = [t.text or "" for t in p.iter(f"{{{ns['w']}}}t")]
                    paras.append("".join(chunks))
                text = "\n".join(paras)
            except Exception as e:
                logger.warning("DOCX extraction failed for %s: %s", source_path.name, e)
        elif suffix == ".rtf":
            raw = source_path.read_text(encoding="utf-8", errors="ignore")
            # Strip RTF control words conservatively — enough to surface
            # citation strings to the LLM/regex parsers.
            import re as _re
            text = _re.sub(r"\\[a-z]+-?\d*\s?", "", raw)
            text = _re.sub(r"[{}]", "", text)
        elif suffix in (".md", ".markdown"):
            text = source_path.read_text(encoding="utf-8", errors="ignore")
        elif suffix in (".html", ".htm"):
            raw = source_path.read_text(encoding="utf-8", errors="ignore")
            try:
                from bs4 import BeautifulSoup
                text = BeautifulSoup(raw, "html.parser").get_text("\n")
            except Exception:
                import re as _re
                text = _re.sub(r"<[^>]+>", "", raw)
        elif suffix == ".odt":
            try:
                import zipfile
                import xml.etree.ElementTree as ET
                with zipfile.ZipFile(source_path) as zf:
                    with zf.open("content.xml") as f:
                        tree = ET.parse(f)
                # Concatenate every text node.
                chunks = [(el.text or "") for el in tree.getroot().iter() if el.text]
                text = "\n".join(c for c in chunks if c.strip())
            except Exception as e:
                logger.warning("ODT extraction failed for %s: %s", source_path.name, e)

        if not text:
            return None
        out.write_text(text, encoding="utf-8")
        logger.info("Converted %s -> %s (%d chars)", source_path.name, out.name, len(text))
        return out
    except Exception as e:
        logger.warning("Conversion failed for %s: %s", source_path.name, e)
        return None


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
                if not any(lower_name.endswith(ext) for ext in [
                    '.pdf', '.txt', '.tex', '.latex', '.bib', '.bbl',
                    '.docx', '.odt', '.rtf', '.md', '.markdown', '.html', '.htm',
                ]):
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
    hallucination_config_id: Optional[int] = None
    hallucination_provider: Optional[str] = None
    hallucination_model: Optional[str] = None
    use_llm: bool = True
    api_key: Optional[str] = None
    hallucination_api_key: Optional[str] = None
    semantic_scholar_api_key: Optional[str] = None


# Create FastAPI app
async def _run_startup_tasks() -> None:
    """Initialize persistent services used by the API."""
    await db.init_db()
    logger.info(f"Usage telemetry log file: {get_usage_log_path()}")
    # Persist LLM token/cost counters across process restarts
    try:
        from . import usage_tracker
        usage_tracker.configure_persistence(get_data_dir() / "llm_usage.json")
    except Exception as e:
        logger.debug("Failed to set up LLM usage persistence: %s", e)

    if is_multiuser_mode():
        try:
            if await db.has_setting("semantic_scholar_api_key"):
                await db.delete_setting("semantic_scholar_api_key")
                logger.info("Removed server-side Semantic Scholar API key in multi-user mode")
        except Exception as e:
            logger.warning(f"Failed to clear Semantic Scholar key in multi-user mode: {e}")

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

    # Hydrate stored API keys into the process env so optional checkers
    # (currently just Paperclip) auto-activate on the next check after
    # a sidecar restart, without forcing the user to re-paste keys.
    if not is_multiuser_mode():
        try:
            stored_paperclip = await db.get_setting("paperclip_api_key")
            if stored_paperclip and not os.environ.get("PAPERCLIP_API_KEY"):
                os.environ["PAPERCLIP_API_KEY"] = stored_paperclip
                logger.info("Paperclip API key restored from settings; secondary tier active")
        except Exception as e:
            logger.debug(f"Could not hydrate Paperclip key: {e}")

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
    try:
        yield
    finally:
        for task in refresh_tasks.values():
            if not task.done():
                task.cancel()
        if refresh_tasks:
            await asyncio.gather(*refresh_tasks.values(), return_exceptions=True)


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
    hallucination_config_id: Optional[int] = Form(None),
    hallucination_provider: Optional[str] = Form(None),
    hallucination_model: Optional[str] = Form(None),
    use_llm: bool = Form(True),
    api_key: Optional[str] = Form(None),
    hallucination_api_key: Optional[str] = Form(None),
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
        semantic_scholar_api_key: SS API key from client, or stored key in single-user mode
        llm_config_id: ID of the LLM config to use (for provider/model/endpoint)
        llm_provider: LLM provider to use
        llm_model: Specific model to use
        use_llm: Whether to use LLM for extraction

    Returns:
        Session ID for tracking progress via WebSocket
    """
    slot_acquired = False
    try:
        source_value = _form_default_value(source_value)
        file = _form_default_value(file)
        source_text = _form_default_value(source_text)
        llm_config_id = _form_default_value(llm_config_id)
        llm_provider = _form_default_value(llm_provider)
        llm_model = _form_default_value(llm_model)
        hallucination_config_id = _form_default_value(hallucination_config_id)
        hallucination_provider = _form_default_value(hallucination_provider)
        hallucination_model = _form_default_value(hallucination_model)
        use_llm = _form_default_value(use_llm)
        api_key = _form_default_value(api_key)
        hallucination_api_key = _form_default_value(hallucination_api_key)
        semantic_scholar_api_key = await _resolve_semantic_scholar_api_key(
            _form_default_value(semantic_scholar_api_key)
        )

        # Generate session ID
        session_id = str(uuid.uuid4())
        check_started_at = utcnow_sqlite()

        user_id = get_user_id_filter(current_user)

        # API keys from form (browser storage) take precedence over stored keys.
        logger.info(f"API key from form: {'present' if api_key else 'MISSING'}, use_llm={use_llm}, provider={llm_provider}")
        llm_provider, llm_model, effective_api_key, endpoint = await _resolve_llm_config_for_request(
            user_id=user_id,
            use_llm=use_llm,
            llm_config_id=llm_config_id,
            llm_provider=llm_provider,
            llm_model=llm_model,
            api_key=api_key,
        )
        resolved_hallucination_provider = hallucination_provider
        resolved_hallucination_model = hallucination_model
        resolved_hallucination_api_key = hallucination_api_key
        resolved_hallucination_endpoint = None
        if hallucination_config_id or hallucination_provider:
            (
                resolved_hallucination_provider,
                resolved_hallucination_model,
                resolved_hallucination_api_key,
                resolved_hallucination_endpoint,
            ) = await _resolve_llm_config_for_request(
                user_id=user_id,
                use_llm=use_llm,
                llm_config_id=hallucination_config_id,
                llm_provider=hallucination_provider,
                llm_model=hallucination_model,
                api_key=hallucination_api_key,
                require_hallucination_capable=True,
            )
        logger.info(
            "Effective LLMs resolved: extraction=%s/%s key=%s; hallucination=%s/%s key=%s; SS=%s",
            llm_provider,
            llm_model,
            'present' if effective_api_key else 'MISSING',
            resolved_hallucination_provider,
            resolved_hallucination_model,
            'present' if resolved_hallucination_api_key else 'MISSING',
            'present' if semantic_scholar_api_key else 'MISSING',
        )

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

            # Office/markup formats: convert to plain text in-place so the
            # downstream pipeline (which only knows pdf / tex / bib / txt)
            # sees something it can parse. The original upload stays on
            # disk under its real name for history; processing reads the
            # generated .txt alongside it.
            converted = _maybe_convert_to_text(file_path)
            if converted is not None:
                paper_source = str(converted)
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
            hallucination_provider=resolved_hallucination_provider if use_llm else None,
            hallucination_model=resolved_hallucination_model if use_llm else None,
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
                "hallucination_provider": resolved_hallucination_provider if use_llm else None,
                "hallucination_model": resolved_hallucination_model if use_llm else None,
                "input_bytes": input_bytes,
                "semantic_scholar_key_present": bool(semantic_scholar_api_key),
                "original_filename_ext": Path(original_filename).suffix.lower() if original_filename else None,
            },
        )

        # Start check in background
        cancel_event = asyncio.Event()
        task = asyncio.create_task(
            run_check(
                session_id, check_id, paper_source, source_type,
                llm_provider, llm_model, effective_api_key, endpoint,
                use_llm, cancel_event, user_id,
                semantic_scholar_api_key=semantic_scholar_api_key,
                hallucination_provider=resolved_hallucination_provider,
                hallucination_model=resolved_hallucination_model,
                hallucination_api_key=resolved_hallucination_api_key,
                hallucination_endpoint=resolved_hallucination_endpoint,
            )
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
    hallucination_provider: Optional[str] = None,
    hallucination_model: Optional[str] = None,
    hallucination_api_key: Optional[str] = None,
    hallucination_endpoint: Optional[str] = None,
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
        semantic_scholar_api_key: Semantic Scholar API key from browser storage or the single-user database
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
                            refs_with_suggestions_only=data.get("refs_with_suggestions_only", 0),
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
            hallucination_provider=hallucination_provider,
            hallucination_model=hallucination_model,
            hallucination_api_key=hallucination_api_key,
            hallucination_endpoint=hallucination_endpoint,
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
        bibliography_source_kind = (
            result.get("bibliography_source_kind")
            or infer_bibliography_source_kind(result.get("extraction_method"))
        )
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
            refs_with_suggestions_only=result["summary"].get("refs_with_suggestions_only", 0),
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
                "hallucination_provider": hallucination_provider,
                "hallucination_model": hallucination_model,
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


async def _resolve_pdf_path_for_check(check: Dict[str, Any], cache_dir: str) -> Optional[str]:
    """Resolve a check record to a local PDF path on disk.

    Mirrors the same source-type cascade /api/preview uses (direct PDF
    URL → arXiv abstract URL → uploaded file) so the new per-page
    endpoints don't drift from the single-page preview's resolution
    logic. Returns None when the source can't be rendered as a PDF
    (text checks, non-PDF uploads, missing files).
    """
    paper_source = check.get("paper_source") or ""
    source_type = check.get("source_type") or "url"
    if "openreview.net/forum" in paper_source.lower():
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(paper_source)
        params = parse_qs(parsed.query)
        or_id = params.get("id", [None])[0]
        if or_id:
            paper_source = f"https://openreview.net/pdf?id={or_id}"
    import re as _re
    arxiv_match = _re.search(r"(\d{4}\.\d{4,5})(v\d+)?", paper_source)
    is_direct_pdf_url = (
        source_type == "url"
        and (paper_source.lower().endswith(".pdf") or "openreview.net/pdf" in paper_source.lower())
        and "arxiv.org" not in paper_source.lower()
    )
    if is_direct_pdf_url:
        from backend.refchecker_wrapper import download_pdf
        pdf_path = get_pdf_storage_path(paper_source, cache_dir=cache_dir)
        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
            try:
                await asyncio.to_thread(download_pdf, paper_source, pdf_path)
            except Exception as e:
                logger.debug(f"download_pdf failed for page render: {e}")
                return None
        return pdf_path if os.path.exists(pdf_path) else None
    if arxiv_match:
        # Use the same cache-key + download helper that
        # `generate_arxiv_preview` uses (`source_identifier="arxiv_<id>"`
        # + `_download_arxiv_pdf`). Otherwise opening this overlay on an
        # arXiv check after the single-page preview has already cached
        # the PDF triggers a wasted second download keyed by a different
        # source_identifier, and the existing first-page cache wouldn't
        # be reused by the per-page renderer either.
        from .thumbnail import _download_arxiv_pdf
        arxiv_id = arxiv_match.group(1)
        source_identifier = f"arxiv_{arxiv_id}"
        pdf_path = get_pdf_storage_path(source_identifier, cache_dir=cache_dir)
        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
            ok = await asyncio.to_thread(_download_arxiv_pdf, arxiv_id, pdf_path)
            if not ok:
                return None
        return pdf_path if os.path.exists(pdf_path) else None
    if source_type == "file" and paper_source.lower().endswith(".pdf"):
        return paper_source if os.path.exists(paper_source) else None
    return None


@app.get("/api/preview/{check_id}/page-count")
async def get_preview_page_count(check_id: int, current_user: UserInfo = Depends(require_user)):
    """Number of pages in the paper backing this check. Powers the
    multi-page scrollable preview overlay so the frontend knows how many
    page slots to render. Returns 0 for non-PDF sources (text/HTML/etc),
    which the frontend treats as "fall back to single preview"."""
    check = await _get_owned_check_or_404(check_id, current_user)
    cache_dir = await _get_configured_cache_dir()
    pdf_path = await _resolve_pdf_path_for_check(check, cache_dir)
    if not pdf_path:
        return {"count": 0}
    count = await get_pdf_page_count_async(pdf_path)
    return {"count": count}


@app.get("/api/preview/{check_id}/page/{page_index}")
async def get_preview_page(
    check_id: int,
    page_index: int,
    current_user: UserInfo = Depends(require_user),
):
    """Render and return a single PDF page as a PNG. Pages are cached
    per-source so the overlay scroll feels instant after the first
    fetch. `page_index` is 0-based."""
    if page_index < 0 or page_index > 9999:
        raise HTTPException(status_code=400, detail="page_index out of range")
    check = await _get_owned_check_or_404(check_id, current_user)
    cache_dir = await _get_configured_cache_dir()
    pdf_path = await _resolve_pdf_path_for_check(check, cache_dir)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="No PDF source for this check")
    page_path = await generate_pdf_page_preview_async(
        pdf_path, page_index, source_identifier=pdf_path, cache_dir=cache_dir,
    )
    if not page_path or not os.path.exists(page_path):
        raise HTTPException(status_code=404, detail="Page not available")
    return FileResponse(
        page_path,
        media_type="image/png",
        headers=_private_artifact_headers(),
    )


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

        # Module-level cap (defaults to 1000 in v0.7.42; env-overridable).
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
        semantic_scholar_api_key = await _resolve_semantic_scholar_api_key(
            request.semantic_scholar_api_key
        )

        llm_provider, llm_model, effective_api_key, endpoint = await _resolve_llm_config_for_request(
            user_id=user_id,
            use_llm=request.use_llm,
            llm_config_id=request.llm_config_id,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
            api_key=request.api_key,
        )
        resolved_hallucination_provider = request.hallucination_provider
        resolved_hallucination_model = request.hallucination_model
        resolved_hallucination_api_key = request.hallucination_api_key
        resolved_hallucination_endpoint = None
        if request.hallucination_config_id or request.hallucination_provider:
            (
                resolved_hallucination_provider,
                resolved_hallucination_model,
                resolved_hallucination_api_key,
                resolved_hallucination_endpoint,
            ) = await _resolve_llm_config_for_request(
                user_id=user_id,
                use_llm=request.use_llm,
                llm_config_id=request.hallucination_config_id,
                llm_provider=request.hallucination_provider,
                llm_model=request.hallucination_model,
                api_key=request.hallucination_api_key,
                require_hallucination_capable=True,
            )

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
                "semantic_scholar_key_present": bool(semantic_scholar_api_key),
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
                hallucination_provider=resolved_hallucination_provider if request.use_llm else None,
                hallucination_model=resolved_hallucination_model if request.use_llm else None,
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
                    semantic_scholar_api_key=semantic_scholar_api_key,
                    hallucination_provider=resolved_hallucination_provider,
                    hallucination_model=resolved_hallucination_model,
                    hallucination_api_key=resolved_hallucination_api_key,
                    hallucination_endpoint=resolved_hallucination_endpoint,
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
    hallucination_config_id: Optional[int] = Form(None),
    hallucination_provider: Optional[str] = Form(None),
    hallucination_model: Optional[str] = Form(None),
    use_llm: bool = Form(True),
    api_key: Optional[str] = Form(None),
    hallucination_api_key: Optional[str] = Form(None),
    semantic_scholar_api_key: Optional[str] = Form(None),
    current_user: UserInfo = Depends(require_user),
    http_request: Request = None,
):
    """
    Start a batch of reference checks from uploaded files.
    
    Accepts multiple files or a single ZIP file containing documents.
    """
    try:
        batch_label = _form_default_value(batch_label)
        llm_config_id = _form_default_value(llm_config_id)
        llm_provider = _form_default_value(llm_provider)
        llm_model = _form_default_value(llm_model)
        hallucination_config_id = _form_default_value(hallucination_config_id)
        hallucination_provider = _form_default_value(hallucination_provider)
        hallucination_model = _form_default_value(hallucination_model)
        use_llm = _form_default_value(use_llm)
        api_key = _form_default_value(api_key)
        hallucination_api_key = _form_default_value(hallucination_api_key)
        semantic_scholar_api_key = _form_default_value(semantic_scholar_api_key)

        if not files or len(files) == 0:
            raise HTTPException(status_code=400, detail="No files provided")

        # MAX_BATCH_SIZE is the module-level constant (defaults to 1000
        # in v0.7.42; env-overridable).

        # Generate unique batch ID
        batch_id = str(uuid.uuid4())
        started_at = utcnow_sqlite()

        user_id = get_user_id_filter(current_user)
        uploads_dir = get_uploads_dir() / str(user_id)
        uploads_dir.mkdir(parents=True, exist_ok=True)
        
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

        semantic_scholar_api_key = await _resolve_semantic_scholar_api_key(
            semantic_scholar_api_key
        )

        llm_provider, llm_model, effective_api_key, endpoint = await _resolve_llm_config_for_request(
            user_id=user_id,
            use_llm=use_llm,
            llm_config_id=llm_config_id,
            llm_provider=llm_provider,
            llm_model=llm_model,
            api_key=api_key,
        )
        resolved_hallucination_provider = hallucination_provider
        resolved_hallucination_model = hallucination_model
        resolved_hallucination_api_key = hallucination_api_key
        resolved_hallucination_endpoint = None
        if hallucination_config_id or hallucination_provider:
            (
                resolved_hallucination_provider,
                resolved_hallucination_model,
                resolved_hallucination_api_key,
                resolved_hallucination_endpoint,
            ) = await _resolve_llm_config_for_request(
                user_id=user_id,
                use_llm=use_llm,
                llm_config_id=hallucination_config_id,
                llm_provider=hallucination_provider,
                llm_model=hallucination_model,
                api_key=hallucination_api_key,
                require_hallucination_capable=True,
            )
        
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
                "semantic_scholar_key_present": bool(semantic_scholar_api_key),
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
                hallucination_provider=resolved_hallucination_provider if use_llm else None,
                hallucination_model=resolved_hallucination_model if use_llm else None,
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
                    "semantic_scholar_key_present": bool(semantic_scholar_api_key),
                    "input_bytes": file_size,
                    "original_filename_ext": Path(file_info['filename']).suffix.lower(),
                },
            )
            
            cancel_event = asyncio.Event()
            task = asyncio.create_task(
                run_check(
                    session_id, check_id, file_info['path'], 'file',
                    llm_provider, llm_model, effective_api_key, endpoint,
                    use_llm, cancel_event, user_id,
                    semantic_scholar_api_key=semantic_scholar_api_key,
                    hallucination_provider=resolved_hallucination_provider,
                    hallucination_model=resolved_hallucination_model,
                    hallucination_api_key=resolved_hallucination_api_key,
                    hallucination_endpoint=resolved_hallucination_endpoint,
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


@app.get("/api/batch/{batch_id}/llm-usage")
async def get_batch_llm_usage(
    batch_id: str,
    current_user: UserInfo = Depends(require_user),
):
    """Aggregate LLM token + cost spend across every child check in a
    batch — one call to the FE instead of N child fetches.

    Returns the same shape as the per-check /llm-usage endpoint plus a
    `per_check` map so the FE can sort children by cost. Soft-fails on
    individual children so a single missing snapshot doesn't blank the
    batch number.
    """
    await _get_owned_batch_or_404(batch_id, current_user)
    user_id = get_user_id_filter(current_user)
    checks = await db.get_batch_checks(batch_id, user_id=user_id)
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).parent.parent / "src"))
        from refchecker.llm import usage_tracker
    except Exception as e:
        logger.warning(f"batch llm-usage import failed: {e}")
        return {
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "calls": 0, "by_flow": {}, "by_model": {}, "per_check": {},
        }
    agg = {
        "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        "calls": 0, "by_flow": {}, "by_model": {}, "per_check": {},
    }
    for check in checks or []:
        cid = check.get("id")
        if cid is None:
            continue
        try:
            snap = usage_tracker.snapshot(str(cid))
        except Exception:
            continue
        agg["input_tokens"] += int(snap.get("input_tokens") or 0)
        agg["output_tokens"] += int(snap.get("output_tokens") or 0)
        agg["cost_usd"] += float(snap.get("cost_usd") or 0.0)
        agg["calls"] += int(snap.get("calls") or 0)
        for flow, sub in (snap.get("by_flow") or {}).items():
            fb = agg["by_flow"].setdefault(flow, {
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0,
            })
            fb["input_tokens"] += int(sub.get("input_tokens") or 0)
            fb["output_tokens"] += int(sub.get("output_tokens") or 0)
            fb["cost_usd"] += float(sub.get("cost_usd") or 0.0)
            fb["calls"] += int(sub.get("calls") or 0)
        for model, sub in (snap.get("by_model") or {}).items():
            mb = agg["by_model"].setdefault(model, {
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            })
            mb["input_tokens"] += int(sub.get("input_tokens") or 0)
            mb["output_tokens"] += int(sub.get("output_tokens") or 0)
            mb["cost_usd"] += float(sub.get("cost_usd") or 0.0)
        if snap.get("cost_usd") or snap.get("input_tokens") or snap.get("output_tokens"):
            agg["per_check"][cid] = {
                "cost_usd": snap.get("cost_usd") or 0.0,
                "input_tokens": snap.get("input_tokens") or 0,
                "output_tokens": snap.get("output_tokens") or 0,
                "calls": snap.get("calls") or 0,
            }
    return agg


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
        if not store_key:
            store_key = await _reuse_provider_key_for_new_config(
                provider=config.provider,
                user_id=user_id,
            )
        if store_key and not is_multiuser_mode():
            await _validate_llm_connection_or_raise(
                provider=config.provider,
                model=config.model,
                api_key=store_key,
                endpoint=config.endpoint,
            )
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
        existing_config = await db.get_llm_config_by_id(config_id, user_id=user_id)
        if not existing_config:
            raise HTTPException(status_code=404, detail="Config not found")

        # In single-user mode, store the API key in the database
        store_key = config.api_key if not is_multiuser_mode() else None
        validation_provider = config.provider or existing_config.get('provider')
        validation_model = config.model if config.model is not None else existing_config.get('model')
        validation_endpoint = config.endpoint if config.endpoint is not None else existing_config.get('endpoint')
        validation_key = store_key or existing_config.get('api_key')
        provider_changed = config.provider is not None and config.provider != existing_config.get('provider')
        model_changed = config.model is not None and config.model != existing_config.get('model')
        endpoint_changed = config.endpoint is not None and config.endpoint != existing_config.get('endpoint')
        key_changed = bool(store_key)
        if validation_key and not is_multiuser_mode() and (provider_changed or model_changed or endpoint_changed or key_changed):
            await _validate_llm_connection_or_raise(
                provider=validation_provider,
                model=validation_model,
                api_key=validation_key,
                endpoint=validation_endpoint,
            )
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
        test_response = provider._call_llm("Respond with only the word 'ok'.")
        
        # If we get here without an exception, the API key and model are valid.
        # Some models return empty text for trivial prompts (e.g. when a
        # system prompt tells them to extract references), so we treat
        # empty-but-no-error as success.
        return {"valid": True, "message": "Connection successful"}
            
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        error_lower = error_msg.lower()
        logger.error(f"LLM validation failed: {error_msg}")

        # 429 / quota / rate-limit errors mean the key IS valid but the
        # account has a billing or rate issue.  Return success with a warning
        # so the user can still save the config.
        # NOTE: match "rate limit" / "rate-limit" instead of bare "rate" to
        # avoid false positives (e.g. "generateContent" contains "rate").
        if "429" in error_msg or "quota" in error_lower or "exceeded" in error_lower or "rate limit" in error_lower or "rate-limit" in error_lower or "rate_limit" in error_lower or "billing" in error_lower:
            warning = "API key is valid, but the account has a quota or rate-limit issue. Check your plan and billing details."
            logger.info(f"LLM validation passed with warning: {warning}")
            return {"valid": True, "message": "Connection validated (with warning)", "warning": warning}
        elif _is_invalid_model_error(e):
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


async def _resolve_semantic_scholar_api_key(api_key: Optional[str]) -> Optional[str]:
    """Use per-request browser keys first, then the single-user stored key."""
    if api_key:
        return api_key
    if is_multiuser_mode():
        return None
    return await db.get_setting("semantic_scholar_api_key")


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
    """Return Semantic Scholar API key storage status for the current mode."""
    if is_multiuser_mode():
        return {
            "has_key": False,
            "storage": "browser-only",
            "message": "Semantic Scholar API keys are encrypted in the browser cache and are not stored on the server",
        }

    has_key = await db.has_setting("semantic_scholar_api_key")
    return {
        "has_key": has_key,
        "storage": "database",
        "message": "Semantic Scholar API keys are encrypted in the local RefChecker database",
    }


@app.put("/api/settings/semantic-scholar")
async def set_semantic_scholar_key(
    data: SemanticScholarKeyUpdate,
    current_user: UserInfo = Depends(require_user),
):
    """Store the Semantic Scholar key in single-user mode only."""
    if is_multiuser_mode():
        raise HTTPException(
            status_code=410,
            detail="Semantic Scholar API keys are encrypted in the browser cache and are not stored on the server",
        )
    api_key = (data.api_key or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    await db.set_setting("semantic_scholar_api_key", api_key)
    return {
        "has_key": True,
        "storage": "database",
        "message": "Semantic Scholar API key saved encrypted in the local RefChecker database",
    }


@app.delete("/api/settings/semantic-scholar")
async def delete_semantic_scholar_key(current_user: UserInfo = Depends(require_user)):
    """Delete the single-user stored Semantic Scholar key."""
    if is_multiuser_mode():
        raise HTTPException(
            status_code=410,
            detail="Semantic Scholar API keys are encrypted in the browser cache and are not stored on the server",
        )
    await db.delete_setting("semantic_scholar_api_key")
    return {
        "has_key": False,
        "storage": "database",
        "message": "Semantic Scholar API key removed from the local RefChecker database",
    }


class PaperclipKeyUpdate(BaseModel):
    api_key: str


@app.get("/api/settings/paperclip")
async def get_paperclip_key_status(current_user: UserInfo = Depends(require_user)):
    """Return Paperclip API key storage status."""
    if is_multiuser_mode():
        return {
            "has_key": False,
            "storage": "browser-only",
            "message": "Paperclip API keys are stored in the browser cache only",
        }
    has_key = await db.has_setting("paperclip_api_key")
    return {
        "has_key": has_key,
        "storage": "database",
        "message": (
            "Paperclip API key saved encrypted in the local RefChecker database. "
            "The next check automatically enables the Paperclip secondary tier."
        ),
    }


@app.put("/api/settings/paperclip")
async def set_paperclip_key(
    data: PaperclipKeyUpdate,
    current_user: UserInfo = Depends(require_user),
):
    """Store the Paperclip key and surface it as PAPERCLIP_API_KEY so
    EnhancedHybridReferenceChecker auto-activates the tier."""
    if is_multiuser_mode():
        raise HTTPException(
            status_code=410,
            detail="Paperclip API keys are stored in the browser cache only",
        )
    api_key = (data.api_key or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    await db.set_setting("paperclip_api_key", api_key)
    # Propagate to the running process's env so the next check picks it
    # up without restarting the sidecar.
    os.environ["PAPERCLIP_API_KEY"] = api_key
    return {
        "has_key": True,
        "storage": "database",
        "message": "Paperclip API key saved and activated for the next check",
    }


@app.delete("/api/settings/paperclip")
async def delete_paperclip_key(current_user: UserInfo = Depends(require_user)):
    """Remove the stored Paperclip key and clear the env var."""
    if is_multiuser_mode():
        raise HTTPException(
            status_code=410,
            detail="Paperclip API keys are stored in the browser cache only",
        )
    await db.delete_setting("paperclip_api_key")
    os.environ.pop("PAPERCLIP_API_KEY", None)
    return {
        "has_key": False,
        "storage": "database",
        "message": "Paperclip API key removed; the secondary tier is now disabled",
    }


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
            "extraction_mode": {
                "default": "cascade",
                "type": "select",
                "label": "Reference Extraction",
                "description": "Cascade: try regex/BibTeX/GROBID first and only fall back to LLM for messy or unrecognized entries (uses fewer tokens). LLM-only: send every reference to the LLM unconditionally.",
                "options": ["cascade", "llm-only"],
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
        valid_keys = {"max_concurrent_checks", "db_path", "cache_dir", "extraction_mode"}
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

        if setting_key == "extraction_mode":
            mode = (update.value or "").strip().lower()
            if mode not in ("cascade", "llm-only"):
                raise HTTPException(status_code=400, detail="extraction_mode must be 'cascade' or 'llm-only'")
            await db.set_setting(setting_key, mode)
            os.environ["REFCHECKER_EXTRACTION_MODE"] = mode
            logger.info(f"Updated extraction_mode -> {mode}")
            return {"key": setting_key, "value": mode, "message": "Setting updated"}

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


# ---------------------------------------------------------------------------
# Local database downloader — user-triggered build of S2/DBLP/OpenAlex
# databases via the existing local_database_updater script. Used by the
# desktop app's settings panel to onboard users who want offline checks
# without dropping to the CLI.
# ---------------------------------------------------------------------------

class _DBDownloadTask:
    __slots__ = ("task", "started_at", "finished_at", "status", "error", "log_path")

    def __init__(self, task: asyncio.Task, log_path: Path):
        self.task = task
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.status: str = "running"  # running | success | failed | cancelled
        self.error: Optional[str] = None
        self.log_path = log_path


_DB_DOWNLOAD_TASKS: Dict[str, _DBDownloadTask] = {}
_DB_DOWNLOAD_SUPPORTED = ("s2", "dblp", "openalex")


class _DBDownloadRequest(BaseModel):
    databases: list[str]
    directory: Optional[str] = None
    openalex_min_year: Optional[int] = None


def _resolve_download_directory(directory: Optional[str]) -> Path:
    """Pick the target directory for downloaded DBs. Persists to settings."""
    candidate: Optional[Path] = None
    if directory:
        candidate = Path(directory).expanduser()
    else:
        configured = os.environ.get("REFCHECKER_DATABASE_DIRECTORY")
        if configured:
            candidate = Path(configured).expanduser()
        else:
            candidate = get_data_dir() / "databases"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


async def _start_db_download(db_name: str, db_path: Path, openalex_min_year: Optional[int]) -> None:
    """Wrap _run_database_refresh_subprocess with state tracking."""
    prior = _DB_DOWNLOAD_TASKS.get(db_name)
    if prior and prior.status == "running":
        return  # idempotent: don't start a second copy
    if db_name == "openalex" and openalex_min_year:
        os.environ["REFCHECKER_OPENALEX_MIN_YEAR"] = str(openalex_min_year)

    log_path = get_logs_dir() / f"database-refresh-{db_name}.log"
    task = asyncio.create_task(
        _run_database_refresh_subprocess(db_name, db_path),
        name=f"db-download-{db_name}",
    )
    state = _DBDownloadTask(task=task, log_path=log_path)
    _DB_DOWNLOAD_TASKS[db_name] = state

    def _on_done(t: asyncio.Task) -> None:
        state.finished_at = time.time()
        if t.cancelled():
            state.status = "cancelled"
        elif t.exception() is not None:
            state.status = "failed"
            state.error = str(t.exception())
        else:
            state.status = "success"

    task.add_done_callback(_on_done)


def _read_log_tail(path: Path, lines: int = 25) -> str:
    if not path.is_file():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def _find_ref_index(refs: list, ref_id: str) -> Optional[int]:
    """Resolve a ref_id from the URL to a position in ``refs``.

    Accepts (in order): explicit ``id`` match, 1-based ``index`` match,
    or 0-based positional index. This is forgiving because different UI
    paths send different identifiers (manual-added refs have an id like
    'manual-...', extracted refs use index, and 'just clicked the 3rd row'
    sends the array position).
    """
    if not refs:
        return None
    # 1) explicit id match
    for i, r in enumerate(refs):
        rid = r.get("id")
        if rid is not None and str(rid) == ref_id:
            return i
    # 2) 1-based index match
    for i, r in enumerate(refs):
        idx = r.get("index")
        if idx is not None and str(idx) == ref_id:
            return i
    # 3) array position fallback
    try:
        pos = int(ref_id)
        if 0 <= pos < len(refs):
            return pos
    except (TypeError, ValueError):
        pass
    return None


class _AddReferenceRequest(BaseModel):
    title: Optional[str] = None
    authors: Optional[list] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    cited_url: Optional[str] = None
    # Insertion position. None = append (default, "Add reference"
    # button). The "Undo Remove" flow passes the original position so
    # the restored ref lands back where it was, not at the bottom.
    insert_at_index: Optional[int] = None


async def _resolve_doi_via_crossref(doi: str) -> Optional[Dict[str, Any]]:
    """Hit CrossRef for a DOI and return a normalized metadata dict.

    Used by the "Add by DOI" flow: the user types a single DOI and the
    backend fills in title/authors/year/venue so they don't have to. Best
    effort — we return None on any failure so the caller can fall back to
    inserting just the DOI and letting Verify pick up the rest.
    """
    doi = (doi or "").strip()
    if not doi:
        return None
    # Accept https://doi.org/..., http://dx.doi.org/..., and bare 10.* —
    # strip the prefix. Also strip ?query / #fragment / trailing whitespace
    # so the user pasting `https://doi.org/10.1038/foo#section` still works.
    if doi.lower().startswith("http"):
        if "doi.org/" in doi:
            doi = doi.split("doi.org/", 1)[1]
        else:
            return None
    doi = doi.split("?", 1)[0].split("#", 1)[0].strip()
    if not doi.lower().startswith("10."):
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"https://api.crossref.org/works/{doi}",
                headers={
                    # Polite-pool: identify ourselves so CrossRef can throttle
                    # us by user rather than IP.
                    "User-Agent": "RefChecker/desktop (https://github.com/ArioMoniri/refchecker)",
                },
            )
            r.raise_for_status()
            data = (r.json() or {}).get("message") or {}
    except Exception as e:
        logger.debug(f"CrossRef DOI lookup failed for {doi}: {e}")
        return None
    titles = data.get("title") or []
    title = titles[0] if isinstance(titles, list) and titles else None
    authors = []
    for a in (data.get("author") or []):
        full = " ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name")
        if full:
            authors.append(full)
    year = None
    for k in ("published-print", "published-online", "published", "issued", "created"):
        parts = ((data.get(k) or {}).get("date-parts") or [[]])[0]
        if parts and isinstance(parts[0], int):
            year = parts[0]
            break
    venue = None
    cts = data.get("container-title") or []
    if isinstance(cts, list) and cts:
        venue = cts[0]
    return {
        "doi": doi,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "cited_url": f"https://doi.org/{doi}",
        "source": "crossref",
    }


@app.get("/api/doi/resolve")
async def resolve_doi(
    doi: str,
    current_user: UserInfo = Depends(require_user),
):
    """Resolve a DOI to title/authors/year/venue via CrossRef. Powers the
    'Add by DOI' one-field input on the References tab so the user can
    add a citation by pasting just the DOI."""
    meta = await _resolve_doi_via_crossref(doi)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Could not resolve DOI: {doi}")
    return meta


def _clean_doi_for_lookup(doi: str) -> str:
    """Strip common DOI URL/prefix forms so what's left is the bare DOI
    (`10.x/y/z`)."""
    s = (doi or '').strip()
    for prefix in ('https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/',
                   'http://dx.doi.org/', 'doi:'):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix):]
            break
    return s.strip()


@app.get("/api/oclc-lookup")
async def lookup_oclc(
    doi: str,
    current_user: UserInfo = Depends(require_user),
):
    """Best-effort DOI -> OCLC via Wikidata SPARQL.

    Wikidata stores DOI as P356 and OCLC control number as P243. When
    a work is in Wikidata with both properties (mostly books and
    well-known journal articles), we can offer the user a direct
    `worldcat.org/oclc/{number}` link instead of the search URL. Hit
    rate is low (Wikidata's article-level coverage is patchy), so
    this endpoint is called LAZILY by the UI — only when the user
    actually clicks the WorldCat chip.

    Cached aggressively because (a) Wikidata responses are slow
    (1–3 s) and (b) the same DOI gets clicked many times across
    sessions. No auth required by Wikidata; we set a polite
    User-Agent.
    """
    import httpx
    from refchecker.utils.cache_utils import cached_api_response, cache_api_response

    clean = _clean_doi_for_lookup(doi)
    if not clean or '/' not in clean:
        return {"oclc": None, "doi": doi, "source": "wikidata"}

    # Strict DOI shape: 10.{registrant}/{suffix}. Reject anything else
    # before building the SPARQL — defence-in-depth against query
    # injection on top of the escaping below. Real DOIs never contain
    # double quotes, backslashes, or control characters.
    import re as _re
    if not _re.match(r'^10\.\d{4,9}/[^\s"\\\x00-\x1f]+$', clean):
        return {"oclc": None, "doi": doi, "source": "wikidata", "error": "doi_shape"}

    cache_key = clean.lower()
    cached = cached_api_response(None, 'wikidata', 'doi_to_oclc', cache_key)
    if cached is not None:
        return cached

    # Wikidata stores most DOIs in uppercase but a few in lowercase —
    # try both via UNION so we never miss on case alone.
    def _esc_literal(s: str) -> str:
        # SPARQL string-literal escaping: backslash and quote. Newlines
        # are also illegal but the shape regex above already excludes
        # them.
        return s.replace('\\', '\\\\').replace('"', '\\"')
    upper_lit = _esc_literal(clean.upper())
    lower_lit = _esc_literal(clean.lower())
    query = (
        'SELECT ?oclc WHERE { '
        f'{{ ?work wdt:P356 "{upper_lit}" }} UNION '
        f'{{ ?work wdt:P356 "{lower_lit}" }} '
        '?work wdt:P243 ?oclc. } LIMIT 1'
    )
    # Wikimedia's UA policy requires a contact method, not just a repo
    # URL — keep an email reachable.
    headers = {
        'Accept': 'application/sparql-results+json',
        'User-Agent': (
            'RefChecker/1.0 '
            '(https://github.com/ariomoniri/refchecker; moniriario@gmail.com)'
        ),
    }
    result: Dict[str, Any] = {"oclc": None, "doi": clean, "source": "wikidata"}
    is_authoritative = False  # True only when Wikidata gave us a clean 200
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                'https://query.wikidata.org/sparql',
                params={'query': query},
                headers=headers,
            )
        if response.status_code == 200:
            is_authoritative = True
            data = response.json()
            bindings = data.get('results', {}).get('bindings', [])
            if bindings:
                oclc_value = (bindings[0].get('oclc') or {}).get('value')
                if oclc_value:
                    # Wikidata returns OCLC as a bare integer string;
                    # strip any accidental whitespace and validate it's
                    # all digits before surfacing.
                    oclc_clean = ''.join(ch for ch in str(oclc_value) if ch.isdigit())
                    if oclc_clean:
                        result["oclc"] = oclc_clean
                        result["worldcat_url"] = f"https://www.worldcat.org/oclc/{oclc_clean}"
        else:
            logger.debug(f"Wikidata SPARQL returned {response.status_code} for DOI {clean}")
    except Exception as e:
        logger.debug(f"Wikidata OCLC lookup failed for {clean}: {e}")

    # Only cache RESPONSES — not transient failures (timeout / 5xx /
    # network error). Locking those in would keep the user stuck with
    # "no OCLC found" forever for a DOI Wikidata actually knows about.
    if is_authoritative:
        cache_api_response(None, 'wikidata', 'doi_to_oclc', cache_key, result)
    return result


@app.post("/api/history/{check_id}/references")
async def add_reference_to_check(
    check_id: int,
    payload: _AddReferenceRequest,
    current_user: UserInfo = Depends(require_user),
):
    """Append a new reference to an existing check. Status starts as
    'pending'; the frontend can show it greyed out and the user can
    trigger a re-verify or rerun the check to validate it for real.

    When the payload contains a DOI but no title (the "Add by DOI" flow),
    we resolve via CrossRef so the row shows up with real metadata
    instead of an empty placeholder."""
    user_id = get_user_id_filter(current_user)
    refs = await db.get_check_references(check_id, user_id=user_id)
    if refs is None:
        raise HTTPException(status_code=404, detail="Check not found")

    title = payload.title
    authors = payload.authors
    year = payload.year
    venue = payload.venue
    cited_url = payload.cited_url
    doi_value = payload.doi
    # If the user gave us a DOI without other metadata, fill it in. Best
    # effort: if CrossRef is down we still insert the DOI as a pending
    # reference that can be re-verified once the network is back.
    if doi_value and not (title or (authors and len(authors) > 0)):
        meta = await _resolve_doi_via_crossref(doi_value)
        if meta:
            title = title or meta.get("title")
            authors = authors or meta.get("authors")
            year = year or meta.get("year")
            venue = venue or meta.get("venue")
            cited_url = cited_url or meta.get("cited_url")
            doi_value = meta.get("doi") or doi_value

    new_ref = {
        "id": f"manual-{int(time.time() * 1000)}",
        "index": (max((r.get("index") or 0) for r in refs) + 1) if refs else 1,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "doi": doi_value,
        "arxiv_id": payload.arxiv_id,
        "cited_url": cited_url,
        "status": "pending",
        "errors": [],
        "warnings": [],
        "suggestions": [{"message": "Added manually — re-run the check or click Verify to validate.", "error_type": "manual"}],
    }
    # Insert at the requested position when the caller specified one
    # (Undo Remove sends the original index). Append otherwise so the
    # default "Add reference" button keeps adding at the bottom.
    if payload.insert_at_index is not None and 0 <= payload.insert_at_index <= len(refs):
        refs.insert(payload.insert_at_index, new_ref)
        # Re-number every ref's `index` field so the visible numbering
        # stays contiguous after the insertion. Without this the
        # restored ref would have the next-available number but sit
        # earlier in the list, which confuses citation-number lookups.
        for i, r in enumerate(refs):
            r["index"] = i + 1
        new_ref["index"] = payload.insert_at_index + 1
    else:
        refs.append(new_ref)
    ok = await db.replace_check_references(check_id, refs, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to persist reference")
    return {"reference": new_ref, "total_refs": len(refs)}


@app.delete("/api/history/{check_id}/references/{ref_id}")
async def remove_reference_from_check(
    check_id: int,
    ref_id: str,
    current_user: UserInfo = Depends(require_user),
):
    """Remove a reference from a check (and recompute the rolled-up
    counters so the history sidebar stays in sync)."""
    user_id = get_user_id_filter(current_user)
    refs = await db.get_check_references(check_id, user_id=user_id)
    if refs is None:
        raise HTTPException(status_code=404, detail="Check not found")
    idx = _find_ref_index(refs, ref_id)
    if idx is None:
        raise HTTPException(status_code=404, detail="Reference not found in check")
    refs.pop(idx)
    ok = await db.replace_check_references(check_id, refs, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to persist removal")
    return {"removed": True, "total_refs": len(refs)}


class _VerifySingleRequest(BaseModel):
    # When true, merge ``corrected_reference`` fields into the stored ref
    # before re-verifying. The Corrections-tab "Apply fix" button hits
    # this path so the verifier runs against the FIXED metadata (and the
    # ref typically flips to verified, which moves the health badge).
    apply_correction: bool = False
    # Explicit field overrides applied BEFORE re-verification. Used by
    # the Corrections-tab "↺ Restore" button to roll a previously-
    # applied fix back to the original cited values — the FE snapshots
    # the ref before calling apply_correction and replays those fields
    # here. Keys recognised: title, authors, year, venue, doi, arxiv_id.
    overrides: Optional[Dict[str, Any]] = None


@app.get("/api/history/{check_id}/llm-usage")
async def get_llm_usage(
    check_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """Per-check LLM token + cost accumulator snapshot for the $ badge.

    Returns total tokens / cost plus a per-flow breakdown
    (extract / verify / hallucination / suggest / graph / reverify) so the
    Summary-tab badge can render a hover tooltip showing what each phase
    cost. The accumulator resets at the start of each `check_paper` call
    so the badge always reflects a single run.
    """
    # Ownership gate: load the check under the same user_id filter the
    # rest of /api/history uses, so one authenticated user can't probe
    # another user's token spend by enumerating check_ids.
    user_id = get_user_id_filter(current_user)
    refs = await db.get_check_references(check_id, user_id=user_id)
    if refs is None:
        raise HTTPException(status_code=404, detail="Check not found")

    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).parent.parent / "src"))
        from refchecker.llm import usage_tracker
        snap = usage_tracker.snapshot(str(check_id))
        return snap
    except Exception as e:
        logger.warning(f"llm-usage snapshot failed: {e}")
        return {
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "calls": 0, "by_flow": {}, "by_model": {},
        }


@app.post("/api/history/{check_id}/references/{ref_id}/verify")
async def verify_single_reference(
    check_id: int,
    ref_id: str,
    body: Optional[_VerifySingleRequest] = None,
    current_user: UserInfo = Depends(require_user),
):
    """Run the verifier on a single reference and persist the result.

    Lets the user re-verify a manually-added or edited reference without
    rerunning the whole check. We instantiate EnhancedHybridReferenceChecker
    directly (cheap — no LLM init) and replace the stored ref in-place.

    When called with ``apply_correction: true``, the stored ref's metadata
    is first overwritten with its ``corrected_reference`` (the verifier's
    own suggestion) — that way re-verifying produces the metadata the user
    just accepted, and the citation-health score moves accordingly.
    """
    user_id = get_user_id_filter(current_user)
    refs = await db.get_check_references(check_id, user_id=user_id)
    if refs is None:
        raise HTTPException(status_code=404, detail="Check not found")
    idx = _find_ref_index(refs, ref_id)
    if idx is None:
        raise HTTPException(status_code=404, detail="Reference not found in check")
    target = refs[idx]

    if body and body.apply_correction:
        corrected = target.get("corrected_reference") or {}
        if isinstance(corrected, dict) and corrected:
            for k in ("title", "authors", "year", "venue", "doi", "arxiv_id"):
                v = corrected.get(k)
                if v not in (None, "", []):
                    target[k] = v
            # Drop the cached "errors / warnings" from the previous run so
            # the badge isn't penalised by stale issues that the fix resolved.
            target["errors"] = []
            target["warnings"] = []

    # Explicit overrides path (Restore button). Replays a FE-side
    # snapshot of the original cited fields, so an "Apply fix" can be
    # reverted. Runs AFTER apply_correction so that — if both were
    # somehow set on the same call — overrides win, matching the
    # caller's intent.
    if body and isinstance(getattr(body, 'overrides', None), dict) and body.overrides:
        for k in ("title", "authors", "year", "venue", "doi", "arxiv_id"):
            if k in body.overrides:
                v = body.overrides[k]
                # Allow explicit empty / None to clear a field — the
                # snapshot may legitimately carry an empty DOI etc.
                target[k] = v
        # Reset the verify cache so the verifier runs fresh against the
        # restored metadata rather than replaying the last result.
        target["errors"] = []
        target["warnings"] = []

    # Try the global identity cache first — same shortcut the live pipeline
    # uses. If we hit, we skip the network call entirely.
    cached = None
    try:
        cached = await db.lookup_verified_reference(target)
    except Exception:
        cached = None

    def _cache_is_pre_split(cached_result: Dict[str, Any]) -> bool:
        """Entries written before the cited-vs-verified split overwrote
        cited title/authors/year/venue/doi/arxiv_id with verified values
        but never wrote any of the new ``verified_*`` siblings. Replaying
        them would reintroduce the "mixed up metadata" bug. Detect the
        old shape so we force a fresh verification instead of replaying
        a corrupted cache entry."""
        if not isinstance(cached_result, dict):
            return False
        # Newer entries always carry at least one verified_* sibling
        # when verified_data was non-empty; old entries never do.
        has_new_shape = any(
            cached_result.get(k) for k in (
                "verified_title", "verified_authors", "verified_year",
                "verified_venue", "verified_doi", "verified_arxiv_id",
            )
        )
        if has_new_shape:
            return False
        # If the entry has a status of verified/warning AND a matched_db
        # but no verified_* siblings, it's almost certainly old-shape.
        looks_verified = cached_result.get("status") in {"verified", "warning"} and bool(
            cached_result.get("matched_db") or cached_result.get("verified_url")
            or cached_result.get("authoritative_urls")
        )
        return looks_verified

    if (
        cached
        and isinstance(cached.get("result"), dict)
        and cached["result"]
        and not _cache_is_pre_split(cached["result"])
    ):
        updated = dict(cached["result"])
        updated["id"] = target.get("id")
        updated["index"] = target.get("index")
        updated["from_cache"] = True
        refs[idx] = updated
        ok = await db.replace_check_references(check_id, refs, user_id=user_id)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to persist verified reference")
        return {"reference": updated, "from_cache": True}

    # Run a fresh verification against the hybrid checker.
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker

        ss_api_key = await _resolve_semantic_scholar_api_key(None)
        checker = EnhancedHybridReferenceChecker(
            semantic_scholar_api_key=ss_api_key,
            debug_mode=False,
        )
        # Tag any LLM calls made during this single-ref re-verify so the
        # $ badge's by-flow breakdown attributes correctly.
        from refchecker.llm import usage_tracker as _usage_tracker

        def _run_verify():
            _usage_tracker.set_current_check(str(check_id))
            with _usage_tracker.FlowScope("reverify"):
                return checker.verify_reference(dict(target))

        import asyncio
        verified_data, errors, url = await asyncio.to_thread(_run_verify)
    except Exception as e:
        logger.exception("Per-ref verify failed")
        raise HTTPException(status_code=500, detail=f"Verify failed: {e}")

    # Assemble a verified result on top of the existing ref so the row
    # keeps its id/index but picks up the new status/errors/url.
    sanitized = []
    for err in (errors or []):
        e_type = err.get('error_type') or err.get('warning_type') or err.get('info_type')
        details = err.get('error_details') or err.get('warning_details') or err.get('info_details')
        if not e_type and not details:
            continue
        sanitized.append({"error_type": e_type, "error_details": details})

    has_error = any((s.get('error_type') and s.get('error_type') != 'unverified') for s in sanitized)
    if verified_data and not has_error:
        status = "verified"
    elif verified_data:
        status = "warning"
    elif sanitized:
        status = "unverified"
    else:
        status = "unverified"

    updated = dict(target)
    updated["status"] = status
    updated["errors"] = [s for s in sanitized if s.get('error_type') and s.get('error_type') != 'unverified']
    updated["warnings"] = []  # warnings come back through error_type for now
    updated["verified_url"] = url
    if verified_data:
        # Surface the canonical metadata in dedicated `verified_*` fields
        # rather than overwriting the cited title/authors/year. Mixing the
        # two on the same field (which is what the old code did) caused
        # the References tab to show inconsistent metadata: re-verified
        # rows showed the newer canonical metadata while never-re-verified
        # rows still showed the cited values, so the user saw "mixed up"
        # versions side-by-side.
        for src_key, dst_key in (
            ("title", "verified_title"),
            ("authors", "verified_authors"),
            ("year", "verified_year"),
            ("venue", "verified_venue"),
            ("doi", "verified_doi"),
            ("arxiv_id", "verified_arxiv_id"),
        ):
            if verified_data.get(src_key):
                updated[dst_key] = verified_data[src_key]
        updated["matched_db"] = verified_data.get("source") or updated.get("matched_db")
        updated["authoritative_urls"] = [{"url": url}] if url else []
        # Display-ready enrichment payload — cited-by counts, reference
        # count, Field of Study, per-author ORCID/OpenAlex IDs, etc.
        # Pulled by the References tab to render the metadata strip.
        try:
            from refchecker.utils.enrichment import build_enrichment
            enrichment = build_enrichment(verified_data)
            if enrichment:
                updated["enrichment"] = enrichment
        except Exception as e:
            logger.debug("enrichment extraction failed: %s", e)

    refs[idx] = updated
    ok = await db.replace_check_references(check_id, refs, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to persist verified reference")

    # Push the freshly-verified ref into the global identity cache so the
    # next check that touches it gets an instant hit.
    try:
        await db.upsert_verified_reference(updated)
    except Exception:
        pass

    return {"reference": updated, "from_cache": False}


@app.post("/api/history/{check_id}/references/{ref_id}/suggest-alternative")
async def suggest_alternative_reference(
    check_id: int,
    ref_id: str,
    current_user: UserInfo = Depends(require_user),
):
    """For a likely-hallucinated reference, surface real candidates the
    user might have meant. Strategy: query Semantic Scholar's title
    search with the cited title and return the top match by title
    similarity. Lightweight (no LLM round-trip) so the user can preview
    candidates before deciding to swap."""
    user_id = get_user_id_filter(current_user)
    refs = await db.get_check_references(check_id, user_id=user_id)
    if refs is None:
        raise HTTPException(status_code=404, detail="Check not found")
    idx = _find_ref_index(refs, ref_id)
    if idx is None:
        raise HTTPException(status_code=404, detail="Reference not found in check")
    target = refs[idx]
    title = (target.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Reference has no title to search on")

    import httpx
    api_key = await _resolve_semantic_scholar_api_key(None)
    headers = {"x-api-key": api_key} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": title, "limit": 5, "fields": "paperId,title,authors,year,externalIds,url"},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Lookup failed: {e}")

    suggestions = []
    for p in (data.get("data") or [])[:5]:
        ext = p.get("externalIds") or {}
        suggestions.append({
            "title": p.get("title"),
            "authors": [a.get("name") for a in (p.get("authors") or []) if a.get("name")],
            "year": p.get("year"),
            "doi": ext.get("DOI"),
            "arxiv_id": ext.get("ArXiv"),
            "url": p.get("url"),
            "paperId": p.get("paperId"),
            "source": "semantic_scholar",
        })

    # ── Crossref fallback (medical / humanities coverage) ────────────
    # S2 indexing is thin outside CS / physics. Crossref covers
    # biomedicine, anatomy, surgery far better — and exposes DOIs
    # directly, so any hit here is immediately verifiable.
    if len(suggestions) < 3:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                cr = await client.get(
                    "https://api.crossref.org/works",
                    params={
                        "query.bibliographic": title,
                        "rows": 5,
                        "select": "DOI,title,author,issued,container-title",
                    },
                )
                if cr.status_code == 200:
                    cr_data = cr.json()
                    for item in (cr_data.get("message", {}).get("items") or [])[:5]:
                        cr_title = (item.get("title") or [None])[0]
                        if not cr_title:
                            continue
                        cr_authors = []
                        for a in (item.get("author") or [])[:8]:
                            given = a.get("given") or ""
                            family = a.get("family") or ""
                            full = f"{given} {family}".strip()
                            if full:
                                cr_authors.append(full)
                        cr_year = None
                        issued = item.get("issued", {}).get("date-parts")
                        if issued and issued[0]:
                            cr_year = issued[0][0]
                        cr_doi = item.get("DOI")
                        suggestions.append({
                            "title": cr_title,
                            "authors": cr_authors,
                            "year": cr_year,
                            "doi": cr_doi,
                            "arxiv_id": None,
                            "url": f"https://doi.org/{cr_doi}" if cr_doi else None,
                            "venue": (item.get("container-title") or [None])[0],
                            "source": "crossref",
                        })
        except Exception as e:
            logger.debug("Crossref suggest-alt fallback failed: %s", e)

    # ── OpenAlex fallback (broad coverage, fast) ─────────────────────
    if len(suggestions) < 3:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                oa = await client.get(
                    "https://api.openalex.org/works",
                    params={
                        "search": title,
                        "per-page": 5,
                        "select": "id,title,doi,publication_year,authorships",
                    },
                )
                if oa.status_code == 200:
                    oa_data = oa.json()
                    for w in (oa_data.get("results") or [])[:5]:
                        w_title = w.get("title")
                        if not w_title:
                            continue
                        suggestions.append({
                            "title": w_title,
                            "authors": [
                                a.get("author", {}).get("display_name")
                                for a in (w.get("authorships") or [])
                                if a.get("author", {}).get("display_name")
                            ],
                            "year": w.get("publication_year"),
                            "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                            "arxiv_id": None,
                            "url": w.get("id"),
                            "source": "openalex",
                        })
        except Exception as e:
            logger.debug("OpenAlex suggest-alt fallback failed: %s", e)

    # Dedupe by DOI / title — Crossref and OpenAlex often return the same paper.
    _seen_keys = set()
    _deduped = []
    for s in suggestions:
        key = (s.get("doi") or "").lower() or (s.get("title") or "").strip().lower()[:80]
        if key in _seen_keys:
            continue
        _seen_keys.add(key)
        _deduped.append(s)
    suggestions = _deduped[:8]

    # ── Co-citation overlap pass ─────────────────────────────────────
    # For each title-search hit, ask Semantic Scholar for its reference
    # list and count how many entries match other references in the
    # current paper's bibliography (by paperId, when known). The candidate
    # that shares the most refs with the rest of the bibliography is
    # almost always the paper the author actually meant — this is the
    # signal the user described as "algorithms of overlap".
    import re as _re_overlap
    try:
        # Build a paperId set for the rest of the bibliography
        other_pids: set = set()
        for r in refs:
            if r is target:
                continue
            for url_obj in (r.get("authoritative_urls") or []):
                u = url_obj.get("url") or ""
                m = _re_overlap.search(r"semanticscholar\.org/paper/([0-9a-f]+)", u, _re_overlap.IGNORECASE)
                if m:
                    other_pids.add(m.group(1).lower())
        if other_pids and suggestions:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for cand in suggestions:
                    pid = cand.get("paperId")
                    if not pid:
                        cand["overlap"] = 0
                        continue
                    try:
                        rr = await client.get(
                            f"https://api.semanticscholar.org/graph/v1/paper/{pid}/references",
                            params={"fields": "citedPaper.paperId", "limit": 100},
                            headers=headers,
                        )
                        if rr.status_code != 200:
                            cand["overlap"] = 0
                            continue
                        rd = rr.json()
                        cited_ids = {
                            (entry.get("citedPaper", {}) or {}).get("paperId", "").lower()
                            for entry in (rd.get("data") or [])
                        }
                        cand["overlap"] = len(cited_ids & other_pids)
                    except Exception:
                        cand["overlap"] = 0
            # Re-rank: candidates with bibliography overlap float to the top.
            suggestions.sort(key=lambda c: c.get("overlap", 0), reverse=True)
            # Mark the overlap winner so the UI can label it
            if suggestions and suggestions[0].get("overlap", 0) > 0:
                suggestions[0]["overlap_winner"] = True
    except Exception as e:
        logger.debug("Suggest-alt overlap pass skipped: %s", e)

    # LLM augmentation: ask the user's configured default LLM what real
    # paper the cited reference probably is. Often it can resolve cases
    # where S2 title-search misses (e.g. mangled author lists, wrong
    # year, hallucinated venue).
    llm_candidates = []
    try:
        default_cfg = await db.get_default_llm_config(user_id=user_id)
        if default_cfg and default_cfg.get("provider"):
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
            from refchecker.llm.base import create_llm_provider

            llm_config = {}
            if default_cfg.get("model"):
                llm_config["model"] = default_cfg["model"]
            if default_cfg.get("api_key"):
                llm_config["api_key"] = default_cfg["api_key"]
            if default_cfg.get("endpoint"):
                llm_config["endpoint"] = default_cfg["endpoint"]
            provider = create_llm_provider(default_cfg["provider"], llm_config)
            if provider and (not hasattr(provider, "is_available") or provider.is_available()):
                authors = target.get("authors")
                if isinstance(authors, list):
                    authors_str = ", ".join(str(a) for a in authors[:10])
                else:
                    authors_str = str(authors or "")
                prompt = (
                    "You are helping resolve a likely-hallucinated academic citation.\n"
                    "Given the (possibly wrong) reference below, identify up to 3 REAL "
                    "papers the author probably meant. For each, return strict JSON "
                    "with fields: title, authors (array of strings), year (int), "
                    "venue, doi (or null), arxiv_id (or null), reason (one short "
                    "sentence on why this is the likely match).\n\n"
                    f"Title: {title}\n"
                    f"Authors: {authors_str}\n"
                    f"Year: {target.get('year') or 'unknown'}\n"
                    f"Venue: {target.get('venue') or 'unknown'}\n\n"
                    "Respond with ONLY a JSON array of objects, no prose, no markdown."
                )
                try:
                    raw = provider._call_llm(prompt)
                except Exception as e:
                    logger.debug("LLM suggest-alt call failed: %s", e)
                    raw = None
                if raw:
                    import json as _json, re as _re
                    text = raw.strip()
                    # Strip code fences if present
                    m = _re.search(r"\[.*\]", text, _re.DOTALL)
                    if m:
                        text = m.group(0)
                    try:
                        parsed = _json.loads(text)
                        if isinstance(parsed, list):
                            for item in parsed[:3]:
                                if not isinstance(item, dict):
                                    continue
                                t = item.get("title")
                                if not t:
                                    continue
                                doi_v = item.get("doi")
                                arxiv_v = item.get("arxiv_id")
                                url_v = None
                                if doi_v:
                                    url_v = f"https://doi.org/{doi_v}"
                                elif arxiv_v:
                                    url_v = f"https://arxiv.org/abs/{arxiv_v}"
                                llm_candidates.append({
                                    "title": t,
                                    "authors": item.get("authors") or [],
                                    "year": item.get("year"),
                                    "venue": item.get("venue"),
                                    "doi": doi_v,
                                    "arxiv_id": arxiv_v,
                                    "url": url_v,
                                    "reason": item.get("reason"),
                                    "source": "llm",
                                })
                    except Exception as e:
                        logger.debug("Failed to parse LLM suggest-alt output: %s", e)
    except Exception as e:
        logger.debug("LLM suggest-alt augmentation skipped: %s", e)

    # Put LLM candidates first when present (they typically explain themselves
    # with `reason`), then fall back to S2 title-search matches.
    return {
        "reference_id": ref_id,
        "cited_title": title,
        "candidates": llm_candidates + suggestions,
    }


class _SimilarPapersRequest(BaseModel):
    references: list  # list of {title, doi?, arxiv_id?, authors?}
    paper_title: Optional[str] = None
    paper_id: Optional[str] = None  # arXiv ID or DOI of the SOURCE paper
    limit: int = 5


def _candidate_key(title: Optional[str], doi: Optional[str], arxiv: Optional[str]) -> str:
    """Build a dedup key across S2/OpenAlex/web/LLM source variation."""
    if doi:
        return f"doi:{doi.strip().lower()}"
    if arxiv:
        return f"arxiv:{arxiv.strip().lower()}"
    if title:
        import re as _re
        norm = _re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
        return f"title:{norm}"
    return f"ghost:{id(title)}"


@app.post("/api/papers/similar")
async def find_similar_papers(req: _SimilarPapersRequest, current_user: UserInfo = Depends(require_user)):
    """Surface up to N papers similar to the current one across four
    sources, then actively verify the survivors so each candidate row
    arrives with a known real/fake status, not just metadata.

    Sources, in order:

      1. **Semantic Scholar** — recommendations endpoint when a paperId
         is known, plus a co-citation tally over the user's references
         (papers that cite many of the same refs).
      2. **OpenAlex** — for each user ref with a DOI we can resolve to
         an OpenAlex Work, query Works that *cite* it; tally overlap
         the same way (true co-citation, OpenAlex side).
      3. **Web search** — runs the user's configured web-search
         provider (OpenAI / Anthropic / Gemini) on the paper title
         plus "related papers"; cited URLs become candidates.
      4. **LLM** — asks the default LLM "given these references,
         suggest 5 papers that build on or sit alongside this work."

    After dedup (by DOI / arXiv / normalized title), each candidate is
    cross-checked against the global identity cache. Cache misses are
    actively verified through the hybrid checker (capped at 5 in
    parallel) so the UI can show a real verification status, not just
    'unknown'.
    """
    try:
        return await _find_similar_papers_impl(req, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("find_similar_papers crashed")
        return {
            "source_paper": req.paper_title,
            "candidates": [],
            "error": f"Similar Papers lookup failed: {e}",
        }


async def _find_similar_papers_impl(req: _SimilarPapersRequest, current_user: UserInfo):
    user_id = get_user_id_filter(current_user)
    refs = req.references or []
    if not refs:
        raise HTTPException(status_code=400, detail="`references` must be a non-empty list")

    import httpx
    import asyncio
    api_key = await _resolve_semantic_scholar_api_key(None)
    headers = {"x-api-key": api_key} if api_key else {}
    timeout = 10.0
    limit = max(1, min(20, int(req.limit or 5)))

    def s2_id_of(ref: dict) -> Optional[str]:
        if ref.get("doi"):
            return f"DOI:{ref['doi']}"
        if ref.get("arxiv_id"):
            return f"arXiv:{ref['arxiv_id']}"
        return None

    tally: Dict[str, Dict[str, Any]] = {}

    def _merge(cand: Dict[str, Any], source: str, shared: int = 0):
        key = _candidate_key(cand.get("title"), cand.get("doi"), cand.get("arxiv_id"))
        if key in tally:
            entry = tally[key]
            entry["shared"] += shared
            if source not in entry["sources"]:
                entry["sources"].append(source)
            # Backfill missing fields
            for k in ("doi", "arxiv_id", "year", "paperId", "url", "venue", "openalex_id"):
                if not entry["paper"].get(k) and cand.get(k):
                    entry["paper"][k] = cand[k]
            if not entry["paper"].get("authors") and cand.get("authors"):
                entry["paper"]["authors"] = cand["authors"]
        else:
            tally[key] = {"paper": dict(cand), "shared": shared, "sources": [source]}

    async def _fetch(client: httpx.AsyncClient, url: str, params: Optional[dict] = None, hdrs: Optional[dict] = None) -> Optional[dict]:
        try:
            r = await client.get(url, params=params, headers=hdrs if hdrs is not None else headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.debug("Fetch failed for %s: %s", url, e)
        return None

    try:
      async with httpx.AsyncClient() as client:
        # ── Source 1: Semantic Scholar ──────────────────────────────
        # If we don't have a paper_id but do have a title, resolve via
        # S2 /paper/search so the /recommendations endpoint still fires.
        # Without this, title-only inputs fell straight through to the
        # garbage-producing web-search source (paper.docx, twitter
        # handles, conference camera-ready pages).
        resolved_paper_id = req.paper_id
        if not resolved_paper_id and req.paper_title:
            try:
                search = await _fetch(
                    client,
                    "https://api.semanticscholar.org/graph/v1/paper/search/match",
                    params={"query": req.paper_title, "fields": "paperId,title"},
                )
                if search and (data := search.get("data")):
                    if isinstance(data, list) and data and data[0].get("paperId"):
                        resolved_paper_id = data[0]["paperId"]
            except Exception as e:
                logger.debug("S2 title->paperId resolve failed: %s", e)

        if resolved_paper_id:
            data = await _fetch(
                client,
                f"https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{resolved_paper_id}",
                params={"fields": "paperId,title,authors,year,externalIds", "limit": 20},
            )
            for p in (data or {}).get("recommendedPapers", []) or []:
                ext = p.get("externalIds") or {}
                _merge({
                    "title": p.get("title"),
                    "year": p.get("year"),
                    "authors": [a.get("name") for a in (p.get("authors") or []) if a.get("name")],
                    "doi": ext.get("DOI"),
                    "arxiv_id": ext.get("ArXiv"),
                    "paperId": p.get("paperId"),
                    "url": f"https://www.semanticscholar.org/paper/{p.get('paperId')}" if p.get("paperId") else None,
                }, "semantic_scholar")

        for ref in refs[:30]:
            ident = s2_id_of(ref)
            if not ident:
                continue
            data = await _fetch(
                client,
                f"https://api.semanticscholar.org/graph/v1/paper/{ident}/citations",
                params={"fields": "citingPaper.paperId,citingPaper.title,citingPaper.year,citingPaper.authors,citingPaper.externalIds", "limit": 30},
            )
            for item in (data or {}).get("data", []) or []:
                cp = item.get("citingPaper") or {}
                ext = cp.get("externalIds") or {}
                if not cp.get("paperId"):
                    continue
                _merge({
                    "title": cp.get("title"),
                    "year": cp.get("year"),
                    "authors": [a.get("name") for a in (cp.get("authors") or []) if a.get("name")],
                    "doi": ext.get("DOI"),
                    "arxiv_id": ext.get("ArXiv"),
                    "paperId": cp.get("paperId"),
                    "url": f"https://www.semanticscholar.org/paper/{cp.get('paperId')}",
                }, "semantic_scholar", shared=1)

        # ── Source 2: OpenAlex ──────────────────────────────────────
        # Resolve user refs with DOIs to OpenAlex Work IDs, then ask
        # OpenAlex for Works that cite each of them. Co-citation overlap
        # is the same signal we use for S2.
        try:
            openalex_ids = []
            for ref in refs[:20]:
                doi = ref.get("doi")
                if not doi:
                    continue
                doi_clean = doi.strip().lstrip("doi:").strip("/")
                wdata = await _fetch(
                    client,
                    f"https://api.openalex.org/works/doi:{doi_clean}",
                    params={"select": "id"},
                    hdrs={},
                )
                if wdata and wdata.get("id"):
                    openalex_ids.append(wdata["id"].rsplit("/", 1)[-1])

            for oa_id in openalex_ids[:15]:
                # Works that cite this ref
                citing = await _fetch(
                    client,
                    "https://api.openalex.org/works",
                    params={"filter": f"cites:{oa_id}", "per-page": 20, "select": "id,title,doi,publication_year,authorships,ids"},
                    hdrs={},
                )
                for w in (citing or {}).get("results", []) or []:
                    doi_v = (w.get("doi") or "").replace("https://doi.org/", "") or None
                    ids = w.get("ids") or {}
                    _merge({
                        "title": w.get("title"),
                        "year": w.get("publication_year"),
                        "authors": [a.get("author", {}).get("display_name") for a in (w.get("authorships") or []) if a.get("author", {}).get("display_name")],
                        "doi": doi_v,
                        "arxiv_id": None,
                        "openalex_id": (w.get("id") or "").rsplit("/", 1)[-1] or None,
                        "url": w.get("id"),
                    }, "openalex", shared=1)
        except Exception as e:
            logger.debug("OpenAlex similar-papers source failed: %s", e)
    except Exception as e:
        logger.debug("S2/OpenAlex similar-papers block failed: %s", e)

    # Web-search source removed — it produced noise (paper.docx
    # templates, conference camera-ready instructions, twitter handles)
    # because LLM web search treats "papers related to X" as generic
    # text queries, not paper retrieval. S2 + OpenAlex + LLM-suggested-
    # from-bibliography give signal; web search just contaminated the
    # tally.

    # ── Source 3: LLM ───────────────────────────────────────────────
    try:
        default_cfg = await db.get_default_llm_config(user_id=user_id)
        if default_cfg and default_cfg.get("provider"):
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
            from refchecker.llm.base import create_llm_provider

            llm_config = {}
            if default_cfg.get("model"):
                llm_config["model"] = default_cfg["model"]
            if default_cfg.get("api_key"):
                llm_config["api_key"] = default_cfg["api_key"]
            if default_cfg.get("endpoint"):
                llm_config["endpoint"] = default_cfg["endpoint"]
            provider = create_llm_provider(default_cfg["provider"], llm_config)
            if provider and (not hasattr(provider, "is_available") or provider.is_available()):
                # Prime with up to 15 bibliography rows so the LLM can
                # actually pick up the subject area. Earlier 10-row cap
                # was too thin for narrow-topic case reports (the LLM
                # would default to broad methodology papers like PRISMA).
                top_refs = []
                for r in refs[:15]:
                    bits = [r.get("title"), str(r.get("year") or "")]
                    a = r.get("authors")
                    if isinstance(a, list):
                        bits.append(", ".join(a[:3]))
                    top_refs.append(" — ".join(b for b in bits if b))
                # Tighter prompt: explicitly demand topic specificity and
                # forbid methodology / reporting-guideline references that
                # apply to any paper in the field. Asks the LLM to think
                # about what the input paper is actually ABOUT (from its
                # title + bibliography) and pull papers that overlap on
                # the specific subject matter.
                prompt = (
                    f"Source paper title: {req.paper_title or '(unknown)'}\n\n"
                    "Its bibliography includes:\n"
                    + "\n".join(f"- {t}" for t in top_refs)
                    + "\n\nIdentify what specific topic this paper is about (read the "
                      "title + bibliography), then suggest up to 5 OTHER real academic "
                      "papers that are NARROWLY on that same specific topic.\n\n"
                      "STRICT RULES:\n"
                      "1. Do NOT suggest methodology papers (PRISMA, CARE guidelines, "
                      "STROBE, CONSORT, etc.) — those apply to every paper in a field "
                      "and are not topic-similar.\n"
                      "2. Do NOT suggest generic reviews unless the source paper IS itself "
                      "a generic review on the same topic.\n"
                      "3. Prefer papers that likely share specific references with the "
                      "input (clinical case series of the same condition, the seminal "
                      "papers the input cites, follow-up studies extending the input's "
                      "findings).\n"
                      "4. Each suggestion must include a DOI when one exists — papers "
                      "without DOIs are usually too obscure to be useful.\n\n"
                      "Return strict JSON array of objects with: title, authors (array), "
                      "year (int), venue, doi (or null), arxiv_id (or null), reason "
                      "(one specific sentence on why this paper is topically narrow). "
                      "Respond with ONLY the JSON array, no prose or markdown."
                )
                # Tag this LLM call as the `suggest` flow so the $ badge's
                # per-flow breakdown attributes the cost to the Similar
                # Papers tab rather than dumping it into "other". The
                # FlowScope's thread-local doesn't cross asyncio.to_thread,
                # so we set it INSIDE the worker function — same pattern
                # as the re-verify path uses.
                def _run_llm_similar():
                    try:
                        from refchecker.llm import usage_tracker as _ut
                        with _ut.FlowScope("suggest"):
                            return provider._call_llm(prompt)
                    except Exception:
                        # Fall back to unflagged call if usage_tracker is unavailable.
                        return provider._call_llm(prompt)
                try:
                    raw = await asyncio.to_thread(_run_llm_similar)
                except Exception as e:
                    logger.debug("LLM similar-papers call failed: %s", e)
                    raw = None
                if raw:
                    import json as _json
                    import re as _re
                    text = raw.strip()
                    m = _re.search(r"\[.*\]", text, _re.DOTALL)
                    if m:
                        text = m.group(0)
                    try:
                        parsed = _json.loads(text)
                        if isinstance(parsed, list):
                            # Reporting-guideline / methodology titles
                            # that LLMs love to suggest regardless of the
                            # actual paper topic. These match any clinical
                            # paper but don't share specific references
                            # with it. Filter aggressively.
                            _GENERIC_TITLE_TOKENS = (
                                'prisma', 'preferred reporting items',
                                'care guidelines', 'care checklist',
                                'consort statement', 'strobe statement',
                                'consort 2010', 'spirit 2013', 'tripod',
                                'reporting guidelines for',
                                'systematic review of systematic reviews',
                            )
                            for item in parsed[:5]:
                                if not isinstance(item, dict) or not item.get("title"):
                                    continue
                                title_lc = item["title"].lower()
                                if any(tok in title_lc for tok in _GENERIC_TITLE_TOKENS):
                                    logger.debug("LLM similar-papers: skipping generic methodology title %r", item["title"])
                                    continue
                                doi_v = item.get("doi")
                                arxiv_v = item.get("arxiv_id")
                                url_v = None
                                if doi_v:
                                    url_v = f"https://doi.org/{doi_v}"
                                elif arxiv_v:
                                    url_v = f"https://arxiv.org/abs/{arxiv_v}"
                                _merge({
                                    "title": item.get("title"),
                                    "authors": item.get("authors") or [],
                                    "year": item.get("year"),
                                    "venue": item.get("venue"),
                                    "doi": doi_v,
                                    "arxiv_id": arxiv_v,
                                    "url": url_v,
                                    "reason": item.get("reason"),
                                }, "llm", shared=0)
                    except Exception as e:
                        logger.debug("Failed to parse LLM similar-papers output: %s", e)
    except Exception as e:
        logger.debug("LLM similar-papers source skipped: %s", e)

    # ── Rank: shared first, multi-source as tiebreak, then llm/web ──
    # Pre-rank by co-citation count so we have a candidate pool, but the
    # FINAL rank is driven by reference-overlap below (the user's actual
    # spec: "papers that share 90% same references with the input"). We
    # take 3x `limit` from the pool so reference-overlap can re-rank
    # before we cut to the user-visible limit.
    pool_size = max(limit * 3, 15)
    ranked = sorted(
        tally.values(),
        key=lambda v: (v["shared"], len(v["sources"]), "semantic_scholar" in v["sources"], "openalex" in v["sources"]),
        reverse=True,
    )[:pool_size]

    # ── Reference-overlap rescoring (this is the user's primary signal) ─
    # For every candidate, pull its own reference list from S2 and compute
    # what fraction of the *input* paper's references also appear in the
    # candidate's bibliography. A candidate that cites 18 of the input's 20
    # references is far more similar to the input than one that just shares
    # a single co-citation. Identity uses DOI -> arXiv -> normalized title.
    def _ref_identity(r: dict) -> Optional[str]:
        if not isinstance(r, dict):
            return None
        doi = (r.get("doi") or "").strip().lower()
        if doi:
            return f"doi:{doi}"
        aid = (r.get("arxiv_id") or "").strip().lower()
        if aid:
            # Strip version suffix so v1/v2 collapse to one identity.
            import re as _re
            aid = _re.sub(r"v\d+$", "", aid)
            return f"arxiv:{aid}"
        title = (r.get("title") or "").strip().lower()
        # Normalise to alphanumerics + spaces so trivial punctuation
        # differences don't break the match.
        import re as _re
        title = _re.sub(r"[^a-z0-9]+", " ", title).strip()
        year = r.get("year")
        # NB: threshold here is intentionally looser (12) than the Seen
        # Refs identity key (30 + 3 tokens). This identity is used only
        # within a single Similar-Papers request to count shared refs
        # between two papers — a loose match slightly inflates one
        # candidate's overlap score but doesn't poison a persistent
        # cache. A stricter threshold would miss real overlaps where one
        # side has the year and the other doesn't.
        if title and len(title) >= 12:
            return f"title:{title}:{year}" if year else f"title:{title}:_"
        return None

    input_idset = {k for k in (_ref_identity(r) for r in refs) if k}
    input_idcount = max(1, len(input_idset))

    async def _candidate_refs(client: httpx.AsyncClient, entry: dict) -> set:
        p = entry["paper"]
        # Need an S2 paperId or external id to ask S2 for references.
        ident = None
        if p.get("paperId"):
            ident = p["paperId"]
        elif p.get("doi"):
            ident = f"DOI:{p['doi']}"
        elif p.get("arxiv_id"):
            ident = f"arXiv:{p['arxiv_id']}"
        if not ident:
            return set()
        data = await _fetch(
            client,
            f"https://api.semanticscholar.org/graph/v1/paper/{ident}/references",
            params={
                "fields": "citedPaper.paperId,citedPaper.title,citedPaper.year,citedPaper.externalIds",
                "limit": 200,
            },
        )
        out: set = set()
        for item in (data or {}).get("data", []) or []:
            cp = item.get("citedPaper") or {}
            ext = cp.get("externalIds") or {}
            ref_shape = {
                "title": cp.get("title"),
                "year": cp.get("year"),
                "doi": ext.get("DOI"),
                "arxiv_id": ext.get("ArXiv"),
            }
            ident_key = _ref_identity(ref_shape)
            if ident_key:
                out.add(ident_key)
        return out

    try:
        import httpx as _httpx
        async with _httpx.AsyncClient() as _client:
            overlap_sem = asyncio.Semaphore(6)

            # Build identity→title map from the input refs so we can
            # surface WHICH refs each candidate shares, not just the
            # count. The FE renders these as a "Shared refs:" list.
            input_id_to_title = {}
            for r in refs:
                k = _ref_identity(r)
                if k:
                    t = (r.get("title") or "").strip()
                    if t:
                        input_id_to_title[k] = t[:160]

            async def _score(entry):
                async with overlap_sem:
                    cand_set = await _candidate_refs(_client, entry)
                shared_refs = input_idset & cand_set
                entry["shared_refs_count"] = len(shared_refs)
                entry["shared_refs_pct"] = len(shared_refs) / input_idcount
                union = input_idset | cand_set
                entry["shared_refs_jaccard"] = (
                    len(shared_refs) / max(1, len(union)) if union else 0.0
                )
                entry["candidate_ref_count"] = len(cand_set)
                # Up to 10 shared-ref titles for the FE expandable list.
                entry["shared_refs_titles"] = [
                    input_id_to_title[k] for k in list(shared_refs)[:10]
                    if k in input_id_to_title
                ]

            await asyncio.gather(*[_score(e) for e in ranked])
    except Exception as e:
        logger.debug("Reference-overlap rescoring failed: %s", e)
        for entry in ranked:
            entry.setdefault("shared_refs_count", 0)
            entry.setdefault("shared_refs_pct", 0.0)
            entry.setdefault("shared_refs_jaccard", 0.0)
            entry.setdefault("candidate_ref_count", 0)

    # Re-rank by overlap percentage, then count, then co-citation tiebreak.
    ranked.sort(
        key=lambda v: (
            v.get("shared_refs_pct", 0.0),
            v.get("shared_refs_count", 0),
            v.get("shared", 0),
            len(v.get("sources", [])),
        ),
        reverse=True,
    )
    ranked = ranked[:limit]

    # ── Active verification of cache-miss candidates ────────────────
    # Cap to `limit` candidates and verify in parallel (sem limits concurrency).
    out: list = []
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
        checker = EnhancedHybridReferenceChecker(
            semantic_scholar_api_key=api_key,
            debug_mode=False,
        )
    except Exception as e:
        logger.debug("Could not init checker for similar-papers verification: %s", e)
        checker = None

    sem = asyncio.Semaphore(4)

    async def _enrich(entry):
        p = entry["paper"]
        probe = {
            "doi": p.get("doi"),
            "arxiv_id": p.get("arxiv_id"),
            "title": p.get("title"),
            "year": p.get("year"),
        }
        cached = None
        try:
            cached = await db.lookup_verified_reference(probe)
        except Exception:
            cached = None

        verification_status = (cached or {}).get("status") if cached else None
        pre_verified = bool(cached)
        was_verified = pre_verified

        # Cache miss: actively verify if we have any identifier or title
        if not pre_verified and checker is not None and (p.get("doi") or p.get("arxiv_id") or p.get("title")):
            async with sem:
                try:
                    verified_data, errors, url = await asyncio.to_thread(
                        checker.verify_reference,
                        {
                            "title": p.get("title"),
                            "authors": p.get("authors"),
                            "year": p.get("year"),
                            "doi": p.get("doi"),
                            "arxiv_id": p.get("arxiv_id"),
                            "venue": p.get("venue"),
                        },
                    )
                    if verified_data:
                        verification_status = "verified"
                        was_verified = True
                        # Backfill identifiers we may have missed
                        if not p.get("doi") and verified_data.get("doi"):
                            p["doi"] = verified_data["doi"]
                        if not p.get("arxiv_id") and verified_data.get("arxiv_id"):
                            p["arxiv_id"] = verified_data["arxiv_id"]
                        if not p.get("url") and url:
                            p["url"] = url
                        # Persist to global cache so the next request is instant
                        try:
                            await db.upsert_verified_reference({
                                **p,
                                "status": "verified",
                                "verified_url": url,
                                "matched_db": (verified_data.get("source") if isinstance(verified_data, dict) else None),
                            })
                        except Exception:
                            pass
                    else:
                        # No data found — likely fake or just missing
                        verification_status = "unverified"
                except Exception as e:
                    logger.debug("Active verification failed for candidate: %s", e)
                    verification_status = "unknown"

        out.append({
            "paperId": p.get("paperId"),
            "openalex_id": p.get("openalex_id"),
            "title": p.get("title"),
            "year": p.get("year"),
            "authors": p.get("authors") or [],
            "doi": p.get("doi"),
            "arxiv_id": p.get("arxiv_id"),
            "venue": p.get("venue"),
            "reason": p.get("reason"),
            "shared_with_source": entry["shared"],
            # NEW: actual reference-overlap signal — the % of the input
            # paper's references that the candidate also cites. Drives
            # the "share 90% same references" experience the user asked
            # for (#4 on the roadmap).
            "shared_refs_count": entry.get("shared_refs_count", 0),
            "shared_refs_pct": entry.get("shared_refs_pct", 0.0),
            "shared_refs_jaccard": entry.get("shared_refs_jaccard", 0.0),
            "candidate_ref_count": entry.get("candidate_ref_count", 0),
            # Up to 10 shared-ref titles so the FE can expand "which refs
            # exactly are shared" on click. Computed during reference-
            # overlap rescoring; empty list when overlap was 0 / scoring
            # skipped (no DOI on the input refs, S2 unreachable, etc.).
            "shared_refs_titles": entry.get("shared_refs_titles") or [],
            "sources": entry["sources"],
            "via": entry["sources"][0] if entry["sources"] else None,
            "semantic_scholar_url": f"https://www.semanticscholar.org/paper/{p.get('paperId')}" if p.get("paperId") else None,
            "url": p.get("url"),
            "pre_verified": pre_verified,
            "was_verified": was_verified,
            "verified_status": verification_status,
            "times_seen": (cached or {}).get("times_seen") if cached else 0,
        })

    # Run enrichment in parallel — sem caps concurrent verifications
    await asyncio.gather(*[_enrich(e) for e in ranked])

    # Trust filter. A candidate is trustworthy when at least one of:
    #   - the active verifier matched it (was_verified)
    #   - multiple independent sources surfaced it (S2 + OpenAlex / etc.)
    #   - it shares at least 2 references with the input paper
    # LLM-only candidates that failed active verification AND share no
    # refs are filtered out — those are the "hallucinated suggestion +
    # fake DOI" case the user hit ("none are similar, some are
    # hallucinations, wrong links"). The previous policy of "always
    # show something" turned the tab into a noise generator on inputs
    # where nothing could be cross-verified.
    def _trustworthy(o):
        if o.get("was_verified"):
            return True
        sources = o.get("sources") or []
        if len(sources) >= 2:
            return True
        if o.get("shared_refs_count", 0) >= 2:
            return True
        # LLM-only, unverified, zero ref overlap → drop.
        if sources == ["llm"]:
            return False
        # Lone non-LLM source with no overlap is still suspect but
        # historically benign (S2 recommendation, OpenAlex similar) —
        # keep but mark unverified so the FE can render a chip.
        return True

    pre_filter = list(out)
    final = [o for o in pre_filter if _trustworthy(o)]
    dropped_hallucinations = len(pre_filter) - len(final)
    if dropped_hallucinations:
        logger.info(
            "similar-papers: filtered %d untrustworthy LLM-only candidate(s) "
            "(no verification + no ref overlap)",
            dropped_hallucinations,
        )
    final.sort(
        key=lambda o: (
            o.get("shared_refs_pct", 0.0),
            o.get("shared_refs_count", 0),
            1 if o["was_verified"] else 0,
            o["shared_with_source"] or 0,
            len(o["sources"]),
        ),
        reverse=True,
    )
    # Tell the UI which sources actually produced anything, so the user
    # can spot a misconfigured key instead of an empty mystery list.
    source_counts: Dict[str, int] = {}
    for o in out:
        for s in (o.get("sources") or []):
            source_counts[s] = source_counts.get(s, 0) + 1
    return {
        "source_paper": req.paper_title,
        "candidates": final[:limit],
        "source_counts": source_counts,
        "total_candidates": len(out),
        "dropped_untrustworthy": dropped_hallucinations,
    }


class _CitationGraphRequest(BaseModel):
    references: list  # list of {id?, title, doi?, arxiv_id?, authors?}
    paper_title: Optional[str] = None


@app.post("/api/papers/citation-graph")
async def citation_graph(req: _CitationGraphRequest, current_user: UserInfo = Depends(require_user)):
    """Real citation-graph edges between the references the user gave us.

    For each ref with a DOI / arXiv ID, look it up on Semantic Scholar's
    graph API to get (a) its citationCount (used for node size) and
    (b) the paperIds it cites itself. Then an edge ``A -> B`` exists
    iff A's reference list contains B's paperId. That gives genuine
    inter-citation structure inside the bibliography, instead of the
    author-overlap proxy.

    Returns ``{nodes: [{id, paperId, citationCount}], edges: [{source, target}]}``.
    """
    refs = req.references or []
    if not refs:
        return {"nodes": [], "edges": []}

    import httpx
    api_key = await _resolve_semantic_scholar_api_key(None)
    headers = {"x-api-key": api_key} if api_key else {}
    timeout = 10.0

    def s2_id_of(ref: dict) -> Optional[str]:
        if ref.get("doi"):
            return f"DOI:{ref['doi']}"
        if ref.get("arxiv_id"):
            return f"arXiv:{ref['arxiv_id']}"
        return None

    async def _fetch(client, url, params=None):
        try:
            r = await client.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.debug("S2 fetch failed for %s: %s", url, e)
        return None

    # Cap at 60 — beyond that S2 rate-limits hard and the graph is unreadable.
    refs = refs[:60]
    nodes_out = []
    paperid_to_local = {}  # S2 paperId -> our local ref id

    async with httpx.AsyncClient() as client:
        # Fetch each ref's citationCount + outgoing references list. We do
        # this sequentially to be polite to the free-tier rate limit.
        ref_details = []
        for i, ref in enumerate(refs):
            local_id = str(ref.get("id") or ref.get("index") or f"ref-{i}")
            ident = s2_id_of(ref)
            paper = None
            references_list = []
            if ident:
                data = await _fetch(
                    client,
                    f"https://api.semanticscholar.org/graph/v1/paper/{ident}",
                    params={"fields": "paperId,citationCount,references.paperId"},
                )
                if data:
                    paper = data
                    references_list = [r.get("paperId") for r in (data.get("references") or []) if r.get("paperId")]
            pid = (paper or {}).get("paperId")
            citation_count = (paper or {}).get("citationCount") or 0
            ref_details.append({
                "local_id": local_id,
                "paperId": pid,
                "citationCount": citation_count,
                "references": references_list,
            })
            if pid:
                paperid_to_local[pid] = local_id
            nodes_out.append({
                "id": local_id,
                "paperId": pid,
                "citationCount": citation_count,
            })

        edges = []
        seen_edges = set()
        for det in ref_details:
            src = det["local_id"]
            for tgt_pid in det["references"]:
                tgt = paperid_to_local.get(tgt_pid)
                if not tgt or tgt == src:
                    continue
                key = f"{src}->{tgt}"
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edges.append({"source": src, "target": tgt})

    return {"nodes": nodes_out, "edges": edges}


class _ExpandRequest(BaseModel):
    paper_id: str  # S2 paperId or "DOI:..." / "arXiv:..." identifier
    limit: int = 8
    # Optional title fallback — when /paper/<paper_id>/references returns
    # an empty list (S2 sometimes has the paper but not its reference
    # graph, particularly for niche / older publications), we search S2
    # by title to resolve the canonical paperId and retry. Without this
    # the graph view shows lots of central refs with no spokes.
    title: Optional[str] = None


@app.post("/api/papers/expand")
async def expand_paper(req: _ExpandRequest, current_user: UserInfo = Depends(require_user)):
    """One-hop expansion for the graph view: list a paper's most-cited
    outgoing references so the user can pull them into the graph."""
    import httpx
    api_key = await _resolve_semantic_scholar_api_key(None)
    headers = {"x-api-key": api_key} if api_key else {}
    timeout = 12.0
    limit = max(1, min(25, int(req.limit or 8)))
    pid = req.paper_id
    if not pid:
        raise HTTPException(status_code=400, detail="paper_id required")

    # Retry with exponential backoff on 429s. Even with the per-key
    # quota, bursts from the graph 2nd-degree expansion (six parallel
    # workers × dozens of refs) easily exceed S2's per-IP rate limit
    # and surface as HTTP 429. Sleeping between retries — plus
    # respecting the Retry-After header when S2 sets it — recovers
    # gracefully without bubbling the error all the way to the FE.
    import asyncio as _asyncio

    async def _fetch_references(client, identifier):
        """Single attempt at /paper/<identifier>/references with the
        existing 429 retry policy. Returns (data, err)."""
        local_err = None
        for attempt in range(3):
            try:
                r = await client.get(
                    f"https://api.semanticscholar.org/graph/v1/paper/{identifier}/references",
                    params={
                        "fields": "citedPaper.paperId,citedPaper.title,citedPaper.year,citedPaper.authors,citedPaper.externalIds,citedPaper.citationCount",
                        "limit": min(50, limit * 4),
                    },
                    headers=headers,
                    timeout=timeout,
                )
                if r.status_code == 429:
                    try:
                        wait_s = float(r.headers.get('Retry-After', '2.0'))
                    except Exception:
                        wait_s = 2.0
                    wait_s = min(8.0, max(0.5, wait_s)) * (2 ** attempt)
                    await _asyncio.sleep(wait_s)
                    local_err = "rate-limited (429) — retrying"
                    continue
                if r.status_code == 404:
                    # Paper not indexed under this identifier — bail so
                    # the caller can fall back to title search.
                    return None, "404"
                r.raise_for_status()
                return r.json(), None
            except HTTPException:
                raise
            except Exception as e:
                local_err = str(e)
                await _asyncio.sleep(0.5 * (2 ** attempt))
        return None, local_err

    data = None
    async with httpx.AsyncClient() as client:
        last_err = None
        # Inline the legacy retry loop's variable so the fallback path
        # below can re-use the same client.
        for attempt in range(3):
            try:
                r = await client.get(
                    f"https://api.semanticscholar.org/graph/v1/paper/{pid}/references",
                    params={
                        "fields": "citedPaper.paperId,citedPaper.title,citedPaper.year,citedPaper.authors,citedPaper.externalIds,citedPaper.citationCount",
                        "limit": min(50, limit * 4),
                    },
                    headers=headers,
                    timeout=timeout,
                )
                if r.status_code == 429:
                    # Honour Retry-After; cap at 8s so a misbehaving
                    # S2 doesn't park the worker indefinitely.
                    try:
                        wait_s = float(r.headers.get('Retry-After', '2.0'))
                    except Exception:
                        wait_s = 2.0
                    wait_s = min(8.0, max(0.5, wait_s)) * (2 ** attempt)
                    await _asyncio.sleep(wait_s)
                    last_err = "rate-limited (429) — retrying"
                    continue
                if r.status_code == 404:
                    # S2 doesn't have this identifier — fall through to
                    # the title-search fallback below.
                    last_err = "404"
                    break
                r.raise_for_status()
                data = r.json()
                break
            except HTTPException:
                raise
            except Exception as e:
                last_err = str(e)
                # Network-level errors get one more attempt after a short pause.
                await _asyncio.sleep(0.5 * (2 ** attempt))

        # Title-search fallback. When the primary lookup returned no
        # reference data (either /references gave an empty list or the
        # paperId resolved to nothing) and the FE supplied a title, ask
        # S2 to resolve the canonical paperId by title match and retry
        # /references against that. This recovers the case where the
        # ref carries a DOI that S2's bibliographic index doesn't
        # cross-reference, but the paper itself IS in S2 — fairly
        # common for older journal articles and case reports.
        def _empty(d):
            return not isinstance(d, dict) or not (d.get("data") or [])

        if (_empty(data) and getattr(req, 'title', None)):
            try:
                sr = await client.get(
                    "https://api.semanticscholar.org/graph/v1/paper/search",
                    params={"query": req.title, "limit": 1, "fields": "paperId,title"},
                    headers=headers,
                    timeout=timeout,
                )
                if sr.status_code == 200:
                    hits = (sr.json() or {}).get("data") or []
                    if hits and hits[0].get("paperId"):
                        retry_pid = hits[0]["paperId"]
                        retry_data, retry_err = await _fetch_references(client, retry_pid)
                        if retry_data and (retry_data.get("data") or []):
                            data = retry_data
                            last_err = None
                        elif retry_err:
                            last_err = f"title-fallback: {retry_err}"
            except Exception as e:
                # Search itself failed — keep the original empty result.
                last_err = f"title-search failed: {e}"

        if data is None:
            # Don't propagate 429 to the FE as a hard error — the graph
            # expander runs many of these in parallel and a single
            # over-quota response will keep popping toast notifications.
            # Return an empty items list so the worker silently skips
            # this node and the rest of the queue continues.
            logger.debug("S2 /papers/expand failed after retries: %s", last_err)
            return {"paper_id": pid, "items": [], "rate_limited": True, "detail": last_err}

    items = []
    for entry in (data.get("data") or []):
        p = entry.get("citedPaper") or {}
        ext = p.get("externalIds") or {}
        items.append({
            "paperId": p.get("paperId"),
            "title": p.get("title"),
            "year": p.get("year"),
            "citationCount": p.get("citationCount") or 0,
            "authors": [a.get("name") for a in (p.get("authors") or []) if a.get("name")],
            "doi": ext.get("DOI"),
            "arxiv_id": ext.get("ArXiv"),
        })
    items.sort(key=lambda x: x["citationCount"] or 0, reverse=True)
    items = items[:limit]

    # 2nd-degree verify-status enrichment. For each expanded item probe
    # the Seen-Refs cache by (DOI / arXiv / title+year) — when we have
    # a hit, the verify status was determined during a previous check
    # and we can colour the graph node by that status. Cache misses now
    # fall through to a lightweight S2-derived verdict: items returned
    # from /references with a paperId AND an external ID (DOI or arXiv)
    # are real, indexed publications and get marked 'verified'. Items
    # with just a paperId (no external ID) get 'unverified' — they
    # exist in S2 but aren't independently locatable. Anything else
    # stays 'unknown'. Without this fall-through every 2nd-degree node
    # ended up cyan/unknown because the user's Seen-Refs cache only
    # holds refs from their own past checks, and references-of-
    # references usually aren't in there yet.
    for it in items:
        probe = {
            "doi": it.get("doi"),
            "arxiv_id": it.get("arxiv_id"),
            "title": it.get("title"),
            "year": it.get("year"),
        }
        try:
            cached = await db.lookup_verified_reference(probe)
        except Exception:
            cached = None
        if cached:
            it["verified_status"] = cached.get("status") or "unknown"
            it["pre_verified"] = True
            it["times_seen"] = cached.get("times_seen") or 0
        else:
            has_paper_id = bool(it.get("paperId"))
            has_external_id = bool(it.get("doi") or it.get("arxiv_id"))
            if has_paper_id and has_external_id:
                # S2 returned this from a /references call AND it has a
                # DOI/arXiv. That's strong evidence it's a real, locatable
                # publication — treat as verified-light for graph colouring.
                it["verified_status"] = "verified"
            elif has_paper_id:
                # Indexed by S2 but no external identifier — exists, but
                # the user can't independently look it up. Mark as
                # unverified rather than verified so the colour distinguishes
                # them from the strong-evidence case.
                it["verified_status"] = "unverified"
            else:
                it["verified_status"] = "unknown"
            it["pre_verified"] = False
            it["times_seen"] = 0

    return {"paper_id": pid, "items": items}


@app.get("/api/references/seen")
async def list_seen_references(
    limit: int = 200,
    offset: int = 0,
    q: Optional[str] = None,
    current_user: UserInfo = Depends(require_user),
):
    """Page through the global identity-keyed reference cache.

    Powers the 'Seen References' tab: every reference RefChecker has ever
    verified, deduped by DOI / ArXiv / normalized title, with how many
    times it's been seen across checks. `q` does a substring match on
    title/authors/doi when supplied."""
    limit = max(1, min(1000, int(limit or 200)))
    offset = max(0, int(offset or 0))
    rows = await db.list_verified_references(limit=limit, offset=offset, q=q)
    total = await db.count_verified_references()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": rows,
        # Expose where the cache lives so users can spot a path mismatch
        # between an old install's cache_dir and the new install.
        "db_path": str(getattr(db, "db_path", "")),
    }


@app.delete("/api/references/seen")
async def clear_seen_references(current_user: UserInfo = Depends(require_user)):
    """Wipe the entire Seen References cache. Powers the 'Clear cache'
    button on the Seen Refs tab."""
    removed = await db.clear_verified_references()
    return {"removed": removed}


@app.get("/api/usage/totals")
async def usage_totals(current_user: UserInfo = Depends(require_user)):
    """Per-provider LLM usage + cost-estimate snapshot.

    Tokens are captured from each provider's response on the way through
    the extractor / hallucination / web-search paths. Cost is derived
    from a hand-curated per-provider/per-model rate table; rows without
    a known rate report `cost_usd: null` and the grand total falls back
    to null too so the UI doesn't claim 'free' for unknown models."""
    from . import usage_tracker
    snapshot = usage_tracker.get_usage_totals()
    # Persist on every read so totals survive a crash even if no explicit flush ran.
    try: usage_tracker.flush_persistence()
    except Exception: pass
    return snapshot


@app.delete("/api/usage/totals")
async def reset_usage_totals(current_user: UserInfo = Depends(require_user)):
    """Reset the per-provider counters to zero."""
    from . import usage_tracker
    usage_tracker.reset_usage()
    usage_tracker.flush_persistence()
    return {"reset": True}


class _ListModelsRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    endpoint: Optional[str] = None


_STATIC_MODEL_FALLBACK = {
    "openai": [
        "gpt-4.1", "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o3", "o3-mini", "o1", "o1-mini",
    ],
    "anthropic": [
        "claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5",
        "claude-3-7-sonnet-latest", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest",
    ],
    "google": [
        "gemini-3.1-flash-lite-preview", "gemini-2.5-pro", "gemini-2.5-flash",
        "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash",
    ],
    "azure": [
        "gpt-4.1", "gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
    ],
    "vllm": [
        "meta-llama/Llama-3.3-70B-Instruct", "meta-llama/Llama-3.1-8B-Instruct",
        "mistralai/Mistral-7B-Instruct-v0.3", "Qwen/Qwen2.5-7B-Instruct",
    ],
}


@app.post("/api/llm-configs/models")
async def list_llm_models(req: _ListModelsRequest, current_user: UserInfo = Depends(require_user)):
    """Return the model list available to the given provider+key combo.

    Tries the provider's live /models endpoint first (so users see whatever
    they have access to, e.g. fine-tunes or new model IDs that aren't in
    the codebase yet). Falls back to a curated static list when the live
    lookup fails or isn't supported — the UI exposes the same field as a
    free-text input too, so an unfamiliar model can always be typed in.
    """
    provider = (req.provider or "").lower().strip()
    if provider in ("gemini",):
        provider = "google"
    api_key = (req.api_key or "").strip() or None
    endpoint = (req.endpoint or "").strip() or None

    source = "fallback"
    models: list[str] = []
    error: Optional[str] = None
    try:
        if provider == "openai" and api_key:
            import httpx
            r = await asyncio.to_thread(
                httpx.get, "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}, timeout=8.0,
            )
            if r.status_code == 200:
                models = sorted({m["id"] for m in r.json().get("data", []) if m.get("id")})
                source = "live"
        elif provider == "anthropic" and api_key:
            import httpx
            r = await asyncio.to_thread(
                httpx.get, "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"}, timeout=8.0,
            )
            if r.status_code == 200:
                models = sorted({m["id"] for m in r.json().get("data", []) if m.get("id")})
                source = "live"
        elif provider == "google" and api_key:
            import httpx
            r = await asyncio.to_thread(
                httpx.get, "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": api_key}, timeout=8.0,
            )
            if r.status_code == 200:
                seen = set()
                for m in r.json().get("models", []):
                    name = (m.get("name") or "").replace("models/", "")
                    if name and name not in seen:
                        seen.add(name)
                models = sorted(seen)
                source = "live"
        elif provider == "vllm" and endpoint:
            import httpx
            url = endpoint.rstrip("/") + "/v1/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            r = await asyncio.to_thread(httpx.get, url, headers=headers, timeout=6.0)
            if r.status_code == 200:
                models = sorted({m["id"] for m in r.json().get("data", []) if m.get("id")})
                source = "live"
    except Exception as e:
        error = str(e)
        logger.info("Live model lookup failed for %s: %s", provider, e)

    if not models:
        models = list(_STATIC_MODEL_FALLBACK.get(provider, []))

    return {"provider": provider, "source": source, "models": models, "error": error}


class _AutoPathRequest(BaseModel):
    setting: str  # "cache_dir" | "db_path"


@app.post("/api/settings/auto-create-path")
async def auto_create_path_setting(req: _AutoPathRequest, current_user: UserInfo = Depends(require_user)):
    """One-click 'use the default location' for cache_dir / db_path.

    Picks the canonical path under the per-user data dir, creates the
    directory if it doesn't exist, persists it as the named setting, and
    returns the resolved path. Pairs with the 'Use default' button in the
    desktop app's Settings panel so the user doesn't have to know where
    Application Support / %APPDATA% / XDG_DATA_HOME live.
    """
    _require_admin(current_user)
    key = (req.setting or "").strip()
    if key not in ("cache_dir", "db_path"):
        raise HTTPException(status_code=400, detail="`setting` must be 'cache_dir' or 'db_path'")
    base = get_data_dir()
    target = base / ("cache" if key == "cache_dir" else "databases")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not create {target}: {e}")
    try:
        await db.set_setting(key, str(target))
    except Exception as e:
        logger.exception("Failed to persist %s setting", key)
        raise HTTPException(status_code=500, detail=str(e))
    if key == "db_path":
        os.environ["REFCHECKER_DATABASE_DIRECTORY"] = str(target)
    return {"setting": key, "path": str(target)}


class _OpenReviewListRequest(BaseModel):
    venue: str
    status: str = "accepted"  # accepted | submitted


@app.post("/api/openreview/list")
async def fetch_openreview_list(req: _OpenReviewListRequest, current_user: UserInfo = Depends(require_user)):
    """Return the URL list for an OpenReview venue so the frontend can feed
    it into the existing batch-check flow. Wraps prepare_openreview_paper_specs
    from the CLI module so the in-app UI matches `--openreview <venue>`."""
    venue = (req.venue or "").strip()
    if not venue:
        raise HTTPException(status_code=400, detail="`venue` is required (e.g. iclr2024)")
    status = (req.status or "accepted").lower()
    if status not in ("accepted", "submitted"):
        raise HTTPException(status_code=400, detail="`status` must be 'accepted' or 'submitted'")

    try:
        from refchecker.core.refchecker import prepare_openreview_paper_specs
        loop = asyncio.get_event_loop()
        paper_specs, list_path, venue_info = await loop.run_in_executor(
            None,
            lambda: prepare_openreview_paper_specs(venue, status=status, output_dir=str(get_data_dir() / "openreview")),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("OpenReview list fetch failed")
        raise HTTPException(status_code=500, detail=f"OpenReview lookup failed: {e}")

    return {
        "venue": venue_info.get("slug", venue),
        "display_name": venue_info.get("display_name", venue),
        "status": status,
        "paper_count": len(paper_specs),
        "papers": paper_specs,
        "list_path": list_path,
    }


@app.post("/api/databases/download")
async def trigger_database_download(req: _DBDownloadRequest, current_user: UserInfo = Depends(require_user)):
    """Kick off background downloads for the requested local databases."""
    _require_admin(current_user)

    requested = [d for d in (req.databases or []) if d in _DB_DOWNLOAD_SUPPORTED]
    if not requested:
        raise HTTPException(status_code=400, detail=f"databases must be a non-empty subset of {_DB_DOWNLOAD_SUPPORTED}")

    target_dir = _resolve_download_directory(req.directory)
    # Persist the directory so check runs find the DBs after they're built.
    try:
        await db.set_setting("db_path", str(target_dir))
    except Exception:
        logger.warning("Could not persist db_path setting", exc_info=True)
    os.environ["REFCHECKER_DATABASE_DIRECTORY"] = str(target_dir)

    started: list[str] = []
    for db_name in requested:
        filename = DATABASE_FILE_ALIASES[db_name][0]
        await _start_db_download(db_name, target_dir / filename, req.openalex_min_year)
        started.append(db_name)

    return {
        "started": started,
        "directory": str(target_dir),
        "openalex_min_year": req.openalex_min_year,
    }


@app.get("/api/databases/download/status")
async def get_database_download_status(current_user: UserInfo = Depends(require_user)):
    """Return current state of in-flight and recently-finished downloads."""
    _require_admin(current_user)
    tasks: Dict[str, Dict[str, object]] = {}
    for name, state in _DB_DOWNLOAD_TASKS.items():
        tasks[name] = {
            "status": state.status,
            "started_at": state.started_at,
            "finished_at": state.finished_at,
            "error": state.error,
            "log_tail": _read_log_tail(state.log_path),
        }
    return {"tasks": tasks, "supported": list(_DB_DOWNLOAD_SUPPORTED)}


@app.post("/api/databases/download/cancel")
async def cancel_database_download(payload: Dict[str, str] = Body(...), current_user: UserInfo = Depends(require_user)):
    """Cancel a running database download."""
    _require_admin(current_user)
    db_name = payload.get("database")
    if not db_name:
        raise HTTPException(status_code=400, detail="`database` is required")
    state = _DB_DOWNLOAD_TASKS.get(db_name)
    if not state or state.status != "running":
        return {"cancelled": False, "reason": "no running task"}
    state.task.cancel()
    return {"cancelled": True}


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
