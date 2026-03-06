import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// Mock window.location for redirect tests
Object.defineProperty(window, 'location', {
  value: { href: '', search: '' },
  writable: true,
})

// Mock history.replaceState
window.history.replaceState = vi.fn()

// Mock the api module
vi.mock('../utils/api', () => ({
  getAuthProviders: vi.fn(() => Promise.resolve({ data: { providers: ['google', 'github'] } })),
  getAuthMe: vi.fn(() => Promise.resolve({ data: { user: { id: 1, email: 'test@example.com', name: 'Test User', avatar_url: null, provider: 'google' } } })),
  authLogout: vi.fn(() => Promise.resolve({})),
  setAuthToken: vi.fn(),
}))

describe('useAuthStore', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    window.location.href = ''
    window.location.search = ''
  })

  it('should initialize with isLoading true', async () => {
    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())
    expect(result.current.isLoading).toBe(true)
  })

  it('should populate providers and user when already logged in', async () => {
    const { getAuthProviders, getAuthMe } = await import('../utils/api')
    getAuthProviders.mockResolvedValueOnce({ data: { providers: ['google', 'github'] } })
    getAuthMe.mockResolvedValueOnce({ data: { user: { id: 1, email: 'test@example.com', name: 'Test User' } } })

    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    await act(async () => {
      await result.current.init()
    })

    expect(result.current.providers).toEqual(['google', 'github'])
    expect(result.current.user).not.toBeNull()
    expect(result.current.user.email).toBe('test@example.com')
    expect(result.current.isLoading).toBe(false)
  })

  it('should set user to null when not logged in (401 from /auth/me)', async () => {
    const { getAuthProviders, getAuthMe } = await import('../utils/api')
    getAuthProviders.mockResolvedValueOnce({ data: { providers: ['google', 'github'] } })
    getAuthMe.mockRejectedValueOnce({ response: { status: 401 } })

    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    await act(async () => {
      await result.current.init()
    })

    expect(result.current.providers).toEqual(['google', 'github'])
    expect(result.current.user).toBeNull()
    expect(result.current.isLoading).toBe(false)
  })

  it('should set empty providers when server returns none', async () => {
    const { getAuthProviders, getAuthMe } = await import('../utils/api')
    getAuthProviders.mockResolvedValueOnce({ data: { providers: [] } })
    getAuthMe.mockRejectedValueOnce({ response: { status: 401 } })

    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    await act(async () => {
      await result.current.init()
    })

    expect(result.current.providers).toEqual([])
    expect(result.current.user).toBeNull()
    expect(result.current.isLoading).toBe(false)
  })

  it('should handle auth_error in URL', async () => {
    window.location.search = '?auth_error=access_denied'

    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    await act(async () => {
      await result.current.init()
    })

    expect(result.current.error).toContain('access_denied')
    expect(result.current.isLoading).toBe(false)
    expect(window.history.replaceState).toHaveBeenCalled()
  })

  it('should clear user state on logout', async () => {
    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    await act(async () => {
      useAuthStore.setState({ user: { id: 1, email: 'x@y.com' } })
    })

    await act(async () => {
      await result.current.logout()
    })

    expect(result.current.user).toBeNull()
  })

  it('loginWithGoogle should redirect to /api/auth/login/google', async () => {
    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    act(() => {
      result.current.loginWithGoogle()
    })

    expect(window.location.href).toBe('/api/auth/login/google')
  })

  it('loginWithGithub should redirect to /api/auth/login/github', async () => {
    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    act(() => {
      result.current.loginWithGithub()
    })

    expect(window.location.href).toBe('/api/auth/login/github')
  })

  it('loginWithMicrosoft should redirect to /api/auth/login/microsoft', async () => {
    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    act(() => {
      result.current.loginWithMicrosoft()
    })

    expect(window.location.href).toBe('/api/auth/login/microsoft')
  })

  it('auth:unauthorized event should clear user', async () => {
    const { useAuthStore } = await import('./useAuthStore')
    const { result } = renderHook(() => useAuthStore())

    await act(async () => {
      useAuthStore.setState({ user: { id: 1, email: 'x@y.com' } })
    })

    await act(async () => {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'))
    })

    expect(result.current.user).toBeNull()
  })
})
