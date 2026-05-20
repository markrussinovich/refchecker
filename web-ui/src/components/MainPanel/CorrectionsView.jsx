import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CITATION_STYLES,
  exportReferenceAsStyle,
  exportResultsAsStyle,
  downloadAsFile,
  formatIssueLine,
} from '../../utils/formatters'
import { wordDiff } from '../../utils/wordDiff'
import { useCheckStore } from '../../stores/useCheckStore'
import { getEffectiveReferenceStatus } from '../../utils/referenceStatus'

/**
 * Mirrors the chip ids exposed by the Summary panel above the tab.
 * Used only for per-row badges — the actual selected filter set lives
 * in useCheckStore.statusFilter so the Summary chips drive both tabs.
 */
const CATEGORY_META = {
  error:         { label: 'Errors',        color: 'var(--color-error, #ef4444)' },
  warning:       { label: 'Warnings',      color: 'var(--color-warning, #f59e0b)' },
  unverified:    { label: 'Unverified',    color: 'var(--color-text-secondary)' },
  hallucination: { label: 'Hallucinated',  color: 'var(--color-hallucination, #a855f7)' },
  suggestion:    { label: 'Suggestions',   color: 'var(--color-suggestion, #3b82f6)' },
}

function classifyReference(ref, isCheckComplete) {
  // Use the same single-category resolver the References list and the
  // Summary chip counts use, so a ref with both an error and a warning
  // is counted as an error in both places — not as both. The Set return
  // type stays for backward compatibility with the filter/badge code.
  const tags = new Set()
  const status = getEffectiveReferenceStatus(ref, isCheckComplete)
  if (status === 'error') tags.add('error')
  else if (status === 'warning') tags.add('warning')
  else if (status === 'suggestion') tags.add('suggestion')
  else if (status === 'unverified') tags.add('unverified')
  else if (status === 'hallucinated' || status === 'hallucination') tags.add('hallucination')
  // Hallucination is an extra signal that can co-exist with errors when the
  // verifier confirms it — keep both tags so the filter can find it via
  // either chip.
  if (ref.hallucination_assessment?.verdict?.toUpperCase?.() === 'LIKELY') {
    tags.add('hallucination')
  }
  return tags
}

/** Reference shell with cited values (no corrections) for AS CITED rendering. */
function citedShell(ref) {
  return { ...ref, errors: [], warnings: [], suggestions: [], authoritative_urls: [] }
}

function DiffSide({ ops, side }) {
  return (
    <pre className="text-xs whitespace-pre-wrap break-words m-0" style={{ fontFamily: 'inherit' }}>
      {ops.map((op, idx) => {
        if (op.type === 'eq') return <span key={idx}>{op.word + op.sep}</span>
        if (side === 'cited' && op.type === 'del') {
          return (
            <span key={idx} style={{
              color: 'var(--color-error, #ef4444)',
              textDecoration: 'line-through',
              backgroundColor: 'rgba(239,68,68,0.12)',
              padding: '0 1px',
              borderRadius: 2,
            }}>{op.word}</span>
          )
        }
        if (side === 'corrected' && op.type === 'add') {
          return (
            <span key={idx} style={{
              color: 'var(--color-success, #22c55e)',
              fontWeight: 600,
              backgroundColor: 'rgba(34,197,94,0.12)',
              padding: '0 1px',
              borderRadius: 2,
            }}>{op.word}</span>
          )
        }
        if ((side === 'cited' && op.type === 'add') || (side === 'corrected' && op.type === 'del')) {
          return null
        }
        return <span key={idx}>{op.word + op.sep}</span>
      })}
    </pre>
  )
}

const STYLE_EXT = {
  bibtex: { ext: 'bib', mime: 'application/x-bibtex' },
  plaintext: { ext: 'txt', mime: 'text/plain' },
  apa: { ext: 'txt', mime: 'text/plain' },
  mla: { ext: 'txt', mime: 'text/plain' },
  chicago: { ext: 'txt', mime: 'text/plain' },
  ieee: { ext: 'txt', mime: 'text/plain' },
  vancouver: { ext: 'txt', mime: 'text/plain' },
  bibitem: { ext: 'tex', mime: 'application/x-tex' },
}

/**
 * Pick a sensible default citation style based on the paper source. A
 * .bib input wants BibTeX back; a .tex input wants \bibitem; otherwise
 * BibTeX is a fine universal default. The user can still override via
 * the dropdown.
 */
