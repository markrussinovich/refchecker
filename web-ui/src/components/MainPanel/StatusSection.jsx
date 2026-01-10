import { useCheckStore } from '../../stores/useCheckStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import * as api from '../../utils/api'
import { logger } from '../../utils/logger'

/**
 * Format a source for display - truncate long URLs/paths
 */
function formatSource(source) {
  if (!source) return null
  // If it's a URL, show it as a link
  if (source.startsWith('http://') || source.startsWith('https://')) {
    return { type: 'url', value: source, display: source.length > 60 ? source.substring(0, 60) + '...' : source }
  }
  // ArXiv IDs
  if (/^\d{4}\.\d{4,5}(v\d+)?$/.test(source)) {
    return { type: 'url', value: `https://arxiv.org/abs/${source}`, display: `arXiv:${source}` }
  }
  // Filename or other
  return { type: 'text', value: source, display: source }
}

/**
 * Status section showing current check progress
 * @param {Object} props
 * @param {boolean} props.isViewingHistory - Whether viewing a history item
 */
export default function StatusSection({ isViewingHistory = false }) {
  const { 
    status, 
    statusMessage, 
    progress, 
    paperTitle, 
    paperSource, 
    currentCheckId,
    sessionId,
    cancelCheck: storeCancelCheck,
    setError,
  } = useCheckStore()
  const { selectedCheck, selectedCheckId, isLoadingDetail } = useHistoryStore()
  
  const sourceInfo = isViewingHistory 
    ? formatSource(selectedCheck?.paper_source) 
    : formatSource(paperSource)
  
  // Show loading state when switching to a history item
  if (isViewingHistory && isLoadingDetail) {
    return (
      <div 
        className="rounded-lg border p-4"
        style={{
          backgroundColor: 'var(--color-bg-secondary)',
          borderColor: 'var(--color-border)',
        }}
      >
        <div className="flex items-center gap-3">
          <div 
            className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 animate-pulse"
            style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
          >
            <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24" style={{ color: 'var(--color-text-muted)' }}>
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
          <div className="flex-1 min-w-0">
            <h3 
              className="font-medium"
              style={{ color: 'var(--color-text-primary)' }}
            >
              Loading check details...
            </h3>
          </div>
        </div>
      </div>
    )
  }
  
  if (isViewingHistory && selectedCheck) {
    return (
      <div 
        className="rounded-lg border p-4"
        style={{
          backgroundColor: 'var(--color-bg-secondary)',
          borderColor: 'var(--color-border)',
        }}
      >
        <div className="flex items-center gap-3">
          <div 
            className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0"
            style={{ backgroundColor: 'var(--color-success-bg)' }}
          >
            <svg 
              className="w-5 h-5" 
              fill="none" 
              viewBox="0 0 24 24" 
              stroke="currentColor"
              style={{ color: 'var(--color-success)' }}
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div className="flex-1 min-w-0">
            <h3 
              className="font-medium truncate"
              style={{ color: 'var(--color-text-primary)' }}
            >
              {selectedCheck.custom_label || selectedCheck.paper_title || 'Check Results'}
            </h3>
            {sourceInfo && (
              <p 
                className="text-sm truncate"
                style={{ color: 'var(--color-text-muted)' }}
                title={sourceInfo.value}
              >
                {sourceInfo.type === 'url' ? (
                  <a 
                    href={sourceInfo.value} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="hover:underline"
                    style={{ color: 'var(--color-accent)' }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {sourceInfo.display}
                  </a>
                ) : (
                  sourceInfo.display
                )}
              </p>
            )}
            <p 
              className="text-sm"
              style={{ color: 'var(--color-text-muted)' }}
            >
              Completed • {selectedCheck.total_refs} references checked
            </p>
          </div>
        </div>
      </div>
    )
  }

  // Not checking
  if (status === 'idle') {
    return null
  }

  // Status icon based on state
  const getStatusIcon = () => {
    switch (status) {
      case 'checking':
        return (
          <svg 
            className="w-7 h-7 animate-spin" 
            fill="none" 
            viewBox="0 0 24 24"
            style={{ color: 'var(--color-accent)' }}
          >
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        )
      case 'completed':
        return (
          <svg 
            className="w-7 h-7" 
            viewBox="0 0 24 24" 
            fill="none"
          >
            <circle cx="12" cy="12" r="10" fill="var(--color-success)" />
            <path d="M8.5 12.5l2.5 2.5 4.5-5" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )
      case 'cancelled':
        return (
          <svg 
            className="w-7 h-7" 
            viewBox="0 0 24 24" 
            fill="none"
          >
            <circle cx="12" cy="12" r="10" fill="var(--color-warning)" />
            <path d="M12 7.5v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
          </svg>
        )
      case 'error':
        return (
          <svg 
            className="w-7 h-7" 
            viewBox="0 0 24 24" 
            fill="none"
          >
            <circle cx="12" cy="12" r="10" fill="var(--color-error)" />
            <path d="M12 7v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
          </svg>
        )
      default:
        return null
    }
  }

  const getStatusBgColor = () => {
    switch (status) {
      case 'checking': return 'var(--color-info-bg)'
      case 'completed': return 'var(--color-success-bg)'
      case 'cancelled': return 'var(--color-warning-bg)'
      case 'error': return 'var(--color-error-bg)'
      default: return 'var(--color-bg-tertiary)'
    }
  }

  return (
    <div 
      className="rounded-lg border p-4"
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)',
      }}
    >
      <div className="flex items-center gap-3">
        <div 
          className="w-12 h-12 rounded-full flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: 'transparent' }}
        >
          {getStatusIcon()}
        </div>
        <div className="flex-1 min-w-0">
          {paperTitle && (
            <h3 
              className="font-medium truncate"
              style={{ color: 'var(--color-text-primary)' }}
            >
              {paperTitle}
            </h3>
          )}
          {sourceInfo && (
            <p 
              className="text-sm truncate"
              style={{ color: 'var(--color-text-muted)' }}
              title={sourceInfo.value}
            >
              {sourceInfo.type === 'url' ? (
                <a 
                  href={sourceInfo.value} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="hover:underline"
                  style={{ color: 'var(--color-accent)' }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {sourceInfo.display}
                </a>
              ) : (
                sourceInfo.display
              )}
            </p>
          )}
          <p 
            className="text-sm"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {statusMessage}
          </p>
        </div>
        {status === 'checking' && (
          <button
            onClick={async () => {
              if (!sessionId) return
              try {
                logger.info('StatusSection', `Cancelling check ${sessionId}`)
                await api.cancelCheck(sessionId)
                storeCancelCheck()
              } catch (error) {
                logger.error('StatusSection', 'Failed to cancel', error)
                storeCancelCheck()
                setError(error.response?.data?.detail || error.message || 'Failed to cancel')
              }
            }}
            className="px-3 py-2 text-sm font-medium rounded transition-colors"
            style={{
              backgroundColor: 'var(--color-error-bg)',
              color: 'var(--color-error)',
            }}
          >
            Cancel
          </button>
        )}
      </div>

      {/* Progress bar */}
      {status === 'checking' && (
        <div className="mt-4">
          <div 
            className="h-2 rounded-full overflow-hidden"
            style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
          >
            <div 
              className="h-full rounded-full transition-all duration-300 progress-bar"
              style={{ 
                width: `${progress}%`,
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
