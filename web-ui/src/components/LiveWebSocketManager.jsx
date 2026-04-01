import { useEffect, useRef } from 'react'
import { createWebSocket, getCheckDetail } from '../utils/api'
import { useCheckStore } from '../stores/useCheckStore'
import { useHistoryStore } from '../stores/useHistoryStore'
import { logger } from '../utils/logger'

/**
 * Manages multiple WebSocket connections - one per session.
 * Keeps old session connections alive so they can receive completed messages.
 * Also reconnects to in_progress sessions on page refresh.
 * Includes a polling fallback to recover from lost WebSocket messages.
 */
export default function LiveWebSocketManager() {
  const activeSessions = useCheckStore(state => state.activeSessions)
  const handleWebSocketMessage = useCheckStore(state => state.handleWebSocketMessage)
  const setError = useCheckStore(state => state.setError)
  const unregisterSession = useCheckStore(state => state.unregisterSession)
  
  // Map of sessionId -> WebSocket
  const wsMapRef = useRef(new Map())
  // Track last WS message time per session for stale detection
  const lastMessageTimeRef = useRef(new Map())

  // Connect to all active sessions
  useEffect(() => {
    if (!activeSessions || activeSessions.length === 0) return

    // Connect to any sessions we don't have a connection for
    for (const sessionId of activeSessions) {
      if (wsMapRef.current.has(sessionId)) {
        continue // Already connected
      }

      logger.info('LiveWebSocketManager', `Creating WebSocket for session ${sessionId}`)
      lastMessageTimeRef.current.set(sessionId, Date.now())

      const ws = createWebSocket(sessionId, {
        onOpen: () => {
          logger.info('WebSocket', `Connected to session ${sessionId}`)
        },
        onMessage: (data) => {
          lastMessageTimeRef.current.set(sessionId, Date.now())
          // Inject session_id into the message so the handler knows which session it's from
          const messageWithSession = { ...data, session_id: sessionId }
          logger.info('WebSocket', `Message from ${sessionId}: ${data.type}`, data)
          handleWebSocketMessage(messageWithSession)
        },
        onError: (error) => {
          logger.error('WebSocket', `Error on session ${sessionId}`, { error: error?.toString() })
          // Only set error for the current session
          if (useCheckStore.getState().sessionId === sessionId) {
            setError('Connection error')
          }
        },
        onClose: (event) => {
          logger.info('WebSocket', `Session ${sessionId} closed with code ${event?.code || 'unknown'}`)
          wsMapRef.current.delete(sessionId)
          // Don't unregister - the session might still be active on the server
        },
      })

      wsMapRef.current.set(sessionId, ws)
    }

    // Close connections for sessions that are no longer active
    for (const [sessionId, ws] of wsMapRef.current.entries()) {
      if (!activeSessions.includes(sessionId)) {
        logger.info('LiveWebSocketManager', `Closing WebSocket for inactive session ${sessionId}`)
        ws.close()
        wsMapRef.current.delete(sessionId)
        lastMessageTimeRef.current.delete(sessionId)
      }
    }
  }, [activeSessions, handleWebSocketMessage, setError, unregisterSession])

  // Polling fallback: detect stalled checks and recover from lost WS messages
  useEffect(() => {
    const POLL_INTERVAL = 10_000 // Check every 10 seconds
    const STALE_THRESHOLD = 15_000 // Consider stale after 15 seconds without a message

    const interval = setInterval(async () => {
      const store = useCheckStore.getState()

      // Poll the current (active) check
      if (store.status === 'checking' && store.currentCheckId) {
        const sessionId = store.sessionId
        const lastMsg = lastMessageTimeRef.current.get(sessionId)
        if (!lastMsg || Date.now() - lastMsg >= STALE_THRESHOLD) {
          logger.info('LiveWebSocketManager', `No WS messages for ${sessionId} in ${STALE_THRESHOLD}ms, polling backend`)
          try {
            const detail = (await getCheckDetail(store.currentCheckId)).data
            if (detail) {
              if (detail.status === 'completed' || detail.status === 'error' || detail.status === 'cancelled') {
                logger.info('LiveWebSocketManager', `Recovered stale check ${store.currentCheckId}: status=${detail.status}`)

                const results = Array.isArray(detail.results) ? detail.results : []
                const verifiedCount = Math.max(
                  (detail.total_refs || 0) - (detail.errors_count || 0) -
                  (detail.warnings_count || 0) - (detail.suggestions_count || 0) -
                  (detail.unverified_count || 0), 0)

                useCheckStore.setState({
                  status: detail.status,
                  statusMessage: detail.status === 'completed' ? 'Check completed' :
                                detail.status === 'error' ? 'Check failed' : 'Check cancelled',
                  paperTitle: detail.paper_title || store.paperTitle,
                  references: results.map((ref, index) => ({
                    ...ref, index,
                    status: ref.status || 'checked',
                    errors: ref.errors || [],
                    warnings: ref.warnings || [],
                    authoritative_urls: ref.authoritative_urls || [],
                  })),
                  stats: {
                    total_refs: detail.total_refs || 0,
                    processed_refs: detail.total_refs || 0,
                    verified_count: verifiedCount,
                    errors_count: detail.errors_count || 0,
                    warnings_count: detail.warnings_count || 0,
                    suggestions_count: detail.suggestions_count || 0,
                    unverified_count: detail.unverified_count || 0,
                    hallucination_count: detail.hallucination_count || 0,
                    refs_with_errors: detail.refs_with_errors || 0,
                    refs_with_warnings_only: detail.refs_with_warnings_only || 0,
                    refs_verified: detail.refs_verified || verifiedCount,
                    progress_percent: 100,
                  },
                  completedCheckId: detail.status === 'completed' ? detail.id : null,
                })

                // Update history store too
                useHistoryStore.getState().fetchHistory()
              } else if (detail.status === 'in_progress' && Array.isArray(detail.results) && detail.results.length > 0) {
                // Check is still in progress but we have partial results - sync them
                const processedRefs = detail.results.filter(
                  r => r && r.status && r.status !== 'pending' && r.status !== 'checking'
                ).length
                if (processedRefs > (store.stats?.processed_refs || 0)) {
                  logger.info('LiveWebSocketManager', `Syncing partial progress: ${processedRefs} refs processed`)
                  lastMessageTimeRef.current.set(sessionId, Date.now())
                  store.setStatusMessage(`Checking references (${processedRefs}/${detail.total_refs || '?'})...`)
                  store.setReferences(detail.results)
                }
              }
            }
          } catch (err) {
            logger.warn('LiveWebSocketManager', 'Stale check poll failed', err?.message)
          }
        }
      }

      // Poll non-current sessions (other batch checks) that may have stale WS connections
      const otherSessions = store.activeSessions.filter(s => s !== store.sessionId)
      for (const otherSessionId of otherSessions) {
        const lastMsg = lastMessageTimeRef.current.get(otherSessionId)
        if (lastMsg && Date.now() - lastMsg < STALE_THRESHOLD) continue

        const checkId = store.sessionToCheckMap[otherSessionId]
        if (!checkId) continue

        // Check if this history item is still in_progress (skip if already resolved)
        const historyItem = useHistoryStore.getState().history.find(h => h.id === checkId)
        if (!historyItem || historyItem.status !== 'in_progress') {
          // Already resolved — unregister to stop polling
          store.unregisterSession(otherSessionId)
          continue
        }

        try {
          const detail = (await getCheckDetail(checkId)).data
          if (!detail) continue

          if (detail.status !== 'in_progress') {
            logger.info('LiveWebSocketManager', `Recovered stale other-session check ${checkId}: status=${detail.status}`)
            useHistoryStore.getState().updateHistoryProgress(checkId, {
              status: detail.status,
              total_refs: detail.total_refs || 0,
              processed_refs: detail.total_refs || 0,
              errors_count: detail.errors_count || 0,
              warnings_count: detail.warnings_count || 0,
              suggestions_count: detail.suggestions_count || 0,
              unverified_count: detail.unverified_count || 0,
              hallucination_count: detail.hallucination_count || 0,
              refs_with_errors: detail.refs_with_errors || 0,
              refs_with_warnings_only: detail.refs_with_warnings_only || 0,
              refs_verified: detail.refs_verified || 0,
            })
            // Clean up completed session
            store.unregisterSession(otherSessionId)
          } else {
            // Still in progress — update timestamp so we don't poll again immediately
            lastMessageTimeRef.current.set(otherSessionId, Date.now())
            // Sync progress if ahead
            const results = Array.isArray(detail.results) ? detail.results : []
            const processedRefs = results.filter(
              r => r && r.status && r.status !== 'pending' && r.status !== 'checking'
            ).length
            if (processedRefs > (historyItem.processed_refs || 0)) {
              useHistoryStore.getState().updateHistoryProgress(checkId, {
                status: 'in_progress',
                total_refs: detail.total_refs || 0,
                processed_refs: processedRefs,
                errors_count: detail.errors_count || 0,
                warnings_count: detail.warnings_count || 0,
                suggestions_count: detail.suggestions_count || 0,
                unverified_count: detail.unverified_count || 0,
                hallucination_count: detail.hallucination_count || 0,
              })
            }
          }
        } catch (err) {
          logger.warn('LiveWebSocketManager', `Stale poll failed for session ${otherSessionId}`, err?.message)
        }
      }
    }, POLL_INTERVAL)

    return () => clearInterval(interval)
  }, [])

  // Cleanup all connections on unmount
  useEffect(() => {
    return () => {
      logger.info('LiveWebSocketManager', 'Unmounting, closing all WebSocket connections')
      wsMapRef.current.forEach((ws, sid) => {
        logger.info('LiveWebSocketManager', `Closing connection to session ${sid}`)
        ws.close()
      })
      wsMapRef.current.clear()
    }
  }, [])

  return null
}
