import { create } from 'zustand'
import { logger } from '../utils/logger'
import * as api from '../utils/api'

/**
 * Store for cookie-based authentication state.
 *
 * Auth is always required. The rc_auth HttpOnly cookie is managed by the
 * server and sent automatically by the browser on every request.
 *
 * On init:
 *  1. Fetches /api/auth/providers to discover available OAuth providers.
 *  2. Calls /api/auth/me — if the cookie is valid, user is populated.
 *     A 401 means the user is not logged in (not an error).
 *  3. Checks for ?auth_error= in the URL (set by failed OAuth callbacks).
 *
 * Login helpers redirect the browser to the OAuth provider URL.
 * After OAuth completes, the server sets the cookie and redirects to /.
 */
export const useAuthStore = create((set, get) => {
  // Listen for 401 events dispatched by the api response interceptor
  if (typeof window !== 'undefined') {
    window.addEventListener('auth:unauthorized', () => {
      logger.warn('AuthStore', 'Received auth:unauthorized event, clearing user')
      set({ user: null })
    })
  }

  return {
    // ------- State -------
    providers: [],    // ['google', 'github', 'microsoft', ...]
    user: null,       // { id, email, name, avatar_url, provider }
    isLoading: true,  // true while bootstrapping
    error: null,

    // ------- Init -------

    init: async () => {
      logger.info('AuthStore', 'Initialising auth...')
      set({ isLoading: true, error: null })

      // Check for OAuth error in URL
      const urlParams = new URLSearchParams(window.location.search)
      const callbackError = urlParams.get('auth_error')
      if (callbackError) {
        logger.warn('AuthStore', `OAuth error: ${callbackError}`)
        window.history.replaceState({}, '', window.location.pathname)
        set({ isLoading: false, error: `Login failed: ${callbackError}` })
        return
      }

      try {
        const provResp = await api.getAuthProviders()
        const providers = provResp.data.providers || []
        logger.info('AuthStore', `Providers: ${providers}`)

        // No OAuth providers configured → single-user mode, skip auth
        if (providers.length === 0) {
          logger.info('AuthStore', 'No providers configured — single-user mode')
          set({ providers: [], user: { id: 0, name: 'Local User', provider: 'local' }, isLoading: false })
          return
        }

        try {
          const meResp = await api.getAuthMe()
          const user = meResp.data.user || null
          set({ providers, user, isLoading: false })
          if (user) logger.info('AuthStore', `Authenticated as ${user.email || user.name}`)
        } catch (_) {
          // 401 means not logged in — that's fine
          set({ providers, user: null, isLoading: false })
        }
      } catch (err) {
        // If providers endpoint fails (500, network error, etc.) → assume single-user mode
        logger.warn('AuthStore', 'Providers fetch failed — falling back to single-user mode', err)
        set({ providers: [], user: { id: 0, name: 'Local User', provider: 'local' }, isLoading: false })
      }
    },

    // ------- OAuth login redirects -------

    loginWithGoogle: () => {
      logger.info('AuthStore', 'Redirecting to Google OAuth...')
      window.location.href = '/api/auth/login/google'
    },

    loginWithGithub: () => {
      logger.info('AuthStore', 'Redirecting to GitHub OAuth...')
      window.location.href = '/api/auth/login/github'
    },

    loginWithMicrosoft: () => {
      logger.info('AuthStore', 'Redirecting to Microsoft OAuth...')
      window.location.href = '/api/auth/login/microsoft'
    },

    // ------- Logout -------

    logout: async () => {
      try {
        await api.authLogout()
      } catch (_) { /* ignore server-side logout errors */ }
      set({ user: null })
      logger.info('AuthStore', 'Logged out')
    },
  }
})
