import { forwardRef, useEffect, useRef } from 'react'

/**
 * An in-modal animated walkthrough of the check results, drawn live on a
 * <canvas> — a "walkthrough video" feel without any recording. Shown in the
 * share dialog and alongside an article's stats. Pure canvas +
 * requestAnimationFrame, no MediaRecorder/captureStream.
 *
 * R23: PLAY ONCE, THEN FREEZE. By default (`loop=false`) the animation runs a
 * single pass — the progress `t` is CLAMPED to `min(1, …)` (no modulo) and the
 * rAF loop is cancelled once `t === 1`, holding the final fully-drawn frame so
 * the top of the share banner never blanks. Re-mounting the component (via a
 * `key` change on open) replays it once, then holds again. Pass `loop` to keep
 * the old continuous-loop behaviour.
 *
 * Counts are NOT recomputed here — they are read verbatim from the `stats`
 * prop, which every call site derives from the SAME authoritative summary the
 * app's Summary bar shows (buildReferenceSummary). So the numbers on the
 * animation always match the numbers in the summary bar.
 */
const C = {
  bg: '#0f1117', fg: '#f3f4f6', muted: '#9aa0ad',
  verified: '#22c55e', warning: '#f59e0b', error: '#ef4444', accent: '#10a37f',
  ai: '#ef4444', mixed: '#f59e0b', human: '#22c55e',
}
const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2)

