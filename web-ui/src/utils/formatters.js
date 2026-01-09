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
export function formatAuthors(authors) {
  if (!authors || authors.length === 0) return 'Unknown authors'
  if (authors.length === 1) return authors[0]
  if (authors.length === 2) return `${authors[0]} and ${authors[1]}`
  return `${authors[0]} et al.`
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
