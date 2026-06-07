import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({
  getUserPreferences: vi.fn(),
  updateUserPreferences: vi.fn(() => Promise.resolve({ data: {} })),
}))

vi.mock('../utils/api', () => apiMocks)
vi.mock('../utils/logger', () => ({
  logger: { warn: vi.fn() },
}))

describe('useStyleStore', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
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
    apiMocks.updateUserPreferences.mockResolvedValue({ data: {} })
  })

  it('defaults to Plain text (ACM) when nothing is saved', async () => {
    const { useStyleStore } = await import('./useStyleStore')

    expect(useStyleStore.getState().format).toBe('plaintext')
    expect(useStyleStore.getState().hasUserPreference).toBe(false)
  })

  it('ignores legacy auto-saved formats that were not explicit user preferences', async () => {
    localStorage.setItem('refchecker:style', JSON.stringify({
      format: 'bibtex',
      styleOptions: { include_url: false },
    }))

    const { useStyleStore } = await import('./useStyleStore')

    expect(useStyleStore.getState().format).toBe('plaintext')
    expect(useStyleStore.getState().styleOptions).toEqual({})
    expect(useStyleStore.getState().hasUserPreference).toBe(false)
  })

  it('persists explicit citation format changes locally and remotely', async () => {
    const { useStyleStore } = await import('./useStyleStore')

    useStyleStore.getState().setFormat('apa', { userSelected: true })

    expect(useStyleStore.getState().format).toBe('apa')
    expect(useStyleStore.getState().hasUserPreference).toBe(true)
    expect(JSON.parse(localStorage.getItem('refchecker:style'))).toMatchObject({
      format: 'apa',
      hasUserPreference: true,
    })
    expect(apiMocks.updateUserPreferences).toHaveBeenCalledWith({
      citation_format: 'apa',
      citation_style_options: {},
    })
  })

  it('loads user-scoped citation preferences from the backend', async () => {
    apiMocks.getUserPreferences.mockResolvedValue({
      data: {
        citation_format: 'ieee',
        citation_style_options: { include_url: false },
        has_citation_format: true,
      },
    })
    const { useStyleStore } = await import('./useStyleStore')

    await useStyleStore.getState().loadPreferences()

    expect(useStyleStore.getState().format).toBe('ieee')
    expect(useStyleStore.getState().styleOptions).toEqual({ include_url: false })
    expect(useStyleStore.getState().hasUserPreference).toBe(true)
  })

  it('seeds backend storage from existing local style in single-user mode', async () => {
    localStorage.setItem('refchecker:style', JSON.stringify({
      format: 'mla',
      styleOptions: { max_authors: 1 },
      hasUserPreference: true,
    }))
    apiMocks.getUserPreferences.mockResolvedValue({
      data: {
        citation_format: 'plaintext',
        citation_style_options: {},
        has_citation_format: false,
      },
    })
    const { useStyleStore } = await import('./useStyleStore')

    await useStyleStore.getState().loadPreferences({ seedFromLocal: true })

    expect(useStyleStore.getState().format).toBe('mla')
    expect(apiMocks.updateUserPreferences).toHaveBeenCalledWith({
      citation_format: 'mla',
      citation_style_options: { max_authors: 1 },
    })
  })
})