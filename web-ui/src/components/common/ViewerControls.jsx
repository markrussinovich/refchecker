/**
 * Shared zoom + find controls for the document viewers (the AI-detection
 * flagged-text viewer and the PDF page thumbnail viewer). Pure presentational
 * — the parent owns the zoom level / find query state and the match list.
 */

const iconBtn = {
  width: 28, height: 28, display: 'inline-flex', alignItems: 'center',
  justifyContent: 'center', borderRadius: 6, cursor: 'pointer',
}

export function ZoomControls({ zoom, onZoomIn, onZoomOut, onReset, min = 0.5, max = 3, dark = false }) {
  const fg = dark ? '#fff' : 'var(--color-text-primary)'
  const border = dark ? 'rgba(255,255,255,0.25)' : 'var(--color-border)'
  const bg = dark ? 'rgba(255,255,255,0.12)' : 'var(--color-bg-secondary)'
  const btn = { ...iconBtn, color: fg, background: bg, border: `1px solid ${border}` }
  return (
    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
      <button type="button" style={{ ...btn, opacity: zoom <= min ? 0.4 : 1 }}
        disabled={zoom <= min} onClick={onZoomOut} title="Zoom out (−)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="5" y1="12" x2="19" y2="12" /></svg>
      </button>
      <button type="button" onClick={onReset} title="Reset zoom / fit"
        style={{ minWidth: 46, height: 28, borderRadius: 6, cursor: 'pointer', fontSize: 12,
                 color: fg, background: bg, border: `1px solid ${border}` }}>
        {Math.round(zoom * 100)}%
      </button>
      <button type="button" style={{ ...btn, opacity: zoom >= max ? 0.4 : 1 }}
        disabled={zoom >= max} onClick={onZoomIn} title="Zoom in (+)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
      </button>
    </div>
  )
}

export function FindBar({ value, onChange, matchCount, currentMatch, onPrev, onNext, onClose, inputRef }) {
  return (
    <div className="flex items-center gap-1 px-1.5 py-1 rounded-md"
      onClick={(e) => e.stopPropagation()}
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--color-text-muted)" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); e.shiftKey ? onPrev?.() : onNext?.() }
          else if (e.key === 'Escape') { e.preventDefault(); onClose?.() }
        }}
        placeholder="Find in document"
        className="text-xs outline-none"
        style={{ width: 150, background: 'transparent', color: 'var(--color-text-primary)' }}
      />
      <span className="text-xs tabular-nums px-1" style={{ color: 'var(--color-text-muted)', minWidth: 48, textAlign: 'right' }}>
        {value ? (matchCount > 0 ? `${currentMatch + 1}/${matchCount}` : '0/0') : ''}
      </span>
      <button type="button" onClick={onPrev} disabled={!matchCount} title="Previous (Shift+Enter)"
        style={{ ...iconBtn, color: 'var(--color-text-primary)', opacity: matchCount ? 1 : 0.4 }}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="18 15 12 9 6 15" /></svg>
      </button>
      <button type="button" onClick={onNext} disabled={!matchCount} title="Next (Enter)"
        style={{ ...iconBtn, color: 'var(--color-text-primary)', opacity: matchCount ? 1 : 0.4 }}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="6 9 12 15 18 9" /></svg>
      </button>
      <button type="button" onClick={onClose} title="Close (Esc)"
        style={{ ...iconBtn, color: 'var(--color-text-muted)' }}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
      </button>
    </div>
  )
}
