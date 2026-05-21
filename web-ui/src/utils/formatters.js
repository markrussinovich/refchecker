/**
 * Formatting utilities
 */

/**
 * Format a date for display
 * @param {string|Date} date - Date to format
 * @returns {string} Formatted date string
 */
export function formatDate(date) {
  // Backend stores UTC timestamps without a timezone suffix (e.g. "2026-02-01 23:03:05").
  // Append 'Z' so the browser interprets them as UTC and displays in local time.
  let input = date
  if (typeof input === 'string' && !input.endsWith('Z') && !input.includes('+') && !input.includes('T')) {
    input = input.replace(' ', 'T') + 'Z'
  }
  const d = new Date(input)
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
/**
 * Render a single error/warning/suggestion object as a human string.
 *
 * Backend ships issues as `{error_type, error_details, actual_value, ...}`
 * objects. Naive `e.message || String(e)` falls through to `String(obj)`
 * which produces "[object Object]". Walk the known fields in priority
 * order; fall back to a safely stringified JSON last so we never render
 * literal `[object Object]`.
 */
export function formatIssueLine(issue) {
  if (!issue) return ''
  if (typeof issue === 'string') return issue
  if (typeof issue !== 'object') return String(issue)
  if (issue.message) return String(issue.message)
  if (issue.error_details) return String(issue.error_details)
  if (issue.detail) return String(issue.detail)
  if (issue.text) return String(issue.text)
  if (issue.error_type) {
    const t = String(issue.error_type)
    if (issue.actual_value !== undefined && issue.cited !== undefined) {
      return `${t}: cited '${issue.cited}', actual '${issue.actual_value}'`
    }
    if (issue.actual_value !== undefined) return `${t} → ${issue.actual_value}`
    return t
  }
  try { return JSON.stringify(issue) } catch { return '(unrenderable issue)' }
}

function getCorrectedReferenceData(ref) {
  // Verifier may attach typed URLs (doi, arxiv, journal) in
  // authoritative_urls. Surface them so the URL picker can prefer DOI
  // and arxiv over Semantic Scholar paper pages.
  const typedUrls = Array.isArray(ref.authoritative_urls) ? ref.authoritative_urls : []
  const doiFromUrls = typedUrls.find(u => u && u.type === 'doi')?.url
  const arxivFromUrls = typedUrls.find(u => u && u.type === 'arxiv')?.url
  const corrected = {
    title: ref.title,
    authors: ref.authors,
    year: ref.year,
    venue: ref.venue,
    doi: ref.doi || (doiFromUrls ? doiFromUrls.replace(/^https?:\/\/(dx\.)?doi\.org\//i, '') : null),
    arxivId: ref.arxiv_id || (arxivFromUrls ? arxivFromUrls.replace(/^https?:\/\/arxiv\.org\/abs\//i, '') : null),
    citedUrl: ref.cited_url || null,
    url: ref.authoritative_urls?.[0]?.url || ref.cited_url,
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
  lines.push(`| Likely Hallucinated | ${stats.hallucination_count ?? 0} |`)
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
        hallucination: '🚩',
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
        
        if (unverifiedError && (status === 'unverified' || status === 'hallucination')) {
          lines.push('')
          lines.push(`**Could not verify:** ${unverifiedError.error_details || 'Paper not found by any checker'}`)
        }
      }

      if (ref.hallucination_assessment?.verdict === 'LIKELY') {
        lines.push('')
        lines.push(`**Likely hallucinated:** ${ref.hallucination_assessment.explanation || 'Strong fabrication signals detected.'}`)
        if (ref.hallucination_assessment.link) {
          lines.push(`**Link:** ${ref.hallucination_assessment.link}`)
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
  lines.push(`Likely Hallucinated: ${stats.hallucination_count ?? 0}`)
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
      const unverifiedError = ref.errors?.find(e => e.error_type === 'unverified')
      if (unverifiedError && (status === 'UNVERIFIED' || status === 'HALLUCINATION')) {
        lines.push(`    Could not verify: ${unverifiedError.error_details || 'Paper not found by any checker'}`)
      }
      if (ref.hallucination_assessment?.verdict === 'LIKELY') {
        lines.push(`    HALLUCINATION: ${ref.hallucination_assessment.explanation || 'Strong fabrication signals detected.'}`)
        if (ref.hallucination_assessment.link) {
          lines.push(`    LINK: ${ref.hallucination_assessment.link}`)
        }
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
 * Flatten a reference into a single JSON record suitable for line-delimited
 * JSON or row-based CSV consumption. Matches the structured fields the CLI
 * --report-format json/jsonl produces so downstream consumers see the same
 * shape regardless of which path produced the report.
 */
function _flattenReferenceForReport(ref, index, paperTitle, paperSource) {
  const errors = (ref.errors || []).map(formatIssueLine)
  const warnings = (ref.warnings || []).map(formatIssueLine)
  return {
    index,
    paper_title: paperTitle || '',
    paper_source: paperSource || '',
    cited_title: ref.title || '',
    cited_authors: ref.authors || '',
    cited_year: ref.year || '',
    cited_venue: ref.venue || '',
    cited_doi: ref.doi || '',
    cited_arxiv_id: ref.arxiv_id || '',
    cited_url: ref.cited_url || '',
    matched_db: ref.matched_db || '',
    verified_url: ref.verified_url || '',
    status: ref.status || '',
    error_count: errors.length,
    warning_count: warnings.length,
    errors,
    warnings,
    hallucination_verdict: ref.hallucination_assessment?.verdict || '',
    hallucination_explanation: ref.hallucination_assessment?.explanation || '',
    hallucination_link: ref.hallucination_assessment?.link || '',
  }
}

export function exportResultsAsJsonl({ paperTitle, paperSource, references }) {
  if (!references || references.length === 0) return ''
  return references
    .map((ref, i) => JSON.stringify(_flattenReferenceForReport(ref, i + 1, paperTitle, paperSource)))
    .join('\n')
}

function _csvField(value) {
  if (value === null || value === undefined) return ''
  let s = Array.isArray(value) ? value.join(' | ') : String(value)
  if (/[,"\n]/.test(s)) {
    s = '"' + s.replace(/"/g, '""') + '"'
  }
  return s
}

export function exportResultsAsCsv({ paperTitle, paperSource, references }) {
  const columns = [
    'index', 'paper_title', 'paper_source',
    'cited_title', 'cited_authors', 'cited_year', 'cited_venue', 'cited_doi',
    'cited_arxiv_id', 'cited_url', 'matched_db', 'verified_url', 'status',
    'error_count', 'warning_count', 'errors', 'warnings',
    'hallucination_verdict', 'hallucination_explanation', 'hallucination_link',
  ]
  const header = columns.join(',')
  if (!references || references.length === 0) return header
  const rows = references.map((ref, i) => {
    const flat = _flattenReferenceForReport(ref, i + 1, paperTitle, paperSource)
    return columns.map(c => _csvField(flat[c])).join(',')
  })
  return [header, ...rows].join('\n')
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
  
  // Append a publishable URL: DOI > ArXiv > original cited URL. Skips
  // the Semantic Scholar / OpenAlex lookup URLs that show up in the
  // verifier's authoritative_urls field — those aren't valid citations.
  const url = _preferredCitationUrl(corrected)
  if (url) {
    citation += ` ${url}`
  }

  return citation
}

/**
 * Pick the URL that actually belongs in a published citation.
 *
 * Verifier-internal URLs (Semantic Scholar paper pages, OpenAlex API
 * endpoints) match RefChecker's lookup record but they're not what an
 * author would put in a bibliography. Prefer, in order:
 *   1. DOI URL              — canonical, used by every modern style
 *   2. ArXiv URL            — when the work is a preprint
 *   3. Original cited URL   — if the author already had a non-S2/non-OA URL
 *   4. Verifier URL         — fallback only
 *
 * Returns `null` when no useful URL exists, so style formatters can skip
 * the URL field entirely instead of emitting a junk Semantic Scholar link.
 */
function _preferredCitationUrl(corrected) {
  const looksInternal = (u) => {
    if (!u) return true
    const s = String(u).toLowerCase()
    return s.includes('semanticscholar.org/paper') ||
           s.includes('api.openalex.org') ||
           s.includes('openalex.org/works')
  }
  if (corrected.doi) {
    const doi = String(corrected.doi).replace(/^https?:\/\/(dx\.)?doi\.org\//i, '').trim()
    if (doi) return `https://doi.org/${doi}`
  }
  if (corrected.arxivUrl) return corrected.arxivUrl
  if (corrected.arxivId) return `https://arxiv.org/abs/${String(corrected.arxivId).replace(/^arxiv:/i, '').trim()}`
  if (corrected.citedUrl && !looksInternal(corrected.citedUrl)) return corrected.citedUrl
  if (corrected.url && !looksInternal(corrected.url)) return corrected.url
  return null
}

/* -------------------------------------------------------------------------
 * Citation-style formatters.
 *
 * Approximate, not pedantic. Goal: produce a string the user can paste into
 * their bibliography and tidy up by hand. Each style operates on the
 * corrected metadata (post-verification) so the output already incorporates
 * RefChecker's fixes.
 * -----------------------------------------------------------------------*/

function _splitAuthorName(rawName) {
  if (!rawName) return { first: '', last: '', initials: '' }
  const name = String(rawName).trim().replace(/\s+/g, ' ')
  // "Lastname, Firstname Middle" form
  if (name.includes(',')) {
    const [last, rest] = name.split(',', 2).map(s => s.trim())
    const givenParts = (rest || '').split(/\s+/).filter(Boolean)
    const initials = givenParts.map(p => p[0] ? p[0].toUpperCase() + '.' : '').join(' ')
    return { first: rest || '', last, initials }
  }
  // "Firstname Middle Lastname" form
  const parts = name.split(/\s+/)
  if (parts.length === 1) return { first: '', last: parts[0], initials: '' }
  const last = parts.pop()
  const first = parts.join(' ')
  const initials = parts.map(p => (p[0] || '').toUpperCase() + '.').join(' ')
  return { first, last, initials }
}

function _authorsArray(authors) {
  if (!authors) return []
  if (Array.isArray(authors)) return authors.filter(Boolean)
  // Some refs ship authors as a single comma-separated string.
  return String(authors).split(/,\s*(?:and\s+)?|;\s*|\s+and\s+/).map(s => s.trim()).filter(Boolean)
}

function _formatAuthorsAPA(authors) {
  const list = _authorsArray(authors).map(a => {
    const { last, initials } = _splitAuthorName(a)
    return last ? `${last}, ${initials}`.trim() : a
  })
  if (list.length === 0) return ''
  if (list.length === 1) return list[0]
  if (list.length === 2) return `${list[0]}, & ${list[1]}`
  if (list.length <= 20) return list.slice(0, -1).join(', ') + ', & ' + list.slice(-1)
  return list.slice(0, 19).join(', ') + ', ... ' + list[list.length - 1]
}

function _formatAuthorsMLA(authors) {
  const list = _authorsArray(authors)
  if (list.length === 0) return ''
  const first = (() => {
    const { first, last } = _splitAuthorName(list[0])
    return last ? `${last}, ${first}`.trim() : list[0]
  })()
  if (list.length === 1) return first
  if (list.length === 2) return `${first}, and ${list[1]}`
  return `${first}, et al`
}

function _formatAuthorsIEEE(authors) {
  const list = _authorsArray(authors).map(a => {
    const { last, initials } = _splitAuthorName(a)
    return last ? `${initials} ${last}`.trim() : a
  })
  if (list.length === 0) return ''
  if (list.length <= 6) return list.join(', ')
  return list.slice(0, 6).join(', ') + ', et al.'
}

function _formatAuthorsVancouver(authors) {
  const list = _authorsArray(authors).map(a => {
    const { last, initials } = _splitAuthorName(a)
    return last ? `${last} ${initials.replace(/\./g, '').replace(/\s+/g, '')}`.trim() : a
  })
  if (list.length === 0) return ''
  if (list.length <= 6) return list.join(', ')
  return list.slice(0, 6).join(', ') + ', et al.'
}

function _formatAuthorsChicago(authors) {
  const list = _authorsArray(authors)
  if (list.length === 0) return ''
  const first = (() => {
    const { first, last } = _splitAuthorName(list[0])
    return last ? `${last}, ${first}`.trim() : list[0]
  })()
  if (list.length === 1) return first
  if (list.length <= 10) return `${first}, ` + list.slice(1).join(', ')
  return `${first}, et al.`
}

/**
 * Citation styles supported by the Corrections tab.
 */
export const CITATION_STYLES = [
  { id: 'bibtex', label: 'BibTeX' },
  { id: 'plaintext', label: 'Plain text (ACM)' },
  { id: 'apa', label: 'APA 7th' },
  { id: 'mla', label: 'MLA 9th' },
  { id: 'chicago', label: 'Chicago author-date' },
  { id: 'ieee', label: 'IEEE' },
  { id: 'vancouver', label: 'Vancouver' },
  { id: 'bibitem', label: 'LaTeX \\bibitem' },
]

// Default options-per-style. Overridable per call via the `options` arg.
// `max_authors`: keep at most N authors, then add the et-al suffix.
// `et_al_threshold`: list size at which we even consider abbreviating.
// `include_url`: append the preferred URL when present.
export const CITATION_STYLE_DEFAULTS = {
  bibtex: { include_url: true, max_authors: null, et_al_threshold: null },
  plaintext: { include_url: true, max_authors: null, et_al_threshold: null },
  apa: { include_url: true, max_authors: 20, et_al_threshold: 21 },
  mla: { include_url: true, max_authors: 1, et_al_threshold: 3 },
  chicago: { include_url: true, max_authors: 1, et_al_threshold: 4 },
  ieee: { include_url: true, max_authors: 6, et_al_threshold: 7 },
  vancouver: { include_url: true, max_authors: 6, et_al_threshold: 7 },
  bibitem: { include_url: true, max_authors: 6, et_al_threshold: 7 },
}

const _CUSTOM_STYLES_KEY = 'refchecker:custom-citation-styles'

export function listCustomCitationStyles() {
  try {
    const raw = localStorage.getItem(_CUSTOM_STYLES_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch { return [] }
}

export function saveCustomCitationStyle(style) {
  if (!style || !style.id || !style.template) return
  const all = listCustomCitationStyles().filter(s => s.id !== style.id)
  all.push(style)
  try { localStorage.setItem(_CUSTOM_STYLES_KEY, JSON.stringify(all)) } catch {}
}

export function deleteCustomCitationStyle(id) {
  const all = listCustomCitationStyles().filter(s => s.id !== id)
  try { localStorage.setItem(_CUSTOM_STYLES_KEY, JSON.stringify(all)) } catch {}
}

// Truncate an author list to N entries with "et al." suffix when there
// are more than `threshold` (so we don't abbreviate 2 authors to "X et al.")
function _applyAuthorCap(formatted, authors, maxAuthors, etAlThreshold) {
  if (!Array.isArray(authors) || authors.length === 0) return formatted
  if (!maxAuthors || maxAuthors <= 0) return formatted
  if (etAlThreshold && authors.length < etAlThreshold) return formatted
  if (authors.length <= maxAuthors) return formatted
  // The formatter already produced something — replace the trailing tail
  // with the truncated form. We rebuild from scratch using the same
  // separator the source used (comma) since that's the lowest common
  // denominator across APA/IEEE/Vancouver/etc.
  const head = authors.slice(0, maxAuthors).join(', ')
  return `${head}, et al.`
}

// Render a user-defined template against a corrected ref. Supported
// placeholders: {authors}, {title}, {year}, {venue}, {doi}, {arxiv_id},
// {url}, {index}. Unknown placeholders are left intact.
function _renderCustomTemplate(template, corrected, index) {
  const url = _preferredCitationUrl(corrected) || ''
  const authors = Array.isArray(corrected.authors) ? corrected.authors.join(', ') : (corrected.authors || '')
  const map = {
    authors,
    title: corrected.title || '',
    year: corrected.year || '',
    venue: corrected.venue || '',
    doi: corrected.doi || '',
    arxiv_id: corrected.arxiv_id || '',
    url,
    index: String((index || 0) + 1),
  }
  return template.replace(/\{(\w+)\}/g, (m, k) => (k in map ? map[k] : m))
}

export function exportReferenceAsStyle(ref, style, index = 0, options = null) {
  const corrected = getCorrectedReferenceData(ref)
  // Custom styles use the `custom:<id>` namespace.
  if (style && style.startsWith('custom:')) {
    const id = style.slice('custom:'.length)
    const def = listCustomCitationStyles().find(s => s.id === id)
    if (def) {
      return _renderCustomTemplate(def.template, corrected, index)
    }
    return exportReferenceAsPlainText(ref)
  }

  // Merge per-call options on top of the per-style defaults.
  const opts = { ...(CITATION_STYLE_DEFAULTS[style] || {}), ...(options || {}) }
  const rawUrl = _preferredCitationUrl(corrected)
  const url = opts.include_url === false ? '' : rawUrl
  const venue = corrected.venue || ''
  const title = corrected.title || ''
  const year = corrected.year || ''
  const cap = (formatted) => _applyAuthorCap(formatted, corrected.authors, opts.max_authors, opts.et_al_threshold)

  switch (style) {
    case 'bibtex':
      return exportReferenceAsBibtex(ref, index)
    case 'plaintext':
      return exportReferenceAsPlainText(ref)
    case 'apa': {
      // Author, F. M. (Year). Title. Venue. URL
      const authors = cap(_formatAuthorsAPA(corrected.authors))
      const parts = []
      if (authors) parts.push(`${authors}${authors.endsWith('.') ? '' : '.'}`)
      if (year) parts.push(`(${year}).`)
      if (title) parts.push(`${title}${title.endsWith('.') ? '' : '.'}`)
      if (venue) parts.push(`${venue}.`)
      if (url) parts.push(url)
      return parts.join(' ')
    }
    case 'mla': {
      // Author. "Title." Venue, Year, URL.
      const authors = cap(_formatAuthorsMLA(corrected.authors))
      const parts = []
      if (authors) parts.push(`${authors}.`)
      if (title) parts.push(`"${title}."`)
      const tail = [venue, year].filter(Boolean).join(', ')
      if (tail) parts.push(`${tail}.`)
      if (url) parts.push(url)
      return parts.join(' ')
    }
    case 'chicago': {
      // Last, First, and Co Author. Year. "Title." Venue. URL.
      const authors = cap(_formatAuthorsChicago(corrected.authors))
      const parts = []
      if (authors) parts.push(`${authors}.`)
      if (year) parts.push(`${year}.`)
      if (title) parts.push(`"${title}."`)
      if (venue) parts.push(`${venue}.`)
      if (url) parts.push(url)
      return parts.join(' ')
    }
    case 'ieee': {
      // F. M. Last, "Title," Venue, Year. [Online]. Available: URL
      const authors = cap(_formatAuthorsIEEE(corrected.authors))
      const parts = []
      if (authors) parts.push(`${authors},`)
      if (title) parts.push(`"${title},"`)
      const tail = [venue, year].filter(Boolean).join(', ')
      if (tail) parts.push(`${tail}.`)
      if (url) parts.push(`[Online]. Available: ${url}`)
      return parts.join(' ')
    }
    case 'vancouver': {
      // Last FM, Co N. Title. Venue. Year. URL
      const authors = cap(_formatAuthorsVancouver(corrected.authors))
      const parts = []
      if (authors) parts.push(`${authors}.`)
      if (title) parts.push(`${title}.`)
      if (venue) parts.push(`${venue}.`)
      if (year) parts.push(`${year}.`)
      if (url) parts.push(`Available from: ${url}`)
      return parts.join(' ')
    }
    case 'bibitem': {
      // \bibitem{key} F. M. Last, "Title," Venue, Year.
      const key = (ref.bibtex_key || `ref${index + 1}`).replace(/[^A-Za-z0-9_-]/g, '')
      const authors = cap(_formatAuthorsIEEE(corrected.authors))
      const tail = [venue, year].filter(Boolean).join(', ')
      const body = [authors && `${authors},`, title && `"${title},"`, tail && `${tail}.`, url].filter(Boolean).join(' ')
      return `\\bibitem{${key}} ${body}`
    }
    default:
      return exportReferenceAsPlainText(ref)
  }
}

export function exportResultsAsStyle(references, style) {
  if (!references || references.length === 0) return ''
  if (style === 'bibtex') return exportResultsAsBibtex({ references })
  return references.map((r, i) => exportReferenceAsStyle(r, style, i)).join('\n\n')
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

// ── RIS / Zotero / Mendeley / EndNote / Rayyan import format ───────────
// RIS is the de-facto interchange format for reference managers. Every
// major tool (Zotero, EndNote, Mendeley, Rayyan, RefWorks, Papers, etc.)
// can import it directly via "File → Import" / drag-drop.

function _risTypeFor(ref) {
  const venue = (ref.venue || '').toLowerCase()
  if (ref.arxiv_id || venue.includes('arxiv')) return 'GEN'
  if (venue.includes('proceedings') || venue.includes('workshop') || venue.includes('conference')) return 'CPAPER'
  if (venue.includes('thesis') || venue.includes('dissertation')) return 'THES'
  if (venue.includes('book')) return 'BOOK'
  return 'JOUR'
}

function _risAuthorList(authors) {
  if (!authors) return []
  if (Array.isArray(authors)) return authors.filter(Boolean)
  return String(authors)
    .split(/\s+and\s+|;|,(?![\w\s]+\.\s*[A-Z])/i)
    .map(a => a.trim())
    .filter(Boolean)
}

export function exportReferenceAsRIS(ref, index = 0) {
  const corrected = getCorrectedReferenceData(ref)
  const type = _risTypeFor(corrected)
  const lines = [`TY  - ${type}`]
  if (corrected.title) lines.push(`TI  - ${corrected.title}`)
  for (const a of _risAuthorList(corrected.authors)) {
    lines.push(`AU  - ${a}`)
  }
  if (corrected.year) lines.push(`PY  - ${corrected.year}`)
  if (corrected.venue) lines.push(type === 'JOUR' ? `JO  - ${corrected.venue}` : `T2  - ${corrected.venue}`)
  if (corrected.doi) lines.push(`DO  - ${corrected.doi}`)
  if (corrected.arxiv_id) lines.push(`AN  - arXiv:${corrected.arxiv_id}`)
  const url = _preferredCitationUrl(corrected)
  if (url) lines.push(`UR  - ${url}`)
  // ID is what Rayyan/EndNote use for de-dup; index is a fine fallback
  lines.push(`ID  - ref-${index + 1}`)
  lines.push('ER  - ')
  return lines.join('\n')
}

export function exportResultsAsRIS({ references }) {
  if (!references || references.length === 0) return ''
  return references.map((r, i) => exportReferenceAsRIS(r, i)).join('\n\n') + '\n'
}

// ── Sort modes for any "export the bibliography" path ─────────────────

export const REFERENCE_SORT_MODES = [
  { id: 'citation', label: 'Citation order (as cited in paper)' },
  { id: 'alphabetical', label: 'Alphabetical (by first author)' },
  { id: 'year-desc', label: 'Year (newest first)' },
  { id: 'year-asc', label: 'Year (oldest first)' },
]

function _firstAuthorKey(ref) {
  const corrected = getCorrectedReferenceData(ref)
  const a = corrected.authors
  let first = ''
  if (Array.isArray(a)) first = a[0] || ''
  else if (typeof a === 'string') first = a.split(/,|;|\s+and\s+/i)[0] || ''
  // Pull the longest token (usually surname). Strip diacritics for sort.
  const parts = first.split(/\s+/).filter(Boolean)
  const surname = parts.length ? parts.reduce((acc, p) => (p.length > acc.length ? p : acc), '') : ''
  return surname.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
}

export function sortReferencesForExport(references, mode = 'citation') {
  const arr = (references || []).slice()
  switch (mode) {
    case 'alphabetical':
      return arr.sort((a, b) => {
        const ak = _firstAuthorKey(a)
        const bk = _firstAuthorKey(b)
        if (ak && bk && ak !== bk) return ak < bk ? -1 : 1
        if (ak && !bk) return -1
        if (!ak && bk) return 1
        return (a.index || 0) - (b.index || 0)
      })
    case 'year-desc':
      return arr.sort((a, b) => (Number(b.year || 0)) - (Number(a.year || 0)))
    case 'year-asc':
      return arr.sort((a, b) => (Number(a.year || 0)) - (Number(b.year || 0)))
    case 'citation':
    default:
      return arr.sort((a, b) => (a.index || 0) - (b.index || 0))
  }
}
