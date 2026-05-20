import { useMemo, useState } from 'react'
import {
  exportReferenceAsPlainText,
  exportReferenceAsBibtex,
  exportResultsAsBibtex,
} from '../../utils/formatters'

/**
 * Grammarly-style "Corrections" tab: a side-by-side view of every
 * reference RefChecker flagged as wrong, with a one-click copy of the
 * corrected metadata in three common formats.
 *
 * Intentionally minimal — no inline editing of the paper, no apply-to-source
 * file (we can't write back to the user's PDF/LaTeX). The value is letting
 * authors copy the corrected entry straight into their bibliography.
 */
export default function CorrectionsView({ references }) {
  const [format, setFormat] = useState('bibtex') // bibtex | plaintext
  const [copiedKey, setCopiedKey] = useState(null)

  const flagged = useMemo(() => {
    const list = references || []
    return list
      .filter(ref => {
        const errs = (ref.errors || []).length
        const warns = (ref.warnings || []).length
        return errs > 0 || warns > 0 || ref.status === 'unverified' || ref.status === 'hallucinated'
      })
      .sort((a, b) => {
        const ai = typeof a?.index === 'number' ? a.index : 999999
        const bi = typeof b?.index === 'number' ? b.index : 999999
        return ai - bi
      })
  }, [references])

  const renderCited = (ref) => {
    // Compose the "cited" line from whatever the parser saw. We don't have
    // the raw source line, so we synthesize a stable representation that
    // mirrors what RefChecker compared against.
    const parts = []
    if (ref.authors) parts.push(ref.authors)
    if (ref.year) parts.push(ref.year)
    if (ref.title) parts.push(ref.title + '.')
    if (ref.venue) parts.push(ref.venue + '.')
    if (ref.cited_url) parts.push(ref.cited_url)
    return parts.join('. ').replace(/\.\.+/g, '.')
  }

  const renderCorrected = (ref) => {
    try {
      if (format === 'bibtex') return exportReferenceAsBibtex(ref, ref.index ?? 0)
      return exportReferenceAsPlainText(ref)
    } catch (e) {
      return '(could not render correction)'
    }
  }

  const copy = async (key, text) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedKey(key)
      setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 1500)
    } catch {
      /* ignore — clipboard may be unavailable in some WebView contexts */
    }
  }

  const copyAll = async () => {
    const text = format === 'bibtex'
      ? exportResultsAsBibtex({ references: flagged })
      : flagged.map(r => exportReferenceAsPlainText(r)).join('\n\n')
    await copy('__all__', text)
  }

  if (flagged.length === 0) {
    return (
      <div
        className="rounded-lg border p-6 text-center text-sm"
        style={{
          borderColor: 'var(--color-border)',
          backgroundColor: 'var(--color-bg-secondary)',
          color: 'var(--color-text-secondary)',
        }}
      >
        No corrections needed — every flagged reference has been verified clean.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div
        className="flex items-center justify-between flex-wrap gap-2 p-3 rounded-lg border"
        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
      >
        <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          <strong style={{ color: 'var(--color-text-primary)' }}>{flagged.length}</strong>{' '}
          reference{flagged.length === 1 ? '' : 's'} need attention. Copy individual entries
          or the whole batch into your bibliography.
        </div>
        <div className="flex items-center gap-2">
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            className="px-2 py-1 rounded border text-xs"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          >
            <option value="bibtex">BibTeX</option>
            <option value="plaintext">Plain text (ACM)</option>
          </select>
          <button
            onClick={copyAll}
            className="px-2 py-1 rounded text-xs font-medium"
            style={{
              backgroundColor: 'var(--color-accent, #3b82f6)',
              color: 'white',
            }}
            type="button"
          >
            {copiedKey === '__all__' ? '✓ Copied all' : 'Copy all corrections'}
          </button>
        </div>
      </div>

      {/* Side-by-side rows */}
      <div className="space-y-2">
        {flagged.map((ref, i) => {
          const key = ref.id || `ref-${i}`
          const corrected = renderCorrected(ref)
          return (
            <div
              key={key}
              className="rounded-lg border overflow-hidden"
              style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
            >
              <div
                className="px-3 py-1.5 text-xs flex items-center justify-between"
                style={{
                  backgroundColor: 'var(--color-bg-tertiary)',
                  color: 'var(--color-text-secondary)',
                  borderBottom: '1px solid var(--color-border)',
                }}
              >
                <span>
                  <strong style={{ color: 'var(--color-text-primary)' }}>
                    [{ref.index ?? '?'}] {ref.title || '(no title)'}
                  </strong>
                </span>
                <button
                  onClick={() => copy(key, corrected)}
                  className="px-2 py-0.5 rounded text-xs"
                  style={{
                    backgroundColor: 'var(--color-accent, #3b82f6)',
                    color: 'white',
                  }}
                  type="button"
                >
                  {copiedKey === key ? '✓ Copied' : 'Copy'}
                </button>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 divide-x" style={{ borderColor: 'var(--color-border)' }}>
                <div className="p-3">
                  <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    As cited
                  </div>
                  <div className="text-xs whitespace-pre-wrap break-words" style={{ color: 'var(--color-error, #ef4444)' }}>
                    {renderCited(ref)}
                  </div>
                  {(ref.errors || []).length > 0 && (
                    <ul className="mt-2 text-[11px] list-disc list-inside" style={{ color: 'var(--color-error, #ef4444)' }}>
                      {(ref.errors || []).slice(0, 4).map((e, j) => (
                        <li key={j}>{e.message || String(e)}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="p-3" style={{ borderLeft: '1px solid var(--color-border)' }}>
                  <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    Suggested correction
                  </div>
                  <pre
                    className="text-xs whitespace-pre-wrap break-words p-2 rounded"
                    style={{
                      backgroundColor: 'var(--color-bg-primary)',
                      color: 'var(--color-success, #22c55e)',
                    }}
                  >{corrected}</pre>
                  {ref.verified_url && (
                    <div className="text-[11px] mt-2" style={{ color: 'var(--color-text-secondary)' }}>
                      Source:{' '}
                      <a href={ref.verified_url} target="_blank" rel="noreferrer">
                        {ref.verified_url}
                      </a>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
