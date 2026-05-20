import { useMemo, useState } from 'react'
import {
  CITATION_STYLES,
  exportReferenceAsStyle,
  exportResultsAsStyle,
} from '../../utils/formatters'
import { wordDiff } from '../../utils/wordDiff'
import { useCheckStore } from '../../stores/useCheckStore'

/**
 * The chip categories the Summary panel exposes, mirrored here only so
 * the Corrections tab can label per-row badges. The actual selected
 * filter set lives in useCheckStore.statusFilter — set from the
 * Summary chips above this tab — so both tabs filter consistently.
 */
const CATEGORY_META = {
  error:         { label: 'Errors',        color: 'var(--color-error, #ef4444)' },
  warning:       { label: 'Warnings',      color: 'var(--color-warning, #f59e0b)' },
  unverified:    { label: 'Unverified',    color: 'var(--color-text-secondary)' },
  hallucination: { label: 'Hallucinated',  color: 'var(--color-hallucination, #a855f7)' },
  suggestion:    { label: 'Suggestions',   color: 'var(--color-suggestion, #3b82f6)' },
}

function classifyReference(ref) {
  // Returns the set of categories this reference belongs to. Keys match
  // the Summary chip ids so the global statusFilter applies cleanly.
  const tags = new Set()
  if ((ref.errors || []).length > 0) tags.add('error')
  if ((ref.warnings || []).length > 0) tags.add('warning')
  if (ref.status === 'unverified') tags.add('unverified')
  if (ref.status === 'hallucinated' || ref.hallucination_assessment?.verdict?.toUpperCase?.() === 'LIKELY') {
    tags.add('hallucination')
  }
  if (ref.status === 'suggestion' || (ref.suggestions || []).length > 0) tags.add('suggestion')
  return tags
}

/**
 * Build a reference shell containing the values *as cited* (no
 * corrections applied). Feeds the same style formatters as the real
 * ref so AS CITED and SUGGESTED CORRECTION render in the same style.
 */
function citedShell(ref) {
  return {
    ...ref,
    // Strip the issue arrays so getCorrectedReferenceData returns the
    // cited title/authors/year/venue verbatim.
    errors: [],
    warnings: [],
    suggestions: [],
    authoritative_urls: [],
  }
}

function DiffSide({ ops, side }) {
  // side === 'cited' keeps eq + del (red strikethrough), drops add
  // side === 'corrected' keeps eq + add (green bold), drops del
  return (
    <pre
      className="text-xs whitespace-pre-wrap break-words m-0"
      style={{ fontFamily: 'inherit' }}
    >
      {ops.map((op, idx) => {
        if (op.type === 'eq') return <span key={idx}>{op.word + op.sep}</span>
        if (side === 'cited' && op.type === 'del') {
          return (
            <span
              key={idx}
              style={{
                color: 'var(--color-error, #ef4444)',
                textDecoration: 'line-through',
                backgroundColor: 'rgba(239,68,68,0.12)',
                padding: '0 1px',
                borderRadius: 2,
              }}
            >{op.word}</span>
          )
        }
        if (side === 'corrected' && op.type === 'add') {
          return (
            <span
              key={idx}
              style={{
                color: 'var(--color-success, #22c55e)',
                fontWeight: 600,
                backgroundColor: 'rgba(34,197,94,0.12)',
                padding: '0 1px',
                borderRadius: 2,
              }}
            >{op.word}</span>
          )
        }
        // Render the trailing separator for kept words even when we skip
        // the inverse-side ops, so spacing stays sensible.
        if ((side === 'cited' && op.type === 'add') || (side === 'corrected' && op.type === 'del')) {
          return null
        }
        return <span key={idx}>{op.word + op.sep}</span>
      })}
      {/* Render trailing separators that belong to skipped words */}
    </pre>
  )
}

