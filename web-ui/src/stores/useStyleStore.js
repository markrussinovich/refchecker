import { create } from 'zustand'

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
    if (!raw) return { format: 'plaintext', styleOptions: {} }
    const parsed = JSON.parse(raw)
    return {
      format: parsed.format || 'plaintext',
      styleOptions: parsed.styleOptions || {},
    }
  } catch {
    return { format: 'plaintext', styleOptions: {} }
  }
}

function persist(state) {
  try {
    localStorage.setItem(_KEY, JSON.stringify({
      format: state.format,
      styleOptions: state.styleOptions,
    }))
  } catch { /* quota / disabled */ }
}

export const useStyleStore = create((set, get) => ({
  ...loadInitial(),
  setFormat: (format) => {
    set({ format })
    persist(get())
  },
  setStyleOptions: (styleOptions) => {
    set({ styleOptions })
    persist(get())
  },
}))
