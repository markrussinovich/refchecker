import { useMemo, useRef, useEffect, useState, lazy, Suspense } from 'react'
import { getEffectiveReferenceStatus } from '../../utils/referenceStatus'

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
 * Nodes: every reference RefChecker pulled out of the paper, sized by
 *   how many other refs cited it (proxy: same author overlap in this
 *   paper's bibliography), colored by verification status. Plus one
 *   centre node for the paper itself.
 * Edges: paper -> every reference. Co-cited refs (sharing an author)
 *   get extra short edges so they cluster together. Orphan refs (no
 *   shared author with anyone else) drift to the rim — hallucinations
 *   tend to land there because they don't share authors with anything.
 *
 * Click a node → shows its details inline; double-click → opens the
 * verified URL in the browser. Drag-pan + scroll-zoom are built into
 * react-force-graph-2d so we don't add interaction code here.
 */
export default function GraphView({ references, paperTitle }) {
  const containerRef = useRef(null)
  const fgRef = useRef(null)
  const [dims, setDims] = useState({ w: 800, h: 560 })
  const [selected, setSelected] = useState(null)

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
    const authorIndex = new Map() // author -> [refIds]

    refs.forEach((r, i) => {
      const id = String(r.id ?? r.index ?? `ref-${i}`)
      const status = getEffectiveReferenceStatus(r, true)
      const tags = []
      ;(r.authors ? (Array.isArray(r.authors) ? r.authors : String(r.authors).split(/,\s*|\s+and\s+/)) : []).forEach((a) => {
        const key = String(a).trim().toLowerCase()
        if (!key) return
        const list = authorIndex.get(key) || []
        list.push(id)
        authorIndex.set(key, list)
        tags.push(key)
      })
      nodes.push({
        id,
        label: (r.title || '(no title)').slice(0, 80),
        type: 'reference',
        status,
        ref: r,
        val: 6,
        color: STATUS_COLOR[status] || STATUS_COLOR.pending,
      })
      edges.push({ source: '__source__', target: id })
    })

    // Co-citation edges: refs sharing at least one author
    const added = new Set()
    for (const [, list] of authorIndex) {
      if (list.length < 2) continue
      for (let i = 0; i < list.length; i++) {
        for (let j = i + 1; j < list.length; j++) {
          const a = list[i], b = list[j]
          const k = a < b ? `${a}|${b}` : `${b}|${a}`
          if (added.has(k)) continue
          added.add(k)
          edges.push({ source: a, target: b, cocitation: true })
        }
      }
    }

    return { nodes, links: edges }
  }, [references, paperTitle])

  return (
    <div ref={containerRef} className="rounded-lg border overflow-hidden relative"
      style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)', minHeight: 420 }}>
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
          linkColor={(l) => l.cocitation ? 'rgba(59,130,246,0.35)' : 'rgba(148,163,184,0.35)'}
          linkWidth={(l) => l.cocitation ? 1.6 : 0.8}
          cooldownTicks={120}
          onNodeClick={(n) => setSelected(n)}
          onNodeDoubleClick={(n) => {
            const url = n?.ref?.verified_url || n?.ref?.cited_url
            if (url) window.open(url, '_blank', 'noopener,noreferrer')
          }}
          nodeCanvasObject={(node, ctx, globalScale) => {
            const label = node.label || ''
            const fontSize = 12 / globalScale
            ctx.fillStyle = node.color || '#888'
            ctx.beginPath()
            ctx.arc(node.x, node.y, Math.max(3, Math.sqrt(node.val) * 1.5), 0, 2 * Math.PI, false)
            ctx.fill()
            if (globalScale > 1.0 || node.type === 'source') {
              ctx.fillStyle = 'rgba(255,255,255,0.85)'
              ctx.font = `${fontSize}px -apple-system, sans-serif`
              ctx.textAlign = 'left'
              ctx.textBaseline = 'middle'
              ctx.fillText(label.slice(0, 40), node.x + 6, node.y)
            }
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
              <div className="mt-1" style={{ color: STATUS_COLOR[selected.status] || STATUS_COLOR.pending }}>
                Status: {selected.status}
              </div>
              {selected.ref.verified_url && (
                <a href={selected.ref.verified_url} target="_blank" rel="noreferrer"
                  className="block mt-1 underline" style={{ color: 'var(--color-accent, #3b82f6)' }}>
                  Open verified source
                </a>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
