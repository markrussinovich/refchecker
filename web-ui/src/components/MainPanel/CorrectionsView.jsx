import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CITATION_STYLES,
  CITATION_STYLE_DEFAULTS,
  exportReferenceAsStyle,
  exportResultsAsStyle,
  downloadAsFile,
  filterIssuesForStyle,
  formatIssueLine,
  listCustomCitationStyles,
  saveCustomCitationStyle,
  deleteCustomCitationStyle,
} from '../../utils/formatters'
import {
  verifyReferenceInCheck,
} from '../../utils/api'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useStyleStore } from '../../stores/useStyleStore'
import useReferenceActions from '../../hooks/useReferenceActions'
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

function DiffSide({ ops, side, fontFamily }) {
  return (
    <pre
      className="text-xs whitespace-pre-wrap break-words m-0"
      style={{ fontFamily: fontFamily || 'inherit' }}
    >
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
 * Font stack matched to each citation style's printed convention.
 *
 *   APA 7 / MLA 9 / Chicago / IEEE / Vancouver / plain text → serif
 *     (every major style guide prints in Times-class fonts; using a
 *     serif here lets the user preview what the citation will look
 *     like once it lands in their document.)
 *   BibTeX / \bibitem → monospace
 *     (both are source code, not running text; rendering them in a
 *     proportional font hides field alignment.)
 */
const STYLE_FONT = {
  bibtex:    "'SF Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace",
  bibitem:   "'SF Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace",
  apa:       "'Charter', 'Iowan Old Style', 'Palatino Linotype', Palatino, 'Times New Roman', Times, Georgia, serif",
  mla:       "'Charter', 'Iowan Old Style', 'Palatino Linotype', Palatino, 'Times New Roman', Times, Georgia, serif",
  chicago:   "'Charter', 'Iowan Old Style', 'Palatino Linotype', Palatino, 'Times New Roman', Times, Georgia, serif",
  ieee:      "'Charter', 'Iowan Old Style', 'Palatino Linotype', Palatino, 'Times New Roman', Times, Georgia, serif",
  vancouver: "'Charter', 'Iowan Old Style', 'Palatino Linotype', Palatino, 'Times New Roman', Times, Georgia, serif",
  plaintext: "'Charter', 'Iowan Old Style', 'Palatino Linotype', Palatino, 'Times New Roman', Times, Georgia, serif",
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

/**
 * Best-effort inference of which citation style the user's bibliography
 * was written in, by sampling the cited_text of the first few refs.
 * Falls back to the source-extension default so existing behaviour is
 * preserved when references aren't extracted yet. Coarse heuristics —
 * the dropdown remains a free override.
 */
function inferStyleFromReferences(references) {
  if (!Array.isArray(references) || references.length === 0) return null
  const samples = references
    .map(r => (r?.cited_text || r?.raw_text || '').trim())
    .filter(s => s.length > 20)
    .slice(0, 8)
  if (samples.length === 0) return null
  let ieee = 0, vancouver = 0, mla = 0, apa = 0, chicago = 0
  for (const s of samples) {
    if (/^\s*\[\d+\]/.test(s)) ieee += 2
    // Vancouver: "Surname AB" — initials with no periods stuck to surname.
    if (/^[A-Z][a-zA-Z'-]+\s+[A-Z]{1,3}(,|\.|\s)/.test(s)) vancouver += 1
    // APA: "Lastname, A. B. (yyyy)." — surname, comma, initials with
    // periods, year in parens.
    if (/^[A-Z][a-zA-Z'-]+,\s+[A-Z]\.\s*[A-Z]?\.?.*\(\d{4}[a-z]?\)/.test(s)) apa += 2
    // MLA: "Lastname, First Last." — surname, comma, full given names,
    // not initials, year usually mid-string not in parens.
    if (/^[A-Z][a-zA-Z'-]+,\s+[A-Z][a-z]+\s+[A-Z][a-z]+/.test(s)) mla += 1
    // Chicago author-date is close to APA but uses "lastname, firstname"
    // with full given names + (year). Hard to disambiguate from MLA
    // without more context, so leave Chicago weakly weighted.
    if (/\(\d{4}[a-z]?\)/.test(s) && /[A-Z][a-z]+ [A-Z][a-z]+/.test(s)) chicago += 0.5
  }
  const tally = [
    ['ieee', ieee], ['vancouver', vancouver],
    ['apa', apa], ['mla', mla], ['chicago', chicago],
  ].sort((a, b) => b[1] - a[1])
  const [winner, score] = tally[0]
  if (score >= 2) return winner
  return null
}

export default function CorrectionsView({ references, isCheckComplete = false, paperSource = null }) {
  const [format, setFormat] = useState(() => detectDefaultStyle(paperSource))
  const [autoDetected, setAutoDetected] = useState(null)
  const lastSourceRef = useRef(paperSource)
  const userOverroteStyle = useRef(false)
  useEffect(() => {
    // Re-pick the default when navigating to a different check / new input
    // so a .bib file doesn't keep showing as APA after a previous APA check.
    if (lastSourceRef.current !== paperSource) {
      lastSourceRef.current = paperSource
      setFormat(detectDefaultStyle(paperSource))
      setAutoDetected(null)
      userOverroteStyle.current = false
    }
  }, [paperSource])

  // Try to infer the style from the references themselves once they
  // land. Only auto-promote it if the user hasn't already touched the
  // dropdown — otherwise we'd fight their explicit choice (#24).
  //
  // Re-infer whenever any cited_text changes (not just the list length),
  // so Re-verify / Apply Fix that swap text in place still trigger a
  // fresh detection if the user hasn't overridden yet.
  const refsTextSig = useMemo(() => {
    if (!Array.isArray(references)) return 0
    let sig = 0
    for (let i = 0; i < references.length; i += 1) {
      const t = references[i]?.cited_text || references[i]?.raw_text || ''
      sig += t.length
    }
    return `${references.length}:${sig}`
  }, [references])
  useEffect(() => {
    if (userOverroteStyle.current) return
    const guess = inferStyleFromReferences(references)
    if (guess && guess !== format) {
      setAutoDetected(guess)
      setFormat(guess)
    } else if (guess) {
      setAutoDetected(guess)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refsTextSig])
  const [copiedKey, setCopiedKey] = useState(null)
  const [showDiff, setShowDiff] = useState(true)

  // Citation-style overrides + custom-style builder.
  const [styleOptions, setStyleOptions] = useState({})  // { max_authors, et_al_threshold, include_url }

  // Mirror format + styleOptions into the shared store so other views
  // (Suggest-alternative, References-tab actions, etc.) can render in
  // the same style without each maintaining its own picker.
  useEffect(() => {
    useStyleStore.getState().setFormat(format)
  }, [format])
  useEffect(() => {
    useStyleStore.getState().setStyleOptions(styleOptions)
  }, [styleOptions])
  const [showStyleCustomize, setShowStyleCustomize] = useState(false)
  const [customStyles, setCustomStyles] = useState(() => listCustomCitationStyles())
  const [newCustomStyle, setNewCustomStyle] = useState({ id: '', label: '', template: '{authors} ({year}). {title}. {venue}. {url}' })

  const refreshCustom = () => setCustomStyles(listCustomCitationStyles())
  const handleSaveCustomStyle = () => {
    const id = (newCustomStyle.id || newCustomStyle.label || '').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-')
    if (!id || !newCustomStyle.template.trim()) {
      alert('Custom style needs a name and a template')
      return
    }
    saveCustomCitationStyle({ id, label: newCustomStyle.label || id, template: newCustomStyle.template })
    setNewCustomStyle({ id: '', label: '', template: '{authors} ({year}). {title}. {venue}. {url}' })
    refreshCustom()
  }
  const handleDeleteCustomStyle = (id) => {
    if (!window.confirm(`Delete custom style "${id}"?`)) return
    deleteCustomCitationStyle(id)
    refreshCustom()
  }
  const styleDefaults = CITATION_STYLE_DEFAULTS[format] || {}
  const effectiveOptions = {
    max_authors: styleOptions.max_authors ?? styleDefaults.max_authors,
    et_al_threshold: styleOptions.et_al_threshold ?? styleDefaults.et_al_threshold,
    include_url: styleOptions.include_url ?? styleDefaults.include_url,
  }

  // Per-reference decision state: keyed by ref id (or fallback "ref-N").
  //   { status: 'applied' | 'rejected' | 'edited', text?: string }
  // text is only set when the user explicitly edited the correction.
  const [decisions, setDecisions] = useState({})
  const [editingKey, setEditingKey] = useState(null)
  const [editBuffer, setEditBuffer] = useState('')
  // Snapshot map: { key: { title, authors, year, venue, doi, arxiv_id } }
  // captured right before "Apply fix" overwrites the ref. Powers the
  // per-row "↺ Restore" button — replays the snapshot through the
  // /verify endpoint's `overrides` path so the ref's metadata reverts
  // and the badge moves back. Lives in component state only (lost on
  // tab unmount), which is the right granularity for an immediate-undo
  // affordance; persistent revert would need a DB-side snapshot.
  const [originalSnapshots, setOriginalSnapshots] = useState({})

  // Add / Remove / Suggest server actions — delegate to the same hook
  // the References tab uses. This gives the Corrections view the same
  // optimistic checkStore updates (so HealthBadge moves immediately),
  // the Undo stash for removed refs, and per-row busy state. Before
  // this, Remove fired a server delete and a reload but skipped the
  // optimistic update, so the badge stayed stale until the user
  // navigated away and back; Undo didn't exist at all here.
  const {
    selectedCheckId,
    busyKey,
    globalBusy,
    showAdd,
    setShowAdd,
    newRef,
    setNewRef,
    suggestFor,
    setSuggestFor,
    handleAddRef,
    handleRemoveRef,
    handleSuggestAlt,
    removedRefs,
    handleRestoreRef,
    clearRemovedRefs,
    isRemoving,
    isSuggesting,
  } = useReferenceActions()

  const statusFilter = useCheckStore(s => s.statusFilter)
  const summaryActive = statusFilter.length > 0

  // Pre-filter each ref's errors/warnings against the user's selected
  // citation style — author-count "mismatches" that just reflect the
  // style's own et-al rules aren't real corrections (#19, #21). The
  // filtered refs then flow into classifyReference + the renderer so a
  // ref whose only "issue" was style-conforming et-al drops out of the
  // Corrections list entirely.
  const styleFilteredRefs = useMemo(() => {
    return (references || []).map(ref => {
      if (!ref) return ref
      const filteredErrors = filterIssuesForStyle(ref.errors, ref, format)
      const filteredWarnings = filterIssuesForStyle(ref.warnings, ref, format)
      if (
        filteredErrors === ref.errors &&
        filteredWarnings === ref.warnings
      ) {
        return ref
      }
      return { ...ref, errors: filteredErrors, warnings: filteredWarnings }
    })
  }, [references, format])

  const categorized = useMemo(() => {
    return (styleFilteredRefs || [])
      .map((ref, i) => {
        const k = ref.id || `ref-${ref.index ?? i}`
        return { ref, tags: classifyReference(ref, isCheckComplete), _decisionKey: k }
      })
      // Keep the row visible if EITHER the ref still has flagged tags OR
      // the user has already recorded a decision (applied / edited /
      // rejected). Otherwise applying a fix made the row vanish — the
      // user lost the affordance to undo or re-edit, and the only signal
      // that the fix landed was the health badge moving. Surfacing
      // accepted rows lets the user reset them via the per-row "Don't
      // apply" / "Reset decisions" buttons or the new "↺ Restore" button.
      .filter(({ tags, _decisionKey }) => tags.size > 0 || !!decisions[_decisionKey])
      .sort((a, b) => {
        const ai = typeof a.ref?.index === 'number' ? a.ref.index : 999999
        const bi = typeof b.ref?.index === 'number' ? b.ref.index : 999999
        return ai - bi
      })
  }, [styleFilteredRefs, isCheckComplete, decisions])

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
    try { return exportReferenceAsStyle(ref, format, i, effectiveOptions) } catch { return '(could not render)' }
  }
  const renderCited = (ref, i) => {
    try { return exportReferenceAsStyle(citedShell(ref), format, i, effectiveOptions) } catch { return '' }
  }

  const setDecision = (k, payload) => {
    setDecisions(prev => {
      const next = { ...prev }
      if (payload === null) delete next[k]
      else next[k] = payload
      return next
    })
  }

  // Snapshot the ref's pre-fix metadata so the "↺ Restore" button can
  // roll it back. Idempotent — the first snapshot wins, so re-applying
  // a fix doesn't overwrite the original cited values.
  const snapshotIfMissing = (k, ref) => {
    setOriginalSnapshots(prev => {
      if (prev[k]) return prev
      return {
        ...prev,
        [k]: {
          title: ref.title ?? '',
          authors: Array.isArray(ref.authors) ? [...ref.authors] : ref.authors,
          year: ref.year ?? null,
          venue: ref.venue ?? '',
          doi: ref.doi ?? '',
          arxiv_id: ref.arxiv_id ?? '',
        },
      }
    })
  }

  // When the user accepts a correction we trigger a live re-verify so
  // the badge / status updates without waiting for a full re-run.
  const applyAndReverify = async (ref, i) => {
    const k = keyFor(ref, i)
    snapshotIfMissing(k, ref)
    setDecision(k, { status: 'applied' })
    if (selectedCheckId) {
      const refIdStr = String(ref.id ?? ref.index ?? i)
      // Optimistically flip status + merge corrected metadata in BOTH
      // stores so the citation-health chip moves immediately. The
      // useHistoryStore update covers historical-view checks; the
      // useCheckStore update covers the in-progress / current-check
      // view (displayRefs prefers checkStore when isCurrentCheck, so
      // without the second call the badge stayed frozen for fresh
      // checks until reload landed).
      useHistoryStore.getState().optimisticApplyCorrection?.(refIdStr)
      useCheckStore.getState().applyCorrectionInStore?.(refIdStr)
      try {
        await verifyReferenceInCheck(selectedCheckId, refIdStr, { apply_correction: true })
        await useHistoryStore.getState().selectCheck?.(selectedCheckId, { force: true })
      } catch (e) {
        /* re-verify is best-effort; the optimistic update stands */
      }
      // The re-verify may have spent tokens — refresh the usage badge now.
      try { window.dispatchEvent(new Event('refchecker:usage-changed')) } catch { /* no-op */ }
    }
  }

  // Roll an applied fix back to the pre-fix snapshot. Re-runs the
  // verifier against the original cited values so the badge / status
  // returns to what it was before the user accepted the fix. No-op when
  // we don't have a snapshot (e.g. user typed an edit without first
  // accepting, or the snapshot map was cleared on tab unmount).
  const restoreOriginal = async (ref, i) => {
    const k = keyFor(ref, i)
    // Roll the optimistic store mutation back NOW so the HealthBadge / list move
    // immediately. Revert BOTH stores: useCheckStore drives the current-check
    // view, useHistoryStore.selectedCheck drives the historical view — without
    // the second call the badge stayed frozen on Restore for history checks.
    const refIdForRevert = String(ref.id ?? ref.index ?? i)
    useCheckStore.getState().revertCorrectionInStore?.(refIdForRevert)
    useHistoryStore.getState().optimisticRevertCorrection?.(refIdForRevert)
    const snap = originalSnapshots[k]
    if (!snap) {
      // No snapshot — best we can do is drop the local decision so the
      // row falls back to its current (post-fix) DB state. The user
      // would need a full re-check to revert.
      setDecision(k, null)
      return
    }
    setDecision(k, null)
    if (!selectedCheckId) return
    const refIdStr = String(ref.id ?? ref.index ?? i)
    try {
      await verifyReferenceInCheck(selectedCheckId, refIdStr, { overrides: snap })
      await useHistoryStore.getState().selectCheck?.(selectedCheckId, { force: true })
    } catch (e) {
      /* best-effort — the local decision flip already happened */
    }
    // Drop the snapshot so a subsequent Apply Fix captures a fresh one.
    setOriginalSnapshots(prev => {
      const next = { ...prev }
      delete next[k]
      return next
    })
  }

  // "Don't apply": if this row was already optimistically applied/edited, roll
  // the correction back in BOTH stores so the HealthBadge drops again — then
  // mark it rejected. Without the rollback the badge stayed inflated after the
  // user changed their mind.
  const rejectCorrection = (ref, i, k) => {
    const prevStatus = decisions[k]?.status
    if (prevStatus === 'applied' || prevStatus === 'edited') {
      const refIdForRevert = String(ref.id ?? ref.index ?? i)
      useCheckStore.getState().revertCorrectionInStore?.(refIdForRevert)
      useHistoryStore.getState().optimisticRevertCorrection?.(refIdForRevert)
    }
    setDecision(k, { status: 'rejected' })
  }

  const applyAllVisible = async () => {
    const targets = []
    // Snapshot every targeted ref BEFORE marking decisions, so Restore
    // can roll back any of them. The map is keyed by row key so
    // per-row restore stays independent even after a bulk apply.
    filtered.forEach(({ ref }, i) => {
      const k = keyFor(ref, i)
      snapshotIfMissing(k, ref)
    })
    setDecisions(prev => {
      const next = { ...prev }
      filtered.forEach(({ ref }, i) => {
        const k = keyFor(ref, i)
        // Don't clobber a user-edited entry — but do mark pending/rejected as applied.
        if (next[k]?.status === 'edited') return
        next[k] = { status: 'applied' }
        targets.push({ ref, i })
      })
      return next
    })
    if (selectedCheckId && targets.length) {
      // Optimistic local flip so the badge climbs immediately for every
      // accepted correction; /verify confirms in the background. Update
      // BOTH stores — historical view reads selectedCheck.results,
      // current-check view reads useCheckStore.references.
      const histStore = useHistoryStore.getState()
      const checkStoreApi = useCheckStore.getState()
      for (const { ref, i } of targets) {
        const refIdStr = String(ref.id ?? ref.index ?? i)
        histStore.optimisticApplyCorrection?.(refIdStr)
        checkStoreApi.applyCorrectionInStore?.(refIdStr)
      }
      // Re-verify the applied refs in parallel (cap 4) so the badge updates.
      const queue = targets.slice()
      const worker = async () => {
        while (queue.length) {
          const { ref, i } = queue.shift()
          try { await verifyReferenceInCheck(selectedCheckId, String(ref.id ?? ref.index ?? i), { apply_correction: true }) } catch {}
        }
      }
      await Promise.all([worker(), worker(), worker(), worker()])
      await useHistoryStore.getState().selectCheck?.(selectedCheckId, { force: true })
      try { window.dispatchEvent(new Event('refchecker:usage-changed')) } catch { /* no-op */ }
    }
  }
  const resetDecisions = () => {
    // Reset the undo list AND roll back every optimistic correction so the
    // HealthBadge returns to the pre-apply value. Revert BOTH stores so the
    // chip moves for the historical view too (it reads selectedCheck.results),
    // not just the current-check view (useCheckStore.references).
    useCheckStore.getState().revertAllCorrections?.()
    useHistoryStore.getState().revertAllOptimisticCorrections?.()
    setDecisions({})
  }

  const startEditing = (k, currentText) => {
    setEditingKey(k); setEditBuffer(currentText)
  }
  const saveEdit = (k) => {
    setDecision(k, { status: 'edited', text: editBuffer })
    setEditingKey(null); setEditBuffer('')
  }
  const cancelEdit = () => { setEditingKey(null); setEditBuffer('') }

  // Font matched to the citation style (serif for narrative styles,
  // monospace for BibTeX/\bibitem). Applied to both diff sides + the
  // edit textarea so the preview matches what'll land in the document.
  const styleFont = STYLE_FONT[format] || 'inherit'
  const isMonoStyle = format === 'bibtex' || format === 'bibitem'

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
            {autoDetected && autoDetected === format && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded"
                style={{
                  backgroundColor: 'var(--color-bg-tertiary)',
                  color: 'var(--color-text-muted)',
                  border: '1px solid var(--color-border)',
                }}
                title="Auto-detected from the cited references"
              >
                auto
              </span>
            )}
            <select
              value={format}
              onChange={(e) => { userOverroteStyle.current = true; setFormat(e.target.value) }}
              className="px-2 py-1 rounded border text-xs"
              style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
              title="Citation style"
            >
              {CITATION_STYLES.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
              {customStyles.length > 0 && <optgroup label="Custom">
                {customStyles.map(s => <option key={s.id} value={`custom:${s.id}`}>{s.label || s.id}</option>)}
              </optgroup>}
            </select>
            <button
              onClick={() => setShowStyleCustomize(v => !v)}
              className="px-2 py-1 rounded-md text-xs font-medium"
              style={{
                border: '1px solid var(--color-border)',
                background: showStyleCustomize ? 'var(--color-bg-tertiary)' : 'var(--color-bg-primary)',
                color: 'var(--color-text-secondary)',
              }}
              title="Tune authors / URL / build a custom style"
            >
              {showStyleCustomize ? 'Hide style options' : 'Customize style'}
            </button>
          </div>
        </div>

        {showStyleCustomize && (
          <div
            className="rounded-md border p-3 mt-2 text-xs space-y-2"
            style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-tertiary)' }}
          >
            {!format.startsWith('custom:') && (
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-1">
                  Max authors:
                  <input
                    type="number" min="1" max="50"
                    value={effectiveOptions.max_authors ?? ''}
                    placeholder={String(styleDefaults.max_authors ?? '')}
                    onChange={(e) => setStyleOptions({ ...styleOptions, max_authors: e.target.value ? parseInt(e.target.value, 10) : null })}
                    className="px-1.5 py-0.5 rounded border w-16"
                    style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                  />
                </label>
                <label className="flex items-center gap-1">
                  Use et al. when ≥
                  <input
                    type="number" min="2" max="50"
                    value={effectiveOptions.et_al_threshold ?? ''}
                    placeholder={String(styleDefaults.et_al_threshold ?? '')}
                    onChange={(e) => setStyleOptions({ ...styleOptions, et_al_threshold: e.target.value ? parseInt(e.target.value, 10) : null })}
                    className="px-1.5 py-0.5 rounded border w-16"
                    style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                  />
                  authors
                </label>
                <label className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={effectiveOptions.include_url !== false}
                    onChange={(e) => setStyleOptions({ ...styleOptions, include_url: e.target.checked })}
                  />
                  Include URL
                </label>
                <button
                  onClick={() => setStyleOptions({})}
                  className="ml-auto underline"
                  style={{ color: 'var(--color-text-muted)' }}
                >Reset to style defaults</button>
              </div>
            )}

            <details className="mt-1">
              <summary className="cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>
                + New custom style (template)
              </summary>
              <div className="mt-2 space-y-2">
                <div className="flex gap-2 flex-wrap">
                  <input
                    placeholder="Name (e.g. 'Lancet')"
                    value={newCustomStyle.label}
                    onChange={(e) => setNewCustomStyle({ ...newCustomStyle, label: e.target.value })}
                    className="px-2 py-1 rounded border flex-1 min-w-[160px]"
                    style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                  />
                  <button
                    onClick={handleSaveCustomStyle}
                    className="px-3 py-1 rounded-md text-xs font-medium"
                    style={{ background: 'var(--color-accent, #3b82f6)', color: 'white' }}
                  >Save style</button>
                </div>
                <textarea
                  rows={2}
                  value={newCustomStyle.template}
                  onChange={(e) => setNewCustomStyle({ ...newCustomStyle, template: e.target.value })}
                  className="w-full px-2 py-1 rounded border font-mono"
                  style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)', fontSize: '0.75rem' }}
                />
                <div style={{ color: 'var(--color-text-muted)' }}>
                  Placeholders: <code>{'{authors}'}</code> <code>{'{title}'}</code> <code>{'{year}'}</code> <code>{'{venue}'}</code> <code>{'{doi}'}</code> <code>{'{arxiv_id}'}</code> <code>{'{url}'}</code> <code>{'{index}'}</code>
                </div>
              </div>
            </details>

            {customStyles.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-1">
                {customStyles.map(s => (
                  <span
                    key={s.id}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full"
                    style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                  >
                    {s.label || s.id}
                    <button
                      onClick={() => handleDeleteCustomStyle(s.id)}
                      style={{ color: 'var(--color-error, #ef4444)' }}
                      title="Delete this custom style"
                    >×</button>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

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
          <button onClick={() => setShowAdd(v => !v)} disabled={!selectedCheckId}
            className="px-3 py-1 rounded text-xs font-medium border"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
              opacity: selectedCheckId ? 1 : 0.5,
            }}
            type="button"
            title="Add a new reference to this check"
          >+ Add reference</button>
        </div>
      </div>

      {suggestFor && (
        <div className="p-3 rounded-lg border space-y-2"
          style={{ borderColor: 'var(--color-hallucination, #a855f7)', backgroundColor: 'rgba(168,85,247,0.06)' }}>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="text-xs font-medium" style={{ color: 'var(--color-text-primary)' }}>
              Real-paper candidates for the flagged reference
              <span style={{ color: 'var(--color-text-secondary)' }}> (top {suggestFor.candidates.length} from Semantic Scholar)</span>
            </div>
            <button onClick={() => setSuggestFor(null)} className="text-xs px-2 py-0.5 rounded border"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }} type="button">×</button>
          </div>
          {suggestFor.candidates.length === 0 ? (
            <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              No candidates found — the cited title may be too generic or genuinely fabricated.
            </div>
          ) : (
            <div className="space-y-1">
              {suggestFor.candidates.map((c, j) => (
                <div key={j} className="flex items-start justify-between gap-2 p-2 rounded border"
                  style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)' }}>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>{c.title}</div>
                    <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                      {(c.authors || []).slice(0, 4).join(', ')}{(c.authors || []).length > 4 ? ', et al.' : ''}
                      {c.year ? ` · ${c.year}` : ''}{c.doi ? ` · ${c.doi}` : ''}
                    </div>
                  </div>
                  {c.url && (
                    <a href={c.url} target="_blank" rel="noreferrer"
                      className="text-xs px-2 py-0.5 rounded flex-shrink-0"
                      style={{ backgroundColor: 'var(--color-accent, #3b82f6)', color: 'white' }}>
                      Open
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {showAdd && (
        <div className="p-3 rounded-lg border space-y-2"
          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}>
          <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            Adds a new reference to this check with status <code>pending</code>. Re-run the check to fully verify it.
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <input type="text" placeholder="Title" value={newRef.title} onChange={(e) => setNewRef({ ...newRef, title: e.target.value })} className="px-2 py-1 rounded border text-xs" style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }} />
            <input type="text" placeholder="Authors (comma-separated)" value={newRef.authors} onChange={(e) => setNewRef({ ...newRef, authors: e.target.value })} className="px-2 py-1 rounded border text-xs" style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }} />
            <input type="number" placeholder="Year" value={newRef.year} onChange={(e) => setNewRef({ ...newRef, year: e.target.value })} className="px-2 py-1 rounded border text-xs" style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }} />
            <input type="text" placeholder="DOI (10.xxxx/xxxx)" value={newRef.doi} onChange={(e) => setNewRef({ ...newRef, doi: e.target.value })} className="px-2 py-1 rounded border text-xs" style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }} />
            <input type="text" placeholder="arXiv ID" value={newRef.arxiv_id} onChange={(e) => setNewRef({ ...newRef, arxiv_id: e.target.value })} className="px-2 py-1 rounded border text-xs" style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }} />
          </div>
          <div className="flex gap-2">
            <button onClick={handleAddRef} disabled={busyKey === '__add__'}
              className="px-3 py-1 rounded text-xs font-medium"
              style={{ backgroundColor: 'var(--color-success, #22c55e)', color: 'white', opacity: busyKey === '__add__' ? 0.5 : 1 }}
              type="button"
            >{busyKey === '__add__' ? 'Adding…' : 'Save reference'}</button>
            <button onClick={() => setShowAdd(false)} className="px-3 py-1 rounded text-xs font-medium border" type="button"
              style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
            >Cancel</button>
          </div>
        </div>
      )}

      {/* Undo strip — appears after the user removes a ref from this
          tab. Mirrors the strip in the References tab so the same
          stash is visible regardless of which view did the remove. */}
      {removedRefs && removedRefs.length > 0 && (
        <div
          className="px-3 py-2 rounded-lg border text-xs flex items-center gap-2 flex-wrap"
          style={{
            borderColor: 'var(--color-border)',
            background: 'var(--color-bg-tertiary)',
            color: 'var(--color-text-secondary)',
          }}
        >
          <span style={{ fontWeight: 600 }}>
            Removed ({removedRefs.length})
          </span>
          <span style={{ color: 'var(--color-text-muted)' }}>
            — click Undo to put a reference back and re-verify.
          </span>
          <div className="flex flex-wrap gap-1.5 ml-auto">
            {removedRefs.slice(0, 6).map(snap => {
              const label = (snap.title || snap.doi || snap.arxiv_id || '(untitled)').toString()
              const short = label.length > 48 ? `${label.slice(0, 48)}…` : label
              return (
                <button
                  key={snap._stashKey}
                  onClick={() => handleRestoreRef(snap)}
                  disabled={!!globalBusy}
                  className="px-2 py-0.5 rounded-md"
                  style={{
                    border: '1px solid var(--color-border)',
                    background: 'var(--color-bg-primary)',
                    color: 'var(--color-text-secondary)',
                    opacity: globalBusy ? 0.6 : 1,
                  }}
                  title={`Undo remove: ${label}`}
                >
                  ↺ {short}
                </button>
              )
            })}
            {removedRefs.length > 6 && (
              <span style={{ color: 'var(--color-text-muted)' }}>
                +{removedRefs.length - 6} more
              </span>
            )}
            <button
              onClick={clearRemovedRefs}
              className="px-2 py-0.5 rounded-md"
              style={{
                border: '1px solid transparent',
                background: 'transparent',
                color: 'var(--color-text-muted)',
              }}
              title="Discard the undo list"
            >
              Clear
            </button>
          </div>
        </div>
      )}

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
                  <button onClick={() => applyAndReverify(ref, i)}
                    className="px-2 py-0.5 rounded text-xs"
                    style={{ backgroundColor: decision?.status === 'applied' ? 'var(--color-success, #22c55e)' : 'var(--color-bg-primary)',
                             color: decision?.status === 'applied' ? 'white' : 'var(--color-text-primary)',
                             border: '1px solid var(--color-border)' }}
                    type="button"
                  >Apply fix</button>
                  <button onClick={() => rejectCorrection(ref, i, key)}
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
                  {(decision?.status === 'applied' || decision?.status === 'edited') && (
                    <button onClick={() => restoreOriginal(ref, i)}
                      className="px-2 py-0.5 rounded text-xs"
                      style={{
                        backgroundColor: 'var(--color-bg-primary)',
                        color: 'var(--color-accent, #3b82f6)',
                        border: '1px solid var(--color-border)',
                      }}
                      type="button"
                      title={originalSnapshots[key]
                        ? 'Roll this fix back to the original cited values and re-verify.'
                        : 'No snapshot available for this row — pressing Restore just clears the local decision; the stored ref keeps the fix.'}
                    >↺ Restore</button>
                  )}
                  {tags.has('hallucination') && (() => {
                    const ident = String(ref.id ?? ref.index ?? i)
                    const suggesting = isSuggesting(ident)
                    const disabled = suggesting || !!globalBusy || !selectedCheckId
                    return (
                      <button onClick={() => handleSuggestAlt(ref, i)} disabled={disabled}
                        className="px-2 py-0.5 rounded text-xs"
                        style={{ backgroundColor: 'var(--color-hallucination, #a855f7)', color: 'white', opacity: disabled ? 0.5 : 1 }}
                        type="button"
                        title="Search Semantic Scholar for real papers matching this title"
                      >{suggesting ? '…' : 'Suggest alternative'}</button>
                    )
                  })()}
                  {(() => {
                    const ident = String(ref.id ?? ref.index ?? i)
                    const removing = isRemoving(ident)
                    const disabled = removing || !!globalBusy || !selectedCheckId
                    return (
                      <button onClick={() => handleRemoveRef(ref, i)} disabled={disabled}
                        className="px-2 py-0.5 rounded text-xs"
                        style={{
                          backgroundColor: 'var(--color-bg-primary)',
                          color: 'var(--color-error, #ef4444)',
                          border: '1px solid var(--color-border)',
                          opacity: disabled ? 0.5 : 1,
                        }}
                        type="button"
                        title="Drop this reference from the check (counters update live)"
                      >{removing ? '…' : 'Remove'}</button>
                    )
                  })()}
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2" style={{ backgroundColor: decisionTint }}>
                <div className="p-3" style={{ minWidth: 0 }}>
                  <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    As cited
                  </div>
                  <div style={{ color: 'var(--color-text-primary)' }}>
                    {ops ? <DiffSide ops={ops} side="cited" fontFamily={styleFont} /> : (
                      <pre className="text-xs whitespace-pre-wrap break-words m-0" style={{ fontFamily: styleFont }}>{citedStr}</pre>
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
                        className={`w-full p-2 rounded text-xs ${isMonoStyle ? 'font-mono' : ''}`}
                        style={{
                          backgroundColor: 'var(--color-bg-primary)',
                          color: 'var(--color-text-primary)',
                          border: '1px solid var(--color-border)',
                          fontFamily: styleFont,
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
                      {ops ? <DiffSide ops={ops} side="corrected" fontFamily={styleFont} /> : (
                        <pre className="text-xs whitespace-pre-wrap break-words m-0" style={{ fontFamily: styleFont }}>{correctedStr}</pre>
                      )}
                    </div>
                  )}
                  {/* "Source:" link removed in v0.7.25 — it surfaces the
                      verifier database URL which isn't a correction in
                      its own right. Users found it redundant noise on
                      the corrections card. The same URL still appears
                      in the References tab's Verification block where
                      it belongs as provenance, not as a fix to apply. */}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
