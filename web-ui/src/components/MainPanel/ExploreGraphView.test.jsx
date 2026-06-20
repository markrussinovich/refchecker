import { describe, expect, it } from 'vitest'
import { buildGraph, yearColor } from './ExploreGraphView'

describe('yearColor', () => {
  it('returns neutral grey when year/range is missing (no fabricated colour)', () => {
    expect(yearColor(null, 2000, 2020)).toBe('#94a3b8')
    expect(yearColor(2010, null, null)).toBe('#94a3b8')
    expect(yearColor(2010, 2010, 2010)).toBe('#94a3b8') // zero-width range
  })

  it('maps the oldest year to blue and the newest to amber', () => {
    expect(yearColor(2000, 2000, 2020)).toBe('rgb(59,130,246)')
    expect(yearColor(2020, 2000, 2020)).toBe('rgb(245,158,11)')
  })
})

describe('buildGraph', () => {
  const candidates = [
    { paperId: 'p1', title: 'Old work', year: 2000, authors: ['A', 'B'], doi: '10.1/x', relation: 'reference', shared_refs_count: 3 },
    { openalex_id: 'W2', title: 'New work', year: 2020, arxiv_id: '2001.00001', relation: 'citation' },
  ]

  it('adds a pinned source node plus one node per real candidate', () => {
    const g = buildGraph(candidates, 'My paper', 800)
    expect(g.nodes).toHaveLength(3) // source + 2 candidates
    const source = g.nodes.find((n) => n.isSource)
    expect(source).toBeTruthy()
    expect(source.fx).toBe(0)
    expect(source.fy).toBe(0)
    expect(g.links).toHaveLength(2)
    expect(g.links.every((l) => l.source === '__source__')).toBe(true)
    expect(g.meta).toMatchObject({ minYear: 2000, maxYear: 2020, count: 2 })
  })

  it('pins the older candidate left of the newer one (year → x)', () => {
    const g = buildGraph(candidates, 'My paper', 800)
    const old = g.nodes.find((n) => n.id === 'p1')
    const recent = g.nodes.find((n) => n.id === 'W2')
    expect(old.fx).toBeLessThan(recent.fx)
  })

  it('drops candidates with no usable identity (real data only)', () => {
    const g = buildGraph([{ year: 2010 }, ...candidates], 'My paper', 800)
    // The identity-less candidate is omitted; only the 2 real ones remain.
    expect(g.meta.count).toBe(2)
    expect(g.nodes).toHaveLength(3)
  })

  it('returns just the source node when there are no candidates (abstain)', () => {
    const g = buildGraph([], 'My paper', 800)
    expect(g.nodes).toHaveLength(1)
    expect(g.nodes[0].isSource).toBe(true)
    expect(g.links).toHaveLength(0)
    expect(g.meta.count).toBe(0)
  })
})
