"""
FastAPI application for RefChecker Web UI
"""
import asyncio
import uuid
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Body, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import logging
from refchecker.__version__ import __version__

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
    MULTIUSER_MODE,
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
    get_text_thumbnail_async,
    get_text_preview_async,
    get_thumbnail_cache_path,
    get_preview_cache_path
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_uploads_dir() -> Path:
    """Return the base uploads directory, inside the persistent data dir."""
    d = get_data_dir() / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
app = FastAPI(title="RefChecker Web UI API", version="1.0.0")

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
    if user_id == 0:
        return True  # opt-out sentinel (e.g., unauthenticated recheck)
    async with _user_active_checks_lock:
        current = _user_active_checks.get(user_id, 0)
        if current >= MAX_CHECKS_PER_USER:
            return False
        _user_active_checks[user_id] = current + 1
        return True


async def _release_user_check_slot(user_id: int) -> None:
    if user_id == 0:
        return  # opt-out sentinel — nothing to release
    async with _user_active_checks_lock:
        current = _user_active_checks.get(user_id, 0)
        _user_active_checks[user_id] = max(0, current - 1)


def _session_id_for_check(check_id: int) -> Optional[str]:
    """Helper to find the session_id for an in-progress check."""
    for session_id, meta in active_checks.items():
        if meta.get("check_id") == check_id:
            return session_id
    return None


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


@app.on_event("startup")
async def startup_event():
    """Initialize database and settings on startup"""
    await db.init_db()
    
    # Initialize global concurrency limiter with saved setting
    try:
        concurrency_setting = await db.get_setting("max_concurrent_checks")
        max_concurrent = int(concurrency_setting) if concurrency_setting else DEFAULT_MAX_CONCURRENT
        await init_limiter(max_concurrent)
        logger.info(f"Initialized global concurrency limiter with max={max_concurrent}")
    except Exception as e:
        logger.warning(f"Failed to load concurrency setting, using default: {e}")
        await init_limiter(DEFAULT_MAX_CONCURRENT)
    
    # Mark any previously in-progress checks as cancelled (e.g., after restart)
    try:
        stale = await db.cancel_stale_in_progress()
        if stale:
            logger.info(f"Cancelled {stale} stale in-progress checks on startup")
    except Exception as e:
        logger.error(f"Failed to cancel stale checks: {e}")
    logger.info("Database initialized")


@app.get("/")
async def root():
    """Serve frontend if available, otherwise return API health check"""
    # If static frontend is bundled, serve it
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
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
    return {"providers": get_available_providers(), "multiuser": MULTIUSER_MODE}


