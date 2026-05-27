import { useEffect, useRef, useState } from 'react'
import {
  addReferenceToCheck,
  removeReferenceFromCheck,
  suggestAlternativeReference,
  verifyReferenceInCheck,
} from '../utils/api'
import { useHistoryStore } from '../stores/useHistoryStore'
import { useCheckStore } from '../stores/useCheckStore'

const EMPTY_NEW = { title: '', authors: '', year: '', doi: '', arxiv_id: '' }

// Add/remove an ident from a Set state without mutating the previous value
// (zustand-style immutable update so React re-renders pick it up).
const enterBusy = (setter, ident) =>
  setter(prev => {
    const next = new Set(prev)
    next.add(ident)
    return next
  })
const leaveBusy = (setter, ident) =>
  setter(prev => {
    const next = new Set(prev)
    next.delete(ident)
    return next
  })

export default function useReferenceActions() {
  const selectedCheckId = useHistoryStore(s => s.selectedCheckId)
  // Per-action in-flight tracking, so Re-verify and Suggest-alternative
  // (and Remove) on the same row don't clobber each other's busy
  // indicators when the user fires them concurrently (#18). Each Set
  // holds the row idents currently running that action.
  const [reverifyBusy, setReverifyBusy] = useState(() => new Set())
  const [suggestBusy, setSuggestBusy] = useState(() => new Set())
  const [removeBusy, setRemoveBusy] = useState(() => new Set())
  // Global busy slot: '__add__' while Add-reference is in flight,
  // '__restore__' during Undo, null otherwise. Kept separate from the
  // per-row sets so per-row ops survive a parallel Undo.
  const [globalBusy, setGlobalBusy] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [newRef, setNewRef] = useState(EMPTY_NEW)
  const [suggestFor, setSuggestFor] = useState(null)
  // Track the most-recently-started Suggest so a slow earlier request
  // can't clobber the panel after the user moved on to a newer one.
  const latestSuggestRef = useRef(null)
  // Session-local "trash" so the user can Undo a removal. Scoped to the
  // currently-selected check — switching checks discards the trash.
  const [removedRefs, setRemovedRefs] = useState([])

  useEffect(() => {
    setRemovedRefs([])
  }, [selectedCheckId])

  const reloadCheck = async () => {
    if (!selectedCheckId) return
    // Force refetch — the store short-circuits same-id selects, but after an
    // Apply Fix / Re-verify we need the freshly-updated reference list so the
    // HealthBadge + Summary tiles recompute against the new statuses.
    await useHistoryStore.getState().selectCheck?.(selectedCheckId, { force: true })
  }

  const handleAddRef = async (override) => {
    if (!selectedCheckId) return null
    setGlobalBusy('__add__')
    // Accept an optional override patch so callers can pass in fields
    // that the parent's `newRef` state hasn't received yet (the "Add by
    // DOI" panel resolves a DOI on click — setNewRef is async, so by
    // the time handleAddRef reads its closure of `newRef`, the new DOI
    // hasn't landed yet. The override merges deterministically over the
    // closure's `newRef`, closing that race).
    const eff = { ...newRef, ...(override || {}) }
    try {
      const res = await addReferenceToCheck(selectedCheckId, {
        title: (eff.title || '').trim() || null,
        authors: (eff.authors || '').trim()
          ? eff.authors.split(',').map(s => s.trim()).filter(Boolean)
          : null,
        year: eff.year ? parseInt(eff.year, 10) : null,
        doi: (eff.doi || '').trim() || null,
        arxiv_id: (eff.arxiv_id || '').trim() || null,
      })
      const addedId = res?.data?.id ?? res?.data?.reference?.id ?? null
      setShowAdd(false)
      setNewRef(EMPTY_NEW)
      // Kick off live re-verification on the new ref so the UI doesn't
      // sit on a permanent 'pending'.
      if (addedId != null) {
        try {
          await verifyReferenceInCheck(selectedCheckId, String(addedId))
        } catch {
          /* server may not support it yet; reload still surfaces the row */
        }
      }
      await reloadCheck()
      return addedId
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Add failed')
      return null
    } finally {
      setGlobalBusy(null)
    }
  }

  const handleRemoveRef = async (ref, i) => {
    if (!selectedCheckId) return
    const ident = String(ref.id ?? ref.index ?? i)
    enterBusy(setRemoveBusy, ident)
    // Snapshot the ref so Undo can re-create it. We stash the metadata
    // the add endpoint needs, plus a synthetic key so the UI can render
    // a stable list of removed items.
    const snapshot = {
      _stashKey: `${ident}-${Date.now()}`,
      title: ref.title || '',
      authors: Array.isArray(ref.authors) ? ref.authors.join(', ') : (ref.authors || ''),
      year: ref.year ?? '',
      doi: ref.doi || '',
      arxiv_id: ref.arxiv_id || '',
      venue: ref.venue || '',
    }
    // Optimistically drop from the live checkStore feed. When the user
    // is viewing the active check, displayRefs comes from checkStore,
    // not from selectedCheck.results — without this, the row stays
    // visible and the health badge doesn't move until they navigate
    // away and back.
    const removedFromStore = (useCheckStore.getState().references || []).find(
      (r, idx) => (
        String(r?.id ?? '') === ident ||
        String(r?.index ?? '') === ident ||
        String(idx) === ident
      )
    )
    useCheckStore.getState().removeReference(ident)
    try {
      await removeReferenceFromCheck(selectedCheckId, ident)
      setRemovedRefs(prev => [snapshot, ...prev].slice(0, 20))
      await reloadCheck()
    } catch (e) {
      // Server rejected the delete — put the ref back so the optimistic
      // remove doesn't strand the UI in a worse state than it started.
      if (removedFromStore) useCheckStore.getState().restoreReference(removedFromStore)
      alert(e?.response?.data?.detail || e?.message || 'Remove failed')
    } finally {
      leaveBusy(setRemoveBusy, ident)
    }
  }

  const handleRestoreRef = async (snapshot) => {
    if (!selectedCheckId || !snapshot) return
    setGlobalBusy('__restore__')
    // Optimistic put-back: drop a placeholder row into the live
    // checkStore *immediately* so the user sees the restore instantly
    // instead of staring at a spinning button for the 5-10s the
    // network roundtrip + re-verify takes.
    const optimisticId = `restoring-${snapshot._stashKey}`
    const authorsArr = (snapshot.authors || '').trim()
      ? snapshot.authors.split(',').map(s => s.trim()).filter(Boolean)
      : []
    const placeholder = {
      id: optimisticId,
      title: snapshot.title || '',
      authors: authorsArr,
      year: snapshot.year || null,
      doi: snapshot.doi || null,
      arxiv_id: snapshot.arxiv_id || null,
      venue: snapshot.venue || null,
      status: 'pending',
      errors: [],
      warnings: [],
      suggestions: [{ message: 'Restoring…', error_type: 'manual' }],
    }
    try {
      useCheckStore.getState().restoreReference(placeholder)
    } catch { /* store may not have action yet */ }
    // Pop from the trash strip right away — user sees the placeholder
    // in the list and the trash entry gone in the same render.
    setRemovedRefs(prev => prev.filter(r => r._stashKey !== snapshot._stashKey))
    try {
      const res = await addReferenceToCheck(selectedCheckId, {
        title: (snapshot.title || '').trim() || null,
        authors: authorsArr.length ? authorsArr : null,
        year: snapshot.year ? parseInt(snapshot.year, 10) : null,
        doi: (snapshot.doi || '').trim() || null,
        arxiv_id: (snapshot.arxiv_id || '').trim() || null,
        venue: (snapshot.venue || '').trim() || null,
      })
      const addedId = res?.data?.id ?? res?.data?.reference?.id ?? null
      // Re-verify runs in the background — don't await. The reload
      // below will pick up its result on the next progress tick.
      if (addedId != null) {
        verifyReferenceInCheck(selectedCheckId, String(addedId)).catch(() => {})
      }
      // reload picks up the real persisted row (with the server-assigned
      // manual-XXX id) and replaces our placeholder.
      await reloadCheck()
    } catch (e) {
      // Roll back the optimistic restore and put the ref back in the trash.
      try { useCheckStore.getState().removeReference(optimisticId) } catch { /* */ }
      setRemovedRefs(prev => [snapshot, ...prev])
      alert(e?.response?.data?.detail || e?.message || 'Restore failed')
    } finally {
      setGlobalBusy(null)
    }
  }

  const clearRemovedRefs = () => setRemovedRefs([])

  const handleSuggestAlt = async (ref, i) => {
    if (!selectedCheckId) return
    const ident = String(ref.id ?? ref.index ?? i)
    enterBusy(setSuggestBusy, ident)
    latestSuggestRef.current = ident
    try {
      const res = await suggestAlternativeReference(selectedCheckId, ident)
      // Discard the result if the user has since started a newer Suggest
      // (e.g. clicked Suggest on a different row while this one was slow).
      // Without this, a slower earlier response can overwrite the panel
      // the user is actively reading.
      if (latestSuggestRef.current === ident) {
        setSuggestFor({ ref_id: ident, candidates: res.data?.candidates || [] })
      }
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Suggest failed')
    } finally {
      leaveBusy(setSuggestBusy, ident)
    }
  }

  const handleReverify = async (ref, i) => {
    if (!selectedCheckId) return
    const ident = String(ref.id ?? ref.index ?? i)
    enterBusy(setReverifyBusy, ident)
    try {
      await verifyReferenceInCheck(selectedCheckId, ident)
      await reloadCheck()
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Re-verify failed')
    } finally {
      leaveBusy(setReverifyBusy, ident)
    }
  }

  // Back-compat: a few callers (AddReferencePanel) still expect a single
  // `busyKey` string. Map the global slot onto it so '__add__'/'__restore__'
  // sentinels keep working without touching those components.
  const busyKey = globalBusy

  const isReverifying = (ident) => reverifyBusy.has(String(ident))
  const isSuggesting = (ident) => suggestBusy.has(String(ident))
  const isRemoving = (ident) => removeBusy.has(String(ident))

  return {
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
    handleReverify,
    removedRefs,
    handleRestoreRef,
    clearRemovedRefs,
    isReverifying,
    isSuggesting,
    isRemoving,
  }
}
