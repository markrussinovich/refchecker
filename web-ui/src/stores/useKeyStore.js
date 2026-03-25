import { create } from 'zustand'

const LEGACY_STORAGE_KEY = 'refchecker_llm_keys'
const SESSION_STORAGE_KEY = 'refchecker_tab_keys'

function clearLegacyKeys() {
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY)
  } catch {}
}

function loadSessionKeys() {
  try {
    const raw = sessionStorage.getItem(SESSION_STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}

function saveSessionKeys(keys) {
  try {
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(keys))
  } catch {}
}

if (typeof window !== 'undefined') {
  clearLegacyKeys()
}

export const useKeyStore = create((set, get) => ({
  keys: loadSessionKeys(), // { provider: key, ... } persists across refresh via sessionStorage

  setKey: (provider, key) => {
    const keys = { ...get().keys, [provider]: key }
    saveSessionKeys(keys)
    set({ keys })
  },

  getKey: (provider) => get().keys[provider] || null,

  deleteKey: (provider) => {
    const keys = { ...get().keys }
    delete keys[provider]
    saveSessionKeys(keys)
    set({ keys })
  },

  hasKey: (provider) => Boolean(get().keys[provider]),

  clearAll: () => {
    saveSessionKeys({})
    set({ keys: {} })
  },
}))
