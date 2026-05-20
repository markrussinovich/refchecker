import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { listSeenReferences } from '../../utils/api'
import { openExternal } from '../../utils/tauriBridge'

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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const PAGE = 100
  const debounceRef = useRef(null)

  const load = useCallback(async (override = {}) => {
    setLoading(true); setError(null)
    try {
      const res = await listSeenReferences(PAGE, override.offset ?? offset, override.q ?? q)
      setItems(res.data.items || [])
      setTotal(res.data.total || 0)
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Load failed')
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [offset, q])

  useEffect(() => { load() }, [load])

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

  const renderUrl = (item) => {
    if (item.doi) return `https://doi.org/${item.doi.replace(/^https?:\/\/(dx\.)?doi\.org\//i, '')}`
    if (item.arxiv_id) return `https://arxiv.org/abs/${item.arxiv_id}`
    return item.verified_url || null
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
        </div>
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
      </div>

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
                </div>
                {url && (
                  <a
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => {
                      if (typeof window !== 'undefined' && window.__TAURI_INTERNALS__) {
                        e.preventDefault()
                        openExternal(url)
                      }
                    }}
                    className="text-xs px-2 py-0.5 rounded border flex-shrink-0"
                    style={{
                      backgroundColor: 'var(--color-bg-primary)',
                      borderColor: 'var(--color-border)',
                      color: 'var(--color-accent, #3b82f6)',
                    }}
                  >Open</a>
                )}
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
    </div>
  )
}
