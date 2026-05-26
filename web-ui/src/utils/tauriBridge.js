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
    // Shell plugin first — it's a documented plugin permission with a
    // scope (^https?://.+ / mailto:.+ / tel:.+ / file://.+) declared
    // in capabilities/default.json. Works on every build without
    // needing an extra ACL grant for the custom `open_external`
    // command, which previously surfaced as "Command open_external
    // not allowed by ACL" on Tauri 2.x. We keep open_external as a
    // last-resort fallback in case the shell scope ever rejects a
    // legitimate URL.
    try {
      if (window.__TAURI_INTERNALS__?.invoke) {
        await window.__TAURI_INTERNALS__.invoke('plugin:shell|open', { path: url })
        return
      }
      if (window.__TAURI__?.shell?.open) {
        await window.__TAURI__.shell.open(url)
        return
      }
    } catch (err) {
      console.warn('[tauriBridge] shell.open failed, trying open_external', err)
    }
    try {
      if (window.__TAURI_INTERNALS__?.invoke) {
        await window.__TAURI_INTERNALS__.invoke('open_external', { url })
        return
      }
    } catch (err) {
      console.warn('[tauriBridge] open_external failed, falling back to window.open', err)
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

  const isExternalAnchor = (link) => {
    if (!link) return false
    const href = link.getAttribute('href') || ''
    return /^(https?:|mailto:|tel:|file:)/i.test(href)
  }

  // Left-click: route through shell.open
  document.addEventListener(
    'click',
    (e) => {
      if (e.defaultPrevented || e.button !== 0) return
      const link = e.target?.closest?.('a[href]')
      if (!link) return
      const href = link.getAttribute('href')
      if (!href) return
      if (href.startsWith('#') || href.startsWith('/')) return
      if (!isExternalAnchor(link)) return
      const target = link.getAttribute('target')
      if (!isTauri() && target !== '_blank') return
      e.preventDefault()
      openExternal(href)
    },
    true,
  )

  // Inside Tauri, WebKit's native right-click menu ("Open Link" / "Open
  // Link in New Window" / "Download Linked File") tries to navigate the
  // in-app WebView. Tauri's navigation policy silently blocks external
  // URLs, so the menu items appear to no-op. Block the menu entirely on
  // external anchors and treat the right-click as an open-in-system-
  // browser action.
  document.addEventListener(
    'contextmenu',
    (e) => {
      if (!isTauri()) return
      const link = e.target?.closest?.('a[href]')
      if (!link || !isExternalAnchor(link)) return
      e.preventDefault()
      const href = link.getAttribute('href')
      if (href) openExternal(href)
    },
    true,
  )

  // Middle-click ("open in new tab") also fires through auxclick.
  document.addEventListener(
    'auxclick',
    (e) => {
      if (e.button !== 1) return
      const link = e.target?.closest?.('a[href]')
      if (!link || !isExternalAnchor(link)) return
      e.preventDefault()
      const href = link.getAttribute('href')
      if (href) openExternal(href)
    },
    true,
  )
}
