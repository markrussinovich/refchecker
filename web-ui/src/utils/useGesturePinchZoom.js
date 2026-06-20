import { useEffect, useRef } from 'react'

/**
 * R31 — Shared trackpad/touch pinch-to-zoom for the document viewers.
 *
 * On macOS a trackpad pinch arrives as a `wheel` event with `ctrlKey=true`;
 * Safari/WebKit/Tauri additionally fire `gesturestart`/`gesturechange`/
 * `gestureend`. We `preventDefault()` those (non-passive listeners) so the
 * browser's own page zoom never engages, and map them onto the caller's zoom
 * state. A plain wheel (no ctrlKey) is left untouched so ordinary vertical
 * scrolling still works.
 *
 * Extracted verbatim from DocumentViewer's inline handler so the per-ref
 * ThumbnailOverlay and the native DocumentViewer share ONE implementation
 * (instead of the overlay being pinch-dead).
 *
 * @param {{current: HTMLElement|null}} ref   scroll container to listen on.
 * @param {(updater: (z:number)=>number)|((z:number)=>void)} setZoom  state setter (React functional-update form supported).
 * @param {{min?: number, max?: number, sensitivity?: number}} [opts]
 *   - min/max: zoom clamp bounds (default 0.5 / 3).
 *   - sensitivity: wheel→zoom exponent factor (default 0.01).
 */
export function useGesturePinchZoom(ref, setZoom, { min = 0.5, max = 3, sensitivity = 0.01 } = {}) {
  // Live zoom mirror so the once-bound gesture handlers can read the current
  // value as their pinch baseline without re-attaching listeners on each zoom
  // change. The baseline is captured from the latest committed zoom on
  // gesturestart via the functional updater.
  const baseRef = useRef(min)

  useEffect(() => {
    const el = ref.current
    if (!el) return undefined

    const clamp = (z) => Math.min(max, Math.max(min, +Number(z).toFixed(3)))

    const onWheel = (e) => {
      if (!e.ctrlKey) return // plain scroll — let it through
      e.preventDefault()
      // deltaY > 0 means pinch-in (zoom out). Scale the step by the magnitude
      // for a smooth, proportional feel, then clamp.
      const factor = Math.exp(-e.deltaY * sensitivity)
      setZoom((z) => clamp(z * factor))
    }
    const onGestureStart = (e) => {
      e.preventDefault()
      // Capture the current zoom as the gesture baseline. setZoom's functional
      // form gives us the latest committed value without a separate prop.
      setZoom((z) => { baseRef.current = z; return z })
    }
    const onGestureChange = (e) => {
      e.preventDefault()
      setZoom(() => clamp(baseRef.current * (e.scale || 1)))
    }
    const onGestureEnd = (e) => { e.preventDefault() }

    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('gesturestart', onGestureStart, { passive: false })
    el.addEventListener('gesturechange', onGestureChange, { passive: false })
    el.addEventListener('gestureend', onGestureEnd, { passive: false })
    return () => {
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('gesturestart', onGestureStart)
      el.removeEventListener('gesturechange', onGestureChange)
      el.removeEventListener('gestureend', onGestureEnd)
    }
    // ref is a stable ref object; re-bind only when bounds/setter change.
  }, [ref, setZoom, min, max, sensitivity])
}

export default useGesturePinchZoom
