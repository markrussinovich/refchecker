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

describe('ReferenceEnrichmentStrip — clickable count tiles (R35/M5)', () => {
  it('renders Citations + Reference Count as OpenAlex drill-down links when openalex_id is present', () => {
    render(
      <ReferenceEnrichmentStrip
        enrichment={{ cited_by_count: 182, reference_count: 51, openalex_id: 'W123' }}
      />
    )
    // Citations value links to the works that cite this paper.
    const citationsLink = screen.getByRole('link', { name: '182' })
    expect(citationsLink).toHaveAttribute('href', 'https://openalex.org/works?filter=cites:W123')
    // Reference Count value links to this work's OpenAlex page.
    const refsLink = screen.getByRole('link', { name: '51' })
    expect(refsLink).toHaveAttribute('href', 'https://openalex.org/W123')
  })

  it('renders the count values as plain text (no link) when openalex_id is absent', () => {
    render(
      <ReferenceEnrichmentStrip
        enrichment={{ cited_by_count: 182, reference_count: 51 }}
      />
    )
    // No dead links: with no OpenAlex id the numbers are plain text.
    expect(screen.queryByRole('link', { name: '182' })).toBeNull()
    expect(screen.queryByRole('link', { name: '51' })).toBeNull()
    // The numbers still render.
    expect(screen.getByText('182')).toBeInTheDocument()
    expect(screen.getByText('51')).toBeInTheDocument()
  })

  it('gives every count tile a title for parity (no inert, unexplained numbers)', () => {
    render(
      <ReferenceEnrichmentStrip
        enrichment={{ cited_by_count: 5, reference_count: 8, citing_patents_count: 2 }}
      />
    )
    // Each tile's wrapping span carries a title (Citing Patents, Citations, Reference Count).
    expect(screen.getByText(/Citing Patents:/).closest('[title]')).toHaveAttribute('title')
    expect(screen.getByText(/Citations:/).closest('[title]')).toHaveAttribute('title')
    expect(screen.getByText(/Reference Count:/).closest('[title]')).toHaveAttribute('title')
  })

  it('keeps Citing Patents informational (never a link) even with openalex_id', () => {
    render(
      <ReferenceEnrichmentStrip
        enrichment={{ citing_patents_count: 3, openalex_id: 'W999' }}
      />
    )
    // There is no per-patent drill-down, so Citing Patents stays plain text.
    expect(screen.queryByRole('link', { name: '3' })).toBeNull()
    expect(screen.getByText('3')).toBeInTheDocument()
  })
})
