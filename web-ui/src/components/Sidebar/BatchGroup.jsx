import { useMemo, useState } from 'react'
import HistoryItem from './HistoryItem'
import * as api from '../../utils/api'
import { useHistoryStore } from '../../stores/useHistoryStore'
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
  const [isEditingLabel, setIsEditingLabel] = useState(false)
  const [editValue, setEditValue] = useState('')
  const { fetchHistory } = useHistoryStore()

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
    const hasErrors = items.some(i => (i.errors_count || 0) > 0)
    const hasWarnings = items.some(i => (i.warnings_count || 0) > 0)
    
    return {
      total,
      completed,
      inProgress,
      errors,
      hasErrors,
      hasWarnings,
      isComplete: completed + errors === total && inProgress === 0,
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

  return (
    <div>
      {/* Batch header */}
      <button
        onClick={onToggle}
        className="w-full px-3 py-2 text-left transition-colors"
        style={{
          backgroundColor: hasSelectedItem 
            ? 'var(--color-bg-hover)' 
            : 'var(--color-bg-tertiary)',
          borderBottom: '1px solid var(--color-border)',
          minHeight: '72px',
        }}
      >
        {/* Top row: icon + label + edit/status icons */}
        <div className="flex items-center gap-2">
          {/* Expand/collapse icon */}
          <svg
            className="w-4 h-4 transition-transform flex-shrink-0"
            style={{ 
              transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
              color: 'var(--color-text-muted)',
            }}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>

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

          {/* Edit button and status icons */}
          <div className="flex items-center gap-1 flex-shrink-0">
            {!isEditingLabel && (
              <button
                onClick={handleEditStart}
                className="text-xs px-1 py-0.5 rounded opacity-50 hover:opacity-100 transition-opacity"
                style={{ color: 'var(--color-text-secondary)' }}
                title="Edit batch label"
              >
                ✏️
              </button>
            )}
            
            {/* Status icons */}
            {stats.hasErrors && (
              <span 
                className="text-xs"
                style={{ color: 'var(--color-error)' }}
              >
                ❌
              </span>
            )}
            {stats.hasWarnings && !stats.hasErrors && (
              <span 
                className="text-xs"
                style={{ color: 'var(--color-warning)' }}
              >
                ⚠️
              </span>
            )}
            {stats.isComplete && !stats.hasErrors && !stats.hasWarnings && (
              <span 
                className="text-xs"
                style={{ color: 'var(--color-success)' }}
              >
                ✓
              </span>
            )}
          </div>
        </div>

        {/* Bottom row: progress stats + cancel button */}
        <div className="flex items-center gap-2 mt-1 ml-10">
          <div 
            className="text-xs flex-1"
            style={{ color: 'var(--color-text-muted)' }}
          >
            <span>{stats.completed}/{stats.total} done</span>
            {stats.inProgress > 0 && (
              <span className="animate-pulse ml-2" style={{ color: 'var(--color-accent)' }}>
                {stats.inProgress} running
              </span>
            )}
          </div>

          {/* Cancel button for in-progress batches */}
          {stats.inProgress > 0 && (
            <button
              onClick={handleCancelBatch}
              disabled={isCancelling}
              className="text-xs px-2 py-0.5 rounded transition-colors flex-shrink-0"
              style={{
                backgroundColor: 'var(--color-error-bg)',
                color: 'var(--color-error)',
                opacity: isCancelling ? 0.5 : 1,
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
      </button>

      {/* Collapsed items */}
      {!isCollapsed && (
        <div 
          className="pl-3"
          style={{ 
            borderLeft: '2px solid var(--color-accent-muted)',
            marginLeft: '0.75rem',
          }}
        >
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
