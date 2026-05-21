import { useMemo, useRef, useEffect, useState, lazy, Suspense } from 'react'
import { getEffectiveReferenceStatus } from '../../utils/referenceStatus'
import { fetchCitationGraph, expandPaper } from '../../utils/api'
import { openExternal } from '../../utils/tauriBridge'

// Lazy-load the heavy graph lib so the rest of the app stays light when
// the user never opens the Graph tab.
const ForceGraph2D = lazy(() => import('react-force-graph-2d'))

const STATUS_COLOR = {
  verified: '#22c55e',
  warning: '#f59e0b',
  error: '#ef4444',
  unverified: '#94a3b8',
  hallucinated: '#a855f7',
  suggestion: '#3b82f6',
  pending: '#64748b',
}

/**
 * Obsidian-style citation graph view.
 *
 * Nodes: every reference RefChecker pulled out of the paper. Sized by the
 *   ref's Semantic Scholar citationCount (real measure of influence —
 *   not an author-overlap proxy), colored by verification status. Plus a
 *   centre node for the source paper.
 * Edges: real inter-reference citations from the S2 graph API: an edge
 *   A → B means A's bibliography cites B. Orphan refs (cited by nothing
 *   else in this bibliography) drift to the rim.
 * Click a node → details inline; double-click → expand one hop (pull in
 * that paper's top outgoing references and add them as new nodes).
 */
