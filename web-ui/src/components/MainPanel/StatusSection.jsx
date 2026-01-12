import { useCheckStore } from '../../stores/useCheckStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import * as api from '../../utils/api'
import { logger } from '../../utils/logger'

/**
 * Format a source for display - extract just the URL if title+URL are combined
 */
function formatSource(source, title) {
  if (!source) return null
  
  // If source contains the title at the beginning followed by a URL, extract just the URL
  // This handles cases where paper_source was incorrectly stored as "Title URL"
  if (title && source.startsWith(title)) {
    const remainder = source.substring(title.length).trim()
    if (remainder.startsWith('http://') || remainder.startsWith('https://')) {
      source = remainder
    }
  }
  
  // If it's a URL, show it as a link
  if (source.startsWith('http://') || source.startsWith('https://')) {
    return { type: 'url', value: source, display: source.length > 60 ? source.substring(0, 60) + '...' : source }
  }
  // ArXiv IDs - show full URL
  if (/^\d{4}\.\d{4,5}(v\d+)?$/.test(source)) {
    const fullUrl = `https://arxiv.org/abs/${source}`
    return { type: 'url', value: fullUrl, display: fullUrl }
  }
  // Filename or other
  return { type: 'text', value: source, display: source }
}

/**
 * Status section showing check progress - treats all checks as peers
 */
