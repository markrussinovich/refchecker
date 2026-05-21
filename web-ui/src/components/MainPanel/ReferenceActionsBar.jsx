import { useState } from 'react'
import { openExternal } from '../../utils/tauriBridge'
import { useStyleStore } from '../../stores/useStyleStore'
import {
  CITATION_STYLE_DEFAULTS,
  CITATION_STYLES,
  exportReferenceAsStyle,
} from '../../utils/formatters'
import { resolveDoi } from '../../utils/api'

export function AddReferencePanel({ newRef, setNewRef, busyKey, onSave, onCancel }) {
  const disabled = busyKey === '__add__'
  // Two entry modes:
  //   'doi'    — paste a DOI, click Resolve, all fields auto-fill from CrossRef.
  //   'manual' — fill in title/authors/year/etc. by hand (the original form).
  // We default to 'doi' because that's the path the user explicitly asked
  // for ("Automated reference adding by only doi"); the manual form stays
  // available for cases where CrossRef doesn't have the paper.
  const [mode, setMode] = useState('doi')
  const [doiInput, setDoiInput] = useState(newRef.doi || '')
  const [resolving, setResolving] = useState(false)
  const [resolveError, setResolveError] = useState(null)
  const [resolved, setResolved] = useState(null) // { title, authors, year, venue }

  const handleResolve = async () => {
    const value = (doiInput || '').trim()
    if (!value) { setResolveError('Enter a DOI first'); return }
    setResolving(true); setResolveError(null); setResolved(null)
    try {
      const res = await resolveDoi(value)
      const meta = res?.data || {}
      const authorsText = Array.isArray(meta.authors) ? meta.authors.join(', ') : (meta.authors || '')
      setNewRef({
        ...newRef,
        title: meta.title || '',
        authors: authorsText,
        year: meta.year ? String(meta.year) : '',
        doi: meta.doi || value,
        arxiv_id: newRef.arxiv_id || '',
      })
      setResolved(meta)
    } catch (e) {
      setResolveError(e?.response?.data?.detail || e?.message || 'Resolution failed')
    } finally {
      setResolving(false)
    }
  }

  const handleAddAndResolve = async () => {
    // Convenience: if the user clicks Add reference with only a DOI typed
    // but never clicked Resolve, the backend will still fall back to
    // CrossRef inside the add endpoint — so just forward what we have.
    // setNewRef is async (React state batch), so we can't depend on
    // newRef.doi being updated by the time onSave reads it; pass the
    // typed DOI through onSave's override path instead. The parent's
    // handleAddRef accepts a patch and merges it over its closure of
    // newRef before building the request body.
    if (mode === 'doi' && doiInput && !newRef.doi) {
      const trimmed = doiInput.trim()
      setNewRef({ ...newRef, doi: trimmed })
      onSave({ doi: trimmed })
      return
    }
    onSave()
  }

  const switchMode = (next) => {
    setMode(next)
    setResolveError(null)
  }

  const fieldStyle = { borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary)' }

  return (
    <div
      className="px-4 py-3 border-t text-sm"
      style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-tertiary)' }}
    >
      {/* Mode toggle — tab strip */}
      <div className="flex items-center gap-1 mb-3 text-xs">
        <button
          onClick={() => switchMode('doi')}
          className="px-2 py-1 rounded font-medium"
          style={{
            background: mode === 'doi' ? 'var(--color-accent)' : 'transparent',
            color: mode === 'doi' ? '#fff' : 'var(--color-text-secondary)',
            border: '1px solid var(--color-border)',
          }}
        >
          By DOI (auto-fill)
        </button>
        <button
          onClick={() => switchMode('manual')}
          className="px-2 py-1 rounded font-medium"
          style={{
            background: mode === 'manual' ? 'var(--color-accent)' : 'transparent',
            color: mode === 'manual' ? '#fff' : 'var(--color-text-secondary)',
            border: '1px solid var(--color-border)',
          }}
        >
          Manual entry
        </button>
      </div>

      {mode === 'doi' ? (
        <div>
          <div className="flex gap-2">
            <input
              className="flex-1 px-2 py-1 rounded border"
              placeholder="DOI (e.g. 10.1038/s41586-023-06924-6) or https://doi.org/..."
              value={doiInput}
              onChange={e => setDoiInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !resolving) handleResolve() }}
              style={fieldStyle}
            />
            <button
              onClick={handleResolve}
              disabled={resolving || !doiInput.trim()}
              className="px-3 py-1 rounded text-sm font-medium"
              style={{
                background: 'var(--color-accent)',
                color: '#fff',
                opacity: (resolving || !doiInput.trim()) ? 0.6 : 1,
              }}
            >
              {resolving ? 'Resolving…' : 'Resolve'}
            </button>
          </div>
          {resolveError && (
            <div className="mt-2 text-xs" style={{ color: 'var(--color-error, #ef4444)' }}>
              {resolveError}
            </div>
          )}
          {resolved && (
            <div
              className="mt-2 p-2 rounded text-xs"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
            >
              <div style={{ fontWeight: 600 }}>{resolved.title || '(no title)'}</div>
              {(resolved.authors || []).length > 0 && (
                <div style={{ color: 'var(--color-text-muted)', marginTop: 2 }}>
                  {(resolved.authors || []).slice(0, 6).join(', ')}
                  {(resolved.authors || []).length > 6 ? ', …' : ''}
                </div>
              )}
              <div style={{ color: 'var(--color-text-muted)', marginTop: 2 }}>
                {resolved.venue || '—'}{resolved.year ? ` · ${resolved.year}` : ''}
              </div>
            </div>
          )}
          <div className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Paste a DOI and we'll fill in title, authors, year, and venue from CrossRef.
            If you skip Resolve, we'll still try when you click Add.
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <input
            className="px-2 py-1 rounded border"
            placeholder="Title"
            value={newRef.title}
            onChange={e => setNewRef({ ...newRef, title: e.target.value })}
            style={fieldStyle}
          />
          <input
            className="px-2 py-1 rounded border"
            placeholder="Authors (comma-separated)"
            value={newRef.authors}
            onChange={e => setNewRef({ ...newRef, authors: e.target.value })}
            style={fieldStyle}
          />
          <input
            className="px-2 py-1 rounded border"
            placeholder="Year"
            value={newRef.year}
            onChange={e => setNewRef({ ...newRef, year: e.target.value })}
            style={fieldStyle}
          />
          <input
            className="px-2 py-1 rounded border"
            placeholder="DOI"
            value={newRef.doi}
            onChange={e => setNewRef({ ...newRef, doi: e.target.value })}
            style={fieldStyle}
          />
          <input
            className="px-2 py-1 rounded border col-span-2"
            placeholder="arXiv ID (e.g. 2401.12345)"
            value={newRef.arxiv_id}
            onChange={e => setNewRef({ ...newRef, arxiv_id: e.target.value })}
            style={fieldStyle}
          />
        </div>
      )}
      <div className="mt-2 flex gap-2 justify-end">
        <button
          onClick={onCancel}
          className="px-3 py-1 rounded text-sm"
          style={{ borderColor: 'var(--color-border)', border: '1px solid' }}
        >
          Cancel
        </button>
        <button
          onClick={handleAddAndResolve}
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
