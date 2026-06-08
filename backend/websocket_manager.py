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


class PresenceManager:
    """Tracks which authenticated users are viewing a shared room (batch/check id).

    A "room" is any opaque string id (a batch id, a check id, …). Each connected
    WebSocket carries a user identity (from auth); the manager broadcasts
    presence join/leave events to the other connections in the same room and can
    hand a newcomer the current roster. Presence is real — it reflects only the
    sockets that are actually connected right now (issue #67).
    """

    def __init__(self):
        # room_id -> { websocket -> user dict {user_id, name, email} }
        self._rooms: Dict[str, Dict[WebSocket, dict]] = {}

    @staticmethod
    def _roster(members: Dict[WebSocket, dict]) -> list:
        """Deduplicate by user_id so a user with multiple tabs counts once.

        Entries without a real ``user_id`` (e.g. a malformed/anonymous token)
        are skipped: they are not authenticated identities, and treating them
        all as the same ``None`` key would collapse every such connection into
        a single bogus roster entry (and could shadow real users).
        """
        seen: Dict[int, dict] = {}
        for user in members.values():
            uid = user.get("user_id")
            if uid is None or uid in seen:
                continue
            seen[uid] = user
        return list(seen.values())

    def roster(self, room_id: str) -> list:
        """Current de-duplicated list of users present in a room."""
        return self._roster(self._rooms.get(room_id, {}))

    async def join(self, websocket: WebSocket, room_id: str, user: dict):
        """Register a connection in a room and notify everyone of the new roster.

        The websocket must already be accepted by the caller. Sends the joiner
        the full current roster (type ``presence_state``) and broadcasts a
        ``presence_join`` to the others.
        """
        members = self._rooms.setdefault(room_id, {})
        uid = user.get("user_id")
        # A None user_id is not a real identity; never treat two such
        # connections as "the same user already present".
        already_present = uid is not None and any(
            m.get("user_id") == uid for m in members.values()
        )
        members[websocket] = user

        # Tell the newcomer who is already here.
        await self._send(websocket, {
            "type": "presence_state",
            "room_id": room_id,
            "users": self.roster(room_id),
        })

        # Notify others only when this user wasn't already represented by
        # another tab — avoids spurious join spam on reconnects/extra tabs.
        if not already_present:
            await self._broadcast(room_id, {
                "type": "presence_join",
                "room_id": room_id,
                "user": user,
                "users": self.roster(room_id),
            }, exclude=websocket)
        logger.info(f"Presence join: user {user.get('user_id')} -> room {room_id}")

    async def leave(self, websocket: WebSocket, room_id: str):
        """Remove a connection from a room and broadcast a leave if the user is fully gone."""
        members = self._rooms.get(room_id)
        if not members or websocket not in members:
            return
        user = members.pop(websocket)
        if not members:
            del self._rooms[room_id]

        uid = user.get("user_id")
        still_present = uid is not None and any(
            m.get("user_id") == uid
            for m in self._rooms.get(room_id, {}).values()
        )
        if not still_present:
            await self._broadcast(room_id, {
                "type": "presence_leave",
                "room_id": room_id,
                "user": user,
                "users": self.roster(room_id),
            })
        logger.info(f"Presence leave: user {user.get('user_id')} -> room {room_id}")

    async def _broadcast(self, room_id: str, message: dict, exclude: WebSocket = None):
        message_json = json.dumps(message)
        for ws in list(self._rooms.get(room_id, {}).keys()):
            if ws is exclude:
                continue
            await self._send(ws, message_json)

    @staticmethod
    async def _send(websocket: WebSocket, message):
        message_json = message if isinstance(message, str) else json.dumps(message)
        try:
            await websocket.send_text(message_json)
        except Exception as e:
            logger.error(f"Error sending presence message: {e}")


# Global connection manager instance
manager = ConnectionManager()

# Global presence manager instance (issue #67)
presence = PresenceManager()
