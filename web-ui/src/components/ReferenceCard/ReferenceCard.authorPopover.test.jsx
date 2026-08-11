import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

// The author popover is lazy — mock api.js so the profile fetch is
// deterministic and never touches the network.
const fetchAuthorProfile = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({
  getVenueProfile: vi.fn().mockResolvedValue({ data: { available: false } }),
  fetchAuthorProfile,
  addSeenReference: vi.fn(),
}))
vi.mock('../../utils/tauriBridge', () => ({ openExternal: vi.fn(), isTauri: () => false }))

import ReferenceCard from './ReferenceCard'

const REF = {
  status: 'verified',
  title: 'A Verified Paper',
  authors: ['Per Buchwald'],
  venue: 'Nat. Methods',
  year: 2021,
  enrichment: {
    authors: [
      { name: 'Per Buchwald', orcid: '0000-0002-1825-0097', openalex_id: 'A111' },
    ],
  },
  errors: [],
  warnings: [],
  suggestions: [],
}

beforeEach(() => {
  fetchAuthorProfile.mockReset()
  fetchAuthorProfile.mockResolvedValue({ data: { available: false } })
})
afterEach(() => { vi.useRealTimers() })

const authorEl = () => screen.getByRole('link', { name: 'Per Buchwald' })

/**
 * The author popover must ALWAYS dismiss once the pointer is off both the
 * author name and the popover itself. This regressed repeatedly: the popover
 * could be "pinned" open by a click, and pinning suppressed the mouse-leave
 * close entirely, stranding the card on screen.
 */
describe('ReferenceCard author popover — dismissal', () => {
  it('opens on hover and dismisses when the pointer leaves the author', async () => {
    render(<ReferenceCard reference={REF} index={0} />)

    fireEvent.mouseEnter(authorEl())
    const pop = await screen.findByRole('tooltip', {}, { timeout: 1500 })
    expect(pop).toBeInTheDocument()

    fireEvent.mouseLeave(authorEl())
    await waitFor(
      () => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument(),
      { timeout: 1500 },
    )
  })

  it('dismisses a CLICK-opened (pinned) popover when the pointer leaves it', async () => {
    render(<ReferenceCard reference={REF} index={1} />)

    // A plain left-click on an enriched author pins the popover open.
    fireEvent.click(authorEl())
    const pinned = await screen.findByRole('dialog', {}, { timeout: 1500 })
    expect(pinned).toBeInTheDocument()

    // Moving off the popover must close it — pinning is NOT a reason to keep
    // it on screen once the pointer has moved away.
    fireEvent.mouseLeave(pinned)
    await waitFor(
      () => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
      { timeout: 1500 },
    )
  })

  it('stays open while the pointer moves from the author onto the popover', async () => {
    render(<ReferenceCard reference={REF} index={2} />)

    fireEvent.mouseEnter(authorEl())
    const pop = await screen.findByRole('tooltip', {}, { timeout: 1500 })

    // Leaving the name schedules a close; entering the popover must cancel it
    // so the card remains usable (links, scrolling) under the pointer.
    fireEvent.mouseLeave(authorEl())
    fireEvent.mouseEnter(pop)

    await new Promise((r) => setTimeout(r, 400))
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })

  it('closes when a document-level mousemove lands outside both elements', async () => {
    render(<ReferenceCard reference={REF} index={3} />)

    fireEvent.mouseEnter(authorEl())
    await screen.findByRole('tooltip', {}, { timeout: 1500 })

    // Safety net for a mouseleave that never fires (fast pointer, re-render,
    // anchor scrolled out from under the cursor).
    fireEvent.mouseMove(document.body)
    await waitFor(
      () => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument(),
      { timeout: 1500 },
    )
  })
})
