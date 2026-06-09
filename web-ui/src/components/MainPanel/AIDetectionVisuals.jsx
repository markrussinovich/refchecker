import { useState } from 'react'

/**
 * GPTZero-style visualizations for the AI-detection result. Everything here is
 * DESCRIPTIVE of the model's windowed outputs — never a probability that a
 * human wrote the text. Pure SVG/CSS, no chart dependency.
 */

const SEG = { AI: 'var(--color-error)', Mixed: 'var(--color-warning)', Human: 'var(--color-success)' }
const BAND_COLOR = {
  high: 'var(--color-error)', medium: 'var(--color-warning)', low: 'var(--color-success)',
}

function ConfidenceDonut({ dist, scorePct }) {
  const R = 34, C = 2 * Math.PI * R
  const order = ['AI', 'Mixed', 'Human']
  let offset = 0
  const arcs = order.map((k) => {
    const frac = Math.max(0, Math.min(1, dist?.[k] ?? 0))
    const len = frac * C
    const arc = { k, dash: `${len} ${C - len}`, off: -offset }
    offset += len
    return arc
  })
  return (
    <svg width="92" height="92" viewBox="0 0 92 92" style={{ flexShrink: 0 }}>
      <circle cx="46" cy="46" r={R} fill="none" stroke="var(--color-bg-tertiary)" strokeWidth="9" />
      {arcs.map((a) => (
        <circle
          key={a.k} cx="46" cy="46" r={R} fill="none"
          stroke={SEG[a.k]} strokeWidth="9"
          strokeDasharray={a.dash} strokeDashoffset={a.off}
          transform="rotate(-90 46 46)" strokeLinecap="butt"
        />
      ))}
      <text x="46" y="44" textAnchor="middle" fontSize="17" fontWeight="700" fill="var(--color-text-primary)">
        {scorePct != null ? scorePct : '—'}
      </text>
      <text x="46" y="58" textAnchor="middle" fontSize="9" fill="var(--color-text-muted)">score</text>
    </svg>
  )
}

function Pills({ dist }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {['AI', 'Mixed', 'Human'].map((k) => (
        <span key={k} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border"
          style={{ borderColor: SEG[k], color: 'var(--color-text-secondary)' }}>
          <span style={{ width: 7, height: 7, borderRadius: 7, background: SEG[k] }} />
          {k} {Math.round((dist?.[k] ?? 0) * 100)}%
        </span>
      ))}
    </div>
  )
}

// Three confidence dots (low · mixed · AI); the dot at the sentence's band is
// filled + colored, mirroring the GPTZero per-sentence indicator.
function SentenceDots({ band }) {
  const idx = band === 'high' ? 2 : band === 'medium' ? 1 : 0
  const color = band === 'high' ? SEG.AI : band === 'medium' ? SEG.Mixed : SEG.Human
  return (
    <span className="inline-flex gap-1 flex-shrink-0" title={`${band} likelihood`}>
      {[0, 1, 2].map((i) => (
        <span key={i} style={{
          width: 8, height: 8, borderRadius: 8,
          background: i === idx ? color : 'transparent',
          border: `1.5px solid ${i === idx ? color : 'var(--color-border)'}`,
        }} />
      ))}
    </span>
  )
}

// R02/R03 — a small "view in document" button rendered next to a sentence. It
// routes through the pdf.js stack (DocumentViewer/NativePdfViewer) via the
// parent's onViewSentence callback. Only rendered when canViewSentence(text) is
// true, so it never appears as a dead button for an unlocatable sentence.
function ViewSentenceButton({ text, onViewSentence, canViewSentence, color }) {
  if (typeof onViewSentence !== 'function') return null
  if (typeof canViewSentence === 'function' && !canViewSentence(text)) return null
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onViewSentence(text) }}
      title="Show this sentence highlighted in the document"
      aria-label="View this sentence in the document"
      className="text-xs inline-flex items-center gap-1 flex-shrink-0 font-medium rounded px-1.5 py-0.5 transition-colors focus:outline-none focus:ring-2 hover:bg-[var(--color-bg-secondary)]"
      style={{ color: color || 'var(--color-accent)', background: 'transparent', border: 'none', cursor: 'pointer', '--tw-ring-color': 'var(--color-accent)' }}
    >
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
      </svg>
      View in document
    </button>
  )
}

