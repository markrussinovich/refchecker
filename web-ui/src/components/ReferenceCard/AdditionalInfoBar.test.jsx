import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// Mock the API + Tauri bridge so the bar renders in isolation. The bar calls
// addSeenReference (confirm) and removeSeenReference (remove-from-library) on
// click; mounting must never hit the network.
const addSeenReference = vi.hoisted(() => vi.fn())
const removeSeenReference = vi.hoisted(() => vi.fn(() => Promise.resolve({})))
vi.mock('../../utils/api', () => ({ addSeenReference, removeSeenReference }))
vi.mock('../../utils/tauriBridge', () => ({ openExternal: vi.fn(), isTauri: () => false }))

import AdditionalInfoBar from './AdditionalInfoBar'

describe('AdditionalInfoBar real-data gating', () => {
  it('renders nothing when there is no enrichment signal and nothing cacheable', () => {
    // No enrichment fields and no doi/arxiv/title -> canCache is false too,
    // so the whole bar must collapse to null.
    const { container } = render(<AdditionalInfoBar reference={{}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the Abstract pill only when enrichment.abstract exists', () => {
    render(<AdditionalInfoBar reference={{ enrichment: { abstract: 'An abstract.' } }} />)
    expect(screen.getByRole('button', { name: 'Abstract' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Claim' })).toBeNull()
    expect(screen.queryByText('Preprint')).toBeNull()
  })

  it('shows the Claim pill only when enrichment.tldr exists', () => {
    render(<AdditionalInfoBar reference={{ enrichment: { tldr: 'One line.' } }} />)
    expect(screen.getByRole('button', { name: 'Claim' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Abstract' })).toBeNull()
  })

  it('shows the Preprint pill only when enrichment.is_preprint is set', () => {
    render(<AdditionalInfoBar reference={{ enrichment: { is_preprint: true } }} />)
    expect(screen.getByText('Preprint')).toBeInTheDocument()
  })

  it('renders the Full-text link when an open-access pdf url exists', () => {
    render(<AdditionalInfoBar reference={{ enrichment: { oa_pdf_url: 'https://ex.com/p.pdf' } }} />)
    const link = screen.getByRole('link', { name: /View full text/ })
    expect(link).toHaveAttribute('href', 'https://ex.com/p.pdf')
  })

  it('renders the In-Library pill when the reference is cacheable (has a title)', () => {
    render(<AdditionalInfoBar reference={{ title: 'A real paper' }} />)
    // Checked refs are auto-saved, so the resting label is the honest "✓ In Library"
    // (the old misleading "+ Add to Library" was removed).
    expect(screen.getByRole('button', { name: '✓ In Library' })).toBeInTheDocument()
    // No enrichment -> none of the info pills appear.
    expect(screen.queryByRole('button', { name: 'Abstract' })).toBeNull()
    expect(screen.queryByText(/^Published /)).toBeNull()
    expect(screen.queryByText(/^Topics:/)).toBeNull()
  })

  it('no longer renders a "Published …" pill (the date is rendered by ReferenceEnrichmentStrip, not here)', () => {
    // AdditionalInfoBar deliberately does NOT render the publication date: the
    // real full date (e.g. "Oct 1, 2021") is rendered as plain "Published:"
    // text in Row-1 of ReferenceEnrichmentStrip (see R01/K2). Keeping it out of
    // this bar avoids a duplicate, looks-clickable-but-inert "Published" pill.
    for (const publication_date of ['Oct 1, 2021', '2021', '2021-10-01']) {
      const { unmount } = render(<AdditionalInfoBar reference={{ enrichment: { publication_date } }} />)
      expect(screen.queryByText(/^Published /)).toBeNull()
      unmount()
    }
  })

  it('abstains from the Published badge when publication_date has no real content', () => {
    // Empty / non-date strings carry no real signal -> badge omitted, never faked.
    const { rerender } = render(<AdditionalInfoBar reference={{ enrichment: { publication_date: '' } }} />)
    expect(screen.queryByText(/^Published /)).toBeNull()
    rerender(<AdditionalInfoBar reference={{ enrichment: { publication_date: 'n/a' } }} />)
    expect(screen.queryByText(/^Published /)).toBeNull()
  })

  it('omits the Published badge when there is no publication_date', () => {
    render(<AdditionalInfoBar reference={{ enrichment: { abstract: 'x' } }} />)
    expect(screen.queryByText(/^Published /)).toBeNull()
  })

  it('shows the Topics badge listing fields_of_study only when present', () => {
    render(<AdditionalInfoBar reference={{ enrichment: { fields_of_study: ['Computer Science', 'Machine Learning'] } }} />)
    expect(screen.getByText(/^Topics: Computer Science, Machine Learning/)).toBeInTheDocument()
  })

  it('omits the Topics badge when fields_of_study is empty or absent', () => {
    const { rerender } = render(<AdditionalInfoBar reference={{ enrichment: { fields_of_study: [] } }} />)
    expect(screen.queryByText(/^Topics:/)).toBeNull()
    rerender(<AdditionalInfoBar reference={{ enrichment: { abstract: 'x' } }} />)
    expect(screen.queryByText(/^Topics:/)).toBeNull()
  })

  it('shows a Checking… status pill only while the reference is checking', () => {
    render(<AdditionalInfoBar reference={{ status: 'checking' }} />)
    expect(screen.getByText('Checking…')).toBeInTheDocument()
  })

  it('shows a Pending status pill only while the reference is pending', () => {
    render(<AdditionalInfoBar reference={{ status: 'pending' }} />)
    expect(screen.getByText('Pending')).toBeInTheDocument()
  })

  it('omits the status pill for non-pending/checking statuses', () => {
    render(<AdditionalInfoBar reference={{ status: 'verified', enrichment: { abstract: 'x' } }} />)
    expect(screen.queryByText('Checking…')).toBeNull()
    expect(screen.queryByText('Pending')).toBeNull()
  })

  it('R33: every pill uses the shared 8px control radius (the ONE radius decision), never 9999px', () => {
    // The Pill is the most-seen pill in the app; BUTTON_DESIGN §1.0/§4.7 makes it
    // 8px (--control-radius) so it reads as part of the action-control family.
    render(<AdditionalInfoBar reference={{ enrichment: { abstract: 'An abstract.', tldr: 'A claim.', is_preprint: true } }} />)
    const pills = [
      screen.getByRole('button', { name: 'Abstract' }),
      screen.getByRole('button', { name: 'Claim' }),
      screen.getByText('Preprint'),
    ]
    for (const pill of pills) {
      expect(pill.style.borderRadius).toBe('var(--control-radius)')
      expect(pill.style.borderRadius).not.toBe('9999px')
    }
  })

  it('R44: the in-library remove is clearly "Remove from library" and calls the library handler (not the list/check remove)', async () => {
    render(<AdditionalInfoBar reference={{ title: 'A real paper' }} />)
    // Clear, distinct label so it is never confused with the reference-list
    // "Remove" (which removes the ref from the check, a different handler).
    const removeBtn = screen.getByRole('button', { name: 'Remove from library' })
    expect(removeBtn).toBeInTheDocument()
    fireEvent.click(removeBtn)
    expect(removeSeenReference).toHaveBeenCalledTimes(1)
    expect(addSeenReference).not.toHaveBeenCalled()
    // State settles to the honest "Removed" pill (no stale "✓ In Library").
    await screen.findByText('Removed')
  })
})
