import { render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// Regression cover for half-drawn pages: the viewer repaints when the scale
// changes (it measures fit-width right after mount, and the zoom control changes
// it again), and pdf.js tears a canvas that two render tasks draw onto at once.
// A cancelled task also keeps drawing until it notices the cancellation, so
// "cancel then immediately resize + render" is not safe either.

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker-stub' }))

// Render tasks the component started, in order. Each stays pending until the
// test settles it, so we can hold a paint open across a scale change.
let renderTasks = []
let liveRenders = 0
let maxLiveRenders = 0

vi.mock('pdfjs-dist', () => {
  const page = {
    getViewport: ({ scale }) => ({
      width: 200 * scale, height: 280 * scale, transform: [scale, 0, 0, -scale, 0, 280 * scale],
    }),
    getTextContent: () => Promise.resolve({ items: [] }),
    render: ({ viewport }) => {
      liveRenders += 1
      maxLiveRenders = Math.max(maxLiveRenders, liveRenders)
      const entry = { scale: viewport.width / 200, settled: false }
      entry.promise = new Promise((resolve, reject) => {
        entry.finish = () => {
          if (entry.settled) return
          entry.settled = true
          liveRenders -= 1
          resolve()
        }
        entry.reject = () => {
          if (entry.settled) return
          entry.settled = true
          liveRenders -= 1
          const err = new Error('cancelled')
          err.name = 'RenderingCancelledException'
          reject(err)
        }
      })
      // pdf.js keeps painting until it observes the cancellation, so cancel()
      // must not settle the task synchronously.
      entry.cancel = vi.fn(() => { setTimeout(() => entry.reject(), 0) })
      const task = { promise: entry.promise, cancel: entry.cancel }
      entry.task = task
      renderTasks.push(entry)
      return task
    },
  }
  const pdf = { numPages: 1, getPage: () => Promise.resolve(page), destroy: vi.fn() }
  return {
    GlobalWorkerOptions: {},
    getDocument: () => ({ promise: Promise.resolve(pdf), destroy: vi.fn() }),
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

beforeEach(() => {
  renderTasks = []
  liveRenders = 0
  maxLiveRenders = 0
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({}))
  Element.prototype.scrollIntoView = vi.fn()
})

describe('NativePdfViewer page painting', () => {
  it('never draws two render tasks onto the same canvas at once', async () => {
    const { rerender, container } = render(
      <NativePdfViewer checkId={1} spans={[]} zoom={1} />,
    )
    await waitFor(() => expect(container.querySelector('canvas')).toBeTruthy())
    await waitFor(() => expect(renderTasks.length).toBe(1))

    // Zoom while the first paint is still drawing, twice, so the second paint is
    // itself superseded while suspended -- the window that used to let two
    // renders overlap and leave the page half drawn.
    rerender(<NativePdfViewer checkId={1} spans={[]} zoom={2} />)
    rerender(<NativePdfViewer checkId={1} spans={[]} zoom={3} />)

    await waitFor(() => expect(renderTasks.length).toBeGreaterThan(1))
    renderTasks.forEach((t) => t.finish())
    await waitFor(() => expect(liveRenders).toBe(0))

    expect(maxLiveRenders).toBe(1)
  })

  it('repaints a page whose paint was cancelled instead of leaving it half drawn', async () => {
    const { rerender, container } = render(
      <NativePdfViewer checkId={1} spans={[]} zoom={1} />,
    )
    await waitFor(() => expect(container.querySelector('canvas')).toBeTruthy())
    await waitFor(() => expect(renderTasks.length).toBe(1))
    const firstScale = renderTasks[0].scale

    // Supersede the in-flight paint, then let everything settle.
    rerender(<NativePdfViewer checkId={1} spans={[]} zoom={2} />)
    await waitFor(() => expect(renderTasks.length).toBeGreaterThan(1))
    renderTasks.forEach((t) => t.finish())

    // The page must end up painted at the new scale, not left at the abandoned one.
    await waitFor(() => {
      const last = renderTasks[renderTasks.length - 1]
      expect(last.scale).toBeCloseTo(firstScale * 2, 5)
    })
  })
})
