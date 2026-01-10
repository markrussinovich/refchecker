import { useEffect, useRef } from 'react'
import { createWebSocket } from '../utils/api'
import { useCheckStore } from '../stores/useCheckStore'
import { logger } from '../utils/logger'

/**
 * Manages multiple WebSocket connections - one per session.
 * Keeps old session connections alive so they can receive completed messages.
 */
export default function LiveWebSocketManager() {
  const sessionId = useCheckStore(state => state.sessionId)
  const handleWebSocketMessage = useCheckStore(state => state.handleWebSocketMessage)
  const setError = useCheckStore(state => state.setError)
  
  // Map of sessionId -> WebSocket
  const wsMapRef = useRef(new Map())

  useEffect(() => {
    if (!sessionId) return

    // Already have a connection for this session
    if (wsMapRef.current.has(sessionId)) {
      logger.debug('LiveWebSocketManager', `Already connected to session ${sessionId}`)
      return
    }

    logger.info('LiveWebSocketManager', `Creating WebSocket for session ${sessionId}`)

    const ws = createWebSocket(sessionId, {
      onOpen: () => logger.info('WebSocket', `Connected to session ${sessionId}`),
      onMessage: (data) => {
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
      },
    })

    wsMapRef.current.set(sessionId, ws)

    // Cleanup: close all connections when component unmounts
    return () => {
      // Don't close on sessionId change - we want to keep receiving messages
      // Only close when component actually unmounts
    }
  }, [sessionId, handleWebSocketMessage, setError])

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
