import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { findSimilarPapers } from '../../utils/api'
import { openExternal } from '../../utils/tauriBridge'
import { logger } from '../../utils/logger'

// 2D force graph carries the d3-force engine; lazy-load so it never touches
// the initial bundle — only paid when the user opens the Explore graph.
const ForceGraph2D = lazy(() => import('react-force-graph-2d'))

// Discovery modes mirror SimilarPapersPanel (#63): 'similar' is the
// co-citation/overlap path; 'cites_refs' is the source paper's real OpenAlex
// references + citations; 'both' merges them.
const MODES = [
  { id: 'similar', label: 'Similar' },
  { id: 'cites_refs', label: 'Cites & Refs' },
  { id: 'both', label: 'Both' },
]

// Pick the same source-id derivation SimilarPapersPanel uses so 'cites_refs'
// mode can resolve the SOURCE paper on OpenAlex.
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

// Map a publication year onto a blue→amber gradient (older = cool blue,
// newer = warm amber). Returns a neutral grey when the year is unknown so we
// never fabricate a position/colour for missing real data.
function yearColor(year, minYear, maxYear) {
  if (!year || !minYear || !maxYear || maxYear === minYear) return '#94a3b8'
  const t = Math.max(0, Math.min(1, (year - minYear) / (maxYear - minYear)))
  // blue (59,130,246) → amber (245,158,11)
  const r = Math.round(59 + t * (245 - 59))
  const g = Math.round(130 + t * (158 - 130))
  const b = Math.round(246 + t * (11 - 246))
  return `rgb(${r},${g},${b})`
}

/**
 * Build the graph from a /api/papers/similar response. The current paper is
 * the centre node; every real candidate becomes a node whose horizontal
 * position is pinned by publication year (left = older, right = newer) and
 * whose colour follows the same year gradient. Edges connect each candidate
 * back to the source. REAL DATA ONLY — candidates with no usable identity are
 * dropped, and an empty response yields an empty graph (we abstain, never
 * invent placeholder nodes).
 */
function buildGraph(candidates, paperTitle, width) {
  const cands = (candidates || []).filter((c) => c && (c.title || c.doi || c.arxiv_id))
  const years = cands.map((c) => c.year).filter((y) => typeof y === 'number' && y > 0)
  const minYear = years.length ? Math.min(...years) : null
  const maxYear = years.length ? Math.max(...years) : null
  const w = Math.max(480, width || 800)
  const xFor = (year) => {
    if (!year || !minYear || !maxYear || maxYear === minYear) return 0
    const t = (year - minYear) / (maxYear - minYear)
    // Spread across the middle 70% of the canvas, centred on 0.
    return (t - 0.5) * (w * 0.7)
  }

  const sourceNode = {
    id: '__source__',
    isSource: true,
    label: paperTitle || 'This paper',
    color: 'var(--color-accent, #3b82f6)',
    fx: 0,
    fy: 0,
  }
  const nodes = [sourceNode]
  const links = []
  cands.forEach((c, idx) => {
    const id = c.paperId || c.openalex_id || c.doi || c.arxiv_id || `cand-${idx}`
    nodes.push({
      id,
      label: c.title || '(untitled)',
      year: c.year || null,
      authors: c.authors || [],
      doi: c.doi || null,
      arxiv_id: c.arxiv_id || null,
      url: c.semantic_scholar_url || c.url || null,
      relation: c.relation || null,
      shared_refs_count: c.shared_refs_count || 0,
      sources: c.sources || [],
      color: yearColor(c.year, minYear, maxYear),
      // Pin x by year so the layout reads as a timeline; y stays free so the
      // force engine spreads overlapping years vertically.
      fx: xFor(c.year),
    })
    links.push({ source: '__source__', target: id, relation: c.relation || null })
  })
  return { nodes, links, meta: { minYear, maxYear, count: cands.length } }
}

/**
 * ResearchRabbit-style EXPLORE graph (#68). Opens as a fullscreen overlay from
 * the results panel and graphs the SIMILAR / CITES&REFS neighbourhood of the
 * current check's references — reusing the exact /api/papers/similar pipeline
 * (incl. the #63 modes) the Similar Papers tab already drives. Nodes are
 * positioned + coloured by publication year and are individually selectable.
 */
