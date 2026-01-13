import { useState } from 'react'
import Button from '../common/Button'
import FileDropZone from './FileDropZone'
import { useCheckStore } from '../../stores/useCheckStore'
import { useConfigStore } from '../../stores/useConfigStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
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
    startCheck, 
    reset,
    cancelCheck: storeCancelCheck,
    setError,
  } = useCheckStore()
  
  const { getSelectedConfig } = useConfigStore()
  const { fetchHistory, clearSelection, selectCheck } = useHistoryStore()
  
  const fileUpload = useFileUpload()

  const handleSubmit = async () => {
    // Clear any previous history selection
    clearSelection()
    
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
      
      // Map inputMode to sourceType
      const sourceType = inputMode === 'url' ? 'url' : (inputMode === 'file' ? 'file' : 'text')
      
      // For file uploads, the filename becomes the paper title
      const displayTitle = inputMode === 'file' ? fileUpload.file?.name : null

      // Start the check
      logger.info('API', 'Sending POST /api/check')
      const response = await api.startCheck(formData)
      const { session_id, check_id, message } = response.data
      
      logger.info('API', 'Check started successfully', { session_id, check_id, message })

      // Initialize check state with the check_id, source, sourceType, and title
      startCheck(session_id, check_id, displaySource, sourceType, displayTitle)

      // IMPORTANT: Add to history IMMEDIATELY so WebSocket updates have a target
      // This prevents race conditions where messages arrive before fetchHistory completes
      const { addToHistory } = useHistoryStore.getState()
      addToHistory({
        id: check_id,
        paper_title: displayTitle || displaySource,
        paper_source: displaySource,
        source_type: sourceType,
        custom_label: null,
        timestamp: new Date().toISOString(),
        total_refs: 0,
        errors_count: 0,
        warnings_count: 0,
        unverified_count: 0,
        llm_provider: config?.provider || null,
        llm_model: config?.model || null,
        status: 'in_progress',
        session_id: session_id,
      })
      
      // Select the current check in history so user can navigate away and back
      selectCheck(check_id)

    } catch (error) {
      logger.error('InputSection', 'Failed to start check', error)
      setError(error.response?.data?.detail || error.message || 'Failed to start check')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleCancel = async () => {
    const { sessionId } = useCheckStore.getState()
    if (!sessionId) return

    try {
      logger.info('InputSection', `Cancelling check ${sessionId}`)
      await api.cancelCheck(sessionId)
      
      // Update store immediately
      storeCancelCheck()
      
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
            onMouseEnter={(e) => {
              if (!isChecking && inputMode !== mode.id) {
                e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
                e.currentTarget.style.color = 'var(--color-text-primary)'
              }
            }}
            onMouseLeave={(e) => {
              if (inputMode !== mode.id) {
                e.currentTarget.style.backgroundColor = 'var(--color-bg-tertiary)'
                e.currentTarget.style.color = 'var(--color-text-secondary)'
              }
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
