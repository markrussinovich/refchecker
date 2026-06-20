import { useEffect, useMemo, useState } from 'react'
import DocumentViewer from './DocumentViewer'
import AIDetectionVisuals from './AIDetectionVisuals'
import Button from '../common/Button'
import IconButton from '../common/IconButton'
import LabelSizer from '../common/LabelSizer'
import { isTauri, openExternal } from '../../utils/tauriBridge'
import { downloadAsFile } from '../../utils/formatters'
import { normalizeResultsByDetector } from '../../stores/useAiDetectionStore'

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

// Whitespace/case-fold a sentence so the same passage surfaced in two different
// lists (per-page vs. top-AI) collapses to one viewer span, and so containment
// checks against a span's window-level quote tolerate spacing differences.
const normSentence = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase()

// Build the spans array handed to DocumentViewer plus a lookup from any flagged
// sentence's text to its index in that array.
//
// DocumentViewer locates a passage purely by its `quote` TEXT, so to focus an
// arbitrary flagged sentence we make that sentence its own locatable span. The
// corroborated detection.spans keep indices 0..n-1 (the existing flagged-passage
// buttons already reference those), and each unique sentence is appended after.
// A sentence already contained in a corroborated span reuses that span's index
// instead of duplicating a highlight.
// R29: every span handed to the viewer must carry a `refId` so the on-hover bar
// + in-document link work for ALL spans, not just citation spans. AI/flagged
// sentences don't map to a bibliography entry, so we give each a stable
// self-referential id (`ai:<index>`) keyed to its position in the located-span
// list — the viewer focuses that span's own highlight when it's followed.
function withSpanRefId(span, idx) {
  if (span && span.refId != null) return span
  return { ...span, refId: `ai:${idx}`, kind: span?.kind || 'ai' }
}

function buildViewerSpans(detection) {
  const baseSpans = Array.isArray(detection?.spans) ? detection.spans : []
  const viewerSpans = baseSpans.map((sp, i) => withSpanRefId(sp, i))
  const indexByText = new Map()

  // A sentence drawn from a window may be a substring of a corroborated span's
  // (longer, window-level) quote — reuse that existing span when so.
  const normalizedBase = baseSpans.map((sp) => normSentence(sp?.quote))
  const findInBase = (norm) => {
    if (norm.length < 8) return -1
    return normalizedBase.findIndex((q) => q && (q.includes(norm) || norm.includes(q)))
  }

  const addSentence = (sentence) => {
    const text = sentence?.text
    const norm = normSentence(text)
    if (norm.length < 8) return
    if (indexByText.has(norm)) return
    const reuse = findInBase(norm)
    if (reuse >= 0) { indexByText.set(norm, reuse); return }
    const idx = viewerSpans.length
    indexByText.set(norm, idx)
    // Carry the sentence's real per-sentence model score so the located passage
    // keeps its own number (no fabricated value when the score is absent).
    // R29: a stable self-referential refId so the hover bar + link work here too.
    const span = { quote: text, confidence: 'medium', refId: `ai:${idx}`, kind: 'ai' }
    if (typeof sentence?.score === 'number') span.model_score = sentence.score
    viewerSpans.push(span)
  }

  const pages = Array.isArray(detection?.per_page_scores) ? detection.per_page_scores : []
  pages.forEach((p) => {
    (Array.isArray(p?.sentences) ? p.sentences : []).forEach(addSentence)
  })
  ;(Array.isArray(detection?.top_ai_sentences) ? detection.top_ai_sentences : [])
    .forEach(addSentence)
  ;(Array.isArray(detection?.top_human_sentences) ? detection.top_human_sentences : [])
    .forEach(addSentence)

  return { viewerSpans, indexByText }
}

// R61 — serialize the SELECTED detectors' results into one of the existing
// export shapes (MD / CSV / JSON). Only the checked detectors' results are
// emitted, and only real numbers — a detector that abstained writes its band
// word with no fabricated score. `results` is the { key: result } map; `keys`
// is the checked subset (caller passes exportSelection).
function detectorRow(key, res) {
  const label = res?.label || res?.detector_label || key
  const band = res?.band || 'unavailable'
  const score = typeof res?.overall_score === 'number'
    ? res.overall_score
    : (typeof res?.score === 'number' ? res.score : null)
  return { key, label, band, score, model_version: res?.model_version || null }
}