export default function ExploreGraphView({ references, paperTitle, paperSource, onClose }) {
  const containerRef = useRef(null)
  const [dims, setDims] = useState({ w: 800, h: 600 })
  const [mode, setMode] = useState('similar')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [candidates, setCandidates] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [selected, setSelected] = useState(null)

  const paperId = deriveSourceId(paperSource)
  const refsForRequest = useMemo(() => (references || [])
    .filter((r) => r && (r.doi || r.arxiv_id || r.title))
    .map((r) => ({ doi: r.doi, arxiv_id: r.arxiv_id, title: r.title, authors: r.authors })), [references])

  // Track container size for the canvas.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return undefined
    const update = () => setDims({ w: el.clientWidth, h: el.clientHeight })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Esc closes.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const load = async () => {
    if (!refsForRequest.length) return
    setLoading(true)
    setError(null)
    setSelected(null)
    try {
      const res = await findSimilarPapers({
        references: refsForRequest,
        paper_title: paperTitle,
        paper_id: paperId || undefined,
        limit: 25,
        mode,
      })
      setCandidates(res.data?.candidates || [])
      setLoaded(true)
    } catch (e) {
      logger.error?.('ExploreGraph', 'fetch failed', e)
      setError(e?.response?.data?.detail || e?.message || 'Could not build the explore graph.')
    } finally {
      setLoading(false)
    }
  }

  const graphData = useMemo(
    () => buildGraph(candidates, paperTitle, dims.w),
    [candidates, paperTitle, dims.w],
  )
  const meta = graphData.meta

  return (
    <div className="fixed inset-0 z-50" style={{ background: 'var(--color-bg-primary)' }}>
      {/* Top bar */}
      <div
        className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between gap-3 px-4 py-2"
        style={{ background: 'var(--color-bg-secondary)', borderBottom: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-3">
          <strong style={{ color: 'var(--color-text-primary)' }}>Explore graph</strong>
          <div className="inline-flex rounded-md overflow-hidden" style={{ border: '1px solid var(--color-border)' }}>
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => { if (m.id !== mode) { setMode(m.id); setLoaded(false); setCandidates([]); setSelected(null) } }}
                className="px-2.5 py-1 text-xs"
                style={mode === m.id
                  ? { background: 'var(--color-accent)', color: '#fff' }
                  : { background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}
              >
                {m.label}
              </button>
            ))}
          </div>
          {loaded && (
            <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
              {meta.count} paper{meta.count === 1 ? '' : 's'}
              {meta.minYear ? ` · ${meta.minYear}–${meta.maxYear}` : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button
            type="button"
            onClick={load}
            disabled={loading || !refsForRequest.length}
            className="px-3 py-1 rounded-md"
            style={{ background: 'var(--color-accent)', color: '#fff', opacity: (loading || !refsForRequest.length) ? 0.5 : 1 }}
          >
            {loading ? 'Building…' : (loaded ? 'Refresh' : 'Build graph')}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1 rounded-md"
            style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}
          >
            Close
          </button>
        </div>
      </div>

      {/* Graph canvas */}
      <div ref={containerRef} className="absolute inset-0" style={{ paddingTop: 44 }}>
        {!refsForRequest.length && (
          <div className="w-full h-full flex items-center justify-center text-sm text-center px-6" style={{ color: 'var(--color-text-muted)' }}>
            Run a check first — Explore needs at least one reference to graph from.
          </div>
        )}
        {refsForRequest.length > 0 && loading && (
          <div className="w-full h-full flex items-center justify-center text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Querying real sources (Semantic Scholar / OpenAlex)…
          </div>
        )}
        {refsForRequest.length > 0 && !loading && error && (
          <div className="w-full h-full flex items-center justify-center text-sm text-center px-6" style={{ color: 'var(--color-text-muted)' }}>{error}</div>
        )}
        {refsForRequest.length > 0 && !loading && !error && !loaded && (
          <div className="w-full h-full flex items-center justify-center text-sm text-center px-6" style={{ color: 'var(--color-text-muted)' }}>
            Build the graph to explore the {mode === 'cites_refs' ? 'citation neighbourhood' : 'similar-paper neighbourhood'} of this check’s references.
          </div>
        )}
        {refsForRequest.length > 0 && !loading && !error && loaded && graphData.nodes.length <= 1 && (
          <div className="w-full h-full flex items-center justify-center text-sm text-center px-6" style={{ color: 'var(--color-text-muted)' }}>
            No related papers surfaced from any source for this check.
          </div>
        )}
        {refsForRequest.length > 0 && !loading && !error && loaded && graphData.nodes.length > 1 && (
          <Suspense fallback={<div className="w-full h-full flex items-center justify-center text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading graph engine…</div>}>
            <ForceGraph2D
              width={dims.w}
              height={dims.h - 44}
              graphData={graphData}
              backgroundColor="rgba(0,0,0,0)"
              nodeId="id"
              nodeLabel={(n) => `${n.label}${n.year ? ` (${n.year})` : ''}`}
              nodeColor={(n) => (selected && selected.id === n.id) ? 'var(--color-accent, #3b82f6)' : n.color}
              nodeVal={(n) => (n.isSource ? 8 : 3 + Math.min(6, n.shared_refs_count || 0))}
              nodeRelSize={4}
              linkColor={() => 'rgba(140,144,170,0.28)'}
              linkWidth={1}
              enableNodeDrag={false}
              cooldownTicks={80}
              onNodeClick={(n) => setSelected(n.isSource ? null : n)}
              onBackgroundClick={() => setSelected(null)}
            />
          </Suspense>
        )}

        {/* Selected-node detail card */}
        {selected && (
          <div
            className="absolute bottom-4 left-4 z-20 p-3 rounded-lg text-xs"
            style={{ maxWidth: 360, background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-primary)' }}
          >
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{selected.label}</div>
            <div style={{ color: 'var(--color-text-muted)' }}>
              {(selected.authors || []).slice(0, 3).join(', ')}
              {(selected.authors || []).length > 3 ? ', et al.' : ''}
              {selected.year ? ` · ${selected.year}` : ''}
              {selected.relation ? ` · ${selected.relation === 'reference' ? 'Reference' : 'Citation'}` : ''}
              {selected.shared_refs_count ? ` · shares ${selected.shared_refs_count} ref${selected.shared_refs_count === 1 ? '' : 's'}` : ''}
            </div>
            {(selected.doi || selected.arxiv_id || selected.url) && (
              <button
                type="button"
                onClick={() => {
                  const target = selected.doi
                    ? `https://doi.org/${selected.doi}`
                    : selected.arxiv_id
                      ? `https://arxiv.org/abs/${selected.arxiv_id}`
                      : selected.url
                  if (typeof window !== 'undefined' && window.__TAURI_INTERNALS__) openExternal(target)
                  else window.open(target, '_blank', 'noopener,noreferrer')
                }}
                className="mt-1.5 underline"
                style={{ color: 'var(--color-accent)' }}
              >
                Open paper
              </button>
            )}
          </div>
        )}

        {/* Legend */}
        {loaded && graphData.nodes.length > 1 && (
          <div
            className="absolute bottom-4 right-4 z-20 p-2 rounded-lg text-[11px] flex flex-col gap-1"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-muted)' }}
          >
            <div className="flex items-center gap-1.5">
              <span style={{ width: 9, height: 9, borderRadius: 9, background: 'var(--color-accent, #3b82f6)', display: 'inline-block' }} />
              <span>this paper</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span style={{ width: 36, height: 8, borderRadius: 4, background: 'linear-gradient(90deg, rgb(59,130,246), rgb(245,158,11))', display: 'inline-block' }} />
              <span>older → newer (x = year)</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Pure, side-effect-free helpers co-located with the component so they can be
// unit-tested directly (see ExploreGraphView.test.jsx). They evaluate no React
// and don't trigger the lazy graph import, so fast-refresh isn't affected.
// eslint-disable-next-line react-refresh/only-export-components
export { buildGraph, yearColor }
