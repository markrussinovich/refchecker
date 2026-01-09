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
      setIsSaving(true)
      setError(null)
      await api.setSemanticScholarKey(apiKey.trim())
      setHasKey(true)
      setIsEditing(false)
      setApiKey('')
      logger.info('SemanticScholarConfig', 'API key saved')
    } catch (err) {
      logger.error('SemanticScholarConfig', 'Failed to save key', err)
      setError(err.response?.data?.detail || 'Failed to save API key')
    } finally {
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
            className="text-sm px-2 py-1 rounded transition-colors"
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
            disabled={isSaving}
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
              disabled={isSaving || !apiKey.trim()}
              className="flex-1 px-3 py-1.5 text-sm rounded"
              style={{
                backgroundColor: 'var(--color-accent)',
                color: 'white',
                opacity: isSaving || !apiKey.trim() ? 0.5 : 1,
              }}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </button>
            {hasKey && (
              <button
                onClick={handleDelete}
                disabled={isSaving}
                className="px-3 py-1.5 text-sm rounded"
                style={{
                  backgroundColor: 'var(--color-error-bg)',
                  color: 'var(--color-error)',
                  opacity: isSaving ? 0.5 : 1,
                }}
              >
                Delete
              </button>
            )}
            <button
              onClick={handleCancel}
              disabled={isSaving}
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
