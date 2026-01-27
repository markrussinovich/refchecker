"""
FastAPI application for RefChecker Web UI
"""
import asyncio
import uuid
import os
import tempfile
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import logging
from refchecker.__version__ import __version__

import aiosqlite
from .database import db
from .websocket_manager import manager
from .refchecker_wrapper import ProgressRefChecker
from .models import CheckRequest, CheckHistoryItem
from .concurrency import init_limiter, get_limiter, DEFAULT_MAX_CONCURRENT
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


# Create FastAPI app
app = FastAPI(title="RefChecker Web UI API", version="1.0.0")

# Static files directory for bundled frontend
STATIC_DIR = Path(__file__).parent / "static"

# Configure CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://localhost:5175", "http://127.0.0.1:5174", "http://127.0.0.1:5175", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Track active check sessions
active_checks = {}


def _session_id_for_check(check_id: int) -> Optional[str]:
    """Helper to find the session_id for an in-progress check."""
    for session_id, meta in active_checks.items():
        if meta.get("check_id") == check_id:
            return session_id
    return None


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


@app.websocket("/api/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time updates"""
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
    use_llm: bool = Form(True)
):
    """
    Start a new reference check

    Args:
        source_type: 'url' or 'file'
        source_value: URL or ArXiv ID (for url type)
        file: Uploaded file (for file type)
        llm_config_id: ID of the LLM config to use (for retrieving API key)
        llm_provider: LLM provider to use
        llm_model: Specific model to use
        use_llm: Whether to use LLM for extraction

    Returns:
        Session ID for tracking progress via WebSocket
    """
    try:
        # Generate session ID
        session_id = str(uuid.uuid4())
        
        # Retrieve API key from config if config_id provided
        api_key = None
        endpoint = None
        if llm_config_id and use_llm:
            config = await db.get_llm_config_by_id(llm_config_id)
            if config:
                api_key = config.get('api_key')
                endpoint = config.get('endpoint')
                llm_provider = config.get('provider', llm_provider)
                llm_model = config.get('model') or llm_model
                logger.info(f"Using LLM config {llm_config_id}: {llm_provider}/{llm_model}")
            else:
                logger.warning(f"LLM config {llm_config_id} not found")

        # Handle file upload or pasted text
        paper_source = source_value
        paper_title = "Processing..."  # Placeholder title until we parse the paper
        if source_type == "file" and file:
            # Save uploaded file to permanent uploads directory
            uploads_dir = Path(__file__).parent / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            # Use check-specific naming to avoid conflicts
            safe_filename = file.filename.replace("/", "_").replace("\\", "_")
            file_path = uploads_dir / f"{session_id}_{safe_filename}"
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
            paper_source = str(file_path)
            paper_title = file.filename
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

        # Create history entry immediately (in_progress status)
        check_id = await db.create_pending_check(
            paper_title=paper_title,
            paper_source=paper_source,
            source_type=source_type,
            llm_provider=llm_provider if use_llm else None,
            llm_model=llm_model if use_llm else None
        )
        logger.info(f"Created pending check with ID {check_id}")

        # Start check in background
        cancel_event = asyncio.Event()
        task = asyncio.create_task(
            run_check(session_id, check_id, paper_source, source_type, llm_provider, llm_model, api_key, endpoint, use_llm, cancel_event)
        )
        active_checks[session_id] = {"task": task, "cancel_event": cancel_event, "check_id": check_id}

        return {
            "session_id": session_id,
            "check_id": check_id,
            "message": "Check started",
            "source": paper_source
        }

    except Exception as e:
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
    cancel_event: asyncio.Event
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
                bib_dir = Path(__file__).parent / "uploads" / "bibliography"
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
            bibliography_source_callback=bibliography_source_callback
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


