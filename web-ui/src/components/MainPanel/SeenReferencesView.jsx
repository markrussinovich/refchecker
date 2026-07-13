import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { listSeenReferences, clearSeenReferences, backfillSeenReferences } from '../../utils/api'
import { openExternal } from '../../utils/tauriBridge'
import { useHistoryStore } from '../../stores/useHistoryStore'

const GraphLibraryView = lazy(() => import('./GraphLibraryView'))

/**
 * "Seen References" — a single global view of every reference RefChecker
 * has ever verified, deduped by DOI / arXiv ID / normalized title. Each
 * row carries a times_seen counter so the user can spot frequently-cited
 * sources at a glance and act as a personal "is this paper real?" cache.
 *
 * Backed by GET /api/references/seen. Search box hits the server-side
 * substring filter so the local memory stays bounded on large libraries.
 */
export default function SeenReferencesView() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [dbPath, setDbPath] = useState('')
  // v0.7.69: growth chip — surfaces NEW rows added in the last 24h/7d so
  // a flat total (the "120 plateau" bug) is distinguishable from an old
  // snapshot. Sourced from /api/references/seen response.
  const [recentGrowth, setRecentGrowth] = useState({ last_24_hours: 0, last_7_days: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  // v0.7.70: manual backfill status — workaround/diagnostic for the
  // "120 plateau" bug. While running, the button shows a busy state;
  // when done, we surface walked/inserted/updated/skipped counts so the
  // user can see whether their historic checks legitimately produce new
  // identity keys.
  const [backfillBusy, setBackfillBusy] = useState(false)
  const [backfillStatus, setBackfillStatus] = useState(null)
  const [showGraph, setShowGraph] = useState(false)
  const PAGE = 100
  const debounceRef = useRef(null)

  const load = useCallback(async (override = {}) => {
    setLoading(true); setError(null)
    try {
      const res = await listSeenReferences(PAGE, override.offset ?? offset, override.q ?? q)
      setItems(res.data.items || [])
      setTotal(res.data.total || 0)
      setDbPath(res.data.db_path || '')
      setRecentGrowth(res.data.recent_growth || { last_24_hours: 0, last_7_days: 0 })
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Load failed')
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [offset, q])

  useEffect(() => { load() }, [load])

  // Refresh the library after any check finishes so newly-verified refs
  // surface here without a manual reload.
  useEffect(() => {
    const onCheckDone = () => { load({ offset: 0 }); setOffset(0) }
    window.addEventListener('refchecker:check-completed', onCheckDone)
    return () => window.removeEventListener('refchecker:check-completed', onCheckDone)
  }, [load])

  const handleClearCache = async () => {
    if (!window.confirm('Clear the entire Seen References cache? This cannot be undone.')) return
    try {
      await clearSeenReferences()
      await load({ offset: 0 })
      setOffset(0)
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Clear failed')
    }
  }

  // v0.7.70: manual backfill — re-walks every completed check_history
  // row and upserts each ref. Safe (idempotent: duplicates merge). The
  // diagnostic counters are the real value here: if walked_refs is high
  // but inserted is 0, the upsert path is hitting ON CONFLICT every
  // time → the identity-key cascade is collapsing too aggressively.
  const handleBackfill = async () => {
    if (!window.confirm(
      'Re-scan all completed checks and add their references to the Seen library? '
      + 'This is safe — duplicates are merged.'
    )) return
    setBackfillBusy(true)
    setBackfillStatus('Backfilling…')
    try {
      const res = await backfillSeenReferences()
      const d = res?.data || {}
      setBackfillStatus(
        `Backfill complete: walked ${d.walked_checks ?? 0} checks `
        + `(${d.walked_refs ?? 0} refs) → +${d.inserted ?? 0} new, `
        + `${d.updated ?? 0} already known, ${d.skipped_no_identity ?? 0} skipped (no identity)`
        + (d.duration_seconds != null ? ` · ${d.duration_seconds}s` : '')
      )
      await load({ offset: 0 })
      setOffset(0)
    } catch (e) {
      setBackfillStatus(
        'Backfill failed: ' + (e?.response?.data?.detail || e?.message || 'unknown error')
      )
    } finally {
      setBackfillBusy(false)
    }
  }

  useEffect(() => {
    // Debounce the search input so we don't hit the server on every keystroke.
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => { setOffset(0); load({ offset: 0, q }) }, 250)
    return () => debounceRef.current && clearTimeout(debounceRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  const verifiedCount = useMemo(() => items.filter(i => i.status === 'verified').length, [items])

  const parseAuthors = (raw) => {
    if (!raw) return ''
    if (typeof raw !== 'string') return String(raw)
    if (raw.startsWith('[')) {
      try {
        const arr = JSON.parse(raw)
        return Array.isArray(arr) ? arr.slice(0, 3).join(', ') + (arr.length > 3 ? ', et al.' : '') : raw
      } catch { /* fallthrough */ }
    }
    return raw
  }

  // Resolve an outbound URL for every row. Priority:
  //   DOI → arXiv → verified_url → S2 search by title (always-on
  //   fallback so every row has an Open button, even refs that landed
  //   in the library via the hash-only identity key).
  const renderUrl = (item) => {
    if (item.doi) return `https://doi.org/${item.doi.replace(/^https?:\/\/(dx\.)?doi\.org\//i, '')}`
    if (item.arxiv_id) return `https://arxiv.org/abs/${item.arxiv_id}`
    if (item.verified_url) return item.verified_url
    if (item.title) return `https://www.semanticscholar.org/search?q=${encodeURIComponent(item.title)}`
    return null
  }

  // Jump the user to the originating check in the History sidebar.
  // Falls back to opening the check via selectCheck when we have an id;
  // if the row has no last_seen_check_id (older rows or pre-v0.7.27
  // upserts) the chip is hidden.
  const selectCheck = useHistoryStore(s => s.selectCheck)
  const openSourceCheck = (checkId) => {
    if (!checkId) return
    try { selectCheck?.(checkId, { force: true }) } catch { /* */ }
    // Bounce the user out of Seen Refs back to Current check view.
    window.dispatchEvent(new CustomEvent('refchecker:switch-to-current'))
  }

  return (
    <div className="space-y-3">
      <div
        className="p-3 rounded-lg border flex items-center justify-between gap-2 flex-wrap"
        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
      >
        <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          <strong style={{ color: 'var(--color-text-primary)' }}>{total}</strong> unique references seen
          {q ? ` (filtered: ${items.length} shown)` : items.length < total ? ` (showing ${items.length})` : ''}
          {' · '}<span style={{ color: 'var(--color-success, #22c55e)' }}>{verifiedCount} verified on this page</span>
          {/* v0.7.69: growth chip — answers "is this counter actually
              moving?" without digging through backend logs. If a user
              just ran a 100-paper batch and last_24h is 0, the upstream
              identity-key collision bug is back. */}
          {(recentGrowth.last_24_hours > 0 || recentGrowth.last_7_days > 0) && (
            <>
              {' · '}
              <span
                title={`${recentGrowth.last_24_hours} new in last 24h, ${recentGrowth.last_7_days} new in last 7 days`}
                style={{ color: 'var(--color-accent, #3b82f6)' }}
              >
                +{recentGrowth.last_24_hours} in 24h · +{recentGrowth.last_7_days} in 7d
              </span>
            </>
          )}
          {dbPath && (
            <div style={{ color: 'var(--color-text-muted)', marginTop: 4 }}>
              <span title={dbPath}>Cache file: <code>{dbPath.split('/').slice(-2).join('/')}</code></span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="text"
            placeholder="Search by title, author, or DOI…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="px-3 py-1.5 rounded border text-xs"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
              minWidth: '260px',
            }}
          />
          <button
            onClick={() => load({ offset: 0 })}
            className="px-2 py-1 rounded text-xs"
            style={{
              border: '1px solid var(--color-border)',
              background: 'var(--color-bg-tertiary)',
              color: 'var(--color-text-secondary)',
            }}
            title="Refresh from server"
          >
            ↻
          </button>
          <button
            onClick={() => setShowGraph(true)}
            disabled={total === 0}
            className="px-2 py-1 rounded text-xs inline-flex items-center gap-1"
            style={{
              border: '1px solid var(--color-border)',
              background: 'transparent',
              color: 'var(--color-text-secondary)',
              opacity: total === 0 ? 0.5 : 1,
              cursor: total === 0 ? 'not-allowed' : 'pointer',
            }}
            title="Explore the whole library as a 3D graph (nodes sized by times seen, edges = shared authors/venue)"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="5" cy="6" r="2" /><circle cx="19" cy="7" r="2" /><circle cx="12" cy="18" r="2" />
              <line x1="6.7" y1="7" x2="10.5" y2="16.5" /><line x1="17.5" y1="8.5" x2="13.3" y2="16.7" /><line x1="7" y1="6.3" x2="17" y2="6.8" />
            </svg>
            3D graph
          </button>
          <button
            onClick={handleBackfill}
            disabled={backfillBusy}
            className="px-2 py-1 rounded text-xs"
            style={{
              border: '1px solid var(--color-border)',
              background: 'transparent',
              color: 'var(--color-text-secondary)',
              opacity: backfillBusy ? 0.5 : 1,
              cursor: backfillBusy ? 'wait' : 'pointer',
            }}
            title="Re-walk every completed check and re-upsert its refs (idempotent — safe to repeat)"
          >
            {backfillBusy ? 'Backfilling…' : 'Backfill from history'}
          </button>
          <button
            onClick={handleClearCache}
            className="px-2 py-1 rounded text-xs"
            style={{
              border: '1px solid var(--color-border)',
              background: 'transparent',
              color: 'var(--color-error, #ef4444)',
            }}
            title="Delete every cached entry"
          >
            Clear cache
          </button>
        </div>
      </div>

      {backfillStatus && (
        <div
          className="text-xs px-2 py-1 rounded"
          style={{
            backgroundColor: 'var(--color-bg-secondary)',
            color: 'var(--color-text-secondary)',
            border: '1px solid var(--color-border)',
          }}
        >
          {backfillStatus}
        </div>
      )}

      {error && (
        <div className="text-xs p-2 rounded" style={{ backgroundColor: 'rgba(239,68,68,0.08)', color: 'var(--color-error, #ef4444)' }}>
          {error}
        </div>
      )}

      {loading && items.length === 0 ? (
        <div className="rounded-lg border p-6 text-center text-sm" style={{
          borderColor: 'var(--color-border)',
          backgroundColor: 'var(--color-bg-secondary)',
          color: 'var(--color-text-secondary)',
        }}>Loading…</div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border p-6 text-center text-sm" style={{
          borderColor: 'var(--color-border)',
          backgroundColor: 'var(--color-bg-secondary)',
          color: 'var(--color-text-secondary)',
        }}>
          {q
            ? 'No verified references match this search.'
            : 'No references seen yet — run a check and the verified ones will collect here.'}
        </div>
      ) : (
        <div className="space-y-1">
          {items.map((it) => {
            const url = renderUrl(it)
            return (
              <div
                key={it.identity_key}
                className="rounded border p-2 flex items-center gap-3 text-sm"
                style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
              >
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0"
                  style={{
                    backgroundColor: it.status === 'verified' ? 'var(--color-success, #22c55e)' : 'var(--color-text-muted, #94a3b8)',
                    color: 'white',
                  }}
                >
                  {it.status || 'unknown'}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
                    {it.title || '(no title)'}
                  </div>
                  <div className="text-xs truncate" style={{ color: 'var(--color-text-secondary)' }}>
                    {parseAuthors(it.authors)}
                    {it.year ? ` · ${it.year}` : ''}
                    {it.venue ? ` · ${it.venue}` : ''}
                    {it.matched_db ? ` · ${it.matched_db}` : ''}
                  </div>
                </div>
                <div className="text-[11px] flex-shrink-0 text-right" style={{ color: 'var(--color-text-muted)' }}>
                  seen <strong style={{ color: 'var(--color-text-primary)' }}>{it.times_seen}×</strong>
                  {it.last_seen_check_id && (
                    <div className="mt-0.5">
                      <button
                        type="button"
                        onClick={() => openSourceCheck(it.last_seen_check_id)}
                        title={it.last_seen_paper_title
                          ? `Open the check this ref was last seen in: "${it.last_seen_paper_title}"`
                          : 'Open the check this ref was last seen in'}
                        className="underline hover:no-underline"
                        style={{ color: 'var(--color-accent, #3b82f6)' }}
                      >
                        in: {it.last_seen_paper_title
                          ? (it.last_seen_paper_title.length > 28 ? it.last_seen_paper_title.slice(0, 28) + '…' : it.last_seen_paper_title)
                          : `check #${it.last_seen_check_id}`}
                      </button>
                    </div>
                  )}
                </div>
                <a
                  href={url || '#'}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => {
                    if (!url) { e.preventDefault(); return }
                    if (typeof window !== 'undefined' && window.__TAURI_INTERNALS__) {
                      e.preventDefault()
                      openExternal(url)
                    }
                  }}
                  className="text-xs px-2 py-0.5 rounded border flex-shrink-0"
                  style={{
                    backgroundColor: 'var(--color-bg-primary)',
                    borderColor: 'var(--color-border)',
                    color: url ? 'var(--color-accent, #3b82f6)' : 'var(--color-text-muted)',
                    cursor: url ? 'pointer' : 'not-allowed',
                    opacity: url ? 1 : 0.5,
                  }}
                  title={url ? 'Open external link' : 'No outbound URL — ref has no DOI / arXiv ID and no title to search by'}
                >Open</a>
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {total > PAGE && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            disabled={offset === 0}
            onClick={() => { const o = Math.max(0, offset - PAGE); setOffset(o); load({ offset: o }) }}
            className="px-3 py-1 rounded border text-xs"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
              opacity: offset === 0 ? 0.5 : 1,
            }}
            type="button"
          >Prev</button>
          <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {offset + 1}–{Math.min(offset + items.length, total)} of {total}
          </div>
          <button
            disabled={offset + items.length >= total}
            onClick={() => { const o = offset + PAGE; setOffset(o); load({ offset: o }) }}
            className="px-3 py-1 rounded border text-xs"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
              opacity: offset + items.length >= total ? 0.5 : 1,
            }}
            type="button"
          >Next</button>
        </div>
      )}
      {showGraph && (
        <Suspense fallback={null}>
          <GraphLibraryView onClose={() => setShowGraph(false)} />
        </Suspense>
      )}
    </div>
  )
}
