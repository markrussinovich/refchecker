import { useEffect, useMemo, useRef, useState } from 'react'
import { getPaperText } from '../../utils/api'
import { isTauri, openExternal } from '../../utils/tauriBridge'

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

export default function DocumentViewer({ checkId, spans = [], focusSpanIndex = null, onClose }) {
  const [state, setState] = useState({ loading: true, text: '', error: null, available: true, truncated: false })
  const scrollRef = useRef(null)

  useEffect(() => {
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
  }, [checkId])

  const { nodes, located, missing, spanToMark } = useMemo(() => {
    const text = state.text || ''
    if (!text) return { nodes: [text], located: 0, missing: spans.length, spanToMark: {} }
    const ranges = []
    let foundCount = 0
    spans.forEach((sp, si) => {
      const r = findRange(text, sp?.quote || '')
      if (r) { ranges.push([r[0], r[1], si]); foundCount += 1 }
    })
    const merged = mergeRanges(ranges)
    const spanToMark = {}
    merged.forEach((mk, mi) => mk.spans.forEach((si) => { spanToMark[si] = mi }))
    const out = []
    let cursor = 0
    merged.forEach((mk, i) => {
      if (mk.start > cursor) out.push(...[].concat(linkify(text.slice(cursor, mk.start), `t${i}`)))
      out.push(
        <mark
          key={`m${i}`}
          id={`docmark-${i}`}
          style={{ backgroundColor: 'var(--color-mark-bg, rgba(239,68,68,0.22))', color: 'inherit',
                   borderRadius: 3, padding: '0 1px', boxShadow: 'inset 0 -2px 0 rgba(239,68,68,0.5)' }}
        >
          {text.slice(mk.start, mk.end)}
        </mark>
      )
      cursor = mk.end
    })
    if (cursor < text.length) out.push(...[].concat(linkify(text.slice(cursor), 'tail')))
    return { nodes: out, located: foundCount, missing: spans.length - foundCount, spanToMark }
  }, [state.text, spans])

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

  const btn = {
    border: '1px solid var(--color-border)', borderRadius: 6, padding: '2px 10px',
    background: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', cursor: 'pointer', fontSize: 13,
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
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
                      padding: '10px 14px', borderBottom: '1px solid var(--color-border)',
                      background: 'var(--color-bg-secondary)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <strong style={{ fontSize: 14 }}>Flagged passages in document</strong>
            {!state.loading && state.available && (
              <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                <mark style={{ backgroundColor: 'var(--color-mark-bg, rgba(239,68,68,0.22))', padding: '0 4px', borderRadius: 3 }}>highlighted</mark>
                {' '}{located} of {spans.length} located
                {missing > 0 ? ` · ${missing} not found` : ''}
                {state.truncated ? ' · truncated' : ''}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {!state.loading && state.available && located > 1 && (
              <>
                <button type="button" onClick={() => gotoMark(-1)} style={btn} title="Previous passage">↑</button>
                <button type="button" onClick={() => gotoMark(1)} style={btn} title="Next passage">↓</button>
              </>
            )}
            <button type="button" onClick={onClose} style={btn}>Close</button>
          </div>
        </div>

        <div ref={scrollRef} style={{ overflow: 'auto', padding: '16px 18px' }}>
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
              <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.6,
                            fontSize: 14, fontFamily: 'var(--font-sans, ui-sans-serif, system-ui)' }}>
                {nodes}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
