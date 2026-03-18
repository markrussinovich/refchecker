import { create } from 'zustand'

const LEGACY_STORAGE_KEY = 'refchecker_llm_keys'

function clearLegacyKeys() {
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY)
  } catch {}
}

if (typeof window !== 'undefined') {
  clearLegacyKeys()
}

export const useKeyStore = create((set, get) => ({
  keys: {}, // { provider: key, ... } kept in memory for this tab only

  setKey: (provider, key) => {
    const keys = { ...get().keys, [provider]: key }
    set({ keys })
  },

  getKey: (provider) => get().keys[provider] || null,

  deleteKey: (provider) => {
    const keys = { ...get().keys }
    delete keys[provider]
    set({ keys })
  },

  hasKey: (provider) => Boolean(get().keys[provider]),

  clearAll: () => set({ keys: {} }),
}))
