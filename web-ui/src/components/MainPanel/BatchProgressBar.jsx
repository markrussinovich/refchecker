import { useMemo } from 'react'

/**
 * Displays batch progress summary when viewing a batch of papers
 */
export default function BatchProgressBar({ batchChecks, batchLabel }) {
  const stats = useMemo(() => {
    if (!batchChecks || batchChecks.length === 0) return null

    const total = batchChecks.length
    const completed = batchChecks.filter(c => c.status === 'completed').length
    const inProgress = batchChecks.filter(c => c.status === 'in_progress').length
    const errors = batchChecks.filter(c => c.status === 'error').length
    const cancelled = batchChecks.filter(c => c.status === 'cancelled').length
    
    // Aggregate reference stats from completed checks
    const totalRefs = batchChecks.reduce((sum, c) => sum + (c.total_refs || 0), 0)
    const totalErrors = batchChecks.reduce((sum, c) => sum + (c.errors_count || 0), 0)
    const totalWarnings = batchChecks.reduce((sum, c) => sum + (c.warnings_count || 0), 0)
    
    const progress = total > 0 ? Math.round((completed / total) * 100) : 0
    const isComplete = completed + errors + cancelled === total

    return {
      total,
      completed,
      inProgress,
      errors,
      cancelled,
      totalRefs,
      totalErrors,
      totalWarnings,
      progress,
      isComplete,
    }
  }, [batchChecks])

  if (!stats) return null

  return (
    <div 
      className="rounded-lg border p-4 mb-4"
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)',
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">📦</span>
          <h3 
            className="font-semibold"
            style={{ color: 'var(--color-text-primary)' }}
          >
            {batchLabel || 'Batch Processing'}
          </h3>
        </div>
        <span 
          className="text-sm font-medium px-2 py-0.5 rounded"
          style={{
            backgroundColor: stats.isComplete 
              ? 'var(--color-success-bg)' 
              : 'var(--color-accent-muted)',
            color: stats.isComplete 
              ? 'var(--color-success)' 
              : 'var(--color-accent)',
          }}
        >
          {stats.isComplete ? 'Complete' : `${stats.progress}%`}
        </span>
      </div>

      {/* Progress bar */}
      <div 
        className="h-2 rounded-full overflow-hidden mb-3"
        style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
      >
        <div 
          className="h-full transition-all duration-300 rounded-full"
          style={{ 
            width: `${stats.progress}%`,
            backgroundColor: stats.errors > 0 
              ? 'var(--color-warning)' 
              : 'var(--color-success)',
          }}
        />
      </div>

      {/* Stats row */}
      <div className="flex flex-wrap gap-4 text-sm">
        <div className="flex items-center gap-1.5">
          <span style={{ color: 'var(--color-text-muted)' }}>Papers:</span>
          <span style={{ color: 'var(--color-text-primary)' }}>
            {stats.completed}/{stats.total}
          </span>
        </div>
        
        {stats.inProgress > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="animate-pulse">⏳</span>
            <span style={{ color: 'var(--color-accent)' }}>
              {stats.inProgress} in progress
            </span>
          </div>
        )}
        
        {stats.errors > 0 && (
          <div className="flex items-center gap-1.5">
            <span>❌</span>
            <span style={{ color: 'var(--color-error)' }}>
              {stats.errors} failed
            </span>
          </div>
        )}

        {stats.isComplete && stats.totalRefs > 0 && (
          <>
            <div className="flex items-center gap-1.5">
              <span style={{ color: 'var(--color-text-muted)' }}>Refs:</span>
              <span style={{ color: 'var(--color-text-primary)' }}>
                {stats.totalRefs}
              </span>
            </div>
            
            {stats.totalErrors > 0 && (
              <div className="flex items-center gap-1.5">
                <span style={{ color: 'var(--color-error)' }}>
                  {stats.totalErrors} errors
                </span>
              </div>
            )}
            
            {stats.totalWarnings > 0 && (
              <div className="flex items-center gap-1.5">
                <span style={{ color: 'var(--color-warning)' }}>
                  {stats.totalWarnings} warnings
                </span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
