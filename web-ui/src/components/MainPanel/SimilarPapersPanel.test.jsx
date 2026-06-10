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

describe('SimilarPapersPanel mode toggle', () => {
  it('exposes the three discovery modes References / Citations / Both', () => {
    render(<SimilarPapersPanel references={REFS} paperTitle="P" paperSource="" />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['References', 'Citations', 'Both'])
  })

  it('defaults to "Both" and sends mode="both" when searched', async () => {
    findSimilarPapers.mockResolvedValue({ data: { candidates: [], source_counts: {} } })
    // Unique title per test: the panel keeps a module-level result cache
    // keyed by `${mode}::${title}`, so a shared title would let one test's
    // cached (empty) result swap the search button for "Refresh".
    render(<SimilarPapersPanel references={REFS} paperTitle="Both Paper" paperSource="" />)

    // "Both" is the default selected tab; its search affordance is shown.
    fireEvent.click(screen.getByRole('button', { name: 'Find shared references + citations' }))

    await waitFor(() => expect(findSimilarPapers).toHaveBeenCalled())
    expect(findSimilarPapers).toHaveBeenCalledWith(
      expect.objectContaining({ mode: 'both', paper_title: 'Both Paper' }),
    )
  })

  it('sends mode="references" when the References tab is searched', async () => {
    findSimilarPapers.mockResolvedValue({ data: { candidates: [], source_counts: {} } })
    render(<SimilarPapersPanel references={REFS} paperTitle="Refs Paper" paperSource="" />)

    fireEvent.click(screen.getByRole('tab', { name: 'References' }))
    fireEvent.click(screen.getByRole('button', { name: 'Find shared references' }))

    await waitFor(() => expect(findSimilarPapers).toHaveBeenCalled())
    expect(findSimilarPapers).toHaveBeenCalledWith(
      expect.objectContaining({ mode: 'references' }),
    )
  })

  it('sends mode="citations" when the Citations tab is searched', async () => {
    findSimilarPapers.mockResolvedValue({ data: { candidates: [], source_counts: {} } })
    render(<SimilarPapersPanel references={REFS} paperTitle="Cites Paper" paperSource="" />)

    fireEvent.click(screen.getByRole('tab', { name: 'Citations' }))
    fireEvent.click(screen.getByRole('button', { name: 'Find shared citations' }))

    await waitFor(() => expect(findSimilarPapers).toHaveBeenCalled())
    expect(findSimilarPapers).toHaveBeenCalledWith(
      expect.objectContaining({ mode: 'citations' }),
    )
  })
})

describe('SimilarPapersPanel mode-aware cache key', () => {
  it('re-queries the backend when switching modes instead of serving the other mode from cache', async () => {
    findSimilarPapers.mockResolvedValue({ data: { candidates: [], source_counts: {} } })
    // Shared title across both modes — the cache key is `${mode}::${title}`,
    // so each mode must keep its own entry and NOT reuse the other's result.
    render(<SimilarPapersPanel references={REFS} paperTitle="Cache Key Paper" paperSource="" />)

    // Search in the default "Both" mode -> caches under "both::…".
    fireEvent.click(screen.getByRole('button', { name: 'Find shared references + citations' }))
    await waitFor(() => expect(findSimilarPapers).toHaveBeenCalledTimes(1))
    expect(findSimilarPapers).toHaveBeenLastCalledWith(
      expect.objectContaining({ mode: 'both' }),
    )

    // Flip to "References". A mode-aware cache key means there is no cached
    // entry for this mode yet, so the search button is shown (not "Refresh").
    fireEvent.click(screen.getByRole('tab', { name: 'References' }))
    fireEvent.click(screen.getByRole('button', { name: 'Find shared references' }))

    // A second backend call fires for the new mode rather than the Both
    // result being reused from cache.
    await waitFor(() => expect(findSimilarPapers).toHaveBeenCalledTimes(2))
    expect(findSimilarPapers).toHaveBeenLastCalledWith(
      expect.objectContaining({ mode: 'references' }),
    )
  })
})

describe('SimilarPapersPanel per-article isolation (R25)', () => {
  it('does not bleed results across articles with identical empty title/source but different checkId', async () => {
    findSimilarPapers.mockResolvedValue({
      data: {
        candidates: [{ paperId: 'iso1', title: 'Isolated result', authors: ['Z'], year: 2021, doi: '10.7/iso', sources: ['semantic_scholar'] }],
        source_counts: { semantic_scholar: 1 },
      },
    })

    // Two articles in the same batch with NO title and NO source — the only
    // thing distinguishing them is their checkId. Pre-R25 the panel fell
    // through to the `title:` cache key (identical, empty), so searching the
    // first leaked its result onto the second.
    const { unmount: unmountA } = render(
      <SimilarPapersPanel references={REFS} paperTitle="" paperSource="" checkId={101} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Find shared references + citations' }))
    await screen.findByText('Isolated result')
    expect(findSimilarPapers).toHaveBeenCalledTimes(1)
    unmountA()

    // The SECOND article (different checkId) must NOT inherit the first's
    // cached candidates: it still shows its own Find button, not "Refresh"
    // and not the leaked candidate.
    render(
      <SimilarPapersPanel references={REFS} paperTitle="" paperSource="" checkId={202} />,
    )
    expect(screen.getByRole('button', { name: 'Find shared references + citations' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Refresh' })).toBeNull()
    expect(screen.queryByText('Isolated result')).toBeNull()
  })
})

describe('SimilarPapersPanel relation chips', () => {
  it('tags overlap candidates as Shared refs or Shared cites, and shows shared-refs for similar rows', async () => {
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
          // OpenAlex overlap rows carry a relation: 'reference' = shares
          // references, 'citation' = shares citations (co-cited).
          { openalex_id: 'W2', title: 'A reference', relation: 'reference', sources: ['openalex'], year: 2010, shared_with_source: 3 },
          { openalex_id: 'W3', title: 'A citation', relation: 'citation', sources: ['openalex'], year: 2022, shared_with_source: 2 },
        ],
        source_counts: { semantic_scholar: 1, reference: 1, citation: 1 },
      },
    })
    render(<SimilarPapersPanel references={REFS} paperTitle="Relation Paper" paperSource="10.9/src" />)

    // "Both" is the default tab; query by text (not role) for the search
    // trigger: a role scan clones every button and jsdom mishandles the
    // shared-refs button's `background` shorthand during accessible-name
    // computation.
    fireEvent.click(screen.getByText('Find shared references + citations'))

    await screen.findByText('Similar work')
    // Relation chips render for the OpenAlex overlap rows.
    expect(screen.getByText('Shared refs')).toBeInTheDocument()
    expect(screen.getByText('Shared cites')).toBeInTheDocument()
    // The similar-path row keeps its shared-refs overlap chip.
    expect(screen.getByText(/shared refs \(2\)/)).toBeInTheDocument()
  })
})
