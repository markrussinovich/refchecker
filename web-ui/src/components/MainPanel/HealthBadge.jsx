import { useMemo, useState } from 'react'

/**
 * Live SVG "Citation health" badge. Recomputes on every edit (Apply Fix /
 * Add / Remove / Suggest) because it's derived from the current
 * `references` prop — no fetch, no async. Rendered as an actual
 * shields.io-shaped <svg> element (not a styled HTML span), so the same
 * markup can be copied to clipboard or saved to disk and still be a
 * valid SVG you can embed in a README or PR description.
 */

function computeScore(references) {
  const list = Array.isArray(references) ? references : []
  const total = list.length
  if (total === 0) return { score: null, total: 0 }

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
  if (score == null) return '#9ca3af'
  if (score >= 90) return '#22c55e'
  if (score >= 70) return '#84cc16'
  if (score >= 50) return '#f59e0b'
  if (score >= 30) return '#f97316'
  return '#ef4444'
}

// Build a shields.io-shaped SVG string. Sized to look natural inline at
// 14px height (matches surrounding text), but the same SVG scales cleanly
// when pasted into a README at default sizes.
export function buildBadgeSvgString({ score, total }) {
  const right = score == null ? '—' : `${score}%`
  const left = 'citation health'
  const color = colorFor(score)
  // Measure-free layout: monospace-ish width estimate. Use ch units via
  // hardcoded widths that look right for the system font.
  const leftW = 92
  const rightW = right.length > 3 ? 50 : 40
  const W = leftW + rightW
  const H = 20
  const titleAttr = total === 0
    ? 'Citation health: no references yet'
    : `Citation health: ${right} across ${total} references`
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" role="img" aria-label="${titleAttr}">
  <title>${titleAttr}</title>
  <linearGradient id="rcg" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <mask id="rcm"><rect width="${W}" height="${H}" rx="3" fill="#fff"/></mask>
  <g mask="url(#rcm)">
    <rect width="${leftW}" height="${H}" fill="#555"/>
    <rect x="${leftW}" width="${rightW}" height="${H}" fill="${color}"/>
    <rect width="${W}" height="${H}" fill="url(#rcg)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="-apple-system,Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="${leftW / 2}" y="14">${left}</text>
    <text x="${leftW + rightW / 2}" y="14">${right}</text>
  </g>
</svg>`
}

export default function HealthBadge({ references }) {
  const stats = useMemo(() => computeScore(references), [references])
  const [copied, setCopied] = useState(null)

  const svgString = buildBadgeSvgString(stats)
  const tooltip = stats.total === 0
    ? 'No references checked yet'
    : `${stats.verified || 0} verified · ${stats.warnings || 0} warning${stats.warnings === 1 ? '' : 's'} · ${stats.errors || 0} error${stats.errors === 1 ? '' : 's'}${stats.halluc ? ` · ${stats.halluc} likely hallucinated` : ''} · ${stats.total} total`

  const copyMarkdown = async (e) => {
    e?.stopPropagation?.()
    try {
      const b64 = typeof window !== 'undefined' ? btoa(unescape(encodeURIComponent(svgString))) : ''
      const md = `![citation health: ${stats.score ?? '—'}%](data:image/svg+xml;base64,${b64})`
      await navigator.clipboard.writeText(md)
      setCopied('md')
      setTimeout(() => setCopied(null), 1500)
    } catch { /* clipboard unavailable */ }
  }

  return (
    <span
      title={tooltip}
      className="inline-flex items-center gap-1"
      onClick={copyMarkdown}
      style={{ cursor: 'copy', verticalAlign: 'middle' }}
    >
      <span
        // Inline SVG via dangerouslySetInnerHTML so the same string we
        // copy to clipboard is the same one rendering on screen.
        // The badge IS the source of truth.
        dangerouslySetInnerHTML={{ __html: svgString }}
        style={{ display: 'inline-flex' }}
      />
      <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)' }}>
        {copied === 'md' ? 'copied!' : ''}
      </span>
    </span>
  )
}
