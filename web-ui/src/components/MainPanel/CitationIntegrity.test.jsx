import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the integrity API so the split-button renders in isolation.
const getCitationIntegrity = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({ getCitationIntegrity }))

import CitationIntegrity from './CitationIntegrity'

const CHECK_ID = 7

// The control's main segment is the single pill rendered through <Button>.
const mainPill = () => screen.getAllByRole('button')[0]
// Geometry-bearing inline styles that, if any changed on click, would reflow.
const geom = (el) => [el.style.height, el.style.minHeight, el.style.borderRadius, el.style.padding, el.style.boxSizing]

beforeEach(() => { getCitationIntegrity.mockReset() })

describe('CitationIntegrity — R33 unified styling + R52 click-state stability', () => {
  it('pre-check is a lone outline pill: no caret/divider, full radius (identical to the other action pills)', () => {
    render(<CitationIntegrity checkId={CHECK_ID} />)
    // Single button — no caret segment exists before the first check (§3.2 A).
    expect(screen.getAllByRole('button').length).toBe(1)
    const pill = mainPill()
    expect(pill.style.height).toBe('var(--control-h)')
    expect(pill.style.borderRadius).toBe('var(--control-radius)') // full radius lone pill
    expect(pill.className).toContain('rc-control')
  })

  it('clicking does NOT change the main pill width/height/radius/border — only icon→spinner + label-in-sizer', async () => {
    // The longest candidate label is reserved by the sizer-grid so the label
    // slot never resizes; every candidate is present as a hidden sizer.
    const sizers = () => Array.from(document.querySelectorAll('span[aria-hidden="true"]')).map((s) => s.textContent)
    getCitationIntegrity.mockReturnValue(new Promise(() => {})) // stay loading

    render(<CitationIntegrity checkId={CHECK_ID} />)
    const idleGeom = geom(mainPill())
    expect(sizers()).toContain('Numbering consistent — re-check') // the 31-char longest

    fireEvent.click(mainPill())
    // While loading: a spinner shows in the icon slot, label is "Checking numbering…".
    await waitFor(() => expect(mainPill().querySelector('.animate-spin')).toBeTruthy())
    expect(geom(mainPill())).toEqual(idleGeom) // byte-for-byte unchanged (R52)
    // The full candidate set still reserves the width while loading.
    expect(sizers()).toContain('Numbering consistent — re-check')
  })

  it('the caret is a POST-result addition; when it appears the main left corners do not move', async () => {
    getCitationIntegrity.mockResolvedValue({ data: { issues: [], badge: { label: 'consistent', color: 'var(--color-success)' }, abstained: false, scheme: 'numeric', counts: { total_markers: 5 } } })
    render(<CitationIntegrity checkId={CHECK_ID} />)
    expect(screen.getAllByRole('button').length).toBe(1) // no caret pre-check

    fireEvent.click(mainPill())
    // After a clean result: the main pill turns success (status-success) and the
    // caret appears (group now has 2 buttons). The main wrapper flattens its
    // RIGHT corners only, so its LEFT edge does not pop.
    await waitFor(() => expect(screen.getAllByRole('button').length).toBe(2))
    const caret = document.querySelector('.rc-caret-in')
    expect(caret).toBeTruthy()
    const wrapper = caret.parentElement.querySelector('span') // main wrapper
    expect(wrapper.style.borderRadius).toBe('var(--control-radius) 0 0 var(--control-radius)')
    // Main pill is now the green status variant — color reports status, geometry didn't change.
    expect(mainPill().style.backgroundColor).toBe('var(--status-success-fill)')
  })

  it('toggling the caret reveals/hides the detail panel without resizing the button', async () => {
    getCitationIntegrity.mockResolvedValue({ data: { issues: [], badge: { label: 'consistent' }, abstained: false, counts: { total_markers: 3 } } })
    render(<CitationIntegrity checkId={CHECK_ID} />)
    fireEvent.click(mainPill())
    await waitFor(() => expect(screen.getAllByRole('button').length).toBe(2))
    const beforeGeom = geom(mainPill())
    const caret = document.querySelector('.rc-caret-in')
    fireEvent.click(caret) // collapse the detail
    expect(geom(mainPill())).toEqual(beforeGeom) // caret toggle never reflows the main pill
  })
})

describe('CitationIntegrity — R15 alphabetic-key scheme', () => {
  it('renders the alpha-key scheme label and alphabetical ordering for a clean alpha-key result', async () => {
    getCitationIntegrity.mockResolvedValue({ data: {
      issues: [], badge: { label: 'consistent', color: 'var(--color-success)' }, abstained: false,
      scheme: 'alpha-key', counts: { total_markers: 8 },
      ordering: { convention: 'alphabetical', consistent: true },
    } })
    render(<CitationIntegrity checkId={CHECK_ID} />)
    fireEvent.click(mainPill())
    await waitFor(() => expect(screen.getByText('scheme: alpha-key')).toBeTruthy())
    expect(screen.getByText('order: alphabetical ✓')).toBeTruthy()
  })

  it('shows the alpha-key-specific ABSTAIN message (not the generic one) when the refs are not derivable', async () => {
    getCitationIntegrity.mockResolvedValue({ data: {
      issues: [], badge: { label: 'n/a', color: '#6b7280' }, abstained: true,
      scheme: 'alpha-key', has_text: true,
      abstain_reason: 'alpha-key reference list not derivable',
    } })
    render(<CitationIntegrity checkId={CHECK_ID} />)
    fireEvent.click(mainPill())
    await waitFor(() => expect(
      screen.getByText(/Alphabetic citation keys detected, but the reference list lacks the author\/year data/),
    ).toBeTruthy())
  })

  it('renders the reverse-appearance ordering label honestly', async () => {
    getCitationIntegrity.mockResolvedValue({ data: {
      issues: [], badge: { label: 'consistent', color: 'var(--color-success)' }, abstained: false,
      scheme: 'numeric', counts: { total_markers: 5 },
      ordering: { convention: 'reverse-appearance', consistent: true },
    } })
    render(<CitationIntegrity checkId={CHECK_ID} />)
    fireEvent.click(mainPill())
    await waitFor(() => expect(screen.getByText('order: reverse-appearance ✓')).toBeTruthy())
  })
})
