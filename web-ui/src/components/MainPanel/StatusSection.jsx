import { useState, useEffect } from 'react'
import { useCheckStore } from '../../stores/useCheckStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import * as api from '../../utils/api'
import { logger } from '../../utils/logger'

// API base URL for thumbnails - use empty string to use relative URLs via Vite proxy
const API_BASE = ''

/**
 * Extract ArXiv ID from a URL or source string
 */
function extractArxivId(source) {
  if (!source) return null
  
  // Match ArXiv ID pattern (e.g., 2311.12022, 2311.12022v1)
  const arxivIdPattern = /(\d{4}\.\d{4,5})(v\d+)?/
  
  // Check if source is a direct ArXiv ID
  if (arxivIdPattern.test(source)) {
    const match = source.match(arxivIdPattern)
    return match ? match[1] : null
  }
  
  // Check if source is an ArXiv URL
  if (source.includes('arxiv.org')) {
    const match = source.match(arxivIdPattern)
    return match ? match[1] : null
  }
  
  return null
}

/**
 * Get thumbnail info based on source type
 * Returns { type: 'arxiv' | 'pdf' | 'text' | 'file', url?: string, arxivId?: string }
 */
function getThumbnailInfo(source, sourceType) {
  if (!source) return { type: 'unknown' }
  
  // Check for ArXiv source
  const arxivId = extractArxivId(source)
  if (arxivId) {
    // ArXiv provides thumbnails via their API
    return { 
      type: 'arxiv', 
      arxivId,
      // Use ArXiv's abstract page thumbnail (first page preview)
      thumbnailUrl: `https://arxiv.org/abs/${arxivId}`,
      pdfUrl: `https://arxiv.org/pdf/${arxivId}.pdf`
    }
  }
  
  // Check source type
  if (sourceType === 'file') {
    if (source.toLowerCase().endsWith('.pdf')) {
      return { type: 'pdf', filename: source }
    }
    return { type: 'file', filename: source }
  }
  
  if (sourceType === 'text') {
    return { type: 'text' }
  }
  
  // URL that's not ArXiv
  if (source.startsWith('http://') || source.startsWith('https://')) {
    if (source.toLowerCase().includes('.pdf')) {
      return { type: 'pdf', url: source }
    }
    return { type: 'url', url: source }
  }
  
  return { type: 'unknown' }
}

/**
 * Format a source for display - extract just the URL if title+URL are combined
 */
function formatSource(source, title, sourceType, checkId) {
  if (!source) return null
  
  // For pasted text, don't show the temp file path - we'll show extraction method as source instead
  if (sourceType === 'text') {
    return null
  }
  
  // For file uploads, show the original filename (stored in title) instead of temp path
  if (sourceType === 'file' && title && checkId) {
    return { 
      type: 'file', 
      value: `/api/file/${checkId}`, 
      display: title,
      checkId: checkId
    }
  }
  
  // If source contains the title at the beginning followed by a URL, extract just the URL
  // This handles cases where paper_source was incorrectly stored as "Title URL"
  if (title && source.startsWith(title)) {
    const remainder = source.substring(title.length).trim()
    if (remainder.startsWith('http://') || remainder.startsWith('https://')) {
      source = remainder
    }
  }
  
  // If it's a URL, show it as a link (full URL, will word-wrap in display)
  if (source.startsWith('http://') || source.startsWith('https://')) {
    return { type: 'url', value: source, display: source }
  }
  // ArXiv IDs - show full URL (handles both "2310.02238" and "arXiv:2310.02238" formats)
  const arxivMatch = source.match(/^(?:arXiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)$/i)
  if (arxivMatch) {
    const fullUrl = `https://arxiv.org/abs/${arxivMatch[1]}`
    return { type: 'url', value: fullUrl, display: fullUrl }
  }
  // Filename or other
  return { type: 'text', value: source, display: source }
}

/**
 * Status section showing check progress - treats all checks as peers
 */