@app.get("/api/auth/login/{provider}")
async def auth_login(provider: str, request: Request):
    """Redirect to the OAuth authorization URL for the given provider."""
    entry = _EXCHANGE_FNS.get(provider)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    url_fn, _ = entry
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
        return RedirectResponse(url=f"{site}?auth_error=unknown_provider")

    if error or not code or not state:
        return RedirectResponse(url=f"{site}?auth_error={error or 'missing_code'}")
    if not _validate_oauth_state(state, provider):
        return RedirectResponse(url=f"{site}?auth_error=invalid_state")

    _, exchange_fn = entry
    user_data = await exchange_fn(code, request)
    if not user_data:
        return RedirectResponse(url=f"{site}?auth_error=exchange_failed")

    user_id = await db.create_or_update_user(**user_data)
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
async def auth_logout():
    """Clear the auth cookie and log out."""
    from fastapi.responses import JSONResponse
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
            await websocket.close(code=4001, reason="Unauthorized")
            return
        token_data = decode_access_token(token)
        if not token_data:
            await websocket.close(code=4001, reason="Invalid token")
            return
        active = active_checks.get(session_id)
        if not active or active.get("user_id") != token_data.user_id:
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
        logger.info(f"Effective API key resolved: {'present' if effective_api_key else 'MISSING'}, SS key: {'present' if semantic_scholar_api_key else 'MISSING'}")

        # Handle file upload or pasted text
        paper_source = source_value
        paper_title = "Processing..."  # Placeholder title until we parse the paper
        original_filename = None  # Only set for file uploads
        if source_type == "file" and file:
            # Save uploaded file to user-isolated uploads directory
            uploads_dir = get_uploads_dir() / str(user_id)
            uploads_dir.mkdir(parents=True, exist_ok=True)
            # Use check-specific naming to avoid conflicts
            safe_filename = file.filename.replace("/", "_").replace("\\", "_")
            file_path = uploads_dir / f"{session_id}_{safe_filename}"
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
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
        elif source_type == "url":
            paper_title = source_value

        if not paper_source:
            raise HTTPException(status_code=400, detail="No source provided")

        # Rate limiting: enforce per-user concurrent check limit
        if not await _acquire_user_check_slot(user_id):
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
        )
        logger.info(f"Created pending check with ID {check_id}")

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
    try:
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
            await manager.send_message(session_id, event_type, data)
            
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

        # Use per-request Semantic Scholar key from client; fall back to DB for single-user mode
        if not semantic_scholar_api_key:
            semantic_scholar_api_key = await db.get_setting("semantic_scholar_api_key")
        
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
            semantic_scholar_api_key=semantic_scholar_api_key
        )

        # Run the check
        result = await checker.check_paper(paper_source, source_type)

        # For file uploads, don't overwrite the original filename with "Unknown Paper"
        # The correct title was already set in the database when the check was created
        result_title = result["paper_title"]
        if source_type == "file" and result_title == "Unknown Paper":
            result_title = None  # Don't update title
        
        # Update the existing check entry with results
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
            extraction_method=result.get("extraction_method")
        )

        # Generate thumbnail for file uploads
        if source_type == "file":
            try:
                # Generate and cache thumbnail
                if paper_source.lower().endswith('.pdf'):
                    thumbnail_path = await generate_pdf_thumbnail_async(paper_source)
                else:
                    thumbnail_path = await get_text_thumbnail_async(check_id, "", paper_source)
                if thumbnail_path:
                    await db.update_check_thumbnail(check_id, thumbnail_path)
                    logger.info(f"Generated thumbnail for check {check_id}: {thumbnail_path}")
            except Exception as thumb_error:
                logger.warning(f"Failed to generate thumbnail for check {check_id}: {thumb_error}")
            
            # Note: We keep uploaded files for later access via /api/file/{check_id}

    except asyncio.CancelledError:
        logger.info(f"Check cancelled: {session_id}")
        await db.update_check_status(check_id, 'cancelled')
        await manager.send_message(session_id, "cancelled", {"message": "Check cancelled", "check_id": check_id})
    except Exception as e:
        logger.error(f"Error in run_check: {e}", exc_info=True)
        await db.update_check_status(check_id, 'error')
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
                headers={"Cache-Control": "public, max-age=86400"}  # Cache for 1 day
            )
        
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
            import hashlib
            import tempfile
            from backend.refchecker_wrapper import download_pdf
            
            pdf_hash = hashlib.md5(paper_source.encode()).hexdigest()[:12]
            pdf_path = os.path.join(tempfile.gettempdir(), f"refchecker_pdf_{pdf_hash}.pdf")
            
            # Download PDF if not already cached
            if not os.path.exists(pdf_path):
                try:
                    await asyncio.to_thread(download_pdf, paper_source, pdf_path)
                except Exception as e:
                    logger.error(f"Failed to download PDF for thumbnail: {e}")
                    thumbnail_path = await get_text_thumbnail_async(check_id, "PDF")
                    pdf_path = None
            
            if pdf_path and os.path.exists(pdf_path):
                thumbnail_path = await generate_pdf_thumbnail_async(pdf_path)
            else:
                thumbnail_path = await get_text_thumbnail_async(check_id, "PDF")
        elif arxiv_match:
            # Generate thumbnail from ArXiv paper
            arxiv_id = arxiv_match.group(1)
            logger.info(f"Generating thumbnail for ArXiv paper: {arxiv_id}")
            thumbnail_path = await generate_arxiv_thumbnail_async(arxiv_id, check_id)
        elif source_type == 'file' and paper_source.lower().endswith('.pdf'):
            # Generate thumbnail from uploaded PDF
            if os.path.exists(paper_source):
                logger.info(f"Generating thumbnail from PDF: {paper_source}")
                thumbnail_path = await generate_pdf_thumbnail_async(paper_source)
            else:
                # PDF file no longer exists, use placeholder
                thumbnail_path = await get_text_thumbnail_async(check_id, "PDF")
        elif source_type == 'file':
            # For non-PDF file uploads, generate thumbnail with file content
            logger.info(f"Generating text content thumbnail for uploaded file check {check_id}")
            if os.path.exists(paper_source):
                thumbnail_path = await get_text_thumbnail_async(check_id, "", paper_source)
            else:
                thumbnail_path = await get_text_thumbnail_async(check_id, "Uploaded file")
        elif source_type == 'text':
            # Generate thumbnail with actual text content for pasted text
            logger.info(f"Generating text content thumbnail for check {check_id}")
            # paper_source is now a file path for text sources
            thumbnail_path = await get_text_thumbnail_async(check_id, "", paper_source)
        else:
            # Default placeholder for other sources
            thumbnail_path = await get_text_thumbnail_async(check_id, source_type)
        
        if thumbnail_path and os.path.exists(thumbnail_path):
            # Cache the thumbnail path in the database
            await db.update_check_thumbnail(check_id, thumbnail_path)
            
            return FileResponse(
                thumbnail_path,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"}
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
            import hashlib
            import tempfile
            from backend.refchecker_wrapper import download_pdf
            
            pdf_hash = hashlib.md5(paper_source.encode()).hexdigest()[:12]
            pdf_path = os.path.join(tempfile.gettempdir(), f"refchecker_pdf_{pdf_hash}.pdf")
            
            # Download PDF if not already cached
            if not os.path.exists(pdf_path):
                try:
                    await asyncio.to_thread(download_pdf, paper_source, pdf_path)
                except Exception as e:
                    logger.error(f"Failed to download PDF for preview: {e}")
                    pdf_path = None
            
            if pdf_path and os.path.exists(pdf_path):
                preview_path = await generate_pdf_preview_async(pdf_path)
        elif arxiv_match:
            # Generate preview from ArXiv paper
            arxiv_id = arxiv_match.group(1)
            logger.info(f"Generating preview for ArXiv paper: {arxiv_id}")
            preview_path = await generate_arxiv_preview_async(arxiv_id, check_id)
        elif source_type == 'file' and paper_source.lower().endswith('.pdf'):
            # Generate preview from uploaded PDF
            if os.path.exists(paper_source):
                logger.info(f"Generating preview from PDF: {paper_source}")
                preview_path = await generate_pdf_preview_async(paper_source)
        
        if preview_path and os.path.exists(preview_path):
            return FileResponse(
                preview_path,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"}  # Cache for 1 day
            )
        
        # For text sources, generate a high-resolution text preview for overlay display
        if source_type == 'text':
            logger.info(f"Generating text preview for check {check_id}")
            preview_path = await get_text_preview_async(check_id, "", paper_source)
            if preview_path and os.path.exists(preview_path):
                return FileResponse(
                    preview_path,
                    media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"}
                )
        
        # For non-PDF file uploads, also generate a text preview
        if source_type == 'file' and not paper_source.lower().endswith('.pdf'):
            logger.info(f"Generating text preview for uploaded file check {check_id}")
            if os.path.exists(paper_source):
                preview_path = await get_text_preview_async(check_id, "", paper_source)
            else:
                preview_path = await get_text_preview_async(check_id, "Uploaded file")
            if preview_path and os.path.exists(preview_path):
                return FileResponse(
                    preview_path,
                    media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"}
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
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "Cache-Control": "public, max-age=3600"
                }
            )
        else:
            # Fallback: if paper_source is the actual text content (legacy)
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(
                paper_source,
                headers={"Cache-Control": "public, max-age=3600"}
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
                headers={"Cache-Control": "public, max-age=3600"}
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
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "Cache-Control": "public, max-age=3600"
                }
            )
        
        # Fall back to pasted text source if source_type is 'text' and it's bbl/bib
        if source_type == 'text' and extraction_method in ['bbl', 'bib'] and os.path.exists(paper_source):
            return FileResponse(
                paper_source,
                media_type="text/plain; charset=utf-8",
                filename=f"bibliography_{check_id}.{extraction_method}",
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "Cache-Control": "public, max-age=3600"
                }
            )
        
        raise HTTPException(status_code=404, detail="Bibliography source not available for this check")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting bibliography source: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/recheck/{check_id}")
