import { create } from 'zustand'

const STORAGE_KEY = 'refchecker_llm_keys'

function loadKeys() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}

function saveKeys(keys) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(keys)) } catch {}
}

export const useKeyStore = create((set, get) => ({
  keys: loadKeys(), // { provider: key, ... }

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
}))
