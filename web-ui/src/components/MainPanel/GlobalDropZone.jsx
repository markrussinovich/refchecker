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
  // Read raw bytes via the fs plugin, then wrap as a File so the existing
  // FormData upload path doesn't need a special case.
  if (!isTauri() || !window.__TAURI_INTERNALS__?.invoke) {
    throw new Error('fs plugin unavailable')
  }
  const bytes = await window.__TAURI_INTERNALS__.invoke('plugin:fs|read_file', { path })
  // The fs plugin returns a Uint8Array (or array of numbers depending on
  // the bridge); normalize both.
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

  useEffect(() => {
    const handleDragEnter = (e) => {
      // Only show overlay when the drag carries files
      if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return
      e.preventDefault()
      setCounter((c) => c + 1)
      setActive(true)
    }
    const handleDragOver = (e) => {
      if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'copy'
    }
    const handleDragLeave = (e) => {
      e.preventDefault()
      setCounter((c) => {
        const next = Math.max(0, c - 1)
        if (next === 0) setActive(false)
        return next
      })
    }
    const handleDrop = (e) => {
      e.preventDefault()
      setCounter(0)
      setActive(false)
      const files = Array.from(e.dataTransfer?.files || [])
      if (files.length === 0) return
      // Single-file: route to single-paper check. Multi: feed the first
      // recognised file; the user can use bulk mode for batches.
      const usable = files.find((f) => looksLikeAcceptedFile(f.name)) || files[0]
      broadcastFile(usable)
    }

    document.addEventListener('dragenter', handleDragEnter)
    document.addEventListener('dragover', handleDragOver)
    document.addEventListener('dragleave', handleDragLeave)
    document.addEventListener('drop', handleDrop)
    return () => {
      document.removeEventListener('dragenter', handleDragEnter)
      document.removeEventListener('dragover', handleDragOver)
      document.removeEventListener('dragleave', handleDragLeave)
      document.removeEventListener('drop', handleDrop)
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
    if (!isTauri()) return
    if (!window.__TAURI_INTERNALS__) return
    const cleanupFns = []

    const consumePaths = async (paths, source) => {
      if (!Array.isArray(paths) || paths.length === 0) return
      const usable = paths.find((p) => looksLikeAcceptedFile(p)) || paths[0]
      try {
        const file = await tauriPathToFile(usable)
        broadcastFile(file, usable)
      } catch (e) {
        console.warn(`[GlobalDropZone] failed to read ${source} path`, usable, e)
      }
    }

    // Subscribe via the dynamic import of @tauri-apps/api/event so we
    // get reliable unlisten handles. Falls through to internals if the
    // package isn't bundled.
    let unlistenFns = []
    ;(async () => {
      try {
        const ev = await import('@tauri-apps/api/event')
        if (!ev?.listen) return
        // 1. Open-With from the OS / file-association launch
        unlistenFns.push(await ev.listen('refchecker://open-files', (event) => {
          consumePaths(event?.payload || [], 'open-with')
        }))
        // 2. File dragged onto the window (Tauri 2.x native drag-drop)
        // The event payload shape is { type: 'enter'|'over'|'drop'|'leave', paths: [...] }
        // on some Tauri builds; on others, the event NAMES split out as
        // tauri://drag-enter / drag-over / drop / drag-leave. Subscribe to
        // both shapes.
        const dropHandler = (event) => {
          const payload = event?.payload
          // Shape A: { type: 'drop', paths: [...] }
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
          // Shape B: payload is itself a list of paths (older Tauri builds)
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
        console.warn('[GlobalDropZone] Tauri event listener install failed', e)
      }
    })()
    cleanupFns.push(() => unlistenFns.forEach((fn) => { try { fn?.() } catch {} }))

    return () => cleanupFns.forEach((fn) => fn())
  }, [])

  if (!active) return null

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        backgroundColor: 'rgba(59, 130, 246, 0.12)',
        backdropFilter: 'blur(2px)',
        border: '3px dashed var(--color-accent, #3b82f6)',
        pointerEvents: 'none',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
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
