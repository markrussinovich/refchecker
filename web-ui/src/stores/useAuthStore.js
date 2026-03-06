import { create } from 'zustand'
import { logger } from '../utils/logger'
import * as api from '../utils/api'

/**
 * Store for authentication state management.
 *
 * When AUTH_ENABLED is false (default single-user mode), the store stays in
 * `{ authEnabled: false, user: null, token: null }` and the app renders
 * normally without a login gate.
 *
 * When AUTH_ENABLED is true, the store handles:
 *  - Bootstrapping from a token stored in sessionStorage
 *  - Parsing the ?auth_token=... query-string placed by the OAuth callback
 *  - Exposing login helpers that redirect the browser to OAuth providers
 */
export const useAuthStore = create((set, get) => ({
  // ------- State -------
  authEnabled: false,   // true once we know the server requires auth
  user: null,           // { id, email, name, avatar_url, provider }
  token: null,          // JWT string (stored in sessionStorage when present)
  isLoading: true,      // true while we are checking auth on startup
  error: null,

  // In-memory API key state (provider -> boolean indicating a key is stored)
  apiKeyProviders: [],

  // ------- Init -------

  /**
   * Called once on app startup.  Checks:
   *  1. Server's /api/auth/providers to learn if auth is required.
   *  2. A ?auth_token= in the URL (from OAuth callback redirect).
   *  3. A previously-saved token in sessionStorage.
   */
  init: async () => {
    logger.info('AuthStore', 'Initialising auth...')
    set({ isLoading: true, error: null })

    try {
      // 1. Ask server what auth looks like
      const providersResp = await api.getAuthProviders()
      const { auth_enabled, providers } = providersResp.data
      logger.info('AuthStore', `Auth enabled: ${auth_enabled}, providers: ${providers}`)

      if (!auth_enabled) {
        // Single-user mode – nothing to do
        set({ authEnabled: false, isLoading: false })
        return
      }

      // 2. Check for OAuth callback token in URL fragment/query
      const urlParams = new URLSearchParams(window.location.search)
      const callbackToken = urlParams.get('auth_token')
      const callbackError = urlParams.get('auth_error')

      if (callbackError) {
        logger.warn('AuthStore', `OAuth error: ${callbackError}`)
        // Remove query param from URL without triggering a reload
        window.history.replaceState({}, '', window.location.pathname)
        set({ authEnabled: true, isLoading: false, error: `Login failed: ${callbackError}` })
        return
      }

      let token = callbackToken
      if (token) {
        // Persist token and clean URL
        sessionStorage.setItem('refchecker_auth_token', token)
        window.history.replaceState({}, '', window.location.pathname)
        logger.info('AuthStore', 'Token received from OAuth callback, stored in sessionStorage')
      } else {
        // 3. Restore from sessionStorage
        token = sessionStorage.getItem('refchecker_auth_token')
      }

      if (!token) {
        // No token – user needs to log in
        set({ authEnabled: true, isLoading: false })
        return
      }

      // Validate token against server and get user info
      api.setAuthToken(token)
      const meResp = await api.getAuthMe()
      const { user } = meResp.data

      if (!user) {
        sessionStorage.removeItem('refchecker_auth_token')
        api.setAuthToken(null)
        set({ authEnabled: true, isLoading: false, token: null, user: null })
        return
      }

      // Load in-memory API key status
      let apiKeyProviders = []
      try {
        const keysResp = await api.getUserApiKeyProviders()
        apiKeyProviders = keysResp.data.providers || []
      } catch (_) { /* ignore */ }

      set({
        authEnabled: true,
        token,
        user,
        isLoading: false,
        apiKeyProviders,
      })
      logger.info('AuthStore', `Authenticated as ${user.email || user.name}`)
    } catch (err) {
      logger.error('AuthStore', 'Init failed', err)
      set({ isLoading: false, error: err.message })
    }
  },

  // ------- OAuth login redirects -------

  loginWithGoogle: () => {
    logger.info('AuthStore', 'Redirecting to Google OAuth...')
    window.location.href = '/api/auth/google'
  },

  loginWithGithub: () => {
    logger.info('AuthStore', 'Redirecting to GitHub OAuth...')
    window.location.href = '/api/auth/github'
  },

  // ------- Logout -------

  logout: async () => {
    try {
      await api.authLogout()
    } catch (_) { /* ignore server-side logout errors */ }
    sessionStorage.removeItem('refchecker_auth_token')
    api.setAuthToken(null)
    set({ token: null, user: null, apiKeyProviders: [] })
    logger.info('AuthStore', 'Logged out')
  },

  // ------- In-memory API key management -------

  storeApiKey: async (provider, apiKey) => {
    const { user } = get()
    if (!user) return
    await api.setUserApiKey(provider, apiKey)
    set(state => ({
      apiKeyProviders: state.apiKeyProviders.includes(provider)
        ? state.apiKeyProviders
        : [...state.apiKeyProviders, provider],
    }))
    logger.info('AuthStore', `API key stored for provider ${provider}`)
  },

  removeApiKey: async (provider) => {
    const { user } = get()
    if (!user) return
    await api.deleteUserApiKey(provider)
    set(state => ({
      apiKeyProviders: state.apiKeyProviders.filter(p => p !== provider),
    }))
    logger.info('AuthStore', `API key removed for provider ${provider}`)
  },

  hasApiKey: (provider) => {
    return get().apiKeyProviders.includes(provider)
  },
}))
