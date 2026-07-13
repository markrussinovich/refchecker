import { render, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ShareAnimationCanvas from './ShareAnimationCanvas'

// jsdom has no real 2D canvas context. Stub getContext with a recording
// double so we can (a) capture every drawn number/label and (b) let the
// component's draw loop run without throwing. setTransform/arc/etc. are no-ops.
function makeCtxStub() {
  const fills = []
  const ctx = {
    fills,
    canvas: {},
    setTransform: vi.fn(),
    fillRect: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    arc: vi.fn(),
    clip: vi.fn(),
    stroke: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    fillText: vi.fn((text) => { fills.push(String(text)) }),
    set fillStyle(_v) {},
    get fillStyle() { return '#000' },
    set strokeStyle(_v) {},
    set lineWidth(_v) {},
    set lineCap(_v) {},
    set font(_v) {},
    set textAlign(_v) {},
    set globalAlpha(_v) {},
    get globalAlpha() { return 1 },
  }
  return ctx
}

// Controllable requestAnimationFrame: collects scheduled callbacks and lets the
// test drive the clock by invoking them with an explicit `now` timestamp.
let rafQueue
let rafId
let rafCancelled

beforeEach(() => {
  rafQueue = new Map()
  rafId = 0
  rafCancelled = []
  vi.stubGlobal('requestAnimationFrame', (cb) => {
    const id = ++rafId
    rafQueue.set(id, cb)
    return id
  })
  vi.stubGlobal('cancelAnimationFrame', (id) => {
    rafCancelled.push(id)
    rafQueue.delete(id)
  })
  HTMLCanvasElement.prototype.getContext = vi.fn(() => makeCtxStub())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// Pull the single pending scheduled callback and run it at time `now`.
function step(now) {
  const entries = [...rafQueue.entries()]
  if (entries.length === 0) return false
  const [id, cb] = entries[entries.length - 1]
  rafQueue.delete(id)
  cb(now)
  return true
}

describe('ShareAnimationCanvas counts come from the stats prop (R23/R24)', () => {
  it('draws the reference / warning / error numbers verbatim from stats', () => {
    let captured
    HTMLCanvasElement.prototype.getContext = vi.fn(() => {
      captured = makeCtxStub()
      return captured
    })

    render(
      <ShareAnimationCanvas
        title="My Paper"
        stats={{ total: 41, verified: 30, warnings: 8, errors: 3 }}
      />
    )
    // Run the animation forward to the final (frozen) frame so every chip and
    // the gauge have fully drawn. The first frame seeds the start timestamp
    // (browsers always pass a non-zero `now`), the second jumps well past the
    // 5200ms duration so `t` clamps to 1.
    step(100)
    step(10_100) // well past DUR (5200ms) => t clamps to 1

    const drawn = captured.fills
    // The numbers shown must be exactly what we passed — never recomputed here.
    expect(drawn).toContain('41') // references
    expect(drawn).toContain('8')  // warnings
    expect(drawn).toContain('3')  // errors
    expect(drawn).toContain('My Paper')
    // Verified gauge reaches 100*30/41 = 73% on the final frame.
    expect(drawn).toContain('73%')
  })
})

describe('ShareAnimationCanvas plays once then freezes (R23)', () => {
  it('cancels the rAF loop at t===1 and keeps the canvas mounted', () => {
    const { container } = render(
      <ShareAnimationCanvas stats={{ total: 10, verified: 5, warnings: 2, errors: 1 }} />
    )

    // First frame (non-zero `now`) seeds the start time and schedules a
    // follow-up while still mid-animation.
    step(100)
    expect(rafQueue.size).toBe(1)

    // Advance partway: still animating, still rescheduling.
    step(1100)
    expect(rafQueue.size).toBe(1)

    // Advance past the duration (5200ms): the loop must STOP — no new frame is
    // scheduled and the running frame is cancelled.
    const cancelledBefore = rafCancelled.length
    step(6100)
    expect(rafQueue.size).toBe(0)
    expect(rafCancelled.length).toBeGreaterThan(cancelledBefore)

    // The canvas element stays in the DOM (frozen final frame), so the banner
    // never blanks.
    expect(container.querySelector('canvas')).toBeTruthy()
  })

  it('loops continuously when loop=true (never auto-freezes)', () => {
    render(
      <ShareAnimationCanvas loop stats={{ total: 10, verified: 5, warnings: 2, errors: 1 }} />
    )
    step(100)
    step(6100) // past DUR
    // With loop=true the frame keeps rescheduling instead of freezing.
    expect(rafQueue.size).toBe(1)
  })
})
