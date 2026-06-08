import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { findSimilarPapers } from '../../utils/api'
import { openExternal } from '../../utils/tauriBridge'
import { logger } from '../../utils/logger'

// Obsidian-style 3D force graph (three.js engine); lazy-load so three never
// touches the initial bundle — only paid when the user opens the Explore graph.
// Same dependency GraphLibraryView already uses for the Seen-References graph.
const ForceGraph3D = lazy(() => import('react-force-graph-3d'))

// Edge colour by RELATION so the user can read the neighbourhood at a glance:
//   reference → violet (this paper shares references with that work)
//   citation  → amber  (co-cited alongside this paper)
//   default   → neutral grey (similar-path link, no relation tag)
const RELATION_LINK_COLOR = {
  reference: 'rgba(167,139,250,0.55)',
  citation: 'rgba(234,179,8,0.6)',
}
const DEFAULT_LINK_COLOR = 'rgba(140,144,170,0.4)'

// Discovery modes mirror SimilarPapersPanel: three real-OpenAlex
// bibliography-overlap modes.
//   'references' — papers that SHARE REFERENCES with this paper.
//   'citations'  — papers that SHARE CITATIONS with it (co-cited).
//   'both'       — the union of the two.
const MODES = [
  { id: 'references', label: 'References' },
  { id: 'citations', label: 'Citations' },
  { id: 'both', label: 'Both' },
]

// Map a persisted/legacy mode value onto the current vocabulary so an older
// saved preference ('similar' / 'cites_refs') still resolves to a valid tab.
const LEGACY_MODE_MAP = {
  similar: 'both',
  cites_refs: 'both',
  reference: 'references',
  citation: 'citations',
}
function normalizeMode(mode) {
  if (MODES.some((m) => m.id === mode)) return mode
  return LEGACY_MODE_MAP[mode] || 'both'
}

// Literal value of the app's --color-accent green. Used for anything painted
// into the 3D scene (the distinct source node, the selected highlight), which
// cannot resolve CSS custom properties. HTML chrome still uses the CSS var.
const SOURCE_GREEN = '#22c55e'

// react-force-graph mutates link endpoints from id strings into node objects
// once the simulation runs. Resolve either shape back to the node id so the
// selected-node edge highlight works before and after that hydration.
const _linkEndId = (v) => (v && typeof v === 'object' ? v.id : v)

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
 * the centre node; every real candidate becomes a node.
 *
 * Layout strategy (fixes the "collapsed line of dots" bug):
 *  - When we have a usable year range we PIN each candidate's HORIZONTAL
 *    position to its year (left = older, right = newer) via `fx`, giving a
 *    readable timeline. The previous bug was NOT the x pinning — it was that
 *    `y` was free but nothing fanned same-year nodes apart, so they stacked on
 *    one horizontal line. The component now adds charge + a vertical-spread
 *    force so they spread out.
 *  - We seed every node with a DISTINCT initial x/y so the engine never starts
 *    with everything on (0,0) (which rendered as empty / a single dot before).
 *  - With no usable year range we fall back to a pure radial cluster around the
 *    source (no x pin), again with distinct seeds.
 *
 * REAL DATA ONLY — candidates with no usable identity are dropped, and an empty
 * response yields an empty graph (we abstain, never invent placeholder nodes).
 */
