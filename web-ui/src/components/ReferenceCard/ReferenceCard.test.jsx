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

  it('R09: "et al. (show N authors)" toggle swaps in the enriched author list', () => {
    const reference = {
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

    // Collapsed: enriched-only names are not visible yet.
    expect(screen.queryByText(/Alice Wong/)).toBeNull()
    const expand = screen.getByRole('button', { name: /et al\. \(show 3 authors\)/i })
    fireEvent.click(expand)

    // Expanded: the full enriched list now renders.
    expect(screen.getByText(/Alice Wong/)).toBeTruthy()
    expect(screen.getByText(/John Doe/)).toBeTruthy()

    // And it collapses back.
    fireEvent.click(screen.getByRole('button', { name: /show less/i }))
    expect(screen.queryByText(/Alice Wong/)).toBeNull()
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

  it('R10: shows a "Find profile" action for an ID-less author and NOT for an author with an id', async () => {
    vi.useRealTimers()
    const reference = {
      status: 'verified',
      title: 'Mixed author paper',
      year: 2018,
      authors: ['Jane Researcher', 'Mark Withid'],
      enrichment: {
        authors: [
          // ID-less: no s2_author_id / openalex_id -> offers "Find profile".
          { name: 'Jane Researcher' },
          // Has an OpenAlex id -> NO "Find profile" (loads a real profile).
          { name: 'Mark Withid', openalex_id: 'A999' },
        ],
      },
      errors: [], warnings: [], suggestions: [],
    }
    render(<ReferenceCard reference={reference} index={0} />)

    // Open the ID-less author's popover -> "Find profile" appears.
    fireEvent.mouseEnter(screen.getByText('Jane Researcher'))
    await waitFor(() => expect(screen.getByRole('button', { name: /find profile/i })).toBeTruthy())

    // Open the WITH-id author's popover -> no "Find profile" (id loads a profile).
    fireEvent.mouseEnter(screen.getByText('Mark Withid'))
    await waitFor(() => expect(mockFetchAuthorProfile).toHaveBeenCalled())
    // The only "Find profile" button in the DOM is the ID-less author's; the
    // with-id chip never renders one.
    expect(screen.getAllByRole('button', { name: /find profile/i }).length).toBe(1)
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
    fireEvent.click(within(tooltip).getByRole('button', { name: /find profile/i }))

    // The corroboration-gated lookup is called with name + the paper title/year.
    await waitFor(() => expect(mockFindAuthorProfile).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Jane Researcher', title: 'A Comparison of Treatment Effects', year: 2018 })
    ))
    // Confident hit -> real metrics render in the popover; the button is gone.
    await waitFor(() => expect(within(tooltip).getByText('1,500')).toBeTruthy())
    expect(within(tooltip).getByText('42')).toBeTruthy()
    expect(within(tooltip).queryByRole('button', { name: /find profile/i })).toBeNull()
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
    fireEvent.click(within(tooltip).getByRole('button', { name: /find profile/i }))

    await waitFor(() => expect(within(tooltip).getByText(/no confident match/i)).toBeTruthy())
    // No invented metrics inside the popover (no fabrication on a miss).
    expect(within(tooltip).queryByText(/citations/i)).toBeNull()
    expect(within(tooltip).queryByText(/h-index/i)).toBeNull()
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
})
