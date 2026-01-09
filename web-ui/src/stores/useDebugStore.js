import { create } from 'zustand'

const MAX_LOGS = 500

/**
 * Store for debug log management
 */
export const useDebugStore = create((set, get) => ({
  // State
  logs: [],
  isEnabled: localStorage.getItem('refchecker_debug') === 'true',
  isVisible: false,
  filter: 'all', // all, error, warn, info, debug

  // Actions
  addLog: (level, component, message, data = null) => {
    if (!get().isEnabled) return
    
    const log = {
      id: Date.now() + Math.random(),
      timestamp: new Date().toISOString(),
      level,
      component,
      message,
      data: data ? JSON.stringify(data, null, 2) : null,
    }
    
    set(state => ({
      logs: [...state.logs.slice(-MAX_LOGS + 1), log]
    }))
  },

  toggleEnabled: () => {
    set(state => {
      const newEnabled = !state.isEnabled
      localStorage.setItem('refchecker_debug', newEnabled.toString())
      return { isEnabled: newEnabled }
    })
  },

  toggleVisible: () => {
    set(state => ({ isVisible: !state.isVisible }))
  },

  setFilter: (filter) => {
    set({ filter })
  },

  clearLogs: () => {
    set({ logs: [] })
  },

  getFilteredLogs: () => {
    const { logs, filter } = get()
    if (filter === 'all') return logs
    return logs.filter(log => log.level.toLowerCase() === filter)
  },
}))
