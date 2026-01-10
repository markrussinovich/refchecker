import { useEffect } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { useCheckStore } from '../stores/useCheckStore'
import { logger } from '../utils/logger'

export default function LiveWebSocketManager() {
  const sessionId = useCheckStore(state => state.sessionId)
  const handleWebSocketMessage = useCheckStore(state => state.handleWebSocketMessage)
  const setError = useCheckStore(state => state.setError)

  const { connect, disconnect } = useWebSocket(sessionId, {
    onOpen: () => logger.info('WebSocket', 'Connected successfully'),
    onMessage: (data) => {
      logger.info('WebSocket', `Message received: ${data.type}`, data)
      handleWebSocketMessage(data)
    },
    onError: (error) => {
      logger.error('WebSocket', 'Connection error', { error: error.toString() })
      setError('Connection error')
    },
    onClose: (event) => {
      logger.info('WebSocket', `Closed with code ${event?.code || 'unknown'}`, { reason: event?.reason })
    },
  })

  useEffect(() => {
    if (sessionId) {
      connect()
      return () => disconnect()
    }
    disconnect()
    return undefined
  }, [sessionId, connect, disconnect])

  return null
}
