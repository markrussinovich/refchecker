import { formatAuthors } from '../../utils/formatters'

/**
 * Individual reference card matching CLI output format
 */
export default function ReferenceCard({ reference, index, totalRefs }) {
  const getStatusEmoji = () => {
    switch (reference.status) {
      case 'verified': return '✓'
      case 'warning': return '⚠️'
      case 'error': return '❌'
      case 'unverified': return '❓'
      case 'checking': return null // Will use spinner
      case 'pending': return null // Will use circle
      default: return '○'
    }
  }

  const getStatusColor = () => {
    switch (reference.status) {
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
    if (reference.status === 'checking') {
      // Spinning animation for actively checking
      return (
        <span 
          className="flex-shrink-0 inline-block w-5 h-5 mr-1"
          title="Checking..."
        >
          <svg 
            className="animate-spin" 
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
    
    if (reference.status === 'pending') {
      // Clock icon for waiting in queue
      return (
        <span 
          className="flex-shrink-0 inline-block w-5 h-5 mr-1"
          title="Waiting in queue"
        >
          <svg 
            viewBox="0 0 24 24" 
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ color: getStatusColor() }}
          >
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        </span>
      )
    }

    // Default emoji-based status
    return (
      <span 
        className="flex-shrink-0 text-lg"
        style={{ color: getStatusColor() }}
        title={reference.status}
      >
        {getStatusEmoji()}
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
      {/* Reference header: [1/14] Title */}
      <div className="flex items-start gap-2">
        <span 
          className="flex-shrink-0 font-bold"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          [{index + 1}/{totalRefs}]
        </span>
        <div className="flex-1 min-w-0">
          {/* Title */}
          <div className="flex items-start justify-between gap-2">
            <span style={{ color: 'var(--color-text-primary)' }}>
              {reference.title || 'Unknown Title'}
            </span>
            {renderStatusIndicator()}
          </div>
          
          {/* Authors */}
          {reference.authors?.length > 0 && (
            <div 
              className="mt-1 pl-6"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {formatAuthors(reference.authors)}
            </div>
          )}
          
          {/* Venue */}
          {reference.venue && (
            <div 
              className="pl-6"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {reference.venue}
            </div>
          )}
          
          {/* Year */}
          {reference.year && (
            <div 
              className="pl-6"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {reference.year}
            </div>
          )}
          
          {/* Cited URL */}
          {reference.cited_url && (
            <div className="pl-6">
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
            <div key={i} className="pl-6">
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
              className="pl-6 flex items-start gap-2"
              style={{ color: 'var(--color-text-muted)' }}
            >
              <span>❓</span>
              <div>
                <div>Could not verify: {reference.title || 'Unknown'}</div>
                {reference.errors?.find(e => e.error_type === 'unverified') && (
                  <div className="pl-3">
                    Subreason: {reference.errors.find(e => e.error_type === 'unverified')?.error_details || 'Paper not found by any checker'}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Warnings */}
          {reference.warnings?.map((warning, i) => (
            <div 
              key={`warning-${i}`}
              className="pl-6 flex items-start gap-2"
              style={{ color: 'var(--color-warning)' }}
            >
              <span>⚠️</span>
              <div>
                <div>Warning: {formatWarningType(warning.error_type)} mismatch:</div>
                {warning.cited_value && (
                  <div className="pl-8" style={{ color: 'var(--color-text-secondary)' }}>
                    cited: '{warning.cited_value}'
                  </div>
                )}
                {warning.actual_value && (
                  <div className="pl-8" style={{ color: 'var(--color-text-secondary)' }}>
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
              className="pl-6 flex items-start gap-2"
              style={{ color: 'var(--color-error)' }}
            >
              <span>❌</span>
              <div>
                <div>Error: {error.error_details || error.error_type}</div>
                {error.cited_value && (
                  <div className="pl-8" style={{ color: 'var(--color-text-secondary)' }}>
                    cited: '{error.cited_value}'
                  </div>
                )}
                {error.actual_value && (
                  <div className="pl-8" style={{ color: 'var(--color-text-secondary)' }}>
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
              className="pl-6 flex items-start gap-2"
              style={{ color: 'var(--color-accent)' }}
            >
              <span>ℹ️</span>
              <span>{info}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
