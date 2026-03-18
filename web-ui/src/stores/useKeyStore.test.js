import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('useKeyStore', () => {
  beforeEach(() => {
    vi.resetModules()
    let storage = {}
    localStorage.getItem.mockImplementation((key) => storage[key] ?? null)
    localStorage.setItem.mockImplementation((key, value) => {
      storage[key] = String(value)
    })
    localStorage.removeItem.mockImplementation((key) => {
      delete storage[key]
    })
    localStorage.clear.mockImplementation(() => {
      storage = {}
    })
    localStorage.clear()
  })

  it('clears legacy localStorage keys on load and keeps new keys in memory only', async () => {
    localStorage.setItem('refchecker_llm_keys', JSON.stringify({ anthropic: 'persisted-key' }))

    const { useKeyStore } = await import('./useKeyStore')

    expect(localStorage.getItem('refchecker_llm_keys')).toBeNull()
    expect(useKeyStore.getState().getKey('anthropic')).toBeNull()

    useKeyStore.getState().setKey('anthropic', 'tab-key')

    expect(useKeyStore.getState().getKey('anthropic')).toBe('tab-key')
    expect(localStorage.getItem('refchecker_llm_keys')).toBeNull()
  })

  it('clears all in-memory keys', async () => {
    const { useKeyStore } = await import('./useKeyStore')

    useKeyStore.getState().setKey('openai', 'openai-key')
    useKeyStore.getState().setKey('semantic_scholar', 'ss-key')
    useKeyStore.getState().clearAll()

    expect(useKeyStore.getState().getKey('openai')).toBeNull()
    expect(useKeyStore.getState().getKey('semantic_scholar')).toBeNull()
  })
})