import { useState, useEffect, useRef } from 'react'
import { useCheckStore } from '../../stores/useCheckStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useDocViewerStore } from '../../stores/useDocViewerStore'
import { useShallow } from 'zustand/react/shallow'
import * as api from '../../utils/api'
import { logger } from '../../utils/logger'
import { useGesturePinchZoom } from '../../utils/useGesturePinchZoom'
import { VerticalZoomControls, FindBar } from '../common/ViewerControls'
import Button from '../common/Button'
import ShareModal from '../Modals/ShareModal'
import DocumentViewer from './DocumentViewer'

// API base URL for thumbnails - use empty string to use relative URLs via Vite proxy
const API_BASE = ''
const extractionValueStyle = { color: 'var(--color-text-secondary)', fontWeight: 600 }

/**
 * Multi-page scrollable preview overlay.
 *
 *   - Fetches `/api/preview/:id/page-count` once.
 *   - If count > 1, renders a vertical scroll column with one <img> per
 *     page lazily loaded from `/api/preview/:id/page/:n`.
 *   - If count is 0 (non-PDF source) or 1, falls back to the existing
 *     single-image preview so text/HTML/legacy checks still get a
 *     usable overlay.
 *   - Page jump strip: top-left chip "Page N / total" plus prev/next.
 */
// AI-band highlight fill (translucent) for native-page overlays.
const _BAND_HL = {
  high: 'rgba(239,68,68,0.30)', medium: 'rgba(245,158,11,0.30)', low: 'rgba(34,197,94,0.22)',
}

// R28: build the locatable spans handed to the native document viewer for the
// "view this citation in the document" flow.
//   - Span 0 is the cited sentence (focused + colored by `status`).
//   - When a reference title is known, span 1 is the reference-list ENTRY, and
//     span 0 carries `refEntryIndex: 1` so clicking the inline citation scrolls +
//     flashes that entry INSIDE the same PDF (hyperlinking to the reference list
//     in-document) rather than switching a React tab.
// Returns [] for no target so callers can render nothing without branching.
function buildCitationViewerSpans(citationTarget) {
  if (!citationTarget?.text) return []
  const hasRefTitle = !!citationTarget.refTitle
  const spans = [{
    quote: citationTarget.text,
    status: citationTarget.status,
    refId: citationTarget.refId,
    refTitle: citationTarget.refTitle,
    label: citationTarget.label,
    refEntryIndex: hasRefTitle ? 1 : undefined,
  }]
  if (hasRefTitle) {
    spans.push({
      quote: citationTarget.refTitle,
      refId: citationTarget.refId,
      refTitle: citationTarget.refTitle,
      label: 'Reference-list entry',
      kind: 'ref-entry',
    })
  }
  return spans
}

