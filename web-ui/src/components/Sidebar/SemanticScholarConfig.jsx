import { useState, useEffect } from 'react'
import * as api from '../../utils/api'
import { logger } from '../../utils/logger'

/**
 * Semantic Scholar API key configuration component
 */
export default function SemanticScholarConfig() {
  const [hasKey, setHasKey] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [error, setError] = useState(null)

  // Load initial status
  useEffect(() => {
    loadKeyStatus()
  }, [])

  const loadKeyStatus = async () => {
    try {
      setIsLoading(true)
      const response = await api.getSemanticScholarKeyStatus()
      setHasKey(response.data.has_key)
      logger.info('SemanticScholarConfig', `Key status: ${response.data.has_key ? 'configured' : 'not configured'}`)
    } catch (err) {
      logger.error('SemanticScholarConfig', 'Failed to load key status', err)
      setError('Failed to load status')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSave = async () => {
    if (!apiKey.trim()) {
      setError('API key cannot be empty')
      return
    }

    try {
      // First validate the API key
      setIsValidating(true)
      setError(null)
      console.log('[SemanticScholarConfig] Starting validation...')
      
      const validationResponse = await api.validateSemanticScholarKey(apiKey.trim())
      console.log('[SemanticScholarConfig] Validation response:', validationResponse.data)
      
      if (!validationResponse.data.valid) {
        setError(validationResponse.data.message || 'Invalid API key')
        setIsValidating(false)
        return
      }
      
      logger.info('SemanticScholarConfig', 'API key validated successfully')
      setIsValidating(false)
      
      // Now save the key
      setIsSaving(true)
      await api.setSemanticScholarKey(apiKey.trim())
      setHasKey(true)
      setIsEditing(false)
      setApiKey('')
      logger.info('SemanticScholarConfig', 'API key saved')
    } catch (err) {
      console.error('[SemanticScholarConfig] Validation/save error:', err)
      logger.error('SemanticScholarConfig', 'Failed to save key', err)
      setError(err.response?.data?.detail || 'Failed to validate API key')
    } finally {
      setIsValidating(false)
      setIsSaving(false)
    }
  }

  const handleDelete = async () => {
    try {
      setIsSaving(true)
      setError(null)
      await api.deleteSemanticScholarKey()
      setHasKey(false)
      setIsEditing(false)
      setApiKey('')
      logger.info('SemanticScholarConfig', 'API key deleted')
    } catch (err) {
      logger.error('SemanticScholarConfig', 'Failed to delete key', err)
      setError(err.response?.data?.detail || 'Failed to delete API key')
    } finally {
      setIsSaving(false)
    }
  }

  const handleCancel = () => {
    setIsEditing(false)
    setApiKey('')
    setError(null)
  }

  if (isLoading) {
    return (
      <div 
        className="text-sm"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Loading...
      </div>
    )
  }

  return (
    <div>
      <h2 
        className="text-sm font-semibold mb-2 uppercase tracking-wide"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        Semantic Scholar
      </h2>

      {/* Status display */}
      {!isEditing ? (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span 
              className="text-sm"
              style={{ color: 'var(--color-text-primary)' }}
            >
              API Key:
            </span>
            {hasKey ? (
              <span 
                className="text-xs px-2 py-0.5 rounded"
                style={{ 
                  backgroundColor: 'var(--color-success-bg)',
                  color: 'var(--color-success)'
                }}
              >
                ✓ Set
              </span>
            ) : (
              <span 
                className="text-xs"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Not set
              </span>
            )}
          </div>
          <button
            onClick={() => setIsEditing(true)}
            className="text-sm px-2 py-1 rounded transition-colors cursor-pointer"
            style={{ color: 'var(--color-accent)' }}
          >
            {hasKey ? 'Edit' : 'Add'}
          </button>
        </div>
      ) : (
        /* Edit form */
        <div className="space-y-2">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            onPaste={(e) => {
              // Ensure paste works
              e.stopPropagation()
            }}
            placeholder={hasKey ? "Enter new key..." : "Enter API key..."}
            className="w-full px-3 py-2 text-sm rounded border"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: error ? 'var(--color-error)' : 'var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
            disabled={isSaving || isValidating}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSave()
              if (e.key === 'Escape') handleCancel()
            }}
          />
          
          {error && (
            <div 
              className="text-xs"
              style={{ color: 'var(--color-error)' }}
            >
              {error}
            </div>
          )}

          <div className="flex gap-2">
            <button
              onClick={handleSave}
              disabled={isSaving || isValidating || !apiKey.trim()}
              className="flex-1 px-3 py-1.5 text-sm rounded"
              style={{
                backgroundColor: 'var(--color-accent)',
                color: 'white',
                opacity: isSaving || isValidating || !apiKey.trim() ? 0.5 : 1,
              }}
            >
              {isValidating ? 'Validating...' : isSaving ? 'Saving...' : 'Save'}
            </button>
            {hasKey && (
              <button
                onClick={handleDelete}
                disabled={isSaving || isValidating}
                className="px-3 py-1.5 text-sm rounded"
                style={{
                  backgroundColor: 'var(--color-error-bg)',
                  color: 'var(--color-error)',
                  opacity: isSaving || isValidating ? 0.5 : 1,
                }}
              >
                Delete
              </button>
            )}
            <button
              onClick={handleCancel}
              disabled={isSaving || isValidating}
              className="px-3 py-1.5 text-sm rounded border"
              style={{
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div 
        className="text-xs mt-2"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Optional. Increases rate limits.
      </div>
    </div>
  )
}
