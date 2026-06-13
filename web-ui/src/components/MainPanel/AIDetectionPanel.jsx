import { useState } from 'react'

/**
 * Document-level AI-generated-text detection result for a single manuscript.
 *
 * Honesty-first by design: it shows a low/med/high *likelihood band* (never a
 * binary "AI-written" verdict), a permanent disclaimer, and renders the
 * abstain ("inconclusive"/"unavailable") states distinctly from "low". Suspect
 * passages are advisory excerpts, not per-sentence accusations.
 */

// Semantic theme tokens (flip correctly between light/dark) — high reuses the
// error palette, medium the warning palette, low the success palette, and the
// abstain states the neutral surfaces, matching every other status surface.
const BAND_STYLES = {
  high:   { label: 'AI-likelihood: High',   bg: 'var(--color-error-bg)',   fg: 'var(--color-error)',   dot: 'var(--color-error)' },
  medium: { label: 'AI-likelihood: Medium', bg: 'var(--color-warning-bg)', fg: 'var(--color-warning)', dot: 'var(--color-warning)' },
  low:    { label: 'AI-likelihood: Low',    bg: 'var(--color-success-bg)', fg: 'var(--color-success)', dot: 'var(--color-success)' },
  inconclusive: { label: 'Inconclusive', bg: 'var(--color-bg-tertiary)', fg: 'var(--color-text-muted)', dot: 'var(--color-text-muted)' },
  unavailable:  { label: 'Not analyzed',  bg: 'var(--color-bg-tertiary)', fg: 'var(--color-text-muted)', dot: 'var(--color-text-muted)' },
}

const ABSTAIN_REASONS = {
  too_short: 'The manuscript body is too short to assess reliably (under ~300 words).',
  technical_section: 'The text is mostly equations, code, or citations — not reliable terrain for detection.',
  insufficient_signal: 'There was not enough reliable signal to produce a score.',
  model_not_installed: 'The local detection model is not downloaded. Download it in Settings → AI Detection.',
  deps_not_installed: 'The local detection runtime is not installed. See Settings → AI Detection.',
  model_load_failed: 'The local detection model failed to load.',
  inference_failed: 'The local detection model failed to run.',
  llm_not_configured: 'No LLM is configured for the LLM-judge backend — set one up in Settings → LLM.',
  llm_call_failed: 'The LLM-judge request failed.',
  api_key_missing: 'No API key was provided for the selected detection service.',
  consent_required: 'Sending text to an external service requires explicit consent (enable it in Settings).',
  requests_missing: 'The HTTP client needed for the API backend is unavailable.',
  api_call_failed: 'The external detection service did not respond successfully.',
  timeout: 'Detection timed out and was skipped — the reference check still completed.',
  detection_error: 'Detection could not complete.',
  unknown_backend: 'The selected detection backend is unknown.',
}

export default function AIDetectionPanel({ detection }) {
  const [open, setOpen] = useState(false)
  if (!detection) return null

  const band = detection.band || 'unavailable'
  const style = BAND_STYLES[band] || BAND_STYLES.unavailable
  const isAbstain = band === 'inconclusive' || band === 'unavailable'
  const spans = Array.isArray(detection.spans) ? detection.spans : []
  const reason = detection.abstain_reason ? ABSTAIN_REASONS[detection.abstain_reason] : null
  const scorePct = typeof detection.overall_score === 'number'
    ? Math.round(detection.overall_score * 100)
    : null

  return (
    <div
      className="mb-4 rounded-lg border"
      style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
    >
      <div className="flex items-center justify-between gap-2 px-3 py-2 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-semibold"
            style={{ backgroundColor: style.bg, color: style.fg }}
          >
            <span style={{ width: 8, height: 8, borderRadius: 999, backgroundColor: style.dot }} />
            {style.label}
          </span>
          {!isAbstain && scorePct != null && (
            <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}
              title="Model score, not a probability that a human wrote this">
              score {scorePct}
            </span>
          )}
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            AI text check
            {detection.backend_used ? ` · ${detection.backend_used}` : ''}
            {detection.model_version ? ` · ${detection.model_version}` : ''}
          </span>
        </div>
        {spans.length > 0 && !isAbstain && (
          <button
            type="button"
            onClick={() => setOpen(o => !o)}
            aria-expanded={open}
            aria-controls="ai-detection-spans"
            className="text-xs underline focus:outline-none focus:ring-2 rounded"
            style={{ color: 'var(--color-accent)', '--tw-ring-color': 'var(--color-accent)' }}
          >
            {open ? 'Hide' : `Show ${spans.length} flagged passage${spans.length === 1 ? '' : 's'}`}
          </button>
        )}
      </div>

      <div className="px-3 pb-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
        {isAbstain ? (reason || detection.summary) : detection.summary}
      </div>

      {open && spans.length > 0 && (
        <div id="ai-detection-spans" className="px-3 pb-2 space-y-2">
          {spans.map((sp, i) => (
            <div
              key={i}
              className="text-sm rounded px-2 py-1.5 border-l-2"
              style={{
                borderColor: style.dot,
                backgroundColor: 'var(--color-bg-tertiary)',
              }}
            >
              <div style={{ color: 'var(--color-text-primary)' }}>“{sp.quote}”</div>
              {sp.reason && (
                <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                  {sp.reason}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Permanent, non-dismissable honesty disclaimer. */}
      <div
        className="px-3 py-2 text-xs rounded-b-lg border-t"
        style={{
          borderColor: 'var(--color-border)',
          color: 'var(--color-text-muted)',
          backgroundColor: 'var(--color-bg-tertiary)',
        }}
      >
        ⚠ {detection.disclaimer}
        {detection.operating_point ? ` (${detection.operating_point})` : ''}
      </div>
    </div>
  )
}
