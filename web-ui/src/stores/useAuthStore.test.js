import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// Mock window.location for redirect tests
const mockLocationHref = vi.fn()
Object.defineProperty(window, 'location', {
  value: { href: '' },
  writable: true,
})

// Mock sessionStorage
const sessionStorageMock = (() => {
  let store = {}
  return {
    getItem: vi.fn((key) => store[key] || null),
    setItem: vi.fn((key, value) => { store[key] = value }),
    removeItem: vi.fn((key) => { delete store[key] }),
    clear: vi.fn(() => { store = {} }),
  }
})()
Object.defineProperty(window, 'sessionStorage', { value: sessionStorageMock })

// Mock history.replaceState
window.history.replaceState = vi.fn()

// Mock the api module
vi.mock('../utils/api', () => ({
  getAuthProviders: vi.fn(() => Promise.resolve({ data: { auth_enabled: false, providers: [] } })),
  getAuthMe: vi.fn(() => Promise.resolve({ data: { auth_enabled: true, user: { id: 1, email: 'test@example.com', name: 'Test User', avatar_url: null, provider: 'google' } } })),
  authLogout: vi.fn(() => Promise.resolve({})),
  getUserApiKeyProviders: vi.fn(() => Promise.resolve({ data: { providers: [] } })),
  setUserApiKey: vi.fn(() => Promise.resolve({})),
  deleteUserApiKey: vi.fn(() => Promise.resolve({})),
  setAuthToken: vi.fn(),
}))

describe('useAuthStore', () => {
  beforeEach(() => {
    vi.resetModules()
    sessionStorageMock.clear()
    vi.clearAllMocks()
  })

  it('should initialize with isLoading true', async () => {
    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())
    expect(result.current.isLoading).toBe(true)
  })

  it('should set authEnabled to false when server says auth is disabled', async () => {
    const { getAuthProviders } = await import('../utils/api')
    getAuthProviders.mockResolvedValueOnce({ data: { auth_enabled: false, providers: [] } })

    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    await act(async () => {
      await result.current.init()
    })

    expect(result.current.authEnabled).toBe(false)
    expect(result.current.isLoading).toBe(false)
    expect(result.current.user).toBeNull()
  })

  it('should require login when auth enabled but no token present', async () => {
    const { getAuthProviders } = await import('../utils/api')
    getAuthProviders.mockResolvedValueOnce({ data: { auth_enabled: true, providers: ['google', 'github'] } })
    sessionStorageMock.getItem.mockReturnValue(null)

    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    await act(async () => {
      await result.current.init()
    })

    expect(result.current.authEnabled).toBe(true)
    expect(result.current.user).toBeNull()
    expect(result.current.isLoading).toBe(false)
  })

  it('should authenticate when a valid token is in sessionStorage', async () => {
    const { getAuthProviders, getAuthMe, setAuthToken } = await import('../utils/api')
    getAuthProviders.mockResolvedValueOnce({ data: { auth_enabled: true, providers: ['google'] } })
    sessionStorageMock.getItem.mockReturnValue('fake.jwt.token')
    getAuthMe.mockResolvedValueOnce({
      data: {
        auth_enabled: true,
        user: { id: 1, email: 'test@example.com', name: 'Test User', avatar_url: null, provider: 'google' },
      },
    })

    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    await act(async () => {
      await result.current.init()
    })

    expect(result.current.authEnabled).toBe(true)
    expect(result.current.user).not.toBeNull()
    expect(result.current.user.email).toBe('test@example.com')
    expect(setAuthToken).toHaveBeenCalledWith('fake.jwt.token')
  })

  it('should clear user state on logout', async () => {
    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    // Seed some state
    await act(async () => {
      result.current.authEnabled = true
    })

    await act(async () => {
      await result.current.logout()
    })

    expect(result.current.user).toBeNull()
    expect(result.current.token).toBeNull()
    expect(sessionStorageMock.removeItem).toHaveBeenCalledWith('refchecker_auth_token')
  })

  it('loginWithGoogle should redirect to /api/auth/google', async () => {
    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    act(() => {
      result.current.loginWithGoogle()
    })

    expect(window.location.href).toBe('/api/auth/google')
  })

  it('loginWithGithub should redirect to /api/auth/github', async () => {
    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    act(() => {
      result.current.loginWithGithub()
    })

    expect(window.location.href).toBe('/api/auth/github')
  })

  it('should expose storeApiKey and removeApiKey methods', async () => {
    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    expect(typeof result.current.storeApiKey).toBe('function')
    expect(typeof result.current.removeApiKey).toBe('function')
    expect(typeof result.current.hasApiKey).toBe('function')
  })
})
