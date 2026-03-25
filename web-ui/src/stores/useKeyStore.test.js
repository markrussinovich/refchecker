import { beforeEach, describe, expect, it, vi } from 'vitest'

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

    expect(useKeyStore.getState().getKey('openai')).toBe('new-key')
    const saved = JSON.parse(localStorage.getItem('refchecker_tab_keys'))
    expect(saved.openai).toBe('new-key')
    expect(saved.anthropic).toBe('persisted-key')
  })

  it('restores keys from localStorage on load', async () => {
    localStorage.setItem('refchecker_tab_keys', JSON.stringify({ openai: 'restored-key' }))

    const { useKeyStore } = await import('./useKeyStore')

    expect(useKeyStore.getState().getKey('openai')).toBe('restored-key')
  })

  it('clears all keys from memory and localStorage', async () => {
    const { useKeyStore } = await import('./useKeyStore')

    useKeyStore.getState().setKey('openai', 'openai-key')
    useKeyStore.getState().setKey('semantic_scholar', 'ss-key')
    useKeyStore.getState().clearAll()

    expect(useKeyStore.getState().getKey('openai')).toBeNull()
    expect(useKeyStore.getState().getKey('semantic_scholar')).toBeNull()
    const saved = JSON.parse(localStorage.getItem('refchecker_tab_keys'))
    expect(saved).toEqual({})
  })
})