@app.get("/api/history")
async def get_history(limit: int = 50):
    """Get check history"""
    try:
        history = await db.get_history(limit)

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
async def get_check_detail(check_id: int):
    """Get detailed results for a specific check"""
    try:
        check = await db.get_check_by_id(check_id)
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
async def get_thumbnail(check_id: int):
    """
    Get or generate a thumbnail for a check.
    
    Returns the thumbnail image file if available, or generates one on-demand.
    For ArXiv papers, downloads the PDF and generates a thumbnail of the first page.
    For uploaded PDFs, generates a thumbnail from the file.
    For pasted text, returns a placeholder thumbnail.
    """
    try:
        check = await db.get_check_by_id(check_id)
        if not check:
            raise HTTPException(status_code=404, detail="Check not found")
        
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
        
        # Try to extract ArXiv ID
        import re
        arxiv_id_pattern = r'(\d{4}\.\d{4,5})(v\d+)?'
        arxiv_match = re.search(arxiv_id_pattern, paper_source)
        
        # Check if this is a direct PDF URL (not ArXiv)
        is_direct_pdf_url = (
            source_type == 'url' and
            paper_source.lower().endswith('.pdf') and 
            'arxiv.org' not in paper_source.lower()
        )
        
        if is_direct_pdf_url:
            # Generate thumbnail from direct PDF URL
            logger.info(f"Generating thumbnail from PDF URL: {paper_source}")
            import hashlib
            import tempfile
            import urllib.request
            
            pdf_hash = hashlib.md5(paper_source.encode()).hexdigest()[:12]
            pdf_path = os.path.join(tempfile.gettempdir(), f"refchecker_pdf_{pdf_hash}.pdf")
            
            # Download PDF if not already cached
            if not os.path.exists(pdf_path):
                try:
                    await asyncio.to_thread(lambda: urllib.request.urlretrieve(paper_source, pdf_path))
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
async def get_preview(check_id: int):
    """
    Get or generate a high-resolution preview for a check.
    
    Returns a larger preview image suitable for overlay display.
    For ArXiv papers, downloads the PDF and generates a preview of the first page.
    For uploaded PDFs, generates a preview from the file.
    """
    try:
        check = await db.get_check_by_id(check_id)
        if not check:
            raise HTTPException(status_code=404, detail="Check not found")
        
        # Generate preview based on source type
        paper_source = check.get('paper_source', '')
        source_type = check.get('source_type', 'url')
        
        # Try to extract ArXiv ID
        import re
        arxiv_id_pattern = r'(\d{4}\.\d{4,5})(v\d+)?'
        arxiv_match = re.search(arxiv_id_pattern, paper_source)
        
        # Check if this is a direct PDF URL (not ArXiv)
        is_direct_pdf_url = (
            source_type == 'url' and
            paper_source.lower().endswith('.pdf') and 
            'arxiv.org' not in paper_source.lower()
        )
        
        preview_path = None
        
        if is_direct_pdf_url:
            # Generate preview from direct PDF URL
            logger.info(f"Generating preview from PDF URL: {paper_source}")
            import hashlib
            import tempfile
            import urllib.request
            
            pdf_hash = hashlib.md5(paper_source.encode()).hexdigest()[:12]
            pdf_path = os.path.join(tempfile.gettempdir(), f"refchecker_pdf_{pdf_hash}.pdf")
            
            # Download PDF if not already cached
            if not os.path.exists(pdf_path):
                try:
                    await asyncio.to_thread(lambda: urllib.request.urlretrieve(paper_source, pdf_path))
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
async def get_pasted_text(check_id: int):
    """
    Get the pasted text content for a check.
    
    Returns the text file content as plain text for viewing.
    """
    try:
        check = await db.get_check_by_id(check_id)
        if not check:
            raise HTTPException(status_code=404, detail="Check not found")
        
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
async def get_uploaded_file(check_id: int):
    """
    Get the uploaded file content for a check.
    
    Returns the file for viewing/download.
    """
    try:
        check = await db.get_check_by_id(check_id)
        if not check:
            raise HTTPException(status_code=404, detail="Check not found")
        
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
async def get_bibliography_source(check_id: int):
    """
    Get the bibliography source content (bbl/bib file) for a check.
    
    Returns the bibliography file content as plain text for viewing.
    This is the actual source file used to extract references (from ArXiv source or pasted text).
    """
    try:
        check = await db.get_check_by_id(check_id)
        if not check:
            raise HTTPException(status_code=404, detail="Check not found")
        
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
async def recheck(check_id: int):
    """Re-run a previous check"""
    try:
        # Get original check
        original = await db.get_check_by_id(check_id)
        if not original:
            raise HTTPException(status_code=404, detail="Check not found")

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
            llm_model=llm_model
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
                None,  # API key will need to be retrieved separately
                None,  # Endpoint will need to be retrieved separately
                True,
                cancel_event
            )
        )
        active_checks[session_id] = {"task": task, "cancel_event": cancel_event, "check_id": new_check_id}

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
async def cancel_check(session_id: str):
    """Cancel an active check"""
    active = active_checks.get(session_id)
    if not active:
        raise HTTPException(status_code=404, detail="Active check not found")
    active["cancel_event"].set()
    active["task"].cancel()
    return {"message": "Cancellation requested"}