const ShareAnimationCanvas = forwardRef(function ShareAnimationCanvas({ title, stats = {}, aiBand, aiScore, height = 248, loop = false }, fwdRef) {
  const ref = useRef(null)
  const rafRef = useRef(0)
  const startRef = useRef(0)
  const setCanvas = (el) => {
    ref.current = el
    if (typeof fwdRef === 'function') fwdRef(el)
    else if (fwdRef) fwdRef.current = el
  }

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return undefined
    const ctx = canvas.getContext('2d')
    if (!ctx) return undefined
    // Render at devicePixelRatio for a crisp, high-quality result (the logical
    // drawing coords stay W x H; the backing store is scaled up). R23: raise
    // the dpr cap to 3 and use a larger logical width for a sharper, more
    // legible "video".
    const dpr = Math.min(3, (typeof window !== 'undefined' && window.devicePixelRatio) || 1)
    const W = 560, H = height
    canvas.width = Math.round(W * dpr)
    canvas.height = Math.round(H * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    const DUR = 5200

    // ---- Layout — every element is placed relative to a fixed padding and the
    // real canvas height, so nothing overlaps or clips regardless of `height`.
    const PAD = 22
    const hasAi = !!aiBand && aiBand !== 'unavailable' && aiBand !== 'inconclusive'
    const headerY = PAD + 6          // "RefChecker" brand baseline
    const titleY = headerY + 28      // document title baseline
    const aiRowH = hasAi ? 26 : 0    // reserved space for the AI footer row
    // The content band (gauge + chips) sits between the title and the AI row,
    // vertically centred so it never collides with either.
    const bandTop = titleY + 14
    const bandBottom = H - PAD - aiRowH
    const bandMidY = (bandTop + bandBottom) / 2
    // Gauge: radius derived from the available band height so it always fits.
    const gaugeR = Math.max(34, Math.min(56, (bandBottom - bandTop) / 2 - 6))
    const gaugeCx = PAD + gaugeR + 6
    const gaugeCy = bandMidY
    // Chips column starts a clear gap to the right of the gauge.
    const chipsX = gaugeCx + gaugeR + 28
    const chipNumX = chipsX
    const chipLblX = chipsX + 42
    const chipGap = Math.min(34, (bandBottom - bandTop) / 3)
    const chipsTop = bandMidY - chipGap   // three rows centred on the gauge

    const total = Math.max(0, stats.total || 0)
    const verified = stats.verified || 0
    const verFrac = total ? Math.min(1, verified / total) : 0
    const bandColor = aiBand === 'high' ? C.ai : aiBand === 'medium' ? C.mixed : C.human
    const aiPct = typeof aiScore === 'number' ? Math.round(aiScore * 100) : null

    const gauge = (cx, cy, r, frac, color, label, sub) => {
      ctx.lineWidth = 10
      ctx.strokeStyle = 'rgba(255,255,255,0.08)'
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke()
      ctx.strokeStyle = color; ctx.lineCap = 'round'
      ctx.beginPath(); ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * frac); ctx.stroke()
      ctx.lineCap = 'butt'
      ctx.fillStyle = C.fg; ctx.textAlign = 'center'
      ctx.font = `700 ${Math.round(r * 0.46)}px -apple-system,Segoe UI,Roboto,sans-serif`
      ctx.fillText(label, cx, cy + 5)
      if (sub) { ctx.fillStyle = C.muted; ctx.font = '11px -apple-system,Segoe UI,Roboto,sans-serif'; ctx.fillText(sub, cx, cy + r * 0.42 + 12) }
    }

    const frame = (now) => {
      if (!startRef.current) startRef.current = now
      // R23: clamp to a single pass (no modulo). When `loop` is set keep the
      // old continuous behaviour; otherwise `t` saturates at 1 and we freeze.
      const elapsed = (now - startRef.current) / DUR
      const t = loop ? (elapsed % 1) : Math.min(1, elapsed)
      ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H)

      // Brand mark
      ctx.fillStyle = C.accent; ctx.textAlign = 'left'
      ctx.font = '700 17px -apple-system,Segoe UI,Roboto,sans-serif'
      ctx.fillText('RefChecker', PAD, headerY)

      // Document title (clipped to the canvas width so it never overruns)
      const s1 = ease(Math.min(1, t / 0.16))
      ctx.save()
      ctx.beginPath(); ctx.rect(PAD, titleY - 22, W - PAD * 2, 30); ctx.clip()
      ctx.fillStyle = C.fg; ctx.globalAlpha = s1
      ctx.font = '700 22px -apple-system,Segoe UI,Roboto,sans-serif'
      ctx.fillText((title || 'Reference report').slice(0, 52), PAD, titleY - (1 - s1) * 10)
      ctx.restore()
      ctx.globalAlpha = 1

      // Verified gauge
      const s2 = ease(Math.max(0, Math.min(1, (t - 0.2) / 0.3)))
      gauge(gaugeCx, gaugeCy, gaugeR, verFrac * s2, C.verified, `${Math.round(verFrac * 100 * s2)}%`, 'verified')

      // Count chips: references / warnings / errors — straight from `stats`.
      const s3 = Math.max(0, Math.min(1, (t - 0.4) / 0.3))
      const chips = [
        [total, 'references', C.fg],
        [stats.warnings || 0, 'warnings', C.warning],
        [stats.errors || 0, 'errors', C.error],
      ]
      chips.forEach((c, i) => {
        const a = Math.max(0, Math.min(1, (s3 * 3) - i)); ctx.globalAlpha = a
        const y = chipsTop + i * chipGap
        ctx.fillStyle = c[2]; ctx.font = '700 22px -apple-system,Segoe UI,Roboto,sans-serif'; ctx.textAlign = 'left'
        ctx.fillText(String(c[0]), chipNumX, y)
        ctx.fillStyle = C.muted; ctx.font = '14px -apple-system,Segoe UI,Roboto,sans-serif'
        ctx.fillText(c[1], chipLblX, y - 1)
        ctx.globalAlpha = 1
      })

      // AI-text likelihood footer (only when there's a real, conclusive band)
      if (hasAi) {
        const s4 = ease(Math.max(0, Math.min(1, (t - 0.66) / 0.3))); ctx.globalAlpha = s4
        const yAi = H - PAD - 6
        ctx.fillStyle = C.muted; ctx.textAlign = 'left'; ctx.font = '13px -apple-system,Segoe UI,Roboto,sans-serif'
        ctx.fillText('AI-text likelihood', PAD, yAi)
        ctx.fillStyle = bandColor; ctx.font = '700 15px -apple-system,Segoe UI,Roboto,sans-serif'
        ctx.fillText(`${aiBand.toUpperCase()}${aiPct != null ? ` · ${aiPct}` : ''}`, PAD + 132, yAi)
        ctx.globalAlpha = 1
      }
      // R23: once a single pass has completed, hold the final frame and STOP
      // the rAF loop — the canvas stays mounted so the banner never blanks.
      if (!loop && t >= 1) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = 0
        return
      }
      rafRef.current = requestAnimationFrame(frame)
    }
    rafRef.current = requestAnimationFrame(frame)
    return () => { cancelAnimationFrame(rafRef.current); startRef.current = 0 }
  }, [title, stats, aiBand, aiScore, height, loop])

  return (
    <canvas
      ref={setCanvas}
      width={560}
      height={height}
      style={{ width: '100%', borderRadius: 10, border: '1px solid var(--color-border)', display: 'block' }}
    />
  )
})

export default ShareAnimationCanvas
