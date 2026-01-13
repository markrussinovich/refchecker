import { create } from 'zustand'
import { logger } from '../utils/logger'

// Use relative path to go through Vite proxy
const API_BASE = ''

/**
 * Settings store for application-wide settings
 */
export const useSettingsStore = create((set, get) => ({
  // State
  settings: {},
  isLoading: false,
  error: null,
  isSettingsOpen: false,

  /**
   * Open the settings panel
   */
  openSettings: () => {
    set({ isSettingsOpen: true })
    // Fetch latest settings when opening
    get().fetchSettings()
  },

  /**
   * Close the settings panel
   */
  closeSettings: () => {
    set({ isSettingsOpen: false })
  },

  /**
   * Toggle the settings panel
   */
  toggleSettings: () => {
    const { isSettingsOpen } = get()
    if (isSettingsOpen) {
      get().closeSettings()
    } else {
      get().openSettings()
    }
  },

  /**
   * Fetch all settings from the backend
   */
  fetchSettings: async () => {
    set({ isLoading: true, error: null })
    try {
      const response = await fetch(`${API_BASE}/api/settings`)
      if (!response.ok) {
        throw new Error(`Failed to fetch settings: ${response.status}`)
      }
      const settings = await response.json()
      logger.info('SettingsStore', 'Fetched settings', settings)
      set({ settings, isLoading: false })
    } catch (error) {
      logger.error('SettingsStore', 'Error fetching settings', error)
      set({ error: error.message, isLoading: false })
    }
  },

  /**
   * Update a single setting
   * @param {string} key - The setting key
   * @param {string} value - The new value (always as string)
   */
  updateSetting: async (key, value) => {
    const { settings } = get()
    
    // Optimistically update the local state
    const previousSettings = { ...settings }
    set({
      settings: {
        ...settings,
        [key]: {
          ...settings[key],
          value: String(value)
        }
      }
    })

    try {
      const response = await fetch(`${API_BASE}/api/settings/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: String(value) })
      })
      
      if (!response.ok) {
        throw new Error(`Failed to update setting: ${response.status}`)
      }
      
      const result = await response.json()
      logger.info('SettingsStore', `Updated setting ${key}`, result)
      
      // Update with the validated value from the server
      set({
        settings: {
          ...get().settings,
          [key]: {
            ...get().settings[key],
            value: result.value
          }
        }
      })
    } catch (error) {
      logger.error('SettingsStore', `Error updating setting ${key}`, error)
      // Revert to previous settings on error
      set({ settings: previousSettings, error: error.message })
    }
  },

  /**
   * Get a setting value with type coercion
   * @param {string} key - The setting key
   * @returns {any} The setting value (coerced to the appropriate type)
   */
  getSetting: (key) => {
    const { settings } = get()
    const setting = settings[key]
    if (!setting) return null
    
    const value = setting.value
    
    // Coerce based on type
    switch (setting.type) {
      case 'number':
        return parseInt(value, 10)
      case 'boolean':
        return value === 'true'
      default:
        return value
    }
  }
}))