@app.delete("/api/history/{check_id}")
async def delete_check(check_id: int):
    """Delete a check from history"""
    try:
        success = await db.delete_check(check_id)
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
async def update_check_label(check_id: int, update: CheckLabelUpdate):
    """Update the custom label for a check"""
    try:
        success = await db.update_check_label(check_id, update.custom_label)
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
async def get_llm_configs():
    """Get all LLM configurations (API keys are not returned)"""
    try:
        configs = await db.get_llm_configs()
        return configs
    except Exception as e:
        logger.error(f"Error getting LLM configs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm-configs")
async def create_llm_config(config: LLMConfigCreate):
    """Create a new LLM configuration"""
    try:
        config_id = await db.create_llm_config(
            name=config.name,
            provider=config.provider,
            model=config.model,
            api_key=config.api_key,
            endpoint=config.endpoint
        )
        # Return the created config (without API key)
        return {
            "id": config_id,
            "name": config.name,
            "provider": config.provider,
            "model": config.model,
            "endpoint": config.endpoint,
            "is_default": False
        }
    except Exception as e:
        logger.error(f"Error creating LLM config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/llm-configs/{config_id}")
async def update_llm_config(config_id: int, config: LLMConfigUpdate):
    """Update an existing LLM configuration"""
    try:
        success = await db.update_llm_config(
            config_id=config_id,
            name=config.name,
            provider=config.provider,
            model=config.model,
            api_key=config.api_key,
            endpoint=config.endpoint
        )
        if success:
            # Get updated config
            updated = await db.get_llm_configs()
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
async def delete_llm_config(config_id: int):
    """Delete an LLM configuration"""
    try:
        success = await db.delete_llm_config(config_id)
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
async def set_default_llm_config(config_id: int):
    """Set an LLM configuration as the default"""
    try:
        success = await db.set_default_llm_config(config_id)
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
        logger.error(f"LLM validation failed: {error_msg}")
        # Extract useful error message
        if "404" in error_msg and "model" in error_msg.lower():
            raise HTTPException(status_code=400, detail=f"Invalid model name. The model '{config.model}' was not found.")
        elif "401" in error_msg or "unauthorized" in error_msg.lower():
            raise HTTPException(status_code=400, detail="Invalid API key")
        elif "rate" in error_msg.lower():
            raise HTTPException(status_code=400, detail="Rate limited - but API key is valid")
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
                
                # Update the global limiter immediately
                limiter = get_limiter()
                await limiter.set_max_concurrent(value)
                logger.info(f"Updated global concurrency limit to {value}")
                
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
async def clear_verification_cache():
    """Clear the verification cache"""
    try:
        count = await db.clear_verification_cache()
        logger.info(f"Cleared {count} entries from verification cache")
        return {"message": f"Cleared {count} cached verification results", "count": count}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/database")
async def clear_database():
    """Clear all data (cache + history) but keep settings and LLM configs"""
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
