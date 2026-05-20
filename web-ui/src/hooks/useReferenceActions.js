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
    await useHistoryStore.getState().selectCheck?.(selectedCheckId)
  }

  const handleAddRef = async () => {
    if (!selectedCheckId) return null
    setBusyKey('__add__')
    try {
      const res = await addReferenceToCheck(selectedCheckId, {
        title: newRef.title.trim() || null,
        authors: newRef.authors.trim()
          ? newRef.authors.split(',').map(s => s.trim()).filter(Boolean)
          : null,
        year: newRef.year ? parseInt(newRef.year, 10) : null,
        doi: newRef.doi.trim() || null,
        arxiv_id: newRef.arxiv_id.trim() || null,
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
