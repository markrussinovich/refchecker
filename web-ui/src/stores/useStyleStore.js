import { create } from 'zustand'
import { logger } from '../utils/logger'
import { getUserPreferences, updateUserPreferences } from '../utils/api'

export const DEFAULT_CITATION_FORMAT = 'plaintext'

/**
 * Shared citation style + style-options state.
 *
 * The Corrections tab has the full style picker; the References tab and
 * the Suggest-alternative panel read from this store so a single choice
 * (style, max-authors, et-al threshold, include_url) drives every
 * rendered citation in the app. Persisted to localStorage so the user's
 * style choice survives reloads.
 */
const _KEY = 'refchecker:style'

function loadInitial() {
  try {
    const raw = localStorage.getItem(_KEY)
    if (!raw) return { format: DEFAULT_CITATION_FORMAT, styleOptions: {}, hasUserPreference: false }
    const parsed = JSON.parse(raw)
    const hasUserPreference = parsed.hasUserPreference === true
    return {
      format: hasUserPreference ? (parsed.format || DEFAULT_CITATION_FORMAT) : DEFAULT_CITATION_FORMAT,
      styleOptions: hasUserPreference ? (parsed.styleOptions || {}) : {},
      hasUserPreference,
    }
  } catch {
    return { format: DEFAULT_CITATION_FORMAT, styleOptions: {}, hasUserPreference: false }
  }
}

function persist(state) {
  try {
    localStorage.setItem(_KEY, JSON.stringify({
      format: state.format,
      styleOptions: state.styleOptions,
      hasUserPreference: state.hasUserPreference,
    }))
  } catch { /* quota / disabled */ }
}

function persistRemote(state) {
  updateUserPreferences({
    citation_format: state.format,
    citation_style_options: state.styleOptions,
  }).catch((e) => {
    logger.warn('StyleStore', 'Failed to persist user style preference', e)
  })
}

export const useStyleStore = create((set, get) => ({
  ...loadInitial(),
  isRemoteLoaded: false,
  loadPreferences: async (options = {}) => {
    try {
      const response = await getUserPreferences()
      const preferences = response.data || {}
      if (!preferences.has_citation_format && options.seedFromLocal && get().hasUserPreference) {
        persistRemote(get())
        set({ isRemoteLoaded: true })
        return
      }
      const next = {
        format: preferences.citation_format || DEFAULT_CITATION_FORMAT,
        styleOptions: preferences.citation_style_options || {},
        hasUserPreference: Boolean(preferences.has_citation_format),
        isRemoteLoaded: true,
      }
      set(next)
      persist(get())
    } catch (e) {
      logger.warn('StyleStore', 'Failed to load user style preference', e)
      set({ isRemoteLoaded: true })
    }
  },
  setFormat: (format, options = {}) => {
    set({ format, hasUserPreference: options.userSelected ?? true })
    persist(get())
    if (options.persistRemote !== false) persistRemote(get())
  },
  setStyleOptions: (styleOptions, options = {}) => {
    set({ styleOptions, hasUserPreference: options.userSelected ?? get().hasUserPreference })
    persist(get())
    if (options.persistRemote !== false) persistRemote(get())
  },
}))
