import { useEffect, useMemo, useRef, useState } from 'react'
import { exportCheckFile, exportBatchFile, publishCheck } from '../../utils/api'
import ShareAnimationCanvas from './ShareAnimationCanvas'
import { useCheckStore } from '../../stores/useCheckStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useStyleStore } from '../../stores/useStyleStore'
import { buildReferenceSummary } from '../../utils/referenceStatus'
import { filterIssuesForStyle } from '../../utils/formatters'

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 4000)
}

const safeName = (t) => (t || 'refchecker-report').replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 80).replace(/^-+|-+$/g, '') || 'refchecker-report'

const FORMATS = [
  { id: 'html', label: 'HTML', ext: 'html', hint: 'Self-contained webpage' },
  { id: 'pdf', label: 'PDF', ext: 'pdf', hint: 'Print-ready document' },
  { id: 'md', label: 'Markdown', ext: 'md', hint: 'LLM-ingestible text' },
  { id: 'docx', label: 'Word', ext: 'docx', hint: 'Editable .docx' },
]

/**
 * "Share this document" — multi-format export (HTML / PDF / Markdown / DOCX)
 * with include/exclude section checkboxes and an optional "suggested
 * corrections" pass, plus opt-in publish-to-web (GitHub Gist → htmlpreview).
 * GPTZero-style: minor year warnings are downweighted server-side, errors and
 * hallucinations elevated. Every option maps to real report content.
 */
