import { useEffect, useState } from 'react'
import { isTauri } from '../../utils/tauriBridge'

/**
 * Full-window drag-drop overlay.
 *
 *   - Listens to document-level dragenter/dragover/dragleave/drop so the
 *     user can drop a PDF / BibTeX / LaTeX / text file anywhere on the
 *     window (not just over the dedicated FileDropZone).
 *   - Also listens to Tauri's `refchecker://open-files` event, which the
 *     Rust side fires when the OS hands us a file via "Open With →
 *     RefChecker" or via launch argv. For those, the payload is a list
 *     of absolute paths; we read each one through the fs plugin and
 *     turn it into a real File so the rest of the pipeline doesn't
 *     care which path it came in on.
 *   - Once a File is in hand, dispatches `refchecker:open-file` as a
 *     custom DOM event. InputSection listens for that and pushes it
 *     into the existing check-submit flow.
 *
 * Designed so the web-ui still works outside Tauri (Docker / pip):
 * the HTML5 drop handlers run unconditionally; the Tauri event listener
 * only fires when invoke is available.
 */

const SUPPORTED_EXTS = [
  '.pdf', '.bib', '.bbl', '.tex', '.latex', '.txt',
  '.docx', '.odt', '.rtf', '.md', '.markdown', '.html', '.htm',
]

function looksLikeAcceptedFile(name) {
  if (!name) return false
  const lower = name.toLowerCase()
  return SUPPORTED_EXTS.some((ext) => lower.endsWith(ext))
}

function broadcastFile(file, sourceLabel) {
  if (!file) return
  window.dispatchEvent(new CustomEvent('refchecker:open-file', {
    detail: { file, sourceLabel: sourceLabel || file.name },
  }))
}

async function tauriPathToFile(path) {
  // Read raw bytes through our custom Rust command FIRST — it bypasses
  // the fs plugin's capability ACL, which silently rejects paths
  // outside the configured scopes ($HOME, $DOWNLOAD, etc.) and was a
  // suspected silent failure mode for drag-drop. Drag-drop hands us
  // an OS-validated absolute path; the user explicitly chose to drop
  // it, so we trust it.
  if (!isTauri() || !window.__TAURI_INTERNALS__?.invoke) {
    throw new Error('Tauri bridge unavailable')
  }
  let bytes
  try {
    bytes = await window.__TAURI_INTERNALS__.invoke('read_dropped_file', { path })
  } catch (e) {
    // Fall back to the fs plugin if the custom command isn't available
    // (older build or registration glitch). Logs the failure so we can
    // see which path the read came through.
    console.warn('[GlobalDropZone] read_dropped_file failed, falling back to plugin:fs|read_file', e)
    bytes = await window.__TAURI_INTERNALS__.invoke('plugin:fs|read_file', { path })
  }
  // The bridge returns a Uint8Array or an array of numbers depending on
  // serializer; normalize both.
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
  const filename = path.split(/[\\/]/).pop() || 'opened-file'
  const lower = filename.toLowerCase()
  const mime = lower.endsWith('.pdf') ? 'application/pdf'
    : lower.endsWith('.bib') || lower.endsWith('.bbl') ? 'application/x-bibtex'
    : lower.endsWith('.tex') || lower.endsWith('.latex') ? 'application/x-tex'
    : lower.endsWith('.docx') ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    : lower.endsWith('.odt') ? 'application/vnd.oasis.opendocument.text'
    : lower.endsWith('.rtf') ? 'application/rtf'
    : lower.endsWith('.html') || lower.endsWith('.htm') ? 'text/html'
    : lower.endsWith('.md') || lower.endsWith('.markdown') ? 'text/markdown'
    : 'text/plain'
  return new File([u8], filename, { type: mime })
}

