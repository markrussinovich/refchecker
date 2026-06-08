import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the API + the Tauri bridge so the panel renders in isolation and we
// can assert exactly what `mode` it sends to /api/papers/similar.
const findSimilarPapers = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({ findSimilarPapers }))
vi.mock('../../utils/tauriBridge', () => ({ openExternal: vi.fn() }))

import SimilarPapersPanel from './SimilarPapersPanel'

const REFS = [
  { doi: '10.1/a', title: 'Ref A', authors: ['X'] },
  { arxiv_id: '2001.00001', title: 'Ref B', authors: ['Y'] },
]

beforeEach(() => {
  findSimilarPapers.mockReset()
})

describe('SimilarPapersPanel mode toggle (#63)', () => {
  it('exposes all three discovery modes including "Both"', () => {
    render(<SimilarPapersPanel references={REFS} paperTitle="P" paperSource="" />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['Similar', 'Cites & Refs', 'Both'])
  })

  it('sends mode="both" to the backend when "Both" is selected and searched', async () => {
    findSimilarPapers.mockResolvedValue({ data: { candidates: [], source_counts: {} } })
    // Unique title per test: the panel keeps a module-level result cache
    // keyed by `${mode}::${title}`, so a shared title would let one test's
    // cached (empty) result swap the search button for "Refresh".
    render(<SimilarPapersPanel references={REFS} paperTitle="Both Paper" paperSource="" />)

    fireEvent.click(screen.getByRole('tab', { name: 'Both' }))
    // Button label switches to the "both" affordance.
    fireEvent.click(screen.getByRole('button', { name: 'Find similar + cites & refs' }))

    await waitFor(() => expect(findSimilarPapers).toHaveBeenCalled())
    expect(findSimilarPapers).toHaveBeenCalledWith(
      expect.objectContaining({ mode: 'both', paper_title: 'Both Paper' }),
    )
  })

  it('sends mode="cites_refs" when that tab is searched', async () => {
    findSimilarPapers.mockResolvedValue({ data: { candidates: [], source_counts: {} } })
    render(<SimilarPapersPanel references={REFS} paperTitle="Cites Paper" paperSource="" />)

    fireEvent.click(screen.getByRole('tab', { name: 'Cites & Refs' }))
    fireEvent.click(screen.getByRole('button', { name: 'Find cites & refs' }))

    await waitFor(() => expect(findSimilarPapers).toHaveBeenCalled())
    expect(findSimilarPapers).toHaveBeenCalledWith(
      expect.objectContaining({ mode: 'cites_refs' }),
    )
  })
})

describe('SimilarPapersPanel mode-aware cache key (#63)', () => {
  it('re-queries the backend when switching modes instead of serving the other mode from cache', async () => {
    findSimilarPapers.mockResolvedValue({ data: { candidates: [], source_counts: {} } })
    // Shared title across both modes — the cache key is `${mode}::${title}`,
    // so each mode must keep its own entry and NOT reuse the other's result.
    render(<SimilarPapersPanel references={REFS} paperTitle="Cache Key Paper" paperSource="" />)

    // Search in the default "Similar" mode -> caches under "similar::…".
    fireEvent.click(screen.getByRole('button', { name: 'Find similar papers' }))
    await waitFor(() => expect(findSimilarPapers).toHaveBeenCalledTimes(1))
    expect(findSimilarPapers).toHaveBeenLastCalledWith(
      expect.objectContaining({ mode: 'similar' }),
    )

    // Flip to "Cites & Refs". A mode-aware cache key means there is no cached
    // entry for this mode yet, so the search button is shown (not "Refresh").
    fireEvent.click(screen.getByRole('tab', { name: 'Cites & Refs' }))
    fireEvent.click(screen.getByRole('button', { name: 'Find cites & refs' }))

    // A second backend call fires for the new mode rather than the Similar
    // result being reused from cache.
    await waitFor(() => expect(findSimilarPapers).toHaveBeenCalledTimes(2))
    expect(findSimilarPapers).toHaveBeenLastCalledWith(
      expect.objectContaining({ mode: 'cites_refs' }),
    )
  })
})

describe('SimilarPapersPanel relation chips (#63)', () => {
  it('tags cites/refs candidates as Reference or Citation, and shows shared-refs for similar rows', async () => {
    findSimilarPapers.mockResolvedValue({
      data: {
        candidates: [
          // Similar-path row: scored for reference overlap, no relation tag.
          {
            paperId: 'p1', title: 'Similar work', year: 2020, authors: ['A'],
            doi: '10.5/sim', sources: ['semantic_scholar'],
            shared_refs_count: 2, shared_refs_pct: 0.5, candidate_ref_count: 4,
            shared_refs_titles: ['Ref A', 'Ref B'],
          },
          // Cites/refs rows carry a relation and no overlap signal.
          { openalex_id: 'W2', title: 'A reference', relation: 'reference', sources: ['openalex'], year: 2010 },
          { openalex_id: 'W3', title: 'A citation', relation: 'citation', sources: ['openalex'], year: 2022 },
        ],
        source_counts: { semantic_scholar: 1, reference: 1, citation: 1 },
      },
    })
    render(<SimilarPapersPanel references={REFS} paperTitle="Relation Paper" paperSource="10.9/src" />)

    fireEvent.click(screen.getByRole('tab', { name: 'Both' }))
    // Query by text (not role) for the search trigger: a role scan clones
    // every button and jsdom mishandles the shared-refs button's `background`
    // shorthand during accessible-name computation.
    fireEvent.click(screen.getByText('Find similar + cites & refs'))

    await screen.findByText('Similar work')
    // Relation chips render for the OpenAlex cites/refs rows.
    expect(screen.getByText('Reference')).toBeInTheDocument()
    expect(screen.getByText('Citation')).toBeInTheDocument()
    // The similar-path row keeps its shared-refs overlap chip.
    expect(screen.getByText(/shared refs \(2\)/)).toBeInTheDocument()
  })
})
