import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReferenceCard from './ReferenceCard'

vi.mock('../../utils/formatters', async () => {
  const actual = await vi.importActual('../../utils/formatters')
  return {
    ...actual,
    copyToClipboard: vi.fn(),
  }
})

// Control the author-profile fetch (used by the AuthorChip popover) and keep
// isTauri() false so anchor clicks behave like a normal browser.
const mockFetchAuthorProfile = vi.fn(() => Promise.resolve({ data: { available: false } }))
// R10: the ID-less "Find profile" lookup.
const mockFindAuthorProfile = vi.fn(() => Promise.resolve({ data: { available: false } }))
vi.mock('../../utils/api', async () => {
  const actual = await vi.importActual('../../utils/api')
  return {
    ...actual,
    fetchAuthorProfile: (...args) => mockFetchAuthorProfile(...args),
    findAuthorProfile: (...args) => mockFindAuthorProfile(...args),
    getVenueProfile: vi.fn(() => Promise.resolve({ data: { available: false } })),
  }
})
vi.mock('../../utils/tauriBridge', async () => {
  const actual = await vi.importActual('../../utils/tauriBridge')
  return { ...actual, isTauri: () => false, openExternal: vi.fn() }
})

describe('ReferenceCard', () => {
  it('does not show a spinner for final unverified refs after completion', () => {
    const reference = {
      status: 'unverified',
      title: 'Unknown Paper',
      authors: ['A. Author'],
      errors: [{ error_type: 'unverified', error_details: 'Paper not found by any checker' }],
      warnings: [],
      suggestions: [],
    }

    const { container } = render(<ReferenceCard reference={reference} index={0} isCheckComplete />)

    expect(container.querySelector('svg.animate-spin')).toBeNull()
    expect(screen.getByText(/Could not verify: Unknown Paper/)).toBeTruthy()
  })

  it('renders LLM-found matching metadata without crashing', () => {
    const reference = {
      status: 'hallucination',
      title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
      authors: ['Martin Balla', 'M. Long', 'George E. James Goodman'],
      venue: 'IEEE Conference on Games',
      year: 2024,
      hallucination_assessment: {
        verdict: 'LIKELY',
        explanation: 'The paper exists with the cited metadata.',
        link: 'https://arxiv.org/abs/2405.18123',
        found_title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
        found_authors: 'Martin Balla, G. E. Long, George E. James Goodman',
        found_year: '2024',
      },
      authoritative_urls: [],
      errors: [{ error_type: 'author', error_details: 'Author mismatch' }],
      warnings: [],
      suggestions: [],
    }

    render(<ReferenceCard reference={reference} index={3} />)

    expect(screen.getByText('Pytag: Tabletop games for multi-agent reinforcement learning')).toBeTruthy()
    expect(screen.getByText('Matched DB:')).toBeTruthy()
    expect(screen.getByText('LLM search')).toBeTruthy()
    expect(screen.queryByText(/Likely hallucinated/i)).toBeNull()
  })

  it('omits no-date placeholders from reference metadata', () => {
    const reference = {
      status: 'verified',
      title: 'Afl',
      authors: [],
      venue: 'n.d.',
      year: 'n.d.',
      cited_url: 'http://lcamtuf.coredump.cx/afl/',
      errors: [],
      warnings: [],
      suggestions: [],
    }

    render(<ReferenceCard reference={reference} index={0} />)

    expect(screen.getByText('Afl')).toBeTruthy()
    expect(screen.queryByText('n.d.')).toBeNull()
  })

  it('highlights author-year citation markers inside context excerpts', () => {
    const reference = {
      status: 'verified',
      title: 'Model multiplicity: Opportunities, concerns, and solutions',
      authors: ['E. Black', 'M. Raghavan', 'S. Barocas'],
      year: 2022,
      citation_count: 1,
      citation_contexts: [{
        marker: '(Black et al., 2022)',
        sentence: 'The model can be arbitrary or random when addressing marginalized groups (Black et al., 2022).',
      }],
      errors: [],
      warnings: [],
      suggestions: [],
    }

    const { container } = render(<ReferenceCard reference={reference} index={10} />)
    fireEvent.click(screen.getByRole('button', { name: /Context/ }))

    const marker = screen.getAllByText('(Black et al., 2022)')[1]
    expect(marker).toBeInTheDocument()
    expect(marker.style.fontWeight).toBe('700')
    expect(container.textContent).toContain('groups (Black et al., 2022).')
  })
})

