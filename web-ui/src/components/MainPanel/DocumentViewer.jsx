import { useEffect, useMemo, useRef, useState } from 'react'
import { getPaperText } from '../../utils/api'
import { isTauri, openExternal } from '../../utils/tauriBridge'
import { ZoomControls, FindBar } from '../common/ViewerControls'
import { useGesturePinchZoom } from '../../utils/useGesturePinchZoom'
import NativePdfViewer from './NativePdfViewer'

/**
 * In-document highlighter. Fetches the extracted body text of a check's source
 * document (`/api/paper-text/{checkId}`) and renders it with the AI-detection
 * flagged passages marked in place.
 *
 * Spans carry only quote TEXT (no char offsets), and PDF extraction leaves odd
 * spacing + ellipsis-truncated quotes, so matching is whitespace-tolerant
 * (exact substring first, then a `word\s+word…` regex on leading words).
 * Passages that can't be located are listed so nothing is hidden.
 *
 * `focusSpanIndex` (optional): scroll to + flash the passage for that span on
 * open — used by the "click a flagged passage → see it in the document" flow.
 */

const ESC = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const URL_OR_DOI_RE = /(https?:\/\/[^\s)<>"']+|\bdoi:\s*10\.\d{4,9}\/[^\s)<>"']+|\b10\.\d{4,9}\/[^\s)<>"']{3,})/gi

function findRange(text, rawQuote) {
  const quote = (rawQuote || '').replace(/[……]+\s*$/, '').replace(/\.\.\.\s*$/, '').trim()
  if (quote.length < 8) return null
  let idx = text.indexOf(quote)
  if (idx >= 0) return [idx, idx + quote.length]
  const words = quote.split(/\s+/).filter(Boolean).slice(0, 16).map(ESC)
  if (words.length < 3) return null
  try {
    const re = new RegExp(words.join('\\s+'), 'i')
    const m = re.exec(text)
    if (m) {
      const len = Math.min(Math.max(m[0].length, quote.length), 700)
      return [m.index, Math.min(text.length, m.index + len)]
    }
  } catch { /* bad regex — ignore */ }
  return null
}

