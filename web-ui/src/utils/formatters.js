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
 * Extract corrected reference data from errors and warnings
 * Uses 'actual' values from mismatches when available
 * @param {object} ref - Reference object with errors/warnings
 * @returns {object} Corrected reference data
 */
function getCorrectedReferenceData(ref) {
  const corrected = {
    title: ref.title,
    authors: ref.authors,
    year: ref.year,
    venue: ref.venue,
    url: ref.authoritative_urls?.[0]?.url || ref.cited_url
  }
  
  // Check errors and warnings for 'actual' values
  const allIssues = [...(ref.errors || []), ...(ref.warnings || [])]
  
  for (const issue of allIssues) {
    const errorType = (issue.error_type || '').toLowerCase()
    const parsed = parseErrorDetailsForMarkdown(issue.error_details)
    const actualValue = parsed?.actual || issue.actual_value
    
    if (actualValue) {
      switch (errorType) {
        case 'title':
          corrected.title = actualValue
          break
        case 'author':
        case 'authors':
          // Parse author string into array if it's a string
          if (typeof actualValue === 'string') {
            // Split on common author separators
            corrected.authors = actualValue.split(/,\s*(?:and\s+)?|;\s*|\s+and\s+/)
              .map(a => a.trim())
              .filter(a => a.length > 0)
          } else if (Array.isArray(actualValue)) {
            corrected.authors = actualValue
          }
          break
        case 'year':
          corrected.year = actualValue
          break
        case 'venue':
          corrected.venue = actualValue
          break
      }
    }
  }
  
  // Check for arXiv suggestion and extract URL
  if (ref.suggestions?.length > 0) {
    for (const suggestion of ref.suggestions) {
      const details = suggestion.suggestion_details || suggestion
      if (typeof details === 'string') {
        // Look for arXiv URL in the suggestion
        const arxivMatch = details.match(/https?:\/\/arxiv\.org\/abs\/[\w.]+/)
        if (arxivMatch) {
          corrected.arxivUrl = arxivMatch[0]
        }
      }
    }
  }
  
  return corrected
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
      
      lines.push(`### ${index + 1}. ${ref.title || ref.cited_url || 'Unknown Title'} ${statusEmoji}`)
      lines.push('')
      
      // Authors
      if (ref.authors?.length > 0) {
        lines.push(`**Authors:** ${formatAuthors(ref.authors)}`)
      }
      
      // Venue
      if (ref.venue) {
        lines.push(`**Venue:** ${ref.venue}`)
      }
      
      // Year
      if (ref.year) {
        lines.push(`**Year:** ${ref.year}`)
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
  
  // Use Markdown line breaks (two trailing spaces) to keep fields on separate, tight lines
  return lines.join('  \n')
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

/**
 * Copy text to clipboard
 * @param {string} text - Text to copy
 * @returns {Promise<boolean>} Whether copy was successful
 */
export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch (err) {
    console.error('Failed to copy to clipboard:', err)
    return false
  }
}

/**
 * Export check results as plain text
 * @param {object} params - Export parameters
 * @returns {string} Plain text formatted report
 */
export function exportResultsAsPlainText({ paperTitle, paperSource, stats, references }) {
  const lines = []
  
  lines.push('REFCHECKER REPORT')
  lines.push('='.repeat(50))
  lines.push('')
  lines.push(`Paper: ${paperTitle || 'Unknown'}`)
  if (paperSource) {
    lines.push(`Source: ${paperSource}`)
  }
  lines.push(`Date: ${new Date().toLocaleString()}`)
  lines.push('')
  lines.push('SUMMARY')
  lines.push('-'.repeat(30))
  lines.push(`Total References: ${stats.total_refs || 0}`)
  lines.push(`Verified: ${stats.refs_verified ?? stats.verified_count ?? 0}`)
  lines.push(`Errors: ${stats.errors_count || 0}`)
  lines.push(`Warnings: ${stats.warnings_count || 0}`)
  lines.push(`Unverified: ${stats.unverified_count ?? 0}`)
  lines.push('')
  lines.push('REFERENCES')
  lines.push('-'.repeat(30))
  
  if (!references || references.length === 0) {
    lines.push('No references found.')
  } else {
    references.forEach((ref, index) => {
      const status = (ref.status || 'unknown').toUpperCase()
      lines.push('')
      lines.push(`[${index + 1}] ${ref.title || ref.cited_url || 'Unknown Title'} [${status}]`)
      if (ref.authors?.length > 0) {
        lines.push(`    Authors: ${formatAuthors(ref.authors)}`)
      }
      if (ref.year) lines.push(`    Year: ${ref.year}`)
      if (ref.venue) lines.push(`    Venue: ${ref.venue}`)
      
      if (ref.errors?.length > 0) {
        ref.errors.filter(e => e.error_type !== 'unverified').forEach(e => {
          lines.push(`    ERROR: ${e.error_details || e.error_type}`)
        })
      }
      if (ref.warnings?.length > 0) {
        ref.warnings.forEach(w => {
          lines.push(`    WARNING: ${w.error_details || w.error_type}`)
        })
      }
    })
  }
  
  return lines.join('\n')
}

/**
 * Generate a BibTeX key from reference data
 * @param {object} ref - Reference object
 * @param {number} index - Reference index for fallback
 * @returns {string} BibTeX key
 */
function generateBibtexKey(ref, index) {
  // Try to create key from first author last name + year
  let key = ''
  if (ref.authors?.length > 0) {
    const firstAuthor = ref.authors[0]
    // Extract last name (last word before any comma, or last word)
    const parts = firstAuthor.split(/[,\s]+/)
    key = parts[parts.length > 1 ? parts.length - 1 : 0] || ''
    key = key.replace(/[^a-zA-Z]/g, '').toLowerCase()
  }
  if (ref.year) {
    key += ref.year
  }
  // Add first word of title for uniqueness
  if (ref.title) {
    const titleWord = ref.title.split(/\s+/)[0].replace(/[^a-zA-Z]/g, '').toLowerCase()
    key += titleWord
  }
  return key || `ref${index + 1}`
}

/**
 * Escape special BibTeX characters
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
function escapeBibtex(text) {
  if (!text) return ''
  return text
    .replace(/\\/g, '\\textbackslash{}')
    .replace(/[&%$#_{}]/g, match => '\\' + match)
    .replace(/~/g, '\\textasciitilde{}')
    .replace(/\^/g, '\\textasciicircum{}')
}

/**
 * Export a single reference as BibTeX
 * Uses corrected values from verification when available
 * @param {object} ref - Reference object
 * @param {number} index - Reference index
 * @returns {string} BibTeX entry
 */
export function exportReferenceAsBibtex(ref, index = 0) {
  // Get corrected data (uses actual values from errors/warnings)
  const corrected = getCorrectedReferenceData(ref)
  
  const key = generateBibtexKey({ ...ref, ...corrected, authors: corrected.authors }, index)
  const lines = []
  
  // Determine entry type
  const venue = (corrected.venue || '').toLowerCase()
  let entryType = 'article'
  if (venue.includes('conference') || venue.includes('proceedings') || venue.includes('workshop')) {
    entryType = 'inproceedings'
  } else if (venue.includes('arxiv') || corrected.arxivUrl || ref.cited_url?.includes('arxiv')) {
    entryType = 'misc'
  }
  
  lines.push(`@${entryType}{${key},`)
  
  // Title
  if (corrected.title) {
    lines.push(`  title = {${escapeBibtex(corrected.title)}},`)
  }
  
  // Authors
  if (corrected.authors?.length > 0) {
    const authorStr = corrected.authors.map(a => escapeBibtex(a)).join(' and ')
    lines.push(`  author = {${authorStr}},`)
  }
  
  // Year
  if (corrected.year) {
    lines.push(`  year = {${corrected.year}},`)
  }
  
  // Venue
  if (corrected.venue) {
    if (entryType === 'inproceedings') {
      lines.push(`  booktitle = {${escapeBibtex(corrected.venue)}},`)
    } else if (entryType === 'article') {
      lines.push(`  journal = {${escapeBibtex(corrected.venue)}},`)
    }
  }
  
  // URL - prefer arXiv from suggestions, then DOI, then authoritative URLs, then cited URL
  if (corrected.arxivUrl) {
    lines.push(`  url = {${corrected.arxivUrl}},`)
    // Extract arXiv ID
    const arxivMatch = corrected.arxivUrl.match(/arxiv\.org\/abs\/(.+)/)
    if (arxivMatch) {
      lines.push(`  eprint = {${arxivMatch[1]}},`)
      lines.push(`  archiveprefix = {arXiv},`)
    }
  } else {
    const doiUrl = ref.authoritative_urls?.find(u => u.type === 'doi')
    const arxivUrl = ref.authoritative_urls?.find(u => u.type === 'arxiv')
    
    if (doiUrl) {
      // Extract DOI from URL
      const doiMatch = doiUrl.url.match(/doi\.org\/(.+)/)
      if (doiMatch) {
        lines.push(`  doi = {${doiMatch[1]}},`)
      } else {
        lines.push(`  url = {${doiUrl.url}},`)
      }
    } else if (arxivUrl) {
      lines.push(`  url = {${arxivUrl.url}},`)
      // Extract arXiv ID
      const arxivMatch = arxivUrl.url.match(/arxiv\.org\/abs\/(.+)/)
      if (arxivMatch) {
        lines.push(`  eprint = {${arxivMatch[1]}},`)
        lines.push(`  archiveprefix = {arXiv},`)
      }
    } else if (ref.cited_url) {
      lines.push(`  url = {${ref.cited_url}},`)
    }
  }
  
  lines.push('}')
  
  return lines.join('\n')
}

/**
 * Export all references as BibTeX
 * @param {object} params - Export parameters
 * @returns {string} BibTeX formatted entries
 */
export function exportResultsAsBibtex({ references }) {
  if (!references || references.length === 0) {
    return '% No references found'
  }
  
  const entries = references.map((ref, index) => exportReferenceAsBibtex(ref, index))
  return entries.join('\n\n')
}

/**
 * Export a single reference as plain text (ACM format)
 * Uses corrected values from verification when available
 * Format: Authors. Year. Title. Venue. URL
 * @param {object} ref - Reference object
 * @returns {string} Plain text citation
 */
export function exportReferenceAsPlainText(ref) {
  // Get corrected data (uses actual values from errors/warnings)
  const corrected = getCorrectedReferenceData(ref)
  const parts = []
  
  // Authors (required or placeholder)
  if (corrected.authors?.length > 0) {
    parts.push(formatAuthors(corrected.authors))
  }
  
  // Year
  if (corrected.year) {
    parts.push(corrected.year)
  }
  
  // Title (required)
  if (corrected.title) {
    parts.push(corrected.title)
  }
  
  // Venue
  if (corrected.venue) {
    parts.push(corrected.venue)
  }
  
  // Build citation
  let citation = parts.join('. ')
  if (citation && !citation.endsWith('.')) {
    citation += '.'
  }
  
  // Add arXiv URL if suggested, otherwise use authoritative URL
  const url = corrected.arxivUrl || corrected.url
  if (url) {
    citation += ` ${url}`
  }
  
  return citation
}

/**
 * Export a single reference as Markdown with elements on separate lines
 * Uses corrected values from verification when available
 * @param {object} ref - Reference object
 * @returns {string} Markdown citation
 */
export function exportReferenceAsMarkdown(ref) {
  // Get corrected data (uses actual values from errors/warnings)
  const corrected = getCorrectedReferenceData(ref)
  const lines = []
  
  // Title (bold) - first line
  if (corrected.title) {
    lines.push(`**${corrected.title}**`)
  }
  
  // Authors
  if (corrected.authors?.length > 0) {
    lines.push(`**Authors:** ${formatAuthors(corrected.authors)}`)
  }
  
  // Venue (italic)
  if (corrected.venue) {
    lines.push(`**Venue:** *${corrected.venue}*`)
  }
  
  // Year
  if (corrected.year) {
    lines.push(`**Year:** ${corrected.year}`)
  }
  
  // Add arXiv URL if suggested, otherwise use authoritative URL
  const url = corrected.arxivUrl || corrected.url
  if (url) {
    lines.push(`**URL:** ${url}`)
  }
  
  return lines.join('\n')
}
