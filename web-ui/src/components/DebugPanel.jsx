import { useEffect, useRef, useState } from 'react'
import { useDebugStore } from '../stores/useDebugStore'
import { clearCache, clearDatabase } from '../utils/api'

/**
 * Debug log panel that shows real-time logs
 */
export default function DebugPanel() {
  const { logs, isEnabled, isVisible, filter, toggleEnabled, toggleVisible, setFilter, clearLogs } = useDebugStore()
  const [clearing, setClearing] = useState(null)
  const logsEndRef = useRef(null)

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (isVisible && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, isVisible])

  const filteredLogs = logs.filter(log => {
    if (filter === 'all') return true
    return log.level.toLowerCase() === filter
  })

  const getLevelColor = (level) => {
    switch (level) {
      case 'ERROR': return '#ef4444'
      case 'WARN': return '#f59e0b'
      case 'INFO': return '#3b82f6'
      case 'DEBUG': return '#6b7280'
      default: return '#9ca3af'
    }
  }

  const getLevelBg = (level) => {
    switch (level) {
      case 'ERROR': return 'rgba(239, 68, 68, 0.1)'
      case 'WARN': return 'rgba(245, 158, 11, 0.1)'
      case 'INFO': return 'rgba(59, 130, 246, 0.1)'
      default: return 'transparent'
    }
  }

  const handleClearCache = async () => {
    if (!confirm('Clear all cached verification results?')) return
    setClearing('cache')
    try {
      const response = await clearCache()
      alert(response.data.message)
    } catch (err) {
      alert('Failed to clear cache: ' + (err.response?.data?.detail || err.message))
    } finally {
      setClearing(null)
    }
  }

  const handleClearDatabase = async () => {
    if (!confirm('Clear all data (cache + history)? This cannot be undone.')) return
    setClearing('database')
    try {
      const response = await clearDatabase()
      alert(response.data.message)
      // Reload to refresh history panel
      window.location.reload()
    } catch (err) {
      alert('Failed to clear database: ' + (err.response?.data?.detail || err.message))
    } finally {
      setClearing(null)
    }
  }

  // Debug toggle button (always visible)
  const toggleButton = (
    <button
      onClick={toggleVisible}
      className="fixed bottom-4 right-4 z-50 p-2 rounded-full shadow-lg transition-all"
      style={{
        backgroundColor: isEnabled ? (isVisible ? '#3b82f6' : '#1f2937') : '#374151',
        color: isEnabled ? 'white' : '#9ca3af',
      }}
      title={isVisible ? 'Hide Debug Panel' : 'Show Debug Panel'}
    >
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
      </svg>
    </button>
  )

  if (!isVisible) {
    return toggleButton
  }

  return (
    <>
      {toggleButton}
      <div
        className="fixed bottom-16 right-4 z-40 w-[600px] max-w-[90vw] rounded-lg shadow-xl border overflow-hidden"
        style={{
          backgroundColor: '#1f2937',
          borderColor: '#374151',
          maxHeight: '50vh',
        }}
      >
        {/* Header */}
        <div 
          className="flex items-center justify-between px-4 py-2 border-b"
          style={{ borderColor: '#374151', backgroundColor: '#111827' }}
        >
          <div className="flex items-center gap-3">
            <span className="text-white font-medium text-sm">Debug Logs</span>
            <span 
              className="text-xs px-2 py-0.5 rounded"
              style={{ backgroundColor: '#374151', color: '#9ca3af' }}
            >
              {filteredLogs.length} entries
            </span>
          </div>
          <div className="flex items-center gap-2">
            {/* Clear Cache button */}
            <button
              onClick={handleClearCache}
              disabled={clearing !== null}
              className="text-xs px-2 py-1 rounded"
              style={{ backgroundColor: '#374151', color: '#9ca3af' }}
              title="Clear verification cache"
            >
              {clearing === 'cache' ? '...' : 'Clear Cache'}
            </button>

            {/* Clear All button */}
            <button
              onClick={handleClearDatabase}
              disabled={clearing !== null}
              className="text-xs px-2 py-1 rounded"
              style={{ backgroundColor: '#7f1d1d', color: '#fca5a5' }}
              title="Clear all data (cache + history)"
            >
              {clearing === 'database' ? '...' : 'Clear All'}
            </button>

            <div className="w-px h-4 bg-gray-600" />

            {/* Filter dropdown */}
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="text-xs px-2 py-1 rounded border-0"
              style={{ backgroundColor: '#374151', color: '#e5e7eb' }}
            >
              <option value="all">All</option>
              <option value="error">Errors</option>
              <option value="warn">Warnings</option>
              <option value="info">Info</option>
              <option value="debug">Debug</option>
            </select>
            
            {/* Enable/Disable toggle */}
            <button
              onClick={toggleEnabled}
              className="text-xs px-2 py-1 rounded"
              style={{
                backgroundColor: isEnabled ? '#059669' : '#374151',
                color: isEnabled ? 'white' : '#9ca3af',
              }}
            >
              {isEnabled ? 'ON' : 'OFF'}
            </button>

            {/* Clear logs button */}
            <button
              onClick={clearLogs}
              className="text-xs px-2 py-1 rounded"
              style={{ backgroundColor: '#374151', color: '#9ca3af' }}
            >
              Clear Logs
            </button>

            {/* Close button */}
            <button
              onClick={toggleVisible}
              className="text-gray-400 hover:text-white"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Logs */}
        <div 
          className="overflow-y-auto font-mono text-xs"
          style={{ maxHeight: 'calc(50vh - 44px)' }}
        >
          {!isEnabled ? (
            <div className="p-4 text-center text-gray-500">
              Debug logging is disabled. Click "ON" to enable.
            </div>
          ) : filteredLogs.length === 0 ? (
            <div className="p-4 text-center text-gray-500">
              No logs yet. Start a check to see logs.
            </div>
          ) : (
            filteredLogs.map(log => (
              <div
                key={log.id}
                className="px-3 py-1.5 border-b hover:bg-gray-800"
                style={{ 
                  borderColor: '#374151',
                  backgroundColor: getLevelBg(log.level),
                }}
              >
                <div className="flex items-start gap-2">
                  <span className="text-gray-500 shrink-0">
                    {log.timestamp.split('T')[1].split('.')[0]}
                  </span>
                  <span 
                    className="font-bold shrink-0 w-12"
                    style={{ color: getLevelColor(log.level) }}
                  >
                    {log.level}
                  </span>
                  <span className="text-purple-400 shrink-0">
                    [{log.component}]
                  </span>
                  <span className="text-gray-200 break-all">
                    {log.message}
                  </span>
                </div>
                {log.data && (
                  <pre 
                    className="mt-1 ml-24 text-gray-400 whitespace-pre-wrap break-all"
                    style={{ fontSize: '10px' }}
                  >
                    {log.data}
                  </pre>
                )}
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      </div>
    </>
  )
}
