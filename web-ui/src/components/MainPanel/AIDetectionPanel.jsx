import { useState } from 'react'
import DocumentViewer from './DocumentViewer'
import AIDetectionVisuals from './AIDetectionVisuals'
import { isTauri, openExternal } from '../../utils/tauriBridge'

// Derive a citation link for the local detection model from its version
// string (e.g. "local:desklib/ai-text-detector-v1.01" → the HF repo).
function deriveModelCitation(detection) {
  const v = detection?.model_version || ''
  const m = v.match(/^local:(.+)$/)
  if (!m) return null
  const repo = m[1]
  if (!repo.includes('/')) return null
  return { repo, url: `https://huggingface.co/${repo}` }
}

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
  no_body_text: 'No manuscript body text was available to analyze — the references were read from a structured source (a .bbl/.bib file or a DOI lookup), so the full text was not extracted. AI detection needs the article body.',
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

export default function AIDetectionPanel({ detection, checkId }) {
  const [open, setOpen] = useState(false)
  const [viewerOpen, setViewerOpen] = useState(false)
  const [focusIdx, setFocusIdx] = useState(null)
  if (!detection) return null

  const band = detection.band || 'unavailable'
  const style = BAND_STYLES[band] || BAND_STYLES.unavailable
  const isAbstain = band === 'inconclusive' || band === 'unavailable'
  const spans = Array.isArray(detection.spans) ? detection.spans : []
  const reason = detection.abstain_reason ? ABSTAIN_REASONS[detection.abstain_reason] : null
  const scorePct = typeof detection.overall_score === 'number'
    ? Math.round(detection.overall_score * 100)
    : null
  const modelCitation = deriveModelCitation(detection)

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
          <div className="flex items-center gap-3">
            {checkId != null && (
              <button
                type="button"
                onClick={() => setViewerOpen(true)}
                className="text-xs px-2.5 py-1 rounded-md inline-flex items-center gap-1.5 font-medium transition-colors focus:outline-none focus:ring-2"
                style={{ background: 'var(--color-accent)', color: '#fff', border: 'none', '--tw-ring-color': 'var(--color-accent)' }}
                title="Show the flagged passages highlighted in the document text"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
                View in document
              </button>
            )}
            <button
              type="button"
              onClick={() => setOpen(o => !o)}
              aria-expanded={open}
              aria-controls="ai-detection-spans"
              className="text-xs px-2.5 py-1 rounded-md border inline-flex items-center gap-1 transition-colors focus:outline-none focus:ring-2 hover:bg-[var(--color-bg-tertiary)]"
              style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary)', color: 'var(--color-text-primary)', '--tw-ring-color': 'var(--color-accent)' }}
            >
              {open ? 'Hide' : `Show ${spans.length} flagged passage${spans.length === 1 ? '' : 's'}`}
            </button>
          </div>
        )}
      </div>
      {viewerOpen && (
        <DocumentViewer
          checkId={checkId}
          spans={spans}
          focusSpanIndex={focusIdx}
          onClose={() => { setViewerOpen(false); setFocusIdx(null) }}
        />
      )}

      <div className="px-3 pb-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
        {isAbstain ? (reason || detection.summary) : detection.summary}
        {detection.abstain_detail && (
          <div
            className="mt-1.5 text-xs font-mono rounded px-2 py-1.5 overflow-x-auto"
            style={{ color: 'var(--color-text-muted)', backgroundColor: 'var(--color-bg-tertiary)' }}
            title="Underlying error — useful for troubleshooting"
          >
            {detection.abstain_detail}
          </div>
        )}
      </div>

      {!isAbstain && <AIDetectionVisuals detection={detection} />}

      {open && spans.length > 0 && (
        <div id="ai-detection-spans" className="px-3 pb-2 space-y-2">
          {spans.map((sp, i) => {
            const pct = typeof sp.model_score === 'number' ? Math.round(sp.model_score * 100) : null
            const clickable = checkId != null
            return (
              <div
                key={i}
                role={clickable ? 'button' : undefined}
                tabIndex={clickable ? 0 : undefined}
                onClick={clickable ? () => { setFocusIdx(i); setViewerOpen(true) } : undefined}
                onKeyDown={clickable ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFocusIdx(i); setViewerOpen(true) } } : undefined}
                title={clickable ? 'Show this passage in the document' : undefined}
                className="text-sm rounded px-2 py-1.5 border-l-2"
                style={{
                  borderColor: style.dot,
                  backgroundColor: 'var(--color-bg-tertiary)',
                  cursor: clickable ? 'pointer' : undefined,
                }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div style={{ color: 'var(--color-text-primary)' }}>“{sp.quote}”</div>
                  {pct != null && (
                    <span
                      className="text-xs font-semibold flex-shrink-0 px-1.5 rounded"
                      style={{ color: style.fg, backgroundColor: style.bg }}
                      title="This passage's own model score — not a probability that a human wrote it"
                    >
                      {pct}
                    </span>
                  )}
                </div>
                {sp.reason && (
                  <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                    {sp.reason}
                  </div>
                )}
                {clickable && (
                  <div className="text-xs mt-1.5 inline-flex items-center gap-1 font-medium" style={{ color: 'var(--color-accent)' }}>
                    View in document
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
                    </svg>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Permanent, non-dismissable honesty disclaimer + model attribution. */}
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
        {modelCitation && (
          <div className="mt-1">
            Local model:{' '}
            <a
              href={modelCitation.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => { if (isTauri()) { e.preventDefault(); openExternal(modelCitation.url) } }}
              style={{ color: 'var(--color-link, #3b82f6)', textDecoration: 'underline' }}
            >
              {modelCitation.repo}
            </a>
            {' '}(DeBERTa-v3, MIT) — by Desklib, via Hugging Face.
          </div>
        )}
      </div>
    </div>
  )
}