export default function GraphView({ references, paperTitle }) {
  const containerRef = useRef(null)
  const fgRef = useRef(null)
  const [dims, setDims] = useState({ w: 800, h: 560 })
  const [selected, setSelected] = useState(null)
  const [hovered, setHovered] = useState(null)
  const [serverGraph, setServerGraph] = useState(null) // { byId: {local_id: {paperId, citationCount}}, edges: [{source,target}] }
  const [loadingGraph, setLoadingGraph] = useState(false)
  const [expandedNodes, setExpandedNodes] = useState([]) // [{id, paperId, title, authors, year, citationCount, parent}]
  const [expanding, setExpanding] = useState(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const update = () => setDims({ w: el.clientWidth, h: Math.max(420, Math.min(720, window.innerHeight - 280)) })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    window.addEventListener('resize', update)
    return () => { ro.disconnect(); window.removeEventListener('resize', update) }
  }, [])

  // Fetch the real S2-backed citation graph once references stabilize.
  useEffect(() => {
    const refs = (references || []).filter(r => r && (r.doi || r.arxiv_id))
    if (!refs.length) { setServerGraph(null); return }
    let cancelled = false
    setLoadingGraph(true)
    const payload = refs.map((r, i) => ({
      id: String(r.id ?? r.index ?? `ref-${i}`),
      title: r.title,
      doi: r.doi,
      arxiv_id: r.arxiv_id,
    }))
    fetchCitationGraph({ references: payload, paper_title: paperTitle })
      .then(res => {
        if (cancelled) return
        const byId = {}
        for (const n of (res.data?.nodes || [])) {
          byId[n.id] = n
        }
        setServerGraph({ byId, edges: res.data?.edges || [] })
      })
      .catch(() => { if (!cancelled) setServerGraph(null) })
      .finally(() => { if (!cancelled) setLoadingGraph(false) })
    return () => { cancelled = true }
  }, [references, paperTitle])

  const graphData = useMemo(() => {
    const refs = (references || []).filter(Boolean)
    const nodes = [{
      id: '__source__',
      label: paperTitle || '(source paper)',
      type: 'source',
      val: 30,
      color: 'var(--color-text-primary)',
    }]
    const edges = []
    const localById = {}

    // First pass: count in-paper in-degree (how many other refs in this
    // same bibliography cite each target). That's the size signal the
    // user wants — not S2's global citationCount.
    const inPaperInDegree = {}
    if (serverGraph?.edges?.length) {
      for (const e of serverGraph.edges) {
        inPaperInDegree[e.target] = (inPaperInDegree[e.target] || 0) + 1
      }
    }

    refs.forEach((r, i) => {
      const id = String(r.id ?? r.index ?? `ref-${i}`)
      const status = getEffectiveReferenceStatus(r, true)
      const serverNode = serverGraph?.byId?.[id]
      const citationCount = serverNode?.citationCount || 0
      const inDegree = inPaperInDegree[id] || 0
      // Size by in-paper in-degree (primary), with a small log-scaled
      // boost from global citationCount so orphan-but-famous refs still
      // read at a glance.
      const val = 4 + inDegree * 2.5 + Math.log10(citationCount + 1) * 0.8
      const node = {
        id,
        label: (r.title || '(no title)').slice(0, 80),
        type: 'reference',
        status,
        ref: r,
        paperId: serverNode?.paperId,
        citationCount,
        inDegree,
        val,
        color: STATUS_COLOR[status] || STATUS_COLOR.pending,
      }
      nodes.push(node)
      localById[id] = node
      edges.push({ source: '__source__', target: id })
    })

    // Real inter-reference citation edges
    if (serverGraph?.edges?.length) {
      for (const e of serverGraph.edges) {
        if (!localById[e.source] || !localById[e.target]) continue
        edges.push({ source: e.source, target: e.target, citation: true })
      }
    }

    // Expanded one-hop nodes (from double-click)
    for (const ex of expandedNodes) {
      nodes.push({
        id: ex.id,
        label: (ex.title || '(no title)').slice(0, 80),
        type: 'expanded',
        ref: ex,
        paperId: ex.paperId,
        citationCount: ex.citationCount,
        val: Math.max(3, Math.log10((ex.citationCount || 0) + 1) * 4 + 3),
        color: '#0ea5e9',
      })
      if (ex.parent) edges.push({ source: ex.parent, target: ex.id, expanded: true })
    }

    return { nodes, links: edges }
  }, [references, paperTitle, serverGraph, expandedNodes])

  const handleExpand = async (node) => {
    if (!node || !node.paperId) return
    if (expanding) return
    setExpanding(node.id)
    try {
      const res = await expandPaper({ paper_id: node.paperId, limit: 6 })
      const items = res.data?.items || []
      const additions = items
        .filter(it => it.paperId)
        .map(it => ({
          id: `exp:${node.id}:${it.paperId}`,
          parent: node.id,
          paperId: it.paperId,
          title: it.title,
          year: it.year,
          authors: it.authors,
          citationCount: it.citationCount,
          doi: it.doi,
          arxiv_id: it.arxiv_id,
          verified_url: it.doi ? `https://doi.org/${it.doi}` : (it.arxiv_id ? `https://arxiv.org/abs/${it.arxiv_id}` : `https://www.semanticscholar.org/paper/${it.paperId}`),
        }))
      // Dedup against existing expanded entries
      setExpandedNodes(prev => {
        const seen = new Set(prev.map(p => p.id))
        return [...prev, ...additions.filter(a => !seen.has(a.id))]
      })
    } catch (e) {
      // swallow — graph is best-effort
    } finally {
      setExpanding(null)
    }
  }

  return (
    <div ref={containerRef} className="rounded-lg border overflow-hidden relative"
      style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)', minHeight: 420 }}>
      <div
        className="absolute top-2 left-2 z-10 text-xs px-2 py-1 rounded"
        style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
      >
        {loadingGraph ? 'Fetching S2 citation graph…' : 'Double-click a node to expand one hop'}
        {expandedNodes.length > 0 && (
          <button
            onClick={() => setExpandedNodes([])}
            className="ml-2 underline"
            style={{ color: 'var(--color-accent, #3b82f6)' }}
          >
            Clear ({expandedNodes.length})
          </button>
        )}
      </div>
      <Suspense fallback={
        <div className="p-6 text-center text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Loading graph…
        </div>
      }>
        <ForceGraph2D
          ref={fgRef}
          graphData={graphData}
          width={dims.w}
          height={dims.h}
          backgroundColor="transparent"
          nodeRelSize={4}
          nodeColor={(n) => n.color}
          linkColor={(l) => l.citation ? 'rgba(59,130,246,0.55)' : (l.expanded ? 'rgba(14,165,233,0.45)' : 'rgba(148,163,184,0.35)')}
          linkWidth={(l) => l.citation ? 1.6 : 0.8}
          linkDirectionalArrowLength={(l) => l.citation ? 3 : 0}
          linkDirectionalArrowRelPos={1}
          cooldownTicks={140}
          d3AlphaDecay={0.02}
          d3VelocityDecay={0.4}
          onNodeClick={(n) => setSelected(n)}
          onNodeDoubleClick={(n) => handleExpand(n)}
          onNodeHover={(n) => setHovered(n || null)}
          nodeCanvasObject={(node, ctx, globalScale) => {
            const label = node.label || ''
            const radius = Math.max(3, Math.sqrt(node.val) * 1.5)
            const isHovered = hovered?.id === node.id
            const isSelected = selected?.id === node.id
            // Soft outline ring on hover / selection so the user knows which
            // node they're targeting.
            if (isHovered || isSelected) {
              ctx.fillStyle = isHovered ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.12)'
              ctx.beginPath()
              ctx.arc(node.x, node.y, radius + 4, 0, 2 * Math.PI, false)
              ctx.fill()
            }
            ctx.fillStyle = node.color || '#888'
            ctx.beginPath()
            ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false)
            ctx.fill()
            // Single-label rule: the hovered node wins. If no hover, the
            // source node always shows its label so the user has at least
            // one orientation anchor. Past 2.5× zoom, render every label.
            const showLabel = isHovered
              || (!hovered && node.type === 'source')
              || globalScale > 2.5
            if (!showLabel) return
            const fontSize = Math.max(10, 12 / globalScale)
            ctx.font = `${fontSize}px -apple-system, sans-serif`
            const text = label.slice(0, 48)
            const padX = 4
            const tx = node.x + radius + 6
            const ty = node.y
            const w = ctx.measureText(text).width + padX * 2
            const h = fontSize + 4
            ctx.fillStyle = 'rgba(15,23,42,0.92)'
            ctx.fillRect(tx - padX, ty - h / 2, w, h)
            ctx.fillStyle = 'rgba(255,255,255,0.96)'
            ctx.textAlign = 'left'
            ctx.textBaseline = 'middle'
            ctx.fillText(text, tx, ty)
          }}
        />
      </Suspense>
      {selected && (
        <div
          className="absolute bottom-2 left-2 right-2 max-w-md rounded-lg border p-3 text-xs"
          style={{
            backgroundColor: 'var(--color-bg-primary)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-text-primary)',
            boxShadow: '0 8px 24px rgba(0,0,0,0.25)',
          }}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="font-semibold mb-1">{selected.label}</div>
            <button onClick={() => setSelected(null)} className="text-xs px-2 py-0.5 rounded border"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}>×</button>
          </div>
          {selected.ref && (
            <div style={{ color: 'var(--color-text-secondary)' }}>
              {selected.ref.authors ? <div>{Array.isArray(selected.ref.authors) ? selected.ref.authors.join(', ') : selected.ref.authors}</div> : null}
              {selected.ref.year ? <div>{selected.ref.year}{selected.ref.venue ? ` · ${selected.ref.venue}` : ''}</div> : null}
              {typeof selected.inDegree === 'number' && selected.inDegree > 0 && (
                <div>Cited by {selected.inDegree} other ref{selected.inDegree === 1 ? '' : 's'} in this paper</div>
              )}
              {typeof selected.citationCount === 'number' && selected.citationCount > 0 && (
                <div style={{ opacity: 0.7 }}>{selected.citationCount.toLocaleString()} total citations on Semantic Scholar</div>
              )}
              {selected.status && (
                <div className="mt-1" style={{ color: STATUS_COLOR[selected.status] || STATUS_COLOR.pending }}>
                  Status: {selected.status}
                </div>
              )}
              {(selected.ref.verified_url || selected.ref.cited_url) && (
                <a
                  href={selected.ref.verified_url || selected.ref.cited_url}
                  onClick={(e) => {
                    e.preventDefault()
                    openExternal(selected.ref.verified_url || selected.ref.cited_url)
                  }}
                  className="block mt-1 underline"
                  style={{ color: 'var(--color-accent, #3b82f6)' }}
                >
                  Open source
                </a>
              )}
              {selected.paperId && (
                <button
                  onClick={() => handleExpand(selected)}
                  disabled={expanding === selected.id}
                  className="mt-1 underline text-xs"
                  style={{ color: 'var(--color-accent, #3b82f6)' }}
                >
                  {expanding === selected.id ? 'Expanding…' : 'Expand one hop'}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