function buildGraph(candidates, paperTitle, width, height) {
  const cands = (candidates || []).filter((c) => c && (c.title || c.doi || c.arxiv_id))
  const years = cands.map((c) => c.year).filter((y) => typeof y === 'number' && y > 0)
  const minYear = years.length ? Math.min(...years) : null
  const maxYear = years.length ? Math.max(...years) : null
  const hasYearAxis = minYear !== null && maxYear !== null && maxYear !== minYear
  const w = Math.max(480, width || 800)
  const h = Math.max(360, height || 600)
  // Horizontal span used for the year axis (centred on 0).
  const spanX = w * 0.78
  const xFor = (year) => {
    if (!hasYearAxis || !year) return 0
    const t = (year - minYear) / (maxYear - minYear)
    return (t - 0.5) * spanX
  }

  const sourceNode = {
    id: '__source__',
    isSource: true,
    label: paperTitle || 'This paper',
    // Literal green — a <canvas> can't resolve CSS vars, so the source dot must
    // be a concrete colour or it renders invisible (part of the "empty" bug).
    color: SOURCE_GREEN,
    // Hard-pin the source to the centre so it stays the visual anchor (3D: pin
    // all three axes so the camera always orbits a fixed centre).
    fx: 0,
    fy: 0,
    fz: 0,
    x: 0,
    y: 0,
    z: 0,
  }
  const nodes = [sourceNode]
  const links = []
  const n = cands.length
  const ring = Math.min(w, h) * 0.34
  cands.forEach((c, idx) => {
    const id = c.paperId || c.openalex_id || c.doi || c.arxiv_id || `cand-${idx}`
    // Seed every node at a DISTINCT position so the simulation never starts with
    // all candidates stacked on (0,0) — that stacking is what produced the empty
    // / one-line render. Fan them around a circle; the forces refine from there.
    const angle = (idx / Math.max(1, n)) * Math.PI * 2
    const yearX = hasYearAxis ? xFor(c.year) : null
    // Distinct seed: along the timeline x (if any) but with a varied y so
    // same-year nodes don't begin on top of each other.
    const seedX = (yearX !== null ? yearX : Math.cos(angle) * ring)
    const seedY = Math.sin(angle) * ring + ((idx % 2 === 0 ? 1 : -1) * ((idx % 9) + 1) * 8)
    // Depth seed (3D): fan candidates around a second angle so they start
    // spread through Z rather than all stacked on the z=0 plane. Deterministic
    // (no randomness) so the layout is reproducible for the same response.
    const seedZ = Math.sin(angle * 1.7 + idx) * ring * 0.6
    const node = {
      id,
      label: c.title || '(untitled)',
      year: c.year || null,
      authors: c.authors || [],
      doi: c.doi || null,
      arxiv_id: c.arxiv_id || null,
      url: c.semantic_scholar_url || c.url || null,
      relation: c.relation || null,
      shared_refs_count: c.shared_refs_count || 0,
      // Overlap count for the bibliography-overlap (References/Citations)
      // candidates: shared references, or co-citation count.
      shared_with_source: c.shared_with_source || 0,
      sources: c.sources || [],
      color: yearColor(c.year, minYear, maxYear),
      x: seedX,
      y: seedY,
      z: seedZ,
    }
    // Pin x to the year axis (timeline). y stays free so charge + the vertical
    // spread force fan papers of the same year apart instead of overlapping
    // them on a single horizontal line (the reported bug).
    if (yearX !== null) node.fx = yearX
    nodes.push(node)
    links.push({ source: '__source__', target: id, relation: c.relation || null })
  })
  return { nodes, links, meta: { minYear, maxYear, count: cands.length, hasYearAxis } }
}

/**
 * ResearchRabbit-style EXPLORE graph (#68), rendered as an Obsidian-style 3D
 * force graph (react-force-graph-3d / three.js, the same engine the Seen-
 * References GraphLibraryView uses). Opens as a fullscreen overlay from the
 * results panel and graphs the bibliography-overlap neighbourhood of the
 * current check's references — reusing the exact /api/papers/similar pipeline
 * (References / Citations / Both modes) the Similar Papers tab already drives.
 *
 * Nodes are coloured by publication year and pinned along an x = year timeline
 * the camera can orbit; the centre "this paper" node is a distinct green; edges
 * are coloured by relation (shares references / co-cited). Nodes are DRAGGABLE
 * and pin where the user drops them (onNodeDragEnd), and hover tooltips show the
 * full title, year and real overlap count. Real data only — no fabricated nodes.
 */
