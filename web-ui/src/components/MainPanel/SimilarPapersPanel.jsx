import { useEffect, useState } from 'react'
import { findSimilarPapers } from '../../utils/api'
import { openExternal } from '../../utils/tauriBridge'

/**
 * Module-level cache keyed by paperTitle. Survives tab unmount/remount
 * so switching from "Similar Papers" to another tab and back doesn't
 * blow away results the user already fetched.
 *
 * SIMILAR_CACHE holds completed responses; SIMILAR_INFLIGHT holds the
 * in-flight Promise + started timestamp so a tab swap mid-search
 * shows the same loading state when the user comes back instead of
 * letting the search appear cancelled.
 */
const SIMILAR_CACHE = new Map()
const SIMILAR_INFLIGHT = new Map()

/**
 * Post-check sibling of the References tab. On mount, asks the backend
 * which papers cite the most refs in common with the current paper
 * (recommendations + co-citation tally from Semantic Scholar). Each
 * candidate gets a one-click "Check this too" that re-uses the existing
 * /api/check pipeline. Disabled until a check has actually produced
 * references.
 */
// Discovery modes (#63). 'similar' is the existing co-citation/overlap
// pipeline; 'cites_refs' shows the source paper's real OpenAlex
// references + citations.
const MODES = [
  { id: 'similar', label: 'Similar' },
  { id: 'cites_refs', label: 'Cites & Refs' },
]

