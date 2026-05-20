import { useEffect, useState } from 'react'
import { findSimilarPapers } from '../../utils/api'
import { openExternal } from '../../utils/tauriBridge'

/**
 * Post-check sibling of the References tab. On mount, asks the backend
 * which papers cite the most refs in common with the current paper
 * (recommendations + co-citation tally from Semantic Scholar). Each
 * candidate gets a one-click "Check this too" that re-uses the existing
 * /api/check pipeline. Disabled until a check has actually produced
 * references.
 */
export default function SimilarPapersPanel({ references, paperTitle, onCheckPaper }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [candidates, setCandidates] = useState([])
  const [loaded, setLoaded] = useState(false)

  const refsForRequest = (references || [])
    .filter((r) => r && (r.doi || r.arxiv_id || r.title))
    .map((r) => ({ doi: r.doi, arxiv_id: r.arxiv_id, title: r.title, authors: r.authors }))

  const load = async () => {
    setLoading(true); setError(null)
    try {
      const res = await findSimilarPapers({
        references: refsForRequest,
        paper_title: paperTitle,
        limit: 5,
      })
      setCandidates(res.data?.candidates || [])
      setLoaded(true)
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Lookup failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setLoaded(false); setCandidates([])
  }, [paperTitle])

  if (!refsForRequest.length) {
    return (
      <div
        className="rounded-lg border p-4 text-center text-sm"
        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
      >
        Run a check first — Similar Papers needs at least one verified reference.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div
        className="rounded-lg border p-3 flex items-center justify-between flex-wrap gap-2"
        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
      >
        <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          Find up to 5 papers from Semantic Scholar that share the most references with this paper.
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="px-3 py-1 rounded text-xs font-medium"
          style={{ backgroundColor: 'var(--color-accent, #3b82f6)', color: 'white', opacity: loading ? 0.5 : 1 }}
          type="button"
        >
          {loading ? 'Searching…' : (loaded ? 'Refresh' : 'Find similar papers')}
        </button>
      </div>

      {error && (
        <div className="text-xs p-2 rounded" style={{ backgroundColor: 'rgba(239,68,68,0.08)', color: 'var(--color-error, #ef4444)' }}>
          {error}
        </div>
      )}

      {loaded && candidates.length === 0 && !loading && (
        <div className="text-xs p-3 rounded border text-center"
          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}>
          Nothing surfaced — try again after a Semantic Scholar API key is configured (Settings → API Keys).
        </div>
      )}

      <div className="space-y-2">
        {candidates.map((c) => {
          const url = c.semantic_scholar_url
          const arxivUrl = c.arxiv_id ? `https://arxiv.org/abs/${c.arxiv_id}` : null
          const doiUrl = c.doi ? `https://doi.org/${c.doi}` : null
          return (
            <div key={c.paperId} className="rounded-lg border p-3"
              style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}>
              <div className="flex items-start justify-between gap-2 flex-wrap">
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
                    {c.title || '(no title)'}
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
                    {(c.authors || []).slice(0, 3).join(', ')}
                    {(c.authors || []).length > 3 ? ', et al.' : ''}
                    {c.year ? ` · ${c.year}` : ''}
                    {c.via === 'recommendations' ? ' · recommended' : c.shared_with_source ? ` · shares ${c.shared_with_source} ref${c.shared_with_source === 1 ? '' : 's'}` : ''}
                  </div>
                </div>
                <div className="flex gap-1 flex-shrink-0">
                  {(doiUrl || arxivUrl || url) && (
                    <button
                      onClick={() => {
                        const target = doiUrl || arxivUrl || url
                        if (typeof window !== 'undefined' && window.__TAURI_INTERNALS__) {
                          openExternal(target)
                        } else {
                          window.open(target, '_blank', 'noopener,noreferrer')
                        }
                      }}
                      className="text-xs px-2 py-0.5 rounded border"
                      style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-accent, #3b82f6)' }}
                      type="button"
                    >Open</button>
                  )}
                  {onCheckPaper && (c.arxiv_id || c.doi) && (
                    <button
                      onClick={() => onCheckPaper(c.arxiv_id ? c.arxiv_id : `https://doi.org/${c.doi}`)}
                      className="text-xs px-2 py-0.5 rounded"
                      style={{ backgroundColor: 'var(--color-accent, #3b82f6)', color: 'white' }}
                      type="button"
                    >Check this too</button>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
