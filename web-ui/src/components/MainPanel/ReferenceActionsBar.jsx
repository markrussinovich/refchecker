import { openExternal } from '../../utils/tauriBridge'
import { useStyleStore } from '../../stores/useStyleStore'
import {
  CITATION_STYLE_DEFAULTS,
  CITATION_STYLES,
  exportReferenceAsStyle,
} from '../../utils/formatters'

export function AddReferencePanel({ newRef, setNewRef, busyKey, onSave, onCancel }) {
  const disabled = busyKey === '__add__'
  return (
    <div
      className="px-4 py-3 border-t text-sm"
      style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-tertiary)' }}
    >
      <div className="grid grid-cols-2 gap-2">
        <input
          className="px-2 py-1 rounded border"
          placeholder="Title"
          value={newRef.title}
          onChange={e => setNewRef({ ...newRef, title: e.target.value })}
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary)' }}
        />
        <input
          className="px-2 py-1 rounded border"
          placeholder="Authors (comma-separated)"
          value={newRef.authors}
          onChange={e => setNewRef({ ...newRef, authors: e.target.value })}
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary)' }}
        />
        <input
          className="px-2 py-1 rounded border"
          placeholder="Year"
          value={newRef.year}
          onChange={e => setNewRef({ ...newRef, year: e.target.value })}
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary)' }}
        />
        <input
          className="px-2 py-1 rounded border"
          placeholder="DOI"
          value={newRef.doi}
          onChange={e => setNewRef({ ...newRef, doi: e.target.value })}
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary)' }}
        />
        <input
          className="px-2 py-1 rounded border col-span-2"
          placeholder="arXiv ID (e.g. 2401.12345)"
          value={newRef.arxiv_id}
          onChange={e => setNewRef({ ...newRef, arxiv_id: e.target.value })}
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary)' }}
        />
      </div>
      <div className="mt-2 flex gap-2 justify-end">
        <button
          onClick={onCancel}
          className="px-3 py-1 rounded text-sm"
          style={{ borderColor: 'var(--color-border)', border: '1px solid' }}
        >
          Cancel
        </button>
        <button
          onClick={onSave}
          disabled={disabled}
          className="px-3 py-1 rounded text-sm"
          style={{ background: 'var(--color-accent)', color: '#fff', opacity: disabled ? 0.6 : 1 }}
        >
          {disabled ? 'Adding…' : 'Add reference'}
        </button>
      </div>
    </div>
  )
}

