import { useEffect, useRef } from 'react'
import { createWebSocket } from '../utils/api'
import { useCheckStore } from '../stores/useCheckStore'
import { logger } from '../utils/logger'

/**
 * Manages multiple WebSocket connections - one per session.
 * Keeps old session connections alive so they can receive completed messages.
 * Also reconnects to in_progress sessions on page refresh.
 */
export default function LiveWebSocketManager() {
  const activeSessions = useCheckStore(state => state.activeSessions)
  const handleWebSocketMessage = useCheckStore(state => state.handleWebSocketMessage)
  const setError = useCheckStore(state => state.setError)
  const unregisterSession = useCheckStore(state => state.unregisterSession)
  
  // Map of sessionId -> WebSocket
  const wsMapRef = useRef(new Map())

  // Connect to all active sessions
  useEffect(() => {
    if (!activeSessions || activeSessions.length === 0) return

    // Connect to any sessions we don't have a connection for
    for (const sessionId of activeSessions) {
      if (wsMapRef.current.has(sessionId)) {
        continue // Already connected
      }

      console.log(`[DEBUG-WS-MGR] Creating WebSocket for session ${sessionId?.slice(0,8)}`)
      logger.info('LiveWebSocketManager', `Creating WebSocket for session ${sessionId}`)

      const ws = createWebSocket(sessionId, {
        onOpen: () => {
          console.log(`[DEBUG-WS-MGR] WebSocket CONNECTED for session ${sessionId?.slice(0,8)}`)
          logger.info('WebSocket', `Connected to session ${sessionId}`)
        },
        onMessage: (data) => {
          // Inject session_id into the message so the handler knows which session it's from
          const messageWithSession = { ...data, session_id: sessionId }
          console.log(`[DEBUG-WS-MGR] Message from ${sessionId?.slice(0,8)}: type=${data.type}`)
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
      }
    }
  }, [activeSessions, handleWebSocketMessage, setError, unregisterSession])

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
