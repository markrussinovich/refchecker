/**
 * R14 (D5) — One shared, complete status→color map across all viewers.
 *
 * Single source of truth for the translucent highlight fill + stroke used to
 * color-code passages/citations by their chaining/verification status. Keyed to
 * the FULL status set produced by `ReferenceCard.getStatusColor`
 * (ReferenceCard.jsx:408-421):
 *
 *   verified, error, warning, suggestion, hallucination (+ `hallucinated`
 *   alias), unverified, checking, pending, unchecked
 *
 * Hue parity with the reference-card palette / CSS theme vars:
 *   verified   → success/green   (--color-success #10a37f)
 *   error      → red             (--color-error)
 *   warning    → amber           (--color-warning #f59e0b)
 *   suggestion → violet          (--color-suggestion #8b5cf6)
 *   hallucination → orange       (--color-hallucination #dc6b1d)  [+ hallucinated]
 *   unverified / pending / unchecked → muted slate (--color-text-muted)
 *   checking   → accent/teal     (--color-accent #10a37f)
 *
 * Highlights are drawn as translucent overlays on rasterized page images / over
 * the pdf.js text layer, so this map uses rgba() literals (the opaque theme hex
 * vars can't express the needed alpha). `default` is the fallback for any
 * unknown/empty status so a highlight never renders invisible.
 */

export const STATUS_COLORS = Object.freeze({
  verified: { fill: 'rgba(16,185,129,0.30)', stroke: 'rgba(16,185,129,0.95)' },
  error: { fill: 'rgba(239,68,68,0.32)', stroke: 'rgba(220,38,38,0.95)' },
  warning: { fill: 'rgba(245,158,11,0.32)', stroke: 'rgba(202,138,4,0.95)' },
  suggestion: { fill: 'rgba(139,92,246,0.30)', stroke: 'rgba(124,58,237,0.95)' },
  hallucination: { fill: 'rgba(220,107,29,0.32)', stroke: 'rgba(194,89,16,0.95)' },
  unverified: { fill: 'rgba(148,163,184,0.30)', stroke: 'rgba(100,116,139,0.85)' },
  checking: { fill: 'rgba(16,163,127,0.26)', stroke: 'rgba(16,163,127,0.9)' },
  pending: { fill: 'rgba(148,163,184,0.26)', stroke: 'rgba(100,116,139,0.8)' },
  unchecked: { fill: 'rgba(148,163,184,0.26)', stroke: 'rgba(100,116,139,0.8)' },
  default: { fill: 'rgba(148,163,184,0.28)', stroke: 'rgba(100,116,139,0.85)' },
})

/**
 * Aliases that normalize to a canonical status key. `hallucinated` is the past
 * tense the backend/UI sometimes emits for `hallucination`.
 */
const STATUS_ALIASES = Object.freeze({
  hallucinated: 'hallucination',
})

/**
 * Normalize an arbitrary status value to a canonical key in STATUS_COLORS.
 * Lowercases + trims (defensive; some callers already lowercase), resolves
 * aliases (`hallucinated`→`hallucination`), and falls back to `default` for
 * empty/unknown values.
 *
 * @param {string} [status]
 * @returns {keyof STATUS_COLORS}
 */
export function normalizeStatus(status) {
  const key = String(status || '').trim().toLowerCase()
  if (!key) return 'default'
  const resolved = STATUS_ALIASES[key] || key
  return Object.prototype.hasOwnProperty.call(STATUS_COLORS, resolved) ? resolved : 'default'
}

/**
 * Get the `{ fill, stroke }` highlight colors for a status. Always returns a
 * valid pair (never undefined) so a highlight is never rendered invisible.
 *
 * @param {string} [status]
 * @returns {{ fill: string, stroke: string }}
 */
export function getStatusColors(status) {
  return STATUS_COLORS[normalizeStatus(status)]
}

export default getStatusColors
