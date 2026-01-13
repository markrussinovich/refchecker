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

          const verifiedCount = Math.max((detail.total_refs || 0) - (detail.errors_count || 0) - (detail.warnings_count || 0) - (detail.suggestions_count || 0) - (detail.unverified_count || 0), 0)

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
              suggestions_count: detail.suggestions_count || 0,
              unverified_count: detail.unverified_count || 0,
              refs_with_issues: detail.refs_with_issues || 0,
              refs_verified: detail.refs_verified || verifiedCount,
              progress_percent: 100,
            },
            completedCheckId: detail.status === 'completed' ? detail.id : null,
          })
        } catch (hydrateErr) {
          logger.error('HistoryStore', 'Failed to hydrate current check detail', hydrateErr)
        }
      }

      // For in_progress items, fetch detail to get current progress and results
      const inProgressItems = historyWorking
        .filter(item => item.status === 'in_progress')
        .slice(0, 5) // cap to avoid excessive calls

      for (const item of inProgressItems) {
        try {
          const detail = (await api.getCheckDetail(item.id)).data
          
          // Calculate processed_refs from results array (completed checks have status != pending/checking)
          const results = Array.isArray(detail.results) ? detail.results : []
          const processedRefs = results.filter(r => r && r.status && r.status !== 'pending' && r.status !== 'checking').length
          
          // Update the item with full progress info
          historyWorking = historyWorking.map(h => h.id === item.id
            ? {
                ...h,
                status: detail.status || 'in_progress',
                total_refs: detail.total_refs || 0,
                processed_refs: processedRefs,
                errors_count: detail.errors_count || 0,
                warnings_count: detail.warnings_count || 0,
                suggestions_count: detail.suggestions_count || 0,
                unverified_count: detail.unverified_count || 0,
                refs_with_errors: detail.refs_with_errors || 0,
                refs_with_warnings_only: detail.refs_with_warnings_only || 0,
                results: results, // Store results for display
                session_id: item.session_id, // Preserve session_id from history API
              }
            : h)
          
          // Register this session for WebSocket reconnection
          if (item.session_id && detail.status === 'in_progress') {
            useCheckStore.getState().registerSession(item.session_id, item.id)
          }
          
          logger.info('HistoryStore', 'Loaded progress for in_progress item', { 
            id: item.id, 
            status: detail.status, 
            total_refs: detail.total_refs,
            processed_refs: processedRefs,
            session_id: item.session_id
          })
        } catch (err) {
          logger.warn('HistoryStore', 'Failed to load in_progress item detail', { id: item.id, error: err?.message })
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
            suggestions_count: checkState.stats?.suggestions_count || 0,
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
      
      // First, merge fetched items with existing in-memory state
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
      
      // Also preserve any locally-added items (e.g., just-started checks) that aren't in the fetch results yet
      // Only preserve items that are in_progress (active checks) - completed/error items not in API were deleted
      const fetchedIds = new Set(historyWithActive.map(h => h.id))
      const localOnlyItems = currentHistory.filter(h => 
        h.id !== -1 && 
        !fetchedIds.has(h.id) && 
        h.status === 'in_progress'  // Only preserve in-progress items (newly started checks)
      )
      if (localOnlyItems.length > 0) {
        logger.info('HistoryStore', `Preserving ${localOnlyItems.length} locally-added items not yet in API`)
        // Add them at the beginning (most recent first)
        mergedHistory.unshift(...localOnlyItems)
      }
      
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

          // Only adopt session if this is a reconnection (not the session we just started)
          // Don't adopt if we're already checking (means we just started a new check)
          const checkStoreState = useCheckStore.getState()
          const isAlreadyChecking = checkStoreState.status === 'checking'
          const isSameSession = checkStoreState.sessionId === check.session_id
          if (check.status === 'in_progress' && check.session_id && !isAlreadyChecking && !isSameSession) {
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
    
    logger.info('HistoryStore', 'Starting initializeWithPlaceholder API call')
    
    // Create a timeout promise to prevent indefinite waiting
    const timeoutPromise = new Promise((_, reject) => 
      setTimeout(() => reject(new Error('Connection timeout - backend may not be running')), 10000)
    )
    
    try {
      // Race between the API call and the timeout
      const response = await Promise.race([
        api.getHistory(limit),
        timeoutPromise
      ])
      const fetched = response.data
      let historyWorking = Array.isArray(fetched) ? [...fetched] : []

      // For in_progress items, fetch detail to get current progress and results
      const inProgressItems = historyWorking
        .filter(item => item.status === 'in_progress')
        .slice(0, 5)

      for (const item of inProgressItems) {
        try {
          const detail = (await api.getCheckDetail(item.id)).data
          
          // Calculate processed_refs from results array
          const results = Array.isArray(detail.results) ? detail.results : []
          const processedRefs = results.filter(r => r && r.status && r.status !== 'pending' && r.status !== 'checking').length
          
          // Update the item with full progress info
          historyWorking = historyWorking.map(h => h.id === item.id
            ? {
                ...h,
                status: detail.status || 'in_progress',
                total_refs: detail.total_refs || 0,
                processed_refs: processedRefs,
                errors_count: detail.errors_count || 0,
                warnings_count: detail.warnings_count || 0,
                suggestions_count: detail.suggestions_count || 0,
                unverified_count: detail.unverified_count || 0,
                refs_with_errors: detail.refs_with_errors || 0,
                refs_with_warnings_only: detail.refs_with_warnings_only || 0,
                results: results,
                session_id: item.session_id,
              }
            : h)
          
          // Register this session for WebSocket reconnection
          if (item.session_id && detail.status === 'in_progress') {
            useCheckStore.getState().registerSession(item.session_id, item.id)
          }
          
          logger.info('HistoryStore', 'Startup: loaded progress for in_progress item', { 
            id: item.id, 
            status: detail.status, 
            total_refs: detail.total_refs,
            processed_refs: processedRefs,
            session_id: item.session_id
          })
        } catch (err) {
          logger.warn('HistoryStore', 'Startup: failed to load in_progress item detail', { id: item.id, error: err?.message })
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
        suggestions_count: 0,
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
      
      // Even on error, initialize with placeholder so user can still use the app
      const placeholder = {
        id: -1,
        paper_title: 'New refcheck',
        paper_source: '',
        custom_label: null,
        timestamp: null,
        total_refs: 0,
        errors_count: 0,
        warnings_count: 0,
        suggestions_count: 0,
        unverified_count: 0,
        llm_provider: null,
        llm_model: null,
        status: 'idle',
        source_type: 'url',
        placeholder: true,
      }
      
      set({ 
        history: [placeholder],
        error: error.message, 
        isLoading: false,
        selectedCheckId: -1,
        selectedCheck: null,
      })
      logger.info('HistoryStore', 'Initialized with placeholder only (API error)')
    }
  },

  selectCheck: async (id) => {
    // Special placeholder for starting a new check without hitting the API
    if (id === -1) {
      set({ selectedCheckId: -1, selectedCheck: null, isLoadingDetail: false, error: null })
      return
    }

    // Check if we already have in-memory data for an in-progress check (from WebSocket updates)
    const existingHistoryItem = get().history.find(h => h.id === id)
    const hasLiveUpdates = existingHistoryItem?.status === 'in_progress' && existingHistoryItem?.total_refs > 0

    // If we have an in-progress check with results in memory, use that directly without API call
    if (existingHistoryItem?.status === 'in_progress' && existingHistoryItem?.results?.length > 0) {
      set({ 
        selectedCheckId: id, 
        selectedCheck: existingHistoryItem, 
        isLoadingDetail: false, 
        error: null 
      })
      return
    }

    // Set selectedCheckId immediately so UI can react
    set({ selectedCheckId: id, isLoadingDetail: true, error: null })
    try {
      logger.info('HistoryStore', `Loading check details for ${id}`)
      const response = await api.getCheckDetail(id)
      const check = response.data
      
      // Only adopt session if this is a reconnection (not the session we just started)
      // Don't adopt if we're already checking (means we just started a new check)
      const checkStoreState = useCheckStore.getState()
      const isAlreadyChecking = checkStoreState.status === 'checking'
      const isSameSession = checkStoreState.sessionId === check.session_id
      if (check.status === 'in_progress' && check.session_id && !isAlreadyChecking && !isSameSession) {
        useCheckStore.getState().adoptSession(check)
      }

      // Sync history list item, but DON'T overwrite WebSocket updates with stale backend data
      // Use priority-based merge: completed > in_progress, and higher counts win
      const statusPriority = { 'completed': 3, 'error': 2, 'cancelled': 2, 'in_progress': 1, 'idle': 0 }
      
      set(state => {
        const existingItem = state.history.find(h => h.id === id)
        const existingPriority = statusPriority[existingItem?.status] ?? 0
        const fetchedPriority = statusPriority[check.status] ?? 0
        
        // If in-memory has higher priority status, or same status with more progress data, keep in-memory
        const existingProcessed = existingItem?.processed_refs || 0
        const fetchedProcessed = check.processed_refs || 0
        const keepExisting = existingItem && (
          existingPriority > fetchedPriority ||
          (existingPriority === fetchedPriority && existingItem.status === 'in_progress' && existingProcessed > fetchedProcessed)
        )
        
        // For selectedCheck, merge in-memory data into fetched results
        // Preserve in-memory results if they exist and have more data than API results
        const existingResults = existingItem?.results || []
        const fetchedResults = check.results || []
        const useExistingResults = existingResults.length > 0 && 
          (fetchedResults.length === 0 || existingResults.length >= fetchedResults.length)
        
        const mergedSelectedCheck = keepExisting && existingItem.status === 'in_progress'
          ? { 
              ...check, 
              status: existingItem.status,
              total_refs: existingItem.total_refs || check.total_refs,
              processed_refs: existingItem.processed_refs || check.processed_refs,
              errors_count: existingItem.errors_count ?? check.errors_count,
              warnings_count: existingItem.warnings_count ?? check.warnings_count,
              suggestions_count: existingItem.suggestions_count ?? check.suggestions_count,
              unverified_count: existingItem.unverified_count ?? check.unverified_count,
              results: useExistingResults ? existingResults : fetchedResults,
            }
          : {
              ...check,
              // Even if not keeping existing status, preserve results if in-memory has more
              results: useExistingResults ? existingResults : fetchedResults,
            }
        
        return {
          selectedCheck: mergedSelectedCheck,
          isLoadingDetail: false,
          selectedCheckId: id,
          history: state.history.map(h =>
            h.id === id
              ? keepExisting
                ? h  // Keep existing history item as-is
                : {
                    ...h,
                    status: check.status,
                    total_refs: check.total_refs,
                    processed_refs: check.processed_refs,
                    errors_count: check.errors_count,
                    warnings_count: check.warnings_count,
                    suggestions_count: check.suggestions_count,
                    unverified_count: check.unverified_count,
                    refs_with_errors: check.refs_with_errors,
                    refs_with_warnings_only: check.refs_with_warnings_only,
                    paper_title: check.paper_title || h.paper_title,
                  }
              : h
          ),
        }
      })
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
    if (!id) {
      logger.warn('HistoryStore', 'updateHistoryProgress called with no id')
      return
    }
    set(state => ({
      history: state.history.map(h => h.id === id ? { ...h, ...payload } : h),
      selectedCheck: state.selectedCheck?.id === id ? { ...state.selectedCheck, ...payload } : state.selectedCheck,
    }))
  },

  // Update a single reference result within a history item (for concurrent session updates)
  updateHistoryReference: (checkId, refIndex, refData) => {
    if (!checkId || refIndex < 0) {
      logger.warn('HistoryStore', 'updateHistoryReference called with invalid args', { checkId, refIndex })
      return
    }
    
    set(state => {
      // Update in history array
      const newHistory = state.history.map(h => {
        if (h.id !== checkId) return h
        if (!h.results || refIndex >= h.results.length) return h
        
        const newResults = [...h.results]
        newResults[refIndex] = { ...newResults[refIndex], ...refData }
        return { ...h, results: newResults }
      })
      
      // Update in selectedCheck if it matches
      let newSelectedCheck = state.selectedCheck
      if (state.selectedCheck?.id === checkId && state.selectedCheck?.results) {
        const newResults = [...state.selectedCheck.results]
        if (refIndex < newResults.length) {
          newResults[refIndex] = { ...newResults[refIndex], ...refData }
          newSelectedCheck = { ...state.selectedCheck, results: newResults }
        }
      }
      
      return { history: newHistory, selectedCheck: newSelectedCheck }
    })
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
        suggestions_count: 0,
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
