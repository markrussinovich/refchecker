import { useEffect } from 'react'
import InputSection from './InputSection'
import StatusSection from './StatusSection'
import StatsSection from './StatsSection'
import ReferenceList from './ReferenceList'
import { useCheckStore } from '../../stores/useCheckStore'
import { useHistoryStore } from '../../stores/useHistoryStore'

/**
 * Main panel containing input, status, stats, and references
 * All checks are treated as peers - no special handling for "current" vs "history"
 */
export default function MainPanel() {
  const { 
    status: checkStoreStatus, 
    references: checkStoreRefs, 
    stats: checkStoreStats, 
    currentCheckId,
    clearStatusFilter 
  } = useCheckStore()
  const { selectedCheck, selectedCheckId, isLoadingDetail, selectCheck } = useHistoryStore()

  // Determine what to display:
  // - selectedCheckId === -1: "New refcheck" placeholder -> show input form
  // - selectedCheckId is set: show that check's data from selectedCheck
  // - No selection but check running: show input (shouldn't happen normally)
  const isNewRefcheckSelected = selectedCheckId === -1
  const isViewingCheck = selectedCheckId !== null && selectedCheckId !== -1

  // Clear status filter when switching views
  useEffect(() => {
    clearStatusFilter()
  }, [selectedCheckId, clearStatusFilter])

  // Show input when "New refcheck" is selected OR no check and idle
  const showInput = isNewRefcheckSelected || (!isViewingCheck && checkStoreStatus === 'idle')
  
  // Show content when viewing any check
  const showContent = isViewingCheck

  // Unified data source - all checks treated equally
  // Source from selectedCheck for ANY selected check (current or not)
  // Fall back to checkStore only if selectedCheck isn't loaded yet for current check
  const isCurrentCheck = selectedCheckId === currentCheckId
  const hasSelectedCheckData = selectedCheck && selectedCheck.id === selectedCheckId
  
  // Determine status
  const displayStatus = hasSelectedCheckData 
    ? selectedCheck.status 
    : (isCurrentCheck ? checkStoreStatus : 'idle')
  
  const isInProgress = displayStatus === 'in_progress' || displayStatus === 'checking'
  const isComplete = displayStatus === 'completed' || displayStatus === 'cancelled'
  // Get paper title and source for export
  const displayPaperTitle = hasSelectedCheckData 
    ? (selectedCheck.custom_label || selectedCheck.paper_title)
    : null
  const displayPaperSource = hasSelectedCheckData 
    ? selectedCheck.paper_source 
    : null
  // Build unified references list FIRST (needed by buildStats)
  // For current check, prefer live checkStore data; for other checks, use selectedCheck
  const getReferences = () => {
    // Current check: use live WebSocket data from checkStore
    if (isCurrentCheck && checkStoreRefs && checkStoreRefs.length > 0) {
      return checkStoreRefs
    }
    
    // Other checks or current check without live data: use selectedCheck
    // Remap to 0-based indices since backend may send 1-based indices
    if (hasSelectedCheckData && selectedCheck.results) {
      return selectedCheck.results.map((ref, idx) => ({
        ...ref,
        index: idx  // Override with 0-based index
      }))
    }
    
    return []
  }

  const displayRefs = getReferences()

  // Build unified stats
  // For current check, prefer live checkStore stats; for other checks, compute from selectedCheck
  const buildStats = () => {
    // Current check: use live WebSocket data from checkStore
    if (isCurrentCheck && checkStoreStats && checkStoreStats.total_refs > 0) {
      return checkStoreStats
    }
    
    if (hasSelectedCheckData) {
      const totalRefs = selectedCheck.total_refs || 0
      // For cancelled checks, processed_refs may be 0 but we have results - use results length
      const resultsCount = displayRefs?.filter(r => 
        r.status && !['pending', 'checking'].includes(r.status.toLowerCase())
      ).length || 0
      const processedRefs = selectedCheck.processed_refs || resultsCount || 0
      const errorsCount = selectedCheck.errors_count || 0
      const warningsCount = selectedCheck.warnings_count || 0
      const suggestionsCount = selectedCheck.suggestions_count || 0
      const unverifiedCount = selectedCheck.unverified_count || 0
      
      // Use stored refs_verified if available, otherwise calculate
      const verifiedCount = selectedCheck.refs_verified ?? selectedCheck.verified_count ?? 
        Math.max(0, (isInProgress ? processedRefs : totalRefs) - errorsCount - warningsCount - unverifiedCount)
      
      // Use stored paper-level counts if available, otherwise compute from results
      let refsWithErrors = selectedCheck.refs_with_errors
      let refsWithWarningsOnly = selectedCheck.refs_with_warnings_only
      
      // If not stored, compute from results
      if (refsWithErrors === undefined && displayRefs?.length > 0) {
        refsWithErrors = displayRefs.filter(r => 
          r.status === 'error' || (r.errors?.some(e => e.error_type !== 'unverified'))
        ).length
      }
      if (refsWithWarningsOnly === undefined && displayRefs?.length > 0) {
        refsWithWarningsOnly = displayRefs.filter(r => 
          (r.status === 'warning' || r.warnings?.length > 0) && 
          r.status !== 'error' && !r.errors?.some(e => e.error_type !== 'unverified')
        ).length
      }
      
      return {
        total_refs: totalRefs,
        processed_refs: processedRefs,
        verified_count: verifiedCount,
        refs_verified: verifiedCount,
        errors_count: errorsCount,
        warnings_count: warningsCount,
        suggestions_count: suggestionsCount,
        unverified_count: unverifiedCount,
        refs_with_errors: refsWithErrors ?? 0,
        refs_with_warnings_only: refsWithWarningsOnly ?? 0,
        progress_percent: totalRefs > 0 ? (processedRefs / totalRefs) * 100 : 0,
      }
    }
    
    // Fallback to checkStore 
    if (checkStoreStats) {
      return checkStoreStats
    }
    
    // Default empty stats
    return {
      total_refs: 0,
      processed_refs: 0,
      verified_count: 0,
      refs_verified: 0,
      errors_count: 0,
      warnings_count: 0,
      suggestions_count: 0,
      unverified_count: 0,
      refs_with_errors: 0,
      refs_with_warnings_only: 0,
      progress_percent: 0,
    }
  }

  const displayStats = buildStats()

  return (
    <main 
      className="flex-1"
      style={{ backgroundColor: 'var(--color-bg-primary)', overflowY: 'scroll' }}
    >
      <div className="max-w-4xl mx-auto p-6 space-y-6">
        {/* Input Section */}
        {showInput && <InputSection />}

        {/* Status Section */}
        {showContent && (
          <StatusSection />
        )}

        {/* Stats Section */}
        {showContent && (
          <StatsSection 
            stats={displayStats}
            isComplete={isComplete}
            references={displayRefs}
            paperTitle={displayPaperTitle}
            paperSource={displayPaperSource}
          />
        )}

        {/* References List */}
        {showContent && (
          <ReferenceList 
            references={displayRefs}
            isLoading={isLoadingDetail}
            isCheckComplete={isComplete}
          />
        )}
      </div>
    </main>
  )
}
