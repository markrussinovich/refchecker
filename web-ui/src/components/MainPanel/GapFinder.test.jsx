import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getCheckGaps = vi.hoisted(() => vi.fn())
const addReferenceToCheck = vi.hoisted(() => vi.fn())
const getCitationRenumberPreview = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({
  getCheckGaps,
  addReferenceToCheck,
  getCitationRenumberPreview,
}))
vi.mock('../../utils/tauriBridge', () => ({ openExternal: vi.fn(), isTauri: () => false }))
vi.mock('../../stores/useHistoryStore', () => ({
  useHistoryStore: { getState: () => ({ selectCheck: vi.fn() }) },
}))

import GapFinder from './GapFinder'

const CHECK_ID = 9
const refsWithDoi = [{ doi: '10.1/x' }]

beforeEach(() => {
  getCheckGaps.mockReset()
  addReferenceToCheck.mockReset()
  getCitationRenumberPreview.mockReset()
})

describe('GapFinder — R33 styling + R52 fixed-header collapse', () => {
  it('the pre-run trigger is a shared outline pill with the sizer reserving the analyzing label', () => {
    render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    const pill = screen.getByRole('button')
    expect(pill.style.height).toBe('var(--control-h)')
    expect(pill.style.borderRadius).toBe('var(--control-radius)')
    expect(pill.className).toContain('rc-control')
    const sizers = Array.from(document.querySelectorAll('span[aria-hidden="true"]')).map((s) => s.textContent)
    expect(sizers).toContain('Analyzing co-citations…') // longest, reserved
  })

  it('the result header is a fixed-28px row with a rotating chevron and constant title (no ▸show/▾hide text)', async () => {
    getCheckGaps.mockResolvedValue({ data: { suggestions: [{ openalex_id: 'W1', title: 'A co-cited work', co_citations: 4 }] } })
    render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText(/work your references cite that you might add/i)

    // The legacy "▸ show" / "▾ hide" text affordance is gone (replaced by a chevron).
    expect(screen.queryByText(/▸ show/)).toBeNull()
    expect(screen.queryByText(/▾ hide/)).toBeNull()

    // The header row reserves a fixed control height so it never grows on toggle.
    const headerRow = screen.getByText(/work your references cite/i).closest('div[style*="height"]')
    expect(headerRow.style.height).toBe('var(--control-h)')

    // The chevron is a rotating IconButton; expanded ⇒ rotated, no text reflow.
    const chevron = headerRow.querySelector('.rc-iconbtn-chevron')
    expect(chevron).toBeTruthy()
    expect(chevron.className).toContain('rc-rotated') // expanded by default
  })

  it('toggling collapse animates a grid-row body while the header stays put (no header shift)', async () => {
    getCheckGaps.mockResolvedValue({ data: { suggestions: [{ openalex_id: 'W1', title: 'A co-cited work', co_citations: 4 }] } })
    render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText(/work your references cite/i)

    const collapse = document.querySelector('.rc-collapse')
    expect(collapse).toBeTruthy()
    expect(collapse.className).not.toContain('rc-collapsed') // expanded
    // Collapse via the chevron — body class flips, header DOM is untouched.
    const chevron = document.querySelector('.rc-iconbtn-chevron')
    fireEvent.click(chevron)
    await waitFor(() => expect(document.querySelector('.rc-collapse').className).toContain('rc-collapsed'))
    // The constant title text is still present (it never changes between states).
    expect(screen.getByText(/work your references cite/i)).toBeInTheDocument()
  })
})

describe('GapFinder — R39 friendly 404', () => {
  it('shows the "update the app" message on an HTTP 404 instead of raw HTML', async () => {
    // Simulate an older desktop build whose /gaps route 404s (SPA catch-all).
    const err = new Error('Request failed with status code 404')
    err.response = { status: 404, data: '<!doctype html><html>…SPA index…</html>' }
    getCheckGaps.mockRejectedValue(err)
    render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))

    await screen.findByText('Gap finder is unavailable — please update the app')
    // The raw proxy HTML must never reach the user.
    expect(screen.queryByText(/SPA index/)).toBeNull()
  })

  it('still surfaces a detail message for non-404 errors', async () => {
    const err = new Error('boom')
    err.response = { status: 500, data: { detail: 'Gap analysis failed: upstream 503' } }
    getCheckGaps.mockRejectedValue(err)
    render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))

    await screen.findByText('Gap analysis failed: upstream 503')
    // Not masked by the 404 message.
    expect(screen.queryByText(/please update the app/)).toBeNull()
  })
})

describe('GapFinder — R17 dedup/validity guard', () => {
  it('grays out a suggestion whose DOI is already in the bibliography (DOI-only match), with no Add control', async () => {
    // A suggestion that resolves to the SAME DOI already in `references`,
    // but written with a resolver prefix + different casing — must still match.
    getCheckGaps.mockResolvedValue({
      data: { suggestions: [{ openalex_id: 'W1', title: 'Already Cited Work', co_citations: 3, doi: 'https://doi.org/10.5555/ABC.1' }] },
    })
    const references = [{ doi: '10.5555/abc.1' }]
    render(<GapFinder checkId={CHECK_ID} references={references} />)
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText('Already Cited Work')

    // The "already in list" label shows and no Add affordance is offered.
    expect(screen.getByText(/already in list/i)).toBeInTheDocument()
    expect(screen.queryByText('+ Add to references')).toBeNull()
  })

  it('hides the Add control for a suggestion with no title and no resolvable DOI (validity guard)', async () => {
    getCheckGaps.mockResolvedValue({
      data: { suggestions: [{ openalex_id: 'W2', title: '', co_citations: 4, doi: 'not-a-doi' }] },
    })
    render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText(/can.t add/i)
    expect(screen.queryByText('+ Add to references')).toBeNull()
  })

  it('surfaces "already in list" with the existing index when the backend rejects with 409', async () => {
    // The suggestion is NOT a client-side match (its DOI isn't in references),
    // so the Add flow runs and the backend wins the race with a 409.
    getCheckGaps.mockResolvedValue({
      data: { suggestions: [{ openalex_id: 'W3', title: 'Server-Detected Dup', co_citations: 5, doi: '10.9999/server.dup' }] },
    })
    getCitationRenumberPreview.mockResolvedValue({ data: { shifted_markers: [], abstained: true, scheme: 'author-year' } })
    const err = new Error('Request failed with status code 409')
    err.response = { status: 409, data: { duplicate: true, existing_index: 7, message: 'Already reference [7] in this check.' } }
    addReferenceToCheck.mockRejectedValue(err)

    render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText('Server-Detected Dup')

    // Open the preview, then confirm the add — which 409s. The Confirm-add
    // label is wrapped by LabelSizer (multiple spans), so target the button.
    fireEvent.click(screen.getByText('+ Add to references'))
    const confirm = await screen.findByRole('button', { name: /confirm add/i })
    fireEvent.click(confirm)

    await screen.findByText(/already in list \(reference \[7\]\)/i)
    expect(screen.queryByText('add failed')).toBeNull()
  })
})
