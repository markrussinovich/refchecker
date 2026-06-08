import { useEffect, useRef, useState } from 'react'
import { createPresenceWebSocket } from '../utils/api'
import { useAuthStore } from '../stores/useAuthStore'
import { logger } from '../utils/logger'

/**
 * Realtime presence for a shared room (a batch id or check id) — issue #67.
 *
 * Opens a presence WebSocket to /api/ws/presence/{roomId} and keeps the live
 * roster of users currently viewing the same room. Presence is REAL: the list
 * only ever contains users whose sockets are actually connected right now. The
 * server drives the roster via presence_state / presence_join / presence_leave.
 *
 * Only connects when:
 *   - a roomId is provided, and
 *   - auth is enabled and the user is signed in (presence needs a real
 *     identity; there is no "team" to show in single-user mode).
 *
 * @param {string|number|null} roomId  batch/check id to subscribe to
 * @returns {Array<{user_id, name, email}>} live roster (includes self)
 */
export function usePresence(roomId) {
  const { user, authRequired } = useAuthStore()
  const [users, setUsers] = useState([])
  const wsRef = useRef(null)

  useEffect(() => {
    // No identity → no presence (and nothing to show).
    if (!roomId || !authRequired || !user) {
      setUsers([])
      return undefined
    }

    setUsers([])
    const ws = createPresenceWebSocket(String(roomId), {
      onMessage: (msg) => {
        // Every server message carries the authoritative roster.
        if (Array.isArray(msg.users)) setUsers(msg.users)
      },
      onClose: () => setUsers([]),
      onError: (e) => logger.warn('usePresence', 'WebSocket error', e),
    })
    wsRef.current = ws

    return () => {
      try { ws.close() } catch (_) { /* ignore */ }
      wsRef.current = null
    }
  }, [roomId, authRequired, user])

  return users
}
