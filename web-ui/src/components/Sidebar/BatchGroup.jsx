import { useMemo, useState } from 'react'
import HistoryItem from './HistoryItem'
import * as api from '../../utils/api'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { formatDate } from '../../utils/formatters'
import { logger } from '../../utils/logger'

/**
 * Collapsible group of batch checks in the history sidebar
 */
export default function BatchGroup({
  batchId,
  batchLabel,
  items,
  isCollapsed,
  onToggle,
  selectedCheckId,
}) {
  const [isCancelling, setIsCancelling] = useState(false)
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false)
  const [isEditingLabel, setIsEditingLabel] = useState(false)
  const [editValue, setEditValue] = useState('')
  const { fetchHistory, deleteCheck, selectCheck } = useHistoryStore()

  const handleEditStart = (e) => {
    e.stopPropagation()
    setEditValue(batchLabel || `Batch of ${items.length} ${items.length === 1 ? 'paper' : 'papers'}`)
    setIsEditingLabel(true)
  }

  const handleEditSave = async () => {
    if (editValue.trim() && editValue.trim() !== batchLabel) {
      try {
        await api.updateBatchLabel(batchId, editValue.trim())
        await fetchHistory()
        logger.info('BatchGroup', `Label updated for batch ${batchId}`)
      } catch (error) {
        logger.error('BatchGroup', 'Failed to update label', error)
      }
    }
    setIsEditingLabel(false)
  }

  const handleEditKeyDown = (e) => {
    if (e.key === 'Enter') {
      handleEditSave()
    } else if (e.key === 'Escape') {
      setIsEditingLabel(false)
    }
  }

  // Calculate batch stats
  const stats = useMemo(() => {
    const total = items.length
    const completed = items.filter(i => i.status === 'completed').length
    const inProgress = items.filter(i => i.status === 'in_progress').length
    const errors = items.filter(i => i.status === 'error').length
    
    // Get most recent timestamp from items
    const timestamps = items
      .map(i => i.timestamp)
      .filter(Boolean)
      .sort((a, b) => new Date(b) - new Date(a))
    const mostRecentTimestamp = timestamps[0] || null
    
    return {
      total,
      completed,
      inProgress,
      errors,
      isComplete: completed + errors === total && inProgress === 0,
      mostRecentTimestamp,
    }
  }, [items])

  // Check if any item in batch is selected
  const hasSelectedItem = items.some(i => i.id === selectedCheckId)

  const handleCancelBatch = async (e) => {
    e.stopPropagation()
    if (isCancelling) return
    
    setIsCancelling(true)
    try {
      logger.info('BatchGroup', `Cancelling batch ${batchId}`)
      await api.cancelBatch(batchId)
      await fetchHistory()
      logger.info('BatchGroup', `Batch ${batchId} cancelled`)
    } catch (error) {
      logger.error('BatchGroup', 'Failed to cancel batch', error)
    } finally {
      setIsCancelling(false)
    }
  }

  const handleDeleteClick = (e) => {
    e.stopPropagation()
    setIsConfirmingDelete(true)
  }

  const handleConfirmDelete = async (e) => {
    e.stopPropagation()
    try {
      // Delete all items in the batch
      for (const item of items) {
        await deleteCheck(item.id)
      }
      logger.info('BatchGroup', `Batch ${batchId} and all children deleted`)
    } catch (error) {
      logger.error('BatchGroup', 'Failed to delete batch', error)
    }
    setIsConfirmingDelete(false)
  }

  const handleCancelDelete = (e) => {
    e.stopPropagation()
    setIsConfirmingDelete(false)
  }

  const handleHeaderClick = () => {
    // If no child is selected, select first child
    if (!hasSelectedItem && items.length > 0) {
      selectCheck(items[0].id)
    }
  }

  const handleToggleClick = (e) => {
    e.stopPropagation()
    onToggle()
  }

  return (
    <div>
      {/* Batch header */}
      <div
        onClick={handleHeaderClick}
        className="w-full px-3 pr-4 py-2 text-left transition-colors cursor-pointer history-item-hoverable"
        style={{
          backgroundColor: hasSelectedItem 
            ? 'var(--color-bg-hover)' 
            : 'var(--color-bg-secondary)',
          borderBottom: !isCollapsed ? '1px solid var(--color-border)' : 'none',
          minHeight: '72px',
        }}
        onMouseEnter={(e) => {
          if (!hasSelectedItem) {
            e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
          }
        }}
        onMouseLeave={(e) => {
          if (!hasSelectedItem) {
            e.currentTarget.style.backgroundColor = 'var(--color-bg-secondary)'
          }
        }}
      >
        {/* Top row: icon + label + edit/status icons */}
        <div className="flex items-center gap-2">
          {/* Expand/collapse button */}
          <button
            onClick={handleToggleClick}
            className="p-1 -ml-1 rounded transition-colors flex-shrink-0"
            style={{ color: 'var(--color-text-muted)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-tertiary)'
              e.currentTarget.style.color = 'var(--color-text-primary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
              e.currentTarget.style.color = 'var(--color-text-muted)'
            }}
            title={isCollapsed ? 'Expand' : 'Collapse'}
          >
            <svg
              className="w-4 h-4 transition-transform"
              style={{ transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)' }}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {/* Batch icon */}
          <span className="text-base flex-shrink-0">📦</span>

          {/* Batch info */}
          <div className="flex-1 min-w-0">
            {isEditingLabel ? (
              <input
                type="text"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onBlur={handleEditSave}
                onKeyDown={handleEditKeyDown}
                onClick={(e) => e.stopPropagation()}
                autoFocus
                className="w-full px-2 py-0.5 text-sm rounded border focus:outline-none focus:ring-1"
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  borderColor: 'var(--color-accent)',
                  color: 'var(--color-text-primary)',
                }}
              />
            ) : (
              <div 
                className="text-sm font-medium truncate"
                style={{ color: 'var(--color-text-primary)' }}
                title={batchLabel || `Batch of ${stats.total} ${stats.total === 1 ? 'paper' : 'papers'}`}
              >
                {batchLabel || `Batch of ${stats.total} ${stats.total === 1 ? 'paper' : 'papers'}`}
              </div>
            )}
          </div>

          {/* Edit button, delete button - hidden until hover */}
          <div className="history-item-actions flex items-center gap-1 flex-shrink-0">
            {!isEditingLabel && !isConfirmingDelete && (
              <button
                onClick={handleEditStart}
                className="p-1 rounded transition-colors"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--color-accent)'
                  e.currentTarget.style.color = 'white'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent'
                  e.currentTarget.style.color = 'var(--color-text-secondary)'
                }}
                title="Edit batch label"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
              </button>
            )}
            
            {/* Delete button with confirmation */}
            {isConfirmingDelete ? (
              <div className="flex items-center gap-1 px-1 py-0.5 rounded" style={{ backgroundColor: 'var(--color-error-bg)' }}>
                <button
                  onClick={handleConfirmDelete}
                  className="p-0.5 rounded transition-colors"
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
                  className="p-0.5 rounded transition-colors"
                  style={{ color: 'var(--color-text-muted)' }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
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
            ) : (
              <button
                onClick={handleDeleteClick}
                className="p-1 rounded opacity-50 hover:opacity-100 transition-all"
                style={{ color: 'var(--color-text-muted)' }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--color-error-bg)'
                  e.currentTarget.style.color = 'var(--color-error)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent'
                  e.currentTarget.style.color = 'var(--color-text-muted)'
                }}
                title="Delete batch"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            )}
          </div>
        </div>

        {/* Date row */}
        {stats.mostRecentTimestamp && (
          <div 
            className="text-xs mt-1 ml-10"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {formatDate(stats.mostRecentTimestamp)}
          </div>
        )}

        {/* Bottom row: progress stats + cancel button */}
        <div className="flex items-center gap-2 mt-1 ml-10">
          <div 
            className="text-xs flex-1 flex items-center gap-1.5"
            style={{ color: 'var(--color-text-muted)' }}
          >
            <span>{stats.completed}/{stats.total} done</span>
            {stats.inProgress > 0 && (
              <svg className="w-3 h-3 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24" style={{ color: 'var(--color-accent)' }}>
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
          </div>

          {/* Cancel button for in-progress batches - only visible on hover */}
          {stats.inProgress > 0 && (
            <button
              onClick={handleCancelBatch}
              disabled={isCancelling}
              className="history-item-cancel text-xs px-2 py-0.5 rounded transition-colors flex-shrink-0"
              style={{
                backgroundColor: 'var(--color-error-bg)',
                color: 'var(--color-error)',
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
              title="Cancel all in batch"
            >
              {isCancelling ? '...' : 'Cancel'}
            </button>
          )}
        </div>
      </div>

      {/* Collapsed items */}
      {!isCollapsed && (
        <div className="pl-3 ml-3">
          {items.map(item => (
            <HistoryItem
              key={item.id}
              item={item}
              isSelected={item.id === selectedCheckId}
              compact
            />
          ))}
        </div>
      )}
    </div>
  )
}
