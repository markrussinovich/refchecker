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

function SentenceList({ sentences, accent }) {
  if (!sentences?.length) return <div className="text-xs px-1 py-2" style={{ color: 'var(--color-text-muted)' }}>No sentences to show.</div>
  return (
    <ul className="space-y-1.5">
      {sentences.map((s, i) => {
        const pct = typeof s.score === 'number' ? Math.round(s.score * 100) : null
        return (
          <li key={i} className="text-sm rounded px-2 py-1.5 flex items-start justify-between gap-2 border-l-2"
            style={{ borderColor: accent, backgroundColor: 'var(--color-bg-tertiary)' }}>
            <span style={{ color: 'var(--color-text-primary)' }}>{s.text}</span>
            {pct != null && (
              <span className="text-xs font-semibold flex-shrink-0 px-1.5 rounded"
                style={{ color: accent }} title="This sentence's own model score — not a probability a human wrote it">
                {pct}
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

export default function AIDetectionVisuals({ detection }) {
  const [tab, setTab] = useState('ai') // 'ai' | 'human'
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
            Page-by-page <span title="Heuristic ~500-word pages, not exact PDF pages">(≈500-word pages)</span>
          </div>
          <div className="space-y-1">
            {pages.map((p) => (
              <div key={p.page} className="flex items-center gap-2">
                <span className="text-xs tabular-nums" style={{ color: 'var(--color-text-muted)', minWidth: 48 }}>Page {p.page}</span>
                <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-bg-tertiary)' }}>
                  <div style={{ width: `${Math.round((p.score || 0) * 100)}%`, height: '100%', background: BAND_COLOR[p.band] || 'var(--color-text-muted)' }} />
                </div>
                <span className="text-xs tabular-nums" style={{ color: BAND_COLOR[p.band] || 'var(--color-text-muted)', minWidth: 30, textAlign: 'right' }}>
                  {Math.round((p.score || 0) * 100)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top AI / Human sentences */}
      {(topAi.length > 0 || topHuman.length > 0) && (
        <div>
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
            ? <SentenceList sentences={topAi} accent={SEG.AI} />
            : <SentenceList sentences={topHuman} accent={SEG.Human} />}
        </div>
      )}
    </div>
  )
}