export default function GlobalDropZone() {
  const [active, setActive] = useState(false)
  const [counter, setCounter] = useState(0) // nested dragenter/leave counter

  // v0.7.38: split HTML5 drag handling by runtime mode.
  //
  // In Tauri (`dragDropEnabled: true`), calling preventDefault on the
  // JS-side `dragover` / `drop` events appears to cancel the OS-level
  // drop on macOS WKWebView before Tauri's native handler can fire.
  // The user reported the overlay banner showing up but the file
  // never being captured — classic symptom of the WebKit handler
  // consuming the event ahead of the NSWindow registration. In Tauri
  // we now ONLY listen to `dragenter` / `dragleave` for the visual
  // overlay, with no preventDefault and no drop handler — drops are
  // exclusively delivered by the Rust `WindowEvent::DragDrop::Drop`
  // handler which re-emits via `refchecker://open-files`.
  //
  // Outside Tauri (Docker / pip web UI) the browser needs the full
  // HTML5 dance to accept drops, so we keep the preventDefault path.
  useEffect(() => {
    const inTauri = isTauri()

    const handleDragEnter = (e) => {
      if (!inTauri) e.preventDefault()
      setCounter((c) => c + 1)
      setActive(true)
    }
    const handleDragLeave = (e) => {
      if (!inTauri) e.preventDefault()
      setCounter((c) => {
        const next = Math.max(0, c - 1)
        if (next === 0) setActive(false)
        return next
      })
    }

    document.addEventListener('dragenter', handleDragEnter)
    document.addEventListener('dragleave', handleDragLeave)

    if (!inTauri) {
      const handleDragOver = (e) => {
        e.preventDefault()
        try { e.dataTransfer.dropEffect = 'copy' } catch { /* read-only on some webviews */ }
      }
      const handleDrop = (e) => {
        e.preventDefault()
        setCounter(0)
        setActive(false)
        const files = Array.from(e.dataTransfer?.files || [])
        if (files.length === 0) return
        const usable = files.find((f) => looksLikeAcceptedFile(f.name)) || files[0]
        broadcastFile(usable)
      }
      document.addEventListener('dragover', handleDragOver)
      document.addEventListener('drop', handleDrop)
      return () => {
        document.removeEventListener('dragenter', handleDragEnter)
        document.removeEventListener('dragleave', handleDragLeave)
        document.removeEventListener('dragover', handleDragOver)
        document.removeEventListener('drop', handleDrop)
      }
    }
    return () => {
      document.removeEventListener('dragenter', handleDragEnter)
      document.removeEventListener('dragleave', handleDragLeave)
    }
  }, [])

  // Tauri-side events: both Open-With (refchecker://open-files) and
  // Tauri's own drag-drop events. With dragDropEnabled=true in
  // tauri.conf.json the OS file-drop is intercepted by Tauri and
  // surfaced as tauri://drag-enter / tauri://drag-over / tauri://drop /
  // tauri://drag-leave — the HTML5 onDrop won't fire, so we have to
  // hook these explicitly instead of relying on the document listeners
  // above.
  useEffect(() => {
    console.info('[GlobalDropZone] mount diagnostic — isTauri=', isTauri(),
      ' TAURI_INTERNALS=', !!window.__TAURI_INTERNALS__)
    if (!isTauri()) return
    if (!window.__TAURI_INTERNALS__) return
    const cleanupFns = []

    const consumePaths = async (paths, source) => {
      console.info(`[GlobalDropZone] consumePaths(${source}) called with`,
        Array.isArray(paths) ? paths.length : '(not-array)', 'paths:', paths)
      if (!Array.isArray(paths) || paths.length === 0) return
      const usable = paths.find((p) => looksLikeAcceptedFile(p)) || paths[0]
      try {
        const file = await tauriPathToFile(usable)
        console.info(`[GlobalDropZone] tauriPathToFile OK — broadcasting`, usable, file.size, 'bytes')
        broadcastFile(file, usable)
      } catch (e) {
        console.warn(`[GlobalDropZone] failed to read ${source} path`, usable, e)
      }
    }

    // Subscribe via the dynamic import of @tauri-apps/api so we get
    // reliable unlisten handles.
    let unlistenFns = []
    ;(async () => {
      try {
        const ev = await import('@tauri-apps/api/event')
        // Open-With from the OS / file-association launch — global event.
        // ALSO the channel the Rust-side drag-drop handler re-emits to,
        // so this listener is on the critical path for both flows.
        if (ev?.listen) {
          console.info('[GlobalDropZone] subscribing to refchecker://open-files')
          unlistenFns.push(await ev.listen('refchecker://open-files', (event) => {
            console.info('[GlobalDropZone] refchecker://open-files event received',
              event?.payload?.length || 0, 'path(s):', event?.payload)
            consumePaths(event?.payload || [], 'open-with')
          }))
        } else {
          console.warn('[GlobalDropZone] ev.listen unavailable')
        }
      } catch (e) {
        console.warn('[GlobalDropZone] @tauri-apps/api/event load failed', e)
      }

      // Native drag-drop in Tauri 2 is delivered through TWO channels
      // — `getCurrentWebview().onDragDropEvent` AND
      // `getCurrentWindow().onDragDropEvent`. On macOS WKWebView the
      // event often fires through the WINDOW path, not the webview.
      // Earlier versions only subscribed to the webview path, which
      // explained why drops appeared to do nothing on macOS even with
      // dragDropEnabled=true. v0.7.31 subscribes to both — duplicate
      // fires are idempotent because consumePaths is dedup-by-path
      // internally and setActive/setCounter are setters.
      const handlePayload = (payload, source) => {
        if (!payload || typeof payload !== 'object') return
        if (payload.type === 'enter' || payload.type === 'over') {
          setActive(true)
          return
        }
        if (payload.type === 'drop') {
          console.info(`[GlobalDropZone] ${source} drop fired with ${payload.paths?.length || 0} paths`)
          consumePaths(payload.paths || [], source)
          setActive(false); setCounter(0)
          return
        }
        if (payload.type === 'leave') {
          setActive(false); setCounter(0)
        }
      }
      try {
        const wv = await import('@tauri-apps/api/webview')
        const webview = wv?.getCurrentWebview?.()
        if (webview?.onDragDropEvent) {
          unlistenFns.push(await webview.onDragDropEvent((event) =>
            handlePayload(event?.payload, 'webview-drag-drop')
          ))
        }
      } catch (e) {
        console.warn('[GlobalDropZone] webview drag-drop subscribe failed', e)
      }
      try {
        const win = await import('@tauri-apps/api/window')
        const window_ = win?.getCurrentWindow?.()
        if (window_?.onDragDropEvent) {
          unlistenFns.push(await window_.onDragDropEvent((event) =>
            handlePayload(event?.payload, 'window-drag-drop')
          ))
        }
      } catch (e) {
        console.warn('[GlobalDropZone] window drag-drop subscribe failed', e)
      }

      // Belt-and-braces: some Tauri builds DO surface drag events on
      // the global bus. Subscribe to those too — duplicate fires are
      // idempotent because consumePaths is dedup-by-path internally and
      // setActive/setCounter are setters.
      try {
        const ev = await import('@tauri-apps/api/event')
        if (!ev?.listen) return
        const dropHandler = (event) => {
          const payload = event?.payload
          if (payload && typeof payload === 'object' && payload.type === 'drop') {
            consumePaths(payload.paths || [], 'drag-drop')
            setActive(false); setCounter(0)
            return
          }
          if (payload && typeof payload === 'object' && (payload.type === 'enter' || payload.type === 'over')) {
            setActive(true)
            return
          }
          if (payload && typeof payload === 'object' && payload.type === 'leave') {
            setActive(false); setCounter(0)
            return
          }
          if (Array.isArray(payload)) {
            consumePaths(payload, 'drag-drop')
            setActive(false); setCounter(0)
          }
        }
        unlistenFns.push(await ev.listen('tauri://drag-drop', dropHandler))
        unlistenFns.push(await ev.listen('tauri://drop', dropHandler))
        unlistenFns.push(await ev.listen('tauri://file-drop', dropHandler))  // legacy
        unlistenFns.push(await ev.listen('tauri://drag-enter', () => setActive(true)))
        unlistenFns.push(await ev.listen('tauri://drag-leave', () => { setActive(false); setCounter(0) }))
      } catch (e) {
        console.warn('[GlobalDropZone] global drag-drop subscribe failed', e)
      }
    })()
    cleanupFns.push(() => unlistenFns.forEach((fn) => { try { fn?.() } catch { /* ignore */ } }))

    return () => cleanupFns.forEach((fn) => fn())
  }, [])

  if (!active) return null

  const inTauri = isTauri()

  // Overlay-as-drop-target — ONLY when running outside Tauri. In
  // Tauri the overlay is visual-only (pointer-events: none) so the
  // NSWindow drag-drop handler isn't blocked by the WebKit overlay
  // capturing the drop ahead of it. The user reported the banner
  // appearing but the drop never being captured; the fix is to let
  // the native handler own the drop entirely in desktop mode.
  const overlayDragOver = (e) => {
    if (inTauri) return
    e.preventDefault()
    try { e.dataTransfer.dropEffect = 'copy' } catch { /* read-only on some webviews */ }
  }
  const overlayDrop = (e) => {
    if (inTauri) return
    e.preventDefault()
    e.stopPropagation()
    setCounter(0)
    setActive(false)
    const files = Array.from(e.dataTransfer?.files || [])
    if (files.length === 0) return
    const usable = files.find((f) => looksLikeAcceptedFile(f.name)) || files[0]
    broadcastFile(usable)
  }

  return (
    <div
      onDragOver={overlayDragOver}
      onDrop={overlayDrop}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        backgroundColor: 'rgba(59, 130, 246, 0.12)',
        backdropFilter: 'blur(2px)',
        border: '3px dashed var(--color-accent, #3b82f6)',
        // In Tauri, click-through so the native NSWindow drag-drop
        // handler receives the drop, not the WebKit overlay. In web
        // mode keep pointer-events:auto so the overlay catches drops
        // that land on areas not covered by FileDropZone.
        pointerEvents: inTauri ? 'none' : 'auto',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'copy',
      }}
    >
      <div
        style={{
          padding: '24px 32px',
          borderRadius: 16,
          backgroundColor: 'var(--color-bg-primary)',
          color: 'var(--color-text-primary)',
          border: '1px solid var(--color-border)',
          boxShadow: '0 20px 40px rgba(0,0,0,0.2)',
          textAlign: 'center',
          pointerEvents: 'none',  // keep the card click-through, the wrapper owns the drop
        }}
      >
        <div style={{ fontSize: 36, marginBottom: 8 }}>📎</div>
        <div style={{ fontSize: 18, fontWeight: 600 }}>Drop a paper to verify</div>
        <div style={{ fontSize: 12, marginTop: 4, color: 'var(--color-text-secondary)' }}>
          PDF · DOCX · ODT · RTF · BibTeX (.bib / .bbl) · LaTeX (.tex) · Markdown · HTML · plain text
        </div>
      </div>
    </div>
  )
}
