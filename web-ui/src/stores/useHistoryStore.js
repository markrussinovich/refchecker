import { create } from 'zustand'
import { logger } from '../utils/logger'
import * as api from '../utils/api'

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
      
      logger.info('HistoryStore', `Fetched ${fetched.length} items from API`)
      
      // Just set the fetched history - placeholder logic is handled separately
      set({ history: fetched, isLoading: false })
      logger.info('HistoryStore', `Set ${fetched.length} history items`)
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
      
      logger.info('HistoryStore', `Fetched ${fetched.length} items, adding placeholder`)
      
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
        history: [placeholder, ...fetched],
        isLoading: false,
        selectedCheckId: -1,
        selectedCheck: null,
      })
      logger.info('HistoryStore', `Initialized with placeholder and ${fetched.length} history items`)
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

    if (get().selectedCheckId === id) return
    
    set({ selectedCheckId: id, isLoadingDetail: true, error: null })
    try {
      logger.info('HistoryStore', `Loading check details for ${id}`)
      const response = await api.getCheckDetail(id)
      const check = response.data
      
      set({ selectedCheck: check, isLoadingDetail: false })
      logger.info('HistoryStore', 'Check details loaded', { 
        title: check.paper_title,
        refs: check.total_refs 
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
