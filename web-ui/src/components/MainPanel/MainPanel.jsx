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
  const isComplete = displayStatus === 'completed'

  // Build unified references list
  // For current check, prefer live checkStore data; for other checks, use selectedCheck
  const getReferences = () => {
    // Current check: use live WebSocket data from checkStore
    if (isCurrentCheck && checkStoreRefs && checkStoreRefs.length > 0) {
      return checkStoreRefs
    }
    
    // Other checks or current check without live data: use selectedCheck
    if (hasSelectedCheckData && selectedCheck.results) {
      return selectedCheck.results
    }
    
    return []
  }

  // Build unified stats
  // For current check, prefer live checkStore stats; for other checks, compute from selectedCheck
  const buildStats = () => {
    // Current check: use live WebSocket data from checkStore
    if (isCurrentCheck && checkStoreStats && checkStoreStats.total_refs > 0) {
      return checkStoreStats
    }
    
    if (hasSelectedCheckData) {
      const totalRefs = selectedCheck.total_refs || 0
      const processedRefs = selectedCheck.processed_refs || 0
      const errorsCount = selectedCheck.errors_count || 0
      const warningsCount = selectedCheck.warnings_count || 0
      const unverifiedCount = selectedCheck.unverified_count || 0
      
      // For in-progress checks, verified = processed - errors - warnings - unverified
      // For completed checks, verified = total - errors - warnings - unverified
      const verifiedCount = isInProgress
        ? Math.max(0, processedRefs - errorsCount - warningsCount - unverifiedCount)
        : Math.max(0, totalRefs - errorsCount - warningsCount - unverifiedCount)
      
      return {
        total_refs: totalRefs,
        processed_refs: processedRefs,
        verified_count: verifiedCount,
        errors_count: errorsCount,
        warnings_count: warningsCount,
        unverified_count: unverifiedCount,
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
      errors_count: 0,
      warnings_count: 0,
      unverified_count: 0,
      progress_percent: 0,
    }
  }

  const displayStats = buildStats()
  const displayRefs = getReferences()

  // Debug: log what we're displaying
  console.log(`[DEBUG-MAINPANEL] selectedCheckId=${selectedCheckId} currentCheckId=${currentCheckId} isCurrentCheck=${isCurrentCheck}`)
  console.log(`[DEBUG-MAINPANEL] hasSelectedCheckData=${hasSelectedCheckData} selectedCheck.results=${selectedCheck?.results?.length} checkStoreRefs=${checkStoreRefs?.length}`)
  console.log(`[DEBUG-MAINPANEL] displayRefs.length=${displayRefs?.length}`)

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
          />
        )}

        {/* References List */}
        {showContent && (
          <ReferenceList 
            references={displayRefs}
            isLoading={isLoadingDetail}
          />
        )}
      </div>
    </main>
  )
}