export default function CorrectionsView({ references }) {
  const [format, setFormat] = useState('bibtex')
  const [copiedKey, setCopiedKey] = useState(null)
  const [showDiff, setShowDiff] = useState(true)

  // Single source of truth for "what's filtered": the Summary chips above
  // both tabs. Empty array = no filter applied (show every flagged ref).
  const statusFilter = useCheckStore(s => s.statusFilter)
  const summaryActive = statusFilter.length > 0

  const categorized = useMemo(() => {
    return (references || [])
      .map(ref => ({ ref, tags: classifyReference(ref) }))
      .filter(({ tags }) => tags.size > 0)
      .sort((a, b) => {
        const ai = typeof a.ref?.index === 'number' ? a.ref.index : 999999
        const bi = typeof b.ref?.index === 'number' ? b.ref.index : 999999
        return ai - bi
      })
  }, [references])

  const filtered = useMemo(() => {
    if (!summaryActive) return categorized
    return categorized.filter(({ tags }) => {
      for (const t of tags) if (statusFilter.includes(t)) return true
      return false
    })
  }, [categorized, statusFilter, summaryActive])

  const renderCorrected = (ref, i) => {
    try { return exportReferenceAsStyle(ref, format, i) } catch { return '(could not render)' }
  }
  const renderCited = (ref, i) => {
    try { return exportReferenceAsStyle(citedShell(ref), format, i) } catch { return '' }
  }

  const copy = async (key, text) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedKey(key)
      setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 1500)
    } catch { /* clipboard unavailable in some WebView contexts */ }
  }
  const copyAll = async () => {
    await copy('__all__', exportResultsAsStyle(filtered.map(f => f.ref), format))
  }

  // Empty states
  if (categorized.length === 0) {
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
      {/* Toolbar — style + copy all. Filtering is driven by the Summary
          chips above the tabs (useCheckStore.statusFilter), so both
          tabs stay in sync. */}
      <div
        className="p-3 rounded-lg border flex items-center justify-between flex-wrap gap-2"
        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
      >
        <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          <strong style={{ color: 'var(--color-text-primary)' }}>{filtered.length}</strong>{' '}
          of {categorized.length} flagged reference{categorized.length === 1 ? '' : 's'} shown
          {summaryActive && (
            <span className="ml-1">— filtered by {statusFilter.join(', ')} (Summary chips)</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs flex items-center gap-1" style={{ color: 'var(--color-text-secondary)' }}>
            <input type="checkbox" checked={showDiff} onChange={(e) => setShowDiff(e.target.checked)} />
            Highlight diff
          </label>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            className="px-2 py-1 rounded border text-xs"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
            title="Citation style"
          >
            {CITATION_STYLES.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
          <button
            onClick={copyAll}
            disabled={filtered.length === 0}
            className="px-2 py-1 rounded text-xs font-medium"
            style={{
              backgroundColor: 'var(--color-accent, #3b82f6)',
              color: 'white',
              opacity: filtered.length === 0 ? 0.5 : 1,
            }}
            type="button"
          >
            {copiedKey === '__all__' ? '✓ Copied all' : 'Copy all'}
          </button>
        </div>
      </div>

      {/* Rows */}
      <div className="space-y-2">
        {filtered.map(({ ref, tags }, i) => {
          const key = ref.id || `ref-${i}`
          const correctedStr = renderCorrected(ref, i)
          const citedStr = renderCited(ref, i)
          const ops = showDiff ? wordDiff(citedStr, correctedStr) : null
          const tagBadges = Object.entries(CATEGORY_META)
            .filter(([id]) => tags.has(id))
            .map(([id, meta]) => ({ id, ...meta }))
          return (
            <div
              key={key}
              className="rounded-lg border overflow-hidden"
              style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
            >
              <div
                className="px-3 py-1.5 text-xs flex items-center justify-between gap-2 flex-wrap"
                style={{
                  backgroundColor: 'var(--color-bg-tertiary)',
                  color: 'var(--color-text-secondary)',
                  borderBottom: '1px solid var(--color-border)',
                }}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <strong style={{ color: 'var(--color-text-primary)' }} className="truncate">
                    [{ref.index ?? '?'}] {ref.title || '(no title)'}
                  </strong>
                  <div className="flex gap-1 flex-shrink-0">
                    {tagBadges.map(t => (
                      <span
                        key={t.id}
                        className="text-[10px] px-1.5 py-0.5 rounded-full"
                        style={{ backgroundColor: t.color, color: 'white' }}
                      >
                        {t.label.replace(/s$/, '')}
                      </span>
                    ))}
                  </div>
                </div>
                <button
                  onClick={() => copy(key, correctedStr)}
                  className="px-2 py-0.5 rounded text-xs"
                  style={{ backgroundColor: 'var(--color-accent, #3b82f6)', color: 'white' }}
                  type="button"
                >
                  {copiedKey === key ? '✓ Copied' : 'Copy'}
                </button>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2" style={{ borderColor: 'var(--color-border)' }}>
                <div className="p-3" style={{ minWidth: 0 }}>
                  <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    As cited
                  </div>
                  <div style={{ color: 'var(--color-text-primary)' }}>
                    {ops ? <DiffSide ops={ops} side="cited" /> : (
                      <pre className="text-xs whitespace-pre-wrap break-words m-0" style={{ fontFamily: 'inherit' }}>{citedStr}</pre>
                    )}
                  </div>
                  {(ref.errors || []).length > 0 && (
                    <ul className="mt-2 text-[11px] list-disc list-inside" style={{ color: 'var(--color-error, #ef4444)' }}>
                      {(ref.errors || []).slice(0, 4).map((e, j) => (
                        <li key={j}>{e.message || String(e)}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="p-3" style={{ borderLeft: '1px solid var(--color-border)', minWidth: 0 }}>
                  <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    Suggested correction
                  </div>
                  <div
                    className="p-2 rounded"
                    style={{ backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)' }}
                  >
                    {ops ? <DiffSide ops={ops} side="corrected" /> : (
                      <pre className="text-xs whitespace-pre-wrap break-words m-0" style={{ fontFamily: 'inherit' }}>{correctedStr}</pre>
                    )}
                  </div>
                  {ref.verified_url && (
                    <div className="text-[11px] mt-2" style={{ color: 'var(--color-text-secondary)' }}>
                      Source:{' '}
                      <a href={ref.verified_url} target="_blank" rel="noreferrer">{ref.verified_url}</a>
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
