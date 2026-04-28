import { create } from 'zustand'
import { logger } from '../utils/logger'
import * as api from '../utils/api'

const EXTRACTION_SELECTION_KEY = 'refchecker_selected_extraction_llm'
const HALLUCINATION_SELECTION_KEY = 'refchecker_selected_hallucination_llm'
const hallucinationCapableProviders = ['openai', 'anthropic', 'google', 'azure']

function getStoredSelection(key) {
  try {
    const value = localStorage.getItem(key)
    return value ? Number(value) : null
  } catch {
    return null
  }
}

function setStoredSelection(key, value) {
  try {
    if (value == null) localStorage.removeItem(key)
    else localStorage.setItem(key, String(value))
  } catch {
    // Ignore storage failures; in-memory selection still works.
  }
}

/**
 * Store for LLM configuration management
 */
export const useConfigStore = create((set, get) => ({
  // State
  configs: [],
  selectedConfigId: null,
  selectedExtractionConfigId: getStoredSelection(EXTRACTION_SELECTION_KEY),
  selectedHallucinationConfigId: getStoredSelection(HALLUCINATION_SELECTION_KEY),
  isLoading: false,
  error: null,

  // Actions
  fetchConfigs: async () => {
    set({ isLoading: true, error: null })
    
    // Retry logic with exponential backoff for server startup race condition
    const maxRetries = 5
    const baseDelay = 1000 // 1 second
    let lastError = null
    
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        logger.info('ConfigStore', `Fetching LLM configs (attempt ${attempt}/${maxRetries})`)
        const response = await api.getLLMConfigs()
        const configs = response.data
        
        // Find the default config
        const defaultConfig = configs.find(c => c.is_default)
        
        const defaultConfigId = defaultConfig?.id || configs[0]?.id || null
        const storedExtractionId = get().selectedExtractionConfigId
        const storedHallucinationId = get().selectedHallucinationConfigId
        const extractionConfigId = configs.some(c => c.id === storedExtractionId)
          ? storedExtractionId
          : defaultConfigId
        const hallucinationConfig = configs.find(c => hallucinationCapableProviders.includes(c.provider))
        const hallucinationConfigId = configs.some(c => c.id === storedHallucinationId && hallucinationCapableProviders.includes(c.provider))
          ? storedHallucinationId
          : hallucinationConfig?.id || null

        setStoredSelection(EXTRACTION_SELECTION_KEY, extractionConfigId)
        setStoredSelection(HALLUCINATION_SELECTION_KEY, hallucinationConfigId)

        set({ 
          configs, 
          selectedConfigId: defaultConfigId,
          selectedExtractionConfigId: extractionConfigId,
          selectedHallucinationConfigId: hallucinationConfigId,
          isLoading: false,
          error: null
        })
        logger.info('ConfigStore', `Loaded ${configs.length} configs`)
        return // Success - exit the function
      } catch (error) {
        lastError = error
        logger.warn('ConfigStore', `Attempt ${attempt}/${maxRetries} failed: ${error.message}`)
        
        // Don't retry on 401 - user needs to authenticate first
        if (error.response?.status === 401) {
          logger.info('ConfigStore', 'Not authenticated, skipping retries')
          break
        }
        
        if (attempt < maxRetries) {
          // Exponential backoff: 1s, 2s, 4s, 8s, 16s
          const delay = baseDelay * Math.pow(2, attempt - 1)
          logger.info('ConfigStore', `Retrying in ${delay}ms...`)
          await new Promise(resolve => setTimeout(resolve, delay))
        }
      }
    }
    
    // All retries exhausted
    logger.error('ConfigStore', `Failed to fetch configs after ${maxRetries} attempts`, lastError)
    set({ error: lastError?.message || 'Failed to connect to server', isLoading: false })
  },

  addConfig: async (config) => {
    set({ isLoading: true, error: null })
    try {
      logger.info('ConfigStore', 'Creating LLM config', { name: config.name, provider: config.provider })
      const response = await api.createLLMConfig(config)
      const newConfig = response.data
      setStoredSelection(EXTRACTION_SELECTION_KEY, newConfig.id)
      if (hallucinationCapableProviders.includes(newConfig.provider)) {
        setStoredSelection(HALLUCINATION_SELECTION_KEY, newConfig.id)
      }
      
      set(state => ({
        configs: [...state.configs, newConfig],
        selectedConfigId: newConfig.id, // Auto-select new config
        selectedExtractionConfigId: newConfig.id,
        selectedHallucinationConfigId: hallucinationCapableProviders.includes(newConfig.provider)
          ? newConfig.id
          : state.selectedHallucinationConfigId,
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
        const newExtractionId = state.selectedExtractionConfigId === id
          ? (newConfigs[0]?.id || null)
          : state.selectedExtractionConfigId
        const newHallucinationId = state.selectedHallucinationConfigId === id
          ? (newConfigs.find(c => hallucinationCapableProviders.includes(c.provider))?.id || null)
          : state.selectedHallucinationConfigId
        setStoredSelection(EXTRACTION_SELECTION_KEY, newExtractionId)
        setStoredSelection(HALLUCINATION_SELECTION_KEY, newHallucinationId)
        return {
          configs: newConfigs,
          selectedConfigId: newSelectedId,
          selectedExtractionConfigId: newExtractionId,
          selectedHallucinationConfigId: newHallucinationId,
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
      setStoredSelection(EXTRACTION_SELECTION_KEY, id)
      set({ selectedConfigId: id, selectedExtractionConfigId: id })
    } catch (error) {
      logger.error('ConfigStore', 'Failed to set default config', error)
    }
  },

  selectExtractionConfig: async (id) => {
    logger.info('ConfigStore', `Selecting extraction config ${id}`)
    try {
      await api.setDefaultLLMConfig(id)
      setStoredSelection(EXTRACTION_SELECTION_KEY, id)
      set({ selectedConfigId: id, selectedExtractionConfigId: id })
    } catch (error) {
      logger.error('ConfigStore', 'Failed to set extraction config', error)
    }
  },

  selectHallucinationConfig: (id) => {
    logger.info('ConfigStore', `Selecting hallucination config ${id}`)
    setStoredSelection(HALLUCINATION_SELECTION_KEY, id)
    set({ selectedHallucinationConfigId: id })
  },

  getSelectedConfig: () => {
    const { configs, selectedConfigId } = get()
    return configs.find(c => c.id === selectedConfigId) || null
  },

  getSelectedExtractionConfig: () => {
    const { configs, selectedExtractionConfigId, selectedConfigId } = get()
    return configs.find(c => c.id === (selectedExtractionConfigId || selectedConfigId)) || null
  },

  getSelectedHallucinationConfig: () => {
    const { configs, selectedHallucinationConfigId, selectedExtractionConfigId, selectedConfigId } = get()
    const selected = configs.find(c => c.id === (selectedHallucinationConfigId || selectedExtractionConfigId || selectedConfigId))
    if (selected && hallucinationCapableProviders.includes(selected.provider)) return selected
    return configs.find(c => hallucinationCapableProviders.includes(c.provider)) || null
  },
}))
