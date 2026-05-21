import { useState } from 'react'
import {
  addReferenceToCheck,
  removeReferenceFromCheck,
  suggestAlternativeReference,
  verifyReferenceInCheck,
} from '../utils/api'
import { useHistoryStore } from '../stores/useHistoryStore'

const EMPTY_NEW = { title: '', authors: '', year: '', doi: '', arxiv_id: '' }

export default function useReferenceActions() {
  const selectedCheckId = useHistoryStore(s => s.selectedCheckId)
  const [busyKey, setBusyKey] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [newRef, setNewRef] = useState(EMPTY_NEW)
  const [suggestFor, setSuggestFor] = useState(null)

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
    try {
      await removeReferenceFromCheck(selectedCheckId, ident)
      await reloadCheck()
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Remove failed')
    } finally {
      setBusyKey(null)
    }
  }

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
  }
}
