import { useMemo } from 'react'
import ReferenceCard from '../ReferenceCard/ReferenceCard'
import { useCheckStore } from '../../stores/useCheckStore'
import { getEffectiveReferenceStatus, llmFoundMetadataMatchesCitation } from '../../utils/referenceStatus'

/**
 * Derive status from reference data, trusting backend final statuses
 * @param {Object} ref - Reference object
 * @param {boolean} isCheckComplete - Whether the overall check has completed/cancelled
 */
const computeDerivedStatus = (ref, isCheckComplete = false) => {
  return getEffectiveReferenceStatus(ref, isCheckComplete)
}

/**
 * List of references being checked
 */
export default function ReferenceList({ references, isLoading, isCheckComplete = false }) {
  const statusFilter = useCheckStore(s => s.statusFilter)

  // Memoize all derived data to ensure consistency within a render
  const { sortedReferences, filteredReferences } = useMemo(() => {
    const filters = statusFilter.map(f => f.toLowerCase())
    
    const sorted = (references || []).slice().sort((a, b) => {
      const aIndex = typeof a?.index === 'number' ? a.index : Number.MAX_SAFE_INTEGER
      const bIndex = typeof b?.index === 'number' ? b.index : Number.MAX_SAFE_INTEGER
      return aIndex - bIndex
    })

    const normalized = sorted.map(ref => ({
      ...ref,
      status: computeDerivedStatus(ref, isCheckComplete),
      errors: Array.isArray(ref.errors) ? ref.errors : [],
      warnings: Array.isArray(ref.warnings) ? ref.warnings : [],
    }))

    const filtered = normalized.filter(ref => {
      const status = (ref.status || '').toLowerCase()
      // If no filter, show all references including pending/checking/unchecked
      if (filters.length === 0) {
        return true
      }
      
      // Inclusive filtering: show refs that HAVE the selected issue type
      // (even if they also have other issues)
      return filters.some(filter => {
        switch (filter) {
          case 'verified':
            // Verified includes both pure verified AND those with only suggestions
            // (suggestions are for verified papers that could be improved)
            return status === 'verified' || status === 'suggestion'
          case 'error':
            // Has any error (non-unverified), but exclude refs already
            // classified as hallucinated — those errors are evidence of
            // the hallucination, displayed under the hallucinated card.
            if (status === 'hallucination') return false
            return ref.errors?.some(e => e.error_type !== 'unverified')
          case 'warning':
            // Has any warning, excluding hallucinated refs.
            if (status === 'hallucination') return false
            return ref.warnings?.length > 0
          case 'suggestion':
            // Has any suggestion
            return ref.suggestions?.length > 0
          case 'unverified':
            // Don't match refs currently showing as 'checking' (awaiting LLM check)
            if (status === 'checking') return false
            if (status === 'unverified' || status === 'hallucination') return true
            if (ref.errors?.some(e => e.error_type === 'unverified')) return true
            // Also include refs flagged LIKELY by the hallucination LLM, even when
            // error precedence would otherwise hide them, but skip cases where the
            // LLM-found metadata actually matches the citation.
            return ref.hallucination_assessment?.verdict === 'LIKELY' &&
              !llmFoundMetadataMatchesCitation(ref)
          case 'hallucination':
            if (status === 'hallucination') return true
            return ref.hallucination_assessment?.verdict === 'LIKELY' &&
              !llmFoundMetadataMatchesCitation(ref)
          default:
            // For other statuses (pending, checking, unchecked), match exactly
            return status === filter
        }
      })
    })

    return { sortedReferences: sorted, filteredReferences: filtered }
  }, [references, statusFilter, isCheckComplete])

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
      className="rounded-lg border overflow-hidden relative"
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)',
      }}
    >
      <div 
        className="px-4 py-3 border-b flex items-center justify-between relative"
        style={{ borderColor: 'var(--color-border)', minHeight: '48px' }}
      >
        <h3 
          className="font-semibold"
          style={{ color: 'var(--color-text-primary)' }}
        >
          References ({sortedReferences.length})
        </h3>
        {statusFilter.length > 0 && (
          <span 
            className="absolute right-4 text-sm px-2 py-1 rounded"
            style={{ 
              backgroundColor: 'var(--color-bg-tertiary)',
              color: 'var(--color-text-secondary)' 
            }}
          >
            Showing {filteredReferences.length} ({statusFilter.join(', ')})
          </span>
        )}
      </div>

      <div 
        className="divide-y"
        style={{ borderColor: 'var(--color-border)' }}
      >
        {filteredReferences.map((ref, displayIndex) => (
            <ReferenceCard 
              key={`ref-${ref.index ?? displayIndex}-${displayIndex}`} 
              reference={ref} 
              index={ref.index ?? displayIndex}
              displayIndex={displayIndex}
              totalRefs={sortedReferences.length}
              isCheckComplete={isCheckComplete}
            />
        ))}
      </div>
    </div>
  )
}