// One page row: a band bar that expands to per-sentence dots for that page.
function PageRow({ p, onViewSentence, canViewSentence }) {
  const [open, setOpen] = useState(false)
  const sentences = Array.isArray(p.sentences) ? p.sentences : []
  const pct = Math.round((p.score || 0) * 100)
  const color = BAND_COLOR[p.band] || 'var(--color-text-muted)'
  return (
    <div>
      <button type="button" onClick={() => sentences.length && setOpen((o) => !o)}
        className="flex items-center gap-2 w-full text-left"
        style={{ cursor: sentences.length ? 'pointer' : 'default' }}>
        <span className="inline-flex items-center" style={{ width: 12, color: 'var(--color-text-muted)' }}>
          {sentences.length > 0 && (
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"
              style={{ transform: open ? 'none' : 'rotate(-90deg)', transition: 'transform 150ms ease' }}><polyline points="6 9 12 15 18 9" /></svg>
          )}
        </span>
        <span className="text-xs tabular-nums" style={{ color: 'var(--color-text-muted)', minWidth: 44 }}>Page {p.page}</span>
        <span className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-bg-tertiary)' }}>
          <span style={{ display: 'block', width: `${pct}%`, height: '100%', background: color }} />
        </span>
        <span className="text-xs tabular-nums" style={{ color, minWidth: 26, textAlign: 'right' }}>{pct}</span>
      </button>
      {open && sentences.length > 0 && (
        <div className="mt-1.5 mb-2 ml-6 space-y-1.5">
          {sentences.map((s, i) => {
            const sBand = s.band || (s.is_flagged ? 'high' : 'low')
            return (
              <div key={i} className="flex items-start gap-2 text-sm">
                <SentenceDots band={sBand} />
                <span className="flex-1" style={{ color: 'var(--color-text-secondary)' }}>{s.text}</span>
                <ViewSentenceButton
                  text={s.text}
                  onViewSentence={onViewSentence}
                  canViewSentence={canViewSentence}
                  color={BAND_COLOR[sBand] || 'var(--color-accent)'}
                />
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function SentenceList({ sentences, accent, onViewSentence, canViewSentence }) {
  if (!sentences?.length) return <div className="text-xs px-1 py-2" style={{ color: 'var(--color-text-muted)' }}>No sentences to show.</div>
  return (
    <ul className="space-y-1.5">
      {sentences.map((s, i) => {
        const pct = typeof s.score === 'number' ? Math.round(s.score * 100) : null
        return (
          <li key={i} className="text-sm rounded px-2 py-1.5 flex items-start justify-between gap-2 border-l-2"
            style={{ borderColor: accent, backgroundColor: 'var(--color-bg-tertiary)' }}>
            <span className="flex-1" style={{ color: 'var(--color-text-primary)' }}>{s.text}</span>
            <div className="flex items-center gap-2 flex-shrink-0">
              <ViewSentenceButton
                text={s.text}
                onViewSentence={onViewSentence}
                canViewSentence={canViewSentence}
                color={accent}
              />
              {pct != null && (
                <span className="text-xs font-semibold px-1.5 rounded"
                  style={{ color: accent }} title="This sentence's own model score — not a probability a human wrote it">
                  {pct}
                </span>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export default function AIDetectionVisuals({ detection, onViewSentence, canViewSentence }) {
  const [tab, setTab] = useState('ai') // 'ai' | 'human'
  const [showSentences, setShowSentences] = useState(false) // collapsed by default
  const dist = detection?.probability_distribution
  const pages = detection?.per_page_scores || []
  const topAi = detection?.top_ai_sentences || []
  const topHuman = detection?.top_human_sentences || []
  const scorePct = typeof detection?.overall_score === 'number' ? Math.round(detection.overall_score * 100) : null
  if (!dist && pages.length === 0 && topAi.length === 0 && topHuman.length === 0) return null

  return (
    <div className="px-3 pb-3 space-y-3">
      {/* Donut + pills */}
      {dist && (
        <div className="flex items-center gap-3">
          <ConfidenceDonut dist={dist} scorePct={scorePct} />
          <div className="space-y-1.5">
            <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
              Distribution of model scores across text windows
            </div>
            <Pills dist={dist} />
          </div>
        </div>
      )}

      {/* Page-by-page bands */}
      {pages.length > 0 && (
        <div>
          <div className="text-xs mb-1" style={{ color: 'var(--color-text-muted)' }}>
            Page-by-page <span title="Heuristic ~500-word pages, not exact PDF pages">(≈500-word pages)</span> · click a page for its sentences
          </div>
          <div className="space-y-1">
            {pages.map((p) => (
              <PageRow key={p.page} p={p} onViewSentence={onViewSentence} canViewSentence={canViewSentence} />
            ))}
          </div>
        </div>
      )}

      {/* Top AI / Human sentences — collapsible (off by default to reduce clutter) */}
      {(topAi.length > 0 || topHuman.length > 0) && (
        <div>
          <button
            type="button"
            onClick={() => setShowSentences(s => !s)}
            aria-expanded={showSentences}
            className="flex items-center gap-1.5 text-xs font-medium mb-2"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
              style={{ transform: showSentences ? 'none' : 'rotate(-90deg)', transition: 'transform 160ms ease' }}>
              <polyline points="6 9 12 15 18 9" />
            </svg>
            Top AI / Human sentences
            <span style={{ color: 'var(--color-text-muted)' }}>({topAi.length + topHuman.length})</span>
          </button>
          {showSentences && (
          <>
          <div className="flex items-center gap-1.5 mb-2">
            <button type="button" onClick={() => setTab('ai')}
              className="text-xs px-2.5 py-1 rounded-full border transition-colors"
              style={tab === 'ai'
                ? { background: 'var(--color-text-primary)', color: 'var(--color-bg-primary)', borderColor: 'var(--color-text-primary)' }
                : { background: 'transparent', color: 'var(--color-text-secondary)', borderColor: 'var(--color-border)' }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: 7, background: SEG.AI, marginRight: 5 }} />
              Top AI sentences
            </button>
            <button type="button" onClick={() => setTab('human')}
              className="text-xs px-2.5 py-1 rounded-full border transition-colors"
              style={tab === 'human'
                ? { background: 'var(--color-text-primary)', color: 'var(--color-bg-primary)', borderColor: 'var(--color-text-primary)' }
                : { background: 'transparent', color: 'var(--color-text-secondary)', borderColor: 'var(--color-border)' }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: 7, background: SEG.Human, marginRight: 5 }} />
              Top Human sentences
            </button>
          </div>
          {tab === 'ai'
            ? <SentenceList sentences={topAi} accent={SEG.AI} onViewSentence={onViewSentence} canViewSentence={canViewSentence} />
            : <SentenceList sentences={topHuman} accent={SEG.Human} onViewSentence={onViewSentence} canViewSentence={canViewSentence} />}
          </>
          )}
        </div>
      )}
    </div>
  )
}
