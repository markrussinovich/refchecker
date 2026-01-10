import { useEffect } from 'react'
import InputSection from './InputSection'
import StatusSection from './StatusSection'
import StatsSection from './StatsSection'
import ReferenceList from './ReferenceList'
import { useCheckStore } from '../../stores/useCheckStore'
import { useHistoryStore } from '../../stores/useHistoryStore'

/**
 * Main panel containing input, status, stats, and references
 */
export default function MainPanel() {
  const { 
    status: checkStatus, 
    references, 
    stats, 
    currentCheckId,
    clearStatusFilter 
  } = useCheckStore()
  const { selectedCheck, selectedCheckId, isLoadingDetail, selectCheck } = useHistoryStore()

  // Determine what to display:
  // - If a history item is selected that's NOT the current running check, show history
  // - Otherwise show the current check state
  // Note: Check selectedCheckId first, then loading state, then selectedCheck
  const isViewingHistory = selectedCheckId !== null && selectedCheckId !== -1 && selectedCheckId !== currentCheckId
  const displayData = isViewingHistory ? selectedCheck : null
  
  // Clear status filter when switching views
  useEffect(() => {
    clearStatusFilter()
  }, [selectedCheckId, clearStatusFilter])

  // Show something if we're checking OR viewing history (or loading history)
  const showContent = checkStatus !== 'idle' || isViewingHistory
  const showInput = !isViewingHistory && checkStatus === 'idle'

  const handleReturnToActiveCheck = () => {
    if (currentCheckId) {
      selectCheck(currentCheckId)
    }
  }

  return (
    <main 
      className="flex-1"
      style={{ backgroundColor: 'var(--color-bg-primary)', overflowY: 'scroll' }}
    >
      <div className="max-w-4xl mx-auto p-6 space-y-6">
        {/* Input Section */}
        {showInput && <InputSection />}

        {/* Status Section - only show when checking or viewing history */}
        {showContent && (
          <StatusSection isViewingHistory={isViewingHistory} />
        )}

        {/* Stats Section */}
        {showContent && (
          <StatsSection 
            stats={isViewingHistory ? {
              total_refs: displayData?.total_refs || 0,
              verified_count: (displayData?.total_refs || 0) - (displayData?.errors_count || 0) - (displayData?.warnings_count || 0) - (displayData?.unverified_count || 0),
              errors_count: displayData?.errors_count || 0,
              warnings_count: displayData?.warnings_count || 0,
              unverified_count: displayData?.unverified_count || 0,
              processed_refs: displayData?.total_refs || 0,
              progress_percent: 100,
            } : stats}
            isComplete={isViewingHistory || checkStatus === 'completed'}
          />
        )}

        {/* References List */}
        {showContent && (
          <ReferenceList 
            references={isViewingHistory ? (displayData?.results || []) : references}
            isLoading={isLoadingDetail}
          />
        )}
      </div>
    </main>
  )
}
