import { openExternal } from '../../utils/tauriBridge'

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
  if (!suggestFor) return null
  return (
    <div
      className="px-4 py-3 border-t text-sm"
      style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-tertiary)' }}
    >
      <div className="flex items-center justify-between mb-2">
        <strong>Suggested alternatives for ref {suggestFor.ref_id}</strong>
        <button
          onClick={onClose}
          className="text-xs px-2 py-0.5 rounded border"
          style={{ borderColor: 'var(--color-border)' }}
        >
          Close
        </button>
      </div>
      {(!suggestFor.candidates || suggestFor.candidates.length === 0) ? (
        <div style={{ color: 'var(--color-text-muted)' }}>No alternatives found.</div>
      ) : (
        <ul className="space-y-2">
          {suggestFor.candidates.map((c, i) => (
            <li key={i} className="flex flex-col gap-0.5">
              <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                {c.title || c.name || 'Untitled'} {c.year ? `(${c.year})` : ''}
              </div>
              <div style={{ color: 'var(--color-text-muted)', fontSize: '0.85em' }}>
                {Array.isArray(c.authors) ? c.authors.slice(0, 5).join(', ') : (c.authors || '')}
                {c.venue ? ` · ${c.venue}` : ''}
                {c.source ? ` · ${c.source}` : ''}
              </div>
              {c.url && (
                <a
                  href={c.url}
                  onClick={e => { e.preventDefault(); openExternal(c.url) }}
                  style={{ color: 'var(--color-accent)', fontSize: '0.85em' }}
                >
                  {c.url}
                </a>
              )}
              {c.reason && (
                <div style={{ color: 'var(--color-text-muted)', fontSize: '0.8em', fontStyle: 'italic' }}>
                  {c.reason}
                </div>
              )}
            </li>
          ))}
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
