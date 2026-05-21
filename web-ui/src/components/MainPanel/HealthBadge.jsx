import { useMemo } from 'react'

/**
 * Minimal "Citation health" chip. Live — recomputes on every edit because
 * it's derived from the current `references` prop, no fetch.
 *
 * Designed to sit inline with the Summary tiles. No buttons, no SVG
 * download — those moved out by user request ("Grammarly-style chip,
 * keep it minimal"). The score breakdown shows on hover via title attr.
 */

function computeScore(references) {
  const list = Array.isArray(references) ? references : []
  const total = list.length
  if (total === 0) return { score: 100, total: 0 }

  let verified = 0
  let halluc = 0
  let errors = 0
  let warnings = 0
  for (const r of list) {
    const status = r?.status || ''
    if (status === 'verified') verified += 1
    if (status === 'hallucinated' || r?.hallucination_assessment?.verdict?.toUpperCase?.() === 'LIKELY') halluc += 1
    if ((r?.errors || []).length > 0) errors += 1
    if ((r?.warnings || []).length > 0) warnings += 1
  }
  const verifyRatio = verified / total
  const cleanRatio = (total - errors - halluc) / total
  const raw = verifyRatio * 70 + cleanRatio * 25 - (warnings / total) * 5
  const penalty = halluc > 0 ? Math.min(20, 8 + halluc * 4) : 0
  const score = Math.max(0, Math.round(raw - penalty))
  return { score, total, verified, halluc, errors, warnings }
}

function colorFor(score) {
  if (score >= 90) return '#22c55e'
  if (score >= 70) return '#84cc16'
  if (score >= 50) return '#f59e0b'
  if (score >= 30) return '#f97316'
  return '#ef4444'
}

export default function HealthBadge({ references, compact = true }) {
  const stats = useMemo(() => computeScore(references), [references])
  // When there are no references yet, an inflated "100%" score is misleading
  // (the user sees a green pill on an empty check). Render a neutral "—"
  // pill instead until we have data to score.
  if (!stats.total) {
    return (
      <span
        title="No references checked yet"
        className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
        style={{
          border: '1px solid var(--color-border)',
          background: 'var(--color-bg-tertiary)',
          color: 'var(--color-text-muted)',
        }}
      >
        <span
          className="inline-block rounded-full"
          style={{ width: 8, height: 8, background: 'var(--color-text-muted)' }}
        />
        Citation health
        <span style={{ fontWeight: 600 }}>—</span>
      </span>
    )
  }

  const color = colorFor(stats.score)
  const tooltip = `${stats.verified || 0} verified · ${stats.warnings || 0} warning${stats.warnings === 1 ? '' : 's'} · ${stats.errors || 0} error${stats.errors === 1 ? '' : 's'}${stats.halluc ? ` · ${stats.halluc} likely hallucinated` : ''} · ${stats.total} total`

  return (
    <span
      title={tooltip}
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
      style={{
        border: `1px solid ${color}55`,
        background: `${color}14`,
        color: 'var(--color-text-primary)',
      }}
    >
      <span
        className="inline-block rounded-full"
        style={{ width: 8, height: 8, background: color }}
      />
      Citation health
      <span style={{ color, fontWeight: 700 }}>{stats.score}%</span>
    </span>
  )
}
