import { useState, useRef, useEffect } from 'react'
import { 
  formatAuthors, 
  exportReferenceAsMarkdown, 
  exportReferenceAsPlainText, 
  exportReferenceAsBibtex,
  copyToClipboard 
} from '../../utils/formatters'

const urlPattern = /https?:\/\/[^\s]+/g

// Parse error_details to extract cited/actual values and format on separate lines
// Handles new format: "Title mismatch:\n       cited:  value\n       actual: value"
const parseErrorDetails = (details) => {
  if (!details) return null
  
  // Split by newlines to handle multiline format
  const lines = details.split('\n')
  
  if (lines.length >= 3) {
    // New three-line format: prefix on first line, cited on second, actual on third
    const prefix = lines[0].replace(/:$/, '').trim() // Remove trailing colon
    
    // Extract value after "cited:" (with any amount of whitespace)
    const citedLine = lines[1]
    const citedMatch = citedLine.match(/cited:\s*(.*)/)
    const cited = citedMatch ? citedMatch[1].trim() : null
    
    // Extract value after "actual:" (with any amount of whitespace)  
    const actualLine = lines[2]
    const actualMatch = actualLine.match(/actual:\s*(.*)/)
    const actual = actualMatch ? actualMatch[1].trim() : null
    
    return { prefix, cited, actual, isMultiline: true }
  }
  
  // Legacy format: "prefix cited: 'value' actual: 'value'" on one line (with quotes)
  const citedMatch = details.match(/cited:\s*'([^']*)'/)
  const actualMatch = details.match(/actual:\s*'([^']*)'/)
  
  // Get the prefix (everything before "cited:" if it exists)
  let prefix = details
  const citedIndex = details.indexOf('cited:')
  if (citedIndex > 0) {
    prefix = details.substring(0, citedIndex).trim()
  } else if (citedIndex === 0) {
    prefix = null
  }
  
  return {
    prefix,
    cited: citedMatch ? citedMatch[1] : null,
    actual: actualMatch ? actualMatch[1] : null,
    isMultiline: false
  }
}

