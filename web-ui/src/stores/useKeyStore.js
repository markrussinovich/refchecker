import { create } from 'zustand'

const STORAGE_KEY = 'refchecker_tab_keys'
const LEGACY_STORAGE_KEY = 'refchecker_llm_keys'

function migrateAndLoadKeys() {
  try {
    // Migrate legacy key format if present
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY)
    if (legacy) {
      const parsed = JSON.parse(legacy)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed))
      localStorage.removeItem(LEGACY_STORAGE_KEY)
      return parsed
    }
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}

function saveKeys(keys) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(keys))
  } catch {}
}

export const useKeyStore = create((set, get) => ({
  keys: migrateAndLoadKeys(), // { provider: key, ... } persists in localStorage

  setKey: (provider, key) => {
    const keys = { ...get().keys, [provider]: key }
    saveKeys(keys)
    set({ keys })
  },

  getKey: (provider) => get().keys[provider] || null,

  deleteKey: (provider) => {
    const keys = { ...get().keys }
    delete keys[provider]
    saveKeys(keys)
    set({ keys })
  },

  hasKey: (provider) => Boolean(get().keys[provider]),

  clearAll: () => {
    saveKeys({})
    set({ keys: {} })
  },
}))
