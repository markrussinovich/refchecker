import { create } from 'zustand'
import { logger } from '../utils/logger'
import * as api from '../utils/api'

const EXTRACTION_SELECTION_KEY = 'refchecker_selected_extraction_llm'
const HALLUCINATION_SELECTION_KEY = 'refchecker_selected_hallucination_llm'
const CHAT_SELECTION_KEY = 'refchecker_selected_chat_llm'
// R34 — Chat-with-PDF and Summarize each get their own model selection.
// Summarize falls back to the chat → extraction/default chain when unset.
const SUMMARY_SELECTION_KEY = 'refchecker_selected_summary_llm'
const hallucinationCapableProviders = ['openai', 'anthropic', 'google', 'azure']

function getStoredSelection(key) {
  try {
    const value = localStorage.getItem(key)
    if (!value) return null
    const numericValue = Number(value)
    return Number.isNaN(numericValue) ? value : numericValue
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
  selectedChatConfigId: getStoredSelection(CHAT_SELECTION_KEY),
  selectedSummaryConfigId: getStoredSelection(SUMMARY_SELECTION_KEY),
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
        const storedChatId = get().selectedChatConfigId
        const storedSummaryId = get().selectedSummaryConfigId
        const extractionConfigId = configs.some(c => c.id === storedExtractionId)
          ? storedExtractionId
          : defaultConfigId
        const hallucinationConfig = configs.find(c => hallucinationCapableProviders.includes(c.provider))
        const hallucinationConfigId = configs.some(c => c.id === storedHallucinationId && hallucinationCapableProviders.includes(c.provider))
          ? storedHallucinationId
          : hallucinationConfig?.id || null
        // Chat (with PDF) works with any configured provider; default to the
        // extraction/default config when nothing is stored.
        const chatConfigId = configs.some(c => c.id === storedChatId)
          ? storedChatId
          : defaultConfigId
        // Summarize works with any configured provider too. It keeps its own
        // selection (R34); fall back to the chat selection — then the
        // extraction/default config — when nothing summary-specific is stored.
        const summaryConfigId = configs.some(c => c.id === storedSummaryId)
          ? storedSummaryId
          : chatConfigId

        setStoredSelection(EXTRACTION_SELECTION_KEY, extractionConfigId)
        setStoredSelection(HALLUCINATION_SELECTION_KEY, hallucinationConfigId)
        setStoredSelection(CHAT_SELECTION_KEY, chatConfigId)
        setStoredSelection(SUMMARY_SELECTION_KEY, summaryConfigId)

        set({
          configs,
          selectedConfigId: defaultConfigId,
          selectedExtractionConfigId: extractionConfigId,
          selectedHallucinationConfigId: hallucinationConfigId,
          selectedChatConfigId: chatConfigId,
          selectedSummaryConfigId: summaryConfigId,
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

  addConfig: async (config, options = {}) => {
    set({ isLoading: true, error: null })
    try {
      logger.info('ConfigStore', 'Creating LLM config', { name: config.name, provider: config.provider })
      const response = await api.createLLMConfig(config)
      const newConfig = response.data
      const selectFor = options.selectFor || 'extraction'
      const canUseForHallucination = hallucinationCapableProviders.includes(newConfig.provider)
      const selectExtraction = selectFor === 'extraction' || selectFor === 'both'
      const selectHallucination = canUseForHallucination && (selectFor === 'hallucination' || selectFor === 'both')
      const initializeHallucination = canUseForHallucination && selectExtraction && get().selectedHallucinationConfigId == null

      if (selectExtraction) {
        setStoredSelection(EXTRACTION_SELECTION_KEY, newConfig.id)
      }
      if (selectHallucination || initializeHallucination) {
        setStoredSelection(HALLUCINATION_SELECTION_KEY, newConfig.id)
      }
      
      set(state => ({
        configs: [...state.configs, newConfig],
        selectedConfigId: selectExtraction ? newConfig.id : state.selectedConfigId,
        selectedExtractionConfigId: selectExtraction ? newConfig.id : state.selectedExtractionConfigId,
        selectedHallucinationConfigId: (selectHallucination || (canUseForHallucination && selectExtraction && state.selectedHallucinationConfigId == null))
          ? newConfig.id
          : state.selectedHallucinationConfigId,
        isLoading: false
      }))
      
      if (selectExtraction) {
        await api.setDefaultLLMConfig(newConfig.id)
      }
      
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
        const newChatId = state.selectedChatConfigId === id
          ? (newConfigs[0]?.id || null)
          : state.selectedChatConfigId
        const newSummaryId = state.selectedSummaryConfigId === id
          ? (newConfigs[0]?.id || null)
          : state.selectedSummaryConfigId
        setStoredSelection(EXTRACTION_SELECTION_KEY, newExtractionId)
        setStoredSelection(HALLUCINATION_SELECTION_KEY, newHallucinationId)
        setStoredSelection(CHAT_SELECTION_KEY, newChatId)
        setStoredSelection(SUMMARY_SELECTION_KEY, newSummaryId)
        return {
          configs: newConfigs,
          selectedConfigId: newSelectedId,
          selectedExtractionConfigId: newExtractionId,
          selectedHallucinationConfigId: newHallucinationId,
          selectedChatConfigId: newChatId,
          selectedSummaryConfigId: newSummaryId,
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

  selectChatConfig: (id) => {
    logger.info('ConfigStore', `Selecting chat config ${id}`)
    setStoredSelection(CHAT_SELECTION_KEY, id)
    set({ selectedChatConfigId: id })
  },

  selectSummaryConfig: (id) => {
    logger.info('ConfigStore', `Selecting summary config ${id}`)
    setStoredSelection(SUMMARY_SELECTION_KEY, id)
    set({ selectedSummaryConfigId: id })
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

  // Chat-with-PDF accepts any configured provider; fall back to the
  // extraction/default config when no chat-specific selection exists.
  getSelectedChatConfig: () => {
    const { configs, selectedChatConfigId, selectedExtractionConfigId, selectedConfigId } = get()
    return configs.find(c => c.id === (selectedChatConfigId || selectedExtractionConfigId || selectedConfigId)) || null
  },

  // Summarize accepts any configured provider too (R34). It has its own
  // selection but falls back to the chat selection, then the
  // extraction/default config, so existing single-selection users are
  // unaffected until they explicitly pick a Summarize model.
  getSelectedSummaryConfig: () => {
    const { configs, selectedSummaryConfigId, selectedChatConfigId, selectedExtractionConfigId, selectedConfigId } = get()
    return configs.find(c => c.id === (selectedSummaryConfigId || selectedChatConfigId || selectedExtractionConfigId || selectedConfigId)) || null
  },
}))
