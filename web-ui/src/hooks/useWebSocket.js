import { useRef, useCallback, useEffect } from 'react'
import { createWebSocket } from '../utils/api'
import { logger } from '../utils/logger'

/**
 * Hook for managing WebSocket connections
 * @param {string} sessionId - Session ID for the WebSocket
 * @param {object} handlers - Event handlers
 * @returns {object} WebSocket control functions
 */
export function useWebSocket(sessionId, handlers) {
  const wsRef = useRef(null)
  const handlersRef = useRef(handlers)
  
  // Keep handlers ref updated
  useEffect(() => {
    handlersRef.current = handlers
  }, [handlers])

  const connect = useCallback(() => {
    if (!sessionId) {
      logger.warn('useWebSocket', 'No session ID provided')
      return
    }

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      logger.debug('useWebSocket', 'Already connected')
      return
    }

    wsRef.current = createWebSocket(sessionId, {
      onOpen: () => handlersRef.current.onOpen?.(),
      onMessage: (data) => handlersRef.current.onMessage?.(data),
      onError: (error) => handlersRef.current.onError?.(error),
      onClose: (event) => handlersRef.current.onClose?.(event),
    })
  }, [sessionId])

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      logger.info('useWebSocket', 'Disconnecting')
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  const send = useCallback((data) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    } else {
      logger.warn('useWebSocket', 'Cannot send - not connected')
    }
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect()
    }
  }, [disconnect])

  return {
    connect,
    disconnect,
    send,
    isConnected: wsRef.current?.readyState === WebSocket.OPEN,
  }
}
