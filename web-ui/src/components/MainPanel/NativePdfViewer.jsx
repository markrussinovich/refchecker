import { useEffect, useRef, useState, useCallback } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { getPaperPdf } from '../../utils/api'
import { logger } from '../../utils/logger'

// Vite resolves `?url` to the emitted worker asset; pdfjs needs it set once.
pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

// Status → highlight colours, matching the reference-card status palette.
const FILL = {
  verified: 'rgba(16,185,129,0.26)', warning: 'rgba(245,158,11,0.30)',
  error: 'rgba(239,68,68,0.30)', hallucination: 'rgba(168,85,247,0.30)',
  suggestion: 'rgba(59,130,246,0.26)', ai: 'rgba(239,68,68,0.24)',
  default: 'rgba(245,158,11,0.28)',
}
const STROKE = {
  verified: 'rgba(16,185,129,0.95)', warning: 'rgba(245,158,11,0.95)',
  error: 'rgba(239,68,68,0.95)', hallucination: 'rgba(168,85,247,0.95)',
  suggestion: 'rgba(59,130,246,0.95)', ai: 'rgba(239,68,68,0.8)',
  default: 'rgba(245,158,11,0.9)',
}

const ESC = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const norm = (s) => (s || '').replace(/\s+/g, ' ').trim()

// [start,end] char range of a quote within page text: exact (case-insensitive)
// first, then a whitespace-tolerant leading-words regex (PDF extraction spacing).
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
  return null
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
export default function NativePdfViewer({ checkId, spans = [], focusSpanIndex = null, zoom = 1, onJumpToReference, onUnavailable, onLocated }) {
  const [pages, setPages] = useState([])      // [{ pageNumber, width, height, highlights }]
  const [status, setStatus] = useState('loading') // loading | ready | error
  const docRef = useRef(null)
  const canvasRefs = useRef({})               // pageNumber -> canvas el
  const renderedRef = useRef(new Set())       // pages already painted at current scale
  const containerRef = useRef(null)
  const SCALE = 1.5 * zoom

  // Load the PDF + compute highlight geometry (independent of paint scale).
  useEffect(() => {
    let cancelled = false
    let task = null
    setStatus('loading'); setPages([]); renderedRef.current = new Set()
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
        let totalLocated = 0
        for (let n = 1; n <= pdf.numPages; n++) {
          const page = await pdf.getPage(n)
          if (cancelled) return
          const vp = page.getViewport({ scale: SCALE })
          const tc = await page.getTextContent()
          // Concatenate item strings, tracking each item's char span + bbox.
          let pageText = ''
          const items = []
          for (const it of tc.items) {
            const str = it.str || ''
            const start = pageText.length
            pageText += str
            const end = pageText.length
            // device-space transform of the item origin
            const tx = pdfjsLib.Util.transform(vp.transform, it.transform)
            const fontH = Math.hypot(tx[2], tx[3]) || Math.abs(tx[3]) || 10
            items.push({
              start, end,
              x: tx[4], y: tx[5] - fontH,
              w: (it.width || 0) * SCALE, h: fontH,
            })
            if (it.hasEOL) pageText += ' '
          }
          // Match each span to the items it covers → highlight rects.
          const highlights = []
          spans.forEach((sp, si) => {
            const range = locate(pageText, sp?.quote || '')
            if (!range) return
            const [qs, qe] = range
            const boxes = items.filter((it) => it.end > qs && it.start < qe && it.w > 0)
            if (!boxes.length) return
            totalLocated += 1
            const sKey = sp.status || (sp.kind === 'ai' ? 'ai' : 'default')
            boxes.forEach((b, bi) => highlights.push({
              spanIndex: si, key: `${n}-${si}-${bi}`,
              x: b.x, y: b.y, w: b.w, h: b.h,
              fill: FILL[sKey] || FILL.default, stroke: STROKE[sKey] || STROKE.default,
              span: sp,
            }))
          })
          out.push({ pageNumber: n, width: vp.width, height: vp.height, highlights })
        }
        if (cancelled) return
        setPages(out)
        setStatus('ready')
        onLocated?.(totalLocated)
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
  }, [checkId, spans, SCALE]) // eslint-disable-line react-hooks/exhaustive-deps

  // Paint each page canvas once it's in the list (and on scale change).
  const paintPage = useCallback(async (pageNumber) => {
    const pdf = docRef.current
    const canvas = canvasRefs.current[pageNumber]
    if (!pdf || !canvas || renderedRef.current.has(pageNumber)) return
    renderedRef.current.add(pageNumber)
    try {
      const page = await pdf.getPage(pageNumber)
      const vp = page.getViewport({ scale: SCALE })
      const ctx = canvas.getContext('2d')
      canvas.width = vp.width
      canvas.height = vp.height
      await page.render({ canvasContext: ctx, viewport: vp }).promise
    } catch (e) {
      logger.debug?.('NativePdfViewer', 'page paint failed', pageNumber, e?.message)
    }
  }, [SCALE])

  useEffect(() => {
    if (status !== 'ready') return
    pages.forEach((p) => paintPage(p.pageNumber))
  }, [status, pages, paintPage])

  // Scroll to + flash the focused passage's highlight once rendered.
  useEffect(() => {
    if (status !== 'ready' || focusSpanIndex == null) return
    const t = setTimeout(() => {
      const el = containerRef.current?.querySelector(`[data-span="${focusSpanIndex}"]`)
      if (!el) return
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      const prev = el.style.boxShadow
      el.style.boxShadow = '0 0 0 3px var(--color-accent, #3b82f6)'
      setTimeout(() => { el.style.boxShadow = prev }, 1500)
    }, 150)
    return () => clearTimeout(t)
  }, [status, focusSpanIndex, pages])

  if (status === 'loading') {
    return <div style={{ color: 'var(--color-text-muted)', fontSize: 14, padding: 20 }}>Rendering PDF…</div>
  }
  if (status === 'error') return null // parent shows the text fallback

  return (
    <div ref={containerRef} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
      {pages.map((p) => (
        <div key={p.pageNumber} style={{ position: 'relative', width: p.width, height: p.height,
          boxShadow: '0 1px 3px rgba(0,0,0,0.2), 0 8px 24px rgba(0,0,0,0.12)', background: '#fff', borderRadius: 2 }}>
          <canvas ref={(el) => { canvasRefs.current[p.pageNumber] = el }}
            style={{ display: 'block', width: p.width, height: p.height }} />
          {p.highlights.map((h) => {
            const clickable = !!(onJumpToReference && (h.span.refId != null || h.span.refIndex != null))
            return (
              <div
                key={h.key}
                data-span={h.spanIndex}
                onClick={clickable ? () => onJumpToReference(h.span) : undefined}
                title={clickable ? `Go to reference${h.span.label ? `: ${h.span.label}` : ''}` : (h.span.label || undefined)}
                style={{
                  position: 'absolute', left: h.x, top: h.y, width: h.w, height: h.h,
                  background: h.fill, border: `1px solid ${h.stroke}`, borderRadius: 2,
                  cursor: clickable ? 'pointer' : 'default', mixBlendMode: 'multiply',
                  transition: 'box-shadow 120ms ease',
                }}
              />
            )
          })}
        </div>
      ))}
    </div>
  )
}
