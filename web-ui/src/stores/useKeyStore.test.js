import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('useKeyStore', () => {
  beforeEach(() => {
    vi.resetModules()
    let lsStorage = {}
    let ssStorage = {}
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
    // Mock sessionStorage
    globalThis.sessionStorage = {
      getItem: vi.fn((key) => ssStorage[key] ?? null),
      setItem: vi.fn((key, value) => { ssStorage[key] = String(value) }),
      removeItem: vi.fn((key) => { delete ssStorage[key] }),
      clear: vi.fn(() => { ssStorage = {} }),
    }
    localStorage.clear()
    sessionStorage.clear()
  })

  it('clears legacy localStorage keys on load and persists new keys in sessionStorage', async () => {
    localStorage.setItem('refchecker_llm_keys', JSON.stringify({ anthropic: 'persisted-key' }))

    const { useKeyStore } = await import('./useKeyStore')

    expect(localStorage.getItem('refchecker_llm_keys')).toBeNull()
    expect(useKeyStore.getState().getKey('anthropic')).toBeNull()

    useKeyStore.getState().setKey('anthropic', 'tab-key')

    expect(useKeyStore.getState().getKey('anthropic')).toBe('tab-key')
    expect(localStorage.getItem('refchecker_llm_keys')).toBeNull()
    // Key should be saved to sessionStorage
    const saved = JSON.parse(sessionStorage.getItem('refchecker_tab_keys'))
    expect(saved.anthropic).toBe('tab-key')
  })

  it('restores keys from sessionStorage on load', async () => {
    sessionStorage.setItem('refchecker_tab_keys', JSON.stringify({ openai: 'restored-key' }))

    const { useKeyStore } = await import('./useKeyStore')

    expect(useKeyStore.getState().getKey('openai')).toBe('restored-key')
  })

  it('clears all keys from memory and sessionStorage', async () => {
    const { useKeyStore } = await import('./useKeyStore')

    useKeyStore.getState().setKey('openai', 'openai-key')
    useKeyStore.getState().setKey('semantic_scholar', 'ss-key')
    useKeyStore.getState().clearAll()

    expect(useKeyStore.getState().getKey('openai')).toBeNull()
    expect(useKeyStore.getState().getKey('semantic_scholar')).toBeNull()
    const saved = JSON.parse(sessionStorage.getItem('refchecker_tab_keys'))
    expect(saved).toEqual({})
  })
})