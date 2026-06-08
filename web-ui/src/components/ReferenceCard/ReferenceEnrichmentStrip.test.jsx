import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// The strip renders external pill links; mock the Tauri bridge + OCLC lookup so
// mounting never touches the network or the Tauri runtime.
vi.mock('../../utils/tauriBridge', () => ({ openExternal: vi.fn(), isTauri: () => false }))
vi.mock('../../utils/api', () => ({ lookupOclc: vi.fn(() => Promise.resolve({ data: {} })) }))

import ReferenceEnrichmentStrip from './ReferenceEnrichmentStrip'

describe('ReferenceEnrichmentStrip — published-date honesty (R01/K2)', () => {
  it('renders the real publication_date as plain text in Row-1', () => {
    render(<ReferenceEnrichmentStrip enrichment={{ publication_date: 'Oct 1, 2021' }} />)
    // The date is shown, prefixed by an honest "Published:" label.
    expect(screen.getByText(/Published:/)).toBeInTheDocument()
    expect(screen.getByText('Oct 1, 2021')).toBeInTheDocument()
  })

  it('renders the date as plain text, never as a clickable button or link', () => {
    render(<ReferenceEnrichmentStrip enrichment={{ publication_date: 'Oct 1, 2021' }} />)
    // No dead button / no fake link for the date.
    expect(screen.queryByRole('button', { name: /Oct 1, 2021/ })).toBeNull()
    expect(screen.queryByRole('link', { name: /Oct 1, 2021/ })).toBeNull()
  })

  it('does NOT render an empty gated container when the only signal is a placeholder date', () => {
    // Content-free / placeholder dates carry no real signal: the strip must
    // stay fully collapsed (null), never an empty gated container.
    for (const publication_date of ['', '   ', 'n/a', 'N/A', 'none', 'null', 'unknown']) {
      const { container, unmount } = render(
        <ReferenceEnrichmentStrip enrichment={{ publication_date }} />
      )
      expect(container).toBeEmptyDOMElement()
      expect(screen.queryByText(/Published:/)).toBeNull()
      unmount()
    }
  })

  it('renders the strip (not an empty container) when publication_date is the only real signal', () => {
    // Before R01 the date gated an otherwise-empty strip but was never shown —
    // an empty gated container. Now a ref with ONLY a real date renders the
    // date, so the gate and the render stay in lock-step.
    const { container } = render(
      <ReferenceEnrichmentStrip enrichment={{ publication_date: '2021-10-01' }} />
    )
    expect(container).not.toBeEmptyDOMElement()
    expect(screen.getByText('2021-10-01')).toBeInTheDocument()
  })

  it('renders nothing when enrichment is absent or has no usable signal', () => {
    const { container: c1 } = render(<ReferenceEnrichmentStrip enrichment={null} />)
    expect(c1).toBeEmptyDOMElement()
    const { container: c2 } = render(<ReferenceEnrichmentStrip enrichment={{}} />)
    expect(c2).toBeEmptyDOMElement()
  })

  it('shows the publication_date alongside other Row-1 metadata', () => {
    render(
      <ReferenceEnrichmentStrip
        enrichment={{ publication_type: 'journal-article', biblio: { volume: '32' }, publication_date: 'Oct 1, 2021' }}
      />
    )
    expect(screen.getByText('Journal Article')).toBeInTheDocument()
    expect(screen.getByText(/Volume: 32/)).toBeInTheDocument()
    expect(screen.getByText('Oct 1, 2021')).toBeInTheDocument()
  })
})