describe('ReferenceCard — R04 hallucination-pending safety net', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('reverts a ref stuck pending past the wall-clock cap to its base status with a timeout note', () => {
    vi.useFakeTimers()
    const reference = {
      status: 'verified',
      title: 'A Reference Stuck Mid-Hallucination-Check',
      authors: ['A. Author'],
      year: 2024,
      hallucination_check_pending: true,
      errors: [],
      warnings: [],
      suggestions: [],
    }

    render(<ReferenceCard reference={reference} index={0} />)

    // Initially: the pending spinner text is shown, no timeout note yet.
    expect(screen.getByText(/Checking for hallucination with LLM/i)).toBeTruthy()
    expect(screen.queryByText(/Hallucination check timed out/i)).toBeNull()

    // Advance past the ~180s FE budget — the safety net fires.
    act(() => {
      vi.advanceTimersByTime(181000)
    })

    // The eternal "checking" indicator is gone, replaced by a timeout note;
    // the card no longer wedges on the spinner.
    expect(screen.queryByText(/Checking for hallucination with LLM/i)).toBeNull()
    expect(screen.getByText(/Hallucination check timed out/i)).toBeTruthy()
  })

  it('does not show a timeout note while still within the budget', () => {
    vi.useFakeTimers()
    const reference = {
      status: 'verified',
      title: 'Still Checking',
      authors: ['B. Author'],
      year: 2024,
      hallucination_check_pending: true,
      errors: [],
      warnings: [],
      suggestions: [],
    }

    render(<ReferenceCard reference={reference} index={1} />)

    act(() => {
      vi.advanceTimersByTime(60000) // 60s — well under the cap
    })

    expect(screen.getByText(/Checking for hallucination with LLM/i)).toBeTruthy()
    expect(screen.queryByText(/Hallucination check timed out/i)).toBeNull()
  })
})

