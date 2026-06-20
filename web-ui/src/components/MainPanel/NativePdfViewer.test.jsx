import { render, waitFor, act } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// ── Mock the pdfjs stack ────────────────────────────────────────────────────
// The worker `?url` import resolves to a string at build time; stub it so the
// test never reaches the real worker. We model a single page whose text layer
// is "the cat sat on the cat" with one text item per token, each item carrying
// a deterministic transform so the highlight/find geometry is predictable.
vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker-stub' }))

// Tokens of the single page's text layer, with char-span widths and x positions.
const TOKENS = ['the ', 'cat ', 'sat ', 'on ', 'the ', 'cat']
let textContentItems

function buildItems() {
  let x = 0
  return TOKENS.map((str) => {
    const it = { str, width: str.length * 5, transform: [1, 0, 0, 10, x, 100], hasEOL: false }
    x += str.length * 6
    return it
  })
}

vi.mock('pdfjs-dist', () => {
  const page = {
    getViewport: ({ scale }) => ({
      width: 200 * scale, height: 280 * scale, transform: [scale, 0, 0, -scale, 0, 280 * scale],
    }),
    getTextContent: () => Promise.resolve({ items: textContentItems }),
    render: () => ({ promise: Promise.resolve() }),
  }
  const pdf = { numPages: 1, getPage: () => Promise.resolve(page), destroy: vi.fn() }
  return {
    GlobalWorkerOptions: {},
    getDocument: () => ({ promise: Promise.resolve(pdf), destroy: vi.fn() }),
    // Pass the item transform straight through: tx[4]=x, tx[5]=y, hypot(tx[2],tx[3])=10.
    Util: { transform: (_vp, itTransform) => itTransform },
  }
})

vi.mock('../../utils/api', () => ({
  getPaperPdf: vi.fn(() => Promise.resolve({ data: new ArrayBuffer(8) })),
}))

vi.mock('../../utils/logger', () => ({
  logger: { debug: vi.fn(), error: vi.fn() },
}))

import NativePdfViewer from './NativePdfViewer'

// jsdom doesn't implement canvas 2d; the render path swallows paint errors, so a
// no-op getContext keeps it quiet.
beforeEach(() => {
  textContentItems = buildItems()
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({}))
  Element.prototype.scrollIntoView = vi.fn()
})

// Drive the find controller the parent (DocumentViewer) would receive via
// onFindController, then assert the rendered match overlays.
describe('NativePdfViewer find-in-PDF (R42)', () => {
  const ready = async (extraProps = {}) => {
    let controller = null
    const onFindController = vi.fn((c) => { controller = c })
    const { container } = render(
      <NativePdfViewer checkId={1} spans={[]} onFindController={onFindController} {...extraProps} />,
    )
    // Wait for the PDF to render its page.
    await waitFor(() => expect(container.querySelector('canvas')).toBeTruthy())
    await waitFor(() => expect(controller).toBeTruthy())
    return { container, getController: () => controller }
  }

  it('publishes a find controller to the parent', async () => {
    const { getController } = await ready()
    const c = getController()
    expect(typeof c.setQuery).toBe('function')
    expect(typeof c.next).toBe('function')
    expect(typeof c.prev).toBe('function')
    expect(typeof c.clear).toBe('function')
    expect(c.matchCount).toBe(0)
  })

  it('highlights all matches with a live count and renders find overlays', async () => {
    const { container, getController } = await ready()
    await act(async () => { getController().setQuery('cat') })
    // "cat" appears twice on the page.
    await waitFor(() => expect(getController().matchCount).toBe(2))
    const overlays = container.querySelectorAll('[data-find]')
    // Two matches → two anchor overlays (one data-find per match's first rect).
    expect(overlays.length).toBe(2)
    expect(overlays[0].getAttribute('data-find')).toBe('0')
    expect(overlays[1].getAttribute('data-find')).toBe('1')
  })

  it('marks the active match distinctly from the rest and advances on next()', async () => {
    const { container, getController } = await ready()
    await act(async () => { getController().setQuery('cat') })
    await waitFor(() => expect(getController().matchCount).toBe(2))

    const styleOf = (i) => container.querySelector(`[data-find="${i}"]`).getAttribute('style')
    // The active (current=0) match gets the blue accent ring (a box-shadow,
    // whose rgba() the DOM keeps unspaced); the other doesn't.
    const RING = 'box-shadow: 0 0 0 2px rgba(37,99,235,0.55)'
    expect(styleOf(0)).toContain(RING)
    expect(styleOf(1)).not.toContain(RING)

    await act(async () => { getController().next() })
    await waitFor(() => expect(getController().current).toBe(1))
    expect(styleOf(1)).toContain(RING)
    expect(styleOf(0)).not.toContain(RING)
  })

  it('find overlays use the yellow find color, NOT an R14 status color', async () => {
    const { container, getController } = await ready()
    await act(async () => { getController().setQuery('the') })
    await waitFor(() => expect(getController().matchCount).toBe(2))
    // Non-active match uses the yellow find fill (outside the status palette:
    // no green/red/amber/violet/orange/slate). Active is index 0, so check 1.
    const inactive = container.querySelector('[data-find="1"]').getAttribute('style')
    // Style is normalized with spaces by the DOM (rgba(250, 204, 21, 0.45)).
    expect(inactive).toContain('rgba(250, 204, 21')
    // Sanity: it is NOT the verified green nor the error red (R14 colors).
    expect(inactive).not.toContain('16, 185, 129') // verified green
    expect(inactive).not.toContain('239, 68, 68')  // error red
  })

  it('clear() removes all find overlays', async () => {
    const { container, getController } = await ready()
    await act(async () => { getController().setQuery('cat') })
    await waitFor(() => expect(container.querySelectorAll('[data-find]').length).toBe(2))
    await act(async () => { getController().clear() })
    await waitFor(() => expect(container.querySelectorAll('[data-find]').length).toBe(0))
  })

  it('a no-match query yields a count of 0 and no overlays', async () => {
    const { container, getController } = await ready()
    await act(async () => { getController().setQuery('zzzz-not-present') })
    await waitFor(() => expect(getController().matchCount).toBe(0))
    expect(container.querySelectorAll('[data-find]').length).toBe(0)
  })
})
