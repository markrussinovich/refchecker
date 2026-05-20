/**
 * Diagnostics collector.
 *
 * Builds a single JSON blob the user can paste into a GitHub issue. The
 * goal is to capture everything needed to triage "links don't open" /
 * "updater ACL" / "extraction failed" reports without making the user
 * write paragraphs. Sensitive values (API keys, full file paths under
 * /Users/...) are redacted before the blob is shown.
 *
 * Errors and warnings logged via the global logger from the moment the
 * page loads are tracked here too, so a report captured after a bug
 * includes the most recent ~200 console lines.
 */

import { isTauri } from './tauriBridge'

const RING_SIZE = 200
const ring = []
let installed = false

const _wrap = (name, level) => {
  const orig = console[name].bind(console)
  console[name] = (...args) => {
    try {
      ring.push({
        ts: new Date().toISOString(),
        level,
        msg: args.map((a) => {
          if (typeof a === 'string') return a
          try { return JSON.stringify(a) } catch { return String(a) }
        }).join(' '),
      })
      if (ring.length > RING_SIZE) ring.shift()
    } catch { /* swallow */ }
    return orig(...args)
  }
}

export function installDiagnosticsRecorder() {
  if (installed || typeof window === 'undefined') return
  installed = true
  _wrap('warn', 'warn')
  _wrap('error', 'error')

  window.addEventListener('error', (e) => {
    try {
      ring.push({
        ts: new Date().toISOString(),
        level: 'error',
        msg: `unhandled: ${e.message || ''} @ ${e.filename || ''}:${e.lineno || ''}`,
      })
      if (ring.length > RING_SIZE) ring.shift()
    } catch { /* swallow */ }
  })
  window.addEventListener('unhandledrejection', (e) => {
    try {
      const reason = e.reason
      ring.push({
        ts: new Date().toISOString(),
        level: 'error',
        msg: `unhandled-rejection: ${reason?.message || String(reason)}`,
      })
      if (ring.length > RING_SIZE) ring.shift()
    } catch { /* swallow */ }
  })
}

function _redact(s) {
  if (typeof s !== 'string') return s
  // Likely API keys / tokens
  return s
    .replace(/sk-[A-Za-z0-9_-]{8,}/g, 'sk-***REDACTED***')
    .replace(/Bearer\s+[A-Za-z0-9._-]{8,}/gi, 'Bearer ***REDACTED***')
    .replace(/\/Users\/[^/\s"]+/g, '/Users/***')
    .replace(/\/home\/[^/\s"]+/g, '/home/***')
    .replace(/C:\\Users\\[^\\]+/g, 'C:\\Users\\***')
}

function _redactObject(obj, depth = 0) {
  if (depth > 4 || obj === null || obj === undefined) return obj
  if (typeof obj === 'string') return _redact(obj)
  if (Array.isArray(obj)) return obj.map((v) => _redactObject(v, depth + 1))
  if (typeof obj === 'object') {
    const out = {}
    for (const k of Object.keys(obj)) {
      const lower = String(k).toLowerCase()
      if (lower.includes('api_key') || lower.includes('apikey') || lower.includes('secret') || lower === 'key' || lower === 'password') {
        out[k] = obj[k] ? '***REDACTED***' : obj[k]
      } else {
        out[k] = _redactObject(obj[k], depth + 1)
      }
    }
    return out
  }
  return obj
}

async function _safe(name, fn) {
  try { return { [name]: await fn() } } catch (e) { return { [name]: { error: String(e?.message || e) } } }
}

/**
 * Collect everything diagnostics-worthy. Synchronously returns; async
 * fetches (settings, health) are awaited internally with short timeouts
 * so the report builds quickly even if the backend is wedged.
 */
export async function collectDiagnostics() {
  const tauri = isTauri()
  const ua = (navigator && navigator.userAgent) || ''
  const env = {
    tauri,
    user_agent: ua,
    platform: navigator?.platform || '',
    languages: navigator?.languages || [],
    online: navigator?.onLine,
    viewport: typeof window !== 'undefined' ? { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio } : null,
    location: typeof window !== 'undefined' ? window.location.origin : null,
    tauri_internals_present: typeof window?.__TAURI_INTERNALS__ !== 'undefined',
    tauri_v1_globals_present: typeof window?.__TAURI__ !== 'undefined',
  }

  const fetchJson = async (url, ms = 2500) => {
    const ctl = new AbortController()
    const t = setTimeout(() => ctl.abort(), ms)
    try {
      const r = await fetch(url, { signal: ctl.signal, credentials: 'include' })
      const ct = r.headers.get('content-type') || ''
      const body = ct.includes('json') ? await r.json() : (await r.text()).slice(0, 4000)
      return { status: r.status, body: _redactObject(body) }
    } finally {
      clearTimeout(t)
    }
  }

  const backend = (await _safe('backend', async () => {
    const [health, version, settings] = await Promise.all([
      fetchJson('/api/health').catch((e) => ({ error: String(e?.message || e) })),
      fetchJson('/api/version').catch((e) => ({ error: String(e?.message || e) })),
      fetchJson('/api/settings').catch((e) => ({ error: String(e?.message || e) })),
    ])
    return { health, version, settings }
  })).backend

  // Try to probe whether the shell plugin's open command works.
  let shell_open_probe = null
  if (tauri) {
    try {
      if (window.__TAURI_INTERNALS__?.invoke) {
        await window.__TAURI_INTERNALS__.invoke('plugin:shell|open', { path: 'about:blank' })
        shell_open_probe = 'invoked-without-error'
      } else {
        shell_open_probe = 'no-internals-bridge'
      }
    } catch (e) {
      shell_open_probe = `error: ${String(e?.message || e)}`.slice(0, 300)
    }
  }

  return {
    generated_at: new Date().toISOString(),
    env,
    backend,
    shell_open_probe,
    recent_console: ring.slice(-RING_SIZE).map((r) => ({ ...r, msg: _redact(r.msg) })),
  }
}

export function diagnosticsToText(report) {
  return JSON.stringify(report, null, 2)
}
