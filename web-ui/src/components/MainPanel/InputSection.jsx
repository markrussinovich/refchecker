import { useState } from 'react'
import Button from '../common/Button'
import FileDropZone from './FileDropZone'
import BulkInputZone from './BulkInputZone'
import { useCheckStore } from '../../stores/useCheckStore'
import { useConfigStore } from '../../stores/useConfigStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useKeyStore } from '../../stores/useKeyStore'
import { useShallow } from 'zustand/react/shallow'
import { useFileUpload } from '../../hooks/useFileUpload'
import * as api from '../../utils/api'
import { logger } from '../../utils/logger'

function getConfigApiKey(keyStore, config) {
  if (!config) return null
  return keyStore.getKey(`llm:${config.id}`) || keyStore.getKey(config.provider)
}

/**
 * Sanitize URL input - detect and fix duplicated URLs
 * E.g., "https://arxiv.org/abs/123https://arxiv.org/abs/123" -> "https://arxiv.org/abs/123"
 */
function sanitizeUrlInput(input) {
  if (!input) return input
  const trimmed = input.trim()
  
  // Check if the string contains a duplicated URL (URL appears twice consecutively)
  // Pattern: URL immediately followed by the same URL (or similar URL with http/https variation)
  const urlPattern = /^(https?:\/\/[^\s]+?)(https?:\/\/)/i
  const match = trimmed.match(urlPattern)
  if (match) {
    // Return just the first URL (before the second http/https)
    return match[1]
  }
  
  return trimmed
}

/**
 * Input section for paper URL, ArXiv ID, or file upload
 */
