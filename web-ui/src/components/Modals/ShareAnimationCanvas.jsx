import { forwardRef, useEffect, useRef } from 'react'

/**
 * An in-modal animated walkthrough of the check results, drawn live on a
 * <canvas> — a "walkthrough video" feel without any recording. Shown in the
 * share dialog (and while the shareable report is generated) as a looping
 * preview; loops until unmounted. Pure canvas + requestAnimationFrame, no
 * MediaRecorder/captureStream.
 */
const C = {
  bg: '#0f1117', fg: '#f3f4f6', muted: '#9aa0ad',
  verified: '#22c55e', warning: '#f59e0b', error: '#ef4444', accent: '#3b82f6',
  ai: '#ef4444', mixed: '#f59e0b', human: '#22c55e',
}
const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2)

const ShareAnimationCanvas = forwardRef(function ShareAnimationCanvas({ title, stats = {}, aiBand, aiScore, height = 220 }, fwdRef) {
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
    // Render at devicePixelRatio for a crisp, high-quality result (the logical
    // drawing coords stay 460xH; the backing store is scaled up).
    const dpr = Math.min(2, (typeof window !== 'undefined' && window.devicePixelRatio) || 1)
    const W = 460, H = height
    canvas.width = Math.round(W * dpr)
    canvas.height = Math.round(H * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    const DUR = 5200
    const total = Math.max(0, stats.total || 0)
    const verified = stats.verified || 0
    const verFrac = total ? verified / total : 0
    const bandColor = aiBand === 'high' ? C.ai : aiBand === 'medium' ? C.mixed : C.human
    const aiPct = typeof aiScore === 'number' ? Math.round(aiScore * 100) : null

    const gauge = (cx, cy, r, frac, color, label, sub) => {
      ctx.lineWidth = 11
      ctx.strokeStyle = 'rgba(255,255,255,0.08)'
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke()
      ctx.strokeStyle = color; ctx.lineCap = 'round'
      ctx.beginPath(); ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * frac); ctx.stroke()
      ctx.fillStyle = C.fg; ctx.textAlign = 'center'
      ctx.font = '700 26px -apple-system,Segoe UI,Roboto,sans-serif'
      ctx.fillText(label, cx, cy + 5)
      if (sub) { ctx.fillStyle = C.muted; ctx.font = '11px -apple-system,Segoe UI,Roboto,sans-serif'; ctx.fillText(sub, cx, cy + 24) }
    }

    const frame = (now) => {
      if (!startRef.current) startRef.current = now
      const t = ((now - startRef.current) % DUR) / DUR
      ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H)
      ctx.fillStyle = C.accent; ctx.textAlign = 'left'
      ctx.font = '700 15px -apple-system,Segoe UI,Roboto,sans-serif'
      ctx.fillText('RefChecker', 28, 34)

      const s1 = ease(Math.min(1, t / 0.16))
      ctx.fillStyle = C.fg; ctx.globalAlpha = s1
      ctx.font = '700 22px -apple-system,Segoe UI,Roboto,sans-serif'
      ctx.fillText((title || 'Reference report').slice(0, 40), 28, 66 - (1 - s1) * 10)
      ctx.globalAlpha = 1

      const s2 = ease(Math.max(0, Math.min(1, (t - 0.2) / 0.3)))
      gauge(110, 150, 56, verFrac * s2, C.verified, `${Math.round(verFrac * 100 * s2)}%`, 'verified')

      const s3 = Math.max(0, Math.min(1, (t - 0.4) / 0.3))
      const chips = [[total, 'references', C.fg], [stats.warnings || 0, 'warnings', C.warning], [stats.errors || 0, 'errors', C.error]]
      chips.forEach((c, i) => {
        const a = Math.max(0, Math.min(1, (s3 * 3) - i)); ctx.globalAlpha = a
        const y = 96 + i * 38
        ctx.fillStyle = c[2]; ctx.font = '700 20px -apple-system,Segoe UI,Roboto,sans-serif'; ctx.textAlign = 'left'
        ctx.fillText(String(c[0]), 230, y)
        ctx.fillStyle = C.muted; ctx.font = '13px -apple-system,Segoe UI,Roboto,sans-serif'
        ctx.fillText(c[1], 268, y - 1)
        ctx.globalAlpha = 1
      })

      if (aiBand && aiBand !== 'unavailable' && aiBand !== 'inconclusive') {
        const s4 = ease(Math.max(0, Math.min(1, (t - 0.66) / 0.3))); ctx.globalAlpha = s4
        ctx.fillStyle = C.muted; ctx.textAlign = 'left'; ctx.font = '12px -apple-system,Segoe UI,Roboto,sans-serif'
        ctx.fillText('AI-text likelihood', 28, 206)
        ctx.fillStyle = bandColor; ctx.font = '700 15px -apple-system,Segoe UI,Roboto,sans-serif'
        ctx.fillText(`${aiBand.toUpperCase()}${aiPct != null ? ` · ${aiPct}` : ''}`, 150, 206)
        ctx.globalAlpha = 1
      }
      rafRef.current = requestAnimationFrame(frame)
    }
    rafRef.current = requestAnimationFrame(frame)
    return () => { cancelAnimationFrame(rafRef.current); startRef.current = 0 }
  }, [title, stats, aiBand, aiScore])

  return (
    <canvas
      ref={setCanvas}
      width={460}
      height={height}
      style={{ width: '100%', borderRadius: 10, border: '1px solid var(--color-border)', display: 'block' }}
    />
  )
})

export default ShareAnimationCanvas
