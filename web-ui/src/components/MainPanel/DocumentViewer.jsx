import { useEffect, useMemo, useState } from 'react'
import { getPaperText } from '../../utils/api'

/**
 * In-document highlighter. Fetches the extracted body text of a check's source
 * document (`/api/paper-text/{checkId}`) and renders it with the AI-detection
 * flagged passages marked in place — the "show these passages in the file
 * itself / converted view" request.
 *
 * Spans carry only the quote TEXT (no char offsets), and PDF extraction leaves
 * odd spacing + the quotes are ellipsis-truncated, so matching is
 * whitespace-tolerant: exact substring first, then a `word\s+word…` regex on
 * the quote's leading words. Passages that can't be located are listed so the
 * user still sees them.
 */

const ESC = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function findRange(text, rawQuote) {
  const quote = (rawQuote || '').replace(/[……]+\s*$/, '').replace(/\.\.\.\s*$/, '').trim()
  if (quote.length < 8) return null
  // 1) exact substring (quotes come from this same extracted text)
  let idx = text.indexOf(quote)
  if (idx >= 0) return [idx, idx + quote.length]
  // 2) whitespace-tolerant on the leading words
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

function mergeRanges(ranges) {
  const sorted = ranges.filter(Boolean).sort((a, b) => a[0] - b[0])
  const out = []
  for (const r of sorted) {
    const last = out[out.length - 1]
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1])
    else out.push([r[0], r[1]])
  }
  return out
}

export default function DocumentViewer({ checkId, spans = [], onClose }) {
  const [state, setState] = useState({ loading: true, text: '', error: null, available: true, truncated: false })

  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    getPaperText(checkId)
      .then((res) => {
        if (!alive) return
        const d = res?.data || {}
        setState({
          loading: false,
          text: d.text || '',
          available: d.available !== false && !!(d.text || '').trim(),
          truncated: !!d.truncated,
          error: null,
        })
      })
      .catch((e) => {
        if (!alive) return
        setState({ loading: false, text: '', available: false, truncated: false,
          error: e?.response?.data?.detail || e?.message || 'Could not load the document text.' })
      })
    return () => { alive = false }
  }, [checkId])

  // Build the highlighted render + track which spans were located.
  const { nodes, located, missing } = useMemo(() => {
    const text = state.text || ''
    if (!text) return { nodes: [text], located: 0, missing: spans.length }
    const ranges = []
    let foundCount = 0
    for (const sp of spans) {
      const r = findRange(text, sp?.quote || '')
      if (r) { ranges.push(r); foundCount += 1 }
    }
    const merged = mergeRanges(ranges)
    const out = []
    let cursor = 0
    merged.forEach(([s, e], i) => {
      if (s > cursor) out.push(text.slice(cursor, s))
      out.push(
        <mark
          key={`m${i}`}
          style={{ backgroundColor: 'rgba(239,68,68,0.22)', color: 'inherit',
                   borderRadius: 3, padding: '0 1px', boxShadow: 'inset 0 -2px 0 rgba(239,68,68,0.5)' }}
        >
          {text.slice(s, e)}
        </mark>
      )
      cursor = e
    })
    if (cursor < text.length) out.push(text.slice(cursor))
    return { nodes: out, located: foundCount, missing: spans.length - foundCount }
  }, [state.text, spans])

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Flagged passages in document"
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000, display: 'flex',
        alignItems: 'center', justifyContent: 'center', padding: 16,
        background: 'rgba(0,0,0,0.5)',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 'min(900px, 100%)', maxHeight: '90vh', display: 'flex', flexDirection: 'column',
          background: 'var(--color-bg-primary)', color: 'var(--color-text-primary)',
          border: '1px solid var(--color-border)', borderRadius: 10, overflow: 'hidden',
          boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      gap: 8, padding: '10px 14px', borderBottom: '1px solid var(--color-border)',
                      background: 'var(--color-bg-secondary)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <strong style={{ fontSize: 14 }}>Flagged passages in document</strong>
            {!state.loading && state.available && (
              <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                <mark style={{ backgroundColor: 'rgba(239,68,68,0.22)', padding: '0 4px', borderRadius: 3 }}>highlighted</mark>
                {' '}{located} of {spans.length} located
                {missing > 0 ? ` · ${missing} not found in extracted text` : ''}
                {state.truncated ? ' · text truncated' : ''}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-sm"
            style={{ border: '1px solid var(--color-border)', borderRadius: 6, padding: '2px 10px',
                     background: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', cursor: 'pointer' }}
          >
            Close
          </button>
        </div>

        <div style={{ overflow: 'auto', padding: '16px 18px' }}>
          {state.loading && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>Extracting document text…</div>
          )}
          {!state.loading && state.error && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>{state.error}</div>
          )}
          {!state.loading && !state.error && !state.available && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>
              The original document text isn’t available for this check (it may have been a structured
              source, or the cached file was cleared). Re-run the check to view it in context.
            </div>
          )}
          {!state.loading && !state.error && state.available && (
            <>
              {missing > 0 && (
                <div style={{ marginBottom: 12, padding: '8px 10px', borderRadius: 6,
                              background: 'var(--color-bg-tertiary)', fontSize: 12, color: 'var(--color-text-muted)' }}>
                  {missing} flagged passage{missing === 1 ? '' : 's'} couldn’t be located in the extracted text
                  (PDF layout/spacing differences):
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
