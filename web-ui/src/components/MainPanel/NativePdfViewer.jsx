import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { getPaperPdf } from '../../utils/api'
import { logger } from '../../utils/logger'
import { getStatusColors } from '../../utils/statusColors'
import { usePdfFind } from '../../utils/usePdfFind'

// Vite resolves `?url` to the emitted worker asset; pdfjs needs it set once.
pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

// AI-flagged spans carry no verification status, so they keep a dedicated red
// highlight; every status-bearing span is colored via the shared R14 map
// (utils/statusColors) so this viewer agrees with StatusSection + ReferenceCard.
const AI_COLORS = { fill: 'rgba(239,68,68,0.24)', stroke: 'rgba(239,68,68,0.8)' }
// R28: the located reference-list ENTRY (the in-PDF jump target of an inline
// citation) gets a distinct blue so it never reads as a verification verdict.
const REF_ENTRY_COLORS = { fill: 'rgba(59,130,246,0.26)', stroke: 'rgba(37,99,235,0.85)' }
// R42: find-in-PDF matches are YELLOW; the active match is the accent/blue.
// Deliberately outside the R14 status palette (green/red/amber/violet/orange/
// slate) so a search highlight never reads as a verification verdict, and the
// active match stands out from the rest of the hits.
const FIND_COLORS = { fill: 'rgba(250,204,21,0.45)', stroke: 'rgba(202,138,4,0.95)' }
const FIND_CURRENT_COLORS = { fill: 'rgba(59,130,246,0.55)', stroke: 'rgba(37,99,235,1)' }

const ESC = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const norm = (s) => (s || '').replace(/\s+/g, ' ').trim()

// Collapse text to lowercase alphanumerics, remembering each kept char's index in
// the original string. Lets us match across PDF-extraction artifacts that plain
// whitespace-tolerance can't bridge — hyphenation ("de- veloped" vs "developed")
// and dropped/merged spaces ("on statistical" vs "onstatistical") — because both
// sides reduce to the same letter stream, then we map the hit back to real offsets.
function alnumIndex(text) {
  const chars = []
  const idx = []
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) {
      chars.push(c.toLowerCase())
      idx.push(i)
    }
  }
  return { compact: chars.join(''), idx }
}

// [start,end] char range of a quote within page text: exact (case-insensitive)
// first, then a whitespace-tolerant leading-words regex, then an alphanumeric-only
// match that ignores hyphenation and spacing differences (PDF extraction spacing).
// Exported for unit testing of the quote-matching fallbacks.
function locate(pageText, rawQuote) {
  const quote = norm(rawQuote).replace(/[……]+$/, '').replace(/\.{3,}$/, '').trim()
  if (quote.length < 8) return null
  const low = pageText.toLowerCase()
  const at = low.indexOf(quote.toLowerCase())
  if (at >= 0) return [at, at + quote.length]
  const words = quote.split(/\s+/).filter(Boolean).slice(0, 14).map(ESC)
  if (words.length < 3) return null
  try {
    const m = new RegExp(words.join('\\s+'), 'i').exec(pageText)
    if (m) return [m.index, Math.min(pageText.length, m.index + Math.max(m[0].length, quote.length))]
  } catch { /* bad regex — ignore */ }
  // Alphanumeric-only fallback: bridges hyphenation + missing/merged spaces that
  // the whitespace regex can't. Match the full compact quote when present, else a
  // leading probe, then map the compact hit back to real page-text offsets.
  const compactQuote = quote.toLowerCase().replace(/[^a-z0-9]/g, '')
  if (compactQuote.length >= 12) {
    const { compact, idx } = alnumIndex(pageText)
    let at2 = compact.indexOf(compactQuote)
    let matchLen = compactQuote.length
    if (at2 < 0) {
      const probe = compactQuote.slice(0, 60)
      at2 = compact.indexOf(probe)
      matchLen = probe.length
    }
    if (at2 >= 0) {
      const startOrig = idx[at2]
      const endOrig = idx[Math.min(idx.length - 1, at2 + matchLen - 1)] + 1
      return [startOrig, endOrig]
    }
  }
  return null
}

