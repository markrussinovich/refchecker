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

    const existingConnections = Array.from(wsMapRef.current.keys())
    console.log(`[DEBUG-WS-MGR] Creating NEW WebSocket for session ${sessionId?.slice(0,8)}, existing connections: ${existingConnections.map(s=>s?.slice(0,8)).join(', ')}`)
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
