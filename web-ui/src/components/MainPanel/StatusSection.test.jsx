import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import StatusSection, { buildCitationViewerSpans, ThumbnailOverlay } from './StatusSection'

const historyState = vi.hoisted(() => ({
  selectedCheckId: 42,
  selectedCheck: {
    id: 42,
    status: 'in_progress',
    paper_title: 'Active paper',
    paper_source: 'https://example.com/paper.pdf',
    source_type: 'url',
    total_refs: 0,
    processed_refs: 0,
    llm_provider: 'google',
    llm_model: 'gemini-3.1-flash-lite-preview',
    hallucination_provider: null,
    hallucination_model: null,
  },
  history: [],
  updateHistoryProgress: vi.fn(),
}))

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

vi.mock('./PaperAuthors', () => ({
  default: ({ checkId }) => <div data-testid="paper-authors">Authors for check {checkId}</div>,
}))

vi.mock('./DocumentViewer', () => ({
  default: ({ checkId, notice, spans, onClose }) => (
    <div role="dialog" aria-label="Document fallback">
      <span>{notice}</span><span>Check {checkId}, {spans.length} highlights</span>
      <button onClick={onClose}>Close document</button>
    </div>
  ),
}))

describe('thumbnail page failures', () => {
  beforeEach(() => {
    vi.stubGlobal('IntersectionObserver', class {
      observe() {}
      disconnect() {}
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('switches failed raster pages to the document viewer and preserves highlights and close', () => {
    const close = vi.fn()
    render(<ThumbnailOverlay checkId={42} initialPageCount={2} onClose={close}
      aiDetection={{ band: 'high', spans: [{ quote: 'A flagged passage' }] }} />)
    const page = screen.getByAltText('Page 1 of 2')
    expect(page.parentElement.style.width).toBe('90vw')
    expect(page.parentElement.style.maxHeight).toBe('')
    fireEvent.error(page)
    expect(screen.queryByAltText('Page 2 of 2')).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Document fallback' })).toBeInTheDocument()
    expect(screen.getByText(/Check 42, 1 highlights/)).toBeInTheDocument()
    expect(screen.getByText(/Page images could not be loaded/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('Close document'))
    expect(close).toHaveBeenCalledOnce()
  })

  it('tries the thumbnail only once before falling back when both preview images fail', () => {
    render(<ThumbnailOverlay checkId={42} initialPageCount={1} onClose={vi.fn()}
      previewUrl="/preview.png" thumbnailUrl="/thumbnail.png" />)
    const image = screen.getByAltText('Paper preview')
    fireEvent.error(image)
    expect(image).toHaveAttribute('src', '/thumbnail.png')
    fireEvent.error(image)
    expect(screen.getByRole('dialog', { name: 'Document fallback' })).toBeInTheDocument()
  })
})

vi.mock('../../stores/useCheckStore', () => {
  const state = {
    status: 'idle',
    statusMessage: '',
    progress: 0,
    stats: {},
    paperTitle: null,
    paperSource: null,
    sourceType: null,
    sessionId: null,
    currentCheckId: null,
    cancelCheck: vi.fn(),
  }
  const useCheckStore = (selector) => selector ? selector(state) : state
  useCheckStore.getState = () => state
  return { useCheckStore }
})

vi.mock('../../stores/useHistoryStore', () => {
  const useHistoryStore = (selector) => selector ? selector(historyState) : historyState
  useHistoryStore.getState = () => historyState
  return { useHistoryStore }
})

describe('StatusSection hallucination model display', () => {
  beforeEach(() => {
    historyState.selectedCheckId = 42
    historyState.selectedCheck = {
      id: 42,
      status: 'in_progress',
      paper_title: 'Active paper',
      paper_source: 'https://example.com/paper.pdf',
      source_type: 'url',
      total_refs: 0,
      processed_refs: 0,
      llm_provider: 'google',
      llm_model: 'gemini-3.1-flash-lite-preview',
      hallucination_provider: null,
      hallucination_model: null,
    }
  })

  it('does not infer hallucination model from extraction-only metadata', () => {
    render(<StatusSection />)

    expect(screen.getByText('Extraction Model:')).toBeInTheDocument()
    expect(screen.getByText('google / gemini-3.1-flash-lite-preview')).toBeInTheDocument()
    expect(screen.queryByText('Hallucination Model:')).toBeNull()
  })

  it('retries thumbnail after a check completes', () => {
    const { rerender } = render(<StatusSection />)
    const image = screen.getByAltText('Paper thumbnail')
    expect(image.getAttribute('src')).toBe('/api/thumbnail/42?phase=active')

    fireEvent.error(image)
    expect(screen.queryByAltText('Paper thumbnail')).toBeNull()

    historyState.selectedCheck = {
      ...historyState.selectedCheck,
      status: 'completed',
      total_refs: 10,
      processed_refs: 10,
    }
    rerender(<StatusSection />)

    const retriedImage = screen.getByAltText('Paper thumbnail')
    expect(retriedImage.getAttribute('src')).toBe('/api/thumbnail/42?phase=completed')
    expect(screen.getByTestId('paper-authors')).toHaveTextContent('Authors for check 42')
  })

  it('waits for completion before looking up paper authors', () => {
    render(<StatusSection />)
    expect(screen.queryByTestId('paper-authors')).not.toBeInTheDocument()
  })
})

// R28 (S6) — clicking an inline citation must hyperlink to the reference list
// INSIDE the same PDF. buildCitationViewerSpans appends the reference-list entry
// as a second locatable span and wires the citation span's `refEntryIndex` so
// the native viewer scrolls + flashes that entry in-document on click.
describe('buildCitationViewerSpans in-PDF reference jump (R28)', () => {
  it('opens an original bibliography entry with a title fallback, not an inline citation', () => {
    const spans = buildCitationViewerSpans({
      text: 'M. Costa and C. Fournet. Securing AI agents. 2025.',
      refTitle: 'Securing AI agents', kind: 'ref-entry', refId: '23',
    })
    expect(spans).toHaveLength(2)
    expect(spans[0].quote).toContain('C. Fournet')
    expect(spans[1].quote).toBe('Securing AI agents')
    expect(spans.every(span => span.kind === 'ref-entry' && span.refEntryIndex === undefined)).toBe(true)
  })

  it('does not duplicate a title-only bibliography target from a legacy check', () => {
    expect(buildCitationViewerSpans({
      text: 'Securing AI agents', refTitle: 'Securing AI agents', kind: 'ref-entry',
    })).toHaveLength(1)
  })

  it('appends the reference-list entry span and wires refEntryIndex', () => {
    const spans = buildCitationViewerSpans({
      text: 'The method outperforms the baseline by a wide margin [4].',
      status: 'verified',
      refId: '4',
      refTitle: 'A Study of Convergence in Deep Networks',
      label: '[4]',
    })

    expect(spans).toHaveLength(2)
    // Span 0 is the cited sentence, pointing at span 1 as its in-PDF jump target.
    expect(spans[0].quote).toContain('outperforms the baseline')
    expect(spans[0].refEntryIndex).toBe(1)
    expect(spans[0].status).toBe('verified')
    // Span 1 is the reference-list entry, located by the reference title.
    expect(spans[1].kind).toBe('ref-entry')
    expect(spans[1].quote).toBe('A Study of Convergence in Deep Networks')
    expect(spans[1].refId).toBe('4')
  })

  it('omits the entry span (and refEntryIndex) when no reference title is known', () => {
    const spans = buildCitationViewerSpans({
      text: 'A cited sentence with no resolvable reference title here.',
      refId: '9',
    })
    expect(spans).toHaveLength(1)
    expect(spans[0].refEntryIndex).toBeUndefined()
    expect(spans[0].kind).toBeUndefined()
  })

  it('returns an empty array for no citation target', () => {
    expect(buildCitationViewerSpans(null)).toEqual([])
    expect(buildCitationViewerSpans({})).toEqual([])
  })
})
