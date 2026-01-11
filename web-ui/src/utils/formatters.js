/**
 * Formatting utilities
 */

/**
 * Format a date for display
 * @param {string|Date} date - Date to format
 * @returns {string} Formatted date string
 */
export function formatDate(date) {
  const d = new Date(date)
  const now = new Date()
  const diffMs = now - d
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  
  if (diffDays === 0) {
    return `Today at ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
  } else if (diffDays === 1) {
    return `Yesterday at ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
  } else if (diffDays < 7) {
    return d.toLocaleDateString([], { weekday: 'long', hour: '2-digit', minute: '2-digit' })
  } else {
    return d.toLocaleDateString([], { 
      year: 'numeric', 
      month: 'short', 
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }
}

/**
 * Format authors for display
 * @param {string[]} authors - Array of author names
 * @returns {string} Formatted author string
 */
export function formatAuthors(authors, truncate = false) {
  if (!authors || authors.length === 0) return 'Unknown authors'
  if (authors.length === 1) return authors[0]
  if (authors.length === 2) return `${authors[0]} and ${authors[1]}`
  if (truncate) {
    return `${authors[0]} et al.`
  }
  // Show all authors with "et al." suffix if list is very long
  if (authors.length > 10) {
    return `${authors.slice(0, 10).join(', ')}, et al.`
  }
  return authors.join(', ')
}

/**
 * Format a reference in standard bibliographic format
 * @param {object} ref - Reference object
 * @returns {string} Formatted reference
 */
export function formatReference(ref) {
  const parts = []
  
  if (ref.authors?.length > 0) {
    parts.push(formatAuthors(ref.authors))
  }
  
  if (ref.year) {
    parts.push(`(${ref.year})`)
  }
  
  if (ref.title) {
    parts.push(`"${ref.title}"`)
  }
  
  if (ref.venue) {
    parts.push(ref.venue)
  }
  
  return parts.join(' ')
}

/**
 * Truncate text with ellipsis
 * @param {string} text - Text to truncate
 * @param {number} maxLength - Maximum length
 * @returns {string} Truncated text
 */
export function truncate(text, maxLength = 50) {
  if (!text || text.length <= maxLength) return text
  return text.slice(0, maxLength - 3) + '...'
}

/**
 * Format file size
 * @param {number} bytes - Size in bytes
 * @returns {string} Formatted size string
 */
export function formatFileSize(bytes) {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

/**
 * Get status color class based on status
 * @param {string} status - Status string (verified, error, warning, unverified)
 * @returns {object} Object with text and bg color classes
 */
export function getStatusColors(status) {
  switch (status?.toLowerCase()) {
    case 'verified':
      return { text: 'var(--color-success)', bg: 'var(--color-success-bg)' }
    case 'error':
      return { text: 'var(--color-error)', bg: 'var(--color-error-bg)' }
    case 'warning':
      return { text: 'var(--color-warning)', bg: 'var(--color-warning-bg)' }
    case 'unverified':
    default:
      return { text: 'var(--color-text-muted)', bg: 'var(--color-bg-tertiary)' }
  }
}

/**
 * Parse error/warning details to extract cited/actual values
 * Handles formats like:
 * - "Title mismatch:\n       cited:  value\n       actual: value"
 * - "Venue mismatch: cited: value actual: value"
 * @param {string} details - Error details string
 * @returns {object|null} Parsed object with prefix, cited, actual or null if not parseable
 */
function parseErrorDetailsForMarkdown(details) {
  if (!details) return null
  
  // Try multiline format first: "Prefix:\n       cited:  value\n       actual: value"
  const lines = details.split('\n')
  if (lines.length >= 3) {
    const prefix = lines[0].replace(/:$/, '').trim()
    const citedMatch = lines[1].match(/cited:\s*(.*)/)
    const actualMatch = lines[2].match(/actual:\s*(.*)/)
    if (citedMatch || actualMatch) {
      return {
        prefix,
        cited: citedMatch ? citedMatch[1].trim() : null,
        actual: actualMatch ? actualMatch[1].trim() : null
      }
    }
  }
  
  // Try single-line format: "Prefix: cited: value actual: value" or "Prefix cited: value actual: value"
  const singleLineMatch = details.match(/^(.+?):?\s*cited:\s*([^a]+?)(?:\s+actual:\s*(.+))?$/i)
  if (singleLineMatch) {
    return {
      prefix: singleLineMatch[1].trim(),
      cited: singleLineMatch[2]?.trim() || null,
      actual: singleLineMatch[3]?.trim() || null
    }
  }
  
  // Try format with "cited:" and "actual:" anywhere in string
  const citedIdx = details.toLowerCase().indexOf('cited:')
  const actualIdx = details.toLowerCase().indexOf('actual:')
  if (citedIdx !== -1 && actualIdx !== -1 && actualIdx > citedIdx) {
    const prefix = details.substring(0, citedIdx).replace(/:$/, '').trim()
    const cited = details.substring(citedIdx + 6, actualIdx).trim()
    const actual = details.substring(actualIdx + 7).trim()
    return { prefix, cited, actual }
  }
  
  return null
}

/**
 * Export check results as markdown
 * @param {object} params - Export parameters
 * @param {string} params.paperTitle - Title of the paper
 * @param {string} params.paperSource - Source URL or file
 * @param {object} params.stats - Summary statistics
 * @param {array} params.references - Array of reference results
 * @returns {string} Markdown formatted report
 */
export function exportResultsAsMarkdown({ paperTitle, paperSource, stats, references }) {
  const lines = []
  
  // Header
  lines.push(`# RefChecker Report`)
  lines.push('')
  lines.push(`**Paper:** ${paperTitle || 'Unknown'}`)
  if (paperSource) {
    lines.push(`**Source:** ${paperSource}`)
  }
  lines.push(`**Date:** ${new Date().toLocaleString()}`)
  lines.push('')
  
  // Summary
  lines.push(`## Summary`)
  lines.push('')
  lines.push(`| Metric | Count |`)
  lines.push(`|--------|-------|`)
  lines.push(`| Total References | ${stats.total_refs || 0} |`)
  lines.push(`| Verified | ${stats.refs_verified ?? stats.verified_count ?? 0} |`)
  lines.push(`| With Errors | ${stats.refs_with_errors ?? 0} |`)
  lines.push(`| With Warnings | ${stats.refs_with_warnings_only ?? 0} |`)
  lines.push(`| Unverified | ${stats.unverified_count ?? 0} |`)
  lines.push('')
  lines.push(`| Issue Type | Count |`)
  lines.push(`|------------|-------|`)
  lines.push(`| Errors | ${stats.errors_count || 0} |`)
  lines.push(`| Warnings | ${stats.warnings_count || 0} |`)
  lines.push(`| Suggestions | ${stats.suggestions_count || 0} |`)
  lines.push('')
  
  // References
  lines.push(`## References`)
  lines.push('')
  
  if (!references || references.length === 0) {
    lines.push('No references found.')
  } else {
    references.forEach((ref, index) => {
      const status = (ref.status || 'unknown').toLowerCase()
      const statusEmoji = {
        verified: '✅',
        warning: '⚠️',
        error: '❌',
        suggestion: '💡',
        unverified: '❓',
      }[status] || '❓'
      
      lines.push(`### ${index + 1}. ${ref.title || 'Unknown Title'} ${statusEmoji}`)
      lines.push('')
      
      // Authors
      if (ref.authors?.length > 0) {
        lines.push(`**Authors:** ${formatAuthors(ref.authors)}`)
      }
      
      // Year and venue
      if (ref.year) {
        lines.push(`**Year:** ${ref.year}`)
      }
      if (ref.venue) {
        lines.push(`**Venue:** ${ref.venue}`)
      }
      
      // Cited URL
      if (ref.cited_url) {
        lines.push(`**Cited URL:** ${ref.cited_url}`)
      }
      
      // Authoritative URLs
      if (ref.authoritative_urls?.length > 0) {
        lines.push('')
        lines.push('**Verified URLs:**')
        ref.authoritative_urls.forEach(urlObj => {
          const typeLabel = {
            semantic_scholar: 'Semantic Scholar',
            arxiv: 'ArXiv',
            doi: 'DOI',
            openalex: 'OpenAlex',
            openreview: 'OpenReview',
          }[urlObj.type] || urlObj.type
          lines.push(`- ${typeLabel}: ${urlObj.url}`)
        })
      }
      
      // Errors
      if (ref.errors?.length > 0) {
        const nonUnverifiedErrors = ref.errors.filter(e => e.error_type !== 'unverified')
        const unverifiedError = ref.errors.find(e => e.error_type === 'unverified')
        
        if (nonUnverifiedErrors.length > 0) {
          lines.push('')
          lines.push('**Errors:**')
          nonUnverifiedErrors.forEach(error => {
            const parsed = parseErrorDetailsForMarkdown(error.error_details)
            if (parsed) {
              lines.push(`- ❌ ${parsed.prefix}`)
              if (parsed.cited) {
                lines.push(`  - Cited: ${parsed.cited}`)
              }
              if (parsed.actual) {
                lines.push(`  - Actual: ${parsed.actual}`)
              }
            } else {
              lines.push(`- ❌ ${error.error_details || error.error_type}`)
              if (error.cited_value) {
                lines.push(`  - Cited: ${error.cited_value}`)
              }
              if (error.actual_value) {
                lines.push(`  - Actual: ${error.actual_value}`)
              }
            }
          })
        }
        
        if (unverifiedError && status === 'unverified') {
          lines.push('')
          lines.push(`**Could not verify:** ${unverifiedError.error_details || 'Paper not found by any checker'}`)
        }
      }
      
      // Warnings
      if (ref.warnings?.length > 0) {
        lines.push('')
        lines.push('**Warnings:**')
        ref.warnings.forEach(warning => {
          const parsed = parseErrorDetailsForMarkdown(warning.error_details)
          if (parsed) {
            lines.push(`- ⚠️ ${parsed.prefix}`)
            if (parsed.cited) {
              lines.push(`  - Cited: ${parsed.cited}`)
            }
            if (parsed.actual) {
              lines.push(`  - Actual: ${parsed.actual}`)
            }
          } else {
            lines.push(`- ⚠️ ${warning.error_details || warning.error_type}`)
            if (warning.cited_value) {
              lines.push(`  - Cited: ${warning.cited_value}`)
            }
            if (warning.actual_value) {
              lines.push(`  - Actual: ${warning.actual_value}`)
            }
          }
        })
      }
      
      // Suggestions
      if (ref.suggestions?.length > 0) {
        lines.push('')
        lines.push('**Suggestions:**')
        ref.suggestions.forEach(suggestion => {
          const text = typeof suggestion === 'string' ? suggestion : suggestion.suggestion_details
          lines.push(`- 💡 ${text}`)
        })
      }
      
      lines.push('')
      lines.push('---')
      lines.push('')
    })
  }
  
  return lines.join('\n')
}

/**
 * Download text content as a file
 * @param {string} content - File content
 * @param {string} filename - Filename to save as
 * @param {string} mimeType - MIME type of the file
 */
export function downloadAsFile(content, filename, mimeType = 'text/markdown') {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
