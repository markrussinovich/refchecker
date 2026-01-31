import { useEffect, useState, useRef, useMemo } from 'react'
import { useHistoryStore } from '../../stores/useHistoryStore'
import HistoryItem from './HistoryItem'
import BatchGroup from './BatchGroup'

/**
 * Scrollable list of historical checks, with batch grouping
 */
export default function HistoryList() {
  const { history, selectedCheckId, isLoading, error, scrollTrigger } = useHistoryStore()
  const [showTimeoutMessage, setShowTimeoutMessage] = useState(false)
  const [collapsedBatches, setCollapsedBatches] = useState({})
  const scrollContainerRef = useRef(null)
  
  // Group history items by batch_id
  const groupedHistory = useMemo(() => {
    const groups = []
    const batchMap = new Map()
    
    for (const item of history) {
      if (item.batch_id) {
        if (!batchMap.has(item.batch_id)) {
          const batchGroup = {
            type: 'batch',
            batch_id: item.batch_id,
            batch_label: item.batch_label,
            items: [],
            timestamp: item.timestamp,
          }
          batchMap.set(item.batch_id, batchGroup)
          groups.push(batchGroup)
        }
        batchMap.get(item.batch_id).items.push(item)
      } else {
        groups.push({ type: 'single', item })
      }
    }
    
    return groups
  }, [history])
  
  const toggleBatchCollapse = (batchId) => {
    setCollapsedBatches(prev => ({
      ...prev,
      [batchId]: !prev[batchId],
    }))
  }
  
  // Scroll to top when scrollTrigger changes (New Refcheck button clicked)
  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = 0
    }
  }, [scrollTrigger])
  
  // Show a timeout message if loading takes too long
  useEffect(() => {
    if (isLoading && history.length === 0) {
      const timer = setTimeout(() => {
        setShowTimeoutMessage(true)
      }, 5000) // Show message after 5 seconds
      return () => clearTimeout(timer)
    } else {
      setShowTimeoutMessage(false)
    }
  }, [isLoading, history.length])

  if (isLoading && history.length === 0) {
    return (
      <div 
        className="flex-1 flex flex-col items-center justify-center p-4"
        style={{ color: 'var(--color-text-muted)' }}
      >
        <div className="flex items-center">
          <svg className="animate-spin h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading...
        </div>
        {showTimeoutMessage && (
          <p className="text-xs mt-2 text-center">
            Taking longer than expected...
            <br />
            Check if the backend is running on port 8000
          </p>
        )}
      </div>
    )
  }

  if (error && history.length === 0) {
    return (
      <div 
        className="flex-1 flex flex-col items-center justify-center p-4 text-center"
        style={{ color: 'var(--color-text-muted)' }}
      >
        <svg className="w-12 h-12 mb-3 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <p className="text-sm text-red-400">Failed to connect to backend</p>
        <p className="text-xs mt-1">Make sure the server is running</p>
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
    <div ref={scrollContainerRef} className="flex-1 overflow-y-auto">
      {groupedHistory.map((group, index) => {
        if (group.type === 'batch') {
          return (
            <BatchGroup
              key={group.batch_id}
              batchId={group.batch_id}
              batchLabel={group.batch_label}
              items={group.items}
              isCollapsed={collapsedBatches[group.batch_id] ?? false}
              onToggle={() => toggleBatchCollapse(group.batch_id)}
              selectedCheckId={selectedCheckId}
            />
          )
        }
        return (
          <HistoryItem
            key={group.item.id}
            item={group.item}
            isSelected={group.item.id === selectedCheckId}
          />
        )
      })}
    </div>
  )
}