// The raster page-image overlay used for the full-page thumbnail/preview modal.
// It locates and highlights AI-flagged passages on the native pages and supports
// Find. The inline-citation → reference-list jump (R28/R29/R30) lives in the
// native pdf.js stack (DocumentViewer → NativePdfViewer), NOT here.
function ThumbnailOverlay({ checkId, previewUrl, thumbnailUrl, aiDetection, onClose }) {
  const [pageCount, setPageCount] = useState(null)
  const [activePage, setActivePage] = useState(0)
  const [highlights, setHighlights] = useState({}) // pageIndex -> [{rects,band,score,reason,key}]
  const [findHl, setFindHl] = useState({})         // pageIndex -> [rects] for the query
  const [hoverHl, setHoverHl] = useState(null)
  const [zoom, setZoom] = useState(1)
  const [findOpen, setFindOpen] = useState(false)
  const [findQuery, setFindQuery] = useState('')
  const [matches, setMatches] = useState([])     // [{page}], page 0-indexed
  const [currentMatch, setCurrentMatch] = useState(0)
  const docTextRef = useRef('')                  // extracted body text (for find)
  const findInputRef = useRef(null)
  const scrollRef = useRef(null)
  const pageRefs = useRef([])

  const ZOOM_MIN = 0.5, ZOOM_MAX = 3, ZOOM_STEP = 0.25
  const zoomIn = () => setZoom(z => Math.min(ZOOM_MAX, +(z + ZOOM_STEP).toFixed(2)))
  const zoomOut = () => setZoom(z => Math.max(ZOOM_MIN, +(z - ZOOM_STEP).toFixed(2)))
  // R31: trackpad/touch pinch-to-zoom on the per-ref overlay page image, via the
  // SAME shared hook the native DocumentViewer uses (ctrl+wheel + WebKit gesture
  // events, non-passive so the browser's own page zoom never engages).
  useGesturePinchZoom(scrollRef, setZoom, { min: ZOOM_MIN, max: ZOOM_MAX })
  // Image sizing: at 100% fit to viewport; when zoomed, grow past the
  // viewport and let the (now two-axis) scroll container pan.
  const imgStyle = zoom === 1
    ? { maxWidth: '95vw', maxHeight: '92vh', objectFit: 'contain' }
    : { width: `${Math.round(zoom * 90)}vw`, maxWidth: 'none', height: 'auto', objectFit: 'contain' }

  useEffect(() => {
    let cancelled = false
    setPageCount(null)
    setActivePage(0)
    if (!checkId || checkId === -1) return undefined
    ;(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/preview/${checkId}/page-count`, {
          credentials: 'include',
        })
        if (cancelled) return
        if (!res.ok) { setPageCount(0); return }
        const data = await res.json()
        setPageCount(Number(data?.count || 0))
      } catch {
        if (!cancelled) setPageCount(0)
      }
    })()
    return () => { cancelled = true }
  }, [checkId])

  // Locate AI-flagged passages on the native pages (PyMuPDF search -> rects),
  // so we can overlay real highlights on the page images with hover AI data.
  useEffect(() => {
    let alive = true
    setHighlights({})
    const spans = Array.isArray(aiDetection?.spans) ? aiDetection.spans : []
    if (!checkId || checkId === -1 || !pageCount || spans.length === 0) return undefined
    const band = aiDetection?.band
    const targets = spans
      .filter((s) => s && s.quote)
      .map((s, i) => ({ text: s.quote, span_index: i, span_type: 'ai', band, model_score: s.model_score, reason: s.reason }))
    if (!targets.length) return undefined
    api.locatePdfSpans(checkId, targets)
      .then((res) => {
        if (!alive) return
        const byPage = {}
        for (const r of (res.data?.results || [])) {
          if (!r.found) continue
          ;(byPage[r.page] = byPage[r.page] || []).push({
            rects: r.rects, band: r.band, score: r.model_score, reason: r.reason,
            key: `ai-${r.span_index}`,
          })
        }
        setHighlights(byPage)
      })
      .catch(() => {})
    return () => { alive = false }
  }, [checkId, pageCount, aiDetection])

  // Fetch the extracted body text once so Find can locate words. The pages are
  // rasterized images (no text layer), so we search the extracted text and jump
  // to the estimated page rather than highlight on the image.
  useEffect(() => {
    let alive = true
    docTextRef.current = ''
    if (!checkId || checkId === -1) return undefined
    fetch(`${API_BASE}/api/paper-text/${checkId}`, { credentials: 'include' })
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (alive && d && d.available !== false) docTextRef.current = d.text || '' })
      .catch(() => {})
    return () => { alive = false }
  }, [checkId])

  // Recompute matches when the query changes. Estimate each match's page from
  // its character offset (chars are roughly evenly distributed across pages).
  useEffect(() => {
    const q = (findQuery || '').trim().toLowerCase()
    const text = docTextRef.current
    if (q.length < 2 || !text) { setMatches([]); setCurrentMatch(0); return }
    const lower = text.toLowerCase()
    const pages = Math.max(1, pageCount || 1)
    const out = []
    let i = 0
    while ((i = lower.indexOf(q, i)) !== -1 && out.length < 2000) {
      out.push({ page: Math.min(pages - 1, Math.floor((i / lower.length) * pages)) })
      i += q.length
    }
    setMatches(out)
    setCurrentMatch(0)
  }, [findQuery, pageCount])

  // Declared before the effects below that reference it (React Compiler flags
  // use-before-declare even when the call only happens inside an async closure).
  const jumpToPage = (n) => {
    const el = pageRefs.current[n]
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  // Show WHERE the query is on the page (not just which page): locate it on the
  // native pages via PyMuPDF search and highlight the rects (debounced).
  useEffect(() => {
    const q = (findQuery || '').trim()
    setFindHl({})
    if (!checkId || checkId === -1 || !pageCount || q.length < 3) return undefined
    let alive = true
    const t = setTimeout(() => {
      api.locatePdfSpans(checkId, [{ text: q, span_index: 0, span_type: 'find' }])
        .then((res) => {
          if (!alive) return
          const byPage = {}
          let firstPage = null
          for (const r of (res.data?.results || [])) {
            if (r.found && Array.isArray(r.rects)) {
              if (firstPage === null) firstPage = r.page
              byPage[r.page] = (byPage[r.page] || []).concat(r.rects)
            }
          }
          setFindHl(byPage)
          if (firstPage !== null) setTimeout(() => jumpToPage(firstPage), 60)
        })
        .catch(() => { /* find-highlight is best-effort; ignore lookup errors */ })
    }, 350)
    return () => { alive = false; clearTimeout(t) }
  }, [findQuery, checkId, pageCount])

  // Track which page is centered in the viewport so the "Page N / total"
  // chip updates as the user scrolls. Uses IntersectionObserver for
  // O(1) per scroll-tick rather than scroll-position math.
  useEffect(() => {
    if (!pageCount || pageCount <= 1 || !scrollRef.current) return undefined
    const observer = new IntersectionObserver(
      (entries) => {
        // Pick the entry with the largest intersectionRatio.
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (visible) {
          const idx = Number(visible.target.dataset.pageIndex)
          if (!Number.isNaN(idx)) setActivePage(idx)
        }
      },
      { root: scrollRef.current, threshold: [0.25, 0.5, 0.75] },
    )
    pageRefs.current.forEach((el) => el && observer.observe(el))
    return () => observer.disconnect()
  }, [pageCount])

  const gotoFind = (dir) => {
    if (!matches.length) return
    const next = (currentMatch + dir + matches.length) % matches.length
    setCurrentMatch(next)
    jumpToPage(matches[next].page)
  }
  const openFind = () => { setFindOpen(true); setTimeout(() => findInputRef.current?.focus(), 0) }

  // Close on Esc — the parent already wires this for the legacy single
  // image case, but the multi-page list is its own component so it
  // needs its own listener.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'f' || e.key === 'F')) { e.preventDefault(); openFind(); return }
      if (e.key === 'Escape') { if (findOpen) { setFindOpen(false); setFindQuery('') } else onClose() }
      else if (e.key === '+' || e.key === '=') { zoomIn() }
      else if (e.key === '-' || e.key === '_') { zoomOut() }
      else if (e.key === '0') { setZoom(1) }
      else if (e.key === 'ArrowDown' || e.key === 'PageDown') {
        if (pageCount > 1) jumpToPage(Math.min(activePage + 1, pageCount - 1))
      } else if (e.key === 'ArrowUp' || e.key === 'PageUp') {
        if (pageCount > 1) jumpToPage(Math.max(activePage - 1, 0))
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [activePage, pageCount, findOpen]) // eslint-disable-line react-hooks/exhaustive-deps

  const multiPage = pageCount && pageCount > 1

  return (
    <div
      className="fixed inset-0 z-50"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.9)' }}
      onClick={onClose}
    >
      {/* Close button */}
      <button
        type="button"
        onClick={onClose}
        className="absolute top-4 right-4 w-10 h-10 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors z-20"
        title="Close (Esc)"
      >
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>

      {/* Page indicator + navigation (only when multi-page) */}
      {multiPage && (
        <div
          className="absolute top-4 left-4 z-20 flex items-center gap-2 px-3 py-1.5 rounded-full text-sm text-white"
          style={{ background: 'rgba(255,255,255,0.12)' }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => jumpToPage(Math.max(activePage - 1, 0))}
            disabled={activePage <= 0}
            className="w-7 h-7 rounded-full hover:bg-white/15 disabled:opacity-30 flex items-center justify-center"
            title="Previous page"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <span>Page {activePage + 1} / {pageCount}</span>
          <button
            type="button"
            onClick={() => jumpToPage(Math.min(activePage + 1, pageCount - 1))}
            disabled={activePage >= pageCount - 1}
            className="w-7 h-7 rounded-full hover:bg-white/15 disabled:opacity-30 flex items-center justify-center"
            title="Next page"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>
      )}

      {/* Zoom controls — vertical, on the right edge (out of the way). */}
      <div
        className="absolute right-4 top-1/2 z-20 flex flex-col gap-2 p-1.5 rounded-xl"
        style={{ transform: 'translateY(-50%)', background: 'rgba(255,255,255,0.10)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <VerticalZoomControls
          zoom={zoom}
          onZoomIn={zoomIn}
          onZoomOut={zoomOut}
          onReset={() => setZoom(1)}
          min={ZOOM_MIN}
          max={ZOOM_MAX}
          dark
        />
      </div>

      {/* Find bar (top-center) — searches the extracted text and jumps to the
          estimated page (images have no text layer, so no in-image highlight). */}
      {findOpen ? (
        <div className="absolute top-4 left-1/2 z-30" style={{ transform: 'translateX(-50%)' }} onClick={(e) => e.stopPropagation()}>
          <FindBar
            value={findQuery}
            onChange={setFindQuery}
            matchCount={matches.length}
            currentMatch={currentMatch}
            onPrev={() => gotoFind(-1)}
            onNext={() => gotoFind(1)}
            onClose={() => { setFindOpen(false); setFindQuery('') }}
            inputRef={findInputRef}
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); openFind() }}
          className="absolute top-4 right-20 z-20 px-2.5 py-1 rounded-full text-xs text-white flex items-center gap-1.5"
          style={{ background: 'rgba(255,255,255,0.12)' }}
          title="Find in document (⌘F / Ctrl+F)"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
          Find
        </button>
      )}

      {/* Pages */}
      <div
        ref={scrollRef}
        className={`w-full h-full ${zoom > 1 ? 'overflow-auto' : 'overflow-y-auto'}`}
        style={{ scrollBehavior: 'smooth' }}
        onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
      >
        {multiPage ? (
          <div
            className="flex flex-col items-center gap-3 py-8 px-4"
            onClick={(e) => e.stopPropagation()}
          >
            {Array.from({ length: pageCount }, (_, i) => (
              <div key={i} ref={(el) => { pageRefs.current[i] = el }} data-page-index={i}
                style={{ position: 'relative', ...imgStyle, height: 'auto', lineHeight: 0 }}>
                <img
                  src={`${API_BASE}/api/preview/${checkId}/page/${i}`}
                  alt={`Page ${i + 1} of ${pageCount}`}
                  loading="lazy"
                  style={{ display: 'block', width: '100%', height: 'auto' }}
                  className="rounded-lg shadow-2xl bg-white"
                />
                {/* Native-page AI highlight overlay (normalized rects -> %). */}
                {(highlights[i] || []).flatMap((hl) =>
                  (hl.rects || []).map(([x0, y0, x1, y1], ri) => (
                    <div
                      key={`${hl.key}-${ri}`}
                      onMouseEnter={() => setHoverHl(hl)}
                      onMouseLeave={() => setHoverHl((h) => (h === hl ? null : h))}
                      title="AI-flagged passage"
                      style={{
                        position: 'absolute', left: `${x0 * 100}%`, top: `${y0 * 100}%`,
                        width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%`,
                        background: _BAND_HL[(hl.band || '').toLowerCase()] || _BAND_HL.medium,
                        borderRadius: 2, cursor: 'help', mixBlendMode: 'multiply',
                      }}
                    >
                      {hoverHl === hl && ri === 0 && (
                        <div style={{
                          // R30: fully opaque so the banner is always legible over
                          // any underlying page content.
                          position: 'absolute', bottom: '100%', left: 0, marginBottom: 4, zIndex: 30,
                          background: 'rgb(17,24,39)', color: '#fff', fontSize: 11,
                          padding: '6px 8px', borderRadius: 6, width: 240, lineHeight: 1.4,
                          pointerEvents: 'none', boxShadow: '0 6px 20px rgba(0,0,0,0.4)',
                        }}>
                          <strong style={{ color: '#fca5a5' }}>AI-likelihood: {hl.band || 'flagged'}</strong>
                          {typeof hl.score === 'number' ? ` · ${Math.round(hl.score * 100)}` : ''}
                          {hl.reason ? <div style={{ color: '#cbd5e1', marginTop: 2 }}>{hl.reason}</div> : null}
                        </div>
                      )}
                    </div>
                  ))
                )}
                {/* Find-query highlight overlay (yellow) — shows where it is. */}
                {(findHl[i] || []).map(([x0, y0, x1, y1], ri) => (
                  <div key={`find-${ri}`} title="Search match"
                    style={{
                      position: 'absolute', left: `${x0 * 100}%`, top: `${y0 * 100}%`,
                      width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%`,
                      background: 'rgba(250,204,21,0.45)', borderRadius: 2,
                      mixBlendMode: 'multiply', boxShadow: '0 0 0 1px rgba(202,138,4,0.7)',
                    }} />
                ))}
              </div>
            ))}
          </div>
        ) : (
          // Single-image fallback (text checks, page-count probe failed)
          <div
            className="w-full h-full flex items-center justify-center p-8"
            onClick={(e) => e.stopPropagation()}
          >
            <img
              src={previewUrl || thumbnailUrl}
              alt="Paper preview"
              style={imgStyle}
              className="rounded-lg shadow-2xl"
              onError={(e) => {
                if (previewUrl && thumbnailUrl && e.target.src !== thumbnailUrl) {
                  e.target.src = thumbnailUrl
                }
              }}
            />
          </div>
        )}
      </div>
    </div>
  )
}

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
function formatSource(source, title, sourceType, checkId, originalFilename) {
  if (!source) return null
  
  // For pasted text, don't show the temp file path - we'll show extraction method as source instead
  if (sourceType === 'text') {
    return null
  }
  
  // For file uploads, show the original filename
  if (sourceType === 'file' && checkId) {
    // Use original_filename if available, otherwise try to extract from title
    const displayName = originalFilename || title
    if (displayName) {
      return { 
        type: 'file', 
        value: `${API_BASE}/api/file/${checkId}`, 
        display: displayName,
        checkId: checkId
      }
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
  
  // If it's a URL, show it as a link styled like an inline reference —
  // prefer the document title, then a short citation-style label
  // ("arxiv.org/abs/2310.02238"), avoiding the raw protocol + querystring.
  const friendlyUrlLabel = (u) => {
    try {
      const parsed = new URL(u)
      const host = parsed.hostname.replace(/^www\./, '')
      const path = parsed.pathname.replace(/\/$/, '')
      const tail = path ? path : ''
      const label = `${host}${tail}`
      // Keep things compact: trim long paths but keep the last segment.
      if (label.length > 60) {
        const segs = label.split('/').filter(Boolean)
        return segs.length > 2
          ? `${segs[0]}/…/${segs[segs.length - 1]}`
          : label.slice(0, 57) + '…'
      }
      return label
    } catch {
      return u
    }
  }

  if (source.startsWith('http://') || source.startsWith('https://')) {
    return { type: 'url', value: source, display: title || friendlyUrlLabel(source) }
  }
  // ArXiv IDs - show as "arXiv:<id>" style
  const arxivMatch = source.match(/^(?:arXiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)$/i)
  if (arxivMatch) {
    const fullUrl = `https://arxiv.org/abs/${arxivMatch[1]}`
    return { type: 'url', value: fullUrl, display: title || `arXiv:${arxivMatch[1]}` }
  }
  // Filename or other
  return { type: 'text', value: source, display: source }
}

function renderSourceMethodLine({
  sourceKind,
  sourceType,
  checkId,
  displaySource,
}) {
  if (!sourceKind) return null

  const lowerKind = sourceKind.toLowerCase()
  const bibliographyLink = checkId ? `${API_BASE}/api/bibliography/${checkId}` : null

  if (['bbl', 'bib'].includes(lowerKind)) {
    let labelPrefix = 'ArXiv'
    if (sourceType === 'text') {
      labelPrefix = 'Pasted'
    } else if (sourceType === 'file') {
      labelPrefix = 'Uploaded'
    }
    const label = `${labelPrefix} .${lowerKind} file`
    return (
      <p 
        className="text-sm"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Extraction:{' '}
        {bibliographyLink ? (
          <a 
            href={bibliographyLink}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline"
            style={extractionValueStyle}
            onClick={(e) => e.stopPropagation()}
          >
            {label}
          </a>
        ) : (
          <span style={extractionValueStyle}>{label}</span>
        )}
      </p>
    )
  }

  if (lowerKind === 'pdf') {
    return (
      <p 
        className="text-sm"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Extraction: <span style={extractionValueStyle}>PDF extraction</span>
      </p>
    )
  }

  if (lowerKind === 'grobid') {
    return (
      <p 
        className="text-sm"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Extraction: <span style={extractionValueStyle}>GROBID fallback</span>
      </p>
    )
  }

  if (lowerKind === 'llm') {
    return (
      <p 
        className="text-sm"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Extraction: <span style={extractionValueStyle}>LLM extraction</span>
      </p>
    )
  }

  if (lowerKind === 'text' && checkId) {
    return (
      <p 
        className="text-sm"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Extraction:{' '}
        <a 
          href={`${API_BASE}/api/text/${checkId}`}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:underline"
          style={extractionValueStyle}
          onClick={(e) => e.stopPropagation()}
        >
          Pasted text
        </a>
      </p>
    )
  }

  if (lowerKind === 'cache' && displaySource) {
    return (
      <p 
        className="text-sm"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Extraction: <span style={extractionValueStyle}>Cached bibliography</span>
      </p>
    )
  }

  return null
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
    aiDetection: checkStoreAiDetection,
    cancelCheck: storeCancelCheck,
    setError,
  } = useCheckStore(useShallow(s => ({
    status: s.status,
    statusMessage: s.statusMessage,
    progress: s.progress,
    paperTitle: s.paperTitle,
    paperSource: s.paperSource,
    sourceType: s.sourceType,
    currentCheckId: s.currentCheckId,
    sessionId: s.sessionId,
    stats: s.stats,
    aiDetection: s.aiDetection,
    cancelCheck: s.cancelCheck,
    setError: s.setError,
  })))
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
  let displayProcessedRefs
  let displayLlmProvider = null
  let displayLlmModel = null
  let displayHallucinationProvider = null
  let displayHallucinationModel = null
  let displayExtractionMethod = null
  let displayBibliographySourceKind = null
  let displayOriginalFilename = null
  
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
    // Get LLM info and extraction method from selectedCheck (history) since it's not in checkStore
    displayLlmProvider = selectedCheck?.llm_provider
    displayLlmModel = selectedCheck?.llm_model
    displayHallucinationProvider = selectedCheck?.hallucination_provider
    displayHallucinationModel = selectedCheck?.hallucination_model
    displayExtractionMethod = selectedCheck?.extraction_method || checkStoreStats?.extraction_method
    displayBibliographySourceKind = selectedCheck?.bibliography_source_kind
    displayOriginalFilename = historyItem?.original_filename || selectedCheck?.original_filename
  } else if (isViewingCheck && selectedCheck) {
    // Other checks: use selectedCheck data from history
    displayStatus = selectedCheck.status || 'idle'
    displayTitle = selectedCheck.custom_label || selectedCheck.paper_title
    displaySource = selectedCheck.paper_source
    // total_refs can be an early estimate that's smaller than the real
    // (post de-dup/merge) processed count. Reconcile the total up to processed
    // and clamp the displayed processed + progress so the bar never exceeds
    // 100% ("28/23 · 122%"). REAL DATA ONLY — no fabricated references.
    {
      const rawTotal = selectedCheck.total_refs || 0
      const rawProcessed = selectedCheck.processed_refs || 0
      displayTotalRefs = Math.max(rawTotal, rawProcessed)
      displayProcessedRefs = Math.min(rawProcessed, displayTotalRefs)
    }
    displayProgress = displayTotalRefs > 0
      ? Math.min((displayProcessedRefs / displayTotalRefs) * 100, 100)
      : 0
    displayLlmProvider = selectedCheck.llm_provider
    displayLlmModel = selectedCheck.llm_model
    displayHallucinationProvider = selectedCheck.hallucination_provider
    displayHallucinationModel = selectedCheck.hallucination_model
    displayExtractionMethod = selectedCheck.extraction_method
    displayBibliographySourceKind = selectedCheck.bibliography_source_kind
    displayOriginalFilename = selectedCheck.original_filename
    
    // Build status message based on state
    if (displayStatus === 'in_progress') {
      if (displayProcessedRefs > 0 && displayProcessedRefs >= displayTotalRefs && displayTotalRefs > 0) {
        displayMessage = 'Finishing hallucination check...'
      } else if (displayProcessedRefs > 0) {
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

  // Final defensive clamp: the progress bar must never render past 100%,
  // regardless of which path (live WebSocket stats or persisted history)
  // produced displayProgress. Guards against a stale early total_refs estimate
  // that lagged behind processed_refs.
  displayProgress = Math.min(Math.max(displayProgress || 0, 0), 100)

  // Determine the source type - prefer selectedCheck, fall back to checkStore for current session
  const displaySourceType = selectedCheck?.source_type || (isCurrentSessionCheck ? checkStoreSourceType : null)
  const displayLlmLabel = displayLlmModel 
    ? `${displayLlmProvider ? `${displayLlmProvider} / ` : ''}${displayLlmModel}`
    : null
  const displayHallucinationLabel = displayHallucinationModel
    ? `${displayHallucinationProvider ? `${displayHallucinationProvider} / ` : ''}${displayHallucinationModel}`
    : null
  
  const sourceInfo = formatSource(displaySource, displayTitle, displaySourceType, selectedCheckId, displayOriginalFilename)
  const thumbnailInfo = getThumbnailInfo(displaySource, displaySourceType)
  const isInProgress = displayStatus === 'in_progress' || displayStatus === 'checking'
  const isCompleted = displayStatus === 'completed'
  const isCancelled = displayStatus === 'cancelled'
  const isError = displayStatus === 'error'
  const thumbnailRetryPhase = isCompleted ? 'completed' : 'active'

  // State for thumbnail loading
  const [thumbnailUrl, setThumbnailUrl] = useState(null)
  const [thumbnailError, setThumbnailError] = useState(false)
  const [thumbnailLoading, setThumbnailLoading] = useState(false)
  const [showThumbnailOverlay, setShowThumbnailOverlay] = useState(false)
  const [showShare, setShowShare] = useState(false)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [citationTarget, setCitationTarget] = useState(null)

  // R02 (O3): a ReferenceCard can request "show this citation context in the
  // document". Route it through the native pdf.js stack (DocumentViewer →
  // NativePdfViewer) — NOT the raster ThumbnailOverlay — so the citation is
  // located + flashed on the real PDF (or the converted-PDF / extracted-text
  // fallback), color-coded by the reference's status (R14) and hyperlinked back
  // to its reference entry via refId.
  const citationRequest = useDocViewerStore((s) => s.citation)
  const clearCitationRequest = useDocViewerStore((s) => s.clearCitation)
  useEffect(() => {
    if (citationRequest?.text) {
      setCitationTarget(citationRequest)
    }
  }, [citationRequest?.seq]) // eslint-disable-line react-hooks/exhaustive-deps

  // The locatable spans handed to DocumentViewer for the citation view.
  const citationSpans = buildCitationViewerSpans(citationTarget)
  const closeCitationViewer = () => { setCitationTarget(null); clearCitationRequest() }

  // Close thumbnail overlay on Escape key
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape' && showThumbnailOverlay) {
        setShowThumbnailOverlay(false)
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [showThumbnailOverlay])

  // Fetch thumbnail when check ID changes, and retry once a check completes.
  // For URL/PDF checks the first request can happen while the backend is still
  // downloading/extracting; if that early request fails, clear the error and
  // re-request after completion so the UI can show the generated thumbnail.
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
    const url = `${API_BASE}/api/thumbnail/${selectedCheckId}?phase=${thumbnailRetryPhase}`
    setThumbnailUrl(url)
    // Set the high-resolution preview URL for overlay
    setPreviewUrl(`${API_BASE}/api/preview/${selectedCheckId}?phase=${thumbnailRetryPhase}`)
    
  }, [selectedCheckId, thumbnailRetryPhase])

  // Thumbnail component showing actual PDF first page
  const renderThumbnail = () => {
    // Only show thumbnail if we have a check selected
    if (!selectedCheckId || selectedCheckId === -1) return null
    
    const thumbnailStyle = {
      width: '112px',
      height: '150px',
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
            opacity: thumbnailLoading ? 0 : 1,
            transition: 'opacity 0.18s ease',
          }}
          onError={() => { setThumbnailError(true); setThumbnailLoading(false) }}
          onLoad={() => setThumbnailLoading(false)}
        />
      )
      const loadingElement = (
        <div
          className="relative w-full h-full flex flex-col items-center justify-center overflow-hidden"
          style={{ background: 'var(--color-bg-tertiary)' }}
          aria-label="Retrieving paper thumbnail"
        >
          <div
            className="absolute inset-x-4 top-5 space-y-2 opacity-60"
            aria-hidden="true"
          >
            <div className="h-2 rounded animate-pulse" style={{ background: 'var(--color-text-muted)' }} />
            <div className="h-2 w-4/5 rounded animate-pulse" style={{ background: 'var(--color-text-muted)', animationDelay: '120ms' }} />
            <div className="h-2 w-2/3 rounded animate-pulse" style={{ background: 'var(--color-text-muted)', animationDelay: '240ms' }} />
          </div>
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center"
            style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)' }}
          >
            <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24" style={{ color: 'var(--color-accent, #3b82f6)' }}>
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
          <div className="mt-2 text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
            Retrieving preview
          </div>
        </div>
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
            position: 'relative',
          }}
          className="hover:border-blue-400 hover:shadow-md"
        >
          {imgElement}
          {thumbnailLoading && (
            <div style={{ position: 'absolute', inset: 0 }}>
              {loadingElement}
            </div>
          )}
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
        <div className="flex items-start gap-3">
        <div 
          className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: getStatusBgColor() }}
        >
          {getStatusIcon()}
        </div>
        {/* Thumbnail */}
        {renderThumbnail()}
        <div className="flex-1 min-w-0">
          {/* Title row: title on the left, Share pinned to the far right of the
              outline (to the right of the thumbnail/title), per request. */}
          <div className="flex items-start justify-between gap-3">
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
            {isViewingCheck && displayStatus === 'completed' && (
              <button
                type="button"
                onClick={() => setShowShare(true)}
                className="flex-shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold shadow-sm transition-all hover:brightness-110 active:scale-[0.98]"
                style={{ background: 'var(--color-accent)', color: '#fff', border: 'none' }}
                title="Share or export these results — HTML, PDF, Markdown or Word; or a public link"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
                  <line x1="8.6" y1="13.5" x2="15.4" y2="17.5" /><line x1="15.4" y1="6.5" x2="8.6" y2="10.5" />
                </svg>
                Share results
              </button>
            )}
          </div>
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
            const sourceMethodLine = renderSourceMethodLine({
              sourceKind: displayBibliographySourceKind || displayExtractionMethod,
              sourceType: displaySourceType,
              checkId: selectedCheckId,
              displaySource,
            })
            if (sourceMethodLine) {
              return sourceMethodLine
            }

            if (displaySourceType === 'text' && selectedCheckId) {
              return (
                <p 
                  className="text-sm"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  Extraction:{' '}
                  <a 
                    href={`${API_BASE}/api/text/${selectedCheckId}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline"
                    style={extractionValueStyle}
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
                  Extraction:{' '}
                  <a 
                    href={`${API_BASE}/api/file/${selectedCheckId}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline"
                    style={extractionValueStyle}
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
              Extraction Model:{' '}
              <span style={{ color: 'var(--color-text-secondary)', fontWeight: 600 }}>
                {displayLlmLabel}
              </span>
            </p>
          )}
          {displayHallucinationLabel && (
            <p
              className="text-sm"
              style={{ color: 'var(--color-text-muted)' }}
            >
              Hallucination Model:{' '}
              <span style={{ color: 'var(--color-text-secondary)', fontWeight: 600 }}>
                {displayHallucinationLabel}
              </span>
            </p>
          )}
          <p 
            className="text-sm"
            style={{ 
              color: isError
                ? 'var(--color-error)'
                : isCancelled
                  ? 'var(--color-warning)'
                  : 'var(--color-text-muted)',
              wordBreak: 'break-word',
              overflowWrap: 'anywhere',
            }}
          >
            {displayMessage}
          </p>
        </div>
        {canCancel && (
          /* In-progress Cancel control — shared pill primitive (BUTTON_DESIGN
             §4.6 contract). variant="outline" so it matches the action family;
             error-tinted text/border keep the "cancel" affordance honest. */
          <Button
            size="pill"
            variant="outline"
            style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}
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
          >
            Cancel
          </Button>
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
              className="h-full rounded-full transition-[width] duration-300 ease-linear progress-bar"
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

      {/* Thumbnail overlay modal — scrollable, one image per page.
          When the backend reports page-count > 1 we render a vertical
          scroll list; otherwise we fall back to the single-image preview
          so text/HTML/etc. checks still get a usable overlay. */}
      {showThumbnailOverlay && (previewUrl || thumbnailUrl) && (
        <ThumbnailOverlay
          checkId={selectedCheckId}
          previewUrl={previewUrl}
          thumbnailUrl={thumbnailUrl}
          aiDetection={selectedCheck?.ai_detection || (isCurrentSessionCheck ? checkStoreAiDetection : null)}
          onClose={() => { setShowThumbnailOverlay(false) }}
        />
      )}

      {/* R02 (O3) — per-ref "View in document" renders the NATIVE pdf.js viewer
          (DocumentViewer → NativePdfViewer for PDF + converted-PDF sources;
          extracted-text highlighter as a fallback), with the citation focused,
          color-coded by status (R14) and linked back to its reference. */}
      {citationTarget?.text && selectedCheckId != null && selectedCheckId !== -1 && (
        <DocumentViewer
          checkId={selectedCheckId}
          spans={citationSpans}
          focusSpanIndex={0}
          onClose={closeCitationViewer}
        />
      )}
      {showShare && (
        <ShareModal
          checkId={selectedCheckId}
          title={displayTitle}
          onClose={() => setShowShare(false)}
        />
      )}
    </div>
  )
}

// Exported for unit tests (R28). Co-located with the component per the project's
// existing pattern (see ExploreGraphView).
// eslint-disable-next-line react-refresh/only-export-components
export { buildCitationViewerSpans }