export default function InputSection() {
  const [inputMode, setInputMode] = useState('url') // url, file, text, bulk
  const [inputValue, setInputValue] = useState('')
  const [textValue, setTextValue] = useState('')
  const [bulkUrls, setBulkUrls] = useState('')
  const [bulkFiles, setBulkFiles] = useState([])
  const [bulkMode, setBulkMode] = useState('urls') // urls or files
  const [isSubmitting, setIsSubmitting] = useState(false)
  
  const { 
    status, 
    startCheck, 
    reset,
    setError,
  } = useCheckStore(useShallow(s => ({
    status: s.status,
    startCheck: s.startCheck,
    reset: s.reset,
    setError: s.setError,
  })))
  
  const { getSelectedExtractionConfig, getSelectedHallucinationConfig, getSelectedConfig } = useConfigStore()
  const { fetchHistory, clearSelection, selectCheck } = useHistoryStore()
  
  const fileUpload = useFileUpload()

  const handleSubmit = async () => {
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
      // Get selected LLM configs
      const config = getSelectedExtractionConfig?.() || getSelectedConfig()
      const hallucinationConfig = getSelectedHallucinationConfig?.() || config
      
      // Sanitize URL input to handle duplicated URLs (e.g., from double paste)
      const sanitizedUrl = inputMode === 'url' ? sanitizeUrlInput(inputValue) : null
      
      // Build form data
      const formData = new FormData()
      formData.append('source_type', inputMode === 'url' ? 'url' : inputMode === 'file' ? 'file' : 'text')
      
      if (inputMode === 'url') {
        formData.append('source_value', sanitizedUrl)
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
        if (hallucinationConfig) {
          formData.append('hallucination_config_id', hallucinationConfig.id.toString())
          formData.append('hallucination_provider', hallucinationConfig.provider)
          if (hallucinationConfig.model) {
            formData.append('hallucination_model', hallucinationConfig.model)
          }
        }
      } else {
        formData.append('use_llm', 'false')
      }

      // Attach per-tab API keys from the in-memory browser store.
      const keyStore = useKeyStore.getState()
      const llmKey = getConfigApiKey(keyStore, config)
      const hallucinationKey = getConfigApiKey(keyStore, hallucinationConfig)
      if (llmKey) formData.append('api_key', llmKey)
      else if (config && !config.has_key) {
        logger.warn('InputSection', `No API key for provider '${config.provider}'. LLM features may be unavailable.`)
      }
      if (hallucinationKey) formData.append('hallucination_api_key', hallucinationKey)
      const ssKey = keyStore.getKey('semantic_scholar')
      if (ssKey) formData.append('semantic_scholar_api_key', ssKey)

      logger.info('Check', 'Initiating check request', { 
        mode: inputMode, 
        llm: config?.provider,
        model: config?.model,
        hallucinationLlm: hallucinationConfig?.provider,
        hallucinationModel: hallucinationConfig?.model,
        hasApiKey: !!(llmKey || config?.has_key),
        source: inputMode === 'url' ? sanitizedUrl : (inputMode === 'file' ? fileUpload.file?.name : 'pasted text')
      })

      // Determine the source for display (use sanitized URL)
      const displaySource = inputMode === 'url' 
        ? sanitizedUrl 
        : (inputMode === 'file' ? fileUpload.file?.name : 'Pasted text')
      
      // Map inputMode to sourceType
      const sourceType = inputMode === 'url' ? 'url' : (inputMode === 'file' ? 'file' : 'text')
      
      // For file uploads, the filename becomes the paper title
      const displayTitle = inputMode === 'file' ? fileUpload.file?.name : null

      // Clear any previous history selection now that validation passed
      clearSelection()

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

  const handleBulkSubmit = async () => {
    // Validate input
    if (bulkMode === 'urls') {
      const urls = bulkUrls.split('\n').map(u => u.trim()).filter(Boolean)
      if (urls.length === 0) {
        logger.warn('InputSection', 'No URLs provided for bulk check')
        return
      }
    } else if (bulkMode === 'files' && bulkFiles.length === 0) {
      logger.warn('InputSection', 'No files selected for bulk check')
      return
    }

    clearSelection()

    setIsSubmitting(true)

    try {
      const config = getSelectedExtractionConfig?.() || getSelectedConfig()
      const hallucinationConfig = getSelectedHallucinationConfig?.() || config
      const { addToHistory } = useHistoryStore.getState()
      const keyStore = useKeyStore.getState()
      const llmKey = getConfigApiKey(keyStore, config)
      const hallucinationKey = getConfigApiKey(keyStore, hallucinationConfig)
      const ssKey = keyStore.getKey('semantic_scholar')
      
      let response
      
      if (bulkMode === 'urls') {
        const urls = bulkUrls.split('\n').map(u => u.trim()).filter(Boolean)
        
        response = await api.startBatchCheck({
          urls,
          batch_label: urls.length === 1 ? urls[0] : `Batch of ${urls.length} papers`,
          llm_config_id: config?.id,
          llm_provider: config?.provider || 'anthropic',
          llm_model: config?.model,
          hallucination_config_id: hallucinationConfig?.id,
          hallucination_provider: hallucinationConfig?.provider,
          hallucination_model: hallucinationConfig?.model,
          use_llm: !!config,
          api_key: llmKey,
          hallucination_api_key: hallucinationKey,
          semantic_scholar_api_key: ssKey,
        })
      } else {
        // File batch
        const formData = new FormData()
        bulkFiles.forEach(file => formData.append('files', file))
        formData.append('batch_label', bulkFiles.length === 1 ? bulkFiles[0].name : `Batch of ${bulkFiles.length} files`)
        if (config) {
          formData.append('llm_config_id', config.id.toString())
          formData.append('llm_provider', config.provider)
          if (config.model) formData.append('llm_model', config.model)
          formData.append('use_llm', 'true')
          if (hallucinationConfig) {
            formData.append('hallucination_config_id', hallucinationConfig.id.toString())
            formData.append('hallucination_provider', hallucinationConfig.provider)
            if (hallucinationConfig.model) formData.append('hallucination_model', hallucinationConfig.model)
          }
        } else {
          formData.append('use_llm', 'false')
        }
        if (llmKey) formData.append('api_key', llmKey)
        if (hallucinationKey) formData.append('hallucination_api_key', hallucinationKey)
        if (ssKey) formData.append('semantic_scholar_api_key', ssKey)
        
        response = await api.startBatchFileCheck(formData)
      }

      const { batch_id, batch_label, checks } = response.data
      
      logger.info('Batch', `Started batch ${batch_id} with ${checks.length} papers`)

      // Register all sessions for WebSocket connections
      const { registerSession } = useCheckStore.getState()
      for (const check of checks) {
        registerSession(check.session_id, check.check_id)
      }

      // Add all checks to history immediately
      for (const check of checks) {
        addToHistory({
          id: check.check_id,
          paper_title: check.source,
          paper_source: check.source,
          source_type: bulkMode === 'urls' ? 'url' : 'file',
          custom_label: null,
          timestamp: new Date().toISOString(),
          total_refs: 0,
          errors_count: 0,
          warnings_count: 0,
          unverified_count: 0,
          llm_provider: config?.provider || null,
          llm_model: config?.model || null,
          status: 'in_progress',
          session_id: check.session_id,
          batch_id: batch_id,
          batch_label: batch_label,
        })
      }

      // Select the first check and set it as the active check display
      if (checks.length > 0) {
        selectCheck(checks[0].check_id)
        startCheck(checks[0].session_id, checks[0].check_id, checks[0].source, bulkMode === 'urls' ? 'url' : 'file', null)
      }

      // Clear bulk inputs
      setBulkUrls('')
      setBulkFiles([])

    } catch (error) {
      logger.error('InputSection', 'Failed to start bulk check', error)
      setError(error.response?.data?.detail || error.message || 'Failed to start bulk check')
    } finally {
      setIsSubmitting(false)
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
      className="rounded-lg border p-4 lg:p-6"
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

      {/* Input mode tabs - horizontally scrollable on mobile */}
      <div className="flex gap-2 mb-4 overflow-x-auto pb-1 -mx-1 px-1">
        {[
          { id: 'url', label: 'URL / ArXiv ID' },
          { id: 'file', label: 'Upload File' },
          { id: 'text', label: 'Paste Text' },
          { id: 'bulk', label: 'Bulk' },
        ].map(mode => (
          <button
            key={mode.id}
            onClick={() => setInputMode(mode.id)}
            disabled={isChecking}
            className="px-3 py-2 text-sm font-medium rounded-lg transition-colors duration-150 whitespace-nowrap flex-shrink-0"
            style={{
              backgroundColor: inputMode === mode.id 
                ? 'var(--color-bg-primary)' 
                : 'var(--color-bg-primary)',
              color: inputMode === mode.id 
                ? 'var(--color-text-primary)' 
                : 'var(--color-text-secondary)',
              border: inputMode === mode.id 
                ? '1px solid var(--color-accent)' 
                : '1px solid var(--color-border)',
              cursor: isChecking ? 'not-allowed' : 'pointer',
            }}
            onMouseEnter={(e) => {
              if (!isChecking && inputMode !== mode.id) {
                e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
                e.currentTarget.style.borderColor = 'var(--color-accent)'
              }
            }}
            onMouseLeave={(e) => {
              if (inputMode !== mode.id) {
                e.currentTarget.style.backgroundColor = 'var(--color-bg-primary)'
                e.currentTarget.style.borderColor = 'var(--color-border)'
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
            onKeyDown={(e) => {
              if (e.key === 'Enter' && inputValue.trim() && !isChecking && !isSubmitting) {
                e.preventDefault()
                handleSubmit()
              }
            }}
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

        {inputMode === 'bulk' && (
          <BulkInputZone
            bulkMode={bulkMode}
            setBulkMode={setBulkMode}
            bulkUrls={bulkUrls}
            setBulkUrls={setBulkUrls}
            bulkFiles={bulkFiles}
            setBulkFiles={setBulkFiles}
            disabled={isChecking}
          />
        )}
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-3">
        {!isChecking && !isComplete && inputMode !== 'bulk' && (
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

        {!isChecking && !isComplete && inputMode === 'bulk' && (
          <Button 
            onClick={handleBulkSubmit}
            loading={isSubmitting}
            disabled={
              (bulkMode === 'urls' && !bulkUrls.trim()) ||
              (bulkMode === 'files' && bulkFiles.length === 0)
            }
          >
            {bulkMode === 'urls' 
              ? `Check ${bulkUrls.split('\n').filter(u => u.trim()).length || 0} ${bulkUrls.split('\n').filter(u => u.trim()).length === 1 ? 'Paper' : 'Papers'}`
              : `Check ${bulkFiles.length} ${bulkFiles.length === 1 ? 'File' : 'Files'}`
            }
          </Button>
        )}

        {isComplete && (
          <Button 
            onClick={handleRestart}
          >
            New Check
          </Button>
        )}
      </div>
    </div>
  )
}
