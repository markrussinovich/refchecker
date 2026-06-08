import { useState, useRef, useEffect, memo } from 'react'
import {
  formatAuthors,
  normalizeAuthors,
  exportReferenceAsMarkdown,
  exportReferenceAsPlainText,
  exportReferenceAsBibtex,
  exportReferenceAsStyle,
  CITATION_STYLE_DEFAULTS,
  copyToClipboard,
  displayReferenceValue,
} from '../../utils/formatters'
import {
  getEffectiveReferenceStatus,
  llmFoundMetadataMatchesCitation,
} from '../../utils/referenceStatus'
import { openExternal, isTauri } from '../../utils/tauriBridge'
import { fetchAuthorProfile } from '../../utils/api'
import { useStyleStore } from '../../stores/useStyleStore'
import { useDocViewerStore } from '../../stores/useDocViewerStore'
import {
  shouldSuppressVenueWarning,
  acronymFor,
  fullNameFor,
  styleAcceptsAbbreviatedVenue,
} from '../../utils/venueAbbreviations'
import ReferenceEnrichmentStrip from './ReferenceEnrichmentStrip'
import AdditionalInfoBar from './AdditionalInfoBar'

// Click handler that routes link clicks through Tauri's shell plugin when
// running inside the desktop app. Belt-and-braces alongside the global
// capture-phase handler in main.jsx — if the global one is somehow
// missed (e.g. by an earlier listener calling stopImmediatePropagation),
// the explicit onClick here still does the right thing.
const handleExternalClick = (url) => (e) => {
  if (!isTauri()) return // let the browser handle it normally
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
  e.preventDefault()
  openExternal(url)
}

const urlPattern = /https?:\/\/[^\s]+/g

function normalizeCitationMarkerText(value) {
  return String(value || '')
    .normalize('NFKC')
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/\s+/g, ' ')
    .replace(/\s*,\s*/g, ', ')
    .trim()
    .toLowerCase()
}

function findCitationMarkerRange(sentence, marker) {
  if (!sentence || !marker) return null
  const exactAt = sentence.indexOf(marker)
  if (exactAt >= 0) return { start: exactAt, end: exactAt + marker.length }

  const normalizedMarker = normalizeCitationMarkerText(marker)
  if (!normalizedMarker) return null
  const markerCore = normalizedMarker.replace(/^\s*[\[(]\s*/, '').replace(/\s*[\])]\s*$/, '')
  const normalizedCore = markerCore || normalizedMarker

  const candidates = []
  for (let start = 0; start < sentence.length; start += 1) {
    const ch = sentence[start]
    if (ch !== '(' && ch !== '[' && !/[A-Za-z]/.test(ch)) continue
    const windowEnd = Math.min(sentence.length, start + Math.max(marker.length + 24, 24))
    for (let end = start + 3; end <= windowEnd; end += 1) {
      const raw = sentence.slice(start, end)
      const normalized = normalizeCitationMarkerText(raw)
      if (normalized === normalizedMarker || normalized === normalizedCore || normalizeCitationMarkerText(raw.replace(/^\s*[\[(]\s*/, '').replace(/\s*[\])]\s*$/, '')) === normalizedCore) {
        candidates.push({ start, end, length: end - start })
      }
    }
  }

  if (!candidates.length) return null
  candidates.sort((a, b) => a.length - b.length || a.start - b.start)
  return { start: candidates[0].start, end: candidates[0].end }
}

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

// Render long text collapsed to 3 visible rows with a chevron toggle to the left
const COLLAPSE_LINES = 3
const LINE_HEIGHT_EM = 1.4

function CollapsibleText({ text }) {
  const [expanded, setExpanded] = useState(false)
  const [needsCollapse, setNeedsCollapse] = useState(false)
  const contentRef = useRef(null)
  const collapsedMaxHeight = `${COLLAPSE_LINES * LINE_HEIGHT_EM}em`

  useEffect(() => {
    if (contentRef.current) {
      const el = contentRef.current
      const lineH = parseFloat(getComputedStyle(el).lineHeight) || (parseFloat(getComputedStyle(el).fontSize) * LINE_HEIGHT_EM)
      setNeedsCollapse(el.scrollHeight > lineH * COLLAPSE_LINES + 2)
    }
  }, [text])

  if (!text) return null

  return (
    <div style={{ position: 'relative', minWidth: 0 }}>
      {needsCollapse && (
        <button
          onClick={() => setExpanded(e => !e)}
          title={expanded ? 'Collapse' : 'Expand'}
          onMouseEnter={e => {
            e.currentTarget.style.background = 'var(--color-bg-hover, #3a3a3a)'
            e.currentTarget.style.borderColor = 'var(--color-text-secondary, #aaa)'
            e.currentTarget.style.color = 'var(--color-text-primary, #eee)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = 'var(--color-bg-secondary, #2a2a2a)'
            e.currentTarget.style.borderColor = 'var(--color-border, #555)'
            e.currentTarget.style.color = 'var(--color-text-secondary, #aaa)'
          }}
          style={{
            position: 'absolute',
            left: '-28px',
            top: `calc(${COLLAPSE_LINES} * ${LINE_HEIGHT_EM}em - 22px)`,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '20px',
            height: '20px',
            border: '1px solid var(--color-border, #555)',
            borderRadius: '4px',
            background: 'var(--color-bg-secondary, #2a2a2a)',
            color: 'var(--color-text-secondary, #aaa)',
            cursor: 'pointer',
            padding: 0,
            fontSize: '12px',
            lineHeight: 1,
            zIndex: 1,
            transition: 'background 0.15s ease, border-color 0.15s ease, color 0.15s ease',
          }}
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 12 12"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{
              transform: expanded ? 'rotate(180deg)' : 'none',
              transition: 'transform 0.15s ease',
            }}
          >
            <polyline points="2,4 6,8 10,4" />
          </svg>
        </button>
      )}
      <span
        ref={contentRef}
        style={{
          display: 'block',
          lineHeight: `${LINE_HEIGHT_EM}em`,
          maxHeight: (!expanded && needsCollapse) ? collapsedMaxHeight : 'none',
          overflow: 'hidden',
        }}
      >
        {renderTextWithLinks(text)}
      </span>
    </div>
  )
}

