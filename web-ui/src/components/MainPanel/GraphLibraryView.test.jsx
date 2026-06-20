import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { forwardRef, useImperativeHandle } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// jsdom has no ResizeObserver; the view observes its container for sizing.
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// --- Mocks -------------------------------------------------------------------
const fetchReferenceLibraryGraph = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({ fetchReferenceLibraryGraph }))

const openExternal = vi.hoisted(() => vi.fn())
const isTauri = vi.hoisted(() => vi.fn(() => false))
vi.mock('../../utils/tauriBridge', () => ({ openExternal, isTauri }))

vi.mock('../../utils/logger', () => ({ logger: { error: vi.fn(), warn: vi.fn(), info: vi.fn() } }))

// Capture the props ForceGraph3D is mounted with, and hand the component a fake
// graph handle (via ref) so the R38 force-tuning / auto-frame effects run
// against spies instead of the real three.js engine (which we never load).
const fg3dProps = vi.hoisted(() => ({ current: null }))
const fgHandle = vi.hoisted(() => ({
  charge: { strength: vi.fn().mockReturnThis(), distanceMax: vi.fn().mockReturnThis() },
  link: { distance: vi.fn().mockReturnThis(), strength: vi.fn().mockReturnThis() },
  d3Force: vi.fn(),
  d3ReheatSimulation: vi.fn(),
  zoomToFit: vi.fn(),
  // Returning null keeps the optional bloom pass degrading silently.
  postProcessingComposer: vi.fn(() => null),
}))
vi.mock('react-force-graph-3d', () => {
  const Mock = forwardRef((props, ref) => {
    fg3dProps.current = props
    useImperativeHandle(ref, () => fgHandle, [])
    return <div data-testid="force-graph-3d" />
  })
  return { default: Mock }
})

import GraphLibraryView from './GraphLibraryView'

const GRAPH = {
  data: {
    nodes: [
      { id: 'n1', label: 'Attention Is All You Need', status: 'verified', times_seen: 9, year: 2017, venue: 'NeurIPS', doi: '10.5555/ABC.1' },
      { id: 'n2', label: 'BERT', status: 'verified', times_seen: 5, year: 2019, venue: 'NAACL', arxiv_id: '1810.04805' },
    ],
    links: [{ source: 'n1', target: 'n2', weight: 2 }],
    meta: { shown_refs: 2, total_refs: 2, total_edges: 1 },
  },
}

beforeEach(() => {
  fetchReferenceLibraryGraph.mockReset().mockResolvedValue(GRAPH)
  openExternal.mockReset()
  isTauri.mockReset().mockReturnValue(false)
  fg3dProps.current = null
  fgHandle.d3Force.mockReset().mockImplementation((name) => (name === 'charge' ? fgHandle.charge : name === 'link' ? fgHandle.link : null))
  fgHandle.d3ReheatSimulation.mockReset()
  fgHandle.zoomToFit.mockReset()
  fgHandle.charge.strength.mockClear(); fgHandle.charge.distanceMax.mockClear()
  fgHandle.link.distance.mockClear(); fgHandle.link.strength.mockClear()
})

describe('GraphLibraryView — R38 library 3D graph polish (Explore parity)', () => {
  it('mounts ForceGraph3D with node drag + drag-end pin + onEngineStop auto-frame', async () => {
    render(<GraphLibraryView onClose={vi.fn()} />)
    await screen.findByTestId('force-graph-3d')

    const props = fg3dProps.current
    expect(props.enableNodeDrag).toBe(true)
    expect(typeof props.onNodeDragEnd).toBe('function')
    expect(typeof props.onEngineStop).toBe('function')

    // drag-end persists the dropped position by writing fx/fy/fz.
    const node = { id: 'n1', x: 12, y: 34, z: 56 }
    props.onNodeDragEnd(node)
    expect(node).toMatchObject({ fx: 12, fy: 34, fz: 56 })

    // onEngineStop auto-frames the whole graph.
    props.onEngineStop()
    expect(fgHandle.zoomToFit).toHaveBeenCalled()
  })

  it('tunes the d3 force engine (charge/link) and reheats the simulation on data load', async () => {
    render(<GraphLibraryView onClose={vi.fn()} />)
    await screen.findByTestId('force-graph-3d')

    await waitFor(() => expect(fgHandle.d3Force).toHaveBeenCalledWith('charge'))
    expect(fgHandle.d3Force).toHaveBeenCalledWith('link')
    expect(fgHandle.charge.strength).toHaveBeenCalled()
    expect(fgHandle.link.distance).toHaveBeenCalled()
    expect(fgHandle.d3ReheatSimulation).toHaveBeenCalled()
  })
})

describe('GraphLibraryView — R32 clickable radial DOIs', () => {
  it('renders the hovered node DOI as a working anchor in the radial info panel', async () => {
    render(<GraphLibraryView onClose={vi.fn()} />)
    // Switch to the radial (SVG) view, which has no lazy three.js dependency.
    await screen.findByTestId('force-graph-3d')
    fireEvent.click(screen.getByRole('button', { name: 'Radial' }))

    // Hover the first node to surface the info panel with its identifier line.
    const circles = await waitFor(() => {
      const c = document.querySelectorAll('svg circle')
      if (!c.length) throw new Error('no nodes yet')
      return c
    })
    fireEvent.mouseEnter(circles[0])

    const link = await screen.findByRole('link', { name: /DOI: 10\.5555\/ABC\.1/i })
    expect(link.tagName).toBe('A')
    expect(link.getAttribute('href')).toBe('https://doi.org/10.5555/ABC.1')
  })

  it('routes the radial DOI link through openExternal inside Tauri', async () => {
    isTauri.mockReturnValue(true)
    render(<GraphLibraryView onClose={vi.fn()} />)
    await screen.findByTestId('force-graph-3d')
    fireEvent.click(screen.getByRole('button', { name: 'Radial' }))

    const circles = await waitFor(() => {
      const c = document.querySelectorAll('svg circle')
      if (!c.length) throw new Error('no nodes yet')
      return c
    })
    fireEvent.mouseEnter(circles[0])

    const link = await screen.findByRole('link', { name: /DOI: 10\.5555\/ABC\.1/i })
    fireEvent.click(link)
    expect(openExternal).toHaveBeenCalledWith('https://doi.org/10.5555/ABC.1')
  })
})