async def recheck(check_id: int, current_user: UserInfo = Depends(require_user)):
    """Re-run a previous check"""
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
        
        # Create history entry immediately
        new_check_id = await db.create_pending_check(
            paper_title=original.get("paper_title", "Re-checking..."),
            paper_source=source,
            source_type=source_type,
            llm_provider=llm_provider,
            llm_model=llm_model,
            original_filename=original.get("original_filename"),
            user_id=user_id,
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
        active_checks[session_id] = {"task": task, "cancel_event": cancel_event, "check_id": new_check_id, "user_id": user_id}

        return {
            "session_id": session_id,
            "check_id": new_check_id,
            "message": "Re-check started",
            "original_id": check_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rechecking: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cancel/{session_id}")
async def cancel_check(session_id: str, current_user: UserInfo = Depends(require_user)):
    """Cancel an active check"""
    active = active_checks.get(session_id)
    if not active:
        raise HTTPException(status_code=404, detail="Active check not found")
    user_id = get_user_id_filter(current_user)
    if user_id is not None and active.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Active check not found")
    active["cancel_event"].set()
    active["task"].cancel()
    return {"message": "Cancellation requested"}


# ============ Batch Operations ============

@app.post("/api/check/batch")
async def start_batch_check(
    request: BatchUrlsRequest,
    current_user: UserInfo = Depends(require_user),
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

        valid_urls = [u.strip() for u in request.urls if u.strip()]

        # Pre-acquire one slot per URL to enforce per-user rate limit atomically
        slots_needed = len(valid_urls)
        slots_acquired = 0
        for _ in range(slots_needed):
            if not await _acquire_user_check_slot(user_id):
                # Release slots already acquired
                for _ in range(slots_acquired):
                    await _release_user_check_slot(user_id)
                raise HTTPException(
                    status_code=429,
                    detail=f"Maximum concurrent checks ({MAX_CHECKS_PER_USER}) reached"
                )
            slots_acquired += 1

        checks = []
        
        for url in valid_urls:
            session_id = str(uuid.uuid4())
            
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
        
        files_to_process = []
        
        # Check if single ZIP file
        if len(files) == 1 and files[0].filename.lower().endswith('.zip'):
            import zipfile
            import io
            
            zip_content = await files[0].read()
            with zipfile.ZipFile(io.BytesIO(zip_content), 'r') as zf:
                for name in zf.namelist():
                    # Skip directories and hidden files
                    if name.endswith('/') or name.startswith('__') or '/.' in name:
                        continue
                    
                    # Only process supported file types
                    lower_name = name.lower()
                    if not any(lower_name.endswith(ext) for ext in ['.pdf', '.txt', '.tex', '.bib', '.bbl']):
                        continue
                    
                    if len(files_to_process) >= MAX_BATCH_SIZE:
                        break
                    
                    # Extract file
                    content = zf.read(name)
                    filename = os.path.basename(name)
                    file_path = uploads_dir / f"{batch_id}_{filename}"
                    with open(file_path, 'wb') as f:
                        f.write(content)
                    
                    files_to_process.append({
                        'path': str(file_path),
                        'filename': filename
                    })
        else:
            # Process individual files
            for file in files[:MAX_BATCH_SIZE]:
                safe_filename = file.filename.replace("/", "_").replace("\\", "_")
                file_path = uploads_dir / f"{batch_id}_{safe_filename}"
                content = await file.read()
                with open(file_path, "wb") as f:
                    f.write(content)
                
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
                raise HTTPException(
                    status_code=429,
                    detail=f"Maximum concurrent checks ({MAX_CHECKS_PER_USER}) reached"
                )
            slots_acquired += 1
        
        checks = []
        for file_info in files_to_process:
            session_id = str(uuid.uuid4())
            
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
        raise
    except Exception as e:
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
async def cancel_batch(batch_id: str, current_user: UserInfo = Depends(require_user)):
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
        # In single-user mode, store the API key in the database
        store_key = config.api_key if not MULTIUSER_MODE else None
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
        # In single-user mode, store the API key in the database
        store_key = config.api_key if not MULTIUSER_MODE else None
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
async def validate_llm_config(config: LLMConfigValidate):
    """
    Validate an LLM configuration by making a test API call.
    Returns success or error message.
    """
    # Map providers to their required packages
    PROVIDER_PACKAGES = {
        "anthropic": ("anthropic", "pip install anthropic"),
        "openai": ("openai", "pip install openai"),
        "google": ("google.generativeai", "pip install google-generativeai"),
        "gemini": ("google.generativeai", "pip install google-generativeai"),
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
async def validate_semantic_scholar_key(data: SemanticScholarKeyValidate):
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
async def get_semantic_scholar_key_status():
    """Check if Semantic Scholar API key is configured (does not return the key)"""
    try:
        has_key = await db.has_setting("semantic_scholar_api_key")
        return {"has_key": has_key}
    except Exception as e:
        logger.error(f"Error checking Semantic Scholar key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/settings/semantic-scholar")
async def set_semantic_scholar_key(data: SemanticScholarKeyUpdate):
    """Set or update the Semantic Scholar API key"""
    try:
        if not data.api_key or not data.api_key.strip():
            raise HTTPException(status_code=400, detail="API key cannot be empty")
        
        await db.set_setting("semantic_scholar_api_key", data.api_key.strip())
        logger.info("Semantic Scholar API key updated")
        return {"message": "Semantic Scholar API key saved", "has_key": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving Semantic Scholar key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/settings/semantic-scholar")
async def delete_semantic_scholar_key():
    """Delete the Semantic Scholar API key"""
    try:
        await db.delete_setting("semantic_scholar_api_key")
        logger.info("Semantic Scholar API key deleted")
        return {"message": "Semantic Scholar API key deleted", "has_key": False}
    except Exception as e:
        logger.error(f"Error deleting Semantic Scholar key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# General Settings endpoints

class SettingUpdate(BaseModel):
    value: str


@app.get("/api/settings")
async def get_all_settings():
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
            }
        }
        
        # Get current values from database
        settings = {}
        for key, config in settings_config.items():
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
        
        return settings
    except Exception as e:
        logger.error(f"Error getting settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/settings/{setting_key}")
async def update_setting(setting_key: str, update: SettingUpdate):
    """Update a specific setting"""
    try:
        # Validate the setting key
        valid_keys = {"max_concurrent_checks"}
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
        
        # For other settings, just store the value
        await db.set_setting(setting_key, update.value)
        return {"key": setting_key, "value": update.value, "message": "Setting updated"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating setting: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Debug/Admin endpoints

@app.delete("/api/admin/cache")
async def clear_verification_cache(current_user: UserInfo = Depends(require_user)):
    """Clear the verification cache"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    try:
        count = await db.clear_verification_cache()
        logger.info(f"Cleared {count} entries from verification cache")
        return {"message": f"Cleared {count} cached verification results", "count": count}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/database")
async def clear_database(current_user: UserInfo = Depends(require_user)):
    """Clear all data (cache + history) but keep settings and LLM configs"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    try:
        # Clear verification cache
        cache_count = await db.clear_verification_cache()
        
        # Clear check history
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("DELETE FROM check_history")
            await conn.commit()
            cursor = await conn.execute("SELECT changes()")
            row = await cursor.fetchone()
            history_count = row[0] if row else 0
        
        logger.info(f"Cleared database: {cache_count} cache entries, {history_count} history entries")
        return {
            "message": f"Cleared {cache_count} cache entries and {history_count} history entries",
            "cache_count": cache_count,
            "history_count": history_count
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
        return FileResponse(str(index_path), media_type="text/html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
