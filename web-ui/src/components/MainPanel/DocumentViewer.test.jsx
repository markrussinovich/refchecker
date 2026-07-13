import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import DocumentViewer, { CITE_FOCUS_ZOOM } from './DocumentViewer'

// NativePdfViewer pulls in pdfjs + the worker; stub it so the test isolates the
// R12 zoom logic in DocumentViewer. The stub renders the `zoom` prop it was
// handed so the test can assert the deterministic focus zoom.
vi.mock('./NativePdfViewer', () => ({
  default: ({ zoom }) => <div data-testid="pdf-zoom">{String(zoom)}</div>,
}))

// Keep the text-fallback path quiet; the PDF stub is what we assert on.
vi.mock('../../utils/api', () => ({
  getPaperText: vi.fn(() => Promise.resolve({ data: { text: '', available: false } })),
}))

vi.mock('../../utils/tauriBridge', () => ({
  isTauri: () => false,
  openExternal: vi.fn(),
}))

const zoomShown = () => Number(screen.getByTestId('pdf-zoom').textContent)

// R12 (S7) — opening a citation must ALWAYS land at the deterministic focus
// zoom regardless of prior zoom/open, and re-targeting while open must reset
// back to it (the viewer stays mounted as the user moves card→card).
describe('DocumentViewer focus zoom (R12)', () => {
  const spans = [
    { quote: 'The method outperforms the baseline by a wide margin in every run.', status: 'verified', refId: '4' },
  ]

  it('opens a focused citation at fit-width (CITE_FOCUS_ZOOM = 1) so the page is not over-zoomed', () => {
    render(<DocumentViewer checkId={1} spans={spans} focusSpanIndex={0} onClose={vi.fn()} />)
    // A focused citation must fit the modal width — centering on the highlight
    // handles focus, so we never open zoomed past fit-width (which clipped the
    // page horizontally in a two-column paper).
    expect(CITE_FOCUS_ZOOM).toBe(1)
    expect(zoomShown()).toBe(CITE_FOCUS_ZOOM)
  })

  it('opens at fit-width (1) when there is no focused passage', () => {
    render(<DocumentViewer checkId={1} spans={spans} focusSpanIndex={null} onClose={vi.fn()} />)
    expect(zoomShown()).toBe(1)
  })

  it('resets zoom to CITE_FOCUS_ZOOM when the citation target changes', () => {
    const { rerender } = render(
      <DocumentViewer checkId={1} spans={spans} focusSpanIndex={0} onClose={vi.fn()} />,
    )
    expect(zoomShown()).toBe(CITE_FOCUS_ZOOM)

    // Simulate the user zooming out manually via the header control.
    fireEvent.click(screen.getByTitle('Zoom out (−)'))
    expect(zoomShown()).toBeLessThan(CITE_FOCUS_ZOOM)

    // Re-target to a DIFFERENT citation (new focused-span quote): zoom must snap
    // back to the deterministic focus zoom, not inherit the stale value.
    const nextSpans = [
      { quote: 'A completely different cited sentence with its own distinct content here.', status: 'error', refId: '9' },
    ]
    rerender(<DocumentViewer checkId={1} spans={nextSpans} focusSpanIndex={0} onClose={vi.fn()} />)
    expect(zoomShown()).toBe(CITE_FOCUS_ZOOM)
  })
})