export default function ExploreGraphView({ references, paperTitle, paperSource, onClose }) {
  const containerRef = useRef(null)
  const fgRef = useRef(null)
  const [dims, setDims] = useState({ w: 800, h: 600 })
  const [mode, setMode] = useState(() => normalizeMode('both'))
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

  const load = useCallback(async (activeMode) => {
    const m = activeMode || mode
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
        mode: m,
      })
      setCandidates(res.data?.candidates || [])
      setLoaded(true)
    } catch (e) {
      logger.error?.('ExploreGraph', 'fetch failed', e)
      setError(e?.response?.data?.detail || e?.message || 'Could not build the explore graph.')
    } finally {
      setLoading(false)
    }
  }, [mode, refsForRequest, paperTitle, paperId])

  // REACTIVE BUILD (fixes the "must recreate" bug): build automatically as soon
  // as we have references, and rebuild whenever the mode changes. No manual
  // "Build graph" click is required — the button is only a manual refresh.
  useEffect(() => {
    if (!refsForRequest.length) return
    load(mode)
    // We intentionally key off mode + the (stable, memoised) request payload so
    // a new search or a mode switch re-fetches; `load` is memoised on the same
    // deps so including it is safe and keeps lint happy.
  }, [mode, refsForRequest, load])

  const graphData = useMemo(
    () => buildGraph(candidates, paperTitle, dims.w, dims.h - 44),
    [candidates, paperTitle, dims.w, dims.h],
  )
  const meta = graphData.meta

  // Configure the 3D d3 force engine once the graph mounts AND whenever the
  // data changes. The year x-pin (fx) still applies in 3D, giving a horizontal
  // timeline the camera can orbit; we add:
  //   - stronger charge repulsion so nodes don't pile up,
  //   - a vertical-spread force that fans same-year nodes apart on Y,
  //   - a gentle pull toward the vertical centre so the cluster stays framed.
  useEffect(() => {
    const fg = fgRef.current
    if (!fg || graphData.nodes.length <= 1) return
    // Strong repulsion so nodes don't pile up on one coordinate.
    fg.d3Force('charge')?.strength(-280).distanceMax(700)
    // Keep candidates a readable distance from the centre / each other.
    fg.d3Force('link')?.distance(90).strength(0.2)
    // Vertical spread: candidates have x pinned to their year, so without this
    // they stack on one horizontal line. This force pushes overlapping nodes
    // apart along Y while pulling the cluster gently back to centre so it stays
    // in frame. The source is hard-pinned (fx/fy/fz) and is skipped
    // automatically (it checks fy != null). User-pinned nodes (drag-end sets
    // fy) are likewise left where the user dropped them.
    fg.d3Force('spreadY', verticalSpreadForce(64, 0.05))
    // Re-energise the layout so the new forces actually take effect (without a
    // manual recreate).
    fg.d3ReheatSimulation?.()
  }, [graphData])

  // Frame the whole graph once it settles so the user never lands on an empty /
  // off-screen scene.
  const handleEngineStop = useCallback(() => {
    fgRef.current?.zoomToFit?.(500, 80)
  }, [])

  // PIN ON DRAG END (Obsidian behaviour). While dragging, react-force-graph
  // already fixes the node; on release we PERSIST that position by writing
  // fx/fy/fz so the node stays exactly where the user parked it instead of
  // springing back. The source node is permanently pinned and left untouched.
  const handleNodeDragEnd = useCallback((node) => {
    if (!node || node.isSource) return
    node.fx = node.x
    node.fy = node.y
    node.fz = node.z
  }, [])

  return (
    <div className="fixed inset-0 z-50" style={{ background: 'var(--color-bg-primary)' }}>
      {/* Top bar */}
      <div
        className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between gap-3 px-4 py-2"
        style={{ background: 'var(--color-bg-secondary)', borderBottom: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-3">
          <strong style={{ color: 'var(--color-text-primary)' }}>Explore graph — 3D</strong>
          <div className="inline-flex rounded-md overflow-hidden" style={{ border: '1px solid var(--color-border)' }}>
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => { if (m.id !== mode) { setMode(m.id); setSelected(null) } }}
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
            onClick={() => load(mode)}
            disabled={loading || !refsForRequest.length}
            className="px-3 py-1 rounded-md"
            style={{ background: 'var(--color-accent)', color: '#fff', opacity: (loading || !refsForRequest.length) ? 0.5 : 1 }}
          >
            {loading ? 'Building…' : 'Refresh'}
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
        {refsForRequest.length > 0 && !loading && !error && loaded && graphData.nodes.length <= 1 && (
          <div className="w-full h-full flex items-center justify-center text-sm text-center px-6" style={{ color: 'var(--color-text-muted)' }}>
            No related papers surfaced from any source for this check.
          </div>
        )}
        {refsForRequest.length > 0 && !loading && !error && graphData.nodes.length > 1 && (
          <Suspense fallback={<div className="w-full h-full flex items-center justify-center text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading 3D engine…</div>}>
            <ForceGraph3D
              ref={fgRef}
              width={dims.w}
              height={dims.h - 44}
              graphData={graphData}
              backgroundColor="rgba(0,0,0,0)"
              nodeId="id"
              // Hover tooltip: full title + year, the relation, and the real
              // overlap count (shared references / co-citation). Real data only.
              nodeLabel={(node) => {
                if (node.isSource) return `${node.label} — this paper`
                const rel = node.relation === 'reference'
                  ? 'shares references'
                  : node.relation === 'citation'
                    ? 'co-cited'
                    : null
                const overlap = node.shared_with_source
                  ? (node.relation === 'citation'
                    ? `co-cited ×${node.shared_with_source}`
                    : `shares ${node.shared_with_source} ref${node.shared_with_source === 1 ? '' : 's'}`)
                  : (node.shared_refs_count
                    ? `shares ${node.shared_refs_count} ref${node.shared_refs_count === 1 ? '' : 's'}`
                    : null)
                return [
                  `${node.label}${node.year ? ` (${node.year})` : ''}`,
                  rel, overlap,
                ].filter(Boolean).join(' · ')
              }}
              // Centre "this paper" node is distinct: always the app green; the
              // selected node also highlights green. Every other node keeps its
              // year colour.
              nodeColor={(node) => node.isSource
                ? SOURCE_GREEN
                : (selected && selected.id === node.id) ? SOURCE_GREEN : node.color}
              nodeVal={(node) => (node.isSource ? 9 : 3 + Math.min(6, node.shared_refs_count || node.shared_with_source || 0))}
              nodeOpacity={0.95}
              nodeResolution={16}
              // Edges coloured BY RELATION (violet = shared refs, amber =
              // co-cited, grey = untagged similar link); the selected node's
              // own edges brighten.
              linkColor={(l) => {
                const tgt = (l.target && typeof l.target === 'object') ? l.target : null
                const rel = l.relation || tgt?.relation || null
                if (selected && (_linkEndId(l.source) === selected.id || _linkEndId(l.target) === selected.id)) {
                  return SOURCE_GREEN
                }
                return RELATION_LINK_COLOR[rel] || DEFAULT_LINK_COLOR
              }}
              linkWidth={(l) => (selected && (_linkEndId(l.source) === selected.id || _linkEndId(l.target) === selected.id)) ? 1.6 : 0.6}
              linkOpacity={0.7}
              // Draggable nodes (Obsidian-style): drag to reposition, and the
              // drop is PINNED via onNodeDragEnd so the node stays put.
              enableNodeDrag
              onNodeDragEnd={handleNodeDragEnd}
              cooldownTicks={120}
              warmupTicks={20}
              onEngineStop={handleEngineStop}
              onNodeClick={(node) => setSelected(node.isSource ? null : node)}
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
              {selected.relation ? ` · ${selected.relation === 'reference' ? 'Shared refs' : 'Shared cites'}` : ''}
              {selected.shared_with_source
                ? (selected.relation === 'citation'
                  ? ` · co-cited ×${selected.shared_with_source}`
                  : ` · shares ${selected.shared_with_source} ref${selected.shared_with_source === 1 ? '' : 's'}`)
                : (selected.shared_refs_count ? ` · shares ${selected.shared_refs_count} ref${selected.shared_refs_count === 1 ? '' : 's'}` : '')}
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
              <span style={{ width: 9, height: 9, borderRadius: 9, background: 'var(--color-accent, #22c55e)', display: 'inline-block' }} />
              <span>this paper</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span style={{ width: 36, height: 8, borderRadius: 4, background: 'linear-gradient(90deg, rgb(59,130,246), rgb(245,158,11))', display: 'inline-block' }} />
              <span>{meta.hasYearAxis ? 'older → newer (x = year)' : 'colour = year'}</span>
            </div>
            {/* Edge legend — links are coloured by relation. */}
            <div className="flex items-center gap-1.5">
              <span style={{ width: 16, height: 0, borderTop: '2px solid rgba(167,139,250,0.85)', display: 'inline-block' }} />
              <span>shares references</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span style={{ width: 16, height: 0, borderTop: '2px solid rgba(234,179,8,0.9)', display: 'inline-block' }} />
              <span>co-cited</span>
            </div>
            <div className="mt-1" style={{ borderTop: '1px solid var(--color-border)', paddingTop: 3 }}>
              drag a node to pin it · scroll/drag to orbit
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// --- Vertical-spread force --------------------------------------------------
// react-force-graph's d3Force(name, force) accepts any d3-force-compatible
// force: a function invoked with `(alpha)` each tick that has an
// `.initialize(nodes)` method. We keep the component self-contained with one
// small force that does two things every tick:
//   1. pushes pairs of nodes that overlap vertically (similar x, close y) apart
//      along Y — this is what fans same-year candidates off a single line, and
//   2. pulls every (non-pinned) node gently toward y=0 so the cluster stays in
//      frame instead of drifting off-canvas.
// `gap` is the minimum vertical breathing room; `centering` is the pull-to-
// centre strength. The hard-pinned source (fy != null) is left untouched.
function verticalSpreadForce(gap, centering) {
  let nodes = []
  function force(alpha) {
    const n = nodes.length
    // Pairwise vertical separation for nodes that share roughly the same x.
    for (let i = 0; i < n; i += 1) {
      const a = nodes[i]
      for (let j = i + 1; j < n; j += 1) {
        const b = nodes[j]
        // Only nudge nodes that are horizontally close (same year column).
        if (Math.abs((a.x || 0) - (b.x || 0)) > gap) continue
        const dy = (a.y || 0) - (b.y || 0)
        const adyAbs = Math.abs(dy)
        if (adyAbs >= gap) continue
        // Push them apart proportionally to how much they overlap.
        const push = ((gap - adyAbs) / gap) * alpha * 0.6
        const dir = dy === 0 ? (i % 2 === 0 ? 1 : -1) : Math.sign(dy)
        if (a.fy == null) a.vy += dir * push
        if (b.fy == null) b.vy -= dir * push
      }
    }
    // Gentle centering so the spread cluster stays framed.
    for (let i = 0; i < n; i += 1) {
      const node = nodes[i]
      if (node.fy != null) continue
      node.vy += (0 - (node.y || 0)) * centering * alpha
    }
  }
  force.initialize = (n) => { nodes = n }
  return force
}

// Pure, side-effect-free helpers co-located with the component so they can be
// unit-tested directly (see ExploreGraphView.test.jsx). They evaluate no React
// and don't trigger the lazy graph import, so fast-refresh isn't affected.
// eslint-disable-next-line react-refresh/only-export-components
export { buildGraph, yearColor }
