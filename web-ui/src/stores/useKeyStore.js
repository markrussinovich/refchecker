import { create } from 'zustand'

const STORAGE_KEY = 'refchecker_tab_keys'
const LEGACY_STORAGE_KEY = 'refchecker_llm_keys'
const ENCRYPTED_STORAGE_VERSION = 2

const browserCrypto = globalThis.crypto?.subtle ? globalThis.crypto : null

function base64Encode(bytes) {
  let binary = ''
  bytes.forEach(byte => { binary += String.fromCharCode(byte) })
  return btoa(binary)
}

function base64Decode(value) {
  const binary = atob(value)
  return Uint8Array.from(binary, char => char.charCodeAt(0))
}

async function getBrowserKey() {
  if (!browserCrypto) return null
  const origin = globalThis.location?.origin || 'refchecker-local'
  const material = new TextEncoder().encode(`${origin}:refchecker-browser-key-cache`)
  const digest = await browserCrypto.subtle.digest('SHA-256', material)
  return browserCrypto.subtle.importKey('raw', digest, 'AES-GCM', false, ['encrypt', 'decrypt'])
}

async function encryptKeys(keys) {
  const key = await getBrowserKey()
  if (!key) return { version: ENCRYPTED_STORAGE_VERSION, encrypted: false, keys }
  const iv = browserCrypto.getRandomValues(new Uint8Array(12))
  const encoded = new TextEncoder().encode(JSON.stringify(keys))
  const ciphertext = await browserCrypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded)
  return {
    version: ENCRYPTED_STORAGE_VERSION,
    encrypted: true,
    iv: base64Encode(iv),
    data: base64Encode(new Uint8Array(ciphertext)),
  }
}

async function decryptKeys(payload) {
  if (!payload?.encrypted) return payload?.keys || {}
  const key = await getBrowserKey()
  if (!key) return {}
  const plaintext = await browserCrypto.subtle.decrypt(
    { name: 'AES-GCM', iv: base64Decode(payload.iv) },
    key,
    base64Decode(payload.data),
  )
  return JSON.parse(new TextDecoder().decode(plaintext))
}

function migrateAndLoadKeys() {
  try {
    // Migrate legacy key format if present
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY)
    if (legacy) {
      const parsed = JSON.parse(legacy)
      saveKeys(parsed)
      localStorage.removeItem(LEGACY_STORAGE_KEY)
      return parsed
    }
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (parsed?.version === ENCRYPTED_STORAGE_VERSION) {
      if (!parsed.encrypted) return parsed.keys || {}
      decryptKeys(parsed).then(keys => {
        useKeyStore.setState({ keys })
      }).catch(() => undefined)
      return {}
    }
    saveKeys(parsed)
    return parsed
  } catch {
    return {}
  }
}

function saveKeys(keys) {
  encryptKeys(keys)
    .then(payload => localStorage.setItem(STORAGE_KEY, JSON.stringify(payload)))
    .catch(() => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
          version: ENCRYPTED_STORAGE_VERSION,
          encrypted: false,
          keys,
        }))
      } catch {
        return undefined
      }
    })
}

export const useKeyStore = create((set, get) => ({
  keys: migrateAndLoadKeys(), // { provider or llm:<configId>: key, ... } persists encrypted in localStorage when available

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