// Render text with clickable URLs, preserving surrounding text
const renderTextWithLinks = (text) => {
  if (!text) return null

  const parts = []
  let lastIndex = 0
  let match

  while ((match = urlPattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    const url = match[0]
    parts.push({ type: 'link', url })
    lastIndex = match.index + url.length
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return parts.map((part, idx) => {
    if (typeof part === 'string') {
      return <span key={`txt-${idx}`}>{part}</span>
    }
    return (
      <a
        key={`url-${idx}`}
        href={part.url}
        target="_blank"
        rel="noopener noreferrer"
        className="hover:underline"
        style={{ color: 'var(--color-link)' }}
      >
        {part.url}
      </a>
    )
  })
}

/**
 * Individual reference card matching CLI output format
 */
export default function ReferenceCard({ reference, index, displayIndex, totalRefs }) {
  // Always use the original index for consistent numbering, even when filtered
  const numberToShow = typeof index === 'number' ? index : (typeof displayIndex === 'number' ? displayIndex : 0)
  const status = (reference.status || '').toLowerCase()
  
  // Export menu state
  const [showExportMenu, setShowExportMenu] = useState(false)
  const exportMenuRef = useRef(null)
  
  // Close export menu on outside click
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(event.target)) {
        setShowExportMenu(false)
      }
    }
    if (showExportMenu) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showExportMenu])
  
  // Handle export for this single reference
  const handleExport = async (format) => {
    let content
    switch (format) {
      case 'markdown':
        content = exportReferenceAsMarkdown(reference)
        break
      case 'plaintext':
        content = exportReferenceAsPlainText(reference)
        break
      case 'bibtex':
        content = exportReferenceAsBibtex(reference)
        break
      default:
        content = exportReferenceAsMarkdown(reference)
    }
    await copyToClipboard(content)
    setShowExportMenu(false)
  }
  
  const getStatusColor = () => {
    switch (status) {
      case 'verified': return 'var(--color-success)'
      case 'warning': return 'var(--color-warning)'
      case 'error': return 'var(--color-error)'
      case 'suggestion': return 'var(--color-suggestion)'
      case 'unverified': return 'var(--color-text-muted)'
      case 'unchecked': return 'var(--color-text-muted)'
      case 'checking': return 'var(--color-accent)'
      case 'pending': return 'var(--color-text-muted)'
      default: return 'var(--color-text-muted)'
    }
  }

  const renderStatusIndicator = () => {
    const commonSize = 'w-7 h-7'

    if (status === 'checking') {
      return (
        <span 
          className="flex-shrink-0 inline-block"
          title="Checking..."
        >
          <svg 
            className={`${commonSize} animate-spin`} 
            viewBox="0 0 24 24" 
            fill="none"
            style={{ color: getStatusColor() }}
          >
            <circle 
              className="opacity-25" 
              cx="12" 
              cy="12" 
              r="10" 
              stroke="currentColor" 
              strokeWidth="3"
            />
            <path 
              className="opacity-75" 
              fill="currentColor" 
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
        </span>
      )
    }
    
    if (status === 'pending') {
      return (
        <span 
          className="flex-shrink-0 inline-block"
          title="Waiting in queue"
        >
          <svg 
            className={commonSize}
            viewBox="0 0 24 24" 
            fill="none"
          >
            <circle cx="12" cy="12" r="10" fill="var(--color-bg-tertiary)" stroke={getStatusColor()} strokeWidth="2" />
            <path d="M12 7v5l3 2" stroke={getStatusColor()} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      )
    }

    if (status === 'error') {
      return (
        <span 
          className="flex-shrink-0 inline-block"
          title="Error"
        >
          <svg 
            className={commonSize}
            viewBox="0 0 24 24" 
            fill="none"
          >
            <circle cx="12" cy="12" r="10" fill="var(--color-error)" />
            <path d="M12 7v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
          </svg>
        </span>
      )
    }

    if (status === 'verified') {
      return (
        <span className="flex-shrink-0 inline-block" title="Verified">
          <svg className={commonSize} viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--color-success)" />
            <path d="M8.5 12.5l2.5 2.5 4.5-5" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      )
    }

    if (status === 'warning') {
      return (
        <span className="flex-shrink-0 inline-block" title="Warning">
          <svg className={commonSize} viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 20h20L12 2z" fill="var(--color-warning)" />
            <path d="M12 9v4" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <circle cx="12" cy="15.5" r="1" fill="#fff" />
          </svg>
        </span>
      )
    }

    if (status === 'suggestion') {
      return (
        <span className="flex-shrink-0 inline-block" title="Suggestion">
          <svg className={commonSize} viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--color-suggestion)" />
            <path d="M12 7v4m0 0l-2-2m2 2l2-2" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
          </svg>
        </span>
      )
    }

    if (status === 'unchecked') {
      return (
        <span className="flex-shrink-0 inline-block" title="Not checked (check cancelled or timed out)">
          <svg className={commonSize} viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--color-text-muted)" />
            <path d="M8 12h8" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </span>
      )
    }

    // unverified/default
    return (
      <span className="flex-shrink-0 inline-block" title="Unverified">
        <svg className={commonSize} viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" fill="var(--color-text-muted)" />
          <path d="M10.75 9.5c.1-1.1.95-2 2.2-2 1.21 0 2.2.89 2.2 1.99 0 .86-.56 1.6-1.4 1.83-.55.15-.95.63-.95 1.2v.23" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="12" cy="16" r="1" fill="#fff" />
        </svg>
      </span>
    )
  }

  // Format URL type for display
  const formatUrlType = (type) => {
    switch (type) {
      case 'semantic_scholar': return 'Verified URL'
      case 'arxiv': return 'ArXiv URL'
      case 'doi': return 'DOI URL'
      case 'openalex': return 'OpenAlex URL'
      case 'openreview': return 'OpenReview URL'
      default: return 'URL'
    }
  }

  const formatWarningType = (type) => {
    switch (type) {
      case 'author': return 'Author'
      case 'year': return 'Year'
      case 'venue': return 'Venue'
      case 'title': return 'Title'
      default: return type?.charAt(0).toUpperCase() + type?.slice(1) || 'Unknown'
    }
  }

  return (
    <div 
      className="py-4 border-b font-mono text-sm"
      style={{ borderColor: 'var(--color-border)' }}
    >
      {/* Reference with status column on left */}
      <div className="flex items-start gap-3 pl-4 pr-8">
        {/* Status indicator column - fixed width */}
        <div className="flex-shrink-0 w-8 flex justify-center pt-0.5">
          {renderStatusIndicator()}
        </div>
        
        {/* Reference number */}
        <span 
          className="flex-shrink-0 w-8 text-right"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {(numberToShow ?? 0) + 1}.
        </span>
        
        {/* Reference content */}
        <div className="flex-1 min-w-0">
          {/* Title row with export button */}
          <div className="flex items-start justify-between gap-2">
            <div 
              className="font-bold flex-1"
              style={{ color: 'var(--color-text-primary)' }}
            >
              {reference.title || reference.cited_url || 'Unknown Title'}
            </div>
            
            {/* Export button */}
            <div className="relative flex-shrink-0" ref={exportMenuRef}>
              <button
                onClick={() => setShowExportMenu(!showExportMenu)}
                className="p-1 rounded opacity-40 hover:opacity-100 transition-opacity cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
                title="Copy corrected reference"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </button>
              
              {/* Export dropdown menu */}
              {showExportMenu && (
                <div 
                  className="absolute right-0 top-full mt-1 py-1 rounded-md shadow-lg z-50 min-w-[140px]"
                  style={{ backgroundColor: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                >
                  <button
                    onClick={() => handleExport('markdown')}
                    className="w-full px-3 py-1.5 text-left text-xs hover:bg-black/10 dark:hover:bg-white/10 cursor-pointer flex items-center gap-2"
                    style={{ color: 'var(--color-text-primary)' }}
                  >
                    <span>📝</span> Markdown
                  </button>
                  <button
                    onClick={() => handleExport('plaintext')}
                    className="w-full px-3 py-1.5 text-left text-xs hover:bg-black/10 dark:hover:bg-white/10 cursor-pointer flex items-center gap-2"
                    style={{ color: 'var(--color-text-primary)' }}
                  >
                    <span>📄</span> Plain Text
                  </button>
                  <button
                    onClick={() => handleExport('bibtex')}
                    className="w-full px-3 py-1.5 text-left text-xs hover:bg-black/10 dark:hover:bg-white/10 cursor-pointer flex items-center gap-2"
                    style={{ color: 'var(--color-text-primary)' }}
                  >
                    <span>📚</span> BibTeX
                  </button>
                </div>
              )}
            </div>
          </div>
          
          {/* Authors */}
          {reference.authors?.length > 0 && (
            <div 
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {formatAuthors(reference.authors)}
            </div>
          )}
          
          {/* Venue */}
          {reference.venue && (
            <div 
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {reference.venue}
            </div>
          )}
          
          {/* Year */}
          {reference.year && (
            <div 
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {reference.year}
            </div>
          )}
          
          {/* Cited URL */}
          {reference.cited_url && (
            <div>
              <a
                href={reference.cited_url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:underline"
                style={{ color: 'var(--color-link)' }}
              >
                {reference.cited_url}
              </a>
            </div>
          )}

          {/* Divider before verification results */}
          {(reference.authoritative_urls?.length > 0 || 
            reference.errors?.length > 0 || 
            reference.warnings?.length > 0 ||
            reference.status === 'unverified') && (
            <div className="my-3 flex items-center gap-3">
              <span className="text-xs uppercase tracking-wide font-medium" style={{ color: 'var(--color-text-muted)' }}>
                Verification
              </span>
              <div className="flex-1 border-t" style={{ borderColor: 'var(--color-border)' }} />
            </div>
          )}

          {/* Authoritative URLs - deduplicate arxiv URLs (prefer abs over pdf) */}
          {(() => {
            const urls = reference.authoritative_urls || []
            // Group by type and deduplicate arxiv
            const seenTypes = new Set()
            const filteredUrls = urls.filter(urlObj => {
              // For arxiv, only show abs URL (skip pdf if we already have abs)
              if (urlObj.type === 'arxiv') {
                if (seenTypes.has('arxiv')) return false
                // Prefer abs URL over pdf
                const hasAbsUrl = urls.some(u => u.type === 'arxiv' && u.url?.includes('/abs/'))
                if (hasAbsUrl && urlObj.url?.includes('/pdf/')) return false
                seenTypes.add('arxiv')
                return true
              }
              // For other types, show all
              return true
            })
            
            return filteredUrls.map((urlObj, i) => (
              <div key={i} className="flex">
                <span 
                  className="flex-shrink-0"
                  style={{ color: 'var(--color-text-secondary)', width: '120px' }}
                >
                  {formatUrlType(urlObj.type)}:
                </span>
                <a
                  href={urlObj.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:underline"
                  style={{ color: 'var(--color-link)' }}
                >
                  {urlObj.url}
                </a>
              </div>
            ))
          })()}

          {/* Unverified message */}
          {reference.status === 'unverified' && (
            <div 
              className="flex items-start gap-2"
              style={{ color: 'var(--color-text-muted)', wordBreak: 'break-word' }}
            >
              <span className="pt-0.5 inline-block flex-shrink-0">
                <svg 
                  className="w-4 h-4"
                  viewBox="0 0 24 24" 
                  fill="currentColor"
                >
                  <circle cx="12" cy="12" r="10" />
                  <text x="12" y="16" textAnchor="middle" fill="#fff" fontSize="14" fontWeight="bold">?</text>
                </svg>
              </span>
              <div>
                <div>Could not verify: {reference.title || 'Unknown'}</div>
                {reference.errors?.find(e => e.error_type === 'unverified') && (
                  <div>
                    Subreason: {renderTextWithLinks(reference.errors.find(e => e.error_type === 'unverified')?.error_details || 'Paper not found by any checker')}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Warnings */}
          {reference.warnings?.map((warning, i) => {
            const parsedDetails = parseErrorDetails(warning.error_details)
            const hasParsedCitedActual = parsedDetails?.cited || parsedDetails?.actual
            
            // Extract version annotation from error_type if present
            const extractVersionAnnotation = (type) => {
              if (!type) return null
              const match = type.match(/\(v\d+\s+vs\s+v\d+\s+update\)/i)
              return match ? match[0] : null
            }
            
            const versionAnnotation = extractVersionAnnotation(warning.error_type)
            
            // Use prefix from error_details and append version annotation if present
            const baseText = (hasParsedCitedActual && parsedDetails?.prefix) 
              ? parsedDetails.prefix?.replace(/:$/, '')
              : (warning.error_details || `${formatWarningType(warning.error_type)} mismatch`)
            
            const warningText = versionAnnotation && !baseText.includes(versionAnnotation)
              ? `${baseText} ${versionAnnotation}`
              : baseText
            
            return (
              <div 
                key={`warning-${i}`}
                style={{ color: 'var(--color-warning)', wordBreak: 'break-word' }}
              >
                <div className="flex items-start gap-2">
                  <span>⚠️</span>
                  <span><span className="font-bold">Warning:</span> {warningText}</span>
                </div>
                {/* Show parsed cited/actual on separate lines, or use direct fields */}
                {(parsedDetails?.cited || warning.cited_value) && (
                  <div className="flex ml-6">
                    <span className="flex-shrink-0" style={{ width: '70px' }}><span className="font-bold">cited:</span></span>
                    <span>{renderTextWithLinks(parsedDetails?.cited || warning.cited_value)}</span>
                  </div>
                )}
                {(parsedDetails?.actual || warning.actual_value) && (
                  <div className="flex ml-6">
                    <span className="flex-shrink-0" style={{ width: '70px' }}><span className="font-bold">actual:</span></span>
                    <span>{renderTextWithLinks(parsedDetails?.actual || warning.actual_value)}</span>
                  </div>
                )}
              </div>
            )
          })}

          {/* Errors (non-unverified) */}
          {reference.errors?.filter(e => e.error_type !== 'unverified').map((error, i) => {
            const parsedDetails = parseErrorDetails(error.error_details)
            const hasParsedCitedActual = parsedDetails?.cited || parsedDetails?.actual
            
            // Extract version annotation from error_type if present (e.g., "title (v3 vs v1 update)" -> "(v3 vs v1 update)")
            const extractVersionAnnotation = (type) => {
              if (!type) return null
              const match = type.match(/\(v\d+\s+vs\s+v\d+\s+update\)/i)
              return match ? match[0] : null
            }
            
            const versionAnnotation = extractVersionAnnotation(error.error_type)
            
            // Use prefix from error_details and append version annotation if present
            const baseText = (hasParsedCitedActual && parsedDetails?.prefix) 
              ? parsedDetails.prefix
              : (error.error_details || error.error_type)
            
            const errorText = versionAnnotation && !baseText.includes(versionAnnotation)
              ? `${baseText} ${versionAnnotation}`
              : baseText
            
            return (
              <div 
                key={`error-${i}`}
                style={{ color: 'var(--color-error)', wordBreak: 'break-word' }}
              >
                <div className="flex items-start gap-2">
                  <span className="pt-0.5 inline-block flex-shrink-0">
                    <svg 
                      className="w-4 h-4"
                      viewBox="0 0 24 24" 
                      fill="currentColor"
                    >
                      <circle cx="12" cy="12" r="10" />
                      <path d="M12 7v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
                      <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
                    </svg>
                  </span>
                  <span>
                    <span className="font-bold">Error:</span> {hasParsedCitedActual ? errorText : renderTextWithLinks(errorText)}
                  </span>
                </div>
                {/* Show parsed cited/actual on separate lines, or use direct fields */}
                {(parsedDetails?.cited || error.cited_value) && (
                  <div className="flex ml-6">
                    <span className="flex-shrink-0" style={{ width: '70px' }}><span className="font-bold">cited:</span></span>
                    <span>{renderTextWithLinks(parsedDetails?.cited || error.cited_value)}</span>
                  </div>
                )}
                {(parsedDetails?.actual || error.actual_value) && (
                  <div className="flex ml-6">
                    <span className="flex-shrink-0" style={{ width: '70px' }}><span className="font-bold">actual:</span></span>
                    <span>{renderTextWithLinks(parsedDetails?.actual || error.actual_value)}</span>
                  </div>
                )}
              </div>
            )
          })}

          {/* Information messages (e.g., missing arXiv URL) - rendered as suggestions */}
          {reference.suggestions?.map((suggestion, i) => (
            <div 
              key={`suggestion-${i}`}
              style={{ color: 'var(--color-suggestion)', wordBreak: 'break-word' }}
            >
              <div className="flex items-start gap-2">
                <span className="pt-0.5 inline-block flex-shrink-0">
                  <svg 
                    className="w-4 h-4"
                    viewBox="0 0 24 24" 
                    fill="currentColor"
                  >
                    <circle cx="12" cy="12" r="10" />
                    <path d="M12 7v4m0 0l-2-2m2 2l2-2" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
                  </svg>
                </span>
                <span><span className="font-bold">Suggestion:</span> {renderTextWithLinks(suggestion.suggestion_details || suggestion)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