/**
 * Individual reference card matching CLI output format
 */
const ReferenceCard = memo(function ReferenceCard({ reference, index, displayIndex, totalRefs: _totalRefs, isCheckComplete = false }) {
  // Always use the original index for consistent numbering, even when filtered
  const numberToShow = typeof index === 'number' ? index : (typeof displayIndex === 'number' ? displayIndex : 0)
  const assessment = reference.hallucination_assessment || {}
  const foundMetadataMatchesCitation = llmFoundMetadataMatchesCitation(reference)
  const status = getEffectiveReferenceStatus(reference, isCheckComplete)

  // Subscribe to the shared citation-style store so the card re-renders
  // when the user changes the style picker on the References tab.
  const activeFormat = useStyleStore(s => s.format)
  const activeStyleOptions = useStyleStore(s => s.styleOptions)

  // "View in document": ask the preview overlay to locate + highlight this
  // citation context on the native PDF page (same machinery as AI highlights).
  const requestCitation = useDocViewerStore(s => s.requestCitation)
  const viewContextInDoc = (ctx, i) => {
    // Locate the WHOLE referenced sentence (with its surrounding before/after
    // when present) and colour the highlight by this reference's check status,
    // and carry the ref id so the highlight can link back to it.
    const sentence = (ctx?.sentence || ctx?.text || '').trim()
    if (!sentence) return
    const text = [ctx?.before, sentence, ctx?.after].filter(Boolean).join(' ').trim() || sentence
    requestCitation({
      text,
      label: ctx?.marker || `Excerpt ${i + 1}`,
      status,
      refId: String(reference.id ?? numberToShow),
      refTitle: reference.title || '',
    })
  }

  // Scroll to + flash this card when a citation highlight links back to it
  // (the "hyperlink the highlighted text back to the reference" flow).
  const cardRef = useRef(null)
  useEffect(() => {
    const myId = String(reference.id ?? numberToShow)
    const onFocus = (e) => {
      if (String(e?.detail?.refId) !== myId) return
      const el = cardRef.current
      if (!el) return
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('rc-ref-flash')
      setTimeout(() => { try { el.classList.remove('rc-ref-flash') } catch { /* unmounted */ } }, 1700)
    }
    window.addEventListener('refchecker:focus-reference', onFocus)
    return () => window.removeEventListener('refchecker:focus-reference', onFocus)
  }, [reference.id, numberToShow])

  // Export menu state
  const [showExportMenu, setShowExportMenu] = useState(false)
  const exportMenuRef = useRef(null)

  // v0.7.67: per-card collapse state for the citation-context list.
  // Collapsed by default so cards stay compact even when a ref is cited
  // multiple times; expands inline on click. Persists nothing — every
  // tab switch or re-render starts collapsed again.
  const [contextOpen, setContextOpen] = useState(false)

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
      case 'hallucination': return 'var(--color-hallucination)'
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

    if (status === 'hallucination') {
      return (
        <span className="flex-shrink-0 inline-block" title="Likely hallucinated">
          <svg className={commonSize} viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--color-hallucination)" />
            <path d="M12 4v10M10 6l2-2 2 2" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="12" cy="17.5" r="1.2" fill="#fff" />
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
      case 'llm_verified': return 'Verified URL'
      case 'verified_url': return 'Verified URL'
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

  const hasLlmVerifiedUrl = foundMetadataMatchesCitation || reference.authoritative_urls?.some(urlObj => urlObj.type === 'llm_verified')

  const matchedDatabase = hasLlmVerifiedUrl
    ? 'LLM search'
    : reference.from_fuzzy_cache
      ? `Cache (fuzzy${reference.fuzzy_match_score ? ` · score ${reference.fuzzy_match_score}` : ''})`
      : reference.matched_database || (
        reference.status === 'verified' && reference.cited_url && !reference.authoritative_urls?.length
          ? 'Web page'
          : null
      )

  const displayUrls = hasLlmVerifiedUrl
    ? (reference.authoritative_urls || []).filter(urlObj => urlObj.type === 'llm_verified').concat(
      foundMetadataMatchesCitation && !(reference.authoritative_urls || []).some(urlObj => urlObj.type === 'llm_verified')
        ? [{ type: 'llm_verified', url: assessment.link }]
        : []
    )
    : reference.authoritative_urls?.length
      ? reference.authoritative_urls
    : reference.status === 'verified' && reference.cited_url
      ? [{ type: 'verified_url', url: reference.cited_url }]
      : []

  const recheckWarnings = (reference.errors || [])
    .filter(issue => issue.warning_type && !issue.error_type)
    .map(issue => ({
      ...issue,
      error_type: issue.warning_type,
      error_details: issue.warning_details || '',
    }))
  const baseDisplayWarnings = foundMetadataMatchesCitation
    ? []
    : (recheckWarnings.length > 0 ? recheckWarnings : (reference.warnings || []))
  // Style-aware venue suppression. When the active citation style
  // permits NLM-style abbreviated journal titles AND the cited venue
  // is a known abbreviation of the database venue, the venue warning
  // is a false positive. Suppression runs at render time, so flipping
  // the style dropdown re-evaluates instantly.
  const displayWarnings = baseDisplayWarnings.filter(w => {
    // Drop content-free warnings. A warning with no details, no cited/actual
    // values, and no usable type renders as a meaningless "Unknown mismatch"
    // on an otherwise cleanly-verified reference — that's the confusing badge
    // the user asked about. If it carries no information, don't show it.
    const details = w.error_details || w.warning_details
    const hasValues = w.cited_value != null || w.actual_value != null
    const rawType = (w.warning_type || w.error_type || '').toLowerCase()
    if (!details && !hasValues && (!rawType || rawType === 'unknown')) return false
    const t = rawType
    if (t !== 'venue') return true
    return !shouldSuppressVenueWarning({
      cited_value: reference.venue,
      actual_value: w.ref_venue_correct || w.actual_value,
      warning_details: w.warning_details || w.error_details,
    }, activeFormat)
  })
  const displayErrors = (reference.errors || [])
    .filter(issue => issue.error_type && issue.error_type !== 'unverified')
    .filter(() => !foundMetadataMatchesCitation)
    .filter(issue => {
      // Same style-aware suppression for errors typed as 'venue'.
      const t = (issue.error_type || '').toLowerCase()
      if (t !== 'venue') return true
      return !shouldSuppressVenueWarning({
        cited_value: reference.venue,
        actual_value: issue.ref_venue_correct || issue.actual_value,
        warning_details: issue.error_details,
      }, activeFormat)
    })
  const displayVenue = displayReferenceValue(reference.venue)
  const displayYear = displayReferenceValue(reference.year)

  return (
    <div
      ref={cardRef}
      className="py-4 border-b font-mono text-sm"
      style={{ borderColor: 'var(--color-border)', contentVisibility: 'auto', containIntrinsicSize: 'auto 120px' }}
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
              {(reference.is_inline_cited || (reference.citation_contexts?.length > 0)) && (() => {
                const inlineUses = reference.citation_count || reference.citation_contexts?.length || 0
                return (
                  <span
                    title={`Cited inline — mentioned ${inlineUses || 1}× in this paper's body text`}
                    className="inline-flex items-center gap-1 align-middle ml-1.5 px-1.5 py-0.5 rounded text-xs font-medium"
                    style={{ color: 'var(--color-accent, #3b82f6)', background: 'rgba(59,130,246,0.14)', verticalAlign: 'middle' }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                      <path d="M12 2a10 10 0 100 20 10 10 0 000-20zm-1.1 14.2l-3.6-3.6 1.4-1.4 2.2 2.2 4.9-4.9 1.4 1.4-6.3 6.3z" />
                    </svg>
                    Cited inline{inlineUses > 0 ? ` · ${inlineUses}×` : ''}
                  </span>
                )
              })()}
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

          {/* When a non-default citation style is picked, render the
              reference once in that style and hide the duplicated
              structured rows below. With Plain text (ACM) selected
              we fall through to the structured authors / venue / year
              / cited-url layout which is the original behaviour. */}
          {(() => {
            const stylePicked = activeFormat && activeFormat !== 'plaintext'
            if (!stylePicked) return null
            const styleDefaults = CITATION_STYLE_DEFAULTS[activeFormat] || {}
            const effectiveOpts = { ...styleDefaults, ...(activeStyleOptions || {}) }
            let rendered = ''
            try { rendered = exportReferenceAsStyle(reference, activeFormat, index, effectiveOpts) } catch { return null }
            if (!rendered) return null
            // In styled mode the structured VenueLine isn't rendered, so surface
            // the journal/venue details on hover of the preview block (user
            // request: "journal info on hover").
            const _v = reference.venue
            const _full = _v ? (reference.enrichment?.venue || fullNameFor(_v)) : null
            const _acr = _v ? acronymFor(_full || _v) : null
            const _vLower = String(_v || '').toLowerCase()
            const venueTitle = _v ? [
              `Journal / venue: ${_v}`,
              ...(_full && String(_full).toLowerCase() !== _vLower ? [`Full name: ${_full}`] : []),
              ...(_acr && String(_acr).toLowerCase() !== _vLower ? [`NLM abbreviation: ${_acr}`] : []),
            ].join('\n') : undefined
            return (
              <div
                className="mt-1 mb-1 px-2 py-1 rounded text-xs"
                title={venueTitle}
                style={{
                  background: 'var(--color-bg-tertiary)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-primary)',
                  fontFamily: activeFormat === 'bibtex' || activeFormat === 'bibitem' ? 'ui-monospace, monospace' : undefined,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {rendered}
              </div>
            )
          })()}

          {/* Structured rows — only shown when the style picker is on Plain
              text (ACM). With APA / IEEE / BibTeX / etc. picked, the
              styled preview block above already contains all this. */}
          {(activeFormat === 'plaintext' || !activeFormat) && (
            <>
              {/* Authors — per-name hover surfaces ORCID + OpenAlex
                  profile links when the enrichment payload has them.
                  Falls back to a plain comma-joined string when no
                  enrichment is available (extractor-only refs). */}
              {normalizeAuthors(reference.authors).length > 0 && (
                <AuthorsLine
                  authors={reference.authors}
                  enrichedAuthors={reference.enrichment?.authors}
                />
              )}

              {/* Venue — hover surfaces the journal/conference page on
                  OpenAlex when we have a source_id from enrichment.
                  Inline parenthetical shows the OTHER form (full name
                  if user cited acronym, or NLM acronym if user cited
                  full name AND the active style accepts abbrevs).
                  Re-evaluates when style changes. */}
              {displayVenue && displayVenue !== 0 && displayVenue !== '0' && (
                <VenueLine
                  venue={displayVenue}
                  fullVenue={reference.enrichment?.venue}
                  venueOpenalexId={reference.enrichment?.venue_id}
                  activeStyle={activeFormat}
                />
              )}

              {/* Year — with accessed date if it differs from the
                  published year (web-style references like "Accessed
                  2024-03-12; published 2018"). */}
              {displayYear && displayYear !== 0 && displayYear !== '0' && (
                <div
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  {displayYear}
                  {reference.accessed_date && String(reference.accessed_date).slice(0, 4) !== String(displayYear) && (
                    <span style={{ color: 'var(--color-text-muted)' }}>
                      {' '}· accessed {reference.accessed_date}
                    </span>
                  )}
                </div>
              )}

              {/* Cited URL */}
              {reference.cited_url && (
                <div>
                  <a
                    href={reference.cited_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline mobile-break-url"
                    style={{ color: 'var(--color-link)' }}
                  >
                    {reference.cited_url}
                  </a>
                </div>
              )}
            </>
          )}

          {/* Divider before verification results */}
          {(displayUrls.length > 0 ||
            displayErrors.length > 0 ||
            displayWarnings.length > 0 ||
            reference.status === 'unverified') && (
            <div className="my-3 flex items-center gap-3">
              <span className="text-xs uppercase tracking-wide font-medium" style={{ color: 'var(--color-text-muted)' }}>
                Verification
              </span>
              <div className="flex-1 border-t" style={{ borderColor: 'var(--color-border)' }} />
            </div>
          )}

          {matchedDatabase && (
            <div className="flex mb-1">
              <span
                className="flex-shrink-0"
                style={{ color: 'var(--color-text-secondary)', width: '120px' }}
              >
                Matched DB:
              </span>
              <span style={{ color: 'var(--color-text)' }}>
                {matchedDatabase}
              </span>
            </div>
          )}

          {/* Citation context — the actual passage(s) in the paper body
              where this reference is cited. v0.7.67: collapsed by
              default behind a `▶ Context (N×)` toggle, then renders one
              SEPARATE box per occurrence (up to 3) with the citation
              marker highlighted so the user can spot misattributions at
              a glance. Falls back to the legacy single-string
              `citation_context` field when the backend hasn't populated
              the new array yet. */}
          {(reference.citation_contexts?.length > 0 || reference.citation_context) && (
            <div className="flex mb-1" style={{ minWidth: 0 }}>
              <span
                className="flex-shrink-0"
                style={{ color: 'var(--color-text-secondary)', width: '120px' }}
              >
                {/* Toggle row — header label + arrow indicator. Whole
                    row is the click target so users can hit either the
                    arrow OR the label. Mimics the native <details>
                    affordance without relying on browser styling. */}
                <button
                  type="button"
                  onClick={() => setContextOpen((v) => !v)}
                  aria-expanded={contextOpen}
                  title={contextOpen ? 'Hide citation contexts' : 'Show citation contexts'}
                  style={{
                    background: 'none',
                    border: 'none',
                    padding: 0,
                    margin: 0,
                    cursor: 'pointer',
                    color: 'var(--color-text-secondary)',
                    font: 'inherit',
                    textAlign: 'left',
                    width: '100%',
                  }}
                >
                  <span style={{ display: 'inline-block', width: '0.9em' }}>
                    {contextOpen ? '▼' : '▶'}
                  </span>
                  {' '}
                  {reference.citation_count > 1
                    ? `Context (${reference.citation_count}×)`
                    : 'Context'}
                </button>
              </span>
              <div
                style={{
                  flex: '1 1 auto',
                  minWidth: 0,
                  overflowWrap: 'anywhere',
                }}
              >
                {contextOpen && (
                  reference.citation_contexts?.length > 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {reference.citation_contexts.slice(0, 3).map((ctx, i) => {
                        // Split sentence at marker for inline bold
                        // without dangerouslySetInnerHTML.
                        const marker = ctx.marker || ''
                        const sent = ctx.sentence || ''
                        const markerRange = findCitationMarkerRange(sent, marker)
                        const markerAt = markerRange ? markerRange.start : -1
                        const markerEnd = markerRange ? markerRange.end : -1
                        const markerText = markerRange ? sent.slice(markerAt, markerEnd) : marker
                        const head = markerRange ? sent.slice(0, markerAt) : sent
                        const tail = markerRange ? sent.slice(markerEnd) : ''
                        return (
                          <div
                            key={i}
                            style={{
                              color: 'var(--color-text-primary)',
                              background: 'var(--color-bg-secondary)',
                              border: '1px solid var(--color-border, #d4d4d8)',
                              borderLeft: '3px solid var(--color-accent, #3b82f6)',
                              borderRadius: 6,
                              padding: '8px 10px',
                              boxShadow: '0 1px 0 rgba(0,0,0,0.03)',
                            }}
                            title="Sentence around the citation marker in the source paper"
                          >
                            <div
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 6,
                                marginBottom: 5,
                                color: 'var(--color-text-muted)',
                                fontSize: '0.72rem',
                                fontStyle: 'normal',
                                textTransform: 'uppercase',
                                letterSpacing: '0.04em',
                              }}
                            >
                              <span>Excerpt {i + 1}</span>
                              {marker && (
                                <span
                                  style={{
                                    color: 'var(--color-accent, #3b82f6)',
                                    background: 'var(--color-bg-tertiary)',
                                    border: '1px solid var(--color-border, #d4d4d8)',
                                    borderRadius: 999,
                                    padding: '0 6px',
                                    textTransform: 'none',
                                    letterSpacing: 0,
                                  }}
                                >
                                  {marker}
                                </span>
                              )}
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); viewContextInDoc(ctx, i) }}
                                title="Open this passage in the document and highlight it"
                                style={{
                                  marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4,
                                  background: 'none', border: '1px solid var(--color-border, #d4d4d8)',
                                  borderRadius: 999, padding: '1px 8px', cursor: 'pointer',
                                  color: 'var(--color-accent, #3b82f6)', textTransform: 'none', letterSpacing: 0,
                                }}
                              >
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 3h7v7" /><path d="M10 14L21 3" /><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" /></svg>
                                View in document
                              </button>
                            </div>
                            <div style={{ fontStyle: 'italic', lineHeight: 1.55 }}>
                              {ctx.before && (
                                <span style={{ color: 'var(--color-text-muted)' }}>
                                  {ctx.before}{' '}
                                </span>
                              )}
                              <span>
                                {head}
                              </span>
                              {markerRange && (
                                <span
                                  style={{
                                    fontStyle: 'normal',
                                    fontWeight: 700,
                                    color: 'var(--color-accent, #3b82f6)',
                                  }}
                                >
                                  {markerText}
                                </span>
                              )}
                              <span>{tail}</span>
                              {ctx.after && (
                                <span style={{ color: 'var(--color-text-muted)' }}>
                                  {' '}{ctx.after}
                                </span>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <span
                      style={{ color: 'var(--color-text)', fontStyle: 'italic' }}
                      title="Sentence around the citation marker in the source paper"
                    >
                      {reference.citation_context}
                    </span>
                  )
                )}
              </div>
            </div>
          )}

          {/* Authoritative URLs - deduplicate arxiv URLs (prefer abs over pdf) */}
          {(() => {
            const urls = displayUrls
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
              <div
                key={i}
                className="flex gap-2"
                style={{ minWidth: 0 }}
              >
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
                  onClick={handleExternalClick(urlObj.url)}
                  className="hover:underline"
                  style={{
                    color: 'var(--color-link)',
                    overflowWrap: 'anywhere',
                    wordBreak: 'break-all',
                    minWidth: 0,
                    flex: '1 1 auto',
                  }}
                >
                  {urlObj.url}
                </a>
              </div>
            ))
          })()}

          {/* Display-ready enrichment from OpenAlex / Crossref / S2 —
              cited-by count, refs count, OA, external IDs, FoS chips,
              per-author ORCID popover. Renders nothing when no
              enrichment data is available. */}
          <ReferenceEnrichmentStrip enrichment={reference.enrichment} />
          {/* Additional Info: abstract / claim / preprint / full text + Add to Library */}
          <AdditionalInfoBar reference={reference} checkId={reference.last_seen_check_id || null} />

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

          {/* Hallucination assessment */}
          {reference.hallucination_assessment?.verdict === 'LIKELY' && !foundMetadataMatchesCitation && (
            <div className="flex items-start gap-2 text-xs mt-1" style={{ color: 'var(--color-hallucination)' }}>
              <span className="flex-shrink-0 mt-0.5">🚩</span>
              <div>
                <div className="font-medium">Likely hallucinated</div>
                {reference.hallucination_assessment.explanation && (
                  <div>
                    {reference.hallucination_assessment.explanation}
                  </div>
                )}
                {reference.hallucination_assessment.link && (
                  <div className="mt-0.5">
                    <a href={reference.hallucination_assessment.link} target="_blank" rel="noopener noreferrer" className="underline" style={{ color: 'var(--color-hallucination)' }}>
                      {reference.hallucination_assessment.link}
                    </a>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Hallucination check pending indicator — shows when:
              1. Backend explicitly set hallucination_check_pending, OR
              2. Ref is unverified during an active check (LLM check hasn't started yet) */}
          {!reference.hallucination_assessment && (
            reference.hallucination_check_pending ||
            (status === 'checking' && reference.errors?.some(e => e.error_type === 'unverified'))
          ) && (
            <div className="flex items-center gap-2 text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
              <span>{reference.hallucination_check_pending ? 'Checking for hallucination with LLM...' : 'Awaiting LLM hallucination check...'}</span>
            </div>
          )}

          {/* Warnings */}
          {displayWarnings.map((warning, i) => {
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
            const baseText = (hasParsedCitedActual && typeof parsedDetails?.prefix === 'string')
              ? parsedDetails.prefix.replace(/:$/, '')
              : (warning.error_details || `${formatWarningType(warning.error_type)} mismatch`)

            const warningText = versionAnnotation && baseText && !baseText.includes(versionAnnotation)
              ? `${baseText} ${versionAnnotation}`
              : (baseText || '')

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
                    <CollapsibleText text={parsedDetails?.cited || warning.cited_value} />
                  </div>
                )}
                {(parsedDetails?.actual || warning.actual_value) && (
                  <div className="flex ml-6">
                    <span className="flex-shrink-0" style={{ width: '70px' }}><span className="font-bold">actual:</span></span>
                    <CollapsibleText text={parsedDetails?.actual || warning.actual_value} />
                  </div>
                )}
              </div>
            )
          })}

          {/* Errors (non-unverified) */}
          {displayErrors.map((error, i) => {
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
            const baseText = (hasParsedCitedActual && typeof parsedDetails?.prefix === 'string')
              ? parsedDetails.prefix
              : (error.error_details || error.error_type)

            const errorText = versionAnnotation && baseText && !baseText.includes(versionAnnotation)
              ? `${baseText} ${versionAnnotation}`
              : (baseText || '')
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
                    <CollapsibleText text={parsedDetails?.cited || error.cited_value} />
                  </div>
                )}
                {(parsedDetails?.actual || error.actual_value) && (
                  <div className="flex ml-6">
                    <span className="flex-shrink-0" style={{ width: '70px' }}><span className="font-bold">actual:</span></span>
                    <CollapsibleText text={parsedDetails?.actual || error.actual_value} />
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
}, (prevProps, nextProps) => {
  // Custom comparator: skip re-render if reference data hasn't changed
  if (prevProps.index !== nextProps.index) return false
  if (prevProps.displayIndex !== nextProps.displayIndex) return false
  if (prevProps.totalRefs !== nextProps.totalRefs) return false
  if (prevProps.isCheckComplete !== nextProps.isCheckComplete) return false
  const prev = prevProps.reference
  const next = nextProps.reference
  if (prev === next) return true
  if (!prev || !next) return false
  return (
    prev.status === next.status &&
    prev.title === next.title &&
    prev.authors === next.authors &&
    prev.year === next.year &&
    prev.venue === next.venue &&
    prev.hallucination_check_pending === next.hallucination_check_pending &&
    prev.hallucination_assessment === next.hallucination_assessment &&
    prev.errors === next.errors &&
    prev.warnings === next.warnings &&
    prev.suggestions === next.suggestions &&
    (prev.matched_database ?? null) === (next.matched_database ?? null) &&
    prev.authoritative_urls === next.authoritative_urls
  )
})

/**
 * Authors line with per-name hover. Matches each surface-string token
 * back to an enrichment record (by surname) so authors that have an
 * ORCID or OpenAlex profile in the OpenAlex/Crossref enrichment
 * payload get a clickable name; others render as plain text.
 *
 * Hover surfaces the author's profile link + first known affiliation.
 * Falls back gracefully when no enrichment was returned (e.g. the
 * ref verified via DBLP only and has no author IDs).
 */
function AuthorsLine({ authors, enrichedAuthors }) {
  const list = normalizeAuthors(authors)
  if (list.length === 0) return null

  // Normalise a name fragment: lowercase, strip diacritics, strip
  // punctuation. Matches "Bossuyt" / "Bössuyt" / "bossuyt," to one
  // canonical "bossuyt" so cited spellings + database spellings
  // match regardless of accents or trailing punctuation.
  const norm = (s) => {
    if (!s) return ''
    return String(s)
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')      // strip combining diacritics
      .toLowerCase()
      .replace(/[^a-z0-9\-' ]+/g, ' ')      // keep letters, digits, hyphens, apostrophes, spaces
      .replace(/\s+/g, ' ')
      .trim()
  }

  // Build a lookup table from surname → enrichment entry. Indexes by:
  //   - normalised full name ("per buchwald")
  //   - normalised surname ("buchwald")
  //   - first initial + surname ("p buchwald", "buchwald p")
  // so the cited "Buchwald P" (Vancouver) and "P. Buchwald" (APA) and
  // "Per Buchwald" (database canonical) all collapse to one entry.
  const enrichmentByKey = (() => {
    const m = new Map()
    const add = (k, v) => { if (k && !m.has(k)) m.set(k, v) }
    for (const a of (enrichedAuthors || [])) {
      const name = a && a.name ? String(a.name).trim() : ''
      if (!name) continue
      const lower = norm(name)
      const tokens = lower.split(/\s+/).filter(Boolean)
      if (tokens.length === 0) continue
      const surname = tokens[tokens.length - 1]
      const given = tokens.slice(0, -1)
      const initials = given.map(t => t.charAt(0)).filter(Boolean)
      add(lower, a)
      add(surname, a)
      // "buchwald p" / "p buchwald"
      for (const ini of initials) {
        add(`${surname} ${ini}`, a)
        add(`${ini} ${surname}`, a)
      }
      // Surname-first (Vancouver order in S2 data)
      if (tokens.length >= 2) {
        add(`${tokens[0]} ${tokens[tokens.length - 1]}`, a)
      }
    }
    return m
  })()

  const lookupEnrichment = (display) => {
    const lower = norm(display)
    if (!lower) return null
    if (enrichmentByKey.has(lower)) return enrichmentByKey.get(lower)
    const tokens = lower.split(/\s+/).filter(Boolean)
    // Try the longest token first (surnames are typically the longest
    // single token in "Buchwald P" or "P. Buchwald"). Then any single
    // token. Final pass: pairwise surname+initial combos.
    const sorted = [...tokens].sort((a, b) => b.length - a.length)
    for (const tok of sorted) {
      if (tok.length >= 2 && enrichmentByKey.has(tok)) return enrichmentByKey.get(tok)
    }
    for (let i = 0; i < tokens.length; i++) {
      for (let j = i + 1; j < tokens.length; j++) {
        const a = `${tokens[i]} ${tokens[j]}`
        if (enrichmentByKey.has(a)) return enrichmentByKey.get(a)
      }
    }
    return null
  }

  // Cap at 10 visible names; an overflow list is expandable to reveal ALL
  // authors (replaces the old static " et al.").
  const [showAll, setShowAll] = useState(false)
  const CAP = 10
  const overflow = list.length > CAP
  const visible = (showAll || !overflow) ? list : list.slice(0, CAP)
  return (
    <div style={{ color: 'var(--color-text-secondary)' }}>
      {visible.map((name, i) => {
        const e = lookupEnrichment(name)
        const profileHref = e?.orcid
          ? `https://orcid.org/${e.orcid}`
          : e?.openalex_id
            ? `https://openalex.org/${e.openalex_id}`
            : e?.s2_author_id
              ? `https://www.semanticscholar.org/author/${e.s2_author_id}`
              : null
        const tooltip = e
          ? [
              e.name && e.name !== name ? `Full name: ${e.name}` : null,
              e.orcid ? `ORCID: ${e.orcid}` : null,
              e.openalex_id ? `OpenAlex: ${e.openalex_id}` : null,
              !e.orcid && !e.openalex_id && e.s2_author_id ? `Semantic Scholar author: ${e.s2_author_id}` : null,
              Array.isArray(e.institutions) && e.institutions.length > 0
                ? `Affiliation: ${e.institutions.slice(0, 2).join(', ')}`
                : null,
              profileHref ? '(click to open profile)' : null,
            ].filter(Boolean).join('\n')
          : null
        const href = profileHref
        const handle = (ev) => {
          if (!href) return
          if (!isTauri()) return
          if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return
          ev.preventDefault()
          openExternal(href)
        }
        return (
          <span key={`${name}-${i}`}>
            <AuthorChip name={name} display={name} e={e} href={href} onClickHref={handle} tooltipFallback={tooltip} />
            {i < visible.length - 1 ? ', ' : ''}
          </span>
        )
      })}
      {overflow && !showAll && (
        <button type="button" onClick={() => setShowAll(true)}
          className="ml-1 underline" style={{ color: 'var(--color-accent)', fontSize: '0.85em' }}
          title="Show all authors">, +{list.length - CAP} more</button>
      )}
      {overflow && showAll && (
        <button type="button" onClick={() => setShowAll(false)}
          className="ml-1 underline" style={{ color: 'var(--color-accent)', fontSize: '0.85em' }}>show less</button>
      )}
    </div>
  )
}

/**
 * Single author chip with hover popover. Renders the name inline with
 * a dotted underline (matching the rest of the card), and on hover
 * pops up a small card with the author's full name, ORCID, OpenAlex
 * / Semantic Scholar author IDs, and first affiliation. Click opens
 * the profile link in the system browser.
 */
// Session-scoped cache of S2 author profiles so re-hovering the same author
// (common across a bibliography) never refetches.
const _authorProfileCache = new Map()

// Initials from a display name ("H.B. Guruprasad" -> "HG", "Jane Doe" -> "JD").
function _authorInitials(name) {
  const parts = String(name || '').replace(/[^A-Za-z\s.\-]/g, '').split(/[\s.\-]+/).filter(Boolean)
  if (!parts.length) return '?'
  const first = parts[0][0] || ''
  const last = parts.length > 1 ? (parts[parts.length - 1][0] || '') : ''
  return (first + last).toUpperCase() || '?'
}
// Deterministic avatar colour from the name (stable across renders, no PRNG).
function _authorColor(name) {
  const palette = ['#2563eb', '#7c3aed', '#0d9488', '#d97706', '#dc2626', '#0891b2', '#4f46e5', '#16a34a', '#db2777']
  let h = 0
  const s = String(name || '')
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return palette[h % palette.length]
}

function AuthorChip({ name, e, href, onClickHref, tooltipFallback }) {
  const [open, setOpen] = useState(false)
  const [profile, setProfile] = useState(() => _authorProfileCache.get(e?.s2_author_id) || null)
  const wrapperRef = useRef(null)
  const enterTimer = useRef(null)
  const leaveTimer = useRef(null)

  // Lazily pull the richer Semantic Scholar profile the first time the card
  // opens for an author that has an S2 id. Soft-fails to the basic card.
  const loadProfile = () => {
    const id = e?.s2_author_id
    if (!id || profile) return
    if (_authorProfileCache.has(id)) { setProfile(_authorProfileCache.get(id)); return }
    fetchAuthorProfile(id)
      .then(res => {
        const data = res?.data || { available: false }
        _authorProfileCache.set(id, data)
        setProfile(data)
      })
      .catch(() => { /* keep basic card */ })
  }

  // 250ms hover delay so brushing past names doesn't flash the popover.
  const onEnter = () => {
    if (leaveTimer.current) { clearTimeout(leaveTimer.current); leaveTimer.current = null }
    if (!e) return
    enterTimer.current = setTimeout(() => { setOpen(true); loadProfile() }, 250)
  }
  const onLeave = () => {
    if (enterTimer.current) { clearTimeout(enterTimer.current); enterTimer.current = null }
    leaveTimer.current = setTimeout(() => setOpen(false), 120)
  }
  useEffect(() => () => {
    if (enterTimer.current) clearTimeout(enterTimer.current)
    if (leaveTimer.current) clearTimeout(leaveTimer.current)
  }, [])

  const orcidUrl = e?.orcid ? `https://orcid.org/${e.orcid}` : null
  const openalexUrl = e?.openalex_id ? `https://openalex.org/${e.openalex_id}` : null
  const s2Url = e?.s2_author_id ? `https://www.semanticscholar.org/author/${e.s2_author_id}` : null

  return (
    <span
      ref={wrapperRef}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      style={{ position: 'relative', display: 'inline-block' }}
    >
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onClickHref}
          title={!e ? tooltipFallback : undefined}
          style={{
            color: 'var(--color-text-secondary)',
            textDecorationColor: 'var(--color-link, #3b82f6)',
            textDecorationStyle: 'dotted',
            textUnderlineOffset: '3px',
            textDecorationLine: 'underline',
          }}
        >
          {name}
        </a>
      ) : (
        <span title={tooltipFallback || undefined}>{name}</span>
      )}
      {open && e && (() => {
        const dispName = e.name || name
        const initials = _authorInitials(dispName)
        const avatarBg = _authorColor(dispName)
        const affs = (profile?.available && Array.isArray(profile.affiliations) && profile.affiliations.length)
          ? profile.affiliations
          : (Array.isArray(e.institutions) ? e.institutions : [])
        const hasMetrics = profile?.available && (profile.paperCount != null || profile.citationCount != null || profile.hIndex != null)
        const loading = !!e.s2_author_id && !profile
        const fmt = (n) => (typeof n === 'number' ? n.toLocaleString() : n)
        const chip = (label, val, title) => (
          <span title={title} className="inline-flex flex-col items-center px-2.5 py-1 rounded-lg"
            style={{ background: 'var(--color-bg-tertiary)', minWidth: 56 }}>
            <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-text-primary)' }}>{val}</span>
            <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>{label}</span>
          </span>
        )
        const profileLinks = [
          orcidUrl && { label: 'ORCID', url: orcidUrl },
          openalexUrl && { label: 'OpenAlex', url: openalexUrl },
          s2Url && { label: 'Semantic Scholar', url: s2Url },
        ].filter(Boolean)
        return (
        <div
          role="tooltip"
          className="rounded-xl text-xs overflow-hidden"
          style={{
            position: 'absolute', top: '100%', left: 0, marginTop: 8, zIndex: 60,
            minWidth: 300, maxWidth: 380,
            background: 'var(--color-bg-primary)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-primary)',
            boxShadow: '0 12px 40px rgba(0,0,0,0.28)',
            whiteSpace: 'normal',
          }}
        >
          {/* Header: avatar + name + affiliation */}
          <div className="flex items-start gap-2.5 px-3 pt-3 pb-2.5">
            <span className="flex-shrink-0 inline-flex items-center justify-center rounded-full"
              style={{ width: 36, height: 36, background: avatarBg, color: '#fff', fontWeight: 700, fontSize: 13 }}>
              {initials}
            </span>
            <div className="min-w-0">
              <div style={{ fontWeight: 600, lineHeight: 1.25 }}>{dispName}</div>
              {affs.length > 0 && (
                <div className="truncate" style={{ color: 'var(--color-text-muted)', fontSize: 11, marginTop: 1 }}>
                  {affs.slice(0, 2).join(' · ')}
                </div>
              )}
            </div>
          </div>

          {/* Metric chips */}
          {hasMetrics && (
            <div className="flex gap-1.5 px-3 pb-2.5">
              {profile.paperCount != null && chip('papers', fmt(profile.paperCount), 'Publications')}
              {profile.citationCount != null && chip('citations', fmt(profile.citationCount), 'Total citations')}
              {profile.hIndex != null && chip('h-index', profile.hIndex, 'h-index')}
            </div>
          )}

          {/* Recent papers */}
          {profile?.available && Array.isArray(profile.papers) && profile.papers.length > 0 && (
            <div className="px-3 pb-2.5">
              <div style={{ color: 'var(--color-text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>Recent work</div>
              <div className="space-y-1.5">
                {profile.papers.slice(0, 3).map((p, i) => (
                  <div key={i} className="leading-snug" style={{ color: 'var(--color-text-secondary)' }}>
                    {p.title}{p.year ? <span style={{ color: 'var(--color-text-muted)' }}> · {p.year}</span> : null}
                  </div>
                ))}
              </div>
            </div>
          )}

          {loading && (
            <div className="px-3 pb-2.5" style={{ color: 'var(--color-text-muted)' }}>Loading profile…</div>
          )}

          {/* Footer: profile links */}
          {(profileLinks.length > 0 || (profile?.available && profile.homepage)) && (
            <div className="flex items-center gap-2 flex-wrap px-3 py-2"
              style={{ borderTop: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}>
              {profile?.available && profile.homepage && (
                <a href={profile.homepage} target="_blank" rel="noopener noreferrer"
                  onClick={(ev) => { if (isTauri()) { ev.preventDefault(); openExternal(profile.homepage) } }}
                  className="px-2 py-0.5 rounded-md" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-accent)' }}>
                  Homepage
                </a>
              )}
              {profileLinks.map((pl) => (
                <a key={pl.label} href={pl.url} target="_blank" rel="noopener noreferrer"
                  onClick={(ev) => { if (isTauri()) { ev.preventDefault(); openExternal(pl.url) } }}
                  className="px-2 py-0.5 rounded-md" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-accent)' }}>
                  {pl.label}
                </a>
              ))}
            </div>
          )}
        </div>
        )
      })()}
    </span>
  )
}

function ProfileRow({ label, value, href }) {
  return (
    <div className="flex items-baseline gap-2 leading-snug">
      <span style={{ color: 'var(--color-text-muted)', minWidth: 64 }}>{label}:</span>
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(ev) => {
          if (!isTauri()) return
          if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return
          ev.preventDefault()
          openExternal(href)
        }}
        style={{
          color: 'var(--color-link, #3b82f6)',
          wordBreak: 'break-all',
        }}
      >
        {value}
      </a>
    </div>
  )
}

/**
 * Venue line with hover. Title attribute shows the full venue name
 * (when the cited string was an abbreviation like "ANZ J Surg" vs
 * OpenAlex's "ANZ journal of surgery") plus the OpenAlex source ID.
 * Click opens the OpenAlex venue page in the system browser.
 */
function VenueLine({ venue, fullVenue, venueOpenalexId, activeStyle }) {
  // Resolve the (full, acronym) pair so we can display both forms.
  // Priority for the FULL name: the OpenAlex-resolved string > the
  // reverse-lookup from the cited string (when only an acronym was
  // cited). Priority for the ACRONYM: NLM table forward lookup on
  // whichever full name we have.
  const resolvedFull = (() => {
    if (fullVenue && fullVenue !== venue) return fullVenue
    const reverse = fullNameFor(venue)
    return reverse && reverse.toLowerCase() !== String(venue).toLowerCase() ? reverse : null
  })()
  const resolvedAcronym = acronymFor(resolvedFull || venue) || acronymFor(venue)

  // Cited venue is the source-of-truth display. The supplemental form
  // (acronym OR full) shows in parens after, gated by whether the
  // ACTIVE STYLE accepts abbreviations: in Vancouver/AMA/IEEE/NLM the
  // acronym is the official form so we surface it alongside the full
  // name; in APA/MLA/Chicago we show the full name alongside an
  // acronym if the cited string was the abbrev.
  const styleAcceptsAbbrev = styleAcceptsAbbreviatedVenue(activeStyle)
  let supplemental = null
  // Pick the form the user DIDN'T cite. If the cited string already
  // matches resolvedFull, show the acronym; otherwise show the full.
  const venueNorm = String(venue || '').toLowerCase().trim()
  const fullNorm = String(resolvedFull || '').toLowerCase().trim()
  if (resolvedFull && venueNorm !== fullNorm) {
    supplemental = resolvedFull
  } else if (resolvedAcronym && resolvedAcronym.toLowerCase() !== venueNorm) {
    // Only show the acronym alongside the full name when the active
    // style would permit it (so APA refs don't get noisy with NLM
    // acronyms the user wouldn't use anyway).
    if (styleAcceptsAbbrev) supplemental = resolvedAcronym
  }

  // Always surface the journal/venue details on hover (parallels the per-author
  // hover) — the first line is the cited venue itself, so the tooltip is never
  // empty even when there's no enrichment (user request: "journal info on hover
  // like authors").
  const titleBits = [`Journal / venue: ${venue}`]
  if (resolvedFull && venueNorm !== fullNorm) titleBits.push(`Full name: ${resolvedFull}`)
  if (resolvedAcronym && resolvedAcronym.toLowerCase() !== venueNorm) titleBits.push(`NLM abbreviation: ${resolvedAcronym}`)
  if (venueOpenalexId) {
    titleBits.push(`OpenAlex source: ${venueOpenalexId}`)
    titleBits.push('(click to open venue page)')
  }
  const title = titleBits.join('\n')
  const href = venueOpenalexId ? `https://openalex.org/${venueOpenalexId}` : null
  const handle = (ev) => {
    if (!href || !isTauri()) return
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return
    ev.preventDefault()
    openExternal(href)
  }
  return (
    <div style={{ color: 'var(--color-text-secondary)' }} title={title}>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handle}
          style={{
            color: 'var(--color-text-secondary)',
            textDecorationColor: 'var(--color-link, #3b82f6)',
            textDecorationStyle: 'dotted',
            textUnderlineOffset: '3px',
            textDecorationLine: 'underline',
          }}
        >
          {venue}
        </a>
      ) : (
        <span>{venue}</span>
      )}
      {supplemental && (
        <span style={{ color: 'var(--color-text-muted)', marginLeft: 6 }}>
          ({supplemental})
        </span>
      )}
    </div>
  )
}

export default ReferenceCard
