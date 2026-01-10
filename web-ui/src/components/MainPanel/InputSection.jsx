import { useState, useRef, useCallback } from 'react'
import Button from '../common/Button'
import FileDropZone from './FileDropZone'
import { useCheckStore } from '../../stores/useCheckStore'
import { useConfigStore } from '../../stores/useConfigStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useWebSocket } from '../../hooks/useWebSocket'
import { useFileUpload } from '../../hooks/useFileUpload'
import * as api from '../../utils/api'
import { logger } from '../../utils/logger'

/**
 * Input section for paper URL, ArXiv ID, or file upload
 */
export default function InputSection() {
  const [inputMode, setInputMode] = useState('url') // url, file, text
  const [inputValue, setInputValue] = useState('')
  const [textValue, setTextValue] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  
  const { 
    status, 
    sessionId,
    currentCheckId,
    startCheck, 
    reset,
    cancelCheck: storeCancelCheck,
    handleWebSocketMessage,
    setError,
    setCurrentCheckId,
  } = useCheckStore()
  
  const { getSelectedConfig } = useConfigStore()
  const { fetchHistory, clearSelection, selectCheck, updateHistoryItemTitle } = useHistoryStore()
  
  const fileUpload = useFileUpload()
  const wsRef = useRef(null)
  const currentCheckIdRef = useRef(null)

  // WebSocket handlers
  const wsHandlers = {
    onOpen: () => {
      logger.info('WebSocket', 'Connected successfully')
    },
    onMessage: (data) => {
      logger.info('WebSocket', `Message received: ${data.type}`, data)
      handleWebSocketMessage(data)
      
      // Update history item title when paper title is received
      if (data.type === 'title_updated' && data.paper_title && currentCheckIdRef.current) {
        updateHistoryItemTitle(currentCheckIdRef.current, data.paper_title)
      }
    },
    onError: (error) => {
      logger.error('WebSocket', 'Connection error', { error: error.toString() })
      setError('Connection error')
    },
    onClose: (event) => {
      logger.info('WebSocket', `Closed with code ${event?.code || 'unknown'}`, { reason: event?.reason })
    },
  }

  const { connect, disconnect } = useWebSocket(sessionId, wsHandlers)

  const handleSubmit = async () => {
    // Clear any previous history selection
    clearSelection()
    
    // Close any existing WebSocket connection from a previous check
    if (wsRef.current) {
      logger.info('WebSocket', 'Closing previous WebSocket connection before starting new check')
      wsRef.current.close()
      wsRef.current = null
    }
    
    // Validate input
    if (inputMode === 'url' && !inputValue.trim()) {
      logger.warn('InputSection', 'No URL/ArXiv ID provided')
      return
    }
    if (inputMode === 'file' && !fileUpload.file) {
      logger.warn('InputSection', 'No file selected')
      return
    }
    if (inputMode === 'text' && !textValue.trim()) {
      logger.warn('InputSection', 'No text provided')
      return
    }

    setIsSubmitting(true)
    
    try {
      // Get selected LLM config
      const config = getSelectedConfig()
      
      // Build form data
      const formData = new FormData()
      formData.append('source_type', inputMode === 'url' ? 'url' : inputMode === 'file' ? 'file' : 'text')
      
      if (inputMode === 'url') {
        formData.append('source_value', inputValue.trim())
      } else if (inputMode === 'file') {
        formData.append('file', fileUpload.file)
      } else {
        formData.append('source_text', textValue)
      }

      // Add LLM config
      if (config) {
        formData.append('llm_config_id', config.id.toString())
        formData.append('llm_provider', config.provider)
        if (config.model) {
          formData.append('llm_model', config.model)
        }
        formData.append('use_llm', 'true')
      } else {
        formData.append('use_llm', 'false')
      }

      logger.info('Check', 'Initiating check request', { 
        mode: inputMode, 
        llm: config?.provider,
        model: config?.model,
        source: inputMode === 'url' ? inputValue.trim() : (inputMode === 'file' ? fileUpload.file?.name : 'pasted text')
      })

      // Determine the source for display
      const displaySource = inputMode === 'url' 
        ? inputValue.trim() 
        : (inputMode === 'file' ? fileUpload.file?.name : 'Pasted text')

      // Start the check
      logger.info('API', 'Sending POST /api/check')
      const response = await api.startCheck(formData)
      const { session_id, check_id, message } = response.data
      
      logger.info('API', 'Check started successfully', { session_id, check_id, message })

      // Store the check_id for WebSocket handler to use
      currentCheckIdRef.current = check_id

      // Initialize check state with the check_id and source
      startCheck(session_id, check_id, displaySource)
      
      // Refresh history immediately to show the new in-progress entry
      fetchHistory()
      
      // Select the current check in history so user can navigate away and back
      selectCheck(check_id)

      // Connect WebSocket
      logger.info('WebSocket', `Connecting to session ${session_id}`)
      setTimeout(() => {
        wsRef.current = api.createWebSocket(session_id, wsHandlers)
      }, 100)

    } catch (error) {
      logger.error('InputSection', 'Failed to start check', error)
      setError(error.response?.data?.detail || error.message || 'Failed to start check')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleCancel = async () => {
    if (!sessionId) return
    
    try {
      logger.info('InputSection', `Cancelling check ${sessionId}`)
      await api.cancelCheck(sessionId)
      
      // Update store immediately
      storeCancelCheck()
      
      // Close WebSocket
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    } catch (error) {
      logger.error('InputSection', 'Failed to cancel', error)
      // Still update the store to reflect cancellation intent
      storeCancelCheck()
    }
  }

  const handleRestart = () => {
    reset()
    // Refresh history to include the completed check
    fetchHistory()
  }

  // Get selectedCheckId to determine if we're on the "New refcheck" placeholder
  const { selectedCheckId } = useHistoryStore.getState()
  const isNewRefcheckMode = selectedCheckId === -1
  
  // Only consider it "checking" if we're not in "new refcheck" mode
  // This allows starting a new check while another is running
  const isChecking = status === 'checking' && !isNewRefcheckMode
  const isComplete = (status === 'completed' || status === 'cancelled' || status === 'error') && !isNewRefcheckMode

  return (
    <div 
      className="rounded-lg border p-6"
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)',
      }}
    >
      <h2 
        className="text-lg font-semibold mb-4"
        style={{ color: 'var(--color-text-primary)' }}
      >
        Check Paper References
      </h2>

      {/* Input mode tabs */}
      <div className="flex gap-2 mb-4">
        {[
          { id: 'url', label: 'URL / ArXiv ID' },
          { id: 'file', label: 'Upload File' },
          { id: 'text', label: 'Paste Text' },
        ].map(mode => (
          <button
            key={mode.id}
            onClick={() => setInputMode(mode.id)}
            disabled={isChecking}
            className="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
            style={{
              backgroundColor: inputMode === mode.id 
                ? 'var(--color-accent)' 
                : 'var(--color-bg-tertiary)',
              color: inputMode === mode.id 
                ? '#ffffff' 
                : 'var(--color-text-secondary)',
              cursor: isChecking ? 'not-allowed' : 'pointer',
            }}
          >
            {mode.label}
          </button>
        ))}
      </div>

      {/* Input area based on mode */}
      <div className="mb-4">
        {inputMode === 'url' && (
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Enter ArXiv ID (e.g., 2401.12345) or URL"
            disabled={isChecking}
            className="w-full px-4 py-3 rounded-lg border focus:outline-none focus:ring-2"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          />
        )}

        {inputMode === 'file' && (
          <FileDropZone 
            file={fileUpload.file}
            isDragging={fileUpload.isDragging}
            error={fileUpload.error}
            onDragEnter={fileUpload.handleDragEnter}
            onDragLeave={fileUpload.handleDragLeave}
            onDragOver={fileUpload.handleDragOver}
            onDrop={fileUpload.handleDrop}
            onFileSelect={fileUpload.handleInputChange}
            onClear={fileUpload.clearFile}
            disabled={isChecking}
          />
        )}

        {inputMode === 'text' && (
          <textarea
            value={textValue}
            onChange={(e) => setTextValue(e.target.value)}
            placeholder="Paste bibliography text here..."
            disabled={isChecking}
            rows={6}
            className="w-full px-4 py-3 rounded-lg border focus:outline-none focus:ring-2 resize-y"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          />
        )}
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-3">
        {!isChecking && !isComplete && (
          <Button 
            onClick={handleSubmit}
            loading={isSubmitting}
            disabled={
              (inputMode === 'url' && !inputValue.trim()) ||
              (inputMode === 'file' && !fileUpload.file) ||
              (inputMode === 'text' && !textValue.trim())
            }
          >
            Check References
          </Button>
        )}

        {isComplete && (
          <Button 
            onClick={handleRestart}
          >
            New Check
          </Button>
        )}

        {/* LLM indicator */}
        {!isComplete && (
          <span 
            className="text-sm"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {(() => {
              const config = getSelectedConfig()
              if (config) {
                return `Using ${config.name} (${config.provider})`
              }
              return 'No LLM configured - using regex extraction'
            })()}
          </span>
        )}
      </div>
    </div>
  )
}
