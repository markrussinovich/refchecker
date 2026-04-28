import { beforeEach, describe, expect, it, vi } from 'vitest'

const waitForSave = () => new Promise(resolve => setTimeout(resolve, 0))

const waitForSavedKeys = async () => {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const raw = localStorage.getItem('refchecker_tab_keys')
    if (raw) return JSON.parse(raw)
    await waitForSave()
  }
  return JSON.parse(localStorage.getItem('refchecker_tab_keys'))
}

describe('useKeyStore', () => {
  beforeEach(() => {
    vi.resetModules()
    let lsStorage = {}
    localStorage.getItem.mockImplementation((key) => lsStorage[key] ?? null)
    localStorage.setItem.mockImplementation((key, value) => {
      lsStorage[key] = String(value)
    })
    localStorage.removeItem.mockImplementation((key) => {
      delete lsStorage[key]
    })
    localStorage.clear.mockImplementation(() => {
      lsStorage = {}
    })
    localStorage.clear()
  })

  it('migrates legacy keys and persists new keys in localStorage', async () => {
    localStorage.setItem('refchecker_llm_keys', JSON.stringify({ anthropic: 'persisted-key' }))

    const { useKeyStore } = await import('./useKeyStore')

    // Legacy key should be migrated
    expect(localStorage.getItem('refchecker_llm_keys')).toBeNull()
    expect(useKeyStore.getState().getKey('anthropic')).toBe('persisted-key')

    useKeyStore.getState().setKey('openai', 'new-key')
    await waitForSave()

    expect(useKeyStore.getState().getKey('openai')).toBe('new-key')
    const saved = await waitForSavedKeys()
    expect(saved.version).toBe(2)
    expect(saved.encrypted).toBeTypeOf('boolean')
  })

  it('restores keys from localStorage on load', async () => {
    localStorage.setItem('refchecker_tab_keys', JSON.stringify({ version: 2, encrypted: false, keys: { openai: 'restored-key' } }))

    const { useKeyStore } = await import('./useKeyStore')

    expect(useKeyStore.getState().getKey('openai')).toBe('restored-key')
  })

  it('clears all keys from memory and localStorage', async () => {
    const { useKeyStore } = await import('./useKeyStore')

    useKeyStore.getState().setKey('openai', 'openai-key')
    useKeyStore.getState().setKey('semantic_scholar', 'ss-key')
    useKeyStore.getState().clearAll()
    await waitForSave()

    expect(useKeyStore.getState().getKey('openai')).toBeNull()
    expect(useKeyStore.getState().getKey('semantic_scholar')).toBeNull()
    const saved = await waitForSavedKeys()
    expect(saved.version).toBe(2)
    if (saved.encrypted) {
      expect(saved.data).toBeTruthy()
    } else {
      expect(saved.keys).toEqual({})
    }
  })
})