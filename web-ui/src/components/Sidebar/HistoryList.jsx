import { useHistoryStore } from '../../stores/useHistoryStore'
import HistoryItem from './HistoryItem'

/**
 * Scrollable list of historical checks
 */
export default function HistoryList() {
  const { history, selectedCheckId, isLoading } = useHistoryStore()

  // Debug: log when component re-renders with history state
  console.log(`[DEBUG-RENDER] HistoryList rendering: ${history.length} items, first few: ${history.slice(0, 3).map(h => `${h.id}:${h.status}:${h.total_refs}`).join(', ')}`)

  if (isLoading && history.length === 0) {
    return (
      <div 
        className="flex-1 flex items-center justify-center"
        style={{ color: 'var(--color-text-muted)' }}
      >
        <svg className="animate-spin h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Loading...
      </div>
    )
  }

  if (history.length === 0) {
    return (
      <div 
        className="flex-1 flex flex-col items-center justify-center p-4 text-center"
        style={{ color: 'var(--color-text-muted)' }}
      >
        <svg className="w-12 h-12 mb-3 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p className="text-sm">No checks yet</p>
        <p className="text-xs mt-1">Start a check to see history</p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      {history.map(item => (
        <HistoryItem
          key={item.id}
          item={item}
          isSelected={item.id === selectedCheckId}
        />
      ))}
    </div>
  )
}
