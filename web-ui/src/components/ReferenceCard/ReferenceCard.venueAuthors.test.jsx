import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// Mock api.js so the lazy venue/author profile fetches are deterministic and
// never touch the network. The default citation format is "plaintext", so the
// structured VenueLine + AuthorsLine rows render on mount.
const getVenueProfile = vi.hoisted(() => vi.fn())
const fetchAuthorProfile = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({
  getVenueProfile,
  fetchAuthorProfile,
  addSeenReference: vi.fn(),
}))
vi.mock('../../utils/tauriBridge', () => ({ openExternal: vi.fn(), isTauri: () => false }))

import ReferenceCard from './ReferenceCard'

const baseRef = {
  status: 'verified',
  title: 'A Verified Paper',
  authors: ['Per Buchwald', 'M. Raghavan'],
  venue: 'Nat. Methods',
  year: 2021,
  enrichment: {
    venue: 'Nature Methods',
    venue_id: 'S123456',
    authors: [
      { name: 'Per Buchwald', orcid: '0000-0002-1825-0097', openalex_id: 'A111' },
    ],
  },
  errors: [],
  warnings: [],
  suggestions: [],
}

describe('ReferenceCard VenueLine + author backfill (mount)', () => {
  it('mounts with venue + author enrichment without crashing', () => {
    render(<ReferenceCard reference={baseRef} index={0} />)
    // Cited venue is the source-of-truth display string.
    expect(screen.getByText('Nat. Methods')).toBeInTheDocument()
    // Backfilled author with an ORCID becomes a profile link.
    const author = screen.getByRole('link', { name: 'Per Buchwald' })
    expect(author).toHaveAttribute('href', 'https://orcid.org/0000-0002-1825-0097')
  })

  it('mounts with no enrichment payload at all (graceful fallback)', () => {
    const bare = { ...baseRef, enrichment: undefined }
    render(<ReferenceCard reference={bare} index={1} />)
    expect(screen.getByText('Nat. Methods')).toBeInTheDocument()
    // Authors still render as plain text (no profile link without enrichment).
    expect(screen.getByText(/Per Buchwald/)).toBeInTheDocument()
  })

  it('opens the venue popover on hover and shows OpenAlex journal metadata', async () => {
    getVenueProfile.mockResolvedValue({
      data: { available: true, display_name: 'Nature Methods', publisher: 'Springer Nature' },
    })
    render(<ReferenceCard reference={baseRef} index={2} />)

    // The popover is lazy (280ms enter delay + async fetch). fireEvent the
    // hover and wait for the tooltip; we assert the real fetched display name.
    fireEvent.mouseEnter(screen.getByText('Nat. Methods'))
    await waitFor(() => expect(getVenueProfile).toHaveBeenCalled(), { timeout: 1000 })
    expect(getVenueProfile).toHaveBeenCalledWith(
      expect.objectContaining({ venue_id: 'S123456', venue_name: 'Nat. Methods' }),
    )
    const tip = await screen.findByRole('tooltip', {}, { timeout: 1000 })
    expect(tip).toHaveTextContent('Springer Nature')
  })
})
