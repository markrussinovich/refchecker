import { useState, useRef, useEffect } from 'react'
import { useCheckStore } from '../../stores/useCheckStore'
import { 
  exportResultsAsMarkdown, 
  exportResultsAsPlainText, 
  exportResultsAsBibtex,
  downloadAsFile 
} from '../../utils/formatters'

/**
 * Stats section showing reference check summary with clickable filters
 * Compact design with refs summary and individual issue counts
 */
export default function StatsSection({ stats, isComplete, references, paperTitle, paperSource }) {
  const { statusFilter, setStatusFilter } = useCheckStore()
  const [showExportMenu, setShowExportMenu] = useState(false)
  const exportMenuRef = useRef(null)

  // Close export menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target)) {
        setShowExportMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // All filter types including verified
  const allFilters = {
    verified: {
      id: 'verified',
      label: 'Verified',
      color: 'var(--color-success)',
      bgColor: 'var(--color-success-bg)',
    },
    error: {
      id: 'error',
      label: 'Errors',
      color: 'var(--color-error)',
      bgColor: 'var(--color-error-bg)',
    },
    warning: {
      id: 'warning',
      label: 'Warnings',
      color: 'var(--color-warning)',
      bgColor: 'var(--color-warning-bg)',
    },
    suggestion: {
      id: 'suggestion',
      label: 'Suggestions',
      color: 'var(--color-suggestion)',
      bgColor: 'var(--color-suggestion-bg)',
    },
    unverified: {
      id: 'unverified',
      label: 'Unverified',
      color: 'var(--color-text-muted)',
      bgColor: 'var(--color-bg-tertiary)',
    },
  }

  // Issue type filters for the chips
  const issueFilters = [
    { ...allFilters.error, value: stats.errors_count || 0 },
    { ...allFilters.warning, value: stats.warnings_count || 0 },
    { ...allFilters.suggestion, value: stats.suggestions_count || 0 },
    { ...allFilters.unverified, value: stats.unverified_count || 0 },
  ]

  const handleFilterClick = (filterId) => {
    setStatusFilter(filterId)
  }

  const isFilterActive = statusFilter.length > 0
  const activeFilterId = isFilterActive ? statusFilter[0] : null
  const activeFilter = activeFilterId ? allFilters[activeFilterId] : null

  // Calculate refs by category - only from processed refs
  const refsWithErrors = stats.refs_with_errors ?? 0
  const refsWithWarningsOnly = stats.refs_with_warnings_only ?? 0
  const refsVerified = stats.refs_verified ?? stats.verified_count ?? 0
  const refsUnverified = stats.unverified_count ?? 0
  const processedRefs = stats.processed_refs ?? 0
  const isVerifiedSelected = statusFilter.includes('verified')
  const isErrorSelected = statusFilter.includes('error')
  const isWarningSelected = statusFilter.includes('warning')
  const isUnverifiedSelected = statusFilter.includes('unverified')

  // Base filename for exports
  const baseFilename = `refchecker-${(paperTitle || 'report').replace(/[^a-z0-9]/gi, '_').substring(0, 50)}`

  // Export handlers
  const handleExport = (format) => {
    setShowExportMenu(false)
    const exportData = { paperTitle, paperSource, stats, references }
    
    switch (format) {
      case 'markdown':
        downloadAsFile(exportResultsAsMarkdown(exportData), `${baseFilename}.md`, 'text/markdown')
        break
      case 'text':
        downloadAsFile(exportResultsAsPlainText(exportData), `${baseFilename}.txt`, 'text/plain')
        break
      case 'bibtex':
        downloadAsFile(exportResultsAsBibtex(exportData), `${baseFilename}.bib`, 'application/x-bibtex')
        break
    }
  }

  return (
    <div 
      className="rounded-lg border p-3"
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)',
      }}
    >
      {/* Header row - fixed height with relative positioning for absolute child */}
      <div className="flex items-center justify-between mb-3 relative" style={{ height: '24px' }}>
        <div className="flex items-center gap-3">
          <h3 
            className="font-semibold text-sm"
            style={{ color: 'var(--color-text-primary)' }}
          >
            Summary
          </h3>
          {!isComplete && stats.processed_refs > 0 && stats.processed_refs < stats.total_refs && (
            <span 
              className="text-xs"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {stats.processed_refs}/{stats.total_refs} checked
            </span>
          )}
        </div>
        {/* Right side controls */}
        <div className="absolute right-0 top-0 flex items-center gap-2">
          {/* Filter indicator */}
          {isFilterActive && activeFilter && (
            <button
              onClick={() => handleFilterClick(activeFilterId)}
              className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium transition-opacity hover:opacity-80"
              style={{ 
                backgroundColor: activeFilter.bgColor,
                color: activeFilter.color,
              }}
            >
              <span>Showing {activeFilter.label.toLowerCase()}</span>
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
          {/* Export dropdown - only enabled when check is complete */}
          <div className="relative" ref={exportMenuRef}>
            <button
              onClick={() => isComplete && setShowExportMenu(!showExportMenu)}
              disabled={!isComplete}
              className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium transition-all ${
                isComplete 
                  ? 'cursor-pointer hover:opacity-80' 
                  : 'cursor-not-allowed opacity-40'
              }`}
              style={{ 
                backgroundColor: isComplete ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                color: isComplete ? 'white' : 'var(--color-text-muted)',
              }}
              title={isComplete ? 'Export results' : 'Export available when check completes'}
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" strokeLinecap="round" strokeLinejoin="round" />
                <polyline points="7,10 12,15 17,10" strokeLinecap="round" strokeLinejoin="round" />
                <line x1="12" y1="15" x2="12" y2="3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>Export</span>
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            {showExportMenu && (
              <div 
                className="absolute right-0 top-full mt-1 py-1 rounded-lg border shadow-lg z-50"
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  borderColor: 'var(--color-border)',
                  minWidth: '140px',
                }}
              >
                <button
                  onClick={() => handleExport('markdown')}
                  className="w-full px-3 py-1.5 text-xs text-left transition-colors cursor-pointer hover:bg-[var(--color-bg-tertiary)]"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  📝 Markdown (.md)
                </button>
                <button
                  onClick={() => handleExport('text')}
                  className="w-full px-3 py-1.5 text-xs text-left transition-colors cursor-pointer hover:bg-[var(--color-bg-tertiary)]"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  📄 Plain Text (.txt)
                </button>
                <button
                  onClick={() => handleExport('bibtex')}
                  className="w-full px-3 py-1.5 text-xs text-left transition-colors cursor-pointer hover:bg-[var(--color-bg-tertiary)]"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  📚 BibTeX (.bib)
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Main stats row - single compact row */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Verified */}
        <button
          onClick={() => handleFilterClick('verified')}
          className={`flex items-center gap-1 px-2 py-1 rounded transition-all cursor-pointer hover:opacity-80 ${
            isVerifiedSelected ? 'ring-1' : ''
          }`}
          style={{ 
            backgroundColor: isVerifiedSelected ? 'var(--color-success-bg)' : 'transparent',
            ringColor: 'var(--color-success)',
          }}
          title={`${refsVerified} reference${refsVerified === 1 ? '' : 's'} fully verified`}
        >
          <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--color-success)" />
            <path d="M8.5 12.5l2.5 2.5 4.5-5" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="text-sm font-bold" style={{ color: 'var(--color-success)' }}>{refsVerified}</span>
        </button>

        {/* Errors */}
        <button
          onClick={() => handleFilterClick('error')}
          disabled={refsWithErrors === 0}
          className={`flex items-center gap-1 px-2 py-1 rounded transition-all ${
            refsWithErrors > 0 ? 'cursor-pointer hover:opacity-80' : 'cursor-default opacity-50'
          } ${isErrorSelected ? 'ring-1' : ''}`}
          style={{ 
            backgroundColor: isErrorSelected ? 'var(--color-error-bg)' : 'transparent',
            ringColor: 'var(--color-error)',
          }}
          title={refsWithErrors > 0 ? `${refsWithErrors} reference${refsWithErrors === 1 ? '' : 's'} with errors` : 'No references with errors'}
        >
          <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--color-error)" />
            <path d="M12 7v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
          </svg>
          <span className="text-sm font-bold" style={{ color: refsWithErrors > 0 ? 'var(--color-error)' : 'var(--color-text-muted)' }}>{refsWithErrors}</span>
        </button>

        {/* Warnings */}
        <button
          onClick={() => handleFilterClick('warning')}
          disabled={refsWithWarningsOnly === 0}
          className={`flex items-center gap-1 px-2 py-1 rounded transition-all ${
            refsWithWarningsOnly > 0 ? 'cursor-pointer hover:opacity-80' : 'cursor-default opacity-50'
          } ${isWarningSelected ? 'ring-1' : ''}`}
          style={{ 
            backgroundColor: isWarningSelected ? 'var(--color-warning-bg)' : 'transparent',
            ringColor: 'var(--color-warning)',
          }}
          title={refsWithWarningsOnly > 0 ? `${refsWithWarningsOnly} reference${refsWithWarningsOnly === 1 ? '' : 's'} with warnings only` : 'No references with warnings only'}
        >
          <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 20h20L12 2z" fill="var(--color-warning)" />
            <path d="M12 9v4" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <circle cx="12" cy="15.5" r="1" fill="#fff" />
          </svg>
          <span className="text-sm font-bold" style={{ color: refsWithWarningsOnly > 0 ? 'var(--color-warning)' : 'var(--color-text-muted)' }}>{refsWithWarningsOnly}</span>
        </button>

        {/* Unverified - only show if > 0 */}
        {refsUnverified > 0 && (
          <button
            onClick={() => handleFilterClick('unverified')}
            className={`flex items-center gap-1 px-2 py-1 rounded transition-all cursor-pointer hover:opacity-80 ${
              isUnverifiedSelected ? 'ring-1' : ''
            }`}
            style={{ 
              backgroundColor: isUnverifiedSelected ? 'var(--color-bg-tertiary)' : 'transparent',
              ringColor: 'var(--color-text-muted)',
            }}
            title={`${refsUnverified} reference${refsUnverified === 1 ? '' : 's'} could not be verified`}
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" fill="var(--color-text-muted)" />
              <text x="12" y="16" textAnchor="middle" fill="#fff" fontSize="12" fontWeight="bold">?</text>
            </svg>
            <span className="text-sm font-bold" style={{ color: 'var(--color-text-muted)' }}>{refsUnverified}</span>
          </button>
        )}

        {/* Separator and total */}
        <span className="text-xs px-1" style={{ color: 'var(--color-text-muted)' }}>of {processedRefs}</span>

        {/* Divider */}
        <div className="w-px h-4 mx-1" style={{ backgroundColor: 'var(--color-border)' }} />

        {/* Issue counts as compact chips */}
        {issueFilters.filter(f => f.value > 0).map(filter => {
          const isSelected = statusFilter.includes(filter.id)
          return (
            <button
              key={filter.id}
              onClick={() => handleFilterClick(filter.id)}
              className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs transition-all cursor-pointer hover:opacity-80 border"
              style={{ 
                backgroundColor: isSelected ? filter.bgColor : 'transparent',
                borderColor: isSelected ? filter.color : 'var(--color-border)',
                color: filter.color,
              }}
              title={`${filter.value} ${filter.label.toLowerCase()} (total issues)`}
            >
              <span className="font-bold">{filter.value}</span>
              <span>{filter.label}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
