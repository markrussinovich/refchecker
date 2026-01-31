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
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false)
  const [isCancelling, setIsCancelling] = useState(false)
  const { fetchHistory } = useHistoryStore()

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

  const handleDeleteBatch = async (e) => {
    e.stopPropagation()
    try {
      logger.info('BatchGroup', `Deleting batch ${batchId}`)
      await api.deleteBatch(batchId)
      await fetchHistory()
      logger.info('BatchGroup', `Batch ${batchId} deleted`)
    } catch (error) {
      logger.error('BatchGroup', 'Failed to delete batch', error)
    }
    setIsConfirmingDelete(false)
  }

  return (
    <div>
      {/* Batch header */}
      <button
        onClick={onToggle}
        className="w-full px-3 py-2 flex items-center gap-2 text-left transition-colors"
        style={{
          backgroundColor: hasSelectedItem 
            ? 'var(--color-bg-hover)' 
            : 'var(--color-bg-tertiary)',
          borderBottom: '1px solid var(--color-border)',
        }}
      >
        {/* Expand/collapse icon */}
        <span 
          className="text-xs transition-transform"
          style={{ 
            transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
            color: 'var(--color-text-muted)',
          }}
        >
          ▼
        </span>

        {/* Batch icon */}
        <span className="text-base">📦</span>

        {/* Batch info */}
        <div className="flex-1 min-w-0">
          <div 
            className="text-sm font-medium truncate"
            style={{ color: 'var(--color-text-primary)' }}
          >
            {batchLabel || `Batch of ${stats.total} papers`}
          </div>
          <div 
            className="text-xs flex items-center gap-2"
            style={{ color: 'var(--color-text-muted)' }}
          >
            <span>{stats.completed}/{stats.total} done</span>
            {stats.inProgress > 0 && (
              <span className="animate-pulse" style={{ color: 'var(--color-accent)' }}>
                {stats.inProgress} running
              </span>
            )}
          </div>
        </div>

        {/* Status indicator and actions */}
        <div className="flex items-center gap-1">
          {/* Cancel button for in-progress batches */}
          {stats.inProgress > 0 && (
            <button
              onClick={handleCancelBatch}
              disabled={isCancelling}
              className="text-xs px-2 py-0.5 rounded transition-colors"
              style={{
                backgroundColor: 'var(--color-error-bg)',
                color: 'var(--color-error)',
                opacity: isCancelling ? 0.5 : 1,
              }}
              title="Cancel all in batch"
            >
              {isCancelling ? '...' : 'Cancel'}
            </button>
          )}
          
          {/* Delete confirmation or button */}
          {isConfirmingDelete ? (
            <div className="flex items-center gap-1">
              <button
                onClick={handleDeleteBatch}
                className="text-xs px-1.5 py-0.5 rounded"
                style={{
                  backgroundColor: 'var(--color-error)',
                  color: 'white',
                }}
              >
                ✓
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setIsConfirmingDelete(false) }}
                className="text-xs px-1.5 py-0.5 rounded"
                style={{
                  backgroundColor: 'var(--color-bg-tertiary)',
                  color: 'var(--color-text-muted)',
                }}
              >
                ✕
              </button>
            </div>
          ) : (
            <button
              onClick={(e) => { e.stopPropagation(); setIsConfirmingDelete(true) }}
              className="text-xs px-1.5 py-0.5 rounded opacity-50 hover:opacity-100 transition-opacity"
              style={{ color: 'var(--color-error)' }}
              title="Delete batch"
            >
              🗑️
            </button>
          )}
          
          {/* Status icons */}
          {stats.errors > 0 && (
            <span 
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: 'var(--color-error)' }}
              title={`${stats.errors} failed`}
            />
          )}
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
      </button>

      {/* Collapsed items */}
      {!isCollapsed && (
        <div 
          className="pl-6"
          style={{ 
            borderLeft: '2px solid var(--color-accent-muted)',
            marginLeft: '1rem',
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
