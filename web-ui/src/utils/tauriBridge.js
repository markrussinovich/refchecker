/**
 * Thin bridge for code that runs both in a normal browser (dev) and inside
 * the Tauri WebView (desktop app). Tauri 2.x doesn't follow target="_blank"
 * to the system browser by default — link clicks just no-op inside the
 * WebView — so we intercept them globally and route through the shell
 * plugin's open() API.
 */

export function isTauri() {
  if (typeof window === 'undefined') return false
  return (
    typeof window.__TAURI_INTERNALS__ !== 'undefined' ||
    typeof window.__TAURI__ !== 'undefined'
  )
}

/**
 * Open a URL in the user's default browser. Falls back to window.open in
 * non-Tauri contexts so dev mode keeps working.
 */
export async function openExternal(url) {
  if (!url) return
  if (isTauri()) {
    try {
      // Tauri 2.x exposes the shell plugin via __TAURI_INTERNALS__.invoke.
      if (window.__TAURI_INTERNALS__?.invoke) {
        await window.__TAURI_INTERNALS__.invoke('plugin:shell|open', { path: url })
        return
      }
      // Older Tauri 1.x shape, retained for safety.
      if (window.__TAURI__?.shell?.open) {
        await window.__TAURI__.shell.open(url)
        return
      }
    } catch (err) {
      console.warn('[tauriBridge] shell.open failed, falling back to window.open', err)
    }
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

/**
 * Read the bundled app version (from tauri.conf.json → version, which
 * itself reads from tauri-app/package.json). Returns null outside of
 * Tauri so the Settings UI can fall back to the backend's CLI version.
 */
export async function getAppVersion() {
  if (!isTauri()) return null
  try {
    if (window.__TAURI_INTERNALS__?.invoke) {
      return await window.__TAURI_INTERNALS__.invoke('plugin:app|version')
    }
  } catch (e) {
    console.warn('[tauriBridge] plugin:app|version failed', e)
  }
  return null
}

/**
 * Invoke a Rust-side Tauri command. Returns `null` outside of Tauri so
 * callers can render a graceful fallback in plain-browser dev mode.
 */
export async function invokeTauri(cmd, payload) {
  if (!isTauri()) return null
  try {
    if (window.__TAURI_INTERNALS__?.invoke) {
      return await window.__TAURI_INTERNALS__.invoke(cmd, payload || {})
    }
    if (window.__TAURI__?.invoke) {
      return await window.__TAURI__.invoke(cmd, payload || {})
    }
  } catch (err) {
    console.warn(`[tauriBridge] invoke ${cmd} failed`, err)
    throw err
  }
  return null
}

/**
 * Install a single capture-phase click handler that turns every
 *   <a href="https://..."> (and mailto:, file:) into shell.open.
 *
 * Idempotent — calling it twice does not double-install.
 */
let _installed = false
export function installLinkHandler() {
  if (_installed || typeof document === 'undefined') return
  _installed = true

  document.addEventListener(
    'click',
    (e) => {
      // Respect modifier-clicks (copy-link, open-in-new-tab from devtools)
      if (e.defaultPrevented || e.button !== 0) return

      const link = e.target?.closest?.('a[href]')
      if (!link) return

      const href = link.getAttribute('href')
      if (!href) return

      // Internal SPA routes / anchors are left alone.
      if (href.startsWith('#') || href.startsWith('/')) return
      if (!/^(https?:|mailto:|file:)/i.test(href)) return

      // In a normal browser, only intercept target="_blank" so we don't
      // hijack same-tab navigations. In Tauri, intercept everything
      // external because the WebView won't navigate to https://... anyway.
      const target = link.getAttribute('target')
      if (!isTauri() && target !== '_blank') return

      e.preventDefault()
      openExternal(href)
    },
    true,
  )
}
