import { useState, useCallback } from 'react'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useCheckStore } from '../../stores/useCheckStore'
import { formatDate } from '../../utils/formatters'
import { logger } from '../../utils/logger'
import * as api from '../../utils/api'

/**
 * Convert arXiv ID to full URL if needed
 */
function expandArxivId(source) {
  if (!source) return source
  // If it's already a URL, return as-is
  if (source.startsWith('http://') || source.startsWith('https://')) {
    return source
  }
  // If it's an arXiv ID (handles both "2310.02238" and "arXiv:2310.02238" formats)
  const arxivMatch = source.match(/^(?:arXiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)$/i)
  if (arxivMatch) {
    return `https://arxiv.org/abs/${arxivMatch[1]}`
  }
  // Otherwise return as-is
  return source
}

/**
 * Individual history item in the sidebar
 */
export default function HistoryItem({ item, isSelected }) {
  const { selectCheck, updateLabel, deleteCheck, updateHistoryProgress } = useHistoryStore()
  // Only subscribe to the specific values we need to minimize re-renders
  const currentSessionId = useCheckStore(state => state.sessionId)
  const storeCancelCheck = useCheckStore(state => state.cancelCheck)
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [isHovered, setIsHovered] = useState(false)
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false)
  const [isCancelling, setIsCancelling] = useState(false)

  const displayLabel = item.custom_label || item.paper_title || 'Untitled Check'

  const isPlaceholder = item.id === -1
  const isInProgress = item.status === 'in_progress'
  
  // Calculate progress percentage
  const totalRefs = item.total_refs || 0
  const processedRefs = item.processed_refs || 0
  const progressPercent = totalRefs > 0 ? Math.min((processedRefs / totalRefs) * 100, 100) : 0

  const handleClick = () => {
    if (!isEditing) {
      logger.info('HistoryItem', `Selecting check ${item.id}`)
      selectCheck(item.id)
    }
  }

  const handleEditStart = (e) => {
    e.stopPropagation()
    setEditValue(displayLabel)
    setIsEditing(true)
  }

  const handleEditSave = async () => {
    if (editValue.trim() && editValue.trim() !== displayLabel) {
      try {
        await updateLabel(item.id, editValue.trim())
        logger.info('HistoryItem', `Label updated for ${item.id}`)
      } catch (error) {
        logger.error('HistoryItem', 'Failed to update label', error)
      }
    }
    setIsEditing(false)
  }

  const handleEditCancel = () => {
    setIsEditing(false)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      handleEditSave()
    } else if (e.key === 'Escape') {
      handleEditCancel()
    }
  }

  const handleDelete = async (e) => {
    e.stopPropagation()
    setIsConfirmingDelete(true)
  }

  const handleConfirmDelete = async (e) => {
    e.stopPropagation()
    try {
      await deleteCheck(item.id)
      logger.info('HistoryItem', `Deleted check ${item.id}`)
    } catch (error) {
      logger.error('HistoryItem', 'Failed to delete', error)
    }
    setIsConfirmingDelete(false)
  }

  const handleCancelDelete = (e) => {
    e.stopPropagation()
    setIsConfirmingDelete(false)
  }

  const handleCancelCheck = async (e) => {
    e.stopPropagation()
    if (!item.session_id || isCancelling) return
    
    setIsCancelling(true)
    try {
      logger.info('HistoryItem', `Cancelling check ${item.session_id}`)
      await api.cancelCheck(item.session_id)
      
      // Update history item status
      updateHistoryProgress(item.id, { status: 'cancelled' })
      
      // If this is the current session, also update check store
      if (item.session_id === currentSessionId) {
        storeCancelCheck()
      }
      
      logger.info('HistoryItem', `Check ${item.id} cancelled`)
    } catch (error) {
      logger.error('HistoryItem', 'Failed to cancel check', error)
      // Still mark as cancelled since the check may have already finished
      updateHistoryProgress(item.id, { status: 'cancelled' })
      if (item.session_id === currentSessionId) {
        storeCancelCheck()
      }
    } finally {
      setIsCancelling(false)
    }
  }

  // Status indicator based on errors or in-progress state
  const getStatusIndicator = () => {
    // Check if this is an in-progress check (only show spinner if status is explicitly in_progress)
    // status will be 'completed', 'cancelled', 'error', or 'in_progress'
    if (item.status === 'in_progress') {
      return { color: 'var(--color-accent)', label: 'In progress', isAnimated: true }
    }
    if (item.status === 'cancelled') {
      return { color: 'var(--color-warning)', label: 'Cancelled', isAnimated: false }
    }
    if (item.status === 'error') {
      return { color: 'var(--color-error)', label: 'Error', isAnimated: false }
    }
    // For completed checks, show status based on counts
    if (item.errors_count > 0) {
      return { color: 'var(--color-error)', label: `${item.errors_count} errors`, isAnimated: false }
    }
    if (item.warnings_count > 0) {
      return { color: 'var(--color-warning)', label: `${item.warnings_count} warnings`, isAnimated: false }
    }
    if (item.unverified_count > 0) {
      return { color: 'var(--color-text-muted)', label: `${item.unverified_count} unverified`, isAnimated: false }
    }
    return { color: 'var(--color-success)', label: 'All verified', isAnimated: false }
  }

  const status = getStatusIndicator()

  return (
    <div
      onClick={handleClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className="px-3 py-2 mx-2 my-0.5 cursor-pointer transition-colors rounded-md relative"
      style={{
        backgroundColor: isSelected ? 'var(--color-bg-tertiary)' : 'transparent',
      }}
      onMouseOver={(e) => {
        if (!isSelected) {
          e.currentTarget.style.backgroundColor = 'var(--color-bg-tertiary)'
        }
      }}
      onMouseOut={(e) => {
        if (!isSelected) {
          e.currentTarget.style.backgroundColor = 'transparent'
        }
      }}
    >
      {/* Label / Title - full width, controls overlay on top */}
      <div className="w-full">
        {isEditing ? (
          <input
            type="text"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={handleEditSave}
            onKeyDown={handleKeyDown}
            onClick={(e) => e.stopPropagation()}
            autoFocus
            className="w-full px-2 py-1 text-sm rounded border focus:outline-none focus:ring-1"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: 'var(--color-accent)',
              color: 'var(--color-text-primary)',
            }}
          />
        ) : (
          <div 
            className="font-medium text-sm leading-tight overflow-hidden text-ellipsis whitespace-nowrap"
            style={{ color: 'var(--color-text-primary)' }}
            title={displayLabel}
          >
            {displayLabel}
          </div>
        )}
        
        {/* Paper source URL (show if available, but not for pasted text or file uploads which use temp paths) */}
        {!isPlaceholder && item.paper_source && item.source_type !== 'text' && item.source_type !== 'file' && (
          <div 
            className="text-xs mt-0.5 overflow-hidden text-ellipsis whitespace-nowrap"
            style={{ color: 'var(--color-text-muted)' }}
            title={expandArxivId(item.paper_source)}
          >
            {expandArxivId(item.paper_source)}
          </div>
        )}
        
        {/* Date (hide for placeholder or missing timestamp) */}
        {item.timestamp && !isPlaceholder && (
          <div 
            className="text-xs mt-1"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {formatDate(item.timestamp)}
          </div>
        )}

        {/* Stats summary - compact layout */}
        <div className="flex items-center gap-1.5 mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>
          {/* Error icon for failed checks */}
          {item.status === 'error' && (
            <svg className="w-3 h-3 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" style={{ color: 'var(--color-error)' }}>
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
          )}
          {/* Warning icon for cancelled checks */}
          {item.status === 'cancelled' && (
            <svg className="w-3 h-3 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" style={{ color: 'var(--color-warning)' }}>
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8 7a1 1 0 00-1 1v4a1 1 0 102 0V8a1 1 0 00-1-1zm4 0a1 1 0 00-1 1v4a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
          )}
          <span style={{ color: item.status === 'error' ? 'var(--color-error)' : (item.status === 'cancelled' ? 'var(--color-warning)' : undefined) }}>
            {isPlaceholder 
              ? 'Start a new check' 
              : (item.status === 'error'
                  ? 'Check failed'
                  : (item.status === 'cancelled'
                      ? 'Cancelled'
                      : (isInProgress 
                          ? (totalRefs > 0 ? `${processedRefs}/${totalRefs}` : 'Extracting...') 
                          : `${totalRefs} refs`)))}
          </span>
          {/* Show error/warning/suggestion counts with compact icons (including during in-progress) */}
          {!isPlaceholder && (
            <>
              {(item.refs_with_errors || 0) > 0 && (
                <span className="flex items-center" style={{ color: 'var(--color-error)' }} title={`${item.refs_with_errors} ref${item.refs_with_errors === 1 ? '' : 's'} with errors`}>
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                  <span className="ml-0.5">{item.refs_with_errors}</span>
                </span>
              )}
              {(item.refs_with_warnings_only || 0) > 0 && (
                <span className="flex items-center" style={{ color: 'var(--color-warning)' }} title={`${item.refs_with_warnings_only} ref${item.refs_with_warnings_only === 1 ? '' : 's'} with warnings`}>
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <span className="ml-0.5">{item.refs_with_warnings_only}</span>
                </span>
              )}
              {(item.suggestions_count || 0) > 0 && (
                <span className="flex items-center" style={{ color: 'var(--color-suggestion)' }} title={`${item.suggestions_count} suggestion${item.suggestions_count === 1 ? '' : 's'}`}>
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.34.208-.646.477-.859a4 4 0 10-4.954 0c.27.213.462.519.476.859h4.002z" />
                  </svg>
                  <span className="ml-0.5">{item.suggestions_count}</span>
                </span>
              )}
              {/* Green check only when completed with no issues at all */}
              {!isInProgress && (item.refs_with_errors || 0) === 0 && (item.refs_with_warnings_only || 0) === 0 && (item.suggestions_count || 0) === 0 && item.status === 'completed' && (
                <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20" style={{ color: 'var(--color-success)' }} title="All references verified">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
              )}
            </>
          )}
          {/* Show spinner for in-progress */}
          {!isPlaceholder && status.isAnimated && (
            <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24" style={{ color: status.color }}>
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          )}
          {/* Cancel button for in-progress checks */}
          {isInProgress && item.session_id && (
            <button
              onClick={handleCancelCheck}
              disabled={isCancelling}
              className="ml-auto text-xs px-2 py-0.5 rounded transition-colors"
              style={{
                backgroundColor: 'var(--color-error-bg)',
                color: 'var(--color-error)',
                opacity: isCancelling ? 0.5 : 1,
                cursor: isCancelling ? 'wait' : 'pointer',
              }}
              onMouseEnter={(e) => {
                if (!isCancelling) {
                  e.currentTarget.style.backgroundColor = 'var(--color-error)'
                  e.currentTarget.style.color = 'white'
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--color-error-bg)'
                e.currentTarget.style.color = 'var(--color-error)'
              }}
              title="Cancel this check"
            >
              {isCancelling ? 'Cancelling...' : 'Cancel'}
            </button>
          )}
        </div>
        
        {/* Progress bar for in-progress checks */}
        {isInProgress && totalRefs > 0 && (
          <div className="mt-2">
            <div 
              className="h-1 rounded-full overflow-hidden"
              style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
            >
              <div 
                className="h-full rounded-full transition-all duration-300 progress-bar"
                style={{ 
                  width: `${Math.round(progressPercent)}%`,
                }}
              />
            </div>
            <p 
              className="text-xs mt-0.5"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {Math.round(progressPercent)}% complete
            </p>
          </div>
        )}
      </div>

      {/* Action buttons - positioned absolutely to overlay title */}
      {isConfirmingDelete ? (
        <div 
          className="absolute top-2 right-2 flex items-center gap-1 px-2 py-1 rounded-lg"
          style={{ backgroundColor: 'var(--color-error-bg)' }}
        >
          <button
            onClick={handleConfirmDelete}
            className="p-1 rounded transition-colors"
            style={{ color: 'var(--color-error)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-error)'
              e.currentTarget.style.color = 'white'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
              e.currentTarget.style.color = 'var(--color-error)'
            }}
            title="Confirm delete"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </button>
          <button
            onClick={handleCancelDelete}
            className="p-1 rounded transition-colors"
            style={{ color: 'var(--color-text-secondary)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-tertiary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
            }}
            title="Cancel"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      ) : isHovered && !isEditing && !isPlaceholder && (
        <div 
          className="absolute top-2 right-2 flex items-center"
        >
          {/* Gradient fade */}
          <div 
            className="w-8 h-6"
            style={{ 
              background: `linear-gradient(to right, transparent, ${isSelected ? 'var(--color-bg-tertiary)' : 'var(--color-bg-primary)'})`
            }}
          />
          <div 
            className="flex items-center gap-1 pl-1 pr-1 h-6"
            style={{ backgroundColor: isSelected ? 'var(--color-bg-tertiary)' : 'var(--color-bg-primary)' }}
          >
            <button
              onClick={handleEditStart}
              className="p-1 rounded transition-colors cursor-pointer"
              style={{ color: 'var(--color-text-secondary)' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--color-accent)'
                e.currentTarget.style.color = 'white'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent'
                e.currentTarget.style.color = 'var(--color-text-secondary)'
              }}
              title="Edit label"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
            </button>
            <button
              onClick={handleDelete}
              className="p-1 rounded transition-colors cursor-pointer"
              style={{ color: 'var(--color-error)' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--color-error-bg)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent'
              }}
              title="Delete"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
