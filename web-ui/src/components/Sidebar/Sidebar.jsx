import { useEffect, useState, useRef, useCallback } from 'react'
import LLMSelector from './LLMSelector'
import SemanticScholarConfig from './SemanticScholarConfig'
import HistoryList from './HistoryList'
import { useConfigStore } from '../../stores/useConfigStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { logger } from '../../utils/logger'

const MIN_WIDTH = 220
const MAX_WIDTH = 500
const DEFAULT_WIDTH = 280
const STORAGE_KEY = 'refchecker-sidebar-width'

/**
 * Sidebar component containing LLM selector and history list
 */
export default function Sidebar() {
  const { fetchConfigs } = useConfigStore()
  const { fetchHistory } = useHistoryStore()
  const [width, setWidth] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, parseInt(saved, 10))) : DEFAULT_WIDTH
  })
  const [isResizing, setIsResizing] = useState(false)
  const sidebarRef = useRef(null)

  useEffect(() => {
    logger.info('Sidebar', 'Initializing sidebar data')
    fetchConfigs()
    fetchHistory()
  }, [fetchConfigs, fetchHistory])

  // Save width to localStorage when it changes
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, width.toString())
  }, [width])

  const startResizing = useCallback((e) => {
    e.preventDefault()
    setIsResizing(true)
  }, [])

  const stopResizing = useCallback(() => {
    setIsResizing(false)
  }, [])

  const resize = useCallback((e) => {
    if (isResizing && sidebarRef.current) {
      const newWidth = e.clientX - sidebarRef.current.getBoundingClientRect().left
      if (newWidth >= MIN_WIDTH && newWidth <= MAX_WIDTH) {
        setWidth(newWidth)
      }
    }
  }, [isResizing])

  useEffect(() => {
    if (isResizing) {
      window.addEventListener('mousemove', resize)
      window.addEventListener('mouseup', stopResizing)
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    }

    return () => {
      window.removeEventListener('mousemove', resize)
      window.removeEventListener('mouseup', stopResizing)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [isResizing, resize, stopResizing])

  return (
    <aside 
      ref={sidebarRef}
      className="flex flex-col h-full relative"
      style={{ 
        width: `${width}px`,
        minWidth: `${MIN_WIDTH}px`,
        maxWidth: `${MAX_WIDTH}px`,
        backgroundColor: 'var(--color-bg-secondary)',
      }}
    >
      {/* LLM Configuration Section */}
      <div 
        className="p-4 border-b"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <h2 
          className="text-sm font-semibold mb-3 uppercase tracking-wide"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          LLM Configuration
        </h2>
        <LLMSelector />
      </div>

      {/* Semantic Scholar Configuration Section */}
      <div 
        className="p-4 border-b"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <SemanticScholarConfig />
      </div>

      {/* History Section */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div 
          className="px-4 py-3 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <h2 
            className="text-sm font-semibold uppercase tracking-wide"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            History
          </h2>
        </div>
        <HistoryList />
      </div>

      {/* Resize handle */}
      <div
        onMouseDown={startResizing}
        className="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-blue-500 transition-colors"
        style={{
          backgroundColor: isResizing ? 'var(--color-accent)' : 'var(--color-border)',
        }}
      />
    </aside>
  )
}
