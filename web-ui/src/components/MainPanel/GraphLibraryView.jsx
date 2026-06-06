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

  const meta = data?.meta || {}

  return (
    <div className="fixed inset-0 z-50" style={{ background: 'var(--color-bg-primary)' }}>
      {/* Top bar */}
      <div
        className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between gap-3 px-4 py-2"
        style={{ background: 'var(--color-bg-secondary)', borderBottom: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-3">
          <strong style={{ color: 'var(--color-text-primary)' }}>Seen References — 3D graph</strong>
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
        {!loading && !error && graphData.nodes.length > 0 && (
          <Suspense fallback={<div className="w-full h-full flex items-center justify-center text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading 3D engine…</div>}>
            <ForceGraph3D
              ref={fgRef}
              width={dims.w}
              height={dims.h - 44}
              graphData={graphData}
              backgroundColor="rgba(0,0,0,0)"
              nodeId="id"
              nodeVal={nodeVal}
              nodeColor={(n) => n.color}
              nodeLabel={(n) => `${n.label}${n.year ? ` (${n.year})` : ''} — seen ${n.times_seen}×`}
              nodeOpacity={0.92}
              linkColor={() => 'rgba(140,140,160,0.25)'}
              linkWidth={(l) => Math.min(2, (l.weight || 1) * 0.6)}
              enableNodeDrag={false}
              onNodeClick={(n) => setSelected(n)}
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
            <button type="button" onClick={() => setSelected(null)} className="mt-1.5 underline" style={{ color: 'var(--color-accent)' }}>dismiss</button>
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
