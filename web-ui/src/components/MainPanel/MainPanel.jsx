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
  const { status: checkStatus, references, stats } = useCheckStore()
  const { selectedCheck, selectedCheckId, isLoadingDetail } = useHistoryStore()

  // Determine what to display: current check or historical check
  const isViewingHistory = selectedCheckId && checkStatus === 'idle'
  const displayData = isViewingHistory ? selectedCheck : null

  return (
    <main 
      className="flex-1 overflow-y-auto"
      style={{ backgroundColor: 'var(--color-bg-primary)' }}
    >
      <div className="max-w-4xl mx-auto p-6 space-y-6">
        {/* Input Section */}
        <InputSection />

        {/* Status Section - only show when checking */}
        {(checkStatus !== 'idle' || isViewingHistory) && (
          <StatusSection />
        )}

        {/* Stats Section */}
        {(checkStatus !== 'idle' || isViewingHistory) && (
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
        {(checkStatus !== 'idle' || isViewingHistory) && (
          <ReferenceList 
            references={isViewingHistory ? (displayData?.results || []) : references}
            isLoading={isLoadingDetail}
          />
        )}
      </div>
    </main>
  )
}
