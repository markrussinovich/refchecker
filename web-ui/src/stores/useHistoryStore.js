import { create } from 'zustand'
import { logger } from '../utils/logger'
import * as api from '../utils/api'
import { useCheckStore } from './useCheckStore'

/**
 * Store for check history management
 */
export const useHistoryStore = create((set, get) => ({
  // State
  history: [],
  selectedCheckId: null,
  selectedCheck: null,
  isLoading: false,
  isLoadingDetail: false,
  error: null,
  placeholderAdded: false, // tracks whether we've already injected the placeholder automatically

  // Actions
  fetchHistory: async (limit = 50) => {
    logger.info('HistoryStore', 'fetchHistory called')
    
    set({ isLoading: true, error: null })
    try {
      const response = await api.getHistory(limit)
      const fetched = response.data
      let historyWorking = Array.isArray(fetched) ? [...fetched] : []
      const checkState = useCheckStore.getState()
      const hasActiveCheck = checkState.status === 'checking' && !!checkState.currentCheckId
      const activeInList = hasActiveCheck && historyWorking.some(item => item.id === checkState.currentCheckId)

      // If backend now shows the current check as finished, hydrate CheckStore with the latest detail
      const currentItem = historyWorking.find(item => item.id === checkState.currentCheckId)
      if (currentItem && hasActiveCheck && currentItem.status !== 'in_progress') {
        logger.info('HistoryStore', 'Detected completed/non-in-progress state for current check, hydrating detail', { id: currentItem.id, status: currentItem.status })
        try {
          const detail = (await api.getCheckDetail(currentItem.id)).data

          const verifiedCount = Math.max((detail.total_refs || 0) - (detail.errors_count || 0) - (detail.warnings_count || 0) - (detail.unverified_count || 0), 0)

          useCheckStore.setState({
            status: detail.status || 'completed',
            statusMessage: detail.status === 'completed' ? 'Check completed' : `Status: ${detail.status || ''}`,
            currentCheckId: detail.id,
            paperTitle: detail.paper_title,
            paperSource: detail.paper_source,
            references: Array.isArray(detail.results)
              ? detail.results.map((ref, index) => ({
                  ...ref,
                  index,
                  status: ref.status || 'checked',
                  errors: ref.errors || [],
                  warnings: ref.warnings || [],
                  authoritative_urls: ref.authoritative_urls || [],
                }))
              : [],
            stats: {
              total_refs: detail.total_refs || 0,
              processed_refs: detail.total_refs || 0,
              verified_count: verifiedCount,
              errors_count: detail.errors_count || 0,
              warnings_count: detail.warnings_count || 0,
              unverified_count: detail.unverified_count || 0,
              progress_percent: 100,
            },
            completedCheckId: detail.status === 'completed' ? detail.id : null,
          })
        } catch (hydrateErr) {
          logger.error('HistoryStore', 'Failed to hydrate current check detail', hydrateErr)
        }
      }

      // Opportunistically fix stale in_progress items (no active session) by reconciling detail or marking as completed
      const staleInProgress = historyWorking
        .filter(item => item.status === 'in_progress')
        .slice(0, 3) // cap to avoid excessive calls

      for (const item of staleInProgress) {
        try {
          const detail = (await api.getCheckDetail(item.id)).data
          if (detail.status && detail.status !== item.status) {
            logger.info('HistoryStore', 'Updating stale history item from detail', { id: item.id, status: detail.status })
            historyWorking = historyWorking.map(h => h.id === item.id
              ? {
                  ...h,
                  status: detail.status,
                  total_refs: detail.total_refs,
                  errors_count: detail.errors_count,
                  warnings_count: detail.warnings_count,
                  unverified_count: detail.unverified_count,
                }
              : h)
            continue
          }

          // Do not override active in-progress items; keep status as-is even if session_id is missing
        } catch (err) {
          logger.warn('HistoryStore', 'Failed to refresh stale in_progress item', { id: item.id, error: err?.message })
        }
      }


      // If backend didn't return the active check yet, inject a client-side placeholder
      const historyWithActive = (!activeInList && hasActiveCheck)
        ? [{
            id: checkState.currentCheckId,
            paper_title: checkState.paperTitle || checkState.paperSource || 'In-progress check',
            paper_source: checkState.paperSource || '',
            custom_label: null,
            timestamp: new Date().toISOString(),
            total_refs: checkState.stats?.total_refs || 0,
            errors_count: checkState.stats?.errors_count || 0,
            warnings_count: checkState.stats?.warnings_count || 0,
            unverified_count: checkState.stats?.unverified_count || 0,
            llm_provider: null,
            llm_model: null,
            status: 'in_progress',
            source_type: 'url',
            placeholder: false,
          }, ...historyWorking]
        : historyWorking
      if (!activeInList && hasActiveCheck) {
        logger.info('HistoryStore', 'Injected active check into history', { id: checkState.currentCheckId })
      }
      
      logger.info('HistoryStore', `Fetched ${historyWithActive.length} items (including injected) from API`)
      
      // Merge fetched history with in-memory state, preserving WebSocket-provided updates
      // that are "more complete" (e.g., completed > in_progress)
      const statusPriority = { 'completed': 3, 'error': 2, 'cancelled': 2, 'in_progress': 1, 'idle': 0 }
      const currentHistory = get().history
      
      const mergedHistory = historyWithActive.map(fetched => {
        const existing = currentHistory.find(h => h.id === fetched.id)
        if (!existing) return fetched
        
        // If in-memory status is "more complete" than fetched, preserve in-memory data
        const existingPriority = statusPriority[existing.status] ?? 0
        const fetchedPriority = statusPriority[fetched.status] ?? 0
        
        if (existingPriority > fetchedPriority) {
          logger.info('HistoryStore', `Preserving in-memory status for ${fetched.id}`, { 
            inMemory: existing.status, 
            fetched: fetched.status 
          })
          return { ...fetched, ...existing }
        }
        return fetched
      })
      
      set({ history: mergedHistory, isLoading: false })
      logger.info('HistoryStore', `Set ${mergedHistory.length} history items (merged)`)

      // Keep selected check detail in sync with updated history status
      const { selectedCheckId, selectedCheck } = get()
      const selectedFromList = historyWithActive.find(h => h.id === selectedCheckId)
      const statusChanged = selectedFromList && selectedCheck && selectedFromList.status !== selectedCheck.status
      const needsDetailRefresh = selectedCheckId !== null && selectedCheckId !== -1 && (statusChanged || !selectedCheck)

      if (needsDetailRefresh) {
        logger.info('HistoryStore', `Refreshing selected check ${selectedCheckId} after history fetch`)
        try {
          const detailResp = await api.getCheckDetail(selectedCheckId)
          const check = detailResp.data

          if (check.status === 'in_progress' && check.session_id) {
            useCheckStore.getState().adoptSession(check)
          }

          set({ selectedCheck: check })
        } catch (err) {
          logger.error('HistoryStore', `Failed to refresh selected check ${selectedCheckId}`, err)
        }
      }
    } catch (error) {
      logger.error('HistoryStore', 'Failed to fetch history', error)
      set({ error: error.message, isLoading: false })
    }
  },
  
  // Called once on app startup to ensure placeholder exists
  initializeWithPlaceholder: async (limit = 50) => {
    const state = get()
    if (state.placeholderAdded) {
      logger.info('HistoryStore', 'Placeholder already added, skipping initialization')
      return
    }
    
    // Mark as added immediately to prevent duplicate calls
    set({ placeholderAdded: true, isLoading: true, error: null })
    
    try {
      const response = await api.getHistory(limit)
      const fetched = response.data
      let historyWorking = Array.isArray(fetched) ? [...fetched] : []

      // Reconcile stale in-progress items on startup as well
      const staleInProgress = historyWorking
        .filter(item => item.status === 'in_progress')
        .slice(0, 3)

      for (const item of staleInProgress) {
        try {
          const detail = (await api.getCheckDetail(item.id)).data
          if (detail.status && detail.status !== item.status) {
            logger.info('HistoryStore', 'Startup reconcile: updating stale item from detail', { id: item.id, status: detail.status })
            historyWorking = historyWorking.map(h => h.id === item.id
              ? {
                  ...h,
                  status: detail.status,
                  total_refs: detail.total_refs,
                  errors_count: detail.errors_count,
                  warnings_count: detail.warnings_count,
                  unverified_count: detail.unverified_count,
                }
              : h)
            continue
          }

          // Avoid force-completing items that still report in_progress but lack a session_id
        } catch (err) {
          logger.warn('HistoryStore', 'Startup reconcile failed for in_progress item', { id: item.id, error: err?.message })
        }
      }

      logger.info('HistoryStore', `Fetched ${historyWorking.length} items, adding placeholder`)
      
      const placeholder = {
        id: -1,
        paper_title: 'New refcheck',
        paper_source: '',
        custom_label: null,
        timestamp: null,
        total_refs: 0,
        errors_count: 0,
        warnings_count: 0,
        unverified_count: 0,
        llm_provider: null,
        llm_model: null,
        status: 'idle',
        source_type: 'url',
        placeholder: true,
      }
      
      set({
        history: [placeholder, ...historyWorking],
        isLoading: false,
        selectedCheckId: -1,
        selectedCheck: null,
      })
      logger.info('HistoryStore', `Initialized with placeholder and ${historyWorking.length} history items`)
    } catch (error) {
      logger.error('HistoryStore', 'Failed to initialize history', error)
      set({ error: error.message, isLoading: false })
    }
  },

  selectCheck: async (id) => {
    // Special placeholder for starting a new check without hitting the API
    if (id === -1) {
      set({ selectedCheckId: -1, selectedCheck: null, isLoadingDetail: false, error: null })
      return
    }

    // Always fetch fresh data to ensure history stays in sync with source of truth
    set({ selectedCheckId: id, isLoadingDetail: true, error: null })
    try {
      logger.info('HistoryStore', `Loading check details for ${id}`)
      const response = await api.getCheckDetail(id)
      const check = response.data
      
      if (check.status === 'in_progress' && check.session_id) {
        useCheckStore.getState().adoptSession(check)
      }

      // Sync history list item with the authoritative detail (source of truth)
      set(state => ({
        selectedCheck: check,
        isLoadingDetail: false,
        selectedCheckId: id,
        history: state.history.map(h =>
          h.id === id
            ? {
                ...h,
                status: check.status,
                total_refs: check.total_refs,
                errors_count: check.errors_count,
                warnings_count: check.warnings_count,
                unverified_count: check.unverified_count,
                paper_title: check.paper_title || h.paper_title,
              }
            : h
        ),
      }))
      logger.info('HistoryStore', 'Check details loaded and history synced', { 
        title: check.paper_title,
        refs: check.total_refs,
        status: check.status,
      })
    } catch (error) {
      logger.error('HistoryStore', 'Failed to load check details', error)
      set({ error: error.message, isLoadingDetail: false })
    }
  },

  clearSelection: () => {
    set({ selectedCheckId: null, selectedCheck: null })
  },

  updateLabel: async (id, label) => {
    if (id === -1) return // don't persist or label the placeholder
    try {
      logger.info('HistoryStore', `Updating label for ${id}`, { label })
      await api.updateCheckLabel(id, label)
      
      set(state => ({
        history: state.history.map(h => 
          h.id === id ? { ...h, custom_label: label } : h
        ),
        selectedCheck: state.selectedCheck?.id === id 
          ? { ...state.selectedCheck, custom_label: label }
          : state.selectedCheck
      }))
      
      logger.info('HistoryStore', 'Label updated')
    } catch (error) {
      logger.error('HistoryStore', 'Failed to update label', error)
      throw error
    }
  },

  updateHistoryProgress: (id, payload = {}) => {
    if (!id) return
    set(state => ({
      history: state.history.map(h => h.id === id ? { ...h, ...payload } : h),
      selectedCheck: state.selectedCheck?.id === id ? { ...state.selectedCheck, ...payload } : state.selectedCheck,
    }))
  },

  deleteCheck: async (id) => {
    if (id === -1) {
      // Drop the placeholder locally
      set(state => ({
        history: state.history.filter(h => h.id !== -1),
        selectedCheckId: state.selectedCheckId === -1 ? null : state.selectedCheckId,
        selectedCheck: state.selectedCheckId === -1 ? null : state.selectedCheck,
      }))
      return
    }
    try {
      logger.info('HistoryStore', `Deleting check ${id}`)
      await api.deleteCheck(id)
      
      set(state => ({
        history: state.history.filter(h => h.id !== id),
        selectedCheckId: state.selectedCheckId === id ? null : state.selectedCheckId,
        selectedCheck: state.selectedCheck?.id === id ? null : state.selectedCheck
      }))
      
      logger.info('HistoryStore', 'Check deleted')
    } catch (error) {
      logger.error('HistoryStore', 'Failed to delete check', error)
      throw error
    }
  },

  addToHistory: (check) => {
    logger.info('HistoryStore', 'Adding check to history', { id: check.id })
    set(state => ({
      // Remove placeholder when a real check is added
      history: [check, ...state.history.filter(h => h.id !== -1)],
      // Keep placeholderAdded true so placeholder doesn't auto-appear; user must click "New refcheck" button
    }))
  },

  ensureNewRefcheckItem: () => {
    set(state => {
      const exists = state.history.some(h => h.id === -1)
      if (exists) return { ...state, placeholderAdded: true }
      const placeholder = {
        id: -1,
        paper_title: 'New refcheck',
        paper_source: '',
        custom_label: null,
        timestamp: null,
        total_refs: 0,
        errors_count: 0,
        warnings_count: 0,
        unverified_count: 0,
        llm_provider: null,
        llm_model: null,
        status: 'idle',
        source_type: 'url',
        placeholder: true,
      }
      return { history: [placeholder, ...state.history], placeholderAdded: true }
    })
  },

  updateHistoryItemTitle: (id, paper_title) => {
    logger.info('HistoryStore', `Updating title for ${id}`, { paper_title })
    set(state => ({
      history: state.history.map(h => 
        h.id === id ? { ...h, paper_title } : h
      ),
      selectedCheck: state.selectedCheck?.id === id 
        ? { ...state.selectedCheck, paper_title }
        : state.selectedCheck
    }))
  },
}))