// Match every span to the page items it covers → highlight rects, in the page's
// UNSCALED (scale=1) coordinate space. Pure/derived from the raw extracted page
// geometry + the current spans, so it can be recomputed cheaply whenever `spans`
// changes WITHOUT refetching or re-parsing the PDF (which caused the viewer to
// flip between "Rendering PDF…" and the page). Returns { highlights, located }.
function computeHighlights(rawPage, spans) {
  const { pageNumber: n, pageText, items } = rawPage
  const highlights = []
  let located = 0
  ;(spans || []).forEach((sp, si) => {
    const range = locate(pageText, sp?.quote || '')
    if (!range) return
    const [qs, qe] = range
    const boxes = items.filter((it) => it.end > qs && it.start < qe && it.w > 0)
    if (!boxes.length) return
    located += 1
    // Status-bearing spans use the shared R14 map; the reference-list entry gets
    // the distinct blue (R28); status-less AI spans keep the dedicated red.
    const colors = sp.kind === 'ref-entry'
      ? REF_ENTRY_COLORS
      : (sp.status
        ? getStatusColors(sp.status)
        : (sp.kind === 'ai' ? AI_COLORS : getStatusColors('default')))
    boxes.forEach((b, bi) => highlights.push({
      spanIndex: si, key: `${n}-${si}-${bi}`,
      x: b.x, y: b.y, w: b.w, h: b.h,
      fill: colors.fill, stroke: colors.stroke,
      span: sp,
    }))
  })
  return { highlights, located }
}

/**
 * Native PDF rendering (pdf.js) of a check's source document, with the flagged /
 * cited passages drawn as colour-coded highlight boxes over the page image.
 * Clicking a highlight calls `onJumpToReference(span)` so the caller can scroll
 * the reference list to the matching entry. Calls `onUnavailable()` when there's
 * no source PDF (404) or it fails to load, so the parent can fall back to text.
 *
 * spans: [{ quote, status?, refId?, label?, _i? }]
 */
// Clamp the auto-computed fit-width base scale to a sensible band so a
// very narrow modal doesn't render an unreadably tiny page and a very wide
// one doesn't blow the page up past native-ish resolution.
const FIT_MIN = 0.5, FIT_MAX = 3
// Until the real scroll-container width is measured, render small rather than
// at a fixed (often-too-wide) default — a single A4/Letter page is ~595–612pt
// wide, and the modal is min(900px,…), so ~0.85 fits without over-zooming on
// first open. The ResizeObserver/measure effect replaces this immediately.
const FIT_FALLBACK = 0.85

// Exported for unit tests of the quote-matching fallbacks. Co-located per the
// project's existing pattern (see StatusSection's buildCitationViewerSpans).
// eslint-disable-next-line react-refresh/only-export-components
export { locate }

