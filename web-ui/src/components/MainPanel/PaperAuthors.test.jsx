import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getPaperAuthors, fetchAuthorProfile, findAuthorProfile } = vi.hoisted(() => ({
  getPaperAuthors: vi.fn(), fetchAuthorProfile: vi.fn(), findAuthorProfile: vi.fn(),
}))
vi.mock('../../utils/api', () => ({
  getPaperAuthors, fetchAuthorProfile,
  findAuthorProfile,
}))
vi.mock('../../utils/tauriBridge', () => ({ openExternal: vi.fn(), isTauri: () => false }))

import PaperAuthors from './PaperAuthors'

const metadata = {
  available: true, title: 'A Study of Reliable Systems', year: 2025, source: 'openalex',
  authors: [{
    name: 'Jane Doe', openalex_id: 'A98765', orcid: '0000-0002-1825-0097',
    institutions: ['Example University'],
  }],
}

beforeEach(() => {
  getPaperAuthors.mockReset()
  fetchAuthorProfile.mockReset()
  findAuthorProfile.mockReset()
  findAuthorProfile.mockResolvedValue({ data: { available: false } })
  getPaperAuthors.mockResolvedValue({ data: metadata })
  fetchAuthorProfile.mockResolvedValue({ data: {
    available: true, hIndex: 12, i10Index: 23, citationCount: 456,
    paperCount: 34, source: 'openalex', metricsSource: 'openalex',
  } })
})

describe('checked-paper author cards', () => {
  it('shows the existing author card with real stats and Google Scholar link', async () => {
    render(<PaperAuthors checkId={42} />)
    expect(screen.getByRole('status')).toHaveTextContent('Preloading paper authors and profiles')
    const name = await screen.findByRole('link', { name: 'Jane Doe' })
    expect(getPaperAuthors).toHaveBeenCalledWith(42)
    fireEvent.mouseEnter(name)
    const card = await screen.findByRole('tooltip')
    await waitFor(() => expect(within(card).getByText('456 citations')).toBeInTheDocument())
    expect(within(card).getByText('Example University')).toBeInTheDocument()
    const scholar = within(card).getByRole('link', { name: /Google Scholar/ })
    expect(scholar).toHaveAttribute('href', 'https://scholar.google.com/scholar?q=Jane%20Doe')
    expect(fetchAuthorProfile).toHaveBeenCalledWith({ author_id: null, openalex_id: 'A98765' })
    expect(screen.getByLabelText('Paper authors')).not.toHaveTextContent('from matched record')
  })

  it('opens a preloaded card immediately without profile or name lookup requests', async () => {
    getPaperAuthors.mockResolvedValueOnce({ data: {
      ...metadata,
      authors: [{
        ...metadata.authors[0],
        profile_lookup_complete: true,
        profile: { available: true, hIndex: 12, citationCount: 456, paperCount: 34 },
      }],
    } })
    const { unmount } = render(<PaperAuthors checkId={45} />)
    fireEvent.mouseEnter(await screen.findByRole('link', { name: 'Jane Doe' }))
    expect(within(await screen.findByRole('tooltip')).getByText('456 citations')).toBeInTheDocument()
    expect(fetchAuthorProfile).not.toHaveBeenCalled()
    unmount()
    render(<PaperAuthors checkId={45} />)
    fireEvent.mouseEnter(await screen.findByRole('link', { name: 'Jane Doe' }))
    expect(within(await screen.findByRole('tooltip')).getByText('456 citations')).toBeInTheDocument()
    expect(fetchAuthorProfile).not.toHaveBeenCalled()
    expect(findAuthorProfile).not.toHaveBeenCalled()
  })

  it('does not retry a preloaded unavailable profile on hover', async () => {
    getPaperAuthors.mockResolvedValueOnce({ data: {
      ...metadata,
      authors: [{
        name: 'Unindexed Author',
        profile_lookup_complete: true,
        profile: { available: false },
      }],
    } })
    render(<PaperAuthors checkId={46} />)
    const name = await screen.findByText('Unindexed Author')
    fireEvent.mouseEnter(name)
    expect(await screen.findByRole('tooltip')).toBeInTheDocument()
    expect(fetchAuthorProfile).not.toHaveBeenCalled()
    expect(findAuthorProfile).not.toHaveBeenCalled()
  })

  it('reports missing authors without inventing names and allows retry', async () => {
    getPaperAuthors.mockResolvedValueOnce({
      data: { available: false, authors: [], reason: 'No confident indexed author list was found.' },
    })
    render(<PaperAuthors checkId={43} />)
    expect(await screen.findByText('No confident indexed author list was found.')).toBeInTheDocument()
    expect(screen.queryByText('Jane Doe')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry author lookup' }))
    expect(await screen.findByRole('link', { name: 'Jane Doe' })).toBeInTheDocument()
  })

  it('keeps author cards available for non-Latin names', async () => {
    getPaperAuthors.mockResolvedValueOnce({ data: {
      ...metadata, source: 'arxiv', authors: [{ name: '李明', openalex_id: 'A98766' }],
    } })
    render(<PaperAuthors checkId={44} />)
    const name = await screen.findByRole('link', { name: '李明' })
    fireEvent.mouseEnter(name)
    const card = await screen.findByRole('tooltip')
    expect(within(card).getByRole('link', { name: /Google Scholar/ })).toHaveAttribute(
      'href', `https://scholar.google.com/scholar?q=${encodeURIComponent('李明')}`,
    )
    expect(screen.getByText(/Authors from arXiv/)).toBeInTheDocument()
  })

  it('surfaces a server error and supports retry', async () => {
    getPaperAuthors.mockRejectedValueOnce({ response: { data: { detail: 'Author service unavailable.' } } })
    render(<PaperAuthors checkId={42} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Author service unavailable.')
    fireEvent.click(screen.getByRole('button', { name: 'Retry author lookup' }))
    expect(await screen.findByRole('link', { name: 'Jane Doe' })).toBeInTheDocument()
  })

  it('does not leak an old paper author list when switching batch/history papers', async () => {
    let finishOld
    getPaperAuthors.mockReturnValueOnce(new Promise(resolve => { finishOld = resolve }))
    const { rerender } = render(<PaperAuthors checkId={42} />)
    rerender(<PaperAuthors checkId={43} />)
    expect(await screen.findByRole('link', { name: 'Jane Doe' })).toBeInTheDocument()
    finishOld({ data: { ...metadata, authors: [{ name: 'Wrong Paper Author' }] } })
    await waitFor(() => expect(getPaperAuthors).toHaveBeenCalledTimes(2))
    expect(screen.queryByText('Wrong Paper Author')).not.toBeInTheDocument()
  })
})
