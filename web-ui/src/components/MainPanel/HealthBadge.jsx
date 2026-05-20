import { useMemo } from 'react'

/**
 * Live "Citation health" SVG badge. Updates on every reference edit
 * (add/remove/apply/reject) because it's derived directly from the
 * current `references` prop — no separate fetch.
 *
 * Score = (verified / total)² weighted, minus a hallucination penalty.
 * It's a heuristic, but it makes Apply / Remove decisions feel
 * meaningful in real-time.
 *
 * Doubles as a downloadable badge users can paste into README files,
 * blog posts, etc. — same shape as shields.io badges so it slots in
 * next to coverage / build badges.
 */

function computeScore(references) {
  const list = Array.isArray(references) ? references : []
  const total = list.length
  if (total === 0) return { score: 100, total: 0, label: 'no references' }

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
  // 70% from verify ratio, 25% from non-error ratio, 5% subtract for warnings
  const raw = verifyRatio * 70 + cleanRatio * 25 - (warnings / total) * 5
  // Hallucination is a strong penalty — even one tanks the score visibly.
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

export function buildBadgeSVG({ score, total }) {
  const right = `${score}%`
  const left = `citations`
  const color = colorFor(score)
  const W_LEFT = 70
  const W_RIGHT = 50
  const W = W_LEFT + W_RIGHT
  const H = 20
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" role="img" aria-label="Citation health: ${score}% across ${total} refs">
  <linearGradient id="g" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <mask id="m"><rect width="${W}" height="${H}" rx="3" fill="#fff"/></mask>
  <g mask="url(#m)">
    <rect width="${W_LEFT}" height="${H}" fill="#555"/>
    <rect x="${W_LEFT}" width="${W_RIGHT}" height="${H}" fill="${color}"/>
    <rect width="${W}" height="${H}" fill="url(#g)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="-apple-system,Verdana,Geneva,sans-serif" font-size="11">
    <text x="${W_LEFT / 2}" y="14">${left}</text>
    <text x="${W_LEFT + W_RIGHT / 2}" y="14">${right}</text>
  </g>
</svg>`
}

export default function HealthBadge({ references }) {
  const stats = useMemo(() => computeScore(references), [references])

  const downloadBadge = () => {
    const svg = buildBadgeSVG(stats)
    const blob = new Blob([svg], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `refchecker-health-${stats.score}.svg`
    document.body.appendChild(a); a.click(); document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const copyMarkdown = async () => {
    // Markdown snippet users can paste into a README. Embeds the SVG
    // inline so it doesn't require hosting.
    const svg = buildBadgeSVG(stats)
    const dataUri = `data:image/svg+xml;base64,${typeof window !== 'undefined' ? btoa(unescape(encodeURIComponent(svg))) : ''}`
    const md = `![citations: ${stats.score}%](${dataUri})`
    try { await navigator.clipboard.writeText(md) } catch { /* ignore */ }
  }

  return (
    <div
      className="rounded-lg border p-3 flex items-center gap-3 flex-wrap"
      style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
    >
      <div
        className="flex items-center gap-2 px-2 py-1 rounded font-mono text-xs"
        style={{ backgroundColor: '#555', color: 'white' }}
      >
        <span style={{ opacity: 0.85 }}>citations</span>
        <span style={{
          backgroundColor: colorFor(stats.score),
          padding: '2px 8px',
          margin: '-4px -8px -4px 0',
          borderRadius: '0 4px 4px 0',
          fontWeight: 600,
        }}>{stats.score}%</span>
      </div>
      <div className="text-xs flex-1 min-w-0" style={{ color: 'var(--color-text-secondary)' }}>
        {stats.total === 0 ? 'No references yet.' : (
          <>
            <strong style={{ color: 'var(--color-text-primary)' }}>{stats.verified || 0}</strong> verified
            {' · '}{stats.warnings || 0} warning{stats.warnings === 1 ? '' : 's'}
            {' · '}{stats.errors || 0} error{stats.errors === 1 ? '' : 's'}
            {stats.halluc ? <> · <span style={{ color: 'var(--color-hallucination, #a855f7)' }}>{stats.halluc} likely hallucinated</span></> : null}
            {' · '}{stats.total} total — recomputes on each edit
          </>
        )}
      </div>
      <button onClick={copyMarkdown} className="text-xs px-2 py-1 rounded border"
        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)' }}
        type="button" title="Copy a self-contained Markdown badge with the current score embedded">Copy badge</button>
      <button onClick={downloadBadge} className="text-xs px-2 py-1 rounded border"
        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)' }}
        type="button">Download SVG</button>
    </div>
  )
}
