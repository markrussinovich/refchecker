import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { fetchReferenceLibraryGraph } from '../../utils/api'
import { logger } from '../../utils/logger'

// 3D force graph is heavy (three.js); lazy-load so it never touches the
// initial bundle — only paid when the user opens the library graph.
const ForceGraph3D = lazy(() => import('react-force-graph-3d'))

const STATUS_COLOR = {
  verified: '#22c55e',
  warning: '#f59e0b',
  error: '#ef4444',
  unverified: '#94a3b8',
  hallucinated: '#a855f7',
}
const STATUS_ORDER = { verified: 0, warning: 1, error: 2, hallucinated: 3, unverified: 4 }
const _linkEnd = (v) => (v && typeof v === 'object' ? v.id : v)

/**
 * 2D radial / chord view of the same library graph. Nodes are placed on a
 * circle (grouped by status, then by times-seen), edges drawn as Bézier chords
 * curving through the centre. Pure SVG, no graph engine, no new dependency.
 * Hovering a node spotlights its chords; clicking opens the same detail card.
 */
function RadialChordGraph({ data, width, height, onNodeClick }) {
  const [hover, setHover] = useState(null)
  // Clicking a node PINS its connections (common articles stay spotlighted)
  // until you click empty space or another node. Hover still previews.
  const [pinned, setPinned] = useState(null)
  const layout = useMemo(() => {
    const nodes = data?.nodes || []
    const w = Math.max(320, width), h = Math.max(320, height)
    const cx = w / 2, cy = h / 2
    const R = Math.max(80, Math.min(w, h) / 2 - 90)
    const ordered = [...nodes].sort((a, b) =>
      (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) || (b.times_seen || 0) - (a.times_seen || 0))
    const pos = {}
    const n = ordered.length || 1
    ordered.forEach((node, i) => {
      const ang = (i / n) * 2 * Math.PI - Math.PI / 2
      pos[node.id] = { x: cx + R * Math.cos(ang), y: cy + R * Math.sin(ang), ang, node }
    })
    const ids = new Set(nodes.map((nd) => nd.id))
    const links = (data?.links || [])
      .map((l) => ({ s: _linkEnd(l.source), t: _linkEnd(l.target), weight: l.weight || 1 }))
      .filter((l) => ids.has(l.s) && ids.has(l.t) && l.s !== l.t)
    return { ordered, pos, links, cx, cy, w, h }
  }, [data, width, height])

  const { ordered, pos, links, cx, cy, w, h } = layout
  const chord = (a, b) => `M${a.x.toFixed(1)},${a.y.toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${b.x.toFixed(1)},${b.y.toFixed(1)}`
  const focus = pinned || hover // pinned wins; hover previews when nothing pinned
  const infoId = hover || pinned // info panel follows the cursor, falls back to the pinned node

  return (
    <svg width={w} height={h} style={{ display: 'block' }}
      onClick={(e) => { if (e.target === e.currentTarget) setPinned(null) }}>
      {/* Background catcher: click empty space to clear the pinned node. */}
      <rect x={0} y={0} width={w} height={h} fill="transparent" onClick={() => setPinned(null)} />
      <g>
        {links.map((l, i) => {
          const a = pos[l.s], b = pos[l.t]
          if (!a || !b) return null
          const active = focus && (l.s === focus || l.t === focus)
          return (
            <path key={i} d={chord(a, b)} fill="none" pointerEvents="none"
              stroke={active ? 'var(--color-accent, #3b82f6)' : 'rgba(140,140,160,0.18)'}
              strokeWidth={active ? 1.7 : Math.min(1.5, l.weight * 0.5)}
              opacity={focus && !active ? 0.05 : 1} />
          )
        })}
      </g>
      <g>
        {ordered.map((node) => {
          const p = pos[node.id]
          if (!p) return null
          const r = Math.sqrt(Math.max(1, node.times_seen || 1)) * 1.7 + 2.5
          const connected = links.some((l) => (l.s === focus && l.t === node.id) || (l.t === focus && l.s === node.id))
          const dim = focus && focus !== node.id && !connected
          const isPinned = pinned === node.id
          return (
            <circle key={node.id} cx={p.x} cy={p.y} r={isPinned ? r + 1.5 : r}
              fill={STATUS_COLOR[node.status] || STATUS_COLOR.unverified}
              opacity={dim ? 0.2 : 1}
              stroke={focus === node.id ? 'var(--color-text-primary)' : 'rgba(0,0,0,0.25)'}
              strokeWidth={focus === node.id ? 1.8 : 0.5}
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => setHover(node.id)}
              onMouseLeave={() => setHover((hh) => (hh === node.id ? null : hh))}
              onClick={(e) => { e.stopPropagation(); setPinned((pp) => (pp === node.id ? null : node.id)); onNodeClick(node) }}>
              <title>{`${node.label}${node.year ? ` (${node.year})` : ''} — seen ${node.times_seen}×`}</title>
            </circle>
          )
        })}
      </g>
      {focus && pos[focus] && (
        <g pointerEvents="none">
          <text x={pos[focus].x} y={pos[focus].y - 10} textAnchor="middle"
            fontSize="11" fill="var(--color-text-primary)"
            style={{ paintOrder: 'stroke', stroke: 'var(--color-bg-primary)', strokeWidth: 3 }}>
            {(pos[focus].node.label || '').slice(0, 48)}
          </text>
        </g>
      )}
      {/* Article info panel — shows on hover, and stays on the pinned node.
          Top-left so it never collides with the legend / pinned hint. */}
      {infoId && pos[infoId] && (() => {
        const nd = pos[infoId].node
        const ident = nd.doi ? `DOI: ${nd.doi}` : (nd.arxiv_id ? `arXiv: ${nd.arxiv_id}` : '')
        return (
          <foreignObject x={10} y={10} width={Math.min(330, w - 20)} height={108} pointerEvents="none">
            <div xmlns="http://www.w3.org/1999/xhtml" style={{
              padding: '8px 10px', borderRadius: 8, fontSize: 12, lineHeight: 1.4,
              background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)',
              color: 'var(--color-text-primary)', boxShadow: '0 4px 14px rgba(0,0,0,0.35)' }}>
              <div style={{ fontWeight: 600, marginBottom: 2, display: '-webkit-box',
                WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{nd.label}</div>
              <div style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
                {(nd.venue || '—')}{nd.year ? ` · ${nd.year}` : ''} · seen {nd.times_seen}× · {nd.status}
              </div>
              {ident && (
                <div style={{ color: 'var(--color-text-secondary)', fontSize: 11, marginTop: 2,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ident}</div>
              )}
            </div>
          </foreignObject>
        )
      })()}
      {pinned && (
        <text x={10} y={h - 10} fontSize="11" fill="var(--color-text-muted)" pointerEvents="none">
          Pinned · click empty space to reset
        </text>
      )}
    </svg>
  )
}

/**
 * Obsidian-style 3D graph of the entire Seen References library.
 * Nodes = deduped references (size ∝ times_seen, colour by status); edges =
 * shared authors / venue. Opened as a fullscreen overlay from the Seen Refs tab.
 */
export default function GraphLibraryView({ onClose }) {
  const containerRef = useRef(null)
  const fgRef = useRef(null)
  const [dims, setDims] = useState({ w: 800, h: 600 })
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [minSeen, setMinSeen] = useState(1)
  const [edgeStrategy, setEdgeStrategy] = useState('shared-authors')
  const [selected, setSelected] = useState(null)
  const [viewMode, setViewMode] = useState('3d') // '3d' | 'radial'

  useEffect(() => {
    const el = containerRef.current
    if (!el) return undefined
    const update = () => setDims({ w: el.clientWidth, h: el.clientHeight })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchReferenceLibraryGraph({ limit: 500, min_times_seen: minSeen, edge_strategy: edgeStrategy })
      .then((res) => {
        if (cancelled) return
        const d = res?.data || { nodes: [], links: [], meta: {} }
        setData({
          nodes: (d.nodes || []).map((n) => ({ ...n, color: STATUS_COLOR[n.status] || STATUS_COLOR.unverified })),
          links: d.links || [],
          meta: d.meta || {},
        })
      })
      .catch((e) => {
        if (cancelled) return
        logger.error?.('GraphLibrary', 'fetch failed', e)
        setError(e?.response?.data?.detail || e?.message || 'Could not load the library graph.')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [minSeen, edgeStrategy])

  // Esc closes.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const graphData = useMemo(() => data || { nodes: [], links: [] }, [data])
  const nodeVal = (n) => Math.sqrt(Math.max(1, n.times_seen || 1)) * 2 + 2

  // Neighbour index for click-to-spotlight: clicking a node keeps its links and
  // co-seen neighbours highlighted (in 3D, mirroring the radial pin) until you
  // click empty space or another node.
  const neighborIndex = useMemo(() => {
    const nodes = new Map(); const linksByNode = new Map()
    for (const n of graphData.nodes) { nodes.set(n.id, new Set()); linksByNode.set(n.id, new Set()) }
    for (const l of (graphData.links || [])) {
      const s = _linkEnd(l.source), t = _linkEnd(l.target)
      if (nodes.has(s) && nodes.has(t)) {
        nodes.get(s).add(t); nodes.get(t).add(s)
        linksByNode.get(s).add(l); linksByNode.get(t).add(l)
      }
    }
    return { nodes, linksByNode }
  }, [graphData])

  const [hl, setHl] = useState({ id: null, nodes: new Set(), links: new Set() })
  useEffect(() => { setHl({ id: null, nodes: new Set(), links: new Set() }) }, [graphData])

  const focusNode = (n) => {
    setSelected(n)
    setHl((prev) => {
      if (prev.id === n.id) return { id: null, nodes: new Set(), links: new Set() }
      const nb = neighborIndex.nodes.get(n.id) || new Set()
      return { id: n.id, nodes: new Set([n.id, ...nb]), links: neighborIndex.linksByNode.get(n.id) || new Set() }
    })
    const fg = fgRef.current
    if (fg && typeof n.x === 'number') {
      const d = 110
      const r = 1 + d / Math.max(1, Math.hypot(n.x, n.y, n.z || 0))
      try { fg.cameraPosition({ x: n.x * r, y: n.y * r, z: (n.z || 0) * r }, n, 1000) } catch { /* no-op */ }
    }
  }
  const clearFocus = () => { setHl({ id: null, nodes: new Set(), links: new Set() }); setSelected(null) }

  // Obsidian-style bloom/glow on the 3D scene (lazy — three stays out of the
  // initial bundle). Retries until the post-processing composer is ready, and
  // degrades silently if the bloom pass is unavailable.
  useEffect(() => {
    if (viewMode !== '3d' || !graphData.nodes.length) return undefined
    let cancelled = false; let tries = 0
    const add = async () => {
      if (cancelled) return
      const fg = fgRef.current
      const composer = fg && fg.postProcessingComposer && fg.postProcessingComposer()
      if (!composer) { if (tries++ < 25) setTimeout(add, 200); return }
      if (composer.__bloomAdded) return
      try {
        const mod = await import('three/examples/jsm/postprocessing/UnrealBloomPass.js')
        if (cancelled) return
        const bloom = new mod.UnrealBloomPass()
        // Subtle glow, not a blinding flare: lower strength + higher threshold
        // so only the brightest nodes bloom (was 1.1/0.55/0.08 — too shiny).
        bloom.strength = 0.55; bloom.radius = 0.4; bloom.threshold = 0.2
        composer.addPass(bloom); composer.__bloomAdded = true
      } catch (e) { logger.error?.('GraphLibrary', 'bloom unavailable', e) }
    }
    add()
    return () => { cancelled = true }
  }, [viewMode, graphData])

  const meta = data?.meta || {}

  return (
    <div className="fixed inset-0 z-50" style={{ background: 'var(--color-bg-primary)' }}>
      {/* Top bar */}
      <div
        className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between gap-3 px-4 py-2"
        style={{ background: 'var(--color-bg-secondary)', borderBottom: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-3">
          <strong style={{ color: 'var(--color-text-primary)' }}>Seen References — {viewMode === 'radial' ? 'radial graph' : '3D graph'}</strong>
          <div className="inline-flex rounded-md overflow-hidden" style={{ border: '1px solid var(--color-border)' }}>
            {['3d', 'radial'].map((mode) => (
              <button key={mode} type="button" onClick={() => setViewMode(mode)}
                className="px-2.5 py-1 text-xs"
                style={viewMode === mode
                  ? { background: 'var(--color-accent)', color: '#fff' }
                  : { background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}>
                {mode === '3d' ? '3D' : 'Radial'}
              </button>
            ))}
          </div>
          {data && (
            <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
              {meta.shown_refs} of {meta.total_refs} refs · {meta.total_edges} links
              {meta.culled_edges ? ` · ${meta.culled_edges} weak links hidden` : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <label style={{ color: 'var(--color-text-muted)' }}>Edges</label>
          <select
            value={edgeStrategy}
            onChange={(e) => setEdgeStrategy(e.target.value)}
            className="px-2 py-1 rounded-md"
            style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}
          >
            <option value="shared-authors">Shared authors</option>
            <option value="shared-venue">Shared venue</option>
            <option value="both">Both</option>
          </select>
          <label style={{ color: 'var(--color-text-muted)' }} title="Only show references seen at least N times">Min seen</label>
          <select
            value={minSeen}
            onChange={(e) => setMinSeen(Number(e.target.value))}
            className="px-2 py-1 rounded-md"
            style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}
          >
            {[1, 2, 3, 5].map((n) => <option key={n} value={n}>{n}+</option>)}
          </select>
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
        {loading && (
          <div className="w-full h-full flex items-center justify-center text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Building graph…
          </div>
        )}
        {!loading && error && (
          <div className="w-full h-full flex items-center justify-center text-sm" style={{ color: 'var(--color-text-muted)' }}>{error}</div>
        )}
        {!loading && !error && graphData.nodes.length === 0 && (
          <div className="w-full h-full flex items-center justify-center text-sm text-center" style={{ color: 'var(--color-text-muted)' }}>
            No references seen yet (or none meet the “min seen” filter).
          </div>
        )}
        {!loading && !error && graphData.nodes.length > 0 && viewMode === 'radial' && (
          <div className="w-full h-full flex items-center justify-center">
            <RadialChordGraph data={graphData} width={dims.w} height={dims.h - 44} onNodeClick={setSelected} />
          </div>
        )}
        {!loading && !error && graphData.nodes.length > 0 && viewMode === '3d' && (
          <Suspense fallback={<div className="w-full h-full flex items-center justify-center text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading 3D engine…</div>}>
            <ForceGraph3D
              ref={fgRef}
              width={dims.w}
              height={dims.h - 44}
              graphData={graphData}
              backgroundColor="rgba(0,0,0,0)"
              nodeId="id"
              nodeVal={nodeVal}
              nodeColor={(n) => (!hl.id || hl.nodes.has(n.id)) ? n.color : 'rgba(120,124,150,0.16)'}
              nodeLabel={(n) => `${n.label}${n.year ? ` (${n.year})` : ''} — seen ${n.times_seen}×`}
              nodeOpacity={0.95}
              nodeResolution={16}
              linkColor={(l) => hl.links.has(l) ? 'rgba(96,165,250,0.95)' : (hl.id ? 'rgba(140,144,170,0.05)' : 'rgba(140,144,170,0.22)')}
              linkWidth={(l) => hl.links.has(l) ? 2.4 : Math.min(1.6, (l.weight || 1) * 0.5)}
              linkOpacity={1}
              linkDirectionalParticles={(l) => hl.links.has(l) ? 4 : 0}
              linkDirectionalParticleWidth={2}
              linkDirectionalParticleSpeed={0.006}
              linkDirectionalParticleColor={() => 'rgba(147,197,253,0.95)'}
              enableNodeDrag={false}
              onNodeClick={focusNode}
              onBackgroundClick={clearFocus}
              warmupTicks={40}
              cooldownTicks={120}
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
              {selected.venue || '—'}{selected.year ? ` · ${selected.year}` : ''} · seen {selected.times_seen}× · {selected.status}
            </div>
            {(selected.doi || selected.arxiv_id) && (
              <div className="mt-1" style={{ color: 'var(--color-text-secondary)' }}>
                {selected.doi ? `DOI: ${selected.doi}` : `arXiv: ${selected.arxiv_id}`}
              </div>
            )}
            {hl.id && viewMode === '3d' && (
              <div className="mt-1" style={{ color: 'var(--color-text-muted)' }}>Spotlighting common links · click empty space to reset</div>
            )}
            <button type="button" onClick={clearFocus} className="mt-1.5 underline" style={{ color: 'var(--color-accent)' }}>dismiss</button>
          </div>
        )}

        {/* Legend */}
        <div
          className="absolute bottom-4 right-4 z-20 p-2 rounded-lg text-[11px] flex flex-col gap-1"
          style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-muted)' }}
        >
          {Object.entries(STATUS_COLOR).map(([k, c]) => (
            <div key={k} className="flex items-center gap-1.5">
              <span style={{ width: 9, height: 9, borderRadius: 9, background: c, display: 'inline-block' }} />
              <span>{k}</span>
            </div>
          ))}
          <div className="mt-1" style={{ borderTop: '1px solid var(--color-border)', paddingTop: 3 }}>node size = times seen</div>
        </div>
      </div>
    </div>
  )
}
