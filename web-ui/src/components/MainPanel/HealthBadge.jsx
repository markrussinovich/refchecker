import { useEffect, useMemo, useRef, useState } from 'react'
import anime from 'animejs'
import { filterIssuesForStyle } from '../../utils/formatters'
import { useStyleStore } from '../../stores/useStyleStore'
import { getEffectiveReferenceStatus } from '../../utils/referenceStatus'

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * Minimal "Citation health" chip. Live — recomputes on every edit because
 * it's derived from the current `references` prop. Pure CSS, matches the
 * app theme; intentionally NOT an SVG (user feedback: "minimalistic
 * design not svg"). Hover for the per-status breakdown.
 *
 * Style-aware: when the active citation style would suppress some
 * issues (style-conforming author count, NLM venue abbreviations,
 * cosmetic-only differences), those issues are excluded from the
 * error/warning counts so the score moves when the user flips the
 * dropdown. Matches what the Corrections view shows.
 */

function computeScore(references, style) {
  const list = Array.isArray(references) ? references : []
  const total = list.length
  if (total === 0) return { score: null, total: 0 }

  let verified = 0
  let halluc = 0
  let errors = 0
  let warnings = 0
  for (const r of list) {
    // Style-filter errors/warnings first, then derive the effective
    // status from the filtered view — this matches what
    // StatsSection's Summary chips show. Counting `verified` off the
    // RAW r.status would diverge from the chips: a ref whose only
    // warning is a style-suppressed venue mismatch reads as
    // "verified" in the chips (effective status) but as "warning" in
    // raw status, which is why the badge sat at 92% while the chips
    // showed 9/0/0.
    const styleFilteredErrors = filterIssuesForStyle(r?.errors, r, style)
    const styleFilteredWarnings = filterIssuesForStyle(r?.warnings, r, style)
    const filteredRef = (styleFilteredErrors === r?.errors && styleFilteredWarnings === r?.warnings)
      ? r
      : { ...r, errors: styleFilteredErrors, warnings: styleFilteredWarnings }
    const effective = getEffectiveReferenceStatus(filteredRef, true)
    if (effective === 'verified') verified += 1
    if (effective === 'hallucination' || effective === 'hallucinated' ||
        r?.hallucination_assessment?.verdict?.toUpperCase?.() === 'LIKELY') {
      halluc += 1
    }
    // Bucket on the SAME effective status StatsSection's chips derive
    // (`computeReferenceStats` increments `withErrors`/`withWarnings` off
    // `getEffectiveReferenceStatus`, not off raw `.errors`/`.warnings`).
    // Two divergences this fixes vs. the old raw-length bucketing:
    //   1. unverified-only refs ({error_type:'unverified'}) are NOT errors —
    //      effective status is 'unverified', so the chip excludes them; the
    //      old `.length > 0` test counted them as errors (off-by-N).
    //   2. hallucinated refs carry error entries as evidence; the chip
    //      suppresses those and counts the ref only in the hallucination
    //      bucket. Effective status 'hallucination' keeps them out of
    //      errors/warnings here too. The old block ran unconditionally and
    //      double-counted them as BOTH halluc and error.
    // A ref with both errors and warnings resolves to 'error' (precedence in
    // getEffectiveReferenceStatus), so it's an error ref only — never also a
    // warning ref. This makes HealthBadge counts == StatsSection chip counts.
    if (effective === 'error') errors += 1
    else if (effective === 'warning') warnings += 1
  }
  // Score weights: verified contributes 70, clean contributes 30 — sums
  // to 100 when every ref is verified + clean (was 70+25=95, capping
  // the badge at 95% even with zero issues). Warnings shave up to 5
  // off, hallucinations get a steeper penalty.
  const verifyRatio = verified / total
  const cleanRatio = (total - errors - halluc) / total
  const raw = verifyRatio * 70 + cleanRatio * 30 - (warnings / total) * 5
  const penalty = halluc > 0 ? Math.min(20, 8 + halluc * 4) : 0
  const score = Math.max(0, Math.min(100, Math.round(raw - penalty)))
  return { score, total, verified, halluc, errors, warnings }
}

function colorFor(score) {
  if (score == null) return 'var(--color-text-muted)'
  if (score >= 90) return '#22c55e'
  if (score >= 70) return '#84cc16'
  if (score >= 50) return '#f59e0b'
  if (score >= 30) return '#f97316'
  return '#ef4444'
}

export default function HealthBadge({ references }) {
  const activeFormat = useStyleStore(s => s.format)
  const stats = useMemo(() => computeScore(references, activeFormat), [references, activeFormat])
  const color = colorFor(stats.score)

  // anime.js count-up: the score ticks from its previous value to the new one
  // when references change (e.g. after "apply all fixes"). Reduced-motion users
  // see the final number immediately. Snapshot kept in a ref to avoid re-anim
  // on unrelated re-renders.
  const [shown, setShown] = useState(stats.score)
  const prev = useRef(stats.score)
  useEffect(() => {
    const target = stats.score
    if (target == null) { setShown(null); prev.current = null; return undefined }
    if (prefersReducedMotion() || prev.current == null) { setShown(target); prev.current = target; return undefined }
    const obj = { v: prev.current }
    const anim = anime({
      targets: obj, v: target, duration: 650, easing: 'easeOutCubic', round: 1,
      update: () => setShown(Math.round(obj.v)),
      complete: () => { prev.current = target },
    })
    return () => anim.pause()
  }, [stats.score])
  const tooltip = stats.total === 0
    ? 'No references checked yet'
    : `${stats.verified || 0} verified · ${stats.warnings || 0} warning${stats.warnings === 1 ? '' : 's'} · ${stats.errors || 0} error${stats.errors === 1 ? '' : 's'}${stats.halluc ? ` · ${stats.halluc} likely hallucinated` : ''} · ${stats.total} total`

  return (
    <span
      title={tooltip}
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium"
      style={{
        border: '1px solid var(--color-border)',
        background: 'var(--color-bg-tertiary)',
        color: 'var(--color-text-secondary)',
        lineHeight: 1.4,
      }}
    >
      <span
        className="inline-block rounded-full"
        style={{ width: 6, height: 6, background: color }}
      />
      <span style={{ color: 'var(--color-text-secondary)' }}>Citation health</span>
      <span style={{ color, fontWeight: 600 }}>
        {shown == null ? '—' : `${shown}%`}
      </span>
    </span>
  )
}
