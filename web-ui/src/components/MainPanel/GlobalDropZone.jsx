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

const SUPPORTED_EXTS = ['.pdf', '.bib', '.bbl', '.tex', '.txt']

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
    : lower.endsWith('.tex') ? 'application/x-tex'
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

  // Tauri Open-With → file path event
  useEffect(() => {
    if (!isTauri()) return
    let unlisten = null
    const onEvent = async (event) => {
      const payload = event?.payload
      if (!Array.isArray(payload) || payload.length === 0) return
      // Take the first path that resolves successfully; surface failures
      // in the console (and via the diagnostics ring buffer).
      for (const p of payload) {
        try {
          const file = await tauriPathToFile(p)
          broadcastFile(file, p)
          break
        } catch (e) {
          console.warn('[GlobalDropZone] failed to read open-with path', p, e)
        }
      }
    }
    ;(async () => {
      try {
        // Tauri 2.x v1-style listener via internals
        if (window.__TAURI_INTERNALS__?.invoke) {
          const eventName = 'refchecker://open-files'
          // Use the event plugin's listen command. plugin:event|listen
          // returns a handler id; unlisten via plugin:event|unlisten.
          const handlerId = await window.__TAURI_INTERNALS__.invoke('plugin:event|listen', {
            event: eventName,
            target: { kind: 'Any' },
            handler: (...args) => { /* unused — events arrive via __TAURI_EVENT__ */ },
          }).catch(() => null)

          // Fallback: subscribe to the global event window dispatches.
          window.addEventListener('tauri://event', (e) => {
            if (e.detail?.event === eventName) onEvent({ payload: e.detail.payload })
          })
          unlisten = () => {
            if (handlerId != null && window.__TAURI_INTERNALS__?.invoke) {
              window.__TAURI_INTERNALS__.invoke('plugin:event|unlisten', { event: eventName, eventId: handlerId }).catch(() => {})
            }
          }
        }
      } catch (e) {
        console.warn('[GlobalDropZone] Tauri event listener install failed', e)
      }
    })()
    return () => { if (unlisten) unlisten() }
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
          PDF · BibTeX (.bib / .bbl) · LaTeX (.tex) · plain text
        </div>
      </div>
    </div>
  )
}
