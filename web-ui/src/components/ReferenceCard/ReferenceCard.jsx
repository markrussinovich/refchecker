import { formatAuthors } from '../../utils/formatters'

const urlPattern = /https?:\/\/[^\s]+/g

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
        style={{ color: 'var(--color-accent)' }}
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
  const numberToShow = typeof displayIndex === 'number' ? displayIndex : index
  const status = (reference.status || '').toLowerCase()
  const getStatusColor = () => {
    switch (status) {
      case 'verified': return 'var(--color-success)'
      case 'warning': return 'var(--color-warning)'
      case 'error': return 'var(--color-error)'
      case 'unverified': return 'var(--color-text-muted)'
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
            <circle cx="12" cy="12" r="10" fill="var(--color-warning)" />
            <path d="M12 7.5v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
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
      <div className="flex items-start gap-3 pl-4">
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
          {/* Title */}
          <div 
            className="font-bold"
            style={{ color: 'var(--color-text-primary)' }}
          >
            {reference.title || 'Unknown Title'}
          </div>
          
          {/* Authors */}
          {reference.authors?.length > 0 && (
            <div 
              className="mt-1"
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
                style={{ color: 'var(--color-accent)' }}
              >
                {reference.cited_url}
              </a>
            </div>
          )}

          {/* Blank line before verification results */}
          {(reference.authoritative_urls?.length > 0 || 
            reference.errors?.length > 0 || 
            reference.warnings?.length > 0 ||
            reference.status === 'unverified') && (
            <div className="h-3" />
          )}

          {/* Authoritative URLs */}
          {reference.authoritative_urls?.map((urlObj, i) => (
            <div key={i}>
              <span style={{ color: 'var(--color-text-secondary)' }}>
                {formatUrlType(urlObj.type)}:{' '}
              </span>
              <a
                href={urlObj.url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:underline"
                style={{ color: 'var(--color-accent)' }}
              >
                {urlObj.url}
              </a>
            </div>
          ))}

          {/* Unverified message */}
          {reference.status === 'unverified' && (
            <div 
              className="flex items-start gap-2"
              style={{ color: 'var(--color-text-muted)', wordBreak: 'break-word' }}
            >
              <span>❓</span>
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
          {reference.warnings?.map((warning, i) => (
            <div 
              key={`warning-${i}`}
              className="flex items-start gap-2"
              style={{ color: 'var(--color-warning)', wordBreak: 'break-word' }}
            >
              <span>⚠️</span>
              <div>
                <div>Warning: {formatWarningType(warning.error_type)} mismatch:</div>
                {warning.error_details && (
                  <div 
                    style={{ 
                      color: 'var(--color-warning)', 
                      whiteSpace: 'pre-line' 
                    }}
                  >
                    {renderTextWithLinks(warning.error_details)}
                  </div>
                )}
                {warning.cited_value && (
                  <div style={{ color: 'var(--color-text-secondary)' }}>
                    cited: '{warning.cited_value}'
                  </div>
                )}
                {warning.actual_value && (
                  <div style={{ color: 'var(--color-text-secondary)' }}>
                    actual: '{warning.actual_value}'
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Errors (non-unverified) */}
          {reference.errors?.filter(e => e.error_type !== 'unverified').map((error, i) => (
            <div 
              key={`error-${i}`}
              className="flex items-start gap-2"
              style={{ color: 'var(--color-error)', wordBreak: 'break-word' }}
            >
              <span className="pt-0.5 inline-block">
                <svg 
                  className="w-4 h-4"
                  viewBox="0 0 24 24" 
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M9.172 4.172a4 4 0 015.656 0l2.828 2.828a4 4 0 010 5.656l-2.828 2.828a4 4 0 01-5.656 0L6.343 12.656a4 4 0 010-5.656l2.829-2.828z" />
                  <path d="M12 8v5" />
                  <path d="M12 16h.01" />
                </svg>
              </span>
              <div>
                <div 
                  style={{ whiteSpace: 'pre-line' }}
                >
                  Error: {renderTextWithLinks(error.error_details || error.error_type)}
                </div>
                {error.cited_value && (
                  <div 
                    className="pl-8" 
                    style={{ color: 'var(--color-text-secondary)', whiteSpace: 'pre-line' }}
                  >
                    cited: '{error.cited_value}'
                  </div>
                )}
                {error.actual_value && (
                  <div 
                    className="pl-8" 
                    style={{ color: 'var(--color-text-secondary)', whiteSpace: 'pre-line' }}
                  >
                    actual: '{error.actual_value}'
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Information messages (e.g., missing arXiv URL) */}
          {reference.info_messages?.map((info, i) => (
            <div 
              key={`info-${i}`}
              className="flex items-start gap-2"
              style={{ color: 'var(--color-accent)', wordBreak: 'break-word' }}
            >
              <span>ℹ️</span>
              <span>{renderTextWithLinks(info)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