// Extract a DOI or arXiv id from the source string (a URL or raw id) so
// 'cites_refs' mode can resolve the SOURCE paper on OpenAlex. Returns ''
// when nothing recognisable is present (then title-only resolution runs).
function deriveSourceId(paperSource) {
  const s = String(paperSource || '').trim()
  if (!s) return ''
  const doi = s.match(/10\.\d{4,9}\/[^\s"<>]+/i)
  if (doi) return doi[0]
  const arxivAbs = s.match(/arxiv\.org\/abs\/([^\s?#]+)/i)
  if (arxivAbs) return arxivAbs[1]
  const arxivRaw = s.match(/^arxiv:\s*(.+)$/i)
  if (arxivRaw) return arxivRaw[1].trim()
  if (/^\d{4}\.\d{4,5}(v\d+)?$/.test(s)) return s
  return ''
}

export default function SimilarPapersPanel({ references, paperTitle, paperSource, onCheckPaper }) {
  const paperId = deriveSourceId(paperSource)
  const [mode, setMode] = useState('similar')
  // Cache key is mode-aware so switching Similar <-> Cites & Refs keeps
  // each mode's results independently and never cross-contaminates.
  const cacheKey = `${mode}::${paperTitle || ''}`
  const cached = SIMILAR_CACHE.get(cacheKey)
  const inflight = SIMILAR_INFLIGHT.get(cacheKey)
  const [loading, setLoading] = useState(Boolean(inflight))
  const [searchStartedAt, setSearchStartedAt] = useState(inflight?.startedAt || null)
  const [error, setError] = useState(null)
  const [candidates, setCandidates] = useState(cached?.candidates || [])
  const [sourceCounts, setSourceCounts] = useState(cached?.sourceCounts || {})
  const [loaded, setLoaded] = useState(Boolean(cached))
  const [expandedShared, setExpandedShared] = useState(null) // paperId of expanded

  const refsForRequest = (references || [])
    .filter((r) => r && (r.doi || r.arxiv_id || r.title))
    .map((r) => ({ doi: r.doi, arxiv_id: r.arxiv_id, title: r.title, authors: r.authors }))

  const load = async () => {
    // Reuse an in-flight search for the same paperTitle so two tab
    // mounts don't fire duplicate backend calls. Also makes the
    // "search continues across tab change" behaviour automatic — when
    // the user comes back, they're attaching to the same Promise.
    const existing = SIMILAR_INFLIGHT.get(cacheKey)
    if (existing) {
      setLoading(true)
      setSearchStartedAt(existing.startedAt)
      try {
        const { cands, counts } = await existing.promise
        setCandidates(cands); setSourceCounts(counts); setLoaded(true); setError(null)
      } catch (e) {
        setError(e?.response?.data?.detail || e?.message || 'Lookup failed')
      } finally {
        setLoading(false); setSearchStartedAt(null)
      }
      return
    }

    setLoading(true); setError(null)
    const startedAt = Date.now()
    setSearchStartedAt(startedAt)
    const promise = findSimilarPapers({
      references: refsForRequest,
      paper_title: paperTitle,
      paper_id: paperId || undefined,
      limit: 5,
      mode,
    }).then(res => {
      const cands = res.data?.candidates || []
      const counts = res.data?.source_counts || {}
      SIMILAR_CACHE.set(cacheKey, { candidates: cands, sourceCounts: counts })
      return { cands, counts }
    }).finally(() => {
      SIMILAR_INFLIGHT.delete(cacheKey)
    })
    SIMILAR_INFLIGHT.set(cacheKey, { promise, startedAt })
    try {
      const { cands, counts } = await promise
      setCandidates(cands); setSourceCounts(counts); setLoaded(true)
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Lookup failed')
    } finally {
      setLoading(false); setSearchStartedAt(null)
    }
  }

  useEffect(() => {
    // Reset / restore state on paperTitle OR mode change. Priority:
    //   1. completed cache → show those candidates
    //   2. in-flight search → attach to its promise and show loading
    //   3. neither → empty + Find papers button
    // Cache key is mode-aware (`${mode}::${title}`) so each mode keeps
    // its own results and a mode flip re-runs against the right path.
    setError(null)
    const c = SIMILAR_CACHE.get(cacheKey)
    const inFly = SIMILAR_INFLIGHT.get(cacheKey)
    if (c) {
      setCandidates(c.candidates)
      setSourceCounts(c.sourceCounts)
      setLoaded(true); setLoading(false); setSearchStartedAt(null)
    } else if (inFly) {
      // Re-attach to the in-flight promise so the loading spinner
      // continues correctly and results land here when done.
      setLoading(true); setLoaded(false)
      setSearchStartedAt(inFly.startedAt)
      inFly.promise
        .then(({ cands, counts }) => {
          setCandidates(cands); setSourceCounts(counts); setLoaded(true)
        })
        .catch(e => setError(e?.message || 'Lookup failed'))
        .finally(() => { setLoading(false); setSearchStartedAt(null) })
    } else {
      setLoaded(false); setCandidates([]); setLoading(false); setSearchStartedAt(null)
    }
  }, [paperTitle, mode, cacheKey])

  // Tick a re-render every second while a search is in flight so the
  // elapsed-time progress label updates instead of freezing.
  useEffect(() => {
    if (!loading || !searchStartedAt) return undefined
    const t = setInterval(() => setSearchStartedAt(s => s), 1000)
    return () => clearInterval(t)
  }, [loading, searchStartedAt])
  const elapsedSec = searchStartedAt ? Math.floor((Date.now() - searchStartedAt) / 1000) : 0

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
      {/* Segmented mode toggle (#63): Similar = co-citation/overlap path;
          Cites & Refs = the source paper's real OpenAlex references +
          citations. Switching modes re-runs against the matching path. */}
      <div className="flex" role="tablist" aria-label="Discovery mode"
        style={{
          border: '1px solid var(--color-border)',
          borderRadius: 8,
          overflow: 'hidden',
          width: 'fit-content',
          background: 'var(--color-bg-secondary)',
        }}>
        {MODES.map((m) => {
          const active = mode === m.id
          return (
            <button
              key={m.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => { if (m.id !== mode) { setMode(m.id); setExpandedShared(null) } }}
              className="px-3 py-1 text-xs font-medium"
              style={{
                background: active ? 'var(--color-accent, #3b82f6)' : 'transparent',
                color: active ? 'white' : 'var(--color-text-secondary)',
                border: 'none',
                cursor: 'pointer',
              }}
            >
              {m.label}
            </button>
          )
        })}
      </div>
      <div
        className="rounded-lg border p-3 flex items-center justify-between flex-wrap gap-2"
        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
      >
        <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          {mode === 'cites_refs'
            ? "This paper's real citation neighbourhood from OpenAlex — the works it cites and the works that cite it."
            : 'Find up to 5 papers from Semantic Scholar that share the most references with this paper.'}
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="px-3 py-1 rounded text-xs font-medium"
          style={{ backgroundColor: 'var(--color-accent, #3b82f6)', color: 'white', opacity: loading ? 0.5 : 1 }}
          type="button"
        >
          {loading
            ? `Searching… ${elapsedSec}s`
            : (loaded ? 'Refresh' : (mode === 'cites_refs' ? 'Find cites & refs' : 'Find similar papers'))}
        </button>
      </div>

      {/* In-flight progress bar — runs across tab changes because the
          inflight Promise lives at module scope. Stages roughly match
          the backend pipeline: S2 recs → OpenAlex co-cite → LLM →
          per-candidate reference-overlap rescore. The bar is an
          estimate, not a real percentage. */}
      {loading && (
        <div className="rounded border p-2"
          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}>
          <div className="text-xs mb-1.5 flex items-center justify-between"
            style={{ color: 'var(--color-text-secondary)' }}>
            <span>
              {elapsedSec < 5 ? 'Querying Semantic Scholar…'
                : elapsedSec < 12 ? 'Cross-checking OpenAlex co-citations…'
                : elapsedSec < 22 ? 'Asking LLM for missed candidates…'
                : 'Scoring reference overlap per candidate…'}
            </span>
            <span style={{ color: 'var(--color-text-muted)' }}>continues across tab changes</span>
          </div>
          <div className="h-1 rounded overflow-hidden" style={{ background: 'var(--color-bg-tertiary)' }}>
            <div
              className="h-full transition-all"
              style={{
                width: `${Math.min(95, (elapsedSec / 30) * 100)}%`,
                background: 'var(--color-accent, #3b82f6)',
              }}
            />
          </div>
        </div>
      )}

      {error && (
        <div className="text-xs p-2 rounded" style={{ backgroundColor: 'rgba(239,68,68,0.08)', color: 'var(--color-error, #ef4444)' }}>
          {error}
        </div>
      )}

      {loaded && candidates.length === 0 && !loading && (
        <div className="text-xs p-3 rounded border"
          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}>
          <div className="mb-1">Nothing surfaced from any source.</div>
          {Object.keys(sourceCounts).length === 0 ? (
            <div style={{ color: 'var(--color-text-muted)' }}>
              All four sources returned empty. Common causes:
              <ul className="list-disc pl-5 mt-1 space-y-0.5">
                <li>Semantic Scholar / OpenAlex rate-limited — set <code>SEMANTIC_SCHOLAR_API_KEY</code> in Settings → API Keys for faster, ungated calls</li>
                <li>Your references don't carry DOIs / arXiv IDs that S2 or OpenAlex can resolve</li>
                <li>The configured LLM provider doesn't have web-search enabled (Anthropic / OpenAI / Gemini only)</li>
              </ul>
            </div>
          ) : (
            <div style={{ color: 'var(--color-text-muted)' }}>
              Sources tried:{' '}
              {Object.entries(sourceCounts).map(([s, n]) => (
                <span key={s} className="mr-2">
                  {s === 'semantic_scholar' ? 'S2' : s === 'openalex' ? 'OpenAlex' : s === 'web' ? 'Web' : s === 'llm' ? 'LLM' : s}: {n}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      {loaded && candidates.length > 0 && Object.keys(sourceCounts).length > 0 && (
        <div className="text-xs px-1" style={{ color: 'var(--color-text-muted)' }}>
          Pulled from:{' '}
          {Object.entries(sourceCounts).map(([s, n], i) => (
            <span key={s}>
              {i > 0 ? ' · ' : ''}{s === 'semantic_scholar' ? 'S2' : s === 'openalex' ? 'OpenAlex' : s === 'web' ? 'Web' : s === 'llm' ? 'LLM' : s} ({n})
            </span>
          ))}
        </div>
      )}

      <div className="space-y-2">
        {candidates.map((c, idx) => {
          const url = c.semantic_scholar_url
          const arxivUrl = c.arxiv_id ? `https://arxiv.org/abs/${c.arxiv_id}` : null
          const doiUrl = c.doi ? `https://doi.org/${c.doi}` : null
          // Cites/refs rows have no S2 paperId, so fall back to a stable
          // composite key (openalex id / doi / index) to avoid React key
          // collisions on the null paperId. (The shared-refs expand toggle
          // only renders for similar-mode rows, which always carry a
          // paperId, so its state key stays c.paperId below.)
          const rowKey = c.paperId || c.openalex_id || c.doi || `row-${idx}`
          return (
            <div key={rowKey} className="rounded-lg border p-3"
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
                    {c.shared_with_source ? ` · shares ${c.shared_with_source} ref${c.shared_with_source === 1 ? '' : 's'}` : ''}
                  </div>
                  <div className="text-xs mt-0.5 flex flex-wrap gap-1">
                    {(c.sources || []).map((s) => (
                      <span
                        key={s}
                        className="px-1.5 py-0.5 rounded"
                        style={{
                          background: 'var(--color-bg-tertiary)',
                          color: 'var(--color-text-secondary)',
                          fontSize: '0.7rem',
                          border: '1px solid var(--color-border)',
                        }}
                      >
                        {s === 'semantic_scholar' ? 'S2' : s === 'openalex' ? 'OpenAlex' : s === 'web' ? 'Web' : s === 'llm' ? 'LLM' : s}
                      </span>
                    ))}
                    {/* Relation chip (#63): in cites_refs / both mode each
                        candidate is tagged as a work the source paper
                        cites (Reference) or one that cites it (Citation). */}
                    {(c.relation === 'reference' || c.relation === 'citation') && (
                      <span
                        className="px-1.5 py-0.5 rounded"
                        style={{
                          background: c.relation === 'reference'
                            ? 'rgba(139,92,246,0.12)' : 'rgba(234,179,8,0.14)',
                          color: c.relation === 'reference'
                            ? 'var(--color-accent, #8b5cf6)' : '#a16207',
                          fontSize: '0.7rem',
                          border: c.relation === 'reference'
                            ? '1px solid rgba(139,92,246,0.35)' : '1px solid rgba(234,179,8,0.4)',
                        }}
                        title={c.relation === 'reference'
                          ? 'This paper is cited BY the source paper (a reference).'
                          : 'This paper CITES the source paper (a citation).'}
                      >
                        {c.relation === 'reference' ? 'Reference' : 'Citation'}
                      </span>
                    )}
                    {/* Reference-overlap chip — the user's primary signal.
                        Shows "85% shared refs (17/20)" when the candidate
                        cites 17 of the input's 20 references. */}
                    {/* Always show the shared-refs chip so the user
                        knows the overlap pass ran for every candidate.
                        Three visible states:
                          - count > 0: clickable "% shared refs (N)" — expands list
                          - count = 0 but candidate_ref_count > 0: "no shared refs"
                          - candidate_ref_count = 0: "shared refs N/A" (couldn't fetch)
                       */}
                    {(() => {
                      // Cites/refs candidates aren't scored for reference
                      // overlap (that signal belongs to the Similar path),
                      // so don't render the "shared refs N/A" noise for them.
                      if (c.relation === 'reference' || c.relation === 'citation') return null
                      const sharedN = c.shared_refs_count || 0
                      const candRefs = c.candidate_ref_count || 0
                      if (sharedN > 0) {
                        return (
                          <button
                            onClick={() => setExpandedShared(expandedShared === c.paperId ? null : c.paperId)}
                            className="px-1.5 py-0.5 rounded"
                            style={{
                              background: 'rgba(59,130,246,0.12)',
                              color: 'var(--color-accent, #3b82f6)',
                              fontSize: '0.7rem',
                              border: '1px solid rgba(59,130,246,0.35)',
                              cursor: 'pointer',
                            }}
                            title={`Click to see which references are shared. Cites ${sharedN} of the input paper's references` +
                              (candRefs ? ` (out of ${candRefs} total in this paper)` : '')}
                            type="button"
                          >
                            {Math.round((c.shared_refs_pct || 0) * 100)}% shared refs ({sharedN})
                            {' '}
                            <span aria-hidden="true">{expandedShared === c.paperId ? '▾' : '▸'}</span>
                          </button>
                        )
                      }
                      if (candRefs > 0) {
                        return (
                          <span
                            className="px-1.5 py-0.5 rounded"
                            style={{
                              background: 'var(--color-bg-tertiary)',
                              color: 'var(--color-text-muted)',
                              fontSize: '0.7rem',
                              border: '1px solid var(--color-border)',
                            }}
                            title={`Overlap computed: 0 of the input paper's references appear in this candidate's ${candRefs} references.`}
                          >
                            no shared refs · 0 / {candRefs}
                          </span>
                        )
                      }
                      return (
                        <span
                          className="px-1.5 py-0.5 rounded"
                          style={{
                            background: 'var(--color-bg-tertiary)',
                            color: 'var(--color-text-muted)',
                            fontSize: '0.7rem',
                            border: '1px solid var(--color-border)',
                            fontStyle: 'italic',
                          }}
                          title="Couldn't fetch this candidate's reference list — overlap not computed."
                        >
                          shared refs N/A
                        </span>
                      )
                    })()}
                    {c.was_verified ? (
                      <span
                        className="px-1.5 py-0.5 rounded"
                        style={{
                          background: 'rgba(34,197,94,0.12)',
                          color: 'var(--color-success, #16a34a)',
                          fontSize: '0.7rem',
                          border: '1px solid rgba(34,197,94,0.35)',
                        }}
                      >
                        {c.pre_verified ? '✓ in cache' : '✓ just verified'}
                        {c.times_seen > 1 ? ` ×${c.times_seen}` : ''}
                      </span>
                    ) : c.verified_status === 'unverified' ? (
                      <span
                        className="px-1.5 py-0.5 rounded"
                        style={{
                          background: 'rgba(239,68,68,0.1)',
                          color: 'var(--color-error, #ef4444)',
                          fontSize: '0.7rem',
                          border: '1px solid rgba(239,68,68,0.35)',
                        }}
                        title="Couldn't confirm this paper against any database"
                      >
                        ? unconfirmed
                      </span>
                    ) : null}
                  </div>
                  {c.reason && (
                    <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                      {c.reason}
                    </div>
                  )}
                  {expandedShared === c.paperId && Array.isArray(c.shared_refs_titles) && c.shared_refs_titles.length > 0 && (
                    <div className="mt-2 p-2 rounded text-xs"
                      style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}>
                      <div className="font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                        Shared references ({c.shared_refs_count}):
                      </div>
                      <ul className="space-y-0.5 list-disc pl-4" style={{ color: 'var(--color-text-secondary)' }}>
                        {c.shared_refs_titles.map((t, i) => (
                          <li key={i} className="leading-snug">{t}</li>
                        ))}
                        {c.shared_refs_count > c.shared_refs_titles.length && (
                          <li style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                            …and {c.shared_refs_count - c.shared_refs_titles.length} more
                          </li>
                        )}
                      </ul>
                    </div>
                  )}
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
