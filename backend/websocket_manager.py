"""
WebSocket connection manager for real-time updates
"""
import asyncio
import json
import time
from typing import Dict, Set
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)

# Pending message buffers older than this are discarded
_PENDING_MAX_AGE_SECONDS = 300  # 5 minutes


class ConnectionManager:
    """Manages WebSocket connections for real-time updates"""

    def __init__(self):
        # Map of session_id -> set of websocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # Buffer early messages sent before WebSocket connects
        self._pending_messages: Dict[str, list] = {}
        # Track when each pending buffer was created
        self._pending_timestamps: Dict[str, float] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept a new WebSocket connection and replay any buffered messages"""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        self.active_connections[session_id].add(websocket)
        logger.info(f"WebSocket connected for session: {session_id}")

        # Replay buffered messages
        pending = self._pending_messages.pop(session_id, [])
        self._pending_timestamps.pop(session_id, None)
        if pending:
            logger.info(f"Replaying {len(pending)} buffered messages for session {session_id}")
            for msg_json in pending:
                try:
                    await websocket.send_text(msg_json)
                except Exception as e:
                    logger.error(f"Error replaying buffered message: {e}")
                    break

    def disconnect(self, websocket: WebSocket, session_id: str):
        """Remove a WebSocket connection"""
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
        logger.info(f"WebSocket disconnected for session: {session_id}")

    def _evict_stale_pending(self):
        """Remove pending message buffers that have been waiting too long."""
        now = time.monotonic()
        stale = [
            sid for sid, ts in self._pending_timestamps.items()
            if now - ts > _PENDING_MAX_AGE_SECONDS
        ]
        for sid in stale:
            self._pending_messages.pop(sid, None)
            self._pending_timestamps.pop(sid, None)
        if stale:
            logger.info(f"Evicted {len(stale)} stale pending message buffers")

    async def send_message(self, session_id: str, message_type: str, data: dict):
        """Send a message to all connections for a session, buffering if none connected yet"""
        # Flatten structure: frontend expects {type, session_id, ...data}
        message = {"type": message_type, "session_id": session_id, **data}
        message_json = json.dumps(message)

        if session_id not in self.active_connections:
            # Buffer the message for replay when the WebSocket connects
            if session_id not in self._pending_messages:
                self._pending_messages[session_id] = []
                self._pending_timestamps[session_id] = time.monotonic()
            # Cap buffer to avoid unbounded memory growth
            if len(self._pending_messages[session_id]) < 500:
                self._pending_messages[session_id].append(message_json)
            # Periodically evict stale buffers
            self._evict_stale_pending()
            return
        
        logger.debug(f"Sending {message_type} to session {session_id}: {message_json[:200]}...")

        # Send to all connections for this session
        disconnected = set()
        for websocket in self.active_connections[session_id]:
            try:
                await websocket.send_text(message_json)
            except Exception as e:
                logger.error(f"Error sending message to websocket: {e}")
                disconnected.add(websocket)

        # Clean up disconnected websockets
        for ws in disconnected:
            self.disconnect(ws, session_id)

    async def broadcast_started(self, session_id: str, paper_title: str, paper_source: str):
        """Broadcast that checking has started"""
        await self.send_message(session_id, "started", {
            "paper_title": paper_title,
            "paper_source": paper_source
        })

    async def broadcast_extracting(self, session_id: str):
        """Broadcast that references are being extracted"""
        await self.send_message(session_id, "extracting", {
            "message": "Extracting references from paper..."
        })

    async def broadcast_progress(self, session_id: str, current: int, total: int):
        """Broadcast progress update"""
        await self.send_message(session_id, "progress", {
            "current": current,
            "total": total,
            "percent": round((current / total * 100) if total > 0 else 0, 1)
        })

    async def broadcast_reference_result(self, session_id: str, reference_data: dict):
        """Broadcast a reference checking result"""
        await self.send_message(session_id, "reference_result", reference_data)

    async def broadcast_summary_update(self, session_id: str, summary: dict):
        """Broadcast updated summary statistics"""
        await self.send_message(session_id, "summary_update", summary)

    async def broadcast_completed(self, session_id: str, final_summary: dict):
        """Broadcast that checking is complete"""
        await self.send_message(session_id, "completed", final_summary)

    async def broadcast_error(self, session_id: str, error_message: str, error_details: str = ""):
        """Broadcast an error"""
        await self.send_message(session_id, "error", {
            "message": error_message,
            "details": error_details
        })


# Global connection manager instance
manager = ConnectionManager()
