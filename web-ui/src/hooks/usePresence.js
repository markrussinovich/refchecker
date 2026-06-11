import { useEffect, useRef, useState } from 'react'
import { createPresenceWebSocket } from '../utils/api'
import { useAuthStore } from '../stores/useAuthStore'
import { useHistoryStore } from '../stores/useHistoryStore'
import { logger } from '../utils/logger'

/**
 * Route a live per-check event (reference_result / summary_update) the server
 * fanned out over a batch's presence room into the history store, keyed by the
 * event's own `check_id` (R26). This is the team-member / non-owner half of
 * live collaboration: the member never opened a check-progress ("manager")
 * socket for someone else's check, so without this the stream would be dropped.
 *
 * It reuses the same idempotent history-store entry points the concurrent-
 * session path uses (`updateHistoryReference` / `updateHistoryProgress`), which
 * also update `selectedCheck` when the member has that check open. Both are
 * upserts/last-writer-wins, so a duplicate delivery (e.g. the owner also has a
 * manager socket open) is harmless; `seen` only avoids redundant writes.
 *
 * Returns true if the message was a live-results event we handled.
 */
function routeBatchRoomEvent(msg, seen) {
  const checkId = msg?.check_id
  if (!checkId) return false
  const history = useHistoryStore.getState()

  if (msg.type === 'reference_result' && typeof msg.index === 'number') {
    const refIndex = msg.index - 1
    if (refIndex < 0) return true
    // Dedup on check_id + ref index against double-delivery.
    const key = `${checkId}:${refIndex}`
    if (seen.has(key)) return true
    seen.add(key)
    const { type: _t, check_id: _c, index: _i, ...refData } = msg
    history.updateHistoryReference(checkId, refIndex, {
      ...refData,
      status: msg.status || 'checked',
    })
    return true
  }

  if (msg.type === 'summary_update') {
    history.updateHistoryProgress(checkId, {
      status: 'in_progress',
      total_refs: msg.total_refs,
      processed_refs: msg.processed_refs,
      errors_count: msg.errors_count,
      warnings_count: msg.warnings_count,
      suggestions_count: msg.suggestions_count,
      unverified_count: msg.unverified_count,
      hallucination_count: msg.hallucination_count || 0,
      verified_count: msg.verified_count,
      refs_with_errors: msg.refs_with_errors,
      refs_with_warnings_only: msg.refs_with_warnings_only,
      refs_with_suggestions_only: msg.refs_with_suggestions_only,
      refs_verified: msg.refs_verified,
    })
    return true
  }

  return false
}

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
  const seenRef = useRef(null)

  useEffect(() => {
    // No identity → no presence (and nothing to show).
    if (!roomId || !authRequired || !user) {
      setUsers([])
      return undefined
    }

    setUsers([])
    // Per-room dedup set for batch-room live results (check_id + ref index).
    seenRef.current = new Set()
    const ws = createPresenceWebSocket(String(roomId), {
      onMessage: (msg) => {
        // Presence roster events (presence_state/join/leave) carry `users`.
        if (Array.isArray(msg.users)) setUsers(msg.users)
        // Live per-check results the server fanned out to this batch room
        // (reference_result / summary_update) — route them into the stores so
        // team members see the stream, not just presence avatars (R26).
        else routeBatchRoomEvent(msg, seenRef.current)
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
