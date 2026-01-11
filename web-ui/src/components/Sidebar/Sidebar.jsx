import { useEffect, useState, useRef, useCallback } from 'react'
import LLMSelector from './LLMSelector'
import SemanticScholarConfig from './SemanticScholarConfig'
import HistoryList from './HistoryList'
import { useConfigStore } from '../../stores/useConfigStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useCheckStore } from '../../stores/useCheckStore'
import { useSettingsStore } from '../../stores/useSettingsStore'
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
  const { initializeWithPlaceholder, ensureNewRefcheckItem, selectCheck } = useHistoryStore()
  const { status, reset } = useCheckStore()
  const { toggleSettings } = useSettingsStore()
  const [width, setWidth] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, parseInt(saved, 10))) : DEFAULT_WIDTH
  })
  const [isResizing, setIsResizing] = useState(false)
  const sidebarRef = useRef(null)

  useEffect(() => {
    logger.info('Sidebar', 'Initializing sidebar data')
    fetchConfigs()
    // Use initializeWithPlaceholder for startup - adds placeholder and selects it
    initializeWithPlaceholder()
  }, [fetchConfigs, initializeWithPlaceholder])

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
      {/* New version badge */}
      <div 
        className="px-4 py-2 border-b flex items-center justify-between"
        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)' }}
      >
        <span 
          className="text-xs font-semibold uppercase tracking-wide"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          New refcheck
        </span>
        <button
          onClick={() => {
            ensureNewRefcheckItem()
            // Only reset if not currently checking - don't interrupt running checks
            if (status !== 'checking') {
              reset()
            }
            selectCheck(-1)
          }}
          className="text-[11px] px-3 py-1 rounded-full font-medium transition-colors flex items-center gap-1 cursor-pointer hover:opacity-80"
          style={{ backgroundColor: 'var(--color-accent)', color: '#ffffff' }}
          title="Create new refcheck"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="w-3.5 h-3.5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
        </button>
      </div>

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

      {/* Settings button */}
      <div 
        className="px-4 py-3 border-t"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <button
          onClick={toggleSettings}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm transition-colors cursor-pointer hover:opacity-80"
          style={{ 
            color: 'var(--color-text-secondary)',
            backgroundColor: 'var(--color-bg-tertiary)'
          }}
          title="Settings"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
            />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <span>Settings</span>
        </button>
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