export default function StatusSection() {
  const { 
    status: checkStoreStatus, 
    statusMessage: checkStoreMessage,
    progress: checkStoreProgress,
    paperTitle: checkStorePaperTitle, 
    paperSource: checkStorePaperSource,
    sourceType: checkStoreSourceType,
    currentCheckId,
    sessionId,
    stats: checkStoreStats,
    cancelCheck: storeCancelCheck,
    setError,
  } = useCheckStore()
  const { selectedCheck, selectedCheckId, isLoadingDetail, updateHistoryProgress, history } = useHistoryStore()

  // Get the history item for the current check (may have the correct title from addToHistory)
  const historyItem = history.find(h => h.id === selectedCheckId)

  // Determine if we're viewing a check (either the current session's check or any history item)
  const isViewingCheck = selectedCheckId !== null && selectedCheckId !== -1
  
  // Get the session_id for the currently viewed check (if any) to enable cancel
  // For current session check, we use sessionId from checkStore
  // For other checks, we'd need the session_id from selectedCheck (if still running)
  const viewedCheckSessionId = selectedCheckId === currentCheckId ? sessionId : selectedCheck?.session_id

  // Unify data source: prefer selectedCheck (from history store) when viewing any check
  // Fall back to checkStore for the current session if selectedCheck isn't loaded yet
  const isCurrentSessionCheck = selectedCheckId === currentCheckId
  
  // Derive display values
  // For current session: prefer checkStore (has live WebSocket data)
  // For other checks: use selectedCheck (has history data)
  let displayStatus = 'idle'
  let displayTitle = null
  let displaySource = null
  let displayMessage = ''
  let displayProgress = 0
  let displayTotalRefs = 0
  let displayProcessedRefs = 0
  let displayLlmProvider = null
  let displayLlmModel = null
  let displayExtractionMethod = null
  
  if (isCurrentSessionCheck && checkStoreStatus !== 'idle') {
    // Current session: use live WebSocket data from checkStore
    displayStatus = checkStoreStatus
    // Use checkStore title if available and not "Unknown Paper", else fall back to history item or selectedCheck
    displayTitle = checkStorePaperTitle && checkStorePaperTitle !== 'Unknown Paper' 
      ? checkStorePaperTitle 
      : (historyItem?.paper_title || selectedCheck?.paper_title || checkStorePaperTitle)
    // Use checkStore source if available, else fall back to history item or selectedCheck
    displaySource = checkStorePaperSource || historyItem?.paper_source || selectedCheck?.paper_source
    displayMessage = checkStoreMessage
    displayProgress = checkStoreProgress
    displayTotalRefs = checkStoreStats?.total_refs || 0
    displayProcessedRefs = checkStoreStats?.processed_refs || 0
    // Get LLM info and extraction method from selectedCheck (history) since it's not in checkStore
    displayLlmProvider = selectedCheck?.llm_provider
    displayLlmModel = selectedCheck?.llm_model
    displayExtractionMethod = selectedCheck?.extraction_method || checkStoreStats?.extraction_method
  } else if (isViewingCheck && selectedCheck) {
    // Other checks: use selectedCheck data from history
    displayStatus = selectedCheck.status || 'idle'
    displayTitle = selectedCheck.custom_label || selectedCheck.paper_title
    displaySource = selectedCheck.paper_source
    displayTotalRefs = selectedCheck.total_refs || 0
    displayProcessedRefs = selectedCheck.processed_refs || 0
    displayProgress = displayTotalRefs > 0 ? (displayProcessedRefs / displayTotalRefs) * 100 : 0
    displayLlmProvider = selectedCheck.llm_provider
    displayLlmModel = selectedCheck.llm_model
    displayExtractionMethod = selectedCheck.extraction_method
    
    // Build status message based on state
    if (displayStatus === 'in_progress') {
      if (displayProcessedRefs > 0) {
        displayMessage = `Processed ${displayProcessedRefs} of ${displayTotalRefs} references...`
      } else if (displayTotalRefs > 0) {
        displayMessage = `Found ${displayTotalRefs} references, starting verification...`
      } else {
        displayMessage = 'Extracting references...'
      }
    } else if (displayStatus === 'completed') {
      displayMessage = `Completed • ${displayTotalRefs} references checked`
    } else if (displayStatus === 'cancelled') {
      displayMessage = 'Check cancelled'
    } else if (displayStatus === 'error') {
      displayMessage = 'Check failed'
    }
  }

  // Determine the source type - prefer selectedCheck, fall back to checkStore for current session
  const displaySourceType = selectedCheck?.source_type || (isCurrentSessionCheck ? checkStoreSourceType : null)
  const displayLlmLabel = displayLlmModel 
    ? `${displayLlmProvider ? `${displayLlmProvider} / ` : ''}${displayLlmModel}`
    : null
  
  const sourceInfo = formatSource(displaySource, displayTitle, displaySourceType, selectedCheckId)
  const thumbnailInfo = getThumbnailInfo(displaySource, displaySourceType)
  const isInProgress = displayStatus === 'in_progress' || displayStatus === 'checking'
  const isCompleted = displayStatus === 'completed'
  const isCancelled = displayStatus === 'cancelled'
  const isError = displayStatus === 'error'

  // State for thumbnail loading
  const [thumbnailUrl, setThumbnailUrl] = useState(null)
  const [thumbnailError, setThumbnailError] = useState(false)
  const [thumbnailLoading, setThumbnailLoading] = useState(false)
  const [showThumbnailOverlay, setShowThumbnailOverlay] = useState(false)
  const [previewUrl, setPreviewUrl] = useState(null)
  
  // Fetch thumbnail when check ID changes
  useEffect(() => {
    if (!selectedCheckId || selectedCheckId === -1) {
      setThumbnailUrl(null)
      setPreviewUrl(null)
      setThumbnailError(false)
      return
    }
    
    // Reset state for new check
    setThumbnailUrl(null)
    setPreviewUrl(null)
    setThumbnailError(false)
    setThumbnailLoading(true)
    
    // Set the thumbnail URL - let the img element handle loading
    const url = `${API_BASE}/api/thumbnail/${selectedCheckId}`
    setThumbnailUrl(url)
    // Set the high-resolution preview URL for overlay
    setPreviewUrl(`${API_BASE}/api/preview/${selectedCheckId}`)
    setThumbnailLoading(false)
    
  }, [selectedCheckId])

  // Thumbnail component showing actual PDF first page
  const renderThumbnail = () => {
    // Only show thumbnail if we have a check selected
    if (!selectedCheckId || selectedCheckId === -1) return null
    
    const thumbnailStyle = {
      width: '80px',
      height: '100px',
      flexShrink: 0,
      borderRadius: '4px',
      overflow: 'hidden',
      backgroundColor: 'var(--color-bg-tertiary)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      border: '1px solid var(--color-border)',
    }
    
    const iconStyle = {
      width: '24px',
      height: '24px',
      color: 'var(--color-text-muted)',
    }
    
    // Build the link URL based on source type
    let linkUrl = null
    if (thumbnailInfo?.type === 'arxiv' && thumbnailInfo?.pdfUrl) {
      linkUrl = thumbnailInfo.pdfUrl
    } else if (thumbnailInfo?.type === 'url' && thumbnailInfo?.url) {
      linkUrl = thumbnailInfo.url
    } else if (thumbnailInfo?.type === 'pdf' && thumbnailInfo?.url) {
      linkUrl = thumbnailInfo.url
    } else if (thumbnailInfo?.type === 'text' && selectedCheckId) {
      // For pasted text, link to the text content endpoint
      linkUrl = `${API_BASE}/api/text/${selectedCheckId}`
    } else if (thumbnailInfo?.type === 'file' && selectedCheckId) {
      // For uploaded files, link to the file endpoint
      linkUrl = `${API_BASE}/api/file/${selectedCheckId}`
    }
    
    // If we have a thumbnail URL and it hasn't errored, show the actual image
    if (thumbnailUrl && !thumbnailError) {
      const imgElement = (
        <img
          src={thumbnailUrl}
          alt="Paper thumbnail"
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            objectPosition: 'top',
          }}
          onError={() => setThumbnailError(true)}
          onLoad={() => setThumbnailLoading(false)}
        />
      )
      
      // Always use button to show overlay on click
      return (
        <button
          type="button"
          title="Click to enlarge"
          onClick={(e) => {
            e.stopPropagation()
            setShowThumbnailOverlay(true)
          }}
          style={{
            ...thumbnailStyle,
            cursor: 'pointer',
            transition: 'border-color 0.2s, box-shadow 0.2s',
            padding: 0,
            background: 'none',
          }}
          className="hover:border-blue-400 hover:shadow-md"
        >
          {thumbnailLoading ? (
            <svg className="w-6 h-6 animate-spin" fill="none" viewBox="0 0 24 24" style={{ color: 'var(--color-text-muted)' }}>
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : imgElement}
        </button>
      )
    }
    
    // Fallback to icons if thumbnail fails or is loading
    if (thumbnailInfo?.type === 'arxiv') {
      return (
        <a 
          href={linkUrl || thumbnailInfo.thumbnailUrl}
          target="_blank"
          rel="noopener noreferrer"
          title={`View on ArXiv: ${thumbnailInfo.arxivId}`}
          onClick={(e) => e.stopPropagation()}
          style={{
            ...thumbnailStyle,
            textDecoration: 'none',
            cursor: 'pointer',
          }}
          className="hover:border-blue-400"
        >
          <div style={{ textAlign: 'center' }}>
            <svg style={iconStyle} viewBox="0 0 24 24" fill="currentColor">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/>
              <polyline points="14 2 14 8 20 8" fill="none" stroke="currentColor" strokeWidth="1.5"/>
              <line x1="16" y1="13" x2="8" y2="13" stroke="white" strokeWidth="1.5"/>
              <line x1="16" y1="17" x2="8" y2="17" stroke="white" strokeWidth="1.5"/>
            </svg>
            <div style={{ fontSize: '8px', marginTop: '2px', color: 'var(--color-text-muted)' }}>
              arXiv
            </div>
          </div>
        </a>
      )
    }
    
    if (thumbnailInfo?.type === 'pdf') {
      const content = (
        <div style={{ textAlign: 'center' }}>
          <svg style={iconStyle} viewBox="0 0 24 24" fill="currentColor">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/>
            <polyline points="14 2 14 8 20 8" fill="none" stroke="currentColor" strokeWidth="1.5"/>
          </svg>
          <div style={{ fontSize: '8px', marginTop: '2px', color: 'var(--color-text-muted)' }}>
            PDF
          </div>
        </div>
      )
      
      if (linkUrl) {
        return (
          <a 
            href={linkUrl}
            target="_blank"
            rel="noopener noreferrer"
            title="View PDF"
            onClick={(e) => e.stopPropagation()}
            style={{
              ...thumbnailStyle,
              textDecoration: 'none',
              cursor: 'pointer',
            }}
            className="hover:border-blue-400"
          >
            {content}
          </a>
        )
      }
      return <div style={thumbnailStyle}>{content}</div>
    }
    
    if (thumbnailInfo?.type === 'text') {
      const textLinkUrl = selectedCheckId ? `${API_BASE}/api/text/${selectedCheckId}` : null
      const content = (
        <div style={{ textAlign: 'center' }}>
          <svg style={iconStyle} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/>
            <path d="M14 2v6h6"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
          </svg>
          <div style={{ fontSize: '8px', marginTop: '2px', color: 'var(--color-text-muted)' }}>
            Text
          </div>
        </div>
      )
      
      if (textLinkUrl) {
        return (
          <a 
            href={textLinkUrl}
            target="_blank"
            rel="noopener noreferrer"
            title="View pasted text"
            onClick={(e) => e.stopPropagation()}
            style={{
              ...thumbnailStyle,
              textDecoration: 'none',
              cursor: 'pointer',
            }}
            className="hover:border-blue-400"
          >
            {content}
          </a>
        )
      }
      return <div style={thumbnailStyle}>{content}</div>
    }
    
    if (thumbnailInfo?.type === 'file') {
      const fileLinkUrl = selectedCheckId ? `${API_BASE}/api/file/${selectedCheckId}` : null
      const content = (
        <div style={{ textAlign: 'center' }}>
          <svg style={iconStyle} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/>
            <path d="M14 2v6h6"/>
          </svg>
          <div style={{ fontSize: '8px', marginTop: '2px', color: 'var(--color-text-muted)' }}>
            File
          </div>
        </div>
      )
      
      if (fileLinkUrl) {
        return (
          <a 
            href={fileLinkUrl}
            target="_blank"
            rel="noopener noreferrer"
            title="View uploaded file"
            onClick={(e) => e.stopPropagation()}
            style={{
              ...thumbnailStyle,
              textDecoration: 'none',
              cursor: 'pointer',
            }}
            className="hover:border-blue-400"
          >
            {content}
          </a>
        )
      }
      return <div style={thumbnailStyle}>{content}</div>
    }
    
    if (thumbnailInfo?.type === 'url') {
      return (
        <a 
          href={thumbnailInfo.url}
          target="_blank"
          rel="noopener noreferrer"
          title="Open URL"
          onClick={(e) => e.stopPropagation()}
          style={{
            ...thumbnailStyle,
            textDecoration: 'none',
            cursor: 'pointer',
          }}
          className="hover:border-blue-400"
        >
          <div style={{ textAlign: 'center' }}>
            <svg style={iconStyle} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="12" cy="12" r="10"/>
              <line x1="2" y1="12" x2="22" y2="12"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
            <div style={{ fontSize: '8px', marginTop: '2px', color: 'var(--color-text-muted)' }}>
              URL
            </div>
          </div>
        </a>
      )
    }
    
    return null
  }

  // Show loading state when switching to a check
  if (isViewingCheck && isLoadingDetail) {
    return (
      <div 
        className="rounded-lg border p-4"
        style={{
          backgroundColor: 'var(--color-bg-secondary)',
          borderColor: 'var(--color-border)',
        }}
      >
        <div className="flex items-center gap-3">
          <div 
            className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 animate-pulse"
            style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
          >
            <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24" style={{ color: 'var(--color-text-muted)' }}>
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
          <div className="flex-1 min-w-0">
            <h3 
              className="font-medium"
              style={{ color: 'var(--color-text-primary)' }}
            >
              Loading check details...
            </h3>
          </div>
        </div>
      </div>
    )
  }

  // Not viewing any check
  if (!isViewingCheck || displayStatus === 'idle') {
    return null
  }

  // Status icon based on state
  const getStatusIcon = () => {
    if (isInProgress) {
      return (
        <svg 
          className="w-6 h-6 animate-spin" 
          fill="none" 
          viewBox="0 0 24 24"
          style={{ color: 'var(--color-accent)' }}
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )
    }
    if (isCompleted) {
      return (
        <svg 
          className="w-6 h-6" 
          fill="none" 
          viewBox="0 0 24 24" 
          stroke="currentColor"
          style={{ color: 'var(--color-success)' }}
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      )
    }
    if (isCancelled) {
      return (
        <svg 
          className="w-6 h-6" 
          viewBox="0 0 24 24" 
          fill="none"
          stroke="currentColor"
          style={{ color: 'var(--color-warning)' }}
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      )
    }
    if (isError) {
      return (
        <svg 
          className="w-6 h-6" 
          viewBox="0 0 24 24" 
          fill="none"
          stroke="currentColor"
          style={{ color: 'var(--color-error)' }}
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      )
    }
    return null
  }

  const getStatusBgColor = () => {
    if (isInProgress) return 'var(--color-info-bg)'
    if (isCompleted) return 'var(--color-success-bg)'
    if (isCancelled) return 'var(--color-warning-bg)'
    if (isError) return 'var(--color-error-bg)'
    return 'var(--color-bg-tertiary)'
  }

  // Can cancel if this check is in progress AND we have a session_id for it
  const canCancel = isInProgress && viewedCheckSessionId

  return (
    <div 
      className="rounded-lg border p-4"
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)',
      }}
    >
      <div className="flex items-center gap-3">
        <div 
          className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: getStatusBgColor() }}
        >
          {getStatusIcon()}
        </div>
        {/* Thumbnail */}
        {renderThumbnail()}
        <div className="flex-1 min-w-0">
          {displayTitle && (
            <h3 
              className="font-medium"
              style={{ 
                color: 'var(--color-text-primary)',
                wordBreak: 'break-word',
                overflowWrap: 'anywhere',
              }}
            >
              {displayTitle}
            </h3>
          )}
          {/* Hide source info for pasted text since it shows the file path or text content */}
          {sourceInfo && thumbnailInfo?.type !== 'text' && (
            <p 
              className="text-sm"
              style={{ 
                color: 'var(--color-text-muted)',
                wordBreak: 'break-all',
                overflowWrap: 'anywhere',
              }}
              title={sourceInfo.value}
            >
              {sourceInfo.type === 'url' || sourceInfo.type === 'file' ? (
                <a 
                  href={sourceInfo.value} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="hover:underline"
                  style={{ color: 'var(--color-link)' }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {sourceInfo.display}
                </a>
              ) : (
                sourceInfo.display
              )}
            </p>
          )}
          {/* Show extraction source - clickable for text sources */}
          {(() => {
            if (displayExtractionMethod && ['bbl', 'bib'].includes(displayExtractionMethod)) {
              const label = displaySourceType === 'text' ? `Pasted .${displayExtractionMethod} file` : `ArXiv .${displayExtractionMethod} file`
              return (
                <p 
                  className="text-sm"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  Source:{' '}
                  {selectedCheckId ? (
                    <a 
                      href={`${API_BASE}/api/bibliography/${selectedCheckId}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:underline"
                      style={{ color: 'var(--color-link)' }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {label}
                    </a>
                  ) : (
                    label
                  )}
                </p>
              )
            }

            if (displayExtractionMethod === 'pdf') {
              return (
                <p 
                  className="text-sm"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  Source: PDF extraction
                </p>
              )
            }

            if (displaySourceType === 'text' && selectedCheckId) {
              return (
                <p 
                  className="text-sm"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  Source:{' '}
                  <a 
                    href={`${API_BASE}/api/text/${selectedCheckId}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline"
                    style={{ color: 'var(--color-link)' }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    Pasted text
                  </a>
                </p>
              )
            }

            if (displaySourceType === 'file' && selectedCheckId) {
              return (
                <p 
                  className="text-sm"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  Source:{' '}
                  <a 
                    href={`${API_BASE}/api/file/${selectedCheckId}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline"
                    style={{ color: 'var(--color-link)' }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    Uploaded file
                  </a>
                </p>
              )
            }

            return null
          })()}

          {displayLlmLabel && (
            <p 
              className="text-sm"
              style={{ color: 'var(--color-text-muted)' }}
            >
              Model: {displayLlmLabel}
            </p>
          )}
          <p 
            className="text-sm"
            style={{ 
              color: isError ? 'var(--color-error)' : 'var(--color-text-muted)',
              wordBreak: 'break-word',
              overflowWrap: 'anywhere',
            }}
          >
            {displayMessage}
          </p>
        </div>
        {canCancel && (
          <button
            onClick={async () => {
              if (!viewedCheckSessionId) return
              try {
                logger.info('StatusSection', `Cancelling check ${viewedCheckSessionId}`)
                await api.cancelCheck(viewedCheckSessionId)
                // Update history item status
                if (selectedCheckId) {
                  updateHistoryProgress(selectedCheckId, { status: 'cancelled' })
                }
                // Only update checkStore if cancelling the current session
                if (viewedCheckSessionId === sessionId) {
                  storeCancelCheck()
                }
              } catch (error) {
                logger.error('StatusSection', 'Failed to cancel', error)
                // Still mark as cancelled since the check may have already finished
                if (selectedCheckId) {
                  updateHistoryProgress(selectedCheckId, { status: 'cancelled' })
                }
                if (viewedCheckSessionId === sessionId) {
                  storeCancelCheck()
                }
                setError(error.response?.data?.detail || error.message || 'Failed to cancel')
              }
            }}
            className="px-3 py-2 text-sm font-medium rounded transition-colors cursor-pointer hover:opacity-80"
            style={{
              backgroundColor: 'var(--color-error-bg)',
              color: 'var(--color-error)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-error)'
              e.currentTarget.style.color = 'white'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-error-bg)'
              e.currentTarget.style.color = 'var(--color-error)'
            }}
          >
            Cancel
          </button>
        )}
      </div>

      {/* Progress bar for in-progress checks */}
      {isInProgress && (
        <div className="mt-4">
          <div 
            className="h-2 rounded-full overflow-hidden"
            style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
          >
            <div 
              className="h-full rounded-full transition-all duration-300 progress-bar"
              style={{ 
                width: `${Math.round(displayProgress)}%`,
              }}
            />
          </div>
          <p 
            className="text-xs mt-1"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {displayTotalRefs > 0 
              ? `${Math.round(displayProgress)}% complete`
              : 'Starting...'}
          </p>
        </div>
      )}

      {/* Thumbnail overlay modal */}
      {showThumbnailOverlay && (previewUrl || thumbnailUrl) && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.9)' }}
          onClick={() => setShowThumbnailOverlay(false)}
        >
          <div className="relative w-full h-full flex items-center justify-center p-8">
            <button
              type="button"
              onClick={() => setShowThumbnailOverlay(false)}
              className="absolute top-4 right-4 w-10 h-10 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors z-10"
              title="Close (Esc)"
            >
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            <img
              src={previewUrl || thumbnailUrl}
              alt="Paper preview"
              style={{ maxWidth: '95vw', maxHeight: '95vh', objectFit: 'contain' }}
              className="rounded-lg shadow-2xl"
              onClick={(e) => e.stopPropagation()}
              onError={(e) => {
                // Fall back to thumbnail if preview fails
                if (previewUrl && thumbnailUrl && e.target.src !== thumbnailUrl) {
                  e.target.src = thumbnailUrl
                }
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
