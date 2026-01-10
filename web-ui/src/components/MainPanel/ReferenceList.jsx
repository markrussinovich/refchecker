import { useMemo } from 'react'
import ReferenceCard from '../ReferenceCard/ReferenceCard'
import { useCheckStore } from '../../stores/useCheckStore'

/**
 * Derive status from reference data, trusting backend final statuses
 */
const computeDerivedStatus = (ref) => {
  const baseStatus = (ref.status || '').trim().toLowerCase()
  
  // Trust backend's final status values
  if (['error', 'warning', 'unverified', 'verified'].includes(baseStatus)) {
    return baseStatus
  }
  
  // Keep pending and checking distinct so UI shows appropriate icons
  // - pending: clock icon (waiting in queue)
  // - checking: spinner (actively being verified)
  if (baseStatus === 'pending') return 'pending'
  if (['checking', 'in_progress', 'queued', 'processing', 'started'].includes(baseStatus)) return 'checking'
  
  // For unknown states, derive from errors/warnings arrays
  const hasErrors = Array.isArray(ref.errors) && ref.errors.some(
    e => (e?.error_type || '').toLowerCase() !== 'unverified'
  )
  const hasWarnings = !hasErrors && Array.isArray(ref.warnings) && ref.warnings.length > 0

  if (hasErrors) return 'error'
  if (hasWarnings) return 'warning'
  // No status and no issues = verified
  return 'verified'
}

/**
 * List of references being checked
 */
export default function ReferenceList({ references, isLoading }) {
  const { statusFilter } = useCheckStore()

  // Memoize all derived data to ensure consistency within a render
  const { sortedReferences, filteredReferences, normalizedFilters } = useMemo(() => {
    const filters = statusFilter.map(f => f.toLowerCase())
    
    const sorted = (references || []).slice().sort((a, b) => {
      const aIndex = typeof a?.index === 'number' ? a.index : Number.MAX_SAFE_INTEGER
      const bIndex = typeof b?.index === 'number' ? b.index : Number.MAX_SAFE_INTEGER
      return aIndex - bIndex
    })

    const normalized = sorted.map(ref => ({
      ...ref,
      status: computeDerivedStatus(ref),
      errors: Array.isArray(ref.errors) ? ref.errors : [],
      warnings: Array.isArray(ref.warnings) ? ref.warnings : [],
    }))

    const filtered = normalized.filter(ref => {
      const status = (ref.status || '').toLowerCase()
      // If no filter, show all references including pending/checking
      if (filters.length === 0) {
        return true
      }
      
      // When filtering by status, hide pending/checking since they don't have a final status yet
      if (status === 'pending' || status === 'checking') {
        return false
      }
      
      // Match filter to status (any of the selected filters)
      return filters.includes(status)
    })

    return { sortedReferences: sorted, filteredReferences: filtered, normalizedFilters: filters }
  }, [references, statusFilter])

  if (isLoading) {
    return (
      <div 
        className="rounded-lg border p-8 text-center"
        style={{
          backgroundColor: 'var(--color-bg-secondary)',
          borderColor: 'var(--color-border)',
        }}
      >
        <svg 
          className="animate-spin h-8 w-8 mx-auto mb-3" 
          fill="none" 
          viewBox="0 0 24 24"
          style={{ color: 'var(--color-accent)' }}
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <p style={{ color: 'var(--color-text-muted)' }}>
          Loading references...
        </p>
      </div>
    )
  }

  if (!references || references.length === 0) {
    return (
      <div 
        className="rounded-lg border p-8 text-center"
        style={{
          backgroundColor: 'var(--color-bg-secondary)',
          borderColor: 'var(--color-border)',
        }}
      >
        <svg 
          className="w-12 h-12 mx-auto mb-3 opacity-50" 
          fill="none" 
          viewBox="0 0 24 24" 
          stroke="currentColor"
          style={{ color: 'var(--color-text-muted)' }}
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <p style={{ color: 'var(--color-text-muted)' }}>
          No references extracted yet
        </p>
        <p 
          className="text-sm mt-1"
          style={{ color: 'var(--color-text-muted)' }}
        >
          References will appear here as they are found
        </p>
      </div>
    )
  }

  return (
    <div 
      className="rounded-lg border overflow-hidden"
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)',
      }}
    >
      <div 
        className="px-4 py-3 border-b flex items-center justify-between"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <h3 
          className="font-semibold"
          style={{ color: 'var(--color-text-primary)' }}
        >
          References ({sortedReferences.length})
        </h3>
        {statusFilter.length > 0 && (
          <span 
            className="text-sm px-2 py-1 rounded"
            style={{ 
              backgroundColor: 'var(--color-bg-tertiary)',
              color: 'var(--color-text-secondary)' 
            }}
          >
            Showing {filteredReferences.length} ({statusFilter.join(', ')})
          </span>
        )}
      </div>

      <div className="divide-y" style={{ borderColor: 'var(--color-border)' }}>
        {filteredReferences.map((ref, displayIndex) => (
            <ReferenceCard 
              key={`ref-${ref.index ?? displayIndex}-${displayIndex}`} 
              reference={ref} 
              index={ref.index ?? displayIndex}
              displayIndex={displayIndex}
              totalRefs={sortedReferences.length}
            />
        ))}
      </div>
    </div>
  )
}