export default function StatusSection() {
  const { 
    status: checkStoreStatus, 
    statusMessage: checkStoreMessage,
    progress: checkStoreProgress,
    paperTitle: checkStorePaperTitle, 
    paperSource: checkStorePaperSource, 
    currentCheckId,
    sessionId,
    stats: checkStoreStats,
    cancelCheck: storeCancelCheck,
    setError,
  } = useCheckStore()
  const { selectedCheck, selectedCheckId, isLoadingDetail, updateHistoryProgress } = useHistoryStore()

  // Determine if we're viewing a check (either the current session's check or any history item)
  const isViewingCheck = selectedCheckId !== null && selectedCheckId !== -1
  
  // Get the session_id for the currently viewed check (if any) to enable cancel
  // For current session check, we use sessionId from checkStore
  // For other checks, we'd need the session_id from selectedCheck (if still running)
  const viewedCheckSessionId = selectedCheckId === currentCheckId ? sessionId : selectedCheck?.session_id

  // Unify data source: prefer selectedCheck (from history store) when viewing any check
  // Fall back to checkStore for the current session if selectedCheck isn't loaded yet
  const isCurrentSessionCheck = selectedCheckId === currentCheckId
  
  // Derive display values
  // For current session: prefer checkStore (has live WebSocket data)
  // For other checks: use selectedCheck (has history data)
  let displayStatus = 'idle'
  let displayTitle = null
  let displaySource = null
  let displayMessage = ''
  let displayProgress = 0
  let displayTotalRefs = 0
  let displayProcessedRefs = 0
  let displayLlmProvider = null
  let displayLlmModel = null
  
  if (isCurrentSessionCheck && checkStoreStatus !== 'idle') {
    // Current session: use live WebSocket data from checkStore
    displayStatus = checkStoreStatus
    displayTitle = checkStorePaperTitle
    displaySource = checkStorePaperSource
    displayMessage = checkStoreMessage
    displayProgress = checkStoreProgress
    displayTotalRefs = checkStoreStats?.total_refs || 0
    displayProcessedRefs = checkStoreStats?.processed_refs || 0
    // Get LLM info from selectedCheck (history) since it's not in checkStore
    displayLlmProvider = selectedCheck?.llm_provider
    displayLlmModel = selectedCheck?.llm_model
  } else if (isViewingCheck && selectedCheck) {
    // Other checks: use selectedCheck data from history
    displayStatus = selectedCheck.status || 'idle'
    displayTitle = selectedCheck.custom_label || selectedCheck.paper_title
    displaySource = selectedCheck.paper_source
    displayTotalRefs = selectedCheck.total_refs || 0
    displayProcessedRefs = selectedCheck.processed_refs || 0
    displayProgress = displayTotalRefs > 0 ? (displayProcessedRefs / displayTotalRefs) * 100 : 0
    displayLlmProvider = selectedCheck.llm_provider
    displayLlmModel = selectedCheck.llm_model
    
    // Build status message based on state
    if (displayStatus === 'in_progress') {
      if (displayProcessedRefs > 0) {
        displayMessage = `Checking ${displayProcessedRefs} of ${displayTotalRefs} references...`
      } else if (displayTotalRefs > 0) {
        displayMessage = `Found ${displayTotalRefs} references, starting verification...`
      } else {
        displayMessage = 'Extracting references...'
      }
    } else if (displayStatus === 'completed') {
      displayMessage = `Completed • ${displayTotalRefs} references checked`
    } else if (displayStatus === 'cancelled') {
      displayMessage = 'Check cancelled'
    } else if (displayStatus === 'error') {
      displayMessage = 'Check failed'
    }
  }

  const sourceInfo = formatSource(displaySource, displayTitle)
  const isInProgress = displayStatus === 'in_progress' || displayStatus === 'checking'
  const isCompleted = displayStatus === 'completed'
  const isCancelled = displayStatus === 'cancelled'
  const isError = displayStatus === 'error'

  // Show loading state when switching to a check
  if (isViewingCheck && isLoadingDetail) {
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

  // Not viewing any check
  if (!isViewingCheck || displayStatus === 'idle') {
    return null
  }

  // Status icon based on state
  const getStatusIcon = () => {
    if (isInProgress) {
      return (
        <svg 
          className="w-6 h-6 animate-spin" 
          fill="none" 
          viewBox="0 0 24 24"
          style={{ color: 'var(--color-accent)' }}
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )
    }
    if (isCompleted) {
      return (
        <svg 
          className="w-6 h-6" 
          fill="none" 
          viewBox="0 0 24 24" 
          stroke="currentColor"
          style={{ color: 'var(--color-success)' }}
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      )
    }
    if (isCancelled) {
      return (
        <svg 
          className="w-6 h-6" 
          viewBox="0 0 24 24" 
          fill="none"
          stroke="currentColor"
          style={{ color: 'var(--color-warning)' }}
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      )
    }
    if (isError) {
      return (
        <svg 
          className="w-6 h-6" 
          viewBox="0 0 24 24" 
          fill="none"
          stroke="currentColor"
          style={{ color: 'var(--color-error)' }}
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      )
    }
    return null
  }

  const getStatusBgColor = () => {
    if (isInProgress) return 'var(--color-info-bg)'
    if (isCompleted) return 'var(--color-success-bg)'
    if (isCancelled) return 'var(--color-warning-bg)'
    if (isError) return 'var(--color-error-bg)'
    return 'var(--color-bg-tertiary)'
  }

  // Can cancel if this check is in progress AND we have a session_id for it
  const canCancel = isInProgress && viewedCheckSessionId

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
          style={{ backgroundColor: getStatusBgColor() }}
        >
          {getStatusIcon()}
        </div>
        <div className="flex-1 min-w-0">
          {displayTitle && (
            <h3 
              className="font-medium"
              style={{ color: 'var(--color-text-primary)' }}
            >
              {displayTitle}
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
                  style={{ color: 'var(--color-link)' }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {sourceInfo.display}
                </a>
              ) : (
                sourceInfo.display
              )}
            </p>
          )}
          {displayLlmModel && (
            <p 
              className="text-sm"
              style={{ color: 'var(--color-text-muted)' }}
            >
              Model: {displayLlmProvider ? `${displayLlmProvider} / ` : ''}{displayLlmModel}
            </p>
          )}
          <p 
            className="text-sm"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {displayMessage}
          </p>
        </div>
        {canCancel && (
          <button
            onClick={async () => {
              if (!viewedCheckSessionId) return
              try {
                logger.info('StatusSection', `Cancelling check ${viewedCheckSessionId}`)
                await api.cancelCheck(viewedCheckSessionId)
                // Update history item status
                if (selectedCheckId) {
                  updateHistoryProgress(selectedCheckId, { status: 'cancelled' })
                }
                // Only update checkStore if cancelling the current session
                if (viewedCheckSessionId === sessionId) {
                  storeCancelCheck()
                }
              } catch (error) {
                logger.error('StatusSection', 'Failed to cancel', error)
                // Still mark as cancelled since the check may have already finished
                if (selectedCheckId) {
                  updateHistoryProgress(selectedCheckId, { status: 'cancelled' })
                }
                if (viewedCheckSessionId === sessionId) {
                  storeCancelCheck()
                }
                setError(error.response?.data?.detail || error.message || 'Failed to cancel')
              }
            }}
            className="px-3 py-2 text-sm font-medium rounded transition-colors cursor-pointer hover:opacity-80"
            style={{
              backgroundColor: 'var(--color-error-bg)',
              color: 'var(--color-error)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-error)'
              e.currentTarget.style.color = 'white'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-error-bg)'
              e.currentTarget.style.color = 'var(--color-error)'
            }}
          >
            Cancel
          </button>
        )}
      </div>

      {/* Progress bar for in-progress checks */}
      {isInProgress && (
        <div className="mt-4">
          <div 
            className="h-2 rounded-full overflow-hidden"
            style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
          >
            <div 
              className="h-full rounded-full transition-all duration-300 progress-bar"
              style={{ 
                width: `${Math.round(displayProgress)}%`,
              }}
            />
          </div>
          <p 
            className="text-xs mt-1"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {displayTotalRefs > 0 
              ? `${Math.round(displayProgress)}% complete`
              : 'Starting...'}
          </p>
        </div>
      )}
    </div>
  )
}
