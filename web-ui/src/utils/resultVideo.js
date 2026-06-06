/**
 * In-app result → video walkthrough.
 *
 * Renders an animated <canvas> summary of a check (title → verdict gauge →
 * reference stats → AI-likelihood) and records it to a WebM Blob via
 * canvas.captureStream() + MediaRecorder. Fully client-side: no ffmpeg, no
 * screen-share permission, no extra dependency. Returns a Blob (or null if the
 * browser/webview can't record).
 */

const COLORS = {
  bg: '#0f1117', card: '#171a23', fg: '#f3f4f6', muted: '#9aa0ad',
  verified: '#22c55e', warning: '#f59e0b', error: '#ef4444', accent: '#3b82f6',
  ai: '#ef4444', mixed: '#f59e0b', human: '#22c55e',
}

function ease(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2 }

function drawGauge(ctx, cx, cy, r, frac, color, label, sub) {
  ctx.lineWidth = 14
  ctx.strokeStyle = 'rgba(255,255,255,0.08)'
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke()
  ctx.strokeStyle = color
  ctx.lineCap = 'round'
  ctx.beginPath(); ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * frac); ctx.stroke()
  ctx.fillStyle = COLORS.fg
  ctx.textAlign = 'center'
  ctx.font = '700 34px -apple-system,Segoe UI,Roboto,sans-serif'
  ctx.fillText(label, cx, cy + 6)
  if (sub) {
    ctx.fillStyle = COLORS.muted
    ctx.font = '14px -apple-system,Segoe UI,Roboto,sans-serif'
    ctx.fillText(sub, cx, cy + 30)
  }
}

export async function recordResultVideo({ title, stats = {}, aiBand, aiScore, durationMs = 6500 } = {}) {
  if (typeof MediaRecorder === 'undefined') return null
  const W = 1280, H = 720
  const canvas = document.createElement('canvas')
  canvas.width = W; canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx || !canvas.captureStream) return null

  const stream = canvas.captureStream(30)
  let mime = 'video/webm;codecs=vp9'
  if (!MediaRecorder.isTypeSupported?.(mime)) mime = 'video/webm;codecs=vp8'
  if (!MediaRecorder.isTypeSupported?.(mime)) mime = 'video/webm'
  const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 4_000_000 })
  const chunks = []
  rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data) }

  const total = Math.max(0, stats.total || 0)
  const verified = stats.verified || 0
  const verFrac = total ? verified / total : 0
  const bandColor = aiBand === 'high' ? COLORS.ai : aiBand === 'medium' ? COLORS.mixed : COLORS.human
  const aiPct = typeof aiScore === 'number' ? Math.round(aiScore * 100) : null

  const start = performance.now()
  const done = new Promise((resolve) => {
    rec.onstop = () => resolve(chunks.length ? new Blob(chunks, { type: 'video/webm' }) : null)
  })

  function frame(now) {
    const t = Math.min(1, (now - start) / durationMs)
    // background
    ctx.fillStyle = COLORS.bg; ctx.fillRect(0, 0, W, H)
    // brand
    ctx.fillStyle = COLORS.accent
    ctx.textAlign = 'left'
    ctx.font = '700 22px -apple-system,Segoe UI,Roboto,sans-serif'
    ctx.fillText('RefChecker', 60, 64)

    // title (scene 1, fades/slides in)
    const s1 = ease(Math.min(1, t / 0.18))
    ctx.fillStyle = COLORS.fg
    ctx.font = '700 40px -apple-system,Segoe UI,Roboto,sans-serif'
    ctx.globalAlpha = s1
    const tt = (title || 'Reference report').slice(0, 52)
    ctx.fillText(tt, 60, 130 - (1 - s1) * 16)
    ctx.globalAlpha = 1
    ctx.fillStyle = COLORS.muted
    ctx.font = '18px -apple-system,Segoe UI,Roboto,sans-serif'
    ctx.fillText('Reference verification report', 60, 162)

    // verification gauge (scene 2)
    const s2 = ease(Math.max(0, Math.min(1, (t - 0.22) / 0.3)))
    drawGauge(ctx, 280, 420, 110, verFrac * s2, COLORS.verified,
      `${Math.round(verFrac * 100 * s2)}%`, 'verified')

    // stat chips (scene 3)
    const s3 = Math.max(0, Math.min(1, (t - 0.4) / 0.3))
    const chips = [
      [total, 'references', COLORS.fg],
      [stats.warnings || 0, 'warnings', COLORS.warning],
      [stats.errors || 0, 'errors', COLORS.error],
    ]
    chips.forEach((c, i) => {
      const a = Math.max(0, Math.min(1, (s3 * 3) - i))
      ctx.globalAlpha = a
      const y = 320 + i * 90
      ctx.fillStyle = COLORS.card
      ctx.fillRect(560, y, 360, 74)
      ctx.fillStyle = c[2]
      ctx.font = '700 30px -apple-system,Segoe UI,Roboto,sans-serif'
      ctx.textAlign = 'left'
      ctx.fillText(String(c[0]), 584, y + 48)
      ctx.fillStyle = COLORS.muted
      ctx.font = '16px -apple-system,Segoe UI,Roboto,sans-serif'
      ctx.fillText(c[1], 660, y + 46)
      ctx.globalAlpha = 1
    })

    // AI band (scene 4)
    if (aiBand && aiBand !== 'unavailable' && aiBand !== 'inconclusive') {
      const s4 = ease(Math.max(0, Math.min(1, (t - 0.66) / 0.3)))
      ctx.globalAlpha = s4
      ctx.fillStyle = COLORS.muted
      ctx.textAlign = 'center'
      ctx.font = '16px -apple-system,Segoe UI,Roboto,sans-serif'
      ctx.fillText('AI-text likelihood', 280, 600)
      ctx.fillStyle = bandColor
      ctx.font = '700 26px -apple-system,Segoe UI,Roboto,sans-serif'
      ctx.fillText(`${aiBand.toUpperCase()}${aiPct != null ? ` · ${aiPct}` : ''}`, 280, 632)
      ctx.globalAlpha = 1
    }

    if (t < 1) requestAnimationFrame(frame)
    else setTimeout(() => { try { rec.stop() } catch { /* noop */ } }, 200)
  }

  rec.start()
  requestAnimationFrame(frame)
  return done
}