export function SuggestAltPanel({ suggestFor, onClose }) {
  // Render suggestions in the user's currently-selected citation style so
  // the candidates can be copied straight into the bibliography without
  // any further formatting work.
  const format = useStyleStore(s => s.format)
  const styleOptions = useStyleStore(s => s.styleOptions)
  if (!suggestFor) return null
  const styleLabel = CITATION_STYLES.find(s => s.id === format)?.label || (format.startsWith('custom:') ? 'Custom' : format)
  const effectiveOpts = {
    ...(CITATION_STYLE_DEFAULTS[format] || {}),
    ...(styleOptions || {}),
  }
  const renderInStyle = (c, i) => {
    try {
      return exportReferenceAsStyle(c, format, i, effectiveOpts)
    } catch {
      return c.title || ''
    }
  }
  const copyToClipboard = async (text) => {
    try { await navigator.clipboard.writeText(text) } catch { /* ignore */ }
  }
  return (
    <div
      className="px-4 py-3 border-t text-sm"
      style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-tertiary)' }}
    >
      <div className="flex items-center justify-between mb-2">
        <strong>Suggested alternatives for ref {suggestFor.ref_id}</strong>
        <div className="flex items-center gap-2">
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            rendered as {styleLabel}
          </span>
          <button
            onClick={onClose}
            className="text-xs px-2 py-0.5 rounded border"
            style={{ borderColor: 'var(--color-border)' }}
          >
            Close
          </button>
        </div>
      </div>
      {(!suggestFor.candidates || suggestFor.candidates.length === 0) ? (
        <div style={{ color: 'var(--color-text-muted)' }}>No alternatives found.</div>
      ) : (
        <ul className="space-y-2">
          {suggestFor.candidates.map((c, i) => {
            const styled = renderInStyle(c, i)
            return (
              <li
                key={i}
                className="flex flex-col gap-1 rounded-md p-2"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div
                    className="flex-1 min-w-0"
                    style={{
                      color: 'var(--color-text-primary)',
                      fontFamily: format === 'bibtex' || format === 'bibitem' ? 'ui-monospace, monospace' : undefined,
                      fontSize: format === 'bibtex' || format === 'bibitem' ? '0.78rem' : undefined,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    }}
                  >
                    {styled}
                  </div>
                  <button
                    onClick={() => copyToClipboard(styled)}
                    className="text-xs px-2 py-0.5 rounded flex-shrink-0"
                    style={{
                      border: '1px solid var(--color-border)',
                      background: 'var(--color-bg-primary)',
                      color: 'var(--color-text-secondary)',
                    }}
                    title="Copy this citation"
                  >
                    Copy
                  </button>
                </div>
                <div className="flex items-center gap-2 flex-wrap text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  {c.source && (
                    <span
                      className="px-1.5 py-0.5 rounded"
                      style={{
                        background: 'var(--color-bg-tertiary)',
                        border: '1px solid var(--color-border)',
                      }}
                    >
                      {c.source === 'llm' ? 'LLM' : c.source === 'semantic_scholar' ? 'S2' : c.source}
                    </span>
                  )}
                  {typeof c.overlap === 'number' && c.overlap > 0 && (
                    <span
                      className="px-1.5 py-0.5 rounded"
                      style={{
                        background: 'rgba(34,197,94,0.12)',
                        color: 'var(--color-success, #16a34a)',
                        border: '1px solid rgba(34,197,94,0.35)',
                      }}
                      title="Shares N other references with this paper's bibliography (co-citation overlap)"
                    >
                      shares {c.overlap} ref{c.overlap === 1 ? '' : 's'}
                      {c.overlap_winner ? ' · best match' : ''}
                    </span>
                  )}
                  {c.url && (
                    <a
                      href={c.url}
                      onClick={e => { e.preventDefault(); openExternal(c.url) }}
                      style={{ color: 'var(--color-accent)' }}
                    >
                      {c.url.length > 80 ? `${c.url.slice(0, 80)}…` : c.url}
                    </a>
                  )}
                </div>
                {c.reason && (
                  <div style={{ color: 'var(--color-text-muted)', fontSize: '0.8em', fontStyle: 'italic' }}>
                    {c.reason}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export function ReferenceRowActions({ reference, displayIndex, busyKey, onSuggest, onRemove, onReverify, selectedCheckId }) {
  const ident = String(reference.id ?? reference.index ?? displayIndex)
  const busy = busyKey === ident
  const disabled = busy || !selectedCheckId
  // Match Settings panel button styling — pill, subtle border, hover lift.
  const baseStyle = {
    border: '1px solid var(--color-border)',
    background: 'var(--color-bg-primary)',
    color: 'var(--color-text-secondary)',
    opacity: disabled ? 0.55 : 1,
    transition: 'background 120ms ease, color 120ms ease, border-color 120ms ease',
  }
  return (
    <div className="px-4 pb-3 pt-1 flex flex-wrap gap-1.5 text-xs">
      <button
        onClick={() => onReverify(reference, displayIndex)}
        disabled={disabled}
        className="px-2.5 py-1 rounded-md font-medium"
        style={baseStyle}
        title="Re-verify this reference now"
      >
        {busy ? '…' : 'Re-verify'}
      </button>
      <button
        onClick={() => onSuggest(reference, displayIndex)}
        disabled={disabled}
        className="px-2.5 py-1 rounded-md font-medium"
        style={baseStyle}
        title="Suggest a real paper the author might have meant"
      >
        Suggest alternative
      </button>
      <button
        onClick={() => onRemove(reference, displayIndex)}
        disabled={disabled}
        className="px-2.5 py-1 rounded-md font-medium"
        style={{
          ...baseStyle,
          color: 'var(--color-error, #ef4444)',
          borderColor: 'var(--color-error, #ef4444)55',
        }}
        title="Remove this reference from the check"
      >
        Remove
      </button>
    </div>
  )
}