export default function ShareModal({ checkId, batchId, title, onClose }) {
  const isBatch = !!batchId
  const checkStore = useCheckStore()
  const selectedCheck = useHistoryStore((s) => s.selectedCheck)
  const [busy, setBusy] = useState(null) // 'download' | 'publish'
  const [fmt, setFmt] = useState('html')
  const [corrections, setCorrections] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)
  const [token, setToken] = useState(() => localStorage.getItem('refchecker.githubToken') || '')
  const [isPublic, setIsPublic] = useState(false)
  const [shareUrl, setShareUrl] = useState('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  // Walkthrough animation control. The canvas loops internally, but here we
  // want it to PLAY ONCE each time the share banner is opened and then settle
  // (no perpetual autoloop). `animKey` forces a fresh canvas mount so the
  // animation re-triggers from frame zero every time the modal opens; once a
  // single play-through has elapsed we unmount the live canvas (`animActive`
  // → false) so the requestAnimationFrame loop stops. One play, no loop.
  // The canvas's own DUR is 5200ms — give it that plus a small tail so the
  // final frame lands before we freeze it.
  const ANIM_PLAY_MS = 5200 + 400
  const [animKey, setAnimKey] = useState(0)
  const [animActive, setAnimActive] = useState(true)
  const animTimerRef = useRef(null)
  useEffect(() => {
    // Re-trigger on open: remount the canvas and run one pass.
    setAnimKey((k) => k + 1)
    setAnimActive(true)
    animTimerRef.current = setTimeout(() => setAnimActive(false), ANIM_PLAY_MS)
    return () => { if (animTimerRef.current) clearTimeout(animTimerRef.current) }
    // Mount-only: ShareModal is conditionally rendered by its parent, so it
    // mounts fresh on every open and this fires exactly once per open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Best-effort summary for the included-scans state + the build animation.
  // The animation's reference / warning / error counts MUST equal the numbers
  // the app's Summary bar shows, so they are derived from the very same source
  // of truth (buildReferenceSummary → getEffectiveReferenceStatus), not a
  // separate, looser recompute. `errors` groups errors + hallucinations so the
  // gauge/chips line up with the "problem" references the user sees — identical
  // to the in-app walkthrough (StatsSection).
  //
  // R48: the canonical summary is STYLE-AWARE (matching StatsSection/HealthBadge):
  // the active citation style can suppress style-conforming warnings, which moves
  // the verified/warning boundary. We replicate StatsSection's filterIssuesForStyle
  // pass so the summary passed to the export is identical to the report card the
  // user is looking at — that is what removes the export's verified/warning
  // off-by-one (30/8/82% badge vs 29/9/80% export).
  const styleFormat = useStyleStore((s) => s.format)
  const summary = useMemo(() => {
    const rawRefs = selectedCheck?.references || checkStore.references || []
    const ai = selectedCheck?.ai_detection || checkStore.aiDetection || null
    // The share dialog only opens on a finished check, so treat it as complete
    // (respect an explicit status if one is present on the selected check).
    const rawStatus = (selectedCheck?.status || '').toLowerCase()
    const isComplete = rawStatus ? !['in_progress', 'pending', 'checking', 'queued', 'processing', 'started'].includes(rawStatus) : true
    // Style-filter each ref's issues exactly as StatsSection does before counting.
    const refs = (Array.isArray(rawRefs) ? rawRefs : []).map((r) => {
      if (!r) return r
      const fe = filterIssuesForStyle(r.errors, r, styleFormat)
      const fw = filterIssuesForStyle(r.warnings, r, styleFormat)
      if (fe === r.errors && fw === r.warnings) return r
      return { ...r, errors: fe, warnings: fw }
    })
    // Pull whatever aggregate stats the surface already has so progress totals
    // are honoured; reference buckets are recomputed from the refs themselves.
    const aggregate = selectedCheck || checkStore.stats || {}
    const s = buildReferenceSummary({ stats: aggregate, references: refs, isComplete })
    const stats = {
      total: s.processedRefs || refs.length,
      verified: s.references.verified,
      warnings: s.references.warnings,
      errors: s.references.errors + s.references.hallucinated,
    }
    const aiOn = isBatch || (!!ai && ai.band !== 'unavailable' && ai.band !== 'inconclusive')
    // `canonical` is the full style-aware buildReferenceSummary result handed to
    // the export so the file shows the SAME counts + citation-health % the user
    // sees in the badge / report card.
    return { refs, ai, stats, aiOn, canonical: s }
  }, [selectedCheck, checkStore.references, checkStore.aiDetection, checkStore.stats, isBatch, styleFormat])

  // Section include/exclude checkboxes (the export "what to include" controls).
  const [sections, setSections] = useState({ summary: true, ai: true, issues: true, references: true })
  const toggleSection = (k) => setSections((s) => ({ ...s, [k]: !s[k] }))
  const includeList = Object.entries(sections).filter(([, v]) => v).map(([k]) => k)

  const SECTION_DEFS = [
    { id: 'summary', label: 'Summary & verdict', always: false },
    { id: 'ai', label: 'AI-text detection', disabled: !summary.aiOn },
    { id: 'issues', label: 'Issues to address', always: false },
    { id: 'references', label: 'Full reference list', always: false },
  ]

  const handleDownload = async () => {
    setBusy('download'); setError('')
    const minShow = new Promise((r) => setTimeout(r, 1800))
    try {
      const opts = { fmt, corrections, include: includeList.length ? includeList : undefined }
      // R48: hand the FE's canonical (style-aware) summary to the single-check
      // export so its counts + citation-health match the badge / report card.
      // Batch exports aggregate many checks server-side, so they keep the
      // server computation.
      const req = isBatch
        ? exportBatchFile(batchId, opts)
        : exportCheckFile(checkId, { ...opts, summary: summary.canonical })
      const [res] = await Promise.all([req, minShow])
      const ext = FORMATS.find((f) => f.id === fmt)?.ext || 'html'
      downloadBlob(res.data, `${safeName(title || (isBatch ? 'batch-report' : 'report'))}.${ext}`)
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Export failed')
    } finally { setBusy(null) }
  }

  const [shareNote, setShareNote] = useState('')

  const handlePublish = async () => {
    setBusy('publish'); setError(''); setShareUrl(''); setShareNote('')
    try {
      localStorage.setItem('refchecker.githubToken', token)
      const res = await publishCheck(checkId, { adapter: 'github_gist', token, public: isPublic })
      setShareUrl(res.data?.url || '')
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Publish failed')
    } finally { setBusy(null) }
  }

  // Quick link: zero-config anonymous host — no domain, no token.
  const handleQuickLink = async () => {
    setBusy('quicklink'); setError(''); setShareUrl(''); setShareNote('')
    try {
      const res = await publishCheck(checkId, { adapter: 'quick_link' })
      setShareUrl(res.data?.url || '')
      setShareNote('Anonymous PDF report link — no account or domain needed. Public to anyone with the URL and expires after a while.')
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Quick link failed')
    } finally { setBusy(null) }
  }

  const copy = () => {
    if (!shareUrl) return
    navigator.clipboard?.writeText(shareUrl)
    setCopied(true); setTimeout(() => setCopied(false), 1500)
  }

  const pill = (active) => ({
    background: active ? 'var(--color-accent)' : 'var(--color-bg-secondary)',
    color: active ? '#fff' : 'var(--color-text-primary)',
    borderColor: active ? 'var(--color-accent)' : 'var(--color-border)',
  })

  return (
    <div className="fixed inset-0 z-[1100] flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.5)' }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
        className="w-full rounded-xl overflow-hidden"
        style={{ maxWidth: 580, maxHeight: '92vh', overflowY: 'auto', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', boxShadow: '0 20px 60px rgba(0,0,0,0.4)' }}>
        {/* Header */}
        <div className="px-5 pt-5 pb-4 text-center relative" style={{ borderBottom: '1px solid var(--color-border)' }}>
          <button type="button" onClick={onClose} className="absolute top-3 right-3 p-1" style={{ color: 'var(--color-text-muted)' }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
          </button>
          <h2 className="text-lg font-bold" style={{ color: 'var(--color-text-primary)' }}>{isBatch ? 'Share this batch' : 'Share this document'}</h2>
          <p className="text-sm mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
            {isBatch
              ? 'Export one report: an overview of every paper, then each paper in detail.'
              : 'Export a self-contained report, or publish a link anyone can view.'}
          </p>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* Walkthrough video — the animated summary for THIS check, shown at
              the top (auto-generated per check, reflects its real numbers).
              No record/download button: it's a live preview. Plays ONCE each
              time this banner is opened — `animKey` remounts the canvas so the
              animation restarts from frame zero on open, and once a single
              play-through has elapsed the canvas is unmounted (`animActive`
              → false) so it doesn't autoloop or keep burning frames. */}
          {!isBatch && summary.stats.total > 0 && animActive && (
            <ShareAnimationCanvas
              key={animKey}
              title={title}
              stats={summary.stats}
              aiBand={summary.ai?.band}
              aiScore={summary.ai?.overall_score}
              height={232}
            />
          )}

          {/* Format selector */}
          <div>
            <div className="text-xs font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>Format</div>
            <div className="grid grid-cols-4 gap-2">
              {FORMATS.map((f) => (
                <button key={f.id} type="button" onClick={() => setFmt(f.id)} title={f.hint}
                  className="px-2 py-2 rounded-md text-sm font-medium border text-center transition-colors"
                  style={pill(fmt === f.id)}>
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          {/* Section include/exclude */}
          <div>
            <div className="text-xs font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>Include sections</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
              {SECTION_DEFS.map((s) => (
                <label key={s.id} className="flex items-center gap-2 text-sm"
                  style={{ color: s.disabled ? 'var(--color-text-muted)' : 'var(--color-text-primary)', opacity: s.disabled ? 0.5 : 1 }}>
                  <input type="checkbox" disabled={s.disabled}
                    checked={!s.disabled && sections[s.id]}
                    onChange={() => toggleSection(s.id)} />
                  {s.label}
                  {s.id === 'ai' && !summary.aiOn && <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>(none)</span>}
                </label>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm mt-2.5 pt-2.5" style={{ color: 'var(--color-text-primary)', borderTop: '1px solid var(--color-border)' }}>
              <input type="checkbox" checked={corrections} onChange={(e) => setCorrections(e.target.checked)} />
              Include suggested corrections
              <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>(verified-source fixes)</span>
            </label>
          </div>

          {busy === 'download' && (
            <div className="text-xs text-center" style={{ color: 'var(--color-text-muted)' }}>
              Building your {FORMATS.find((f) => f.id === fmt)?.label} report…
            </div>
          )}

          {/* Export actions */}
          <div className="flex gap-2 flex-wrap">
            <button type="button" onClick={handleDownload} disabled={busy === 'download' || includeList.length === 0}
              className="px-3 py-2 rounded-md text-sm font-medium inline-flex items-center gap-1.5"
              style={{ background: 'var(--color-accent)', color: '#fff', border: 'none', opacity: (busy === 'download' || includeList.length === 0) ? 0.6 : 1 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
              {busy === 'download' ? 'Preparing…' : `Download ${FORMATS.find((f) => f.id === fmt)?.label}`}
            </button>
            {!isBatch && (
              <button type="button" onClick={handleQuickLink} disabled={busy === 'quicklink'}
                className="px-3 py-2 rounded-md text-sm inline-flex items-center gap-1.5 border"
                style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-primary)', borderColor: 'var(--color-border)', opacity: busy === 'quicklink' ? 0.6 : 1 }}
                title="Get an instant anonymous link — no domain or token needed (ephemeral, public)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" /></svg>
                {busy === 'quicklink' ? 'Creating link…' : 'Quick link'}
              </button>
            )}
            {!isBatch && (
              <button type="button" onClick={() => setPublishOpen((v) => !v)}
                className="px-3 py-2 rounded-md text-sm inline-flex items-center gap-1.5 border"
                style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-primary)', borderColor: 'var(--color-border)' }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></svg>
                Publish to web
              </button>
            )}
          </div>

          {/* Publish panel */}
          {!isBatch && publishOpen && (
            <div className="rounded-lg p-3 space-y-2" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
              <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                Publishes the HTML to a GitHub Gist and returns a viewable link. Needs a personal access token with <code>gist</code> scope (stored locally, used only for this request).
              </div>
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="GitHub token (gist scope)"
                className="w-full px-2 py-1.5 rounded-md text-sm outline-none"
                style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}
              />
              <label className="flex items-center gap-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                <input type="checkbox" checked={isPublic} onChange={(e) => setIsPublic(e.target.checked)} />
                Public gist (anyone can find it) — otherwise unlisted
              </label>
              <button type="button" onClick={handlePublish} disabled={!token || busy === 'publish'}
                className="px-3 py-1.5 rounded-md text-sm font-medium"
                style={{ background: 'var(--color-accent)', color: '#fff', border: 'none', opacity: (!token || busy === 'publish') ? 0.6 : 1 }}>
                {busy === 'publish' ? 'Publishing…' : 'Publish & get link'}
              </button>
            </div>
          )}

          {/* Share URL */}
          {shareNote && <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{shareNote}</div>}
          {shareUrl && (
            <div className="flex items-center gap-2">
              <input readOnly value={shareUrl}
                className="flex-1 px-2 py-1.5 rounded-md text-sm outline-none"
                style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }} />
              <button type="button" onClick={copy} className="px-2 py-1.5 rounded-md text-sm border"
                style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}>
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          )}

          {error && <div className="text-sm" style={{ color: 'var(--color-error)' }}>{error}</div>}
        </div>

        <div className="px-5 py-3 flex justify-end" style={{ borderTop: '1px solid var(--color-border)' }}>
          <button type="button" onClick={onClose} className="px-4 py-1.5 rounded-md text-sm font-medium"
            style={{ background: 'var(--color-text-primary)', color: 'var(--color-bg-primary)' }}>Done</button>
        </div>
      </div>
    </div>
  )
}
