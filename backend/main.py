"""
FastAPI application for RefChecker Web UI
"""
from contextlib import asynccontextmanager
import asyncio
import time
import uuid
import os
import re
import shutil
import sys
import tempfile
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Body, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
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
from .websocket_manager import manager, presence
from .refchecker_wrapper import ProgressRefChecker
from .models import CheckRequest, CheckHistoryItem
from .concurrency import init_limiter, get_limiter, set_default_max_concurrent, DEFAULT_MAX_CONCURRENT
from .cites_refs import fetch_cites_and_refs, normalize_mode as _normalize_overlap_mode
from .auth import (
    SITE_URL,
    is_multiuser_mode,
    reload_config as reload_auth_config,
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
    get_preview_cache_path,
    is_probably_placeholder_thumbnail,
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

if sys.platform == 'win32' and not os.environ.get("PYTEST_CURRENT_TEST"):
    loggers = [logging.getLogger()]
    loggers.extend(
        logger_obj
        for logger_obj in logging.Logger.manager.loggerDict.values()
        if isinstance(logger_obj, logging.Logger)
    )
    for configured_logger in loggers:
        for handler in configured_logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                handler.setStream(sys.stderr)
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
LLMConfigId = Union[int, str]
ENV_LLM_CONFIG_ID_PREFIX = "env:"


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


def _normalize_llm_provider_name(provider_name: Optional[str]) -> str:
    normalized = (provider_name or "").strip().lower()
    return "google" if normalized == "gemini" else normalized


def _env_llm_config_for_provider(provider_name: str) -> Optional[Dict[str, Any]]:
    """Return non-secret metadata for a provider configured via server env vars."""
    from refchecker.config.settings import DEFAULT_EXTRACTION_MODELS, resolve_api_key, resolve_endpoint

    provider = _normalize_llm_provider_name(provider_name)
    if provider == "vllm" or provider not in DEFAULT_EXTRACTION_MODELS:
        return None
    if not resolve_api_key(provider):
        return None

    endpoint = resolve_endpoint(provider)
    return {
        "id": f"{ENV_LLM_CONFIG_ID_PREFIX}{provider}",
        "name": f"{provider.title()} (server environment)",
        "provider": provider,
        "model": DEFAULT_EXTRACTION_MODELS[provider],
        "endpoint": endpoint,
        "is_default": False,
        "created_at": None,
        "has_key": True,
        "key_source": "environment",
        "is_environment": True,
        "env_key_available": True,
        "env_endpoint_available": bool(endpoint),
    }


def _all_env_llm_configs() -> Dict[str, Dict[str, Any]]:
    from refchecker.config.settings import DEFAULT_EXTRACTION_MODELS

    configs: Dict[str, Dict[str, Any]] = {}
    for provider in DEFAULT_EXTRACTION_MODELS:
        config = _env_llm_config_for_provider(provider)
        if config:
            configs[provider] = config
    return configs


def _merge_env_llm_configs(configs: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Annotate DB configs with env-key availability and add missing env configs."""
    env_configs = _all_env_llm_configs()
    merged: list[Dict[str, Any]] = []
    seen_providers: set[str] = set()

    for config in configs:
        enriched = dict(config)
        provider = _normalize_llm_provider_name(enriched.get("provider"))
        if provider:
            seen_providers.add(provider)
        env_config = env_configs.get(provider)
        if env_config:
            enriched["env_key_available"] = True
            enriched["env_endpoint_available"] = env_config.get("env_endpoint_available", False)
            if not enriched.get("endpoint") and env_config.get("endpoint"):
                enriched["endpoint"] = env_config["endpoint"]
                enriched["endpoint_source"] = "environment"
            if not enriched.get("has_key"):
                enriched["has_key"] = True
                enriched["key_source"] = "environment"
            else:
                enriched.setdefault("key_source", "database")
        else:
            enriched.setdefault("env_key_available", False)
            if enriched.get("has_key"):
                enriched.setdefault("key_source", "database")
        merged.append(enriched)

    default_provider = _normalize_llm_provider_name(os.environ.get("REFCHECKER_LLM_PROVIDER"))
    has_default = any(config.get("is_default") for config in merged)
    for provider, env_config in env_configs.items():
        if provider in seen_providers:
            continue
        synthetic = dict(env_config)
        if not has_default and provider == default_provider:
            synthetic["is_default"] = True
            has_default = True
        merged.append(synthetic)

    return merged


def _is_env_llm_config_id(config_id: Optional[LLMConfigId]) -> bool:
    return isinstance(config_id, str) and config_id.startswith(ENV_LLM_CONFIG_ID_PREFIX)


def _env_llm_config_from_id(config_id: LLMConfigId) -> Optional[Dict[str, Any]]:
    if not _is_env_llm_config_id(config_id):
        return None
    provider = str(config_id)[len(ENV_LLM_CONFIG_ID_PREFIX):]
    return _env_llm_config_for_provider(provider)


async def _resolve_llm_config_for_request(
    *,
    user_id: int,
    use_llm: bool,
    llm_config_id: Optional[LLMConfigId],
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
        config = _env_llm_config_from_id(llm_config_id)
        if not config and not _is_env_llm_config_id(llm_config_id):
            config = await db.get_llm_config_by_id(int(llm_config_id), user_id=user_id)
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

    if provider:
        from refchecker.config.settings import resolve_api_key, resolve_endpoint

        if not effective_api_key:
            effective_api_key = resolve_api_key(provider)
        if not endpoint:
            endpoint = resolve_endpoint(provider)

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
    # Both optional so a caller can update only the label, only the team share,
    # or both. ``team_id`` of ``None`` is "leave unchanged"; pass 0 to unshare
    # (R26). ``batch_label`` of ``None`` leaves the label untouched.
    batch_label: Optional[str] = None
    team_id: Optional[int] = None


class BatchUrlsRequest(BaseModel):
    """Request model for batch URL submission.

    Carries the same per-check configuration as the single-check endpoint —
    the /api/check/batch handler reads all of these off the request, so they
    must be declared here (previously only urls/batch_label were, which made
    the handler raise AttributeError -> HTTP 500 on the first config read)."""
    urls: list[str]
    batch_label: Optional[str] = None
    llm_config_id: Optional[LLMConfigId] = None
    llm_provider: str = "anthropic"
    llm_model: Optional[str] = None
    hallucination_config_id: Optional[LLMConfigId] = None
    hallucination_provider: Optional[str] = None
    hallucination_model: Optional[str] = None
    use_llm: bool = True
    api_key: Optional[str] = None
    hallucination_api_key: Optional[str] = None
    semantic_scholar_api_key: Optional[str] = None
    paperclip_api_key: Optional[str] = None
    ai_detection_enabled: bool = False
    ai_detection_backend: str = "local"
    ai_detection_api_key: Optional[str] = None
    ai_detection_consent: bool = False
    ai_detection_service: str = "pangram"
    # R61: the FE's chosen multi-detector run-set. >1 key routes through
    # multi_run.run_detectors (compare); empty/1 keeps the single-detector path.
    ai_detection_detectors: Optional[List[str]] = None
    detection_mode: str = "both"


class TeamCreate(BaseModel):
    """Request model for creating a team (issue #66)."""
    name: str


class CheckShareRequest(BaseModel):
    """Request model for sharing a single check with a team (R26).

    ``team_id`` of 0/None unshares the check (clears its team)."""
    team_id: Optional[int] = None


class TeamMemberAdd(BaseModel):
    """Request model for adding a member to a team by email or user id."""
    email: Optional[str] = None
    user_id: Optional[int] = None
    role: str = "member"
    llm_provider: str = "anthropic"
    llm_model: Optional[str] = None
    hallucination_config_id: Optional[LLMConfigId] = None
    hallucination_provider: Optional[str] = None
    hallucination_model: Optional[str] = None
    use_llm: bool = True
    api_key: Optional[str] = None
    hallucination_api_key: Optional[str] = None
    semantic_scholar_api_key: Optional[str] = None
    paperclip_api_key: Optional[str] = None
    ai_detection_enabled: bool = False
    ai_detection_backend: str = "local"
    ai_detection_api_key: Optional[str] = None
    ai_detection_consent: bool = False
    ai_detection_service: str = "pangram"
    # R61: the FE's chosen multi-detector run-set. >1 key routes through
    # multi_run.run_detectors (compare); empty/1 keeps the single-detector path.
    ai_detection_detectors: Optional[List[str]] = None
    detection_mode: str = "both"


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

    # Reconcile orphaned in_progress checks left behind by a previous process
    # (a run_check task that died — or the server restarted — between the last
    # reference and the terminal 'completed' write, so the row stayed
    # 'in_progress' forever and a polling FE never unstuck). At startup nothing
    # is genuinely running yet, but pass the (empty) live map's ids anyway so
    # this path is identical to the on-demand one. Each row is finalized to a
    # status computed from its stored references (completed, or error if zero).
    try:
        active_ids = {meta.get("check_id") for meta in active_checks.values()
                      if meta.get("check_id") is not None}
        reconciled = await db.reconcile_stale_in_progress(active_check_ids=active_ids)
        if reconciled:
            logger.info(f"Reconciled {reconciled} orphaned in-progress checks on startup")
    except Exception as e:
        logger.error(f"Failed to reconcile stale checks: {e}")
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


async def _get_accessible_check_or_404(check_id: int, current_user: UserInfo) -> dict:
    """Return a check if the requester owns it OR it is shared with a team the
    requester belongs to (R26) — the single-check counterpart of
    ``_get_accessible_batch_or_404``.

    Used by the *read* endpoints so a team member can open a check shared with
    them (e.g. from TeamMenu's "Shared checks" list) instead of getting a 404.
    Mutating endpoints stay owner-scoped via ``_get_owned_check_or_404`` /
    ``get_user_id_filter``. A non-owner non-member gets the same opaque 404 an
    unknown check returns. In single-user mode (``user_id`` None) there is no
    scoping, so this is equivalent to the owned variant."""
    user_id = get_user_id_filter(current_user)
    team_ids = await db.get_user_team_ids(current_user.id) if user_id is not None else []
    check = await db.get_check_by_id(check_id, user_id=user_id, team_ids=team_ids)
    if not check:
        raise HTTPException(status_code=404, detail="Check not found")
    return check


async def _get_owned_batch_or_404(batch_id: str, current_user: UserInfo) -> tuple[dict, list[dict]]:
    """Return a batch summary and checks only if they belong to the current user.

    Used by the *mutating* batch endpoints (cancel/delete) where only the owner
    may act. Read endpoints use ``_get_accessible_batch_or_404`` (R26)."""
    user_id = get_user_id_filter(current_user)
    summary = await db.get_batch_summary(batch_id, user_id=user_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Batch not found")
    checks = await db.get_batch_checks(batch_id, user_id=user_id)
    return summary, checks


async def _get_accessible_batch_or_404(batch_id: str, current_user: UserInfo) -> tuple[dict, list[dict]]:
    """Return a batch summary and checks if the requester is the owner OR a
    member of the team the batch is shared with (R26).

    In single-user mode (``user_id`` is None) there is no scoping, so this is
    equivalent to the owned variant. A non-owner non-member gets 404 — the same
    opaque response an unknown batch returns, so sharing isn't enumerable."""
    user_id = get_user_id_filter(current_user)
    team_ids = await db.get_user_team_ids(current_user.id) if user_id is not None else []
    summary = await db.get_batch_summary_accessible(batch_id, user_id=user_id, team_ids=team_ids)
    if not summary:
        raise HTTPException(status_code=404, detail="Batch not found")
    checks = await db.get_batch_checks_accessible(batch_id, user_id=user_id, team_ids=team_ids)
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


def _auth_config_path() -> Path:
    return get_data_dir() / "auth_config.env"


def _read_auth_config_file() -> Dict[str, str]:
    cfg: Dict[str, str] = {}
    p = _auth_config_path()
    try:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    except Exception as e:  # noqa: BLE001
        logger.debug("auth_config read failed: %s", e)
    return cfg


@app.get("/api/auth/config")
async def get_auth_config(current_user: UserInfo = Depends(require_user)):
    """In-app multi-user / OAuth config STATE (presence only — never the secret
    values). Powers Settings -> 'Enable accounts & Teams' so it can show what's
    configured and whether a restart is pending."""
    cfg = _read_auth_config_file()

    def has(k: str) -> bool:
        return bool(cfg.get(k) or os.environ.get(k))

    want_multiuser = cfg.get("REFCHECKER_MULTIUSER", "").lower() in ("1", "true", "yes")
    return {
        "multiuser_active": is_multiuser_mode(),          # this running process
        "multiuser_configured": want_multiuser,            # what's saved for next start
        # R27: set_auth_config hot-reloads, so the running process matches the
        # saved config — no restart needed when these already agree.
        "needs_restart": want_multiuser != is_multiuser_mode(),
        "providers": {
            "google": has("GOOGLE_CLIENT_ID") and has("GOOGLE_CLIENT_SECRET"),
            "github": has("GITHUB_CLIENT_ID") and has("GITHUB_CLIENT_SECRET"),
            "microsoft": has("MS_CLIENT_ID") and has("MS_CLIENT_SECRET"),
        },
    }


class _AuthConfigRequest(BaseModel):
    """Multi-user + OAuth credentials saved from Settings. Secrets omitted (None)
    are KEPT as-is so the UI never has to re-echo them."""
    multiuser: bool = False
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    github_client_id: Optional[str] = None
    github_client_secret: Optional[str] = None
    ms_client_id: Optional[str] = None
    ms_client_secret: Optional[str] = None


@app.put("/api/auth/config")
async def set_auth_config(payload: _AuthConfigRequest, current_user: UserInfo = Depends(require_user)):
    """Persist the multi-user + OAuth config to a private app-data file that the
    sidecar loads on its next start (server_entry.py). The desktop app then
    relaunches to apply. Real-data only: nothing is invented; omitted secrets are
    preserved. In multi-user mode this is restricted to admins."""
    if is_multiuser_mode() and not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin only in multi-user mode")

    existing = _read_auth_config_file()

    def setk(k: str, v):
        if v is not None and str(v).strip():
            existing[k] = str(v).strip()

    existing["REFCHECKER_MULTIUSER"] = "true" if payload.multiuser else "false"
    setk("GOOGLE_CLIENT_ID", payload.google_client_id)
    setk("GOOGLE_CLIENT_SECRET", payload.google_client_secret)
    setk("GITHUB_CLIENT_ID", payload.github_client_id)
    setk("GITHUB_CLIENT_SECRET", payload.github_client_secret)
    setk("MS_CLIENT_ID", payload.ms_client_id)
    setk("MS_CLIENT_SECRET", payload.ms_client_secret)

    has_provider = any([
        existing.get("GOOGLE_CLIENT_ID") and existing.get("GOOGLE_CLIENT_SECRET"),
        existing.get("GITHUB_CLIENT_ID") and existing.get("GITHUB_CLIENT_SECRET"),
        existing.get("MS_CLIENT_ID") and existing.get("MS_CLIENT_SECRET"),
    ])
    if payload.multiuser and not has_provider:
        raise HTTPException(status_code=400, detail="Enabling accounts needs at least one provider's client id + secret")

    lines = [
        "# RefChecker multi-user / OAuth config — written by Settings -> Enable accounts & Teams.",
        "# Loaded by the app's backend at startup. Delete this file to revert to single-user.",
        "",
    ] + [f"{k}={v}" for k, v in existing.items()]
    p = _auth_config_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            os.chmod(p, 0o600)  # restrict (best-effort)
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not save config: {e}")

    # R27: hot-reload the saved config into the running process so accounts /
    # providers take effect without a backend restart. /api/auth/providers and
    # the presence gate read live values, so they reflect the change at once.
    try:
        reload_auth_config(existing)
    except Exception as e:  # noqa: BLE001
        logger.warning("auth hot-reload failed (will apply on next restart): %s", e)

    return {
        "saved": True,
        "multiuser": payload.multiuser,
        "has_provider": bool(has_provider),
        "multiuser_active": is_multiuser_mode(),
        "providers": get_available_providers(),
        # No restart needed now — kept for FE back-compat; it can drop its
        # "please restart" banner since the change is already live.
        "restart_required": False,
    }


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


# ---------------------------------------------------------------------------
# Teams (issue #66): create a team, list my teams, add/list members.
# All require_user; mutations are owner-gated.
# ---------------------------------------------------------------------------

async def _get_team_for_member_or_404(team_id: int, current_user: UserInfo) -> dict:
    """Fetch a team the current user belongs to, or raise 404."""
    team = await db.get_team(team_id)
    if not team or not await db.is_team_member(team_id, current_user.id):
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@app.post("/api/teams")
async def create_team(
    payload: TeamCreate,
    current_user: UserInfo = Depends(require_user),
):
    """Create a team owned by the current user (who is also added as a member)."""
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Team name is required")
    team = await db.create_team(name, current_user.id)
    await db.log_team_activity(
        team["id"], current_user.id, getattr(current_user, "email", None),
        "created_team", detail=name,
    )
    return {"team": team}


@app.get("/api/teams")
async def list_teams(current_user: UserInfo = Depends(require_user)):
    """List teams the current user owns or belongs to."""
    return {"teams": await db.get_teams_for_user(current_user.id)}


@app.get("/api/teams/{team_id}/members")
async def list_team_members(
    team_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """List members of a team the current user belongs to."""
    await _get_team_for_member_or_404(team_id, current_user)
    return {"members": await db.get_team_members(team_id)}


@app.get("/api/teams/{team_id}/activity")
async def list_team_activity(
    team_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """Team activity/audit log — who created the team, added or removed which
    member, and who left. Visible to any member of the team."""
    await _get_team_for_member_or_404(team_id, current_user)
    return {"activity": await db.get_team_activity(team_id, limit=100)}


@app.get("/api/teams/{team_id}/checks")
async def list_team_checks(
    team_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """List checks shared with a team. Visible to any member of the team (R26).

    Gated through ``_get_team_for_member_or_404`` so a non-member gets the same
    opaque 404 a non-existent team returns."""
    await _get_team_for_member_or_404(team_id, current_user)
    return {"checks": await db.get_team_checks(team_id)}


@app.post("/api/checks/{check_id}/share")
async def share_check_with_team(
    check_id: int,
    payload: CheckShareRequest,
    current_user: UserInfo = Depends(require_user),
):
    """Share (or unshare) a single check with a team (R26).

    Only the check's owner may share it, and only with a team they belong to.
    ``team_id`` of 0/None clears the share."""
    user_id = get_user_id_filter(current_user)
    # Owner-scoped fetch: a non-owner gets the same 404 an unknown check returns.
    check = await db.get_check_by_id(check_id, user_id=user_id)
    if not check:
        raise HTTPException(status_code=404, detail="Check not found")

    new_team_id: Optional[int] = payload.team_id if payload.team_id else None
    if new_team_id is not None:
        if user_id is None or not await db.is_team_member(new_team_id, current_user.id):
            raise HTTPException(status_code=403, detail="You are not a member of that team")

    await db.set_check_team(check_id, new_team_id)
    return {"shared": new_team_id is not None, "team_id": new_team_id, "check_id": check_id}


@app.post("/api/teams/{team_id}/members")
async def add_team_member(
    team_id: int,
    payload: TeamMemberAdd,
    current_user: UserInfo = Depends(require_user),
):
    """Add a member by email or user id. Only the team owner may add members."""
    team = await db.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team["owner_user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Only the team owner can add members")

    target = None
    if payload.user_id is not None:
        target = await db.get_user_by_id(payload.user_id)
    elif payload.email:
        target = await db.get_user_by_email(payload.email)
    else:
        raise HTTPException(status_code=400, detail="Provide an email or user_id")

    if not target:
        raise HTTPException(status_code=404, detail="No user found for that email or id")

    role = (payload.role or "member").strip() or "member"
    added = await db.add_team_member(team_id, target["id"], role)
    if added:
        await db.log_team_activity(
            team_id, current_user.id, getattr(current_user, "email", None),
            "added_member", target_user_id=target["id"],
            target_email=target.get("email"), detail=role,
        )
    return {"added": added, "members": await db.get_team_members(team_id)}


@app.delete("/api/teams/{team_id}/members/{user_id}")
async def remove_team_member(
    team_id: int,
    user_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """Remove a member from a team. Only the team owner may remove members, and
    the owner cannot remove themselves this way (they must transfer or delete the
    team / use the leave endpoint, which also forbids it)."""
    team = await db.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team["owner_user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Only the team owner can remove members")
    if user_id == team["owner_user_id"]:
        raise HTTPException(status_code=400, detail="The team owner cannot be removed")

    target = await db.get_user_by_id(user_id)
    removed = await db.remove_team_member(team_id, user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="That user is not a member of this team")
    await db.log_team_activity(
        team_id, current_user.id, getattr(current_user, "email", None),
        "removed_member", target_user_id=user_id,
        target_email=(target or {}).get("email"),
    )
    return {"removed": True, "members": await db.get_team_members(team_id)}


@app.post("/api/teams/{team_id}/leave")
async def leave_team(
    team_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """Leave a team you belong to. The owner may not leave while other members
    remain (they would orphan the team); a sole-owner can leave to empty it."""
    team = await db.get_team(team_id)
    if not team or not await db.is_team_member(team_id, current_user.id):
        raise HTTPException(status_code=404, detail="Team not found")
    if team["owner_user_id"] == current_user.id and await db.count_team_members(team_id) > 1:
        raise HTTPException(
            status_code=400,
            detail="The owner cannot leave a team that still has other members",
        )

    removed = await db.remove_team_member(team_id, current_user.id)
    if removed:
        await db.log_team_activity(
            team_id, current_user.id, getattr(current_user, "email", None),
            "left_team", target_user_id=current_user.id,
            target_email=getattr(current_user, "email", None),
        )
    return {"left": removed}


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


async def _can_access_presence_room(room_id: str, user_id: int) -> bool:
    """Whether ``user_id`` may join a presence room (R26).

    ``batch-{id}`` rooms are gated on owner-or-team-member access to that batch.
    Any other room id keeps the prior authenticated-only behaviour (the caller
    has already validated the JWT)."""
    if not room_id.startswith("batch-"):
        return True
    batch_id = room_id[len("batch-"):]
    if not batch_id:
        return True
    try:
        team_ids = await db.get_user_team_ids(user_id)
        summary = await db.get_batch_summary_accessible(
            batch_id, user_id=user_id, team_ids=team_ids
        )
        return summary is not None
    except Exception as e:  # noqa: BLE001
        logger.warning("presence room access check failed for %s: %s", room_id, e)
        return False


async def _broadcast_check_event_to_batch_room(check_id: int, event_type: str, data: dict) -> None:
    """Mirror a per-check realtime event (reference_result / summary_update) to
    the batch's presence room so every team member viewing it gets it live (R26).

    Best-effort + cheap: skips the DB lookup entirely when nobody is present in
    any batch room, and never raises into the check pipeline."""
    if event_type not in ("reference_result", "summary_update"):
        return
    try:
        info = await db.get_check_batch_team(check_id)
        if not info:
            return
        batch_id = info.get("batch_id")
        if not batch_id:
            return
        room_id = f"batch-{batch_id}"
        if not presence.has_room(room_id):
            return
        await presence.broadcast_to_room(room_id, event_type, {**data, "check_id": check_id})
    except Exception as e:  # noqa: BLE001
        logger.debug("batch-room broadcast failed for check %s: %s", check_id, e)


@app.websocket("/api/ws/presence/{room_id}")
async def presence_endpoint(websocket: WebSocket, room_id: str):
    """Realtime presence for a shared room (batch/check id) — issue #67.

    Authenticated users who open the same ``room_id`` see each other via
    presence_join / presence_leave / presence_state messages. Presence requires
    a real identity, so it only works when OAuth is configured (multi-user mode);
    in single-user mode there is no "team" to show, so we close the socket.
    """
    if not get_available_providers():
        await websocket.close(code=4003, reason="Presence requires multi-user mode")
        return

    token = websocket.cookies.get("rc_auth")
    if not token:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    token_data = decode_access_token(token)
    if not token_data:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # Gate batch rooms on accessible-batch membership (R26): a user may only
    # join a `batch-{id}` room if they own that batch or belong to the team it
    # is shared with. Non-batch rooms (e.g. a bare check id) keep the prior
    # authenticated-only behaviour.
    if not await _can_access_presence_room(room_id, token_data.user_id):
        await websocket.close(code=4003, reason="Not authorized for this room")
        return

    user = {
        "user_id": token_data.user_id,
        "name": token_data.name,
        "email": token_data.email,
    }
    await websocket.accept()
    await presence.join(websocket, room_id, user)
    try:
        # Keep the connection open; presence is driven by connect/disconnect.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await presence.leave(websocket, room_id)


@app.post("/api/check")
async def start_check(
    source_type: str = Form(...),
    source_value: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    source_text: Optional[str] = Form(None),
    llm_config_id: Optional[LLMConfigId] = Form(None),
    llm_provider: str = Form("anthropic"),
    llm_model: Optional[str] = Form(None),
    hallucination_config_id: Optional[LLMConfigId] = Form(None),
    hallucination_provider: Optional[str] = Form(None),
    hallucination_model: Optional[str] = Form(None),
    use_llm: bool = Form(True),
    api_key: Optional[str] = Form(None),
    hallucination_api_key: Optional[str] = Form(None),
    semantic_scholar_api_key: Optional[str] = Form(None),
    paperclip_api_key: Optional[str] = Form(None),
    ai_detection_enabled: bool = Form(False),
    ai_detection_backend: str = Form("local"),
    ai_detection_api_key: Optional[str] = Form(None),
    ai_detection_consent: bool = Form(False),
    ai_detection_service: str = Form("pangram"),
    # R61: repeated form field — one value per chosen detector key. FastAPI
    # collects the repeats into a list; >1 routes through the compare path.
    ai_detection_detectors: Optional[List[str]] = Form(None),
    detection_mode: str = Form("both"),
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
        paperclip_api_key = _form_default_value(paperclip_api_key)
        ai_detection_enabled = _form_default_value(ai_detection_enabled)
        ai_detection_backend = _form_default_value(ai_detection_backend)
        ai_detection_api_key = _form_default_value(ai_detection_api_key)
        ai_detection_consent = _form_default_value(ai_detection_consent)
        ai_detection_service = _form_default_value(ai_detection_service)
        detection_mode = _form_default_value(detection_mode)
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
                "paperclip_key_present": bool(paperclip_api_key),
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
                ai_detection_enabled=ai_detection_enabled,
                ai_detection_backend=ai_detection_backend,
                ai_detection_api_key=ai_detection_api_key,
                ai_detection_consent=ai_detection_consent,
                ai_detection_service=ai_detection_service,
                ai_detection_detectors=ai_detection_detectors,
                paperclip_api_key=paperclip_api_key,
                detection_mode=detection_mode,
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
    ai_detection_enabled: bool = False,
    ai_detection_backend: str = "local",
    ai_detection_api_key: Optional[str] = None,
    ai_detection_consent: bool = False,
    ai_detection_service: str = "pangram",
    ai_detection_detectors: Optional[List[str]] = None,
    paperclip_api_key: Optional[str] = None,
    detection_mode: str = "both",
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

            # R26: also fan live per-ref / summary updates out to the batch's
            # presence room so team members collaborating on the same batch see
            # them, not just the owner's session. No-op unless someone's present.
            await _broadcast_check_event_to_batch_room(check_id, event_type, data)

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
            ai_detection_enabled=ai_detection_enabled,
            ai_detection_backend=ai_detection_backend,
            ai_detection_api_key=ai_detection_api_key,
            ai_detection_consent=ai_detection_consent,
            ai_detection_service=ai_detection_service,
            ai_detection_detectors=ai_detection_detectors,
            paperclip_api_key=paperclip_api_key,
            detection_mode=detection_mode,
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
            ai_detection=result.get("ai_detection"),
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
        # R54: release the per-request hallucination ThreadPoolExecutor (the
        # 8-worker pool added in R04) so each check does not leak daemon threads.
        # Best-effort + idempotent; runs after all progress/result emission, and
        # `checker` may be unbound if construction failed early, so look it up
        # defensively rather than assuming it exists.
        _checker = locals().get('checker')
        if _checker is not None:
            try:
                _checker.close()
            except Exception:
                pass
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
    """Get detailed results for a specific check.

    Read access is team-aware (R26): the owner, or any member of the team the
    check is shared with, can open it. This is what makes TeamMenu's "Shared
    checks" list openable for members instead of 404."""
    try:
        check = await _get_accessible_check_or_404(check_id, current_user)

        if check.get("status") == "in_progress":
            session_id = _session_id_for_check(check_id)
            if session_id:
                # A genuinely running check — hand the FE its live session so
                # it can keep streaming. NEVER reconcile this one.
                check["session_id"] = session_id
            else:
                # Orphaned: in_progress but not in the live active_checks map.
                # If it's also stale (refs done, or last activity too old),
                # finalize it now so the polling FE unsticks on this very GET
                # instead of looping forever. The active-ids guard (re-checked
                # inside finalize_stale_check) keeps a check that started
                # running between these two lines untouched.
                active_ids = {m.get("check_id") for m in active_checks.values()
                              if m.get("check_id") is not None}
                try:
                    stale = await db.find_stale_in_progress_checks(active_check_ids=active_ids)
                    if any(int(r["id"]) == check_id for r in stale):
                        finalized = await db.finalize_stale_check(check_id)
                        if finalized:
                            logger.info(
                                "Reconciled orphaned in-progress check %s on read (-> %s)",
                                check_id, finalized,
                            )
                            check = await _get_accessible_check_or_404(check_id, current_user)
                except Exception as e:  # noqa: BLE001 — read must still return
                    logger.warning("On-demand reconcile failed for check %s: %s", check_id, e)
        return check
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting check detail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _render_check_html(check_id: int, current_user: UserInfo) -> tuple[str, str]:
    """Resolve a check and render it to standalone HTML. Returns (title, html).

    Team-aware read (R26): a member of the team a check is shared with can export
    it, mirroring the shared-check detail view (renders only the already-shared
    references + verdicts, no owner-only raw assets)."""
    check = await _get_accessible_check_or_404(check_id, current_user)
    from backend.export import serialize_check_to_html
    html_str = serialize_check_to_html(check)
    title = check.get("paper_title") or check.get("custom_label") or f"refchecker-{check_id}"
    return title, html_str


@app.get("/api/export/{check_id}/html")
async def export_check_html(check_id: int, download: bool = True,
                            current_user: UserInfo = Depends(require_user)):
    """Self-contained HTML export of a check's results (references + verdicts +
    AI-detection summary). The default download path drives 'Share → Download'."""
    try:
        title, html_str = await _render_check_html(check_id, current_user)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", title)[:80].strip("-") or f"refchecker-{check_id}"
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{safe}.html"'
        return HTMLResponse(content=html_str, headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting check html: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not export this check as HTML.")


class _PublishRequest(BaseModel):
    adapter: str = "github_gist"   # 'github_gist'
    token: str = ""                 # caller-supplied PAT (gist scope)
    public: bool = False


@app.get("/api/check/{check_id}/health")
async def get_check_health(check_id: int, current_user: UserInfo = Depends(require_user)):
    """Citation-health score for a check (same formula as the in-app badge)."""
    try:
        # Team-aware read (R26): the health badge must work in the shared-check
        # detail view for a team member, not just the owner.
        check = await _get_accessible_check_or_404(check_id, current_user)
        from backend import export as _export
        m = _export._model(check, corrections=False, sections=set(_export.ALL_SECTIONS))
        return {"check_id": check_id, **m["health"], "stats": m["stats"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error computing health for {check_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/check/{check_id}/retractions")
async def get_check_retractions(check_id: int, current_user: UserInfo = Depends(require_user)):
    """Flag cited references that OpenAlex reports as retracted (real signal only).

    On-demand (one batched OpenAlex query). References with no DOI -> 'no_doi';
    DOIs not found -> 'unknown'; never a fabricated retraction.
    """
    try:
        # Team-aware read (R26): retraction check operates on the already-shared
        # reference list, so a team member viewing the shared check may run it.
        check = await _get_accessible_check_or_404(check_id, current_user)
        from backend import export as _export
        from backend.retraction import check_retractions
        refs = _export._as_list(check.get("results")) or _export._as_list(check.get("references"))
        result = await asyncio.to_thread(check_retractions, refs)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking retractions for {check_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _extract_paper_text_for_check(check_id: int, check: Dict[str, Any]) -> str:
    """Best-effort extracted body text for a check (cache-first), for analyses
    that need the full paper body. Mirrors get_paper_text's retrieval."""
    try:
        cache_dir = await _get_configured_cache_dir()
        if cache_dir:
            p = os.path.join(str(cache_dir), "paper_text", f"{check_id}.txt")
            if os.path.exists(p) and os.path.getsize(p) > 0:
                cached = await asyncio.to_thread(_read_cached_paper_text, p)
                if cached and cached.strip():
                    return cached
    except Exception as _e:
        logger.debug("citation-integrity cache read skipped: %s", _e)
    source_type = check.get("source_type", "") or ""
    paper_source = check.get("paper_source", "") or ""
    from backend.refchecker_wrapper import _extract_pdf_text_cli_style
    text = ""
    if source_type == "file" and paper_source and os.path.exists(paper_source):
        if paper_source.lower().endswith(".pdf"):
            text = await asyncio.to_thread(_extract_pdf_text_cli_style, paper_source, None)
        else:
            try:
                with open(paper_source, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except Exception:
                text = ""
    if not (text or "").strip() and paper_source:
        try:
            from refchecker.utils.cache_utils import get_cached_artifact_path
            cache_dir = await _get_configured_cache_dir()
            if cache_dir:
                for artifact in ("ai_body.pdf", "paper.pdf"):
                    pp = get_cached_artifact_path(str(cache_dir), paper_source, artifact)
                    if pp and os.path.exists(pp) and os.path.getsize(pp) > 0:
                        text = await asyncio.to_thread(_extract_pdf_text_cli_style, pp, None)
                        break
        except Exception as _e:
            logger.debug("citation-integrity pdf lookup failed: %s", _e)
    return text or ""


@app.get("/api/check/{check_id}/citation-integrity")
async def get_citation_integrity(check_id: int, current_user: UserInfo = Depends(require_user)):
    """Inline-citation numbering integrity (gaps / out-of-order / duplicates /
    undefined / uncited), scheme-aware. Abstains when the scheme is unclear."""
    try:
        check = await _get_owned_check_or_404(check_id, current_user)
        text = await _extract_paper_text_for_check(check_id, check)
        from backend import export as _export
        from backend.inline_citation_checker import inline_citation_report
        refs = _export._as_list(check.get("results")) or _export._as_list(check.get("references"))
        report = await asyncio.to_thread(inline_citation_report, text, refs)
        report["has_text"] = bool((text or "").strip())
        return report
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking citation integrity for {check_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------------------------------- #
# EPIC-D: grounded Chat-with-PDF + Summarize                                   #
# --------------------------------------------------------------------------- #
# Grounding is REAL DATA ONLY: the extracted paper body (source='pdf'), or an
# Abstract section sliced from that body as a fallback (source='abstract'). If
# neither exists (source='none') the feature is disabled honestly — no LLM call.

# Below this many chars of body text we treat the available text as an abstract
# rather than a full paper (e.g. a .bbl/.bib source where only the abstract was
# captured, or a very short note). The summarize/chat answer is then explicitly
# flagged "from abstract only" in the UI.
_CHAT_PDF_BODY_MIN_CHARS = 2500


def _slice_abstract(text: str) -> str:
    """Best-effort: return the Abstract section of a paper body, or ''.

    Real-data only — slices the existing extracted text between an 'Abstract'
    heading and the next section heading (Introduction / Keywords / 1 ...). No
    fabrication; returns '' when no abstract block is recognizable.
    """
    if not text:
        return ""
    # NOTE: the leading (?im) applies to the WHOLE alternation, so a second
    # inline (?i) mid-pattern is redundant AND illegal on Python 3.11+
    # ("global flags not at the start of the expression"). Keep only the leading flags.
    m = re.search(r'(?im)^\s*abstract\s*[:.\-]?\s*$|\babstract\b\s*[:.\-]', text)
    if not m:
        return ""
    tail = text[m.end():]
    stop = re.search(
        r'(?im)^\s*(?:\d+\s*[.\)]?\s*)?(introduction|keywords|index terms|'
        r'1\s+introduction|background|related work)\b',
        tail,
    )
    abstract = tail[: stop.start()] if stop else tail[:2000]
    return abstract.strip()


async def _resolve_chat_grounding(check_id: int, check: Dict[str, Any]) -> tuple[str, str]:
    """Resolve (grounding_text, source) for chat/summarize. Real data only.

    source is one of: 'pdf' (full body), 'abstract' (only an abstract is
    available), 'none' (nothing to ground on — caller disables the feature).
    """
    text = (await _extract_paper_text_for_check(check_id, check)) or ""
    text = text.strip()
    if len(text) >= _CHAT_PDF_BODY_MIN_CHARS:
        return text, "pdf"
    abstract = _slice_abstract(text)
    if abstract:
        return abstract, "abstract"
    if text:
        # Short body that is not a recognizable abstract block — still real
        # extracted text; treat it as an abstract-grade snippet, honestly.
        return text, "abstract"
    return "", "none"


class _ArticleSummaryRequest(BaseModel):
    llm_config_id: Optional[LLMConfigId] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class _ArticleChatRequest(_ArticleSummaryRequest):
    messages: List[Dict[str, str]] = []


async def _resolve_article_assistant(req: _ArticleSummaryRequest, user_id: int, check_id=None):
    """Resolve the Chat & Summarize provider via the shared LLM config path.

    ``check_id`` attributes chat / summarize token spend to the per-check LLM
    usage meter (the on-screen token/$ badge) so follow-up chat / summarize
    calls tick the badge up live, with their own per-flow breakdown.
    """
    provider, model, api_key, endpoint = await _resolve_llm_config_for_request(
        user_id=user_id,
        use_llm=True,
        llm_config_id=req.llm_config_id,
        llm_provider=req.provider,
        llm_model=req.model,
        api_key=req.api_key,
    )
    if not provider:
        raise HTTPException(status_code=400, detail="No LLM configured for Chat & Summarize.")
    from backend.article_chat import ArticleAssistant
    return ArticleAssistant(
        provider=provider, api_key=api_key, endpoint=endpoint, model=model, check_id=check_id,
    )


@app.post("/api/check/{check_id}/summarize")
async def summarize_article(
    check_id: int,
    req: _ArticleSummaryRequest = Body(default=_ArticleSummaryRequest()),
    current_user: UserInfo = Depends(require_user),
):
    """Grounded one-shot summary of the article, from its own text only.

    Honest by construction: when no paper text is available (source='none')
    the feature is disabled and no LLM is called."""
    try:
        check = await _get_owned_check_or_404(check_id, current_user)
        grounding, source = await _resolve_chat_grounding(check_id, check)
        if source == "none":
            return {"summary": None, "source": "none",
                    "detail": "No article text is available to summarize."}
        assistant = await _resolve_article_assistant(req, get_user_id_filter(current_user), check_id=check_id)
        if not assistant.available:
            raise HTTPException(status_code=400, detail="LLM provider unavailable (missing API key?).")
        result = await asyncio.to_thread(assistant.summarize, grounding, source)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error summarizing check {check_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/check/{check_id}/chat")
async def chat_article(
    check_id: int,
    req: _ArticleChatRequest,
    current_user: UserInfo = Depends(require_user),
):
    """Grounded chat over the article: answers ONLY from the document text.

    The system prompt is prompt-injection-safe (document text is untrusted
    data) and abstains ("the article does not state this") rather than guess.
    When no paper text is available (source='none') the feature is disabled."""
    try:
        check = await _get_owned_check_or_404(check_id, current_user)
        grounding, source = await _resolve_chat_grounding(check_id, check)
        if source == "none":
            return {"answer": None, "source": "none",
                    "detail": "No article text is available to chat about."}
        if not req.messages:
            raise HTTPException(status_code=400, detail="No message provided.")
        assistant = await _resolve_article_assistant(req, get_user_id_filter(current_user), check_id=check_id)
        if not assistant.available:
            raise HTTPException(status_code=400, detail="LLM provider unavailable (missing API key?).")
        result = await asyncio.to_thread(assistant.chat, req.messages, grounding, source)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in article chat for {check_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------------------------------- #
# R43: per-reference chat grounded in the reference's own fetched full text.   #
# --------------------------------------------------------------------------- #
# When a user opens Chat & Summarize for a CITED reference (not the host
# paper), we try to fetch that reference's open-access PDF (arXiv → OpenAlex
# best_oa_location / Unpaywall) and extract its real body text so chat can
# answer from the document. HONESTY: only real fetched text is returned; on any
# miss the FE keeps the existing TL;DR-only disclaimer verbatim — nothing is
# fabricated. Retrieval is cached per identity (DOI/arXiv/title), soft-fails,
# and is concurrency-bounded inside the retrieval module.


class _ReferenceFulltextRequest(BaseModel):
    # The minimal real identity of the cited reference, as the FE already holds
    # it on each ReferenceCard: doi / arxiv_id / title (+ optional enrichment so
    # an already-resolved oa_pdf_url can short-circuit the network).
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    title: Optional[str] = None
    verified_doi: Optional[str] = None
    enrichment: Optional[Dict[str, Any]] = None


@app.post("/api/check/{check_id}/reference-fulltext")
async def get_reference_fulltext(
    check_id: int,
    req: _ReferenceFulltextRequest = Body(default=_ReferenceFulltextRequest()),
    current_user: UserInfo = Depends(require_user),
):
    """Retrieve a cited reference's REAL open-access full text for grounded chat.

    Returns ``{source: 'pdf', grounding: <full_text>}`` when an OA PDF was
    fetched + extracted, else ``{source: 'tldr', grounding: None}`` so the FE
    keeps the existing TL;DR-only disclaimer. Never fabricates: on any miss it
    returns the TL;DR fallback. The check ownership gate is reused so this
    endpoint can't be used to fetch arbitrary PDFs anonymously.
    """
    try:
        await _get_owned_check_or_404(check_id, current_user)
        from refchecker.utils.reference_fulltext import get_reference_fulltext as _get_ft
        reference = {
            "doi": req.doi,
            "verified_doi": req.verified_doi,
            "arxiv_id": req.arxiv_id,
            "title": req.title,
            "enrichment": req.enrichment or {},
        }
        text, source = await asyncio.to_thread(_get_ft, reference)
        if source == "pdf" and text:
            return {"source": "pdf", "grounding": text}
        # Honest fallback — no full text resolved; FE keeps the TL;DR disclaimer.
        return {"source": "tldr", "grounding": None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving reference full text for {check_id}: {e}", exc_info=True)
        # Soft-fail to the TL;DR fallback rather than surfacing a 500 — the chat
        # still works grounded in the reference metadata.
        return {"source": "tldr", "grounding": None}


@app.get("/api/check/{check_id}/citation-renumber-preview")
async def get_citation_renumber_preview(
    check_id: int,
    insert_at: Optional[int] = None,
    current_user: UserInfo = Depends(require_user),
):
    """Read-only preview of how EXISTING inline numeric markers would renumber if
    a new reference were inserted to take printed position ``insert_at`` (1-based;
    omit to append). Abstains (empty shifts) whenever the inline-citation checker
    abstains. Mutates nothing — the document/PDF is never edited."""
    try:
        check = await _get_owned_check_or_404(check_id, current_user)
        text = await _extract_paper_text_for_check(check_id, check)
        from backend import export as _export
        from backend.inline_citation_checker import renumber_preview
        refs = _export._as_list(check.get("results")) or _export._as_list(check.get("references"))
        report = await asyncio.to_thread(renumber_preview, text, refs, insert_at)
        return report
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error computing renumber preview for {check_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/check/{check_id}/corrected-reference-list")
async def get_corrected_reference_list(
    check_id: int,
    style: str = "plaintext",
    renumber: int = 1,
    current_user: UserInfo = Depends(require_user),
):
    """Return the FULL reference list in *style* with new CONTIGUOUS numbers.

    Used by the "Download new reference list" button after an Add/renumber: the
    persisted references already carry contiguous ``index`` values (the write
    path renumbers on insert), so with ``renumber=1`` (default) the list is
    numbered 1..N in document order. Each row prefers the verified
    ``corrected_reference`` and never fabricates fields. Mutates nothing."""
    try:
        check = await _get_owned_check_or_404(check_id, current_user)
        from backend import export as _export
        refs = _export._as_list(check.get("results")) or _export._as_list(check.get("references"))
        chosen = style if style in _export.CITATION_STYLES else "plaintext"
        rows = await asyncio.to_thread(
            _export.serialize_reference_list, refs, chosen, bool(renumber)
        )
        text = "\n".join(f"[{row['number']}] {row['formatted']}" for row in rows)
        return {
            "style": chosen,
            "renumbered": bool(renumber),
            "count": len(rows),
            "references": rows,
            "text": text,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building corrected reference list for {check_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/check/{check_id}/gaps")
async def get_check_gaps(check_id: int, current_user: UserInfo = Depends(require_user)):
    """"Did you miss these?" — works frequently co-cited by the bibliography's own
    references but absent from it (OpenAlex). Advisory discovery aid, real data only."""
    try:
        # Team-aware read (R26): gap finder operates on the already-shared
        # reference list, so a team member viewing the shared check may run it.
        check = await _get_accessible_check_or_404(check_id, current_user)
        from backend import export as _export
        from backend.gap_finder import find_gaps
        refs = _export._as_list(check.get("results")) or _export._as_list(check.get("references"))
        result = await asyncio.to_thread(find_gaps, refs)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error finding gaps for {check_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/check/{check_id}/badge.svg")
async def get_check_badge(check_id: int, current_user: UserInfo = Depends(require_user)):
    """A self-contained citation-health SVG badge (embeddable in reports/READMEs)."""
    try:
        # Team-aware read (R26): the badge mirrors the shared-check health score.
        check = await _get_accessible_check_or_404(check_id, current_user)
        from backend import export as _export
        m = _export._model(check, corrections=False, sections=set(_export.ALL_SECTIONS))
        h = m["health"]
        svg = _export.render_badge_svg(h.get("score"), h.get("grade", "n/a"), h.get("color", "#6b7280"))
        return Response(content=svg, media_type="image/svg+xml",
                        headers={"Cache-Control": "no-cache"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rendering badge for {check_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _export_filename(title: str, check_id: int, ext: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", title or "")[:80].strip("-") or f"refchecker-{check_id}"
    return f"{safe}.{ext}"


def _parse_summary_param(summary: Optional[str]) -> Optional[Dict[str, Any]]:
    """Decode the FE's canonical ``buildReferenceSummary`` result from a query
    param (URL-encoded JSON). R48: when the FE passes this through, the export's
    headline counts + citation health are rendered IDENTICAL to the in-app
    Summary badge / report card. Returns None for absent/garbage input so the
    server-side computation is used as the fallback — never a 500."""
    if not summary:
        return None
    try:
        data = json.loads(summary)
        return data if isinstance(data, dict) else None
    except Exception:
        logger.debug("export: ignoring unparseable summary param")
        return None


@app.get("/api/export/{check_id}/file")
async def export_check_file(check_id: int, fmt: str = "html", corrections: bool = False,
                            include: Optional[str] = None, download: bool = True,
                            summary: Optional[str] = None,
                            current_user: UserInfo = Depends(require_user)):
    """Multi-format export of one check: html | md | pdf | docx.

    Query params drive the share-dialog controls:
      * fmt          — output format.
      * corrections  — include the stored corrected-reference suggestions.
      * include      — comma list of sections to keep (summary,ai,issues,references).
      * download     — attach a Content-Disposition filename.
      * summary      — (R48) URL-encoded JSON of the FE's canonical
                       buildReferenceSummary so the exported counts + citation
                       health match the in-app Summary badge / report card
                       exactly; falls back to server-side counts when absent.
    """
    try:
        # Team-aware read (R26): a team member can export a shared check, matching
        # the batch export path and the shared-check detail view (renders only the
        # already-shared references/verdicts).
        check = await _get_accessible_check_or_404(check_id, current_user)
        from backend import export as _export
        canonical_summary = _parse_summary_param(summary)
        try:
            content, media_type, ext = _export.render_export(
                check, fmt, corrections=corrections, include=include,
                summary=canonical_summary)
        except _export.PdfEngineUnavailableError as e:
            raise HTTPException(status_code=501, detail=str(e))
        title = check.get("paper_title") or check.get("custom_label") or f"refchecker-{check_id}"
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{_export_filename(title, check_id, ext)}"'
        return Response(content=content, media_type=media_type, headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        # Don't leak the raw exception string to the client — log it server-side
        # and return a stable, generic detail with the format that failed.
        logger.error(f"Error exporting check {check_id} as {fmt}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not export this check as {fmt}.")


@app.get("/api/export/batch/{batch_id}/file")
async def export_batch_file(batch_id: str, fmt: str = "html", corrections: bool = False,
                            include: Optional[str] = None, download: bool = True,
                            current_user: UserInfo = Depends(require_user)):
    """Multi-format batch report: one-page overview + each paper separately."""
    try:
        # Access already gated by team membership here, so per-check fetches
        # are batch-scoped (not re-scoped to the requester) — a team member
        # exporting an owner's shared batch needs the owner's check rows (R26).
        summary, rows = await _get_accessible_batch_or_404(batch_id, current_user)
        checks: list[dict] = []
        for row in rows:
            cid = row.get("id") or row.get("check_id")
            if cid is None:
                continue
            full = await db.get_check_by_id(int(cid), user_id=None)
            if full:
                checks.append(full)
        if not checks:
            raise HTTPException(status_code=404, detail="No completed checks in this batch")
        label = summary.get("batch_label") or f"Batch {batch_id[:8]}"
        from backend import export as _export
        try:
            content, media_type, ext = _export.render_batch_export(
                checks, fmt, corrections=corrections, include=include, label=label)
        except _export.PdfEngineUnavailableError as e:
            raise HTTPException(status_code=501, detail=str(e))
        headers = {}
        if download:
            safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label)[:80].strip("-") or "batch-report"
            headers["Content-Disposition"] = f'attachment; filename="{safe}.{ext}"'
        return Response(content=content, media_type=media_type, headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting batch {batch_id} as {fmt}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not export this batch report.")


@app.post("/api/export/{check_id}/publish")
async def publish_check(check_id: int, req: _PublishRequest,
                        current_user: UserInfo = Depends(require_user)):
    """Publish the HTML export to a web host and return a shareable URL.

    Pluggable by adapter. The GitHub-Gist adapter needs a user-supplied token
    (gist scope) and yields an htmlpreview.github.io link that renders the
    standalone HTML. No credentials are persisted server-side here — the token
    is used for this single request only.
    """
    # Guard the render: serialize_check_to_html (or resolving the check) can
    # raise on a drifted/odd-shaped row, and this call used to sit OUTSIDE the
    # per-adapter try/except — so any failure surfaced as a raw, detail-leaking
    # 500 for EVERY share type. Wrap it into a stable, generic 500.
    try:
        title, html_str = await _render_check_html(check_id, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"publish_check render failed for {check_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not render this check for sharing.")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", title)[:80].strip("-") or f"refchecker-{check_id}"
    import httpx

    # Quick link: zero-config anonymous host (no domain, no token). The host
    # (tmpfiles.org) rejects HTML uploads (anti-phishing), so we upload the PDF
    # report instead — which renders/downloads for anyone with the URL and is
    # ephemeral + public (surfaced as such in the UI). No credentials involved.
    if req.adapter == "quick_link":
        try:
            user_id = get_user_id_filter(current_user)
            check = await db.get_check_by_id(check_id, user_id=user_id)
            if not check:
                raise HTTPException(status_code=404, detail="Check not found")
            from backend import export as _export
            try:
                pdf_bytes = await asyncio.to_thread(_export.render_check_to_pdf, check)
            except _export.PdfEngineUnavailableError as e:
                # No PDF engine in this bundle: quick-link needs a PDF, so tell
                # the user to use Publish-to-web or download HTML/MD instead.
                raise HTTPException(status_code=501, detail=str(e))
            files = {"file": (f"{safe}.pdf", pdf_bytes, "application/pdf")}
            async with httpx.AsyncClient() as client:
                r = await client.post("https://tmpfiles.org/api/v1/upload", files=files, timeout=45.0)
            if r.status_code not in (200, 201):
                raise HTTPException(status_code=502, detail=f"Quick-link host unavailable (HTTP {r.status_code}). Try 'Publish to web', or download the report.")
            url = ((r.json() or {}).get("data") or {}).get("url")
            if not url:
                raise HTTPException(status_code=502, detail="Quick-link host did not return a URL. Try 'Publish to web'.")
            # tmpfiles serves the raw file at /dl/ ; rewrite so the PDF opens directly.
            view = url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1) if "/dl/" not in url else url
            return {"url": view, "page_url": url, "ephemeral": True, "adapter": "quick_link", "format": "pdf"}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"quick_link publish failed: {e}", exc_info=True)
            raise HTTPException(status_code=502, detail="Quick-link failed. Try 'Publish to web', or download the report.")

    if req.adapter != "github_gist":
        raise HTTPException(status_code=400, detail=f"Unknown publish adapter: {req.adapter}")
    if not req.token:
        raise HTTPException(status_code=400, detail="A GitHub token (gist scope) is required.")
    payload = {
        "description": f"RefChecker report — {title}",
        "public": bool(req.public),
        "files": {f"{safe}.html": {"content": html_str}},
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.github.com/gists",
                json=payload,
                headers={"Authorization": f"Bearer {req.token}",
                         "Accept": "application/vnd.github+json"},
                timeout=20.0,
            )
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"GitHub gist publish failed ({r.status_code}).")
        gist = r.json()
        raw_url = next((f.get("raw_url") for f in (gist.get("files") or {}).values() if f.get("raw_url")), None)
        # htmlpreview renders the raw HTML in the browser.
        preview = f"https://htmlpreview.github.io/?{raw_url}" if raw_url else gist.get("html_url")
        return {"url": preview, "gist_url": gist.get("html_url"), "raw_url": raw_url}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"publish_check failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Publish to web failed. Check your GitHub token, or download the report.")


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
        force_pdf_thumbnail_regen = False

        # Check if we already have a cached thumbnail path
        thumbnail_path = check.get('thumbnail_path')
        if thumbnail_path and os.path.exists(thumbnail_path):
            if is_direct_pdf_url and is_probably_placeholder_thumbnail(thumbnail_path):
                logger.info(f"Regenerating placeholder PDF thumbnail for check {check_id}: {thumbnail_path}")
                force_pdf_thumbnail_regen = True
            else:
                return FileResponse(
                    thumbnail_path,
                    media_type="image/png",
                    headers=_private_artifact_headers(),
                )

        # Stale thumbnail path — clear it from DB so we regenerate cleanly
        if thumbnail_path:
            logger.info(f"Thumbnail file missing for check {check_id}, regenerating: {thumbnail_path}")
            await db.update_check_thumbnail(check_id, "")
        
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
                        source_identifier=f"{paper_source}#pdf-placeholder",
                        cache_dir=cache_dir,
                    )
                    pdf_path = None
            
            if pdf_path and os.path.exists(pdf_path):
                thumbnail_path = await generate_pdf_thumbnail_async(
                    pdf_path,
                    source_identifier=paper_source,
                    cache_dir=cache_dir,
                    force=force_pdf_thumbnail_regen,
                )
            else:
                thumbnail_path = await get_text_thumbnail_async(
                    check_id,
                    "PDF",
                    source_identifier=f"{paper_source}#pdf-placeholder",
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


class _LocateTarget(BaseModel):
    text: str
    span_index: Optional[int] = None
    span_type: Optional[str] = "ai"   # 'ai' | 'citation'
    band: Optional[str] = None
    reason: Optional[str] = None
    model_score: Optional[float] = None


class _LocateRequest(BaseModel):
    targets: List[_LocateTarget] = []


@app.post("/api/preview/{check_id}/locate")
async def locate_preview_spans(
    check_id: int,
    req: _LocateRequest,
    current_user: UserInfo = Depends(require_user),
):
    """Locate target texts (AI-flagged passages / citation-context sentences)
    inside this check's source PDF and return their page + normalized rects so
    the frontend can highlight them ON the native page image. Returns
    found=False per target that can't be located (never a fabricated position)."""
    check = await _get_owned_check_or_404(check_id, current_user)
    cache_dir = await _get_configured_cache_dir()
    pdf_path = await _resolve_pdf_path_for_check(check, cache_dir)
    if not pdf_path:
        return {"available": False, "results": []}
    targets = [t.model_dump() for t in (req.targets or [])]
    if not targets:
        return {"available": True, "results": []}
    from backend.thumbnail import locate_text_spans_in_pdf
    results = await asyncio.to_thread(locate_text_spans_in_pdf, pdf_path, targets)
    return {"available": True, "results": results}


@app.get("/api/preview/{check_id}/annotated-pdf")
async def get_annotated_pdf(
    check_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """Return the source PDF with the AI-flagged passages highlighted as real
    PDF annotations (PyMuPDF) — a downloadable native-highlighted artifact."""
    check = await _get_owned_check_or_404(check_id, current_user)
    cache_dir = await _get_configured_cache_dir()
    pdf_path = await _resolve_pdf_path_for_check(check, cache_dir)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="No PDF source for this check")
    ai = check.get("ai_detection") or {}
    spans = ai.get("spans") if isinstance(ai, dict) else None
    targets = [
        {"text": s.get("quote") or "", "band": ai.get("band"), "model_score": s.get("model_score")}
        for s in (spans or []) if isinstance(s, dict) and s.get("quote")
    ]
    if not targets:
        raise HTTPException(status_code=404, detail="No flagged passages to annotate")
    out_path = await asyncio.to_thread(_annotate_pdf_highlights, pdf_path, targets, str(cache_dir or ""), check_id)
    if not out_path or not os.path.exists(out_path):
        raise HTTPException(status_code=500, detail="Could not annotate PDF")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (check.get("paper_title") or f"refchecker-{check_id}"))[:80].strip("-")
    return FileResponse(out_path, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{safe}-highlighted.pdf"'})


def _annotate_pdf_highlights(pdf_path, targets, cache_dir, check_id):
    """Add real PyMuPDF highlight annotations on the located target rects."""
    try:
        import fitz
        from backend.thumbnail import locate_text_spans_in_pdf
        located = locate_text_spans_in_pdf(pdf_path, targets)
        doc = fitz.open(pdf_path)
        band_rgb = {"high": (0.96, 0.45, 0.45), "medium": (0.98, 0.75, 0.18), "low": (0.55, 0.86, 0.6)}
        added = 0
        for r in located:
            if not r.get("found"):
                continue
            page = doc.load_page(r["page"])
            pw, ph = float(page.rect.width), float(page.rect.height)
            color = band_rgb.get((r.get("band") or "").lower(), (0.98, 0.75, 0.18))
            for nx0, ny0, nx1, ny1 in r["rects"]:
                rect = fitz.Rect(nx0 * pw, ny0 * ph, nx1 * pw, ny1 * ph)
                annot = page.add_highlight_annot(rect)
                try:
                    annot.set_colors(stroke=color)
                    annot.update()
                except Exception:
                    pass
                added += 1
        if not added:
            doc.close()
            return None
        out_dir = os.path.join(cache_dir or os.path.dirname(pdf_path), "annotated")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{check_id}-highlighted.pdf")
        doc.save(out_path, garbage=3, deflate=True)
        doc.close()
        return out_path
    except Exception as e:
        logger.warning("PDF annotation failed: %s", e)
        return None


def _correction_targets_for_check(check: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per flagged reference that carries a verified ``corrected_reference``, build
    a locate target whose ``text`` is the ORIGINAL cited line (so it can be found
    in the PDF) and whose ``corrected`` is the verified should-be line.

    Honesty contract: a target is produced ONLY when a real ``corrected_reference``
    exists AND it actually differs from the cited line — never a fabricated
    correction, never a no-op strikeout. Returns [] when nothing should change."""
    from backend import export as _export
    refs = _export._as_list(check.get("results")) or _export._as_list(check.get("references"))
    targets: List[Dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("corrected_reference"), dict):
            continue
        corrected = _export._corrected_str(ref)
        if not corrected:
            continue
        cited = _export._cited_str(ref)
        if not cited or cited.strip() == corrected.strip():
            # No baseline to strike, or an identical "correction" — skip (no
            # fabricated annotation).
            continue
        # Locate the cited TITLE in the PDF (the most reliably present anchor),
        # but carry the full corrected line as the inserted note.
        anchor = (ref.get("title") or cited).strip()
        if len(anchor) < 8:
            anchor = cited
        targets.append({
            "text": anchor,
            "ref_id": ref.get("index") or ref.get("ref_num"),
            "cited": cited,
            "corrected": corrected,
        })
    return targets


def _annotate_pdf_corrections(pdf_path, targets, marker_shifts, cache_dir, check_id):
    """R19: render the tracked was→should-be changes as REAL PDF annotations.

    For each correction target, locate the cited text via
    ``locate_text_spans_in_pdf`` (the same locator the highlight path uses),
    strike it out (``page.add_strikeout_annot``) and attach a text note
    (``page.add_text_annot``) carrying the verified corrected line. For inline
    renumber, each ``marker_shifts`` row's OLD marker (e.g. ``[9]``) is located on
    its page and annotated with its NEW form (e.g. ``[10]``).

    Never fabricates a position: a target/marker that can't be located is simply
    skipped. Returns the annotated PDF path, or None when nothing was annotated."""
    try:
        import fitz
        from backend.thumbnail import locate_text_spans_in_pdf
        added = 0
        doc = fitz.open(pdf_path)
        try:
            located = locate_text_spans_in_pdf(pdf_path, targets) if targets else []
            by_index = {i: t for i, t in enumerate(targets)}
            for i, r in enumerate(located):
                if not r.get("found"):
                    continue
                t = by_index.get(i, {})
                corrected = (t.get("corrected") or "").strip()
                page = doc.load_page(r["page"])
                pw, ph = float(page.rect.width), float(page.rect.height)
                note_pt = None
                for nx0, ny0, nx1, ny1 in r["rects"]:
                    rect = fitz.Rect(nx0 * pw, ny0 * ph, nx1 * pw, ny1 * ph)
                    try:
                        page.add_strikeout_annot(rect)
                    except Exception:
                        pass
                    if note_pt is None:
                        note_pt = fitz.Point(rect.x1, rect.y0)
                    added += 1
                # Attach the corrected line as a sticky text note anchored at the
                # end of the struck text (the should-be side of the change).
                if corrected and note_pt is not None:
                    try:
                        annot = page.add_text_annot(note_pt, f"Should be: {corrected}")
                        annot.set_info(title="RefChecker correction")
                        annot.update()
                    except Exception:
                        pass
            # Inline renumber: annotate each OLD marker with its NEW form.
            for sm in (marker_shifts or []):
                if not isinstance(sm, dict):
                    continue
                old_m = (sm.get("marker") or "").strip()
                new_m = (sm.get("new_marker") or "").strip()
                if not old_m or not new_m or old_m == new_m:
                    continue
                for page in doc:
                    try:
                        hits = page.search_for(old_m)
                    except Exception:
                        hits = []
                    if not hits:
                        continue
                    rect = hits[0]
                    try:
                        page.add_strikeout_annot(rect)
                        annot = page.add_text_annot(
                            fitz.Point(rect.x1, rect.y0), f"Renumber: {old_m} -> {new_m}")
                        annot.set_info(title="RefChecker renumber")
                        annot.update()
                        added += 1
                    except Exception:
                        pass
                    break  # annotate the first occurrence only (the marker's offset)
            if not added:
                return None
            out_dir = os.path.join(cache_dir or os.path.dirname(pdf_path), "annotated")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{check_id}-corrections.pdf")
            doc.save(out_path, garbage=3, deflate=True)
            return out_path
        finally:
            doc.close()
    except Exception as e:
        logger.warning("PDF correction annotation failed: %s", e)
        return None


@app.get("/api/preview/{check_id}/corrections-annotated-pdf")
async def get_corrections_annotated_pdf(
    check_id: int,
    current_user: UserInfo = Depends(require_user),
):
    """R19 (G2): return the source PDF with the tracked was→should-be corrections
    rendered as REAL PDF annotations — each corrected reference's cited text is
    struck through and a note carries the verified corrected line; inline
    renumber markers are annotated with their new number.

    Returns a clean 404 when the source isn't a PDF or there are no real
    corrections to render (never a blank/fabricated artifact)."""
    check = await _get_owned_check_or_404(check_id, current_user)
    cache_dir = await _get_configured_cache_dir()
    pdf_path = await _resolve_pdf_path_for_check(check, cache_dir)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="No PDF source for this check")
    targets = _correction_targets_for_check(check)

    # Inline-renumber markers to annotate (only when the renumber preview did not
    # abstain). Best-effort: a failure here must not block the strikeout path.
    marker_shifts: List[Dict[str, Any]] = []
    try:
        text = await _extract_paper_text_for_check(check_id, check)
        if text:
            from backend.inline_citation_checker import renumber_preview
            from backend import export as _export
            refs = _export._as_list(check.get("results")) or _export._as_list(check.get("references"))
            report = await asyncio.to_thread(renumber_preview, text, refs, None)
            if isinstance(report, dict) and not report.get("abstained"):
                marker_shifts = report.get("shifted_markers") or []
    except Exception as e:
        logger.debug("renumber preview for corrections-annotated-pdf failed: %s", e)

    if not targets and not marker_shifts:
        raise HTTPException(status_code=404, detail="No corrections to annotate")

    out_path = await asyncio.to_thread(
        _annotate_pdf_corrections, pdf_path, targets, marker_shifts, str(cache_dir or ""), check_id)
    if not out_path or not os.path.exists(out_path):
        # Nothing could be located on the page -> honest 404, not a 500.
        raise HTTPException(status_code=404, detail="No corrections could be located in the PDF")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (check.get("paper_title") or f"refchecker-{check_id}"))[:80].strip("-")
    return FileResponse(out_path, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{safe}-corrections.pdf"'})


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


def _read_cached_paper_text(path: str) -> str:
    """Read a previously-extracted paper-text blob (blocking; call via to_thread)."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except Exception:
        return ""


def _write_cached_paper_text(path: str, text: str) -> None:
    """Atomically persist extracted paper text (blocking; call via to_thread)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        # Best-effort cache — a write failure must never break the response.
        pass


@app.get("/api/paper-pdf/{check_id}")
async def get_paper_pdf(check_id: int, current_user: UserInfo = Depends(require_user)):
    """Serve the original source PDF for a check (uploaded file or the PDF cached
    during the check), so the frontend can render it natively with PDF.js.

    Returns 404 when the source isn't a PDF (pasted text, .bib/.tex) or the cached
    file was cleared — the viewer then falls back to the extracted-text view.
    Real-data only: never synthesises a PDF.
    """
    check = await _get_owned_check_or_404(check_id, current_user)
    source_type = check.get('source_type', '') or ''
    paper_source = check.get('paper_source', '') or ''

    pdf_path = None
    # 1) Uploaded local PDF.
    if (source_type == 'file' and paper_source
            and paper_source.lower().endswith('.pdf') and os.path.exists(paper_source)):
        pdf_path = paper_source
    # 2) URL / DOI input — reuse the PDF cached during the check (same artifacts
    #    the text extractor reads, so availability matches the text view).
    if not pdf_path and paper_source:
        try:
            from refchecker.utils.cache_utils import get_cached_artifact_path
            cache_dir = await _get_configured_cache_dir()
            if cache_dir:
                for artifact in ("ai_body.pdf", "paper.pdf"):
                    p = get_cached_artifact_path(str(cache_dir), paper_source, artifact)
                    if p and os.path.exists(p) and os.path.getsize(p) > 0:
                        pdf_path = p
                        break
        except Exception as _e:  # noqa: BLE001
            logger.debug("paper-pdf cache lookup failed: %s", _e)

    if pdf_path:
        return FileResponse(pdf_path, media_type="application/pdf", headers=_private_artifact_headers())

    # 2b) R02 — uploaded non-PDF document (.docx / .html / .htm): convert the
    #     real document text to a self-contained PDF so the SAME native pdf.js
    #     viewer renders it (highlights + back-links included). Cached as
    #     {check_id}.gen.pdf. Honesty: only the document's own text is rendered.
    if (source_type == 'file' and paper_source and os.path.exists(paper_source)
            and paper_source.lower().endswith(('.docx', '.html', '.htm'))):
        try:
            cache_dir = await _get_configured_cache_dir()
            if cache_dir:
                text_dir = os.path.join(str(cache_dir), "paper_text")
                gen_path = os.path.join(text_dir, f"{check_id}.gen.pdf")
                if os.path.exists(gen_path) and os.path.getsize(gen_path) > 0:
                    return FileResponse(gen_path, media_type="application/pdf", headers=_private_artifact_headers())
                from backend.pdf_convert import convert_to_pdf
                title = check.get('title') or check.get('paper_title') or None
                os.makedirs(text_dir, exist_ok=True)
                await asyncio.to_thread(convert_to_pdf, paper_source, gen_path, title)
                if os.path.exists(gen_path) and os.path.getsize(gen_path) > 0:
                    return FileResponse(gen_path, media_type="application/pdf", headers=_private_artifact_headers())
        except Exception as _e:  # noqa: BLE001
            logger.debug("paper-pdf docx/html→PDF conversion failed: %s", _e)
            # fall through to the extracted-text render below

    # 3) No original PDF (pasted text / .tex / .bib / .txt / .md) — render the
    #    extracted body text into a clean, self-contained PDF so the SAME native
    #    pdf.js viewer (with highlights + back-links) is used for every source.
    #    Cached as {check_id}.gen.pdf. Real-data only: the PDF is exactly the
    #    extracted text. Any failure falls through to 404 → the text view.
    try:
        cache_dir = await _get_configured_cache_dir()
        if cache_dir:
            text_dir = os.path.join(str(cache_dir), "paper_text")
            gen_path = os.path.join(text_dir, f"{check_id}.gen.pdf")
            if os.path.exists(gen_path) and os.path.getsize(gen_path) > 0:
                return FileResponse(gen_path, media_type="application/pdf", headers=_private_artifact_headers())
            # Prefer the already-cached extracted text; else extract on demand.
            text = ""
            txt_path = os.path.join(text_dir, f"{check_id}.txt")
            if os.path.exists(txt_path) and os.path.getsize(txt_path) > 0:
                text = await asyncio.to_thread(_read_cached_paper_text, txt_path)
            if not (text or "").strip():
                text = await _extract_paper_text_for_check(check_id, check)
            if (text or "").strip():
                from backend.pdf_convert import text_to_pdf
                title = check.get('title') or check.get('paper_title') or None
                await asyncio.to_thread(text_to_pdf, text, gen_path, title)
                return FileResponse(gen_path, media_type="application/pdf", headers=_private_artifact_headers())
    except Exception as _e:  # noqa: BLE001
        logger.debug("paper-pdf text→PDF conversion failed: %s", _e)

    raise HTTPException(status_code=404, detail="No source PDF available for this check")


@app.get("/api/paper-text/{check_id}")
async def get_paper_text(check_id: int, current_user: UserInfo = Depends(require_user)):
    """Return the extracted body text of a check's source document.

    Powers the "view in document" highlighter: the frontend renders this text
    and marks the AI-detection flagged passages / citation contexts in place.
    Works for uploaded PDFs/text files AND URL/DOI inputs (via the PDF cached
    during the check). Never throws on a missing source — returns available=False.
    """
    try:
        check = await _get_owned_check_or_404(check_id, current_user)
        source_type = check.get('source_type', '') or ''
        paper_source = check.get('paper_source', '') or ''
        text = ""
        fmt = "text"

        # ── Per-check extracted-text cache ────────────────────────────────
        # PDF text extraction is CPU-bound (5-30s on a big paper) and was
        # re-run on EVERY "View doc" / "View flagged" open — the source of
        # the "extracting document text…" lag. The extracted body never
        # changes for a given check, so memoise it to disk keyed by
        # check_id. First open pays the extraction cost; every later open
        # is an instant file read.
        _text_cache_path = None
        try:
            _cache_dir = await _get_configured_cache_dir()
            if _cache_dir:
                _text_cache_dir = os.path.join(str(_cache_dir), "paper_text")
                _text_cache_path = os.path.join(_text_cache_dir, f"{check_id}.txt")
                if os.path.exists(_text_cache_path) and os.path.getsize(_text_cache_path) > 0:
                    cached = await asyncio.to_thread(_read_cached_paper_text, _text_cache_path)
                    if cached and cached.strip():
                        MAX = 600_000
                        return {
                            "text": cached[:MAX],
                            "format": "cached",
                            "word_count": len(cached.split()),
                            "truncated": len(cached) > MAX,
                            "available": True,
                        }
        except Exception as _e:
            logger.debug("paper-text cache read skipped: %s", _e)

        def _read_textfile(path):
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                    return fh.read()
            except Exception:
                return ""

        from backend.refchecker_wrapper import _extract_pdf_text_cli_style

        # 1) Uploaded local file (pdf / txt / bib / tex).
        if source_type == 'file' and paper_source and os.path.exists(paper_source):
            if paper_source.lower().endswith('.pdf'):
                text = await asyncio.to_thread(_extract_pdf_text_cli_style, paper_source, None)
                fmt = "pdf"
            else:
                text = _read_textfile(paper_source)

        # 1b) Pasted text / .bib / .bbl / .tex (source_type == 'text'). The body
        #     is saved to a temp file (read it) — or, for an inline paste, IS the
        #     stored string. Without this the DocumentViewer fell through to the
        #     cached-PDF lookup below (no PDF exists for a structured/text
        #     source) and showed "the original document text isn't available".
        if not (text or "").strip() and source_type == 'text' and paper_source:
            if os.path.exists(paper_source):
                if paper_source.lower().endswith('.pdf'):
                    text = await asyncio.to_thread(_extract_pdf_text_cli_style, paper_source, None)
                    fmt = "pdf"
                else:
                    text = _read_textfile(paper_source)
            elif len(paper_source) > 200:
                # The pasted content was stored inline rather than as a file path.
                text = paper_source

        # 2) URL / DOI input — reuse the PDF cached during the check.
        if not (text or "").strip() and paper_source:
            try:
                from refchecker.utils.cache_utils import get_cached_artifact_path
                cache_dir = await _get_configured_cache_dir()
                if cache_dir:
                    for artifact in ("ai_body.pdf", "paper.pdf"):
                        p = get_cached_artifact_path(str(cache_dir), paper_source, artifact)
                        if p and os.path.exists(p) and os.path.getsize(p) > 0:
                            text = await asyncio.to_thread(_extract_pdf_text_cli_style, p, None)
                            fmt = "pdf"
                            break
            except Exception as _e:
                logger.debug("paper-text cache lookup failed: %s", _e)

        text = text or ""
        # Persist the freshly-extracted text so the next open is instant.
        if text.strip() and _text_cache_path:
            try:
                await asyncio.to_thread(_write_cached_paper_text, _text_cache_path, text)
            except Exception as _e:
                logger.debug("paper-text cache write skipped: %s", _e)
        MAX = 600_000  # cap so a whole book can't bloat the response
        return {
            "text": text[:MAX],
            "format": fmt,
            "word_count": len(text.split()),
            "truncated": len(text) > MAX,
            "available": bool(text.strip()),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting paper text: {e}", exc_info=True)
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
                # AI-generated-text detection is intentionally NOT replayed on
                # recheck: it is a live client-side preference (useAiDetectionStore),
                # never persisted per-check, so there is nothing to restore. A
                # recheck re-verifies citations only; run a fresh check to get a
                # new AI-detection result.
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
                "paperclip_key_present": bool(request.paperclip_api_key),
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
                    ai_detection_enabled=request.ai_detection_enabled,
                    ai_detection_backend=request.ai_detection_backend,
                    ai_detection_api_key=request.ai_detection_api_key,
                    ai_detection_consent=request.ai_detection_consent,
                    ai_detection_service=request.ai_detection_service,
                    ai_detection_detectors=getattr(request, 'ai_detection_detectors', None),
                    detection_mode=getattr(request, 'detection_mode', 'both'),
                    paperclip_api_key=request.paperclip_api_key,
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
    llm_config_id: Optional[LLMConfigId] = Form(None),
    llm_provider: str = Form("anthropic"),
    llm_model: Optional[str] = Form(None),
    hallucination_config_id: Optional[LLMConfigId] = Form(None),
    hallucination_provider: Optional[str] = Form(None),
    hallucination_model: Optional[str] = Form(None),
    use_llm: bool = Form(True),
    api_key: Optional[str] = Form(None),
    hallucination_api_key: Optional[str] = Form(None),
    semantic_scholar_api_key: Optional[str] = Form(None),
    paperclip_api_key: Optional[str] = Form(None),
    ai_detection_enabled: bool = Form(False),
    ai_detection_backend: str = Form("local"),
    ai_detection_api_key: Optional[str] = Form(None),
    ai_detection_consent: bool = Form(False),
    ai_detection_service: str = Form("pangram"),
    # R61: repeated form field — one value per chosen detector key. FastAPI
    # collects the repeats into a list; >1 routes through the compare path.
    ai_detection_detectors: Optional[List[str]] = Form(None),
    detection_mode: str = Form("both"),
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
        paperclip_api_key = _form_default_value(paperclip_api_key)
        ai_detection_enabled = _form_default_value(ai_detection_enabled)
        ai_detection_backend = _form_default_value(ai_detection_backend)
        ai_detection_api_key = _form_default_value(ai_detection_api_key)
        ai_detection_consent = _form_default_value(ai_detection_consent)
        ai_detection_service = _form_default_value(ai_detection_service)
        detection_mode = _form_default_value(detection_mode)

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
                "paperclip_key_present": bool(paperclip_api_key),
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
                    ai_detection_enabled=ai_detection_enabled,
                    ai_detection_backend=ai_detection_backend,
                    ai_detection_api_key=ai_detection_api_key,
                    ai_detection_consent=ai_detection_consent,
                    ai_detection_service=ai_detection_service,
                    ai_detection_detectors=ai_detection_detectors,
                    paperclip_api_key=paperclip_api_key,
                    detection_mode=detection_mode,
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
        summary, checks = await _get_accessible_batch_or_404(batch_id, current_user)
        
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
    summary, checks = await _get_accessible_batch_or_404(batch_id, current_user)
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
    """Cancel all active checks in a batch.

    v0.7.51: DB flip FIRST, then task.cancel() — previously the task
    cancellation could race the DB update. A child task might finish
    its current await between the cancel_event being set and the DB
    update, write its own status='completed' row, and end up
    NOT-cancelled. Reversing the order means any subsequent DB write
    from a still-running task hits a row that's already 'cancelled',
    so the task's status update becomes a no-op.
    """
    try:
        user_id = get_user_id_filter(current_user)
        await _get_owned_batch_or_404(batch_id, current_user)
        # Flip the DB first — covers queued/pending children that haven't
        # yet acquired a concurrency slot, and stops any running task's
        # next status write from racing past us.
        db_cancelled = await db.cancel_batch(batch_id, user_id=user_id)
        # Now interrupt every active task that belongs to this batch.
        cancelled_sessions = 0
        for session_id, meta in list(active_checks.items()):
            if meta.get("batch_id") == batch_id and (user_id is None or meta.get("user_id") == user_id):
                meta["cancel_event"].set()
                meta["task"].cancel()
                cancelled_sessions += 1
        
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
    """Update a batch's label and/or share it with a team (R26).

    Only the owner may mutate a batch, so this stays on the owner-scoped DB
    helpers. ``team_id`` semantics: ``None`` leaves the share unchanged; ``0``
    unshares; a positive id shares the whole batch with that team (the caller
    must be a member of it)."""
    try:
        user_id = get_user_id_filter(current_user)
        touched = False

        if update.batch_label is not None:
            label_ok = await db.update_batch_label(batch_id, update.batch_label, user_id=user_id)
            if not label_ok:
                raise HTTPException(status_code=404, detail="Batch not found")
            touched = True

        if update.team_id is not None:
            # Owner must belong to the team they're sharing with. user_id is None
            # in single-user mode, where there are no teams to share to.
            new_team_id: Optional[int] = update.team_id if update.team_id else None
            if new_team_id is not None:
                if user_id is None or not await db.is_team_member(new_team_id, current_user.id):
                    raise HTTPException(status_code=403, detail="You are not a member of that team")
            shared = await db.set_batch_team(batch_id, new_team_id, user_id=user_id)
            if shared == 0:
                raise HTTPException(status_code=404, detail="Batch not found")
            touched = True

        if not touched:
            raise HTTPException(status_code=400, detail="Nothing to update")

        # Keep the historical message so existing callers/tests stay green.
        return {"message": "Batch label updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating batch: {e}", exc_info=True)
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
        return _merge_env_llm_configs(configs)
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
        created = {
            "id": config_id,
            "name": config.name,
            "provider": config.provider,
            "model": config.model,
            "endpoint": config.endpoint,
            "is_default": False,
            "has_key": bool(store_key),
        }
        return _merge_env_llm_configs([created])[0]
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
            updated_config = next((c for c in _merge_env_llm_configs(updated) if c["id"] == config_id), None)
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
    config_id: LLMConfigId,
    current_user: UserInfo = Depends(require_user),
):
    """Set an LLM configuration as the default"""
    try:
        if _is_env_llm_config_id(config_id):
            if _env_llm_config_from_id(config_id):
                return {"message": "Environment config selected"}
            raise HTTPException(status_code=404, detail="Config not found")
        user_id = get_user_id_filter(current_user)
        success = await db.set_default_llm_config(int(config_id), user_id=user_id)
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


class UserPreferencesUpdate(BaseModel):
    citation_format: Optional[str] = None
    citation_style_options: Optional[Dict[str, Any]] = None


CITATION_FORMATS = {
    "bibtex",
    "plaintext",
    "apa",
    "mla",
    "chicago",
    "ieee",
    "vancouver",
    "bibitem",
}


async def _get_user_preferences_payload(user_id: int) -> Dict[str, Any]:
    citation_format = await db.get_user_preference(user_id, "citation_format")
    raw_style_options = await db.get_user_preference(user_id, "citation_style_options")
    style_options: Dict[str, Any] = {}
    if raw_style_options:
        try:
            parsed = json.loads(raw_style_options)
            if isinstance(parsed, dict):
                style_options = parsed
        except Exception:
            style_options = {}

    return {
        "citation_format": citation_format or "plaintext",
        "citation_style_options": style_options,
        "has_citation_format": citation_format is not None,
    }


@app.get("/api/user/preferences")
async def get_user_preferences(current_user: UserInfo = Depends(require_user)):
    """Get user-scoped UI preferences."""
    return await _get_user_preferences_payload(current_user.id)


@app.put("/api/user/preferences")
async def update_user_preferences(
    update: UserPreferencesUpdate,
    current_user: UserInfo = Depends(require_user),
):
    """Update user-scoped UI preferences."""
    if update.citation_format is not None:
        citation_format = update.citation_format.strip()
        if not (
            citation_format in CITATION_FORMATS
            or citation_format.startswith("custom:")
        ):
            raise HTTPException(status_code=400, detail="Unknown citation format")
        await db.set_user_preference(current_user.id, "citation_format", citation_format)

    if update.citation_style_options is not None:
        await db.set_user_preference(
            current_user.id,
            "citation_style_options",
            json.dumps(update.citation_style_options),
        )

    return await _get_user_preferences_payload(current_user.id)


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

    # R17 (G3) — reject duplicates before inserting. Normalize the incoming
    # identity (DOI via the same `normalize_doi` the retraction/gap-finder
    # paths use; arXiv id and title lowercased) and compare it against every
    # existing reference's cited AND verified identity. A match returns 409
    # so the UI can say "already reference [N]" instead of silently creating
    # a duplicate row that pollutes the renumbering map and the export list.
    from backend.retraction import normalize_doi as _normalize_doi

    def _norm_arxiv(v: Any) -> Optional[str]:
        s = (str(v).strip().lower() if v else "")
        # Strip a leading "arxiv:" scheme and any version suffix (v1/v2…)
        # so "arXiv:2106.01345v2" and "2106.01345" compare equal.
        if s.startswith("arxiv:"):
            s = s[len("arxiv:"):]
        s = re.sub(r"v\d+$", "", s)
        return s or None

    def _norm_title(v: Any) -> Optional[str]:
        # Collapse whitespace + lowercase so trivial spacing/case differences
        # don't slip a duplicate through.
        s = " ".join(str(v).split()).strip().lower() if v else ""
        return s or None

    incoming_doi = _normalize_doi(payload.doi)
    incoming_arxiv = _norm_arxiv(payload.arxiv_id)
    incoming_title = _norm_title(payload.title)
    if incoming_doi or incoming_arxiv or incoming_title:
        for r in refs:
            if not isinstance(r, dict):
                continue
            existing_doi = _normalize_doi(r.get("doi") or r.get("verified_doi"))
            existing_arxiv = _norm_arxiv(r.get("arxiv_id") or r.get("verified_arxiv_id"))
            existing_title = _norm_title(r.get("title") or r.get("verified_title"))
            is_dup = (
                (incoming_doi and existing_doi and incoming_doi == existing_doi)
                or (incoming_arxiv and existing_arxiv and incoming_arxiv == existing_arxiv)
                or (incoming_title and existing_title and incoming_title == existing_title)
            )
            if is_dup:
                # Return the duplicate envelope at the top level (not wrapped
                # in `detail`) so the FE can read `data.duplicate` /
                # `data.existing_index` directly and render "already reference
                # [N]". A bare HTTPException would bury it under `detail`.
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=409,
                    content={
                        "duplicate": True,
                        "existing_index": r.get("index"),
                        "message": f"Already reference [{r.get('index')}] in this check.",
                    },
                )

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
    # Snapshot the existing printed indices BEFORE any renumber, so we can
    # return a real before/after renumber map (drives the "document changes"
    # preview in the UI — no PDF is mutated; this is the list-level diff only).
    before_index = {r.get("id"): r.get("index") for r in refs if r.get("id") is not None}
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
    # Additive renumber map: which existing references changed printed index.
    renumbering = []
    for r in refs:
        rid = r.get("id")
        if rid is None or rid == new_ref["id"]:
            continue
        old = before_index.get(rid)
        if old is not None and old != r.get("index"):
            renumbering.append({
                "id": rid,
                "title": (str(r.get("title") or "")[:80]),
                "old_index": old,
                "new_index": r.get("index"),
            })
    return {
        "reference": new_ref,
        "total_refs": len(refs),
        "inserted_index": new_ref["index"],
        "renumbering": renumbering,
    }


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
    # v0.7.46: use a lightweight existence/ownership check instead of
    # `get_check_references` which pulled the entire results_json blob
    # — that was timing out while the SQLite DB was busy with a giant
    # batch write. get_check_by_id only touches the row's columns
    # (still includes results_json but is at least a single PK lookup,
    # not a scan; and we don't actually need the JSON here).
    user_id = get_user_id_filter(current_user)
    try:
        owns = await asyncio.wait_for(
            db.get_check_by_id(check_id, user_id=user_id),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        # DB is busy — return empty usage rather than holding the
        # request and blocking the FE behind a slow ownership probe.
        return {
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "calls": 0, "by_flow": {}, "by_model": {},
        }
    if owns is None:
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
            from refchecker.utils.enrichment import backfill_enrichment, build_enrichment
            # Cross-source backfill (R21/R22) for the add-ref verify path:
            # backfill missing-only counts / abstract / tldr / funding by DOI
            # from OpenAlex / Crossref / S2 before projecting. Never overwrites
            # a real value, never fabricates, soft-fails, bounded.
            if isinstance(verified_data, dict):
                backfill_enrichment(verified_data, target)
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
                # Tag this call under the `suggest` flow so the $ badge's
                # per-flow breakdown attributes it correctly. The
                # FlowScope's thread-local doesn't cross asyncio.to_thread,
                # so set it INSIDE the worker, same pattern as
                # `_run_llm_similar` further down this file.
                _cid_for_suggest_alt = check_id
                def _run_suggest_alt_llm():
                    try:
                        from refchecker.llm import usage_tracker as _ut
                        if _cid_for_suggest_alt is not None:
                            _ut.set_current_check(str(_cid_for_suggest_alt))
                        with _ut.FlowScope("suggest"):
                            return provider._call_llm(prompt)
                    except Exception:
                        return provider._call_llm(prompt)
                try:
                    raw = await asyncio.to_thread(_run_suggest_alt_llm)
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
    # Discovery mode. Three CLEARLY-SCOPED, bibliography-overlap modes
    # backed by real OpenAlex data (backend/cites_refs.py):
    #   'references' — papers that SHARE REFERENCES with the source
    #                  (overlap in their bibliographies / referenced_works).
    #   'citations'  — papers that SHARE CITATIONS with the source
    #                  (co-cited works: things the source's citers also cite).
    #   'both'       — the union of the two.
    # Legacy aliases are mapped: 'cites_refs' -> 'both'. The historical
    # 'similar' co-citation pipeline (_find_similar_papers_impl) is still
    # reachable for backward compatibility but is no longer a public mode.
    mode: str = 'both'


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
        raw_mode = (req.mode or "both").strip().lower()
        # The historical Semantic-Scholar co-citation pipeline stays reachable
        # for backward compatibility, but the public modes are now the three
        # bibliography-overlap kinds (References / Citations / Both), all of
        # which run on real OpenAlex data via _cites_refs_papers_impl.
        if raw_mode == "similar":
            return await _find_similar_papers_impl(req, current_user)
        # 'references' | 'citations' | 'both' (+ legacy 'cites_refs' alias).
        return await _cites_refs_papers_impl(req)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("find_similar_papers crashed")
        return {
            "source_paper": req.paper_title,
            "candidates": [],
            "error": f"Similar Papers lookup failed: {e}",
        }


async def _cites_refs_papers_impl(req: _SimilarPapersRequest) -> Dict[str, Any]:
    """CLEAN SEPARATE path: papers that overlap the SOURCE paper's
    bibliography on real OpenAlex data. ``mode`` selects the overlap kind:

      * 'references' — papers that SHARE REFERENCES with the source
        (their bibliographies overlap the source's referenced_works).
      * 'citations'  — papers that SHARE CITATIONS with the source
        (co-cited works: what the source's citers also cite).
      * 'both'       — the union of the two.

    Legacy 'cites_refs' is mapped to 'both'. REAL OpenAlex data only;
    empty in -> empty out.
    """
    import httpx
    limit = max(1, min(20, int(req.limit or 5)))
    resolved_mode = _normalize_overlap_mode(req.mode)
    timeout = 12.0

    async with httpx.AsyncClient() as client:
        async def _fetch(url: str, params: Optional[dict] = None) -> Optional[dict]:
            try:
                r = await client.get(url, params=params, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
            except Exception as e:  # noqa: BLE001
                logger.debug("OpenAlex cites/refs fetch failed for %s: %s", url, e)
            return None

        result = await fetch_cites_and_refs(
            _fetch,
            _candidate_key,
            paper_id=req.paper_id,
            paper_title=req.paper_title,
            limit=limit,
            mode=resolved_mode,
        )

    candidates = _shape_cites_refs_candidates(result.get("candidates", []))
    # R20 — populate REAL verification status (pre_verified / was_verified /
    # verified_status) on each row so the existing SimilarPapersPanel chips
    # render true "verified / ? unconfirmed" state instead of always-null.
    # Reuses the same cache-lookup + active-verify discipline as the similar
    # path (db.lookup_verified_reference -> checker.verify_reference), bounded
    # by a semaphore. Real-data-gated: a candidate that can't be confirmed is
    # marked unverified, never synthesized as verified.
    await _verify_candidates_in_place(candidates)
    # Tally by relation: 'reference' = shared-references match,
    # 'citation' = shared-citations (co-cited) match.
    source_counts: Dict[str, int] = {}
    for c in candidates:
        rel = c.get("relation") or "openalex"
        source_counts[rel] = source_counts.get(rel, 0) + 1
    return {
        "source_paper": req.paper_title,
        "candidates": candidates,
        "source_counts": source_counts,
        "total_candidates": len(candidates),
        "mode": resolved_mode,
        "source_work": result.get("source_work"),
    }


def _shape_cites_refs_candidates(raw: list) -> list:
    """Project OpenAlex cites/refs candidates onto the same row shape the
    Similar-Papers UI already renders, tagging each with its relation."""
    out = []
    for c in raw:
        out.append({
            "paperId": None,
            "openalex_id": c.get("openalex_id"),
            "title": c.get("title"),
            "year": c.get("year"),
            "authors": c.get("authors") or [],
            "doi": c.get("doi"),
            "arxiv_id": c.get("arxiv_id"),
            "venue": None,
            "reason": None,
            "relation": c.get("relation"),  # 'reference' | 'citation'
            # Overlap count that earned this candidate a place: number of the
            # source's references it shares ('reference' rows), or number of
            # the source's citers that co-cite it ('citation' rows).
            "shared_with_source": c.get("shared_with_source") or 0,
            "shared_refs_count": 0,
            "shared_refs_pct": 0.0,
            "shared_refs_jaccard": 0.0,
            "candidate_ref_count": 0,
            "shared_refs_titles": [],
            # R08 — the ACTUAL works shared with the source paper (hydrated
            # real OpenAlex records), so the panel can show WHICH works are
            # shared, not just a count. For 'reference' rows these are the
            # shared reference works; for 'citation' rows, the co-citing
            # works. Real data only — empty when nothing resolved.
            "shared_works": c.get("shared_works") or [],
            "shared_works_titles": c.get("shared_works_titles") or [],
            "shared_overlap_count": (
                c.get("shared_overlap_count")
                if c.get("shared_overlap_count") is not None
                else (c.get("shared_with_source") or 0)
            ),
            "sources": ["openalex"],
            "via": "openalex",
            "semantic_scholar_url": None,
            "url": c.get("url"),
            "pre_verified": False,
            "was_verified": False,
            "verified_status": None,
            "times_seen": 0,
        })
    return out


def _build_similar_papers_checker():
    """Best-effort init of the hybrid reference checker used to actively
    verify candidate rows. Returns the checker or ``None`` if it can't load
    (no network deps available, import error, etc.) — callers degrade to
    cache-only verification. Mirrors the init in ``_find_similar_papers_impl``."""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
        return EnhancedHybridReferenceChecker(debug_mode=False)
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not init checker for cites/refs verification: %s", e)
        return None


async def _verify_candidates_in_place(candidates: list) -> None:
    """R20 — populate REAL verification status on shaped candidate rows.

    For each candidate row (already shaped by ``_shape_cites_refs_candidates``)
    this resolves a real verification status using the SAME discipline as the
    similar path's ``_enrich``:

      1. Look the candidate up in the global identity cache
         (``db.lookup_verified_reference``). A hit sets ``pre_verified`` /
         ``was_verified`` and carries the cached status + ``times_seen``.
      2. On a cache miss, actively verify via ``checker.verify_reference`` —
         bounded by a semaphore so we never fan out unboundedly — and mark
         ``verified`` only when a real database record is matched. No match
         -> ``unverified`` ("? unconfirmed" chip). An error -> ``unknown``.

    Mutates ``candidates`` in place. REAL-DATA-GATED: a row is only marked
    verified when a real source confirmed it — never synthesized. When there
    are no candidates, this is a no-op (no checker init, no network).
    """
    if not candidates:
        return

    checker = await asyncio.to_thread(_build_similar_papers_checker)
    sem = asyncio.Semaphore(5)

    async def _verify_one(row: dict) -> None:
        probe = {
            "doi": row.get("doi"),
            "arxiv_id": row.get("arxiv_id"),
            "title": row.get("title"),
            "year": row.get("year"),
        }
        cached = None
        try:
            cached = await db.lookup_verified_reference(probe)
        except Exception:
            cached = None

        if cached:
            row["pre_verified"] = True
            row["was_verified"] = True
            row["verified_status"] = (cached or {}).get("status") or "verified"
            row["times_seen"] = (cached or {}).get("times_seen") or 0
            return

        # Cache miss: actively verify if we have any identifier or title.
        if checker is not None and (row.get("doi") or row.get("arxiv_id") or row.get("title")):
            async with sem:
                try:
                    verified_data, _errors, url = await asyncio.to_thread(
                        checker.verify_reference,
                        {
                            "title": row.get("title"),
                            "authors": row.get("authors"),
                            "year": row.get("year"),
                            "doi": row.get("doi"),
                            "arxiv_id": row.get("arxiv_id"),
                            "venue": row.get("venue"),
                        },
                    )
                    if verified_data:
                        row["was_verified"] = True
                        row["verified_status"] = "verified"
                        if not row.get("doi") and verified_data.get("doi"):
                            row["doi"] = verified_data["doi"]
                        if not row.get("arxiv_id") and verified_data.get("arxiv_id"):
                            row["arxiv_id"] = verified_data["arxiv_id"]
                        if not row.get("url") and url:
                            row["url"] = url
                        try:
                            await db.upsert_verified_reference({
                                "doi": row.get("doi"),
                                "arxiv_id": row.get("arxiv_id"),
                                "title": row.get("title"),
                                "year": row.get("year"),
                                "status": "verified",
                                "verified_url": url,
                                "matched_db": (verified_data.get("source") if isinstance(verified_data, dict) else None),
                            })
                        except Exception:
                            pass
                    else:
                        # No record found — likely fake or just missing.
                        row["verified_status"] = "unverified"
                except Exception as e:  # noqa: BLE001
                    logger.debug("Active verification failed for cites/refs candidate: %s", e)
                    row["verified_status"] = "unknown"

    await asyncio.gather(*[_verify_one(c) for c in candidates])


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
                _cid_for_suggest = check_id
                def _run_llm_similar():
                    try:
                        from refchecker.llm import usage_tracker as _ut
                        # threading.local doesn't cross asyncio.to_thread.
                        # Without re-binding check_id inside the worker the
                        # suggest-flow cost lands in the "default" bucket and
                        # the $ badge silently under-counts.
                        if _cid_for_suggest is not None:
                            _ut.set_current_check(str(_cid_for_suggest))
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
    # When true (and the local model is installed) attach a per-reference
    # AI-generated-text band to each first-degree node so the graph's AI
    # ring renders on the bibliography itself, not just expanded nodes.
    ai_detection: bool = False


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

    want_ai = bool(getattr(req, "ai_detection", False))
    _node_fields = "paperId,citationCount,references.paperId"
    if want_ai:
        _node_fields += ",abstract"

    # Cap at 60 — beyond that S2 rate-limits hard and the graph is unreadable.
    refs = refs[:60]
    nodes_out = []
    paperid_to_local = {}  # S2 paperId -> our local ref id

    # Fetch every ref's S2 record CONCURRENTLY (bounded by a semaphore)
    # instead of one-at-a-time. The old sequential loop spent ~1s per ref
    # and, on a 60-ref bibliography under any network latency, sailed past
    # the frontend's 120s timeout ("timeout of 120000ms exceeded"). A
    # bounded fan-out keeps us polite to S2's per-IP rate limit (smaller
    # pool when we have no API key) while cutting wall-time roughly Nx.
    _graph_conc = 8 if api_key else 5
    _graph_sem = asyncio.Semaphore(_graph_conc)

    async with httpx.AsyncClient() as client:
        async def _fetch_ref(i, ref):
            local_id = str(ref.get("id") or ref.get("index") or f"ref-{i}")
            ident = s2_id_of(ref)
            paper = None
            references_list = []
            if ident:
                async with _graph_sem:
                    data = await _fetch(
                        client,
                        f"https://api.semanticscholar.org/graph/v1/paper/{ident}",
                        params={"fields": _node_fields},
                    )
                if data:
                    paper = data
                    references_list = [r.get("paperId") for r in (data.get("references") or []) if r.get("paperId")]
            pid = (paper or {}).get("paperId")
            citation_count = (paper or {}).get("citationCount") or 0
            return {
                "local_id": local_id,
                "paperId": pid,
                "citationCount": citation_count,
                "references": references_list,
                "abstract": (paper or {}).get("abstract") or "",
                "title": ref.get("title") or (paper or {}).get("title") or "",
            }

        # return_exceptions so one ref's failure can't sink the whole graph.
        _raw = await asyncio.gather(
            *[_fetch_ref(i, ref) for i, ref in enumerate(refs)],
            return_exceptions=True,
        )
        ref_details = [d for d in _raw if isinstance(d, dict)]
        for det in ref_details:
            pid = det["paperId"]
            if pid:
                paperid_to_local[pid] = det["local_id"]
            nodes_out.append({
                "id": det["local_id"],
                "paperId": pid,
                "citationCount": det["citationCount"],
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

    # Optional per-first-degree-node AI-gen band from the abstract (free,
    # offline). Mirrors the /papers/expand pass so the ring renders on the
    # bibliography nodes themselves, not only on expanded ones. Bounded by a
    # semaphore; short abstracts short-circuit before any model load.
    if want_ai:
        try:
            band_by_local = {}
            from refchecker.ai_detection import run_detection
            model_ready = False
            try:
                from refchecker.ai_detection import model_manager
                model_ready = model_manager.is_model_installed() and model_manager.deps_available()
            except Exception:
                model_ready = False

            if model_ready:
                _ai_sem = asyncio.Semaphore(4)

                async def _detect_node(det):
                    abstract = (det.get("abstract") or "").strip()
                    if not abstract:
                        band_by_local[det["local_id"]] = {"band": "unavailable", "score": None}
                        return
                    async with _ai_sem:
                        res = await asyncio.to_thread(
                            run_detection, abstract, title=det.get("title"), backend="local"
                        )
                    band_by_local[det["local_id"]] = {"band": res.band, "score": res.overall_score}

                await asyncio.gather(
                    *[_detect_node(det) for det in ref_details], return_exceptions=True
                )
            else:
                for det in ref_details:
                    band_by_local[det["local_id"]] = {"band": "unavailable", "score": None}

            for n in nodes_out:
                b = band_by_local.get(n["id"])
                if b:
                    n["ai_detection_band"] = b["band"]
                    n["ai_detection_score"] = b["score"]
        except Exception as e:
            logger.debug("Graph AI-gen (first-degree) skipped: %s", e)

    return {"nodes": nodes_out, "edges": edges, "ai_detection": want_ai}


class _ExpandRequest(BaseModel):
    paper_id: str  # S2 paperId or "DOI:..." / "arXiv:..." identifier
    limit: int = 8
    # Optional title fallback — when /paper/<paper_id>/references returns
    # an empty list (S2 sometimes has the paper but not its reference
    # graph, particularly for niche / older publications), we search S2
    # by title to resolve the canonical paperId and retry. Without this
    # the graph view shows lots of central refs with no spokes.
    title: Optional[str] = None
    # When true, also estimate an AI-generated-text likelihood band for each
    # expanded article from its ABSTRACT, using the free offline local model.
    # Abstracts are short, so most come back "inconclusive" — this is an
    # advisory signal, never proof, and it never incurs API/LLM cost.
    ai_detection: bool = False


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

    # Pull abstracts too when the caller wants a per-expanded-article AI-gen
    # band (computed locally from the abstract below).
    want_ai = bool(getattr(req, "ai_detection", False))
    _fields = (
        "citedPaper.paperId,citedPaper.title,citedPaper.year,citedPaper.authors,"
        "citedPaper.externalIds,citedPaper.citationCount"
    )
    if want_ai:
        _fields += ",citedPaper.abstract"

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
                        "fields": _fields,
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
                        "fields": _fields,
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
            "abstract": p.get("abstract") if want_ai else None,
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

    # Optional per-expanded-article AI-gen band, computed locally from the
    # abstract (free, offline). Abstracts are short, so should_abstain()
    # short-circuits most to "inconclusive" before any model load — keeping
    # this bounded and cost-free. Never uses a paid backend here.
    if want_ai:
        try:
            from refchecker.ai_detection import run_detection
            model_ready = False
            try:
                from refchecker.ai_detection import model_manager
                model_ready = model_manager.is_model_installed() and model_manager.deps_available()
            except Exception:
                model_ready = False

            # Cap concurrent CPU-bound inferences. Most abstracts short-circuit
            # in should_abstain() before any model load, but a few long ones can
            # each run a DeBERTa forward pass; a semaphore keeps the spike bounded
            # and matches the asyncio.Semaphore idiom used elsewhere in this file.
            _ai_sem = asyncio.Semaphore(4)

            async def _detect_abstract(it):
                abstract = (it.get("abstract") or "").strip()
                if not abstract:
                    it["ai_detection_band"] = "unavailable"
                    return
                async with _ai_sem:
                    res = await asyncio.to_thread(
                        run_detection, abstract, title=it.get("title"), backend="local"
                    )
                it["ai_detection_band"] = res.band
                it["ai_detection_score"] = res.overall_score
                it["ai_detection_reason"] = res.abstain_reason

            if model_ready:
                # return_exceptions so one item's failure can't wipe the bands
                # already computed for the others (each mutates its own dict).
                await asyncio.gather(
                    *[_detect_abstract(it) for it in items], return_exceptions=True
                )
            else:
                for it in items:
                    it["ai_detection_band"] = "unavailable"
                    it["ai_detection_reason"] = "model_not_installed"
        except Exception as e:
            logger.debug("Graph AI-gen expansion skipped: %s", e)

    return {"paper_id": pid, "items": items, "ai_detection": want_ai}


class _AuthorProfileRequest(BaseModel):
    author_id: Optional[str] = None      # Semantic Scholar author id
    openalex_id: Optional[str] = None    # OpenAlex author id (A…) — fallback for non-S2 authors


# Module-level TTL cache for S2 author profiles — the hover tooltip can fire
# many times for the same author across a bibliography; this keeps us well
# under S2's per-IP rate limit. {author_id: (fetched_monotonic, payload)}
_AUTHOR_PROFILE_CACHE: dict = {}
_AUTHOR_PROFILE_TTL = 6 * 60 * 60  # 6 hours


@app.post("/api/authors/profile")
async def author_profile(req: _AuthorProfileRequest, current_user: UserInfo = Depends(require_user)):
    """Fetch an enriched Semantic Scholar author profile for the hover card:
    affiliation, paper/citation counts, h-index, homepage, and a few recent
    papers. Cached (6h TTL) and soft-failing — returns {available: False} on
    any error so the tooltip simply falls back to the basic identifiers.
    """
    import time as _time
    author_id = (req.author_id or "").strip()
    oa_id = (req.openalex_id or "").strip()
    cache_key = author_id or (f"oa:{oa_id}" if oa_id else "")
    if not cache_key:
        return {"available": False}
    # Serve from cache when fresh.
    cached = _AUTHOR_PROFILE_CACHE.get(cache_key)
    if cached and (_time.monotonic() - cached[0]) < _AUTHOR_PROFILE_TTL:
        return cached[1]

    import httpx
    payload = {"available": False}
    try:
        if author_id:
            # Semantic Scholar author API (richest: + recent papers).
            api_key = await _resolve_semantic_scholar_api_key(None)
            headers = {"x-api-key": api_key} if api_key else {}
            fields = "name,affiliations,paperCount,citationCount,hIndex,homepage,papers.title,papers.year"
            url = f"https://api.semanticscholar.org/graph/v1/author/{author_id}"
            async with httpx.AsyncClient() as client:
                r = await client.get(url, params={"fields": fields}, headers=headers, timeout=10.0)
            if r.status_code == 200:
                d = r.json() or {}
                papers = [{"title": p.get("title"), "year": p.get("year")}
                          for p in (d.get("papers") or []) if p.get("title")]
                papers.sort(key=lambda p: (p.get("year") or 0), reverse=True)
                payload = {
                    "available": True, "name": d.get("name"),
                    "affiliations": d.get("affiliations") or [],
                    "paperCount": d.get("paperCount"), "citationCount": d.get("citationCount"),
                    "hIndex": d.get("hIndex"), "homepage": d.get("homepage"),
                    "papers": papers[:5], "source": "semantic_scholar",
                }
        elif oa_id:
            # OpenAlex /authors fallback for authors with no S2 id — supplies
            # h-index / citations / works-count / ORCID for the hover.
            vid = oa_id if oa_id.startswith("A") else str(oa_id).rsplit("/", 1)[-1]
            async with httpx.AsyncClient() as client:
                r = await client.get(f"https://api.openalex.org/authors/{vid}", timeout=10.0)
            if r.status_code == 200:
                d = r.json() or {}
                ss = d.get("summary_stats") or {}
                insts = [i.get("display_name") for i in (d.get("last_known_institutions") or [])
                         if isinstance(i, dict) and i.get("display_name")]
                if not insts:
                    for aff in (d.get("affiliations") or [])[:2]:
                        nm = ((aff or {}).get("institution") or {}).get("display_name")
                        if nm:
                            insts.append(nm)
                orcid = d.get("orcid") or (d.get("ids") or {}).get("orcid")
                if isinstance(orcid, str):
                    orcid = orcid.rsplit("/", 1)[-1]
                payload = {
                    "available": True, "name": d.get("display_name"),
                    "affiliations": insts,
                    "paperCount": d.get("works_count"), "citationCount": d.get("cited_by_count"),
                    "hIndex": ss.get("h_index"), "homepage": None,
                    "orcid": orcid if isinstance(orcid, str) else None,
                    "papers": [], "source": "openalex",
                }
    except Exception as e:
        logger.debug("author_profile fetch failed for %s: %s", cache_key, e)
        payload = {"available": False}

    _AUTHOR_PROFILE_CACHE[cache_key] = (_time.monotonic(), payload)
    return payload


# --------------------------------------------------------------------------- #
# R10 (A3) — ID-less author resolution by name + paper title/year.             #
#                                                                              #
# When a reference's author carries NO author id (no s2_author_id / openalex   #
# id), the hover popover can't fetch a profile. This sibling endpoint resolves #
# a *single* high-confidence author id from a bare name PLUS the citing        #
# paper's title (and optional year) — and ONLY returns it when a strong        #
# corroboration signal exists: the candidate author actually appears on a work #
# whose title matches the supplied title. Otherwise it returns                 #
# {available: False, reason: 'no confident match'} — never a guess. This keeps #
# the "ABSTAIN beats a wrong badge" / no-fabrication contract: a wrong author  #
# profile is worse than none.                                                  #
# --------------------------------------------------------------------------- #

class _AuthorFindRequest(BaseModel):
    name: str                              # bare author name (no id)
    title: Optional[str] = None            # the citing paper's title (corroboration anchor)
    year: Optional[int] = None             # optional year, tightens the corroboration


# Separate, shorter-lived cache from the by-id profile cache: keyed on the
# (name, title, year) triple so the same ID-less author on the same paper isn't
# re-resolved across re-hovers.
_AUTHOR_FIND_CACHE: dict = {}
_AUTHOR_FIND_TTL = 6 * 60 * 60  # 6 hours


def _normalize_person_name(name: str) -> str:
    """Lowercase, strip diacritics + punctuation, collapse whitespace. Mirrors
    the FE AuthorsLine `norm()` so 'Bössuyt' / 'Bossuyt,' both reduce to one
    canonical token sequence for corroboration matching."""
    import unicodedata
    s = unicodedata.normalize("NFD", str(name or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.lower()
    s = re.sub(r"[^a-z0-9\-' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _name_tokens(name: str) -> set:
    """Surname + given-name tokens (length >= 2; drops lone initials so 'J.' on
    one side and 'John' on the other don't spuriously block a match)."""
    return {t for t in _normalize_person_name(name).split(" ") if len(t) >= 2}


def _author_corroborated_on_work(query_name: str, authorship_names: list) -> Optional[str]:
    """Return the work-author display name that corroborates `query_name`, or
    None. A match requires the surname to be present AND the multi-letter token
    overlap to be non-empty — i.e. the cited name and the work's author name
    share their distinctive tokens. Real-data gated: no fuzzy/approximate
    surname guessing, only exact normalized-token containment."""
    q_tokens = _name_tokens(query_name)
    if not q_tokens:
        return None
    # The cited surname is (heuristically) the longest token — it must appear
    # in the work-author's tokens for a corroboration to count.
    q_surname = max(q_tokens, key=len)
    for an in authorship_names:
        a_tokens = _name_tokens(an)
        if not a_tokens:
            continue
        if q_surname in a_tokens and (q_tokens & a_tokens):
            return an
    return None


@app.post("/api/authors/find")
async def author_find(req: _AuthorFindRequest,
                      current_user: UserInfo = Depends(require_user)):
    """R10: resolve a SINGLE high-confidence author id for an ID-less author,
    corroborated by the citing paper's title.

    Strategy (OpenAlex, no fabrication):
      1. Require both a name and a title — without a corroboration anchor we
         refuse outright (return empty), because a name-only search across
         OpenAlex's 90M+ authors is an ambiguity machine.
      2. Find the work by title (`/works?filter=title.search:<title>`,
         optionally `,publication_year:<year>`). Pick the work whose title
         actually matches (normalized) the supplied title.
      3. In that work's authorships, find the single author whose name
         corroborates the supplied name (surname + token overlap). That
         author's OpenAlex id IS the high-confidence match — it's literally an
         author of the cited paper.
      4. Return that author's ids + metrics. If no work matches, or no/ambiguous
         (>1) author on the matching work corroborates the name, return
         {available: False, reason: 'no confident match'}.

    Soft-fails to {available: False} on any error. Cached (6h TTL).
    """
    import time as _time
    name = (req.name or "").strip()
    title = (req.title or "").strip()
    if not name or not title:
        # No corroboration anchor -> never guess.
        return {"available": False, "reason": "no confident match"}

    cache_key = f"{_normalize_person_name(name)}|{_normalize_person_name(title)}|{req.year or ''}"
    cached = _AUTHOR_FIND_CACHE.get(cache_key)
    if cached and (_time.monotonic() - cached[0]) < _AUTHOR_FIND_TTL:
        return cached[1]

    import httpx
    payload = {"available": False, "reason": "no confident match"}
    norm_title = _normalize_person_name(title)
    try:
        filt = f"title.search:{title}"
        if req.year:
            filt += f",publication_year:{int(req.year)}"
        works_fields = "id,title,publication_year,authorships"
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.openalex.org/works",
                params={"filter": filt, "per_page": 5, "select": works_fields},
            )
        if r.status_code == 200:
            results = (r.json() or {}).get("results") or []
            # Keep only works whose title genuinely matches the supplied one
            # (exact normalized equality OR one fully contains the other) —
            # title.search is a loose ranker, so we re-check ourselves.
            def _title_matches(w):
                wt = _normalize_person_name(w.get("title") or "")
                if not wt:
                    return False
                return wt == norm_title or norm_title in wt or wt in norm_title

            matching_works = [w for w in results if _title_matches(w)]
            for w in matching_works:
                authorships = w.get("authorships") or []
                names = [((a or {}).get("author") or {}).get("display_name") or "" for a in authorships]
                # All work-authors whose name corroborates the cited name.
                corro = [
                    (a, nm) for (a, nm) in zip(authorships, names)
                    if nm and _author_corroborated_on_work(name, [nm])
                ]
                if len(corro) != 1:
                    # 0 -> this work doesn't list the cited author; >1 ->
                    # ambiguous (e.g. two same-surname authors). Either way,
                    # ABSTAIN on this work.
                    continue
                author_obj = (corro[0][0] or {}).get("author") or {}
                oa_author_id = author_obj.get("id") or ""
                short_id = oa_author_id.rsplit("/", 1)[-1] if oa_author_id else ""
                if not short_id.startswith("A"):
                    continue
                # Hydrate the resolved author for real metrics (h-index /
                # citations / ORCID), reusing the same OpenAlex author shape as
                # author_profile's OpenAlex fallback.
                metrics = await _fetch_openalex_author_metrics(short_id)
                payload = {
                    "available": True,
                    "name": author_obj.get("display_name") or corro[0][1],
                    "openalex_id": short_id,
                    "matched_work_title": w.get("title"),
                    "matched_work_year": w.get("publication_year"),
                    "source": "openalex",
                    **metrics,
                }
                break
    except Exception as e:
        logger.debug("author_find failed for %s / %s: %s", name, title, e)
        payload = {"available": False, "reason": "no confident match"}

    _AUTHOR_FIND_CACHE[cache_key] = (_time.monotonic(), payload)
    return payload


async def _fetch_openalex_author_metrics(short_id: str) -> Dict[str, Any]:
    """Fetch h-index / citations / works-count / ORCID / affiliations + recent
    papers for a resolved OpenAlex author id. Returns {} on any failure so the
    caller still reports the (corroborated) id without metrics."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"https://api.openalex.org/authors/{short_id}")
        if r.status_code != 200:
            return {}
        d = r.json() or {}
        ss = d.get("summary_stats") or {}
        insts = [i.get("display_name") for i in (d.get("last_known_institutions") or [])
                 if isinstance(i, dict) and i.get("display_name")]
        if not insts:
            for aff in (d.get("affiliations") or [])[:2]:
                nm = ((aff or {}).get("institution") or {}).get("display_name")
                if nm:
                    insts.append(nm)
        orcid = d.get("orcid") or (d.get("ids") or {}).get("orcid")
        if isinstance(orcid, str):
            orcid = orcid.rsplit("/", 1)[-1]
        return {
            "affiliations": insts,
            "paperCount": d.get("works_count"),
            "citationCount": d.get("cited_by_count"),
            "hIndex": ss.get("h_index"),
            "homepage": None,
            "orcid": orcid if isinstance(orcid, str) else None,
            "papers": [],
        }
    except Exception:
        return {}


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
    # v0.7.69: surface recent-growth so the FE chip can answer "is the
    # count actually stuck or just an old snapshot?" without forcing
    # users to dig through logs.
    recent_growth = await db.verified_references_recent_growth()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": rows,
        # Expose where the cache lives so users can spot a path mismatch
        # between an old install's cache_dir and the new install.
        "db_path": str(getattr(db, "db_path", "")),
        "recent_growth": recent_growth,
    }


class _AddSeenReferenceRequest(BaseModel):
    reference: Dict[str, Any]
    check_id: Optional[int] = None
    paper_title: Optional[str] = None


@app.post("/api/references/seen")
async def add_seen_reference(req: _AddSeenReferenceRequest,
                             current_user: UserInfo = Depends(require_user)):
    """'Add to Library' — persist a single reference (with its enrichment blob)
    into the global identity-keyed Seen-References cache. Idempotent: repeated
    adds bump times_seen. Returns {added, times_seen}; added=False when the ref
    has no safe identity key (DOI/arXiv/normalized title) so nothing is stored."""
    try:
        ref = req.reference if isinstance(req.reference, dict) else {}
        ident = await db.upsert_verified_reference(ref, check_id=req.check_id, paper_title=req.paper_title)
        if not ident:
            return {"added": False, "times_seen": 0, "reason": "no identity key"}
        row = await db.lookup_verified_reference(ref)
        return {"added": True, "times_seen": (row or {}).get("times_seen") or 1}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding seen reference: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/references/seen")
async def clear_seen_references(current_user: UserInfo = Depends(require_user)):
    """Wipe the entire Seen References cache. Powers the 'Clear cache'
    button on the Seen Refs tab."""
    removed = await db.clear_verified_references()
    return {"removed": removed}


class _RemoveSeenReferenceRequest(BaseModel):
    # Optional: pass the full reference and let the server resolve the same
    # identity key the upsert/add path uses. Mirrors _AddSeenReferenceRequest
    # so the FE can post the exact ref it rendered.
    reference: Optional[Dict[str, Any]] = None


@app.delete("/api/references/seen/{identity_key:path}")
async def remove_seen_reference(identity_key: str,
                                current_user: UserInfo = Depends(require_user)):
    """'Remove from Library' — drop a single reference from the global
    Seen-References cache by its identity key (DOI / arXiv / normalized
    title — the same key the add/upsert path computes). Counterpart to the
    whole-cache wipe above. Idempotent: returns {removed: False} when no
    matching row exists. Same auth gating as the other /references/seen
    endpoints."""
    removed = await db.delete_verified_reference((identity_key or "").strip())
    return {"removed": removed}


@app.post("/api/references/seen/remove")
async def remove_seen_reference_by_body(req: _RemoveSeenReferenceRequest,
                                        current_user: UserInfo = Depends(require_user)):
    """Body-based variant of the per-reference removal: accepts a full
    reference dict, resolves its identity key exactly like the add/upsert
    path (Database.reference_identity_key), and deletes that one row.
    Returns {removed: bool}; removed=False when the ref yields no safe
    identity key or no matching row exists. Same auth gating as the other
    /references/seen endpoints."""
    ref = req.reference if isinstance(req.reference, dict) else {}
    ident = db.reference_identity_key(ref)
    if not ident:
        return {"removed": False, "reason": "no identity key"}
    removed = await db.delete_verified_reference(ident)
    return {"removed": removed, "identity_key": ident}


class _VenueProfileRequest(BaseModel):
    venue_id: Optional[str] = None    # OpenAlex source id (S…)
    issn: Optional[str] = None
    venue_name: Optional[str] = None


_VENUE_PROFILE_CACHE: Dict[str, Dict[str, Any]] = {}


@app.post("/api/venues/profile")
async def get_venue_profile(req: _VenueProfileRequest,
                            current_user: UserInfo = Depends(require_user)):
    """Resolve a journal/venue to REAL metadata for the venue-name hover:
    publisher, ISSN, open-access/DOAJ status, homepage, and (when DOAJ lists it)
    an author-guidelines link. Source: OpenAlex /sources + DOAJ. Soft-fails to
    {available: false}; never fabricates metadata or guidelines."""
    cache_key = (req.venue_id or req.issn or req.venue_name or "").strip().lower()
    if cache_key and cache_key in _VENUE_PROFILE_CACHE:
        return _VENUE_PROFILE_CACHE[cache_key]
    import httpx
    try:
        src = None
        async with httpx.AsyncClient(timeout=10.0) as client:
            if req.venue_id:
                vid = req.venue_id if req.venue_id.startswith("S") else str(req.venue_id).rsplit("/", 1)[-1]
                r = await client.get(f"https://api.openalex.org/sources/{vid}")
                if r.status_code == 200:
                    src = r.json()
            if not src and req.issn:
                r = await client.get("https://api.openalex.org/sources",
                                     params={"filter": f"issn:{req.issn}", "per_page": 1})
                if r.status_code == 200:
                    res = (r.json() or {}).get("results") or []
                    src = res[0] if res else None
            if not src and req.venue_name:
                r = await client.get("https://api.openalex.org/sources",
                                     params={"search": req.venue_name, "per_page": 1})
                if r.status_code == 200:
                    res = (r.json() or {}).get("results") or []
                    src = res[0] if res else None
            if not isinstance(src, dict) or not src.get("display_name"):
                out = {"available": False}
                if cache_key:
                    _VENUE_PROFILE_CACHE[cache_key] = out
                return out

            issns = src.get("issn") or []
            if isinstance(issns, str):
                issns = [issns]
            out: Dict[str, Any] = {
                "available": True,
                "display_name": src.get("display_name"),
                "publisher": src.get("host_organization_name"),
                "issn_l": src.get("issn_l"),
                "issn": issns,
                "is_oa": src.get("is_oa"),
                "is_in_doaj": src.get("is_in_doaj"),
                "homepage_url": src.get("homepage_url"),
                "works_count": src.get("works_count"),
                "cited_by_count": src.get("cited_by_count"),
            }
            if isinstance(src.get("id"), str):
                out["openalex_id"] = str(src["id"]).rsplit("/", 1)[-1]
            if isinstance(src.get("apc_usd"), int):
                out["apc_usd"] = src["apc_usd"]

            # DOAJ author guidelines — only when an ISSN is known AND DOAJ lists it.
            issn_for_doaj = out.get("issn_l") or (issns[0] if issns else None)
            if issn_for_doaj:
                try:
                    dr = await client.get(f"https://doaj.org/api/search/journals/issn:{issn_for_doaj}")
                    if dr.status_code == 200:
                        results = (dr.json() or {}).get("results") or []
                        if results:
                            bj = (results[0] or {}).get("bibjson") or {}
                            ref = bj.get("ref") or {}
                            gl = ref.get("author_instructions")
                            if isinstance(gl, str) and gl.startswith("http"):
                                out["author_guidelines_url"] = gl
                            lic = bj.get("license")
                            if isinstance(lic, list) and lic and isinstance(lic[0], dict):
                                out["license"] = lic[0].get("type")
                except Exception as _de:
                    logger.debug("DOAJ lookup failed: %s", _de)

            if cache_key:
                _VENUE_PROFILE_CACHE[cache_key] = out
            return out
    except Exception as e:
        logger.debug("venue profile failed: %s", e)
        return {"available": False}


@app.get("/api/references/library/graph")
async def references_library_graph(
    limit: int = 400,
    min_times_seen: int = 1,
    edge_strategy: str = "shared-authors",
    current_user: UserInfo = Depends(require_user),
):
    """Nodes + edges for the Obsidian-style 3D Seen-References graph. Bounded
    (node cap + edge cull) so a large library stays renderable."""
    try:
        return await db.build_reference_graph_data(
            limit=limit, min_times_seen=min_times_seen, edge_strategy=edge_strategy
        )
    except Exception as e:
        logger.error(f"Error building reference graph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/references/seen/backfill")
async def backfill_seen_references(current_user: UserInfo = Depends(require_user)):
    """Re-run the Seen-Refs backfill: walk every completed check_history
    row, upsert every reference into the global identity index. Idempotent
    — repeated keys just bump times_seen. Used to recover when the
    backstop silently dropped refs in earlier versions (the "120 plateau"
    bug), and as a diagnostic: the response reports how many NEW vs
    DUPLICATE rows landed, so the user can see whether their recent
    checks actually produce new identity keys."""
    result = await db.backfill_seen_references()
    return result


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
    if not api_key or not endpoint:
        from refchecker.config.settings import resolve_api_key, resolve_endpoint

        api_key = api_key or resolve_api_key(provider)
        endpoint = endpoint or resolve_endpoint(provider)

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


@app.get("/api/ai-detection/model/status")
async def ai_detection_model_status(current_user: UserInfo = Depends(require_user)):
    """Install/download status for the local AI-text-detection model."""
    from refchecker.ai_detection import model_manager
    return model_manager.model_status()


@app.get("/api/ai-detection/model/update-check")
async def ai_detection_model_update_check(current_user: UserInfo = Depends(require_user)):
    """Is a newer revision of the local model available on Hugging Face?

    Deliberately a SEPARATE endpoint from /status (which the UI polls during
    downloads) — this makes a network round-trip to HF, run off the hot path and
    only when the Settings panel asks. Degrades to update_available=false on any
    failure. The HF call can take a couple of seconds, so run it off-thread.
    """
    from refchecker.ai_detection import model_manager
    return await asyncio.to_thread(model_manager.query_update_available)


@app.post("/api/ai-detection/model/download")
async def ai_detection_model_download(current_user: UserInfo = Depends(require_user)):
    """Start (or report) the background download of the local model.

    The model lives at a single shared filesystem path (not per-user), so in
    a multi-user deployment only admins may mutate it; on the single-user
    desktop app the (admin) user manages their own model.
    """
    if is_multiuser_mode():
        _require_admin(current_user)
    from refchecker.ai_detection import model_manager
    if not model_manager.deps_available():
        raise HTTPException(
            status_code=400,
            detail=(
                "Local detection runtime not installed. Use “Install runtime” "
                "in Settings → AI Detection (installs torch + transformers), or "
                "pick the LLM-judge or API backend instead."
            ),
        )
    return model_manager.start_download()


@app.delete("/api/ai-detection/model")
async def ai_detection_model_delete(current_user: UserInfo = Depends(require_user)):
    """Remove the downloaded local model from disk.

    Admin-gated in multi-user mode: the model is shared across all users, so a
    non-admin must not be able to delete it out from under everyone else.
    """
    if is_multiuser_mode():
        _require_admin(current_user)
    from refchecker.ai_detection import model_manager
    return model_manager.delete_model()


@app.get("/api/ai-detection/detectors")
async def ai_detection_list_detectors(current_user: UserInfo = Depends(require_user)):
    """Multi-detector registry + per-detector install status (R61).

    Returns the full registry (Tier-1 runnable + Tier-2 heavy/opt-in) with real
    size/license/RAID-note metadata and each detector's install state. Tier-2
    detectors report ``installable: false`` so the UI shows them as unavailable
    and never offers to run them (honesty: never a fabricated number).
    """
    from refchecker.ai_detection import model_manager
    return model_manager.registry_status()


@app.post("/api/ai-detection/install/{key}")
async def ai_detection_install_detector(
    key: str,
    current_user: UserInfo = Depends(require_user),
):
    """Start (or report) the background download of a specific detector (R61).

    Refuses unknown / non-installable (heavy Tier-2) keys honestly. The model
    lives at a single shared filesystem path, so admin-gated in multi-user mode.
    """
    if is_multiuser_mode():
        _require_admin(current_user)
    from refchecker.ai_detection import model_manager
    entry = model_manager.get_detector(key)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Unknown detector: {key}")
    if not entry.get("installable"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Detector '{key}' is a heavy Tier-2 detector that is not "
                "runnable in this build, so it cannot be installed."
            ),
        )
    if not model_manager.deps_available():
        raise HTTPException(
            status_code=400,
            detail=(
                "Local detection runtime not installed. Use “Install runtime” "
                "in Settings → AI Detection (installs torch + transformers)."
            ),
        )
    return model_manager.start_detector_download(key)


@app.delete("/api/ai-detection/model/{key}")
async def ai_detection_delete_detector(
    key: str,
    current_user: UserInfo = Depends(require_user),
):
    """Remove a specific installed detector's weights from disk (R61).

    Per-key counterpart of ``DELETE /api/ai-detection/model``. Admin-gated in
    multi-user mode (detectors are shared across users).
    """
    if is_multiuser_mode():
        _require_admin(current_user)
    from refchecker.ai_detection import model_manager
    if not model_manager.get_detector(key):
        raise HTTPException(status_code=404, detail=f"Unknown detector: {key}")
    return model_manager.delete_detector(key)


@app.get("/api/ai-detection/runtime/status")
async def ai_detection_runtime_status(current_user: UserInfo = Depends(require_user)):
    """Status of the optional local-detector inference runtime (torch/onnx)."""
    from refchecker.ai_detection import runtime_manager
    return runtime_manager.runtime_status()


@app.post("/api/ai-detection/runtime/install")
async def ai_detection_runtime_install(
    variant: str = "torch",
    current_user: UserInfo = Depends(require_user),
):
    """Install the optional inference runtime from the app (pip --target).

    ``variant`` is 'torch' (default; required by the bundled desklib model,
    which ships safetensors only) or 'onnx' (smaller; needs an ONNX export).
    Installed into a per-user dir and added to sys.path — no restart needed.
    Admin-gated in multi-user mode (it mutates a shared on-disk runtime).
    """
    if is_multiuser_mode():
        _require_admin(current_user)
    from refchecker.ai_detection import runtime_manager
    return runtime_manager.start_install(variant)


@app.get("/api/ai-detection/diagnostics")
async def ai_detection_diagnostics(current_user: UserInfo = Depends(require_user)):
    """Debugger payload for Settings → AI Detection: the runtime install
    status + live install log, plus recent (text-free) detection-run events
    so users can see why detection produced a given band / no band."""
    from refchecker.ai_detection import runtime_manager, model_manager, diagnostics
    return {
        "runtime": runtime_manager.runtime_status(),
        "model": model_manager.model_status(),
        "events": diagnostics.events(),
    }


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