// Wrap URLs / DOIs in a plain text slice as themed, app-opened links.
function linkify(text, keyPrefix) {
  if (!text) return text
  const out = []
  let last = 0
  let m
  URL_OR_DOI_RE.lastIndex = 0
  while ((m = URL_OR_DOI_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const raw = m[0]
    let href = raw
    if (/^doi:/i.test(raw)) href = 'https://doi.org/' + raw.replace(/^doi:\s*/i, '')
    else if (/^10\./.test(raw)) href = 'https://doi.org/' + raw
    out.push(
      <a
        key={`${keyPrefix}-${m.index}`}
        href={href}
        onClick={(e) => { if (isTauri()) { e.preventDefault(); openExternal(href) } }}
        target="_blank"
        rel="noopener noreferrer"
        style={{ color: 'var(--color-link, #3b82f6)', textDecoration: 'underline', wordBreak: 'break-all' }}
      >
        {raw}
      </a>
    )
    last = m.index + raw.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

function mergeRanges(ranges) {
  // ranges: [start, end, spanIndex]; merge overlapping, tracking covered spans.
  const sorted = ranges.filter(Boolean).slice().sort((a, b) => a[0] - b[0])
  const out = []
  for (const r of sorted) {
    const last = out[out.length - 1]
    if (last && r[0] <= last.end) {
      last.end = Math.max(last.end, r[1])
      last.spans.push(r[2])
    } else {
      out.push({ start: r[0], end: r[1], spans: [r[2]] })
    }
  }
  return out
}

// R12: a citation/passage view always opens at this deterministic focus zoom
// (a clear, readable "zoomed in to the cited sentence" level on top of the
// fit-width base scale) — never inheriting a stale prior zoom. When the viewer
// is opened with no focus target it opens at fit-width (1).
const CITE_FOCUS_ZOOM = 1.5

export default function DocumentViewer({ checkId, spans = [], focusSpanIndex = null, onClose, onJumpToReference }) {
  // Native PDF first; fall back to the extracted-text view when there's no
  // source PDF (pasted text / .bib / .tex) or pdf.js can't render it.
  const [mode, setMode] = useState('pdf') // 'pdf' | 'text'
  const [pdfLocated, setPdfLocated] = useState(0)
  const [state, setState] = useState({ loading: true, text: '', error: null, available: true, truncated: false })
  // R12: start at the focus zoom whenever a citation/passage is focused so the
  // first paint already lands at a clear, centered reading zoom.
  const [zoom, setZoom] = useState(focusSpanIndex != null ? CITE_FOCUS_ZOOM : 1)
  const [findOpen, setFindOpen] = useState(false)
  const [findQuery, setFindQuery] = useState('')
  const [currentMatch, setCurrentMatch] = useState(0)
  const scrollRef = useRef(null)
  const findInputRef = useRef(null)

  const ZOOM_MIN = 0.7, ZOOM_MAX = 2.2, ZOOM_STEP = 0.15
  const zoomIn = () => setZoom(z => Math.min(ZOOM_MAX, +(z + ZOOM_STEP).toFixed(2)))
  const zoomOut = () => setZoom(z => Math.max(ZOOM_MIN, +(z - ZOOM_STEP).toFixed(2)))

  // R31: trackpad/touch pinch-to-zoom via the shared hook (ctrl+wheel + WebKit
  // gesture events), the same implementation the per-ref ThumbnailOverlay uses.
  useGesturePinchZoom(scrollRef, setZoom, { min: ZOOM_MIN, max: ZOOM_MAX })

  // R12: deterministically RESET to the focus zoom whenever the citation target
  // changes — the viewer stays mounted while a user re-targets from card to
  // card, so without this it would keep whatever zoom the user (or the prior
  // citation) left behind. Keyed on the focused span's own text so re-targeting
  // to a different citation always re-centers at the focus zoom, while a plain
  // re-render (e.g. find-bar typing) does NOT yank the user's manual zoom.
  const focusKey = focusSpanIndex != null ? (spans[focusSpanIndex]?.quote || focusSpanIndex) : null
  useEffect(() => {
    if (focusKey == null) return
    setZoom(CITE_FOCUS_ZOOM)
  }, [focusKey])

  // Back-link from a clicked PDF highlight to its reference card. NativePdfViewer
  // calls this with the span it drew. We dispatch the `refchecker:focus-reference`
  // event the reference list (and MainPanel) listens for FIRST — that switches to
  // the References tab and flashes the target card — then close the viewer on a
  // short beat so the tab switch lands before the modal disappears, keeping the
  // user oriented instead of yanking them into a different tab abruptly. Falls
  // back to whatever the parent passed if it supplied a handler.
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose }, [onClose])
  const jumpToReference = (span) => {
    const refId = span?.refId != null ? span.refId : span?.refIndex
    // R29: AI/flagged sentences use a self-referential `ai:<i>` id (so the hover
    // bar + link engage for every span). They don't map to a reference card, so
    // never switch tabs / tear down the viewer for them — NativePdfViewer
    // re-centers on the span itself.
    if (typeof refId === 'string' && refId.startsWith('ai:')) return
    if (onJumpToReference) {
      onJumpToReference(span)
    } else if (refId != null) {
      try {
        window.dispatchEvent(new CustomEvent('refchecker:focus-reference', { detail: { refId } }))
      } catch { /* no-op */ }
    } else {
      return // nothing to focus — leave the viewer open and oriented
    }
    // Let the tab switch + card-flash commit before tearing down the modal.
    setTimeout(() => closeRef.current?.(), 220)
  }

  useEffect(() => {
    if (mode !== 'text') return        // only fetch text once we fall back to it
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    getPaperText(checkId)
      .then((res) => {
        if (!alive) return
        const d = res?.data || {}
        setState({
          loading: false, text: d.text || '',
          available: d.available !== false && !!(d.text || '').trim(),
          truncated: !!d.truncated, error: null,
        })
      })
      .catch((e) => {
        if (!alive) return
        setState({ loading: false, text: '', available: false, truncated: false,
          error: e?.response?.data?.detail || e?.message || 'Could not load the document text.' })
      })
    return () => { alive = false }
  }, [checkId, mode])

  const { nodes, located, missing, spanToMark, findCount } = useMemo(() => {
    const text = state.text || ''
    if (!text) return { nodes: [text], located: 0, missing: spans.length, spanToMark: {}, findCount: 0 }
    const ranges = []
    let foundCount = 0
    spans.forEach((sp, si) => {
      const r = findRange(text, sp?.quote || '')
      if (r) { ranges.push([r[0], r[1], si]); foundCount += 1 }
    })
    const merged = mergeRanges(ranges)
    const spanToMark = {}
    merged.forEach((mk, mi) => mk.spans.forEach((si) => { spanToMark[si] = mi }))

    // Find-in-document matches (case-insensitive, non-overlapping).
    const findMatches = []
    const q = (findQuery || '').trim()
    if (q.length >= 2) {
      const lower = text.toLowerCase()
      const lq = q.toLowerCase()
      let i = 0
      while ((i = lower.indexOf(lq, i)) !== -1) { findMatches.push([i, i + lq.length]); i += lq.length }
    }

    // Build a sorted set of segment boundaries from BOTH AI marks and find
    // matches, then emit one node per maximal segment — so a find highlight
    // and an AI highlight can coexist without clobbering each other.
    const points = new Set([0, text.length])
    merged.forEach((m) => { points.add(m.start); points.add(m.end) })
    findMatches.forEach(([s, e]) => { points.add(s); points.add(e) })
    const bounds = Array.from(points).sort((a, b) => a - b)

    const markIndexAt = (s, e) => merged.findIndex((m) => s >= m.start && e <= m.end)
    const findIndexAt = (s, e) => findMatches.findIndex(([fs, fe]) => s >= fs && e <= fe)

    const out = []
    for (let k = 0; k < bounds.length - 1; k++) {
      const s = bounds[k], e = bounds[k + 1]
      if (s >= e) continue
      const slice = text.slice(s, e)
      const mi = markIndexAt(s, e)
      const fi = findIndexAt(s, e)
      const isAi = mi !== -1
      const isFind = fi !== -1
      if (!isAi && !isFind) { out.push(...[].concat(linkify(slice, `t${k}`))); continue }
      const isCurrentFind = isFind && fi === currentMatch
      const style = {
        color: 'inherit', borderRadius: 3, padding: '0 1px',
        ...(isAi ? { backgroundColor: 'var(--color-mark-bg, rgba(239,68,68,0.22))', boxShadow: 'inset 0 -2px 0 rgba(239,68,68,0.5)' } : {}),
        ...(isFind ? {
          backgroundColor: isCurrentFind ? 'var(--color-accent, #3b82f6)' : 'rgba(250, 204, 21, 0.55)',
          color: isCurrentFind ? '#fff' : 'inherit',
          boxShadow: isCurrentFind ? '0 0 0 1px var(--color-accent, #3b82f6)' : 'none',
        } : {}),
      }
      out.push(
        <mark
          key={`seg${k}`}
          id={isFind ? `docfind-${fi}` : (isAi ? `docmark-${mi}` : undefined)}
          style={style}
        >
          {slice}
        </mark>
      )
    }
    return { nodes: out, located: foundCount, missing: spans.length - foundCount, spanToMark, findCount: findMatches.length }
  }, [state.text, spans, findQuery, currentMatch])

  // Scroll to + briefly flash the focused passage once the text is rendered.
  useEffect(() => {
    if (state.loading || focusSpanIndex == null) return
    const mi = spanToMark[focusSpanIndex]
    if (mi == null) return
    const t = setTimeout(() => {
      const el = document.getElementById(`docmark-${mi}`)
      if (!el) return
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      const prev = el.style.boxShadow
      el.style.boxShadow = '0 0 0 3px var(--color-accent, #3b82f6)'
      setTimeout(() => { el.style.boxShadow = prev }, 1400)
    }, 120)
    return () => clearTimeout(t)
  }, [state.loading, focusSpanIndex, spanToMark])

  // Keep the active find match in range and scroll to it.
  useEffect(() => { setCurrentMatch(0) }, [findQuery])
  useEffect(() => {
    if (!findQuery || findCount === 0) return
    const t = setTimeout(() => {
      const el = document.getElementById(`docfind-${currentMatch}`)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 30)
    return () => clearTimeout(t)
  }, [currentMatch, findQuery, findCount])

  const gotoFind = (dir) => {
    if (!findCount) return
    setCurrentMatch((c) => (c + dir + findCount) % findCount)
  }

  // Ctrl/Cmd+F opens the find bar; Esc closes it (or the viewer).
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'f' || e.key === 'F')) {
        e.preventDefault(); setFindOpen(true)
        setTimeout(() => findInputRef.current?.focus(), 0)
      } else if (e.key === 'Escape' && findOpen) {
        e.preventDefault(); setFindOpen(false); setFindQuery('')
      } else if ((e.metaKey || e.ctrlKey) && (e.key === '=' || e.key === '+')) {
        e.preventDefault(); zoomIn()
      } else if ((e.metaKey || e.ctrlKey) && e.key === '-') {
        e.preventDefault(); zoomOut()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [findOpen])

  const markEls = () => Array.from(scrollRef.current?.querySelectorAll('mark') || [])
  const gotoMark = (dir) => {
    const els = markEls()
    if (!els.length) return
    const container = scrollRef.current
    const mid = container.scrollTop + container.clientHeight / 2
    let idx = els.findIndex((el) => el.offsetTop > mid)
    if (idx === -1) idx = els.length - 1
    idx = dir > 0 ? Math.min(els.length - 1, idx) : Math.max(0, idx - 1)
    els[idx]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  // Control-bar buttons. Primary surface on the (slightly darker) tertiary
  // header bar so they read with clear contrast over the white PDF / the bar.
  const btn = {
    border: '1px solid var(--color-border)', borderRadius: 6, padding: '4px 11px',
    background: 'var(--color-bg-primary)', color: 'var(--color-text-primary)',
    cursor: 'pointer', fontSize: 13, fontWeight: 500, lineHeight: 1.4,
  }

  return (
    <div role="dialog" aria-modal="true" aria-label="Flagged passages in document" onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', alignItems: 'center',
               justifyContent: 'center', padding: 16, background: 'rgba(0,0,0,0.5)' }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ width: 'min(900px, 100%)', maxHeight: '90vh', display: 'flex', flexDirection: 'column',
                 background: 'var(--color-bg-primary)', color: 'var(--color-text-primary)',
                 border: '1px solid var(--color-border)', borderRadius: 10, overflow: 'hidden',
                 boxShadow: '0 20px 60px rgba(0,0,0,0.4)' }}>
        {/* Solid, themed control bar. Sticky + above the scrolling pages so the
            zoom / find / close controls never disappear over a white PDF page.
            Uses the tertiary surface (a touch darker than the secondary "desk"
            below) so the secondary-bg control buttons read with real contrast
            instead of rendering near-white-on-white. */}
        <div style={{ position: 'sticky', top: 0, zIndex: 5, flexShrink: 0,
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
                      padding: '10px 14px', borderBottom: '1px solid var(--color-border)',
                      background: 'var(--color-bg-tertiary)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <strong style={{ fontSize: 14 }}>Flagged passages in document</strong>
            {((mode === 'pdf') || (!state.loading && state.available)) && spans.length > 0 && (
              <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                <mark style={{ backgroundColor: 'var(--color-mark-bg, rgba(239,68,68,0.22))', padding: '0 4px', borderRadius: 3 }}>highlighted</mark>
                {' '}{mode === 'pdf' ? pdfLocated : located} of {spans.length} located
                {mode === 'text' && missing > 0 ? ` · ${missing} not found` : ''}
                {mode === 'text' && state.truncated ? ' · truncated' : ''}
                {mode === 'pdf' ? ' · native PDF' : ''}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {mode === 'text' && !state.loading && state.available && (
              findOpen ? (
                <FindBar
                  value={findQuery}
                  onChange={setFindQuery}
                  matchCount={findCount}
                  currentMatch={currentMatch}
                  onPrev={() => gotoFind(-1)}
                  onNext={() => gotoFind(1)}
                  onClose={() => { setFindOpen(false); setFindQuery('') }}
                  inputRef={findInputRef}
                />
              ) : (
                <button type="button" onClick={() => { setFindOpen(true); setTimeout(() => findInputRef.current?.focus(), 0) }}
                  style={btn} title="Find in document (⌘F)">⌕ Find</button>
              )
            )}
            {((mode === 'pdf') || (!state.loading && state.available)) && (
              <ZoomControls zoom={zoom} onZoomIn={zoomIn} onZoomOut={zoomOut} onReset={() => setZoom(1)} min={ZOOM_MIN} max={ZOOM_MAX} />
            )}
            {mode === 'text' && !state.loading && state.available && located > 1 && (
              <>
                <button type="button" onClick={() => gotoMark(-1)} style={btn} title="Previous passage">↑</button>
                <button type="button" onClick={() => gotoMark(1)} style={btn} title="Next passage">↓</button>
              </>
            )}
            <button type="button" onClick={onClose} style={btn}>Close</button>
          </div>
        </div>

        <div ref={scrollRef} style={{ overflow: 'auto', padding: '20px 18px',
                                      background: 'var(--color-bg-secondary)' }}>
          {mode === 'pdf' && (
            <NativePdfViewer
              checkId={checkId} spans={spans} focusSpanIndex={focusSpanIndex} zoom={zoom}
              onJumpToReference={jumpToReference}
              onUnavailable={() => setMode('text')} onLocated={setPdfLocated}
            />
          )}
          {mode === 'text' && (<>
          {state.loading && (<div style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>Extracting document text…</div>)}
          {!state.loading && state.error && (<div style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>{state.error}</div>)}
          {!state.loading && !state.error && !state.available && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>
              The original document text isn’t available for this check (a structured source, or the cached
              file was cleared). Re-run the check to view it in context.
            </div>
          )}
          {!state.loading && !state.error && state.available && (
            <>
              {missing > 0 && (
                <div style={{ marginBottom: 12, padding: '8px 10px', borderRadius: 6,
                              background: 'var(--color-bg-tertiary)', fontSize: 12, color: 'var(--color-text-muted)' }}>
                  {missing} flagged passage{missing === 1 ? '' : 's'} couldn’t be located (PDF layout differences):
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                    {spans.filter((sp) => !findRange(state.text, sp?.quote || '')).slice(0, 6).map((sp, i) => (
                      <li key={i} style={{ marginBottom: 2 }}>“{(sp.quote || '').slice(0, 120)}…”</li>
                    ))}
                  </ul>
                </div>
              )}
              {/* Render the extracted body as a centered "page" so it reads
                  like the source document instead of a flat text dump:
                  a paper-coloured card on the muted desk above, a measured
                  column, serif type, and comfortable leading. pre-wrap is
                  kept so the PDF's own line structure is preserved. */}
              <div style={{ maxWidth: 760 * zoom, margin: '0 auto', padding: '44px 52px',
                            background: 'var(--color-bg-primary)',
                            border: '1px solid var(--color-border)', borderRadius: 4,
                            boxShadow: '0 1px 3px rgba(0,0,0,0.12), 0 8px 24px rgba(0,0,0,0.06)',
                            whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.75,
                            fontSize: 15.5 * zoom, color: 'var(--color-text-primary)',
                            fontFamily: 'var(--font-serif, Georgia, "Times New Roman", ui-serif, serif)' }}>
                {nodes}
              </div>
            </>
          )}
          </>)}
        </div>
      </div>
    </div>
  )
}

// R12: exported for unit tests — the deterministic focus zoom a citation/passage
// view opens (and re-targets) at. Co-located per the project's existing pattern.
// eslint-disable-next-line react-refresh/only-export-components
export { CITE_FOCUS_ZOOM }
