import { useEffect, useState } from 'react'
import {
  addReferenceToCheck,
  removeReferenceFromCheck,
  suggestAlternativeReference,
  verifyReferenceInCheck,
} from '../utils/api'
import { useHistoryStore } from '../stores/useHistoryStore'
import { useCheckStore } from '../stores/useCheckStore'

const EMPTY_NEW = { title: '', authors: '', year: '', doi: '', arxiv_id: '' }

export default function useReferenceActions() {
  const selectedCheckId = useHistoryStore(s => s.selectedCheckId)
  const [busyKey, setBusyKey] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [newRef, setNewRef] = useState(EMPTY_NEW)
  const [suggestFor, setSuggestFor] = useState(null)
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
    setBusyKey('__add__')
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
      setBusyKey(null)
    }
  }

  const handleRemoveRef = async (ref, i) => {
    if (!selectedCheckId) return
    const ident = String(ref.id ?? ref.index ?? i)
    setBusyKey(ident)
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
      setBusyKey(null)
    }
  }

  const handleRestoreRef = async (snapshot) => {
    if (!selectedCheckId || !snapshot) return
    setBusyKey('__restore__')
    try {
      const res = await addReferenceToCheck(selectedCheckId, {
        title: (snapshot.title || '').trim() || null,
        authors: (snapshot.authors || '').trim()
          ? snapshot.authors.split(',').map(s => s.trim()).filter(Boolean)
          : null,
        year: snapshot.year ? parseInt(snapshot.year, 10) : null,
        doi: (snapshot.doi || '').trim() || null,
        arxiv_id: (snapshot.arxiv_id || '').trim() || null,
        venue: (snapshot.venue || '').trim() || null,
      })
      const addedId = res?.data?.id ?? res?.data?.reference?.id ?? null
      if (addedId != null) {
        try {
          await verifyReferenceInCheck(selectedCheckId, String(addedId))
        } catch { /* re-verify is best-effort */ }
      }
      setRemovedRefs(prev => prev.filter(r => r._stashKey !== snapshot._stashKey))
      await reloadCheck()
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Restore failed')
    } finally {
      setBusyKey(null)
    }
  }

  const clearRemovedRefs = () => setRemovedRefs([])

  const handleSuggestAlt = async (ref, i) => {
    if (!selectedCheckId) return
    const ident = String(ref.id ?? ref.index ?? i)
    setBusyKey(ident)
    try {
      const res = await suggestAlternativeReference(selectedCheckId, ident)
      setSuggestFor({ ref_id: ident, candidates: res.data?.candidates || [] })
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Suggest failed')
    } finally {
      setBusyKey(null)
    }
  }

  const handleReverify = async (ref, i) => {
    if (!selectedCheckId) return
    const ident = String(ref.id ?? ref.index ?? i)
    setBusyKey(ident)
    try {
      await verifyReferenceInCheck(selectedCheckId, ident)
      await reloadCheck()
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Re-verify failed')
    } finally {
      setBusyKey(null)
    }
  }

  return {
    selectedCheckId,
    busyKey,
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
  }
}