// D1 author-UI cluster: R09 (et-al expand), R41 (no fake sentinel chip),
// R11 (pin/scroll), R36/R53 (ORCID link + number), R37 (badge co-locate).
describe('ReferenceCard — author UI cluster (D1)', () => {
  afterEach(() => {
    mockFetchAuthorProfile.mockReset()
    mockFetchAuthorProfile.mockResolvedValue({ data: { available: false } })
    mockFindAuthorProfile.mockReset()
    mockFindAuthorProfile.mockResolvedValue({ data: { available: false } })
  })

  it('R41: never renders a standalone "et al." sentinel as an author chip', () => {
    const reference = {
      status: 'verified',
      title: 'Truncated authors paper',
      authors: ['Jane Smith', 'John Doe', 'et al.'],
      year: 2021,
      errors: [], warnings: [], suggestions: [],
    }
    const { container } = render(<ReferenceCard reference={reference} index={0} />)
    // The author line text shows the real names but NOT the bare sentinel.
    expect(screen.getByText(/Jane Smith/)).toBeTruthy()
    // No element renders the literal "et al." as a name (only the expand
    // control, which is absent here because no enriched list was provided).
    expect(within(container).queryByText('et al.')).toBeNull()
  })

  it('never substitutes the matched record\'s author for the cited one (mismatch case)', () => {
    // Mirrors a real report: the card header read "Fan Yang" (the matched
    // record) while its own error said `cited: F. Li` — the card contradicted
    // itself. The displayed reference must always be the extracted one.
    const reference = {
      status: 'error',
      title: 'The cost of thinking',
      authors: ['F. Li', 'et al.'],
      year: 2025,
      enrichment: { authors: [{ name: 'Fan Yang' }] },
      errors: [{ error_type: 'author', error_details: 'Author 1 mismatch' }],
      warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)

    expect(screen.getByText(/F\. Li/)).toBeTruthy()
    // The corrected name must NOT appear in the reference display itself.
    expect(screen.queryByText(/^Fan Yang$/)).toBeNull()
    // The citation's own truncation marker stays visible.
    expect(screen.getByText(/et al\./)).toBeTruthy()
  })

  it('R09: an "et al." cited list still shows what was CITED, with an opt-in toggle to the resolved list', () => {    const reference = {
      status: 'verified',
      title: 'Et-al expandable paper',
      authors: ['Jane Smith', 'et al.'],
      year: 2021,
      enrichment: {
        authors: [
          { name: 'Jane Smith' },
          { name: 'John Doe' },
          { name: 'Alice Wong' },
        ],
      },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)

    // The card shows the reference AS EXTRACTED — it must never silently
    // substitute the matched record's author list for what the paper cited.
    expect(screen.queryByText(/Alice Wong/)).toBeNull()
    expect(screen.queryByText(/John Doe/)).toBeNull()

    // The fuller resolved list is offered explicitly instead.
    const toggle = screen.getByRole('button', { name: /show all 3 authors/i })
    fireEvent.click(toggle)
    expect(screen.getByText(/Alice Wong/)).toBeTruthy()
    expect(screen.getByText(/John Doe/)).toBeTruthy()
    // ...and is clearly labelled as coming from the matched record.
    expect(screen.getByText(/from matched record/i)).toBeTruthy()

    // The user can always get back to the cited text.
    fireEvent.click(screen.getByRole('button', { name: /show as cited/i }))
    expect(screen.queryByText(/Alice Wong/)).toBeNull()
  })

  it('AuthorsLine: a very long author list gets a show-more/show-less toggle', () => {
    const authors = Array.from({ length: 25 }, (_, i) => `Author${i} Surname${i}`)
    const reference = {
      status: 'verified',
      title: 'Many-author paper',
      authors,
      year: 2021,
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)

    // Collapsed: line-clamped, but the toggle offers to reveal the rest.
    const expand = screen.getByRole('button', { name: /show more/i })
    expect(screen.queryByText(/Author24 Surname24/)).toBeTruthy() // still in DOM (CSS-clamped, not removed)
    fireEvent.click(expand)
    expect(screen.getByRole('button', { name: /show less/i })).toBeTruthy()
  })

  it('R11: clicking the name pins the popover; ×, Escape, and outside-click close it; shows >3 papers', async () => {
    vi.useRealTimers()
    mockFetchAuthorProfile.mockResolvedValue({
      data: {
        available: true,
        hIndex: 12,
        citationCount: 340,
        papers: [
          { title: 'Paper One', year: 2024 },
          { title: 'Paper Two', year: 2023 },
          { title: 'Paper Three', year: 2022 },
          { title: 'Paper Four', year: 2021 },
          { title: 'Paper Five', year: 2020 },
        ],
      },
    })
    const reference = {
      status: 'verified',
      title: 'Pinnable author paper',
      authors: ['Jane Smith'],
      year: 2021,
      enrichment: { authors: [{ name: 'Jane Smith', s2_author_id: '99', orcid: '0000-0002-1825-0097' }] },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)

    // Click the name → pins open (a dialog role appears, off-hover).
    fireEvent.click(screen.getByText('Jane Smith'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toBeTruthy()

    // Pinned panel shows the FULL recent-papers list (>3), not the 3-cap.
    await waitFor(() => expect(within(dialog).getByText('Paper Four')).toBeTruthy())
    expect(within(dialog).getByText('Paper Five')).toBeTruthy()

    // Escape closes it.
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())

    // Re-pin, then close via the × control.
    fireEvent.click(screen.getByText('Jane Smith'))
    const dialog2 = await screen.findByRole('dialog')
    fireEvent.click(within(dialog2).getByRole('button', { name: /close author card/i }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())

    // Re-pin, then close via outside-click (mousedown on the body).
    fireEvent.click(screen.getByText('Jane Smith'))
    await screen.findByRole('dialog')
    fireEvent.mouseDown(document.body)
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('resolves an ID-less author automatically on open — no click required', async () => {
    vi.useRealTimers()
    mockFindAuthorProfile.mockResolvedValue({ data: { available: false, reason: 'no confident match' } })
    const reference = {
      status: 'verified',
      title: 'Mixed author paper',
      year: 2018,
      authors: ['Jane Researcher', 'Mark Withid'],
      enrichment: {
        authors: [
          // ID-less: no s2_author_id / openalex_id -> resolved by name + title.
          { name: 'Jane Researcher' },
          // Has an OpenAlex id -> loads a real by-id profile instead.
          { name: 'Mark Withid', openalex_id: 'A999' },
        ],
      },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)

    // Opening the ID-less author's popover runs the lookup by itself.
    fireEvent.mouseEnter(screen.getByText('Jane Researcher'))
    await waitFor(() => expect(mockFindAuthorProfile).toHaveBeenCalled())
    // The old manual affordance is gone — nothing is left to click.
    expect(screen.queryByRole('button', { name: /find profile/i })).toBeNull()

    // The with-id author loads a by-id profile.
    fireEvent.mouseEnter(screen.getByText('Mark Withid'))
    await waitFor(() => expect(mockFetchAuthorProfile).toHaveBeenCalled())
  })

  it('does not look up an author by name when there is no paper title to corroborate against', async () => {
    vi.useRealTimers()
    mockFindAuthorProfile.mockClear()
    const reference = {
      status: 'verified',
      // No title -> the backend has nothing to corroborate the name against.
      year: 2018,
      authors: ['Jane Researcher'],
      enrichment: { authors: [{ name: 'Jane Researcher' }] },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    fireEvent.mouseEnter(screen.getByText('Jane Researcher'))
    const tooltip = await screen.findByRole('tooltip')
    await waitFor(() => expect(within(tooltip).getByText(/no paper title to search by/i)).toBeTruthy())
    // Guessing from a bare name is worse than showing nothing.
    expect(mockFindAuthorProfile).not.toHaveBeenCalled()
  })

  it('R10: a confident hit populates the popover with real metrics; the find lookup carries the paper title', async () => {
    vi.useRealTimers()
    mockFindAuthorProfile.mockResolvedValue({
      data: {
        available: true,
        name: 'Jane Q. Researcher',
        openalex_id: 'A111',
        hIndex: 21,
        citationCount: 1500,
        paperCount: 42,
        papers: [],
        source: 'openalex',
      },
    })
    const reference = {
      status: 'verified',
      title: 'A Comparison of Treatment Effects',
      year: 2018,
      authors: ['Jane Researcher'],
      enrichment: { authors: [{ name: 'Jane Researcher' }] },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    fireEvent.mouseEnter(screen.getByText('Jane Researcher'))
    const tooltip = await screen.findByRole('tooltip')

    // The corroboration-gated lookup is called with name + the paper title/year.
    await waitFor(() => expect(mockFindAuthorProfile).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Jane Researcher', title: 'A Comparison of Treatment Effects', year: 2018 })
    ))
    // Confident hit -> real metrics render in the popover.
    await waitFor(() => expect(within(tooltip).getByText('1,500')).toBeTruthy())
    expect(within(tooltip).getByText('42')).toBeTruthy()
  })

  it('R10: a miss shows a quiet "no confident match" and fabricates nothing', async () => {
    vi.useRealTimers()
    mockFindAuthorProfile.mockResolvedValue({ data: { available: false, reason: 'no confident match' } })
    const reference = {
      status: 'verified',
      title: 'An Ambiguous Paper',
      year: 2018,
      authors: ['Jane Researcher'],
      enrichment: { authors: [{ name: 'Jane Researcher' }] },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    fireEvent.mouseEnter(screen.getByText('Jane Researcher'))
    const tooltip = await screen.findByRole('tooltip')

    await waitFor(() => expect(within(tooltip).getByText(/no confident match/i)).toBeTruthy())
    // No invented metrics inside the popover (no fabrication on a miss).
    expect(within(tooltip).queryByText(/citations/i)).toBeNull()
    expect(within(tooltip).queryByText(/h-index/i)).toBeNull()
  })

  it('resolves an ORCID for an S2-only author, whose by-id profile can never carry one', async () => {
    vi.useRealTimers()
    mockFindAuthorProfile.mockClear()
    // Semantic Scholar publishes no ORCID, so the by-id profile comes back without one.
    mockFetchAuthorProfile.mockResolvedValue({
      data: { available: true, hIndex: 12, papers: [], source: 'semantic_scholar' },
    })
    mockFindAuthorProfile.mockResolvedValue({
      data: { available: true, name: 'Jane Smith', openalex_id: 'A321', orcid: '0000-0003-1111-2222' },
    })
    const reference = {
      status: 'verified',
      title: 'An S2-only author paper',
      authors: ['Jane Smith'],
      year: 2021,
      enrichment: { authors: [{ name: 'Jane Smith', s2_author_id: '4242' }] },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    fireEvent.click(screen.getByText('Jane Smith'))
    const dialog = await screen.findByRole('dialog')

    await waitFor(() => expect(within(dialog).getByText('0000-0003-1111-2222')).toBeTruthy())
    const orcidLink = within(dialog).getAllByRole('link')
      .find(a => a.getAttribute('href') === 'https://orcid.org/0000-0003-1111-2222')
    expect(orcidLink).toBeTruthy()
    // The card still shows the (richer) S2 metrics — the lookup only filled the gap.
    expect(within(dialog).getAllByText('12').length).toBeGreaterThan(0)
    // A "no confident match" notice belongs only to authors with no profile at all.
    expect(within(dialog).queryByText(/no confident match/i)).toBeNull()
  })

  it('does not spend a name lookup when the ORCID is already known', async () => {
    vi.useRealTimers()
    mockFindAuthorProfile.mockClear()
    mockFetchAuthorProfile.mockResolvedValue({ data: { available: true, papers: [] } })
    const reference = {
      status: 'verified',
      title: 'Known ORCID paper',
      authors: ['Jane Smith'],
      year: 2021,
      enrichment: { authors: [{ name: 'Jane Smith', s2_author_id: '4243', orcid: '0000-0001-2345-6789' }] },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    fireEvent.click(screen.getByText('Jane Smith'))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getByText('0000-0001-2345-6789')).toBeTruthy())
    expect(mockFindAuthorProfile).not.toHaveBeenCalled()
  })

  it('R36/R53: renders the ORCID page link AND the visible ORCID number, gated to real values', async () => {
    vi.useRealTimers()
    mockFetchAuthorProfile.mockResolvedValue({
      data: { available: true, orcid: '0000-0001-2345-6789', papers: [] },
    })
    const reference = {
      status: 'verified',
      title: 'ORCID author paper',
      authors: ['Jane Smith'],
      year: 2021,
      // No ORCID on the enrichment record — it must come from the fetched profile (R36).
      enrichment: { authors: [{ name: 'Jane Smith', s2_author_id: '42' }] },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    fireEvent.click(screen.getByText('Jane Smith'))
    const dialog = await screen.findByRole('dialog')

    // The visible ORCID NUMBER renders (R53)...
    await waitFor(() => expect(within(dialog).getByText('0000-0001-2345-6789')).toBeTruthy())
    // ...alongside a clickable orcid.org page LINK to it (R53/R36).
    const orcidLink = within(dialog).getAllByRole('link').find(a => a.getAttribute('href') === 'https://orcid.org/0000-0001-2345-6789')
    expect(orcidLink).toBeTruthy()
  })

  it('R36/R53: shows no ORCID when none resolved (no fabrication)', async () => {
    vi.useRealTimers()
    mockFetchAuthorProfile.mockResolvedValue({ data: { available: true, papers: [] } })
    const reference = {
      status: 'verified',
      title: 'No ORCID paper',
      authors: ['Jane Smith'],
      year: 2021,
      enrichment: { authors: [{ name: 'Jane Smith', s2_author_id: '7' }] },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    fireEvent.click(screen.getByText('Jane Smith'))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(mockFetchAuthorProfile).toHaveBeenCalled())
    // No orcid.org link anywhere in the pinned panel.
    const orcidLink = within(dialog).queryAllByRole('link').find(a => (a.getAttribute('href') || '').includes('orcid.org'))
    expect(orcidLink).toBeUndefined()
  })

  it('shows the i10-index alongside the h-index when the profile carries it', async () => {
    vi.useRealTimers()
    mockFetchAuthorProfile.mockResolvedValue({
      data: {
        available: true,
        hIndex: 137,
        i10Index: 300,
        metricsSource: 'semantic_scholar',
        i10Source: 'openalex',
        papers: [],
      },
    })
    const reference = {
      status: 'verified',
      title: 'Indexed author paper',
      authors: ['Ada Index'],
      year: 2021,
      enrichment: { authors: [{ name: 'Ada Index', s2_author_id: '55', openalex_id: 'A55' }] },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    fireEvent.click(screen.getByText('Ada Index'))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getAllByText('300').length).toBeGreaterThan(0))
    expect(within(dialog).getAllByText('137').length).toBeGreaterThan(0)
    // Both surfaces render it: the inline header line AND the metric chip row.
    expect(within(dialog).getAllByTitle(/i10-index \(OpenAlex\)/i).length).toBe(2)
    expect(within(dialog).getByText('i10-index')).toBeTruthy() // the chip's label
    // Each index names the corpus it came from, since the two providers differ.
    expect(within(dialog).getAllByTitle(/h-index \(Semantic Scholar\)/i).length).toBe(2)
  })

  it('omits the i10-index when the profile has none (no fabrication)', async () => {
    vi.useRealTimers()
    mockFetchAuthorProfile.mockResolvedValue({
      data: { available: true, hIndex: 9, papers: [] },
    })
    const reference = {
      status: 'verified',
      title: 'No i10 paper',
      authors: ['Bob Noindex'],
      year: 2021,
      enrichment: { authors: [{ name: 'Bob Noindex', s2_author_id: '56' }] },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    fireEvent.click(screen.getByText('Bob Noindex'))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getAllByText('9').length).toBeGreaterThan(0))
    expect(within(dialog).queryAllByText(/i10/i).length).toBe(0)
  })

  it('sends BOTH author ids so the OpenAlex-only i10-index is reachable for S2 authors', async () => {
    vi.useRealTimers()
    mockFetchAuthorProfile.mockClear()
    mockFetchAuthorProfile.mockResolvedValue({ data: { available: true, papers: [] } })
    const reference = {
      status: 'verified',
      title: 'Dual id paper',
      authors: ['Cara Dual'],
      year: 2021,
      enrichment: { authors: [{ name: 'Cara Dual', s2_author_id: '77', openalex_id: 'A77' }] },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    fireEvent.mouseEnter(screen.getByText('Cara Dual'))
    await waitFor(() => expect(mockFetchAuthorProfile).toHaveBeenCalled())
    expect(mockFetchAuthorProfile).toHaveBeenCalledWith({ author_id: '77', openalex_id: 'A77' })
  })

  it('R37: relabels the inline badge and appends a literature-citation pill when cited_by_count exists', () => {
    const reference = {
      status: 'verified',
      title: 'Inline cited paper',
      authors: ['Jane Smith'],
      year: 2021,
      is_inline_cited: true,
      citation_count: 4,
      enrichment: { cited_by_count: 1234 },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    expect(screen.getByText(/Used 4× in this paper/)).toBeTruthy()
    expect(screen.getByText(/1,234 citations/)).toBeTruthy()
  })

  it('R37: omits the literature-citation pill when cited_by_count is absent', () => {
    const reference = {
      status: 'verified',
      title: 'Inline cited paper without enrichment count',
      authors: ['Jane Smith'],
      year: 2021,
      is_inline_cited: true,
      citation_count: 2,
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)
    expect(screen.getByText(/Used 2× in this paper/)).toBeTruthy()
    expect(screen.queryByText(/citations/)).toBeNull()
  })

  it('renders a warning that only carries warning_type/warning_details (not "Unknown mismatch")', () => {
    const reference = {
      status: 'verified',
      title: 'Paper with a recheck-style warning',
      authors: ['Jane Smith'],
      year: 2021,
      errors: [],
      // Recheck/core variant field names — the render must read these too.
      warnings: [{ warning_type: 'venue', warning_details: 'Venue abbreviation differs from canonical form' }],
      suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} isCheckComplete />)
    expect(screen.getByText(/Venue abbreviation differs from canonical form/)).toBeTruthy()
    expect(screen.queryByText(/Unknown mismatch/)).toBeNull()
  })

  it('labels a typed-but-detail-less warning by its field, never "Unknown mismatch"', () => {
    const reference = {
      status: 'verified',
      title: 'Paper with a bare typed warning',
      authors: ['Jane Smith'],
      year: 2021,
      errors: [],
      warnings: [{ warning_type: 'year' }],
      suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} isCheckComplete />)
    expect(screen.getByText(/Year mismatch/)).toBeTruthy()
    expect(screen.queryByText(/Unknown mismatch/)).toBeNull()
  })
})
