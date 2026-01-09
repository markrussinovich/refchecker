import { create } from 'zustand'
import { logger } from '../utils/logger'
import * as api from '../utils/api'

/**
 * Store for LLM configuration management
 */
export const useConfigStore = create((set, get) => ({
  // State
  configs: [],
  selectedConfigId: null,
  isLoading: false,
  error: null,

  // Actions
  fetchConfigs: async () => {
    set({ isLoading: true, error: null })
    try {
      logger.info('ConfigStore', 'Fetching LLM configs')
      const response = await api.getLLMConfigs()
      const configs = response.data
      
      // Find the default config
      const defaultConfig = configs.find(c => c.is_default)
      
      set({ 
        configs, 
        selectedConfigId: defaultConfig?.id || configs[0]?.id || null,
        isLoading: false 
      })
      logger.info('ConfigStore', `Loaded ${configs.length} configs`)
    } catch (error) {
      logger.error('ConfigStore', 'Failed to fetch configs', error)
      set({ error: error.message, isLoading: false })
    }
  },

  addConfig: async (config) => {
    set({ isLoading: true, error: null })
    try {
      logger.info('ConfigStore', 'Creating LLM config', { name: config.name, provider: config.provider })
      const response = await api.createLLMConfig(config)
      const newConfig = response.data
      
      set(state => ({
        configs: [...state.configs, newConfig],
        selectedConfigId: newConfig.id, // Auto-select new config
        isLoading: false
      }))
      
      // Set as default
      await api.setDefaultLLMConfig(newConfig.id)
      
      logger.info('ConfigStore', 'Config created', newConfig)
      return newConfig
    } catch (error) {
      logger.error('ConfigStore', 'Failed to create config', error)
      set({ error: error.message, isLoading: false })
      throw error
    }
  },

  updateConfig: async (id, updates) => {
    set({ isLoading: true, error: null })
    try {
      logger.info('ConfigStore', `Updating config ${id}`, updates)
      const response = await api.updateLLMConfig(id, updates)
      const updatedConfig = response.data
      
      set(state => ({
        configs: state.configs.map(c => c.id === id ? updatedConfig : c),
        isLoading: false
      }))
      
      logger.info('ConfigStore', 'Config updated')
      return updatedConfig
    } catch (error) {
      logger.error('ConfigStore', 'Failed to update config', error)
      set({ error: error.message, isLoading: false })
      throw error
    }
  },

  deleteConfig: async (id) => {
    set({ isLoading: true, error: null })
    try {
      logger.info('ConfigStore', `Deleting config ${id}`)
      await api.deleteLLMConfig(id)
      
      set(state => {
        const newConfigs = state.configs.filter(c => c.id !== id)
        const newSelectedId = state.selectedConfigId === id 
          ? (newConfigs[0]?.id || null) 
          : state.selectedConfigId
        return {
          configs: newConfigs,
          selectedConfigId: newSelectedId,
          isLoading: false
        }
      })
      
      logger.info('ConfigStore', 'Config deleted')
    } catch (error) {
      logger.error('ConfigStore', 'Failed to delete config', error)
      set({ error: error.message, isLoading: false })
      throw error
    }
  },

  selectConfig: async (id) => {
    logger.info('ConfigStore', `Selecting config ${id}`)
    try {
      await api.setDefaultLLMConfig(id)
      set({ selectedConfigId: id })
    } catch (error) {
      logger.error('ConfigStore', 'Failed to set default config', error)
    }
  },

  getSelectedConfig: () => {
    const { configs, selectedConfigId } = get()
    return configs.find(c => c.id === selectedConfigId) || null
  },
}))