function serializeDetectorExport(results, keys, fmt = 'json') {
  const picked = (Array.isArray(keys) ? keys : Object.keys(results || {}))
    .filter((k) => results && results[k])
  const rows = picked.map((k) => detectorRow(k, results[k]))

  if (fmt === 'csv') {
    const head = 'detector_key,label,band,score'
    const body = rows.map((r) =>
      [r.key, r.label, r.band, r.score == null ? '' : r.score]
        .map((c) => {
          const s = String(c)
          return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
        })
        .join(',')
    )
    return [head, ...body].join('\n')
  }

  if (fmt === 'md') {
    const lines = ['# AI-text detection — selected detectors', '',
      '| Detector | Band | Score |', '| --- | --- | --- |']
    rows.forEach((r) => {
      lines.push(`| ${r.label} | ${r.band} | ${r.score == null ? '—' : Math.round(r.score * 100)} |`)
    })
    lines.push('', '_Each detector\'s own verdict — no synthetic ensemble score. A dash means the detector abstained._')
    return lines.join('\n')
  }

  // json (default)
  return JSON.stringify({ detectors: rows }, null, 2)
}

const EXPORT_MIME = { md: 'text/markdown', csv: 'text/csv', json: 'application/json' }

// R61 — adapt the backend's comparison summary into the per-sentence agreement
// rows the visuals consume. The backend (src/refchecker/ai_detection/multi_run
// ._comparison_summary) emits `comparison.per_sentence` as
//   { text, bands: { detectorKey: band }, detector_count, agreement_count, ... }
// while DetectorComparison renders `{ text, flagged_by: [keys], detector_count }`
// and shows "how many detectors flagged this sentence". A detector "flagged" a
// sentence when its per-sentence band is AI-ish (medium/high). We DERIVE
// flagged_by from the real per-detector bands — nothing is fabricated; a row
// where no detector landed AI-ish honestly shows 0/N. Falls back to a legacy
// `flagged_by` array if a payload already carries one, and to
// `detection.agreement` for older shapes.
const AI_ISH_BANDS = new Set(['high', 'medium'])
// eslint-disable-next-line react-refresh/only-export-components
export function buildAgreementRows(detection) {
  const rows = detection?.comparison?.per_sentence
    || detection?.comparison?.sentences
    || detection?.agreement
  if (!Array.isArray(rows) || rows.length === 0) return null
  return rows.map((r) => {
    // Already in the expected shape — pass it through untouched.
    if (Array.isArray(r?.flagged_by)) {
      return { text: r.text, flagged_by: r.flagged_by, detector_count: r.detector_count }
    }
    const bands = (r && typeof r.bands === 'object' && r.bands) ? r.bands : {}
    const flaggedBy = Object.keys(bands).filter((k) => AI_ISH_BANDS.has(bands[k]))
    // detector_count = how many detectors ASSESSED the sentence (have a band);
    // flagged_by = the subset that landed AI-ish. The visuals show flagged/total.
    const detectorCount = typeof r?.detector_count === 'number'
      ? r.detector_count
      : Object.keys(bands).length
    return { text: r.text, flagged_by: flaggedBy, detector_count: detectorCount }
  })
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
// BUTTON_DESIGN §4.5: the band fills are repointed from the opaque themed *-bg
// tokens (the brown/red-block look §1.1 warns about) to the new translucent
// --status-*-fill tokens, so the AI dense pill matches the re-check pills
// exactly. fg/dot stay as-is; the abstain bands keep the neutral surface.
const BAND_STYLES = {
  high:   { label: 'AI-likelihood: High',   bg: 'var(--status-error-fill)',   fg: 'var(--color-error)',   dot: 'var(--color-error)' },
  medium: { label: 'AI-likelihood: Medium', bg: 'var(--status-warning-fill)', fg: 'var(--color-warning)', dot: 'var(--color-warning)' },
  low:    { label: 'AI-likelihood: Low',    bg: 'var(--status-success-fill)', fg: 'var(--color-success)', dot: 'var(--color-success)' },
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
  const [collapsed, setCollapsed] = useState(false)
  const [viewerOpen, setViewerOpen] = useState(false)
  const [focusIdx, setFocusIdx] = useState(null)
  const [exportFmt, setExportFmt] = useState('json') // checkbox-export format
  // Combined spans for the viewer: corroborated spans (indices preserved for the
  // flagged-passage buttons) + every flagged sentence made independently
  // locatable, so a "View in document" on any sentence focuses that sentence.
  // Computed before the early return so hooks run in a stable order;
  // buildViewerSpans tolerates a null detection.
  const { viewerSpans, indexByText } = useMemo(() => buildViewerSpans(detection), [detection])

  // R61 — when this detection carries MULTIPLE detectors, build the normalized
  // { key: result } map for the comparison view. A legacy single-detector
  // payload yields a one-entry map (and DetectorComparison no-ops on <2), so the
  // single-detector render path is unchanged.
  const resultsByDetector = useMemo(() => normalizeResultsByDetector(detection), [detection])
  const detectorKeys = useMemo(() => Object.keys(resultsByDetector), [resultsByDetector])
  const isMulti = detectorKeys.length >= 2

  // Checkbox-export selection: every present detector checked by default.
  const [exportSelection, setExportSelection] = useState(detectorKeys)
  useEffect(() => { setExportSelection(detectorKeys) }, [detectorKeys.join('|')]) // eslint-disable-line react-hooks/exhaustive-deps

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

  // Open the native document viewer focused on a specific flagged sentence.
  // Resolves the sentence text to its index in viewerSpans (built above) so the
  // viewer scrolls to + flashes exactly that passage. No-op without a checkId
  // (the viewer needs one to fetch the document text) or an unlocatable
  // sentence — so only real, focusable flagged sentences get a working button.
  const canViewSentence = (text) => checkId != null && indexByText.has(normSentence(text))
  const openSentence = (text) => {
    const idx = indexByText.get(normSentence(text))
    if (checkId == null || idx == null) return
    setFocusIdx(idx)
    setViewerOpen(true)
  }

  // R61 — checkbox-export: serialize ONLY the checked detectors' results into
  // the selected shape (MD/CSV/JSON) and download. Exporting exactly the
  // checked keys means an unchecked detector never lands in the file.
  const toggleExport = (key) =>
    setExportSelection((cur) => cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key])
  const exportSelected = (keys) => {
    const picked = Array.isArray(keys) ? keys : exportSelection
    if (!picked.length) return
    const content = serializeDetectorExport(resultsByDetector, picked, exportFmt)
    downloadAsFile(content, `ai-detection-detectors.${exportFmt}`, EXPORT_MIME[exportFmt] || 'application/json')
  }

  // The comparison props are only meaningful with ≥2 detectors. The agreement
  // array comes from the backend's comparison summary (§14 item 2) — never
  // synthesized here. The backend (multi_run._comparison_summary) emits
  // `comparison.per_sentence` rows shaped { text, bands:{key:band},
  // detector_count, agreement_count }. The visuals expect `flagged_by` (the
  // detectors that landed AI-ish on that sentence), so we adapt the real shape
  // here — deriving flagged_by from the per-detector bands, NOT fabricating it.
  const agreement = isMulti ? buildAgreementRows(detection) : null
  const comparison = isMulti ? {
    results: resultsByDetector,
    order: detectorKeys,
    selection: exportSelection,
    onToggle: toggleExport,
    onExport: exportSelected,
    exportFmt,
    onExportFmtChange: setExportFmt,
    agreement,
  } : null

  return (
    <div
      className="mb-4 rounded-lg border"
      style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
    >
      <div className="flex items-center justify-between gap-2 px-3 py-2 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Collapse chevron — shared IconButton sm (22×22), rotation only, no
              reflow (BUTTON_DESIGN §4.5 / §3.5). Down when expanded, up rotated. */}
          <IconButton
            size="sm"
            chevron
            rotated={!collapsed}
            onClick={() => setCollapsed(c => !c)}
            aria-expanded={!collapsed}
            title={collapsed ? 'Expand AI-text detection' : 'Collapse AI-text detection'}
            className="-ml-1"
            style={{ color: 'var(--color-text-muted)' }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </IconButton>
          {/* Dense status pill (BUTTON_DESIGN §3.5): 22px tall, 8px radius (same
              family), filled by --status-*-fill. min-width holds the widest band
              label so changing band (high/medium/low) never resizes it. */}
          <span
            className="inline-flex items-center gap-1.5 text-xs font-semibold cursor-pointer"
            onClick={() => setCollapsed(c => !c)}
            style={{
              backgroundColor: style.bg, color: style.fg,
              height: 'var(--control-h-sm)', padding: '0 var(--control-pad-x-sm)',
              borderRadius: 'var(--control-radius)', boxSizing: 'border-box',
            }}
          >
            <span style={{ width: 8, height: 8, borderRadius: 999, backgroundColor: style.dot, flex: 'none' }} />
            <LabelSizer candidates={['AI-likelihood: High', 'AI-likelihood: Medium', 'AI-likelihood: Low', 'Inconclusive', 'Not analyzed']}>
              {style.label}
            </LabelSizer>
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
        {spans.length > 0 && !isAbstain && !collapsed && (
          <div className="flex items-center gap-3">
            {checkId != null && (
              <Button
                size="pill"
                variant="primary"
                onClick={() => setViewerOpen(true)}
                icon={(
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                )}
                title="Show the flagged passages highlighted in the document text"
              >
                View in document
              </Button>
            )}
            {/* Sizer-grid holds both Hide↔Show candidates so toggling doesn't jump
                the button width (BUTTON_DESIGN §3.5 / §3.1). */}
            <Button
              size="pill"
              variant="outline"
              onClick={() => setOpen(o => !o)}
              aria-expanded={open}
              aria-controls="ai-detection-spans"
            >
              <LabelSizer candidates={['Hide', `Show ${spans.length} flagged passage${spans.length === 1 ? '' : 's'}`]}>
                {open ? 'Hide' : `Show ${spans.length} flagged passage${spans.length === 1 ? '' : 's'}`}
              </LabelSizer>
            </Button>
          </div>
        )}
      </div>
      {viewerOpen && (
        <DocumentViewer
          checkId={checkId}
          spans={viewerSpans}
          focusSpanIndex={focusIdx}
          onClose={() => { setViewerOpen(false); setFocusIdx(null) }}
        />
      )}

      {!collapsed && (
      <>
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

      {/* The comparison view stands on its own (multi-detector); the single-
          detector visuals still render when the top-level detection is not an
          abstain. With ≥2 detectors the comparison shows even if the aggregate
          band abstains, so the per-detector verdicts are never hidden. */}
      {(!isAbstain || isMulti) && (
        <AIDetectionVisuals
          detection={detection}
          onViewSentence={openSentence}
          canViewSentence={canViewSentence}
          comparison={comparison}
        />
      )}

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
                      className="text-xs font-semibold flex-shrink-0 px-1.5 rounded-[8px]"
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
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setFocusIdx(i); setViewerOpen(true) }}
                    title="Open this flagged sentence in the document viewer"
                    className="text-xs mt-1.5 inline-flex items-center gap-1 font-medium rounded px-1.5 py-0.5 transition-colors focus:outline-none focus:ring-2 hover:bg-[var(--color-bg-secondary)]"
                    style={{ color: 'var(--color-accent)', background: 'transparent', border: 'none', cursor: 'pointer', '--tw-ring-color': 'var(--color-accent)' }}
                  >
                    View in document
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
                    </svg>
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
      </>
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

// Exported for unit tests (R29, R61). Co-located with the component per the
// project's existing pattern (see ExploreGraphView). buildAgreementRows is also
// exported above; re-listed here for discoverability.
// eslint-disable-next-line react-refresh/only-export-components
export { buildViewerSpans, serializeDetectorExport }
