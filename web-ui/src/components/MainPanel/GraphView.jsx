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
  // Filters / display modes. When `hideSourceSpokes` is on we drop the
  // source-paper -> ref edges so the actual co-citation structure
  // between refs reads cleanly (otherwise everything spokes off the
  // centre node and the inter-ref edges drown).
  const [hideSourceSpokes, setHideSourceSpokes] = useState(false)

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

    // Out-degree too — used along with in-degree to detect orphans
    // (refs with no co-citation links at all) so they can be styled and
    // visually pushed to the rim.
    const inPaperOutDegree = {}
    if (serverGraph?.edges?.length) {
      for (const e of serverGraph.edges) {
        inPaperOutDegree[e.source] = (inPaperOutDegree[e.source] || 0) + 1
      }
    }

    refs.forEach((r, i) => {
      const id = String(r.id ?? r.index ?? `ref-${i}`)
      const status = getEffectiveReferenceStatus(r, true)
      const serverNode = serverGraph?.byId?.[id]
      const citationCount = serverNode?.citationCount || 0
      const inDegree = inPaperInDegree[id] || 0
      const outDegree = inPaperOutDegree[id] || 0
      const isOrphan = inDegree === 0 && outDegree === 0
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
        outDegree,
        isOrphan,
        val,
        color: STATUS_COLOR[status] || STATUS_COLOR.pending,
      }
      nodes.push(node)
      localById[id] = node
      // The source-paper spoke is optional — hiding it lets the
      // co-citation structure read clearly without the centre node
      // dragging everything into a rosette.
      if (!hideSourceSpokes) {
        edges.push({ source: '__source__', target: id, spoke: true })
      }
    })

    // Real inter-reference citation edges
    if (serverGraph?.edges?.length) {
      for (const e of serverGraph.edges) {
        if (!localById[e.source] || !localById[e.target]) continue
        edges.push({ source: e.source, target: e.target, citation: true })
      }
    }

    // Expanded one-hop nodes (from double-click). Sized by the
    // expanded paper's S2 citation count so the user can pick out
    // landmark-influential refs at a glance. Coloured by the 2nd-degree
    // verify status when it's known (the expand endpoint probes the
    // Seen-Refs cache and returns `verified_status`) — that's the
    // "shows the references status of the references in the article"
    // 2nd-degree analysis. Unknown / un-probed nodes fall back to cyan
    // so they're still distinguishable from the in-paper nodes.
    const EXPANDED_FALLBACK = '#0ea5e9'
    for (const ex of expandedNodes) {
      const expStatus = ex.verified_status
      const expColor = expStatus && expStatus !== 'unknown'
        ? (STATUS_COLOR[expStatus] || EXPANDED_FALLBACK)
        : EXPANDED_FALLBACK
      nodes.push({
        id: ex.id,
        label: (ex.title || '(no title)').slice(0, 80),
        type: 'expanded',
        ref: ex,
        paperId: ex.paperId,
        status: expStatus || 'unknown',
        citationCount: ex.citationCount,
        val: Math.max(4, Math.log10((ex.citationCount || 0) + 1) * 4.5 + 4),
        color: expColor,
      })
      if (ex.parent) edges.push({ source: ex.parent, target: ex.id, expanded: true })
    }

    return { nodes, links: edges }
  }, [references, paperTitle, serverGraph, expandedNodes, hideSourceSpokes])

  // Tune the force-graph engine: orphans (refs with no co-citation
  // edges) should drift outward so they cluster at the rim — that's the
  // visual cue the user asked for ("hallucinated refs land there
  // visually"). We do this by overriding the charge force per-node so
  // orphans repel everyone harder than well-connected nodes.
  useEffect(() => {
    const fg = fgRef.current
    if (!fg || typeof fg.d3Force !== 'function') return
    try {
      const charge = fg.d3Force('charge')
      if (charge && typeof charge.strength === 'function') {
        charge.strength((node) => {
          if (node.type === 'source') return -180
          if (node.isOrphan) return -260
          // Connected refs pull each other inward more gently.
          return -60 - Math.min(8, (node.inDegree || 0)) * 12
        })
      }
      // Re-heat the simulation so the new strengths take effect.
      if (typeof fg.d3ReheatSimulation === 'function') fg.d3ReheatSimulation()
    } catch {
      /* d3Force not yet wired — next data update will re-trigger */
    }
  }, [graphData])

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
          // 2nd-degree verify status (from Seen-Refs cache probe on the
          // backend). Lets the graph colour expanded nodes by their
          // verification result instead of a uniform cyan.
          verified_status: it.verified_status || 'unknown',
          pre_verified: !!it.pre_verified,
          times_seen: it.times_seen || 0,
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

  // ── 2nd-level auto-expansion ─────────────────────────────────────
  // Expand every verified reference one hop in parallel (capped at 4 in
  // flight) so the user sees the references-of-references tree without
  // having to double-click each node. Heavy on the S2 API — gated behind
  // an explicit toggle.
  const [autoExpanding, setAutoExpanding] = useState(false)
  const [autoExpanded, setAutoExpanded] = useState(false)
  const eligibleNodes = useMemo(() => (
    Object.values(serverGraph?.byId || {}).filter(n => n?.paperId)
  ), [serverGraph])

  const runAutoExpand = async () => {
    if (autoExpanding || !eligibleNodes.length) return
    setAutoExpanding(true)
    try {
      const queue = eligibleNodes.slice(0, 25)  // hard cap for sanity
      const worker = async () => {
        while (queue.length) {
          const node = queue.shift()
          try {
            const res = await expandPaper({ paper_id: node.paperId, limit: 4 })
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
            setExpandedNodes(prev => {
              const seen = new Set(prev.map(p => p.id))
              return [...prev, ...additions.filter(a => !seen.has(a.id))]
            })
          } catch { /* skip this one */ }
        }
      }
      await Promise.all([worker(), worker(), worker(), worker()])
      setAutoExpanded(true)
    } finally {
      setAutoExpanding(false)
    }
  }

  return (
    <div ref={containerRef} className="rounded-lg border overflow-hidden relative"
      style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)', minHeight: 420 }}>
      <div
        className="absolute top-2 left-2 z-10 text-xs px-2 py-1 rounded flex items-center gap-2 flex-wrap"
        style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
      >
        <span>
          {loadingGraph ? 'Fetching S2 citation graph…' : 'Double-click a node to expand one hop'}
        </span>
        <label className="inline-flex items-center gap-1 cursor-pointer" title="Hide source-paper spokes so the co-citation structure between refs reads clearly. Orphan refs drift to the rim.">
          <input
            type="checkbox"
            checked={hideSourceSpokes}
            onChange={(e) => setHideSourceSpokes(e.target.checked)}
            style={{ accentColor: 'var(--color-accent, #3b82f6)' }}
          />
          <span>Hide source spokes</span>
        </label>
        {eligibleNodes.length > 0 && (
          <button
            onClick={runAutoExpand}
            disabled={autoExpanding}
            className="ml-1 px-2 py-0.5 rounded"
            style={{
              border: '1px solid var(--color-border)',
              background: 'var(--color-bg-secondary)',
              color: autoExpanded ? 'var(--color-success, #16a34a)' : 'var(--color-text-secondary)',
              opacity: autoExpanding ? 0.6 : 1,
            }}
            title={`Pre-fetch each verified ref's own references (up to 25 refs × 4 children each)`}
          >
            {autoExpanding ? 'Expanding…' : autoExpanded ? '✓ 2nd-level expanded' : 'Expand all verified refs (2nd level)'}
          </button>
        )}
        {expandedNodes.length > 0 && (
          <button
            onClick={() => setExpandedNodes([])}
            className="underline"
            style={{ color: 'var(--color-accent, #3b82f6)' }}
          >
            Clear expanded ({expandedNodes.length})
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
          // Co-citation edges (inter-ref) are the load-bearing signal,
          // so they get the loudest stroke. Expanded one-hop edges are
          // cyan to match their nodes. Source-spoke edges (when shown)
          // are subdued so they fade behind the co-citation structure.
          linkColor={(l) =>
            l.citation
              ? 'rgba(59,130,246,0.7)'
              : l.expanded
                ? 'rgba(14,165,233,0.75)'
                : 'rgba(148,163,184,0.22)'
          }
          linkWidth={(l) => (l.citation ? 1.8 : l.expanded ? 1.5 : 0.6)}
          linkDirectionalArrowLength={(l) => (l.citation || l.expanded ? 3 : 0)}
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
            // Soft halo on hover / selection so the user knows which
            // node they're targeting.
            if (isHovered || isSelected) {
              ctx.fillStyle = isHovered ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.12)'
              ctx.beginPath()
              ctx.arc(node.x, node.y, radius + 4, 0, 2 * Math.PI, false)
              ctx.fill()
            }
            // Filled disc — primary node visual.
            ctx.fillStyle = node.color || '#888'
            ctx.beginPath()
            ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false)
            ctx.fill()
            // Status-aware emphasis rings. Orphan refs that also carry a
            // problem status (hallucinated, error, unverified) get a
            // ring in the node's own status colour — the rim position
            // already conveys "isolated", the ring layers on top to
            // call attention to the refs reviewers should look at
            // first. Verified orphans intentionally get no ring so we
            // don't visually conflate them with hallucinated colour.
            // Expanded (one-hop) nodes get a faint white ring to mark
            // them as 2nd-degree.
            const problemStatuses = new Set(['hallucinated', 'error', 'unverified'])
            if (node.isOrphan && node.type === 'reference' && problemStatuses.has(node.status)) {
              ctx.strokeStyle = node.color || 'rgba(168, 85, 247, 0.8)'
              ctx.lineWidth = Math.max(1.4, 1.8 / globalScale)
              ctx.beginPath()
              ctx.arc(node.x, node.y, radius + 2.5, 0, 2 * Math.PI, false)
              ctx.stroke()
            } else if (node.type === 'expanded') {
              ctx.strokeStyle = 'rgba(255,255,255,0.6)'
              ctx.lineWidth = Math.max(1, 1.2 / globalScale)
              ctx.beginPath()
              ctx.arc(node.x, node.y, radius + 1.5, 0, 2 * Math.PI, false)
              ctx.stroke()
            }
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
