import { render } from '@testing-library/react'
import { useRef } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useGesturePinchZoom } from './useGesturePinchZoom'

// R31 (S7) — the per-ref ThumbnailOverlay and the native DocumentViewer must
// share ONE pinch-to-zoom implementation. The hook attaches non-passive wheel +
// WebKit gesture listeners to the given scroll container, gates wheel on
// ctrlKey, preventDefault()s so the browser's own page zoom never fires, and
// drives the caller's setZoom (clamped to {min,max}).

function Harness({ setZoom, opts, onEl }) {
  const ref = useRef(null)
  useGesturePinchZoom(ref, setZoom, opts)
  return <div ref={(el) => { ref.current = el; onEl?.(el) }} data-testid="scroll" />
}

describe('useGesturePinchZoom (R31 shared pinch hook)', () => {
  it('attaches non-passive wheel + gesture listeners to the ref element', () => {
    let el = null
    const spy = vi.fn()
    // Capture addEventListener before render so we see the hook's bindings.
    render(<Harness setZoom={vi.fn()} onEl={(node) => {
      if (node && !el) {
        el = node
        el.addEventListener = spy
      }
    }} />)
    // The listener-attach effect runs after the ref is set; force a re-render so
    // the effect binds to the spied element. (addEventListener was swapped in
    // the ref callback above, which runs before effects.)
    const events = spy.mock.calls.map((c) => c[0])
    expect(events).toContain('wheel')
    expect(events).toContain('gesturestart')
    expect(events).toContain('gesturechange')
    expect(events).toContain('gestureend')
    // All bound non-passively (so preventDefault can stop browser zoom).
    for (const call of spy.mock.calls) {
      expect(call[2]).toMatchObject({ passive: false })
    }
  })

  it('ctrl+wheel zooms via setZoom and preventDefaults; plain wheel is ignored', () => {
    let zoom = 1
    const setZoom = vi.fn((updater) => { zoom = typeof updater === 'function' ? updater(zoom) : updater })
    const { getByTestId } = render(<Harness setZoom={setZoom} opts={{ min: 0.5, max: 3 }} />)
    const el = getByTestId('scroll')

    // Plain wheel (no ctrlKey): the hook must NOT touch zoom (normal scroll).
    const plain = new WheelEvent('wheel', { deltaY: -100, bubbles: true, cancelable: true })
    el.dispatchEvent(plain)
    expect(setZoom).not.toHaveBeenCalled()
    expect(plain.defaultPrevented).toBe(false)

    // Ctrl+wheel up (deltaY<0) = pinch-out (zoom in): setZoom called + prevented.
    const pinchIn = new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, bubbles: true, cancelable: true })
    el.dispatchEvent(pinchIn)
    expect(setZoom).toHaveBeenCalledTimes(1)
    expect(pinchIn.defaultPrevented).toBe(true)
    expect(zoom).toBeGreaterThan(1)

    // Ctrl+wheel down (deltaY>0) = pinch-in (zoom out).
    const pinchOut = new WheelEvent('wheel', { deltaY: 100, ctrlKey: true, bubbles: true, cancelable: true })
    el.dispatchEvent(pinchOut)
    expect(zoom).toBeLessThan(1.5)
  })

  it('clamps zoom to the configured min/max bounds', () => {
    let zoom = 1
    const setZoom = vi.fn((updater) => { zoom = typeof updater === 'function' ? updater(zoom) : updater })
    const { getByTestId } = render(<Harness setZoom={setZoom} opts={{ min: 0.7, max: 2.2 }} />)
    const el = getByTestId('scroll')
    // A huge zoom-in delta should clamp at max, not blow past it.
    for (let i = 0; i < 20; i++) {
      el.dispatchEvent(new WheelEvent('wheel', { deltaY: -300, ctrlKey: true, cancelable: true }))
    }
    expect(zoom).toBeLessThanOrEqual(2.2)
    // A huge zoom-out delta should clamp at min.
    for (let i = 0; i < 40; i++) {
      el.dispatchEvent(new WheelEvent('wheel', { deltaY: 300, ctrlKey: true, cancelable: true }))
    }
    expect(zoom).toBeGreaterThanOrEqual(0.7)
  })

  it('removes its listeners on unmount', () => {
    const removeSpy = vi.fn()
    let el = null
    const { unmount } = render(<Harness setZoom={vi.fn()} onEl={(node) => {
      if (node && !el) { el = node; el.removeEventListener = removeSpy }
    }} />)
    unmount()
    const removed = removeSpy.mock.calls.map((c) => c[0])
    expect(removed).toContain('wheel')
    expect(removed).toContain('gesturestart')
  })
})
