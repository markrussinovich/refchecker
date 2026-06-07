import { useMemo, useState } from 'react'
import { exportCheckHtml, publishCheck } from '../../utils/api'
import ShareAnimationCanvas from './ShareAnimationCanvas'
import { useCheckStore } from '../../stores/useCheckStore'
import { useHistoryStore } from '../../stores/useHistoryStore'

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 4000)
}

const safeName = (t) => (t || 'refchecker-report').replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 80).replace(/^-+|-+$/g, '') || 'refchecker-report'

/**
 * "Share this document" — self-contained HTML export (always), an opt-in
 * publish-to-web (GitHub Gist → htmlpreview link), and an in-app video
 * walkthrough export. Mirrors the GPTZero share dialog.
 */
export default function ShareModal({ checkId, title, onClose }) {
  const checkStore = useCheckStore()
  const selectedCheck = useHistoryStore((s) => s.selectedCheck)
  const [busy, setBusy] = useState(null) // 'html' | 'video' | 'publish'
  const [publishOpen, setPublishOpen] = useState(false)
  const [token, setToken] = useState(() => localStorage.getItem('refchecker.githubToken') || '')
  const [isPublic, setIsPublic] = useState(false)
  const [shareUrl, setShareUrl] = useState('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  // Best-effort summary for the included-scans list + the video animation.
  const summary = useMemo(() => {
    const refs = selectedCheck?.references || checkStore.references || []
    const ai = selectedCheck?.ai_detection || checkStore.aiDetection || null
    const status = (r) => (r.status || '').toLowerCase()
    const stats = {
      total: refs.length,
      verified: refs.filter((r) => status(r) === 'verified').length,
      warnings: refs.filter((r) => status(r) === 'warning').length,
      errors: refs.filter((r) => status(r) === 'error' || (r.errors?.length)).length,
    }
    return { refs, ai, stats }
  }, [selectedCheck, checkStore.references, checkStore.aiDetection])

  const scans = [
    { name: 'Reference verification', on: summary.refs.length > 0 },
    { name: 'AI-text detection', on: !!summary.ai && summary.ai.band !== 'unavailable' },
    { name: 'Citation contexts', on: summary.refs.some((r) => (r.citation_contexts?.length || 0) > 0) },
  ].filter((s) => s.on)

  const handleDownloadHtml = async () => {
    setBusy('html'); setError('')
    // Keep the build animation on screen for a beat even when the export is
    // instant, so the "generating report" moment reads intentionally.
    const minShow = new Promise((r) => setTimeout(r, 2600))
    try {
      const [res] = await Promise.all([exportCheckHtml(checkId), minShow])
      downloadBlob(res.data, `${safeName(title)}.html`)
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Export failed')
    } finally { setBusy(null) }
  }

  const handlePublish = async () => {
    setBusy('publish'); setError(''); setShareUrl('')
    try {
      localStorage.setItem('refchecker.githubToken', token)
      const res = await publishCheck(checkId, { adapter: 'github_gist', token, public: isPublic })
      setShareUrl(res.data?.url || '')
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Publish failed')
    } finally { setBusy(null) }
  }

  const copy = () => {
    if (!shareUrl) return
    navigator.clipboard?.writeText(shareUrl)
    setCopied(true); setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="fixed inset-0 z-[1100] flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.5)' }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
        className="w-full rounded-xl overflow-hidden"
        style={{ maxWidth: 560, background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', boxShadow: '0 20px 60px rgba(0,0,0,0.4)' }}>
        {/* Header */}
        <div className="px-5 pt-5 pb-4 text-center relative" style={{ borderBottom: '1px solid var(--color-border)' }}>
          <button type="button" onClick={onClose} className="absolute top-3 right-3 p-1" style={{ color: 'var(--color-text-muted)' }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
          </button>
          <h2 className="text-lg font-bold" style={{ color: 'var(--color-text-primary)' }}>Share this document</h2>
          <p className="text-sm mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
            Export a self-contained report, or publish a link anyone can view.
          </p>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* Scans included */}
          <div>
            <div className="text-sm mb-2" style={{ color: 'var(--color-text-secondary)' }}>The following scans will be included:</div>
            <ul className="space-y-1.5">
              {scans.map((s) => (
                <li key={s.name} className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-text-primary)' }}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--color-success)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
                  {s.name}
                </li>
              ))}
              {scans.length === 0 && <li className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No completed scans yet.</li>}
            </ul>
          </div>

          {/* Live results animation while the report is being generated. */}
          {busy === 'html' && (
            <div>
              <ShareAnimationCanvas
                title={title}
                stats={summary.stats}
                aiBand={summary.ai?.band}
                aiScore={summary.ai?.overall_score}
              />
              <div className="text-xs mt-1.5 text-center" style={{ color: 'var(--color-text-muted)' }}>
                Building your shareable report…
              </div>
            </div>
          )}

          {/* Export actions */}
          <div className="flex gap-2 flex-wrap">
            <button type="button" onClick={handleDownloadHtml} disabled={busy === 'html'}
              className="px-3 py-2 rounded-md text-sm font-medium inline-flex items-center gap-1.5"
              style={{ background: 'var(--color-accent)', color: '#fff', border: 'none', opacity: busy === 'html' ? 0.6 : 1 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
              {busy === 'html' ? 'Preparing…' : 'Download HTML'}
            </button>
            <button type="button" onClick={() => setPublishOpen((v) => !v)}
              className="px-3 py-2 rounded-md text-sm inline-flex items-center gap-1.5 border"
              style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-primary)', borderColor: 'var(--color-border)' }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></svg>
              Publish to web
            </button>
          </div>

          {/* Publish panel */}
          {publishOpen && (
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
