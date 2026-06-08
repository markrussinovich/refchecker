import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// Mock the API + Tauri bridge so the bar renders in isolation. The bar only
// calls addSeenReference on click; mounting must never hit the network.
const addSeenReference = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({ addSeenReference }))
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

  it('renders the Add-to-Library pill when the reference is cacheable (has a title)', () => {
    render(<AdditionalInfoBar reference={{ title: 'A real paper' }} />)
    expect(screen.getByRole('button', { name: '+ Add to Library' })).toBeInTheDocument()
    // No enrichment -> none of the info pills appear.
    expect(screen.queryByRole('button', { name: 'Abstract' })).toBeNull()
  })
})
