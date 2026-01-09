"""
FastAPI application for RefChecker Web UI
"""
import asyncio
import uuid
import os
import tempfile
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging

from database import db
from websocket_manager import manager
from refchecker_wrapper import ProgressRefChecker
from models import CheckRequest, CheckHistoryItem

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

# Configure CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://localhost:5175", "http://127.0.0.1:5174", "http://127.0.0.1:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Track active check sessions
active_checks = {}


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    await db.init_db()
    logger.info("Database initialized")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "message": "RefChecker Web UI API"}


@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


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
        if llm_config_id and use_llm:
            config = await db.get_llm_config_by_id(llm_config_id)
            if config:
                api_key = config.get('api_key')
                llm_provider = config.get('provider', llm_provider)
                llm_model = config.get('model') or llm_model
                logger.info(f"Using LLM config {llm_config_id}: {llm_provider}/{llm_model}")
            else:
                logger.warning(f"LLM config {llm_config_id} not found")

        # Handle file upload or pasted text
        paper_source = source_value
        if source_type == "file" and file:
            # Save uploaded file to temp directory
            temp_dir = tempfile.gettempdir()
            file_path = Path(temp_dir) / f"refchecker_{session_id}_{file.filename}"
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
            paper_source = str(file_path)
        elif source_type == "text":
            if not source_text:
                raise HTTPException(status_code=400, detail="No text provided")
            paper_source = source_text

        if not paper_source:
            raise HTTPException(status_code=400, detail="No source provided")

        # Start check in background
        cancel_event = asyncio.Event()
        task = asyncio.create_task(
            run_check(session_id, paper_source, source_type, llm_provider, llm_model, api_key, use_llm, cancel_event)
        )
        active_checks[session_id] = {"task": task, "cancel_event": cancel_event}

        return {
            "session_id": session_id,
            "message": "Check started",
            "source": paper_source
        }

    except Exception as e:
        logger.error(f"Error starting check: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def run_check(
    session_id: str,
    paper_source: str,
    source_type: str,
    llm_provider: str,
    llm_model: Optional[str],
    api_key: Optional[str],
    use_llm: bool,
    cancel_event: asyncio.Event
):
    """
    Run reference check in background and emit progress updates

    Args:
        session_id: Unique session ID
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

        # Create progress callback
        async def progress_callback(event_type: str, data: dict):
            await manager.send_message(session_id, event_type, data)

        # Create checker with progress callback
        checker = ProgressRefChecker(
            llm_provider=llm_provider,
            llm_model=llm_model,
            api_key=api_key,
            use_llm=use_llm,
            progress_callback=progress_callback,
            cancel_event=cancel_event
        )

        # Run the check
        result = await checker.check_paper(paper_source, source_type)

        # Save to database
        await db.save_check(
            paper_title=result["paper_title"],
            paper_source=result["paper_source"],
            source_type=source_type,
            total_refs=result["summary"]["total_refs"],
            errors_count=result["summary"]["errors_count"],
            warnings_count=result["summary"]["warnings_count"],
            unverified_count=result["summary"]["unverified_count"],
            results=result["references"],
            llm_provider=llm_provider,
            llm_model=llm_model
        )

        # Cleanup temp file if it was uploaded
        if source_type == "file" and paper_source.startswith(tempfile.gettempdir()):
            try:
                os.unlink(paper_source)
            except:
                pass

    except asyncio.CancelledError:
        logger.info(f"Check cancelled: {session_id}")
        await manager.send_message(session_id, "cancelled", {"message": "Check cancelled"})
    except Exception as e:
        logger.error(f"Error in run_check: {e}", exc_info=True)
        await manager.broadcast_error(
            session_id,
            f"Check failed: {str(e)}",
            type(e).__name__
        )
    finally:
        active_checks.pop(session_id, None)


@app.get("/api/history")
async def get_history(limit: int = 50):
    """Get check history"""
    try:
        history = await db.get_history(limit)
        return history  # Return array directly
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
        return check
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting check detail: {e}", exc_info=True)
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

        # Start check in background
        cancel_event = asyncio.Event()
        task = asyncio.create_task(
            run_check(
                session_id,
                source,
                source_type,
                original.get("llm_provider", "anthropic"),
                original.get("llm_model"),
                True,
                cancel_event
            )
        )
        active_checks[session_id] = {"task": task, "cancel_event": cancel_event}

        return {
            "session_id": session_id,
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
        else:
            raise HTTPException(status_code=400, detail=f"Validation failed: {error_msg}")


# Semantic Scholar API Key endpoints

class SemanticScholarKeyUpdate(BaseModel):
    api_key: str


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