function detectDefaultStyle(paperSource) {
  if (!paperSource) return 'bibtex'
  const lower = String(paperSource).toLowerCase()
  if (lower.endsWith('.bib') || lower.endsWith('.bbl')) return 'bibtex'
  if (lower.endsWith('.tex')) return 'bibitem'
  if (lower.endsWith('.txt')) return 'plaintext'
  return 'bibtex'
}

export default function CorrectionsView({ references, isCheckComplete = false, paperSource = null }) {
  const [format, setFormat] = useState(() => detectDefaultStyle(paperSource))
  const lastSourceRef = useRef(paperSource)
  useEffect(() => {
    // Re-pick the default when navigating to a different check / new input
    // so a .bib file doesn't keep showing as APA after a previous APA check.
    if (lastSourceRef.current !== paperSource) {
      lastSourceRef.current = paperSource
      setFormat(detectDefaultStyle(paperSource))
    }
  }, [paperSource])
  const [copiedKey, setCopiedKey] = useState(null)
  const [showDiff, setShowDiff] = useState(true)

  // Per-reference decision state: keyed by ref id (or fallback "ref-N").
  //   { status: 'applied' | 'rejected' | 'edited', text?: string }
  // text is only set when the user explicitly edited the correction.
  const [decisions, setDecisions] = useState({})
  const [editingKey, setEditingKey] = useState(null)
  const [editBuffer, setEditBuffer] = useState('')

  const statusFilter = useCheckStore(s => s.statusFilter)
  const summaryActive = statusFilter.length > 0

  const categorized = useMemo(() => {
    return (references || [])
      .map(ref => ({ ref, tags: classifyReference(ref, isCheckComplete) }))
      .filter(({ tags }) => tags.size > 0)
      .sort((a, b) => {
        const ai = typeof a.ref?.index === 'number' ? a.ref.index : 999999
        const bi = typeof b.ref?.index === 'number' ? b.ref.index : 999999
        return ai - bi
      })
  }, [references, isCheckComplete])

  const filtered = useMemo(() => {
    if (!summaryActive) return categorized
    return categorized.filter(({ tags }) => {
      for (const t of tags) if (statusFilter.includes(t)) return true
      return false
    })
  }, [categorized, statusFilter, summaryActive])

  const keyFor = (ref, i) => ref.id || `ref-${ref.index ?? i}`

  const renderCorrected = (ref, i) => {
    const k = keyFor(ref, i)
    const d = decisions[k]
    if (d?.status === 'edited' && typeof d.text === 'string') return d.text
    try { return exportReferenceAsStyle(ref, format, i) } catch { return '(could not render)' }
  }
  const renderCited = (ref, i) => {
    try { return exportReferenceAsStyle(citedShell(ref), format, i) } catch { return '' }
  }

  const setDecision = (k, payload) => {
    setDecisions(prev => {
      const next = { ...prev }
      if (payload === null) delete next[k]
      else next[k] = payload
      return next
    })
  }

  const applyAllVisible = () => {
    setDecisions(prev => {
      const next = { ...prev }
      filtered.forEach(({ ref }, i) => {
        const k = keyFor(ref, i)
        // Don't clobber a user-edited entry — but do mark pending/rejected as applied.
        if (next[k]?.status === 'edited') return
        next[k] = { status: 'applied' }
      })
      return next
    })
  }
  const resetDecisions = () => setDecisions({})

  const startEditing = (k, currentText) => {
    setEditingKey(k); setEditBuffer(currentText)
  }
  const saveEdit = (k) => {
    setDecision(k, { status: 'edited', text: editBuffer })
    setEditingKey(null); setEditBuffer('')
  }
  const cancelEdit = () => { setEditingKey(null); setEditBuffer('') }

  const acceptedRefs = useMemo(() => {
    // Order respects the displayed (filtered + sorted) order so the
    // exported list matches what the user sees.
    return filtered
      .map(({ ref }, i) => ({ ref, i, key: keyFor(ref, i) }))
      .filter(({ key }) => decisions[key]?.status === 'applied' || decisions[key]?.status === 'edited')
  }, [filtered, decisions])

  const acceptedText = useMemo(() => {
    return acceptedRefs
      .map(({ ref, i, key }) => decisions[key]?.text || exportReferenceAsStyle(ref, format, i))
      .join('\n\n')
  }, [acceptedRefs, decisions, format])

  const copy = async (key, text) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedKey(key)
      setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 1500)
    } catch { /* clipboard may be unavailable in some WebView contexts */ }
  }

  const exportChangedList = () => {
    if (acceptedRefs.length === 0) return
    const { ext, mime } = STYLE_EXT[format] || STYLE_EXT.plaintext
    const filename = `refchecker-corrections-applied-${new Date().toISOString().slice(0,10)}.${ext}`
    downloadAsFile(acceptedText, filename, mime)
  }

  if (categorized.length === 0) {
    return (
      <div className="rounded-lg border p-6 text-center text-sm" style={{
        borderColor: 'var(--color-border)',
        backgroundColor: 'var(--color-bg-secondary)',
        color: 'var(--color-text-secondary)',
      }}>
        No corrections needed — every flagged reference has been verified clean.
      </div>
    )
  }

  const appliedCount = Object.values(decisions).filter(d => d.status === 'applied' || d.status === 'edited').length
  const rejectedCount = Object.values(decisions).filter(d => d.status === 'rejected').length

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="p-3 rounded-lg border space-y-2"
        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            <strong style={{ color: 'var(--color-text-primary)' }}>{filtered.length}</strong>{' '}
            of {categorized.length} flagged shown
            {' · '}
            <span style={{ color: 'var(--color-success, #22c55e)' }}>{appliedCount} applied</span>
            {' · '}
            <span style={{ color: 'var(--color-text-muted)' }}>{rejectedCount} rejected</span>
            {summaryActive && (
              <span className="ml-1">— filtered by {statusFilter.join(', ')} (Summary chips)</span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <label className="text-xs flex items-center gap-1" style={{ color: 'var(--color-text-secondary)' }}>
              <input type="checkbox" checked={showDiff} onChange={(e) => setShowDiff(e.target.checked)} />
              Highlight diff
            </label>
            <select value={format} onChange={(e) => setFormat(e.target.value)}
              className="px-2 py-1 rounded border text-xs"
              style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
              title="Citation style"
            >
              {CITATION_STYLES.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={applyAllVisible} disabled={filtered.length === 0}
            className="px-3 py-1 rounded text-xs font-medium"
            style={{ backgroundColor: 'var(--color-success, #22c55e)', color: 'white', opacity: filtered.length === 0 ? 0.5 : 1 }}
            type="button"
          >Apply all visible</button>
          <button onClick={resetDecisions} disabled={appliedCount + rejectedCount === 0}
            className="px-3 py-1 rounded text-xs font-medium border"
            style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)', opacity: (appliedCount + rejectedCount) === 0 ? 0.5 : 1 }}
            type="button"
          >Reset decisions</button>
          <button onClick={() => copy('__applied__', acceptedText)} disabled={appliedCount === 0}
            className="px-3 py-1 rounded text-xs font-medium border"
            style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)', opacity: appliedCount === 0 ? 0.5 : 1 }}
            type="button"
          >{copiedKey === '__applied__' ? '✓ Copied' : 'Copy applied'}</button>
          <button onClick={exportChangedList} disabled={appliedCount === 0}
            className="px-3 py-1 rounded text-xs font-medium"
            style={{ backgroundColor: 'var(--color-accent, #3b82f6)', color: 'white', opacity: appliedCount === 0 ? 0.5 : 1 }}
            type="button"
            title="Download just the corrections you applied, in the selected style"
          >Export changed list ({appliedCount})</button>
        </div>
      </div>

      {/* Rows */}
      <div className="space-y-2">
        {filtered.map(({ ref, tags }, i) => {
          const key = keyFor(ref, i)
          const decision = decisions[key]
          const correctedStr = renderCorrected(ref, i)
          const citedStr = renderCited(ref, i)
          const ops = showDiff && decision?.status !== 'edited' ? wordDiff(citedStr, correctedStr) : null
          const tagBadges = Object.entries(CATEGORY_META).filter(([id]) => tags.has(id)).map(([id, m]) => ({ id, ...m }))

          const decisionTint =
            decision?.status === 'applied' ? 'rgba(34,197,94,0.07)' :
            decision?.status === 'rejected' ? 'rgba(148,163,184,0.07)' :
            decision?.status === 'edited' ? 'rgba(59,130,246,0.07)' :
            'transparent'

          return (
            <div key={key}
              className="rounded-lg border overflow-hidden transition-colors"
              style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
            >
              <div className="px-3 py-1.5 text-xs flex items-center justify-between gap-2 flex-wrap"
                style={{
                  backgroundColor: 'var(--color-bg-tertiary)',
                  color: 'var(--color-text-secondary)',
                  borderBottom: '1px solid var(--color-border)',
                }}>
                <div className="flex items-center gap-2 min-w-0">
                  <strong style={{ color: 'var(--color-text-primary)' }} className="truncate">
                    [{ref.index ?? '?'}] {ref.title || '(no title)'}
                  </strong>
                  <div className="flex gap-1 flex-shrink-0">
                    {tagBadges.map(t => (
                      <span key={t.id} className="text-[10px] px-1.5 py-0.5 rounded-full"
                        style={{ backgroundColor: t.color, color: 'white' }}>
                        {t.label.replace(/s$/, '')}
                      </span>
                    ))}
                    {decision && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{
                        backgroundColor:
                          decision.status === 'applied' ? 'var(--color-success, #22c55e)' :
                          decision.status === 'rejected' ? 'var(--color-text-muted, #94a3b8)' :
                          'var(--color-accent, #3b82f6)',
                        color: 'white',
                      }}>
                        {decision.status}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1 flex-wrap">
                  <button onClick={() => setDecision(key, { status: 'applied' })}
                    className="px-2 py-0.5 rounded text-xs"
                    style={{ backgroundColor: decision?.status === 'applied' ? 'var(--color-success, #22c55e)' : 'var(--color-bg-primary)',
                             color: decision?.status === 'applied' ? 'white' : 'var(--color-text-primary)',
                             border: '1px solid var(--color-border)' }}
                    type="button"
                  >Apply fix</button>
                  <button onClick={() => setDecision(key, { status: 'rejected' })}
                    className="px-2 py-0.5 rounded text-xs"
                    style={{ backgroundColor: decision?.status === 'rejected' ? 'var(--color-text-muted, #94a3b8)' : 'var(--color-bg-primary)',
                             color: decision?.status === 'rejected' ? 'white' : 'var(--color-text-primary)',
                             border: '1px solid var(--color-border)' }}
                    type="button"
                  >Don't apply</button>
                  <button onClick={() => startEditing(key, correctedStr)}
                    className="px-2 py-0.5 rounded text-xs"
                    style={{ backgroundColor: editingKey === key ? 'var(--color-accent, #3b82f6)' : 'var(--color-bg-primary)',
                             color: editingKey === key ? 'white' : 'var(--color-text-primary)',
                             border: '1px solid var(--color-border)' }}
                    type="button"
                  >Edit</button>
                  <button onClick={() => copy(key, correctedStr)}
                    className="px-2 py-0.5 rounded text-xs"
                    style={{ backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}
                    type="button"
                  >{copiedKey === key ? '✓' : 'Copy'}</button>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2" style={{ backgroundColor: decisionTint }}>
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
                        <li key={j}>{formatIssueLine(e)}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="p-3" style={{ borderLeft: '1px solid var(--color-border)', minWidth: 0 }}>
                  <div className="text-[10px] uppercase tracking-wider mb-1 flex items-center gap-1" style={{ color: 'var(--color-text-secondary)' }}>
                    Suggested correction
                    {decision?.status === 'edited' && <span style={{ color: 'var(--color-accent, #3b82f6)' }}>(edited)</span>}
                  </div>
                  {editingKey === key ? (
                    <div className="space-y-2">
                      <textarea
                        value={editBuffer}
                        onChange={(e) => setEditBuffer(e.target.value)}
                        rows={Math.min(12, Math.max(4, editBuffer.split('\n').length + 1))}
                        className="w-full p-2 rounded text-xs font-mono"
                        style={{
                          backgroundColor: 'var(--color-bg-primary)',
                          color: 'var(--color-text-primary)',
                          border: '1px solid var(--color-border)',
                        }}
                      />
                      <div className="flex gap-2">
                        <button onClick={() => saveEdit(key)}
                          className="px-3 py-1 rounded text-xs font-medium"
                          style={{ backgroundColor: 'var(--color-accent, #3b82f6)', color: 'white' }}
                          type="button"
                        >Save edit</button>
                        <button onClick={cancelEdit}
                          className="px-3 py-1 rounded text-xs font-medium border"
                          style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                          type="button"
                        >Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <div className="p-2 rounded" style={{
                      backgroundColor: 'var(--color-bg-primary)',
                      color: 'var(--color-text-primary)',
                    }}>
                      {ops ? <DiffSide ops={ops} side="corrected" /> : (
                        <pre className="text-xs whitespace-pre-wrap break-words m-0" style={{ fontFamily: 'inherit' }}>{correctedStr}</pre>
                      )}
                    </div>
                  )}
                  {ref.verified_url && (
                    <div className="text-[11px] mt-2" style={{ color: 'var(--color-text-secondary)' }}>
                      Source: <a href={ref.verified_url} target="_blank" rel="noreferrer">{ref.verified_url}</a>
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
