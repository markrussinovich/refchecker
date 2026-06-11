import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getCheckGaps = vi.hoisted(() => vi.fn())
const addReferenceToCheck = vi.hoisted(() => vi.fn())
const getCitationRenumberPreview = vi.hoisted(() => vi.fn())
const getCorrectedReferenceList = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({
  getCheckGaps,
  addReferenceToCheck,
  getCitationRenumberPreview,
  getCorrectedReferenceList,
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
  getCorrectedReferenceList.mockReset()
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

describe('GapFinder — R49 persistent collapse toggle', () => {
  // setup.js stubs window.localStorage with bare vi.fn()s; back them with a
  // real Map for this suite so we can assert the persisted value round-trips.
  let store
  beforeEach(() => {
    store = new Map()
    vi.spyOn(window.localStorage, 'getItem').mockImplementation((k) => (store.has(k) ? store.get(k) : null))
    vi.spyOn(window.localStorage, 'setItem').mockImplementation((k, v) => { store.set(k, String(v)) })
  })

  it('persists the collapse choice to localStorage and restores it on remount', async () => {
    getCheckGaps.mockResolvedValue({
      data: { suggestions: [{ openalex_id: 'W1', title: 'A co-cited work', co_citations: 4 }] },
    })
    const { unmount } = render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText(/work your references cite/i)

    // Starts expanded; collapsing via the chevron persists '1' under the
    // per-check key so the choice survives a remount (article re-open / reload).
    expect(document.querySelector('.rc-collapse').className).not.toContain('rc-collapsed')
    fireEvent.click(document.querySelector('.rc-iconbtn-chevron'))
    await waitFor(() => expect(document.querySelector('.rc-collapse').className).toContain('rc-collapsed'))
    expect(window.localStorage.setItem).toHaveBeenCalledWith(
      `refchecker:gapfinder:collapsed:${CHECK_ID}`, '1',
    )

    // Remount: the persisted '1' seeds the panel collapsed without re-clicking.
    unmount()
    render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText(/work your references cite/i)
    expect(document.querySelector('.rc-collapse').className).toContain('rc-collapsed')
  })

  it('scopes the persisted collapse per checkId (one article does not leak into another)', async () => {
    getCheckGaps.mockResolvedValue({
      data: { suggestions: [{ openalex_id: 'W1', title: 'A co-cited work', co_citations: 4 }] },
    })
    // Pre-seed check 9 as collapsed; a DIFFERENT check must still open expanded.
    store.set(`refchecker:gapfinder:collapsed:${CHECK_ID}`, '1')
    render(<GapFinder checkId={CHECK_ID + 1} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText(/work your references cite/i)
    expect(document.querySelector('.rc-collapse').className).not.toContain('rc-collapsed')
  })
})

describe('GapFinder — R18 commit renumber + download new list', () => {
  it('passes insert_at_index derived from new_printed_number when the preview has numeric shifts', async () => {
    getCheckGaps.mockResolvedValue({
      data: { suggestions: [{ openalex_id: 'W1', title: 'A co-cited work', co_citations: 4, doi: '10.1/new' }] },
    })
    // A numeric preview that says the new ref takes printed position 3 and that
    // existing markers shift — so the commit must NOT append (insert_at_index=2).
    getCitationRenumberPreview.mockResolvedValue({
      data: {
        abstained: false, scheme: 'bracket', new_printed_number: 3,
        shifted_markers: [{ offset: 10, marker: '[3]', new_marker: '[4]', numbers: [3] }],
        shifted_count: 1,
      },
    })
    addReferenceToCheck.mockResolvedValue({ data: { inserted_index: 3 } })

    render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText('A co-cited work')

    fireEvent.click(screen.getByText('+ Add to references'))
    const confirm = await screen.findByRole('button', { name: /confirm add/i })
    fireEvent.click(confirm)

    await waitFor(() => expect(addReferenceToCheck).toHaveBeenCalled())
    const [, payload] = addReferenceToCheck.mock.calls[0]
    // new_printed_number(3) - 1 => 0-based insert_at_index 2.
    expect(payload.insert_at_index).toBe(2)
  })

  it('appends (no insert_at_index) when the preview abstains for a non-numeric scheme', async () => {
    getCheckGaps.mockResolvedValue({
      data: { suggestions: [{ openalex_id: 'W2', title: 'Author-year paper', co_citations: 2, doi: '10.2/ay' }] },
    })
    getCitationRenumberPreview.mockResolvedValue({
      data: { abstained: true, scheme: 'author-year', shifted_markers: [], new_printed_number: null },
    })
    addReferenceToCheck.mockResolvedValue({ data: { inserted_index: 9 } })

    render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText('Author-year paper')
    fireEvent.click(screen.getByText('+ Add to references'))
    const confirm = await screen.findByRole('button', { name: /confirm add/i })
    fireEvent.click(confirm)

    await waitFor(() => expect(addReferenceToCheck).toHaveBeenCalled())
    const [, payload] = addReferenceToCheck.mock.calls[0]
    expect(payload.insert_at_index).toBeUndefined()
  })

  it('shows a "Download new reference list" button after an add and fetches the renumbered list', async () => {
    getCheckGaps.mockResolvedValue({
      data: { suggestions: [{ openalex_id: 'W3', title: 'Added work', co_citations: 3, doi: '10.3/x' }] },
    })
    getCitationRenumberPreview.mockResolvedValue({
      data: { abstained: true, scheme: 'author-year', shifted_markers: [], new_printed_number: null },
    })
    addReferenceToCheck.mockResolvedValue({ data: { inserted_index: 5 } })
    getCorrectedReferenceList.mockResolvedValue({
      data: { style: 'plaintext', renumbered: true, count: 1, text: '[1] Added work. 2024.' },
    })

    // jsdom lacks URL.createObjectURL / anchor download; stub the bits we touch.
    const createSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:fake')
    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    render(<GapFinder checkId={CHECK_ID} references={refsWithDoi} />)
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText('Added work')

    // No download button before any add.
    expect(screen.queryByText('Download new reference list')).toBeNull()

    fireEvent.click(screen.getByText('+ Add to references'))
    const confirm = await screen.findByRole('button', { name: /confirm add/i })
    fireEvent.click(confirm)
    await screen.findByText(/✓ Added/i)

    // The download affordance now appears; clicking it pulls the renumbered list.
    const dlBtn = await screen.findByText('Download new reference list')
    fireEvent.click(dlBtn)
    await waitFor(() => expect(getCorrectedReferenceList).toHaveBeenCalledWith(
      CHECK_ID, expect.objectContaining({ renumber: true }),
    ))
    expect(clickSpy).toHaveBeenCalled()

    createSpy.mockRestore(); revokeSpy.mockRestore(); clickSpy.mockRestore()
  })
})
