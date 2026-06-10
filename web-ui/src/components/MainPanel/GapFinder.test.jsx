import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getCheckGaps = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({
  getCheckGaps,
  addReferenceToCheck: vi.fn(),
  getCitationRenumberPreview: vi.fn(),
}))
vi.mock('../../utils/tauriBridge', () => ({ openExternal: vi.fn(), isTauri: () => false }))
vi.mock('../../stores/useHistoryStore', () => ({
  useHistoryStore: { getState: () => ({ selectCheck: vi.fn() }) },
}))

import GapFinder from './GapFinder'

const CHECK_ID = 9
const refsWithDoi = [{ doi: '10.1/x' }]

beforeEach(() => { getCheckGaps.mockReset() })

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
