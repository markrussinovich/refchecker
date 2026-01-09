import { useCheckStore } from '../../stores/useCheckStore'
import { useHistoryStore } from '../../stores/useHistoryStore'

/**
 * Status section showing current check progress
 */
export default function StatusSection() {
  const { status, statusMessage, progress, paperTitle } = useCheckStore()
  const { selectedCheck, selectedCheckId } = useHistoryStore()

  // Viewing historical check
  const isViewingHistory = selectedCheckId && status === 'idle'
  
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
            className="w-10 h-10 rounded-full flex items-center justify-center"
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
          <div className="flex-1">
            <h3 
              className="font-medium"
              style={{ color: 'var(--color-text-primary)' }}
            >
              {selectedCheck.custom_label || selectedCheck.paper_title || 'Check Results'}
            </h3>
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
            className="w-5 h-5 animate-spin" 
            fill="none" 
            viewBox="0 0 24 24"
            style={{ color: 'var(--color-accent)' }}
          >
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        )
      case 'completed':
        return (
          <svg 
            className="w-5 h-5" 
            fill="none" 
            viewBox="0 0 24 24" 
            stroke="currentColor"
            style={{ color: 'var(--color-success)' }}
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        )
      case 'cancelled':
        return (
          <svg 
            className="w-5 h-5" 
            fill="none" 
            viewBox="0 0 24 24" 
            stroke="currentColor"
            style={{ color: 'var(--color-warning)' }}
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        )
      case 'error':
        return (
          <svg 
            className="w-5 h-5" 
            fill="none" 
            viewBox="0 0 24 24" 
            stroke="currentColor"
            style={{ color: 'var(--color-error)' }}
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
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
          className="w-10 h-10 rounded-full flex items-center justify-center"
          style={{ backgroundColor: getStatusBgColor() }}
        >
          {getStatusIcon()}
        </div>
        <div className="flex-1">
          {paperTitle && (
            <h3 
              className="font-medium"
              style={{ color: 'var(--color-text-primary)' }}
            >
              {paperTitle}
            </h3>
          )}
          <p 
            className="text-sm"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {statusMessage}
          </p>
        </div>
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
          <p 
            className="text-xs mt-1 text-right"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {Math.round(progress)}%
          </p>
        </div>
      )}
    </div>
  )
}
