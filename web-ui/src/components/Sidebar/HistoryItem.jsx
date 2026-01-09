import { useState } from 'react'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { formatDate } from '../../utils/formatters'
import { logger } from '../../utils/logger'

/**
 * Individual history item in the sidebar
 */
export default function HistoryItem({ item, isSelected }) {
  const { selectCheck, updateLabel, deleteCheck } = useHistoryStore()
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [isHovered, setIsHovered] = useState(false)
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false)

  const displayLabel = item.custom_label || item.paper_title || 'Untitled Check'

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

  // Status indicator based on errors
  const getStatusIndicator = () => {
    if (item.errors_count > 0) {
      return { color: 'var(--color-error)', label: `${item.errors_count} errors` }
    }
    if (item.warnings_count > 0) {
      return { color: 'var(--color-warning)', label: `${item.warnings_count} warnings` }
    }
    return { color: 'var(--color-success)', label: 'All verified' }
  }

  const status = getStatusIndicator()

  return (
    <div
      onClick={handleClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className="px-4 py-3 cursor-pointer transition-colors border-b relative"
      style={{
        backgroundColor: isSelected ? 'var(--color-bg-tertiary)' : 'transparent',
        borderColor: 'var(--color-border)',
      }}
      onMouseOver={(e) => {
        if (!isSelected) {
          e.currentTarget.style.backgroundColor = 'var(--color-bg-primary)'
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
        
        {/* Date */}
        <div 
          className="text-xs mt-1"
          style={{ color: 'var(--color-text-muted)' }}
        >
          {formatDate(item.timestamp)}
        </div>

        {/* Stats summary */}
        <div className="flex items-center gap-2 mt-1">
          <span 
            className="text-xs"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {item.total_refs} refs
          </span>
          <span 
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: status.color }}
            title={status.label}
          />
        </div>
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
      ) : isHovered && !isEditing && (
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
              className="p-1 rounded transition-colors"
              style={{ color: 'var(--color-text-secondary)' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--color-bg-tertiary)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent'
              }}
              title="Edit label"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
            </button>
            <button
              onClick={handleDelete}
              className="p-1 rounded transition-colors"
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
