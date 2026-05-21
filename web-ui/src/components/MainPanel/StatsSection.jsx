import { useState, useRef, useEffect, useMemo } from 'react'
import { useCheckStore } from '../../stores/useCheckStore'
import { 
  exportResultsAsMarkdown,
  exportResultsAsPlainText,
  exportResultsAsBibtex,
  exportResultsAsJsonl,
  exportResultsAsCsv,
  exportResultsAsRIS,
  sortReferencesForExport,
  REFERENCE_SORT_MODES,
  downloadAsFile
} from '../../utils/formatters'
import { buildReferenceSummary } from '../../utils/referenceStatus'

/**
 * Stats section showing reference check summary with clickable filters
 * Compact design with refs summary and individual issue counts
 */
export default function StatsSection({ stats, isComplete, references, paperTitle, paperSource, healthBadge, usageChip }) {
  const statusFilter = useCheckStore(s => s.statusFilter)
  const setStatusFilter = useCheckStore(s => s.setStatusFilter)
  const [showExportMenu, setShowExportMenu] = useState(false)
  const [sortMode, setSortMode] = useState('citation')
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
    hallucination: {
      id: 'hallucination',
      label: 'Hallucinated',
      color: 'var(--color-hallucination)',
      bgColor: 'var(--color-hallucination-bg)',
    },
  }

  const handleFilterClick = (filterId) => {
    setStatusFilter(filterId)
  }

  const isFilterActive = statusFilter.length > 0
  const activeFilterId = isFilterActive ? statusFilter[0] : null
  const activeFilter = activeFilterId ? allFilters[activeFilterId] : null

  const summaryCounts = useMemo(
    () => buildReferenceSummary({ stats, references, isComplete }),
    [stats, references, isComplete]
  )

  const refsWithErrors = summaryCounts.references.errors
  const refsWithWarningsOnly = summaryCounts.references.warnings
  const refsWithSuggestionsOnly = summaryCounts.references.suggestions
  const refsVerified = summaryCounts.references.verified
  const refsUnverified = summaryCounts.references.unverified
  const refsHallucinated = summaryCounts.references.hallucinated
  const processedRefs = summaryCounts.processedRefs
  const totalRefs = summaryCounts.totalRefs

  const issueFilters = [
    { ...allFilters.error, value: summaryCounts.issues.errors },
    { ...allFilters.warning, value: summaryCounts.issues.warnings },
    { ...allFilters.suggestion, value: summaryCounts.issues.suggestions },
    { ...allFilters.unverified, value: refsUnverified },
    { ...allFilters.hallucination, value: refsHallucinated },
  ]
  const isVerifiedSelected = statusFilter.includes('verified')
  const isErrorSelected = statusFilter.includes('error')
  const isWarningSelected = statusFilter.includes('warning')
  const isSuggestionSelected = statusFilter.includes('suggestion')
  const isUnverifiedSelected = statusFilter.includes('unverified')
  const isHallucinationSelected = statusFilter.includes('hallucination')

  // Base filename for exports
  const baseFilename = `refchecker-${(paperTitle || 'report').replace(/[^a-z0-9]/gi, '_').substring(0, 50)}`

  // Export handlers
  const handleExport = (format) => {
    setShowExportMenu(false)
    const sortedRefs = sortReferencesForExport(references, sortMode)
    const exportData = { paperTitle, paperSource, stats, references: sortedRefs }

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
      case 'ris':
        // RIS imports directly into Zotero / Mendeley / EndNote / Rayyan / Papers.
        downloadAsFile(exportResultsAsRIS(exportData), `${baseFilename}.ris`, 'application/x-research-info-systems')
        break
      case 'jsonl':
        downloadAsFile(exportResultsAsJsonl(exportData), `${baseFilename}.jsonl`, 'application/x-ndjson')
        break
      case 'csv':
        downloadAsFile(exportResultsAsCsv(exportData), `${baseFilename}.csv`, 'text/csv')
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
      {/* Header row */}
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <h3
            className="font-semibold text-sm"
            style={{ color: 'var(--color-text-primary)' }}
          >
            Summary
          </h3>
          {!isComplete && processedRefs > 0 && processedRefs < totalRefs && (
            <span
              className="text-xs"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {processedRefs}/{totalRefs} checked
            </span>
          )}
          {healthBadge}
          {usageChip}
        </div>
        {/* Right side controls */}
        <div className="flex items-center gap-2">
          {/* Filter indicator — single 'Clear filters' chip whenever any
              of the multi-select Summary chips is active. */}
          {isFilterActive && (
            <button
              onClick={() => useCheckStore.getState().clearStatusFilter()}
              className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium transition-opacity hover:opacity-80"
              style={{
                backgroundColor: 'var(--color-bg-tertiary)',
                color: 'var(--color-text-primary)',
                border: '1px solid var(--color-border)',
              }}
              title="Clear all active filters"
            >
              <span>
                Filtered: {statusFilter.join(', ')}
              </span>
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
                  minWidth: '220px',
                }}
              >
                <div className="px-3 py-1 border-b" style={{ borderColor: 'var(--color-border)' }}>
                  <div className="text-[10px] uppercase tracking-wide mb-1" style={{ color: 'var(--color-text-muted)' }}>
                    Sort
                  </div>
                  <select
                    value={sortMode}
                    onChange={(e) => setSortMode(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    className="w-full px-2 py-1 rounded text-xs border"
                    style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                  >
                    {REFERENCE_SORT_MODES.map(m => (
                      <option key={m.id} value={m.id}>{m.label}</option>
                    ))}
                  </select>
                </div>
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
                <button
                  onClick={() => handleExport('ris')}
                  className="w-full px-3 py-1.5 text-xs text-left transition-colors cursor-pointer hover:bg-[var(--color-bg-tertiary)]"
                  style={{ color: 'var(--color-text-primary)' }}
                  title="Imports directly into Zotero, EndNote, Mendeley, Rayyan, Papers, RefWorks"
                >
                  🔖 RIS (.ris) — Zotero / EndNote / Rayyan
                </button>
                <button
                  onClick={() => handleExport('jsonl')}
                  className="w-full px-3 py-1.5 text-xs text-left transition-colors cursor-pointer hover:bg-[var(--color-bg-tertiary)]"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  🧾 JSONL (.jsonl)
                </button>
                <button
                  onClick={() => handleExport('csv')}
                  className="w-full px-3 py-1.5 text-xs text-left transition-colors cursor-pointer hover:bg-[var(--color-bg-tertiary)]"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  📊 CSV (.csv)
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Reference counts row */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>References</span>
        {/* Verified */}
        <button
          onClick={() => handleFilterClick('verified')}
          className={`flex items-center gap-1 px-2 py-1 rounded transition-all cursor-pointer hover:scale-105 hover:shadow-sm ${
            isVerifiedSelected ? 'ring-1 shadow-sm' : ''
          }`}
          style={{ 
            backgroundColor: isVerifiedSelected ? 'var(--color-success-bg)' : 'transparent',
            ringColor: 'var(--color-success)',
          }}
          onMouseEnter={(e) => {
            if (!isVerifiedSelected) {
              e.currentTarget.style.backgroundColor = 'var(--color-success-bg)'
            }
          }}
          onMouseLeave={(e) => {
            if (!isVerifiedSelected) {
              e.currentTarget.style.backgroundColor = 'transparent'
            }
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
            refsWithErrors > 0 ? 'cursor-pointer hover:scale-105 hover:shadow-sm' : 'cursor-default opacity-50'
          } ${isErrorSelected ? 'ring-1 shadow-sm' : ''}`}
          style={{ 
            backgroundColor: isErrorSelected ? 'var(--color-error-bg)' : 'transparent',
            ringColor: 'var(--color-error)',
          }}
          onMouseEnter={(e) => {
            if (refsWithErrors > 0 && !isErrorSelected) {
              e.currentTarget.style.backgroundColor = 'var(--color-error-bg)'
            }
          }}
          onMouseLeave={(e) => {
            if (refsWithErrors > 0 && !isErrorSelected) {
              e.currentTarget.style.backgroundColor = 'transparent'
            }
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
            refsWithWarningsOnly > 0 ? 'cursor-pointer hover:scale-105 hover:shadow-sm' : 'cursor-default opacity-50'
          } ${isWarningSelected ? 'ring-1 shadow-sm' : ''}`}
          style={{ 
            backgroundColor: isWarningSelected ? 'var(--color-warning-bg)' : 'transparent',
            ringColor: 'var(--color-warning)',
          }}
          onMouseEnter={(e) => {
            if (refsWithWarningsOnly > 0 && !isWarningSelected) {
              e.currentTarget.style.backgroundColor = 'var(--color-warning-bg)'
            }
          }}
          onMouseLeave={(e) => {
            if (refsWithWarningsOnly > 0 && !isWarningSelected) {
              e.currentTarget.style.backgroundColor = 'transparent'
            }
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

        {/* Suggestions */}
        {refsWithSuggestionsOnly > 0 && (
          <button
            onClick={() => handleFilterClick('suggestion')}
            className={`flex items-center gap-1 px-2 py-1 rounded transition-all cursor-pointer hover:scale-105 hover:shadow-sm ${
              isSuggestionSelected ? 'ring-1 shadow-sm' : ''
            }`}
            style={{
              backgroundColor: isSuggestionSelected ? 'var(--color-suggestion-bg)' : 'transparent',
              ringColor: 'var(--color-suggestion)',
            }}
            onMouseEnter={(e) => {
              if (!isSuggestionSelected) {
                e.currentTarget.style.backgroundColor = 'var(--color-suggestion-bg)'
              }
            }}
            onMouseLeave={(e) => {
              if (!isSuggestionSelected) {
                e.currentTarget.style.backgroundColor = 'transparent'
              }
            }}
            title={`${refsWithSuggestionsOnly} reference${refsWithSuggestionsOnly === 1 ? '' : 's'} with suggestions only`}
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" style={{ color: 'var(--color-suggestion)' }}>
              <path d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.34.208-.646.477-.859a4 4 0 10-4.954 0c.27.213.462.519.476.859h4.002z" />
            </svg>
            <span className="text-sm font-bold" style={{ color: 'var(--color-suggestion)' }}>{refsWithSuggestionsOnly}</span>
          </button>
        )}

        {/* Unverified - only show if > 0 */}
        {refsUnverified > 0 && (
          <button
            onClick={() => handleFilterClick('unverified')}
            className={`flex items-center gap-1 px-2 py-1 rounded transition-all cursor-pointer hover:scale-105 hover:shadow-sm ${
              isUnverifiedSelected ? 'ring-1 shadow-sm' : ''
            }`}
            style={{ 
              backgroundColor: isUnverifiedSelected ? 'var(--color-bg-tertiary)' : 'transparent',
              ringColor: 'var(--color-text-muted)',
            }}
            onMouseEnter={(e) => {
              if (!isUnverifiedSelected) {
                e.currentTarget.style.backgroundColor = 'var(--color-bg-tertiary)'
              }
            }}
            onMouseLeave={(e) => {
              if (!isUnverifiedSelected) {
                e.currentTarget.style.backgroundColor = 'transparent'
              }
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

        {/* Hallucinated - only show if > 0 */}
        {refsHallucinated > 0 && (
          <button
            onClick={() => handleFilterClick('hallucination')}
            className={`flex items-center gap-1 px-2 py-1 rounded transition-all cursor-pointer hover:scale-105 hover:shadow-sm ${
              isHallucinationSelected ? 'ring-1 shadow-sm' : ''
            }`}
            style={{ 
              backgroundColor: isHallucinationSelected ? 'var(--color-hallucination-bg)' : 'transparent',
              ringColor: 'var(--color-hallucination)',
            }}
            onMouseEnter={(e) => {
              if (!isHallucinationSelected) {
                e.currentTarget.style.backgroundColor = 'var(--color-hallucination-bg)'
              }
            }}
            onMouseLeave={(e) => {
              if (!isHallucinationSelected) {
                e.currentTarget.style.backgroundColor = 'transparent'
              }
            }}
            title={`${refsHallucinated} reference${refsHallucinated === 1 ? '' : 's'} likely hallucinated`}
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" fill="var(--color-hallucination)" />
              <path d="M12 4v10M10 6l2-2 2 2" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="12" cy="17.5" r="1.2" fill="#fff" />
            </svg>
            <span className="text-sm font-bold" style={{ color: 'var(--color-hallucination)' }}>{refsHallucinated}</span>
          </button>
        )}

        {/* Separator and total */}
        <span className="text-xs px-1" style={{ color: 'var(--color-text-muted)' }}>of {processedRefs}</span>
      </div>

      {/* Issue counts row - separate line */}
      {issueFilters.some(f => f.value > 0) && (
        <div className="flex items-center gap-2 flex-wrap mt-2">
          <span className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>Issues</span>
          {issueFilters.filter(f => f.value > 0).map(filter => {
            const isSelected = statusFilter.includes(filter.id)
            return (
              <button
                key={filter.id}
                onClick={() => handleFilterClick(filter.id)}
                className={`group flex items-center gap-1 px-2 py-0.5 rounded-full text-xs transition-all cursor-pointer border hover:scale-105 hover:shadow-sm ${
                  isSelected ? 'ring-1 shadow-sm' : ''
                }`}
                style={{ 
                  backgroundColor: isSelected ? filter.bgColor : 'transparent',
                  borderColor: isSelected ? filter.color : 'var(--color-border)',
                  color: filter.color,
                  '--hover-bg': filter.bgColor,
                  '--hover-border': filter.color,
                  ringColor: isSelected ? filter.color : undefined,
                }}
                onMouseEnter={(e) => {
                  if (!isSelected) {
                    e.currentTarget.style.backgroundColor = filter.bgColor
                    e.currentTarget.style.borderColor = filter.color
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) {
                    e.currentTarget.style.backgroundColor = 'transparent'
                    e.currentTarget.style.borderColor = 'var(--color-border)'
                  }
                }}
                title={`${filter.value} ${filter.label.toLowerCase()} (total issues)`}
              >
                <span className="font-bold">{filter.value}</span>
                <span>{filter.label}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