export default function NativePdfViewer({ checkId, spans = [], focusSpanIndex = null, zoom = 1, onJumpToReference, onUnavailable, onLocated, onFindController }) {
  // Raw per-page geometry extracted ONCE from the PDF: { pageNumber, width,
  // height, items, pageText }. Highlight rects are derived from this + `spans`
  // separately (see `pages` memo) so a new `spans` array identity never triggers
  // a PDF refetch / status reset.
  const [rawPages, setRawPages] = useState([])
  const [status, setStatus] = useState('loading') // loading | ready | error
  const docRef = useRef(null)
  const canvasRefs = useRef({})               // pageNumber -> canvas el
  const paintedScaleRef = useRef({})          // pageNumber -> scale it was last painted at
  const renderTasksRef = useRef({})           // pageNumber -> in-flight pdf.js RenderTask
  const containerRef = useRef(null)
  // Base scale that makes a page fit the modal width at zoom=1. Measured from
  // the scroll container once mounted; falls back to a SMALL scale until then
  // (never 1.5×, which over-zooms on open). Multiplied by the `zoom` prop so the
  // header zoom controls (and pinch) scale on top of a fit-width default.
  const [fitScale, setFitScale] = useState(FIT_FALLBACK)
  const SCALE = fitScale * zoom
  // Hover tooltip for a highlight: { x, y, span } positioned relative to the
  // page wrapper. Null when nothing is hovered. Rendered as a solid opaque card
  // (not the browser's native, easy-to-miss title tooltip).
  const [hover, setHover] = useState(null)

  // Stable content signature of `spans` so highlight recomputation is keyed to
  // what actually affects geometry/colour — not the array's identity (the caller
  // rebuilds the array on every render). Prevents needless highlight recompute.
  const spansKey = useMemo(() => JSON.stringify(
    (spans || []).map((s) => [s?.quote, s?.status, s?.kind, s?.refId, s?.refIndex, s?.refEntryIndex, s?._i])
  ), [spans])

  // Derived pages: raw geometry + highlight rects for the current spans. Recomputed
  // only when the document (rawPages) or the spans' content (spansKey) changes —
  // never resets `status`, never refetches the PDF.
  const pages = useMemo(
    () => rawPages.map((rp) => ({ ...rp, highlights: computeHighlights(rp, spans).highlights })),
    [rawPages, spansKey] // eslint-disable-line react-hooks/exhaustive-deps
  )

  // Report how many *distinct* spans located to a highlight (drives the caller's
  // "found N in document" affordance). A span whose quote matches on multiple
  // pages must count once — summing per-page `located` produced impossible tallies
  // (e.g. "3 of 2 located"). Count unique spanIndexes that produced a highlight.
  const totalLocated = useMemo(() => {
    const located = new Set()
    rawPages.forEach((rp) => {
      computeHighlights(rp, spans).highlights.forEach((h) => located.add(h.spanIndex))
    })
    return located.size
  }, [rawPages, spansKey]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (status === 'ready') onLocated?.(totalLocated)
  }, [status, totalLocated]) // eslint-disable-line react-hooks/exhaustive-deps

  // R42: find-in-PDF controller over the rendered text-layer geometry. The query
  // + current-match index live here (where the geometry is); the FindBar UI lives
  // in the parent (DocumentViewer), wired through `onFindController` so a single
  // bar drives every native PDF view.
  const find = usePdfFind(pages)
  const { matchCount, current: findCurrent, currentMatch, next: findNext, prev: findPrev,
    setQuery: setFindQuery, clear: clearFind, isMatchCurrent } = find

  // Hand the controller up so the parent can render the shared FindBar + drive
  // the same keyboard shortcuts. Re-published whenever count/index changes so the
  // bar's "N/M" counter and prev/next stay live.
  useEffect(() => {
    if (!onFindController) return
    onFindController({
      setQuery: setFindQuery, clear: clearFind,
      next: findNext, prev: findPrev,
      matchCount, current: findCurrent,
    })
  }, [onFindController, setFindQuery, clearFind, findNext, findPrev, matchCount, findCurrent])

  // Measure the available width (the scroll container that wraps us) and derive
  // a fit-width base scale from the PDF's intrinsic page width. Re-measures on
  // resize so the page tracks the modal/window size. The page never exceeds the
  // container width at zoom=1 because the base scale targets the inner width.
  useEffect(() => {
    const compute = () => {
      const host = containerRef.current?.parentElement
      const pdf = docRef.current
      if (!host || !pdf) return
      ;(async () => {
        try {
          const page = await pdf.getPage(1)
          const base = page.getViewport({ scale: 1 })
          // Subtract a little so the page + its drop shadow sit inside the
          // padded scroll area rather than forcing a horizontal scrollbar.
          const avail = Math.max(0, host.clientWidth - 8)
          if (!avail || !base.width) return
          const next = Math.min(FIT_MAX, Math.max(FIT_MIN, avail / base.width))
          setFitScale((prev) => (Math.abs(prev - next) > 0.01 ? next : prev))
        } catch { /* not ready yet — ignore */ }
      })()
    }
    compute()
    const host = containerRef.current?.parentElement
    let ro
    if (typeof ResizeObserver !== 'undefined' && host) {
      ro = new ResizeObserver(compute)
      ro.observe(host)
    }
    window.addEventListener('resize', compute)
    return () => {
      try { ro?.disconnect() } catch { /* ignore */ }
      window.removeEventListener('resize', compute)
    }
  }, [status])

  // Clicking a highlight that carries a reference id should scroll the matching
  // reference card into view. Prefer the caller's handler when supplied;
  // otherwise dispatch the same `refchecker:focus-reference` event the
  // ReferenceCard list listens for, wiring the back-link end-to-end without a
  // prop drill. (MainPanel switches to the References tab on this event.)
  // Scroll a span's own highlight into view + briefly flash it (used for the
  // in-PDF reference-list jump and the AI self-reference).
  const flashSpanInDoc = useCallback((spanIndex) => {
    const el = containerRef.current?.querySelector(`[data-span="${spanIndex}"]`)
    if (!el) return false
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    const prev = el.style.boxShadow
    el.style.boxShadow = '0 0 0 3px rgba(37,99,235,0.9)'
    setTimeout(() => { el.style.boxShadow = prev }, 1500)
    return true
  }, [])

  const jumpToReference = useCallback((span) => {
    // R28: an inline citation whose reference-list entry was located in this PDF
    // scrolls + flashes that entry IN-DOCUMENT instead of switching a React tab.
    if (span?.refEntryIndex != null && flashSpanInDoc(span.refEntryIndex)) return
    const refId = span?.refId != null ? span.refId : span?.refIndex
    // R29: AI/flagged sentences carry a self-referential `ai:<i>` id so the hover
    // bar + click work for every span. These don't map to a bibliography card, so
    // re-center on the span's own highlight in-document rather than switch tabs.
    if (typeof refId === 'string' && refId.startsWith('ai:')) {
      flashSpanInDoc(span?._i)
      return
    }
    if (onJumpToReference) { onJumpToReference(span); return }
    if (refId == null) return
    try {
      window.dispatchEvent(new CustomEvent('refchecker:focus-reference', { detail: { refId } }))
    } catch { /* no-op */ }
  }, [onJumpToReference, flashSpanInDoc])

  // Load the PDF + extract raw per-page geometry ONCE, in unscaled (scale=1)
  // coordinates. Depends ONLY on `checkId` — never on `spans` (whose array
  // identity changes on every parent render) or on the paint scale. This is what
  // stops the viewer flip-flopping between "Rendering PDF…" and the page:
  // highlight rects are derived separately from `rawPages` + `spans` (see the
  // `pages` memo), and SCALE is applied at paint/render time only.
  useEffect(() => {
    let cancelled = false
    let task = null
    setStatus('loading'); setRawPages([]); paintedScaleRef.current = {}
    Object.values(renderTasksRef.current).forEach((t) => { try { t?.cancel() } catch { /* ignore */ } })
    renderTasksRef.current = {}
    ;(async () => {
      let buf
      try {
        const res = await getPaperPdf(checkId)
        buf = res?.data
      } catch (e) {
        if (cancelled) return
        logger.debug?.('NativePdfViewer', 'no source PDF', e?.response?.status)
        onUnavailable?.()
        setStatus('error')
        return
      }
      try {
        task = pdfjsLib.getDocument({ data: new Uint8Array(buf) })
        const pdf = await task.promise
        if (cancelled) { pdf.destroy?.(); return }
        docRef.current = pdf
        const out = []
        for (let n = 1; n <= pdf.numPages; n++) {
          const page = await pdf.getPage(n)
          if (cancelled) return
          const vp = page.getViewport({ scale: 1 })
          const tc = await page.getTextContent()
          // Concatenate item strings, tracking each item's char span + bbox.
          let pageText = ''
          const items = []
          for (const it of tc.items) {
            const str = it.str || ''
            const start = pageText.length
            pageText += str
            const end = pageText.length
            // unscaled-space transform of the item origin
            const tx = pdfjsLib.Util.transform(vp.transform, it.transform)
            const fontH = Math.hypot(tx[2], tx[3]) || Math.abs(tx[3]) || 10
            items.push({
              start, end,
              x: tx[4], y: tx[5] - fontH,
              w: (it.width || 0), h: fontH,
            })
            if (it.hasEOL) pageText += ' '
          }
          // Keep the per-item geometry + concatenated page text so both the
          // highlight overlays and the find controller (usePdfFind) reuse the
          // EXACT same coordinates — no second text extraction, no drift.
          out.push({ pageNumber: n, width: vp.width, height: vp.height, items, pageText })
        }
        if (cancelled) return
        setRawPages(out)
        setStatus('ready')
      } catch (e) {
        if (cancelled) return
        logger.error?.('NativePdfViewer', 'PDF render failed', e?.message || e)
        onUnavailable?.()
        setStatus('error')
      }
    })()
    return () => {
      cancelled = true
      try { task?.destroy?.() } catch { /* ignore */ }
      try { docRef.current?.destroy?.() } catch { /* ignore */ }
      docRef.current = null
    }
  }, [checkId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Paint a page's canvas at the current SCALE. Re-renders when SCALE changes so
  // zoomed text stays crisp, but guards against pdf.js render races: a fit-width
  // measurement (or a zoom) changes SCALE right after the first paint, which would
  // otherwise start a second `render()` on the same canvas while the first is still
  // in flight — pdf.js then blanks/tears the canvas (blank page with floating
  // highlights, or upside-down content). We cancel any in-flight task for the page
  // before starting a new one, and skip repaint when already crisp at this scale.
  const paintPage = useCallback(async (pageNumber) => {
    const pdf = docRef.current
    const canvas = canvasRefs.current[pageNumber]
    if (!pdf || !canvas) return
    if (paintedScaleRef.current[pageNumber] === SCALE) return
    try { renderTasksRef.current[pageNumber]?.cancel() } catch { /* ignore */ }
    let task = null
    try {
      const page = await pdf.getPage(pageNumber)
      const vp = page.getViewport({ scale: SCALE })
      const ctx = canvas.getContext('2d')
      canvas.width = vp.width
      canvas.height = vp.height
      task = page.render({ canvasContext: ctx, viewport: vp })
      renderTasksRef.current[pageNumber] = task
      await task.promise
      paintedScaleRef.current[pageNumber] = SCALE
    } catch (e) {
      // RenderingCancelledException is expected when a newer scale supersedes this
      // paint; only surface genuine failures.
      if (e?.name !== 'RenderingCancelledException') {
        logger.debug?.('NativePdfViewer', 'page paint failed', pageNumber, e?.message)
      }
    } finally {
      if (renderTasksRef.current[pageNumber] === task) delete renderTasksRef.current[pageNumber]
    }
  }, [SCALE])

  useEffect(() => {
    if (status !== 'ready') return
    // SCALE changes swap `paintPage`'s identity, re-running this effect. `paintPage`
    // itself no-ops pages already crisp at the current scale and cancels in-flight
    // renders, so repainting on scale change is race-safe. Keyed to `rawPages` (the
    // document) — NOT the highlight-bearing `pages` — so a spans change never
    // repaints the canvases.
    rawPages.forEach((p) => paintPage(p.pageNumber))
  }, [status, rawPages, paintPage])

  // R12: deterministically scroll to + flash the focused passage's highlight,
  // reliably centered. The highlight's geometry depends on the page canvas
  // being laid out at the current SCALE, so we center across two paint frames
  // via requestAnimationFrame (first frame: layout settles after the scale
  // change; second frame: re-center so we land dead-centre) rather than racing
  // a single fixed timeout. Re-runs on SCALE (zoom) change so re-centering
  // tracks pinch / focus-zoom. No retry loop — one rAF pass is enough now that
  // geometry is layout-driven, not image-load-driven.
  useEffect(() => {
    if (status !== 'ready' || focusSpanIndex == null) return undefined
    let raf1 = 0
    let raf2 = 0
    let clearFlash = 0
    const center = (smooth) => {
      const root = containerRef.current
      if (!root) return null
      // Prefer the explicitly-focused span; if it didn't locate in the PDF
      // (e.g. the citation quote isn't found but its reference-list entry is),
      // fall back to the FIRST located highlight so "View in document" always
      // lands on a highlighted passage instead of dumping the user at page 1.
      const el = root.querySelector(`[data-span="${focusSpanIndex}"]`)
        || root.querySelector('[data-span]')
      if (!el) return null
      el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'center' })
      return el
    }
    raf1 = requestAnimationFrame(() => {
      // First pass (instant) once the post-scale layout has settled.
      center(false)
      raf2 = requestAnimationFrame(() => {
        // Second pass (smooth) lands it dead-centre + flashes it.
        const el = center(true)
        if (!el) return
        const prev = el.style.boxShadow
        el.style.boxShadow = '0 0 0 3px var(--color-accent, #3b82f6)'
        clearFlash = setTimeout(() => { el.style.boxShadow = prev }, 1500)
      })
    })
    return () => {
      cancelAnimationFrame(raf1)
      cancelAnimationFrame(raf2)
      clearTimeout(clearFlash)
    }
  }, [status, focusSpanIndex, pages, SCALE])

  // R42: scroll the ACTIVE find match into view whenever the current index (or
  // the match set) changes. Each match overlay carries `data-find` = its global
  // match index; the active one is centered. rAF lets the new overlays lay out
  // before we measure/scroll.
  useEffect(() => {
    if (status !== 'ready' || !currentMatch) return undefined
    const raf = requestAnimationFrame(() => {
      const el = containerRef.current?.querySelector(`[data-find="${findCurrent}"]`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
    return () => cancelAnimationFrame(raf)
  }, [status, currentMatch, findCurrent])

  if (status === 'loading') {
    return <div style={{ color: 'var(--color-text-muted)', fontSize: 14, padding: 20 }}>Rendering PDF…</div>
  }
  if (status === 'error') return null // parent shows the text fallback

  // Which span indices actually drew a highlight — so the in-PDF "jump to the
  // reference-list entry" affordance only appears when that entry was located
  // (otherwise the click honestly falls back to the React reference card).
  const locatedSpanSet = new Set()
  for (const p of pages) for (const h of p.highlights) locatedSpanSet.add(h.spanIndex)

  // R42: group find matches by page so each page draws only its own match rects.
  // Each match keeps its GLOBAL index so the active match (currentMatch) and the
  // `data-find` scroll anchor stay in sync with the FindBar's "N/M" counter.
  const findByPage = new Map()
  for (const m of find.matches) {
    if (!findByPage.has(m.pageNumber)) findByPage.set(m.pageNumber, [])
    findByPage.get(m.pageNumber).push(m)
  }

  return (
    <div ref={containerRef} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
      {pages.map((p) => (
        <div key={p.pageNumber} style={{ position: 'relative', width: p.width * SCALE, height: p.height * SCALE,
          boxShadow: '0 1px 3px rgba(0,0,0,0.2), 0 8px 24px rgba(0,0,0,0.12)', background: '#fff', borderRadius: 2 }}>
          <canvas ref={(el) => { canvasRefs.current[p.pageNumber] = el }}
            style={{ display: 'block', width: p.width * SCALE, height: p.height * SCALE }} />
          {p.highlights.map((h) => {
            const refId = h.span.refId != null ? h.span.refId : h.span.refIndex
            // The reference-list entry is a jump TARGET, not itself clickable.
            const isRefEntry = h.span.kind === 'ref-entry'
            // R28: a citation that resolved its reference-list entry in-PDF, or
            // (R29) an `ai:<i>` self-reference, or any span with a real refId.
            // Only advertise the in-PDF jump when the entry was actually located.
            const canJumpInPdf = h.span.refEntryIndex != null && locatedSpanSet.has(h.span.refEntryIndex)
            const isAiRef = typeof refId === 'string' && refId.startsWith('ai:')
            const clickable = !isRefEntry && (canJumpInPdf || refId != null)
            return (
              <div
                key={h.key}
                data-span={h.spanIndex}
                data-ref={refId != null ? String(refId) : undefined}
                onClick={clickable ? (e) => { e.stopPropagation(); jumpToReference({ ...h.span, _i: h.spanIndex }) } : undefined}
                onMouseEnter={() => setHover({ pageNumber: p.pageNumber, x: h.x, y: h.y, h: h.h, span: h.span, stroke: h.stroke, clickable, isAiRef, canJumpInPdf })}
                onMouseLeave={() => setHover((cur) => (cur && cur.span === h.span && cur.x === h.x ? null : cur))}
                style={{
                  position: 'absolute', left: h.x * SCALE, top: h.y * SCALE, width: h.w * SCALE, height: h.h * SCALE,
                  background: h.fill, border: `1px solid ${h.stroke}`, borderRadius: 2,
                  cursor: clickable ? 'pointer' : 'default', mixBlendMode: 'multiply',
                  transition: 'box-shadow 120ms ease',
                }}
              />
            )
          })}
          {/* R42: find-in-PDF match overlays. Drawn ABOVE the status/citation
              highlights (later in DOM order) but never clickable (pointer-events
              off) so they don't steal the status-highlight hover/click. The
              active match uses the accent/blue + a soft ring; the rest are
              yellow. Colors sit outside the R14 status palette so a search hit
              never reads as a verification verdict. */}
          {(findByPage.get(p.pageNumber) || []).map((m) => {
            const active = isMatchCurrent(m)
            const c = active ? FIND_CURRENT_COLORS : FIND_COLORS
            return m.rects.map((r, ri) => (
              <div
                key={`find-${m.matchIndex}-${ri}`}
                data-find={ri === 0 ? m.matchIndex : undefined}
                style={{
                  position: 'absolute', left: r.x * SCALE, top: r.y * SCALE, width: r.w * SCALE, height: r.h * SCALE,
                  background: c.fill, border: `1px solid ${c.stroke}`, borderRadius: 2,
                  pointerEvents: 'none', mixBlendMode: 'multiply',
                  boxShadow: active ? '0 0 0 2px rgba(37,99,235,0.55)' : 'none',
                  zIndex: 2,
                }}
              />
            ))
          })}
          {/* Solid, opaque hover card describing the cited/flagged passage.
              Positioned above the hovered highlight; uses themed surface +
              readable text + a subtle shadow, and sits above the page (z-index).
              Replaces the easy-to-miss native title tooltip. */}
          {hover && hover.pageNumber === p.pageNumber && (
            <div
              role="tooltip"
              style={{
                position: 'absolute', zIndex: 30, pointerEvents: 'none',
                left: Math.max(4, Math.min(hover.x * SCALE, p.width * SCALE - 304)),
                top: hover.y * SCALE > 76 ? hover.y * SCALE - 8 : hover.y * SCALE + hover.h * SCALE + 8,
                transform: hover.y * SCALE > 76 ? 'translateY(-100%)' : 'none',
                maxWidth: 300, padding: '8px 11px', borderRadius: 8,
                background: 'var(--color-bg-secondary, #1f2430)',
                color: 'var(--color-text-primary, #f3f4f6)',
                border: `1px solid ${hover.stroke}`,
                boxShadow: '0 6px 20px rgba(0,0,0,0.35), 0 1px 3px rgba(0,0,0,0.25)',
                fontSize: 12, lineHeight: 1.45, opacity: 1,
              }}
            >
              {hover.span.label && (
                <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--color-text-primary, #f3f4f6)' }}>
                  {hover.span.label}
                </div>
              )}
              {hover.span.quote && (
                <div style={{
                  color: 'var(--color-text-primary, #f3f4f6)',
                  display: '-webkit-box', WebkitLineClamp: 4, WebkitBoxOrient: 'vertical', overflow: 'hidden',
                }}>
                  “{norm(hover.span.quote).slice(0, 240)}{norm(hover.span.quote).length > 240 ? '…' : ''}”
                </div>
              )}
              {hover.clickable && (
                <div style={{ marginTop: 5, fontSize: 11, fontWeight: 600, color: 'var(--color-accent, #10a37f)' }}>
                  {hover.canJumpInPdf
                    ? 'Click to jump to the reference-list entry in this PDF ↓'
                    : (hover.isAiRef ? 'Click to center this passage →' : 'Click to view this reference →')}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
