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

  // Actions
  fetchHistory: async (limit = 50) => {
    set({ isLoading: true, error: null })
    try {
      logger.info('HistoryStore', `Fetching history (limit: ${limit})`)
      const response = await api.getHistory(limit)
      const history = response.data
      
      set({ history, isLoading: false })
      logger.info('HistoryStore', `Loaded ${history.length} history items`)
    } catch (error) {
      logger.error('HistoryStore', 'Failed to fetch history', error)
      set({ error: error.message, isLoading: false })
    }
  },

  selectCheck: async (id) => {
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
      history: [check, ...state.history]
    }))
  },
}))
