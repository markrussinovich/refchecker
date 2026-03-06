import axios from 'axios'
import { logger } from './logger'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// -----------------------------------------------------------------------
// Auth token management
// The token is injected into every request via the request interceptor.
// -----------------------------------------------------------------------
let _authToken = null

export const setAuthToken = (token) => {
  _authToken = token
}

// Request interceptor for logging + auth header injection
api.interceptors.request.use(
  (config) => {
    logger.debug('API', `${config.method?.toUpperCase()} ${config.url}`, config.data)
    if (_authToken) {
      config.headers = config.headers || {}
      config.headers['Authorization'] = `Bearer ${_authToken}`
    }
    return config
  },
  (error) => {
    logger.error('API', 'Request error', error)
    return Promise.reject(error)
  }
)

// Response interceptor for logging
api.interceptors.response.use(
  (response) => {
    logger.debug('API', `Response ${response.status} from ${response.config.url}`)
    return response
  },
  (error) => {
    logger.error('API', `Error from ${error.config?.url}`, error.response?.data || error.message)
    return Promise.reject(error)
  }
)

// Health check
export const health = () => api.get('/health')

// -----------------------------------------------------------------------
// Auth endpoints
// -----------------------------------------------------------------------
export const getAuthProviders = () => api.get('/auth/providers')
export const getAuthMe = () => api.get('/auth/me')
export const authLogout = () => api.post('/auth/logout')

// In-memory user API key management (multi-user mode)
export const getUserApiKeyProviders = () => api.get('/user/api-keys')
export const setUserApiKey = (provider, apiKey) => api.post('/user/api-keys', { provider, api_key: apiKey })
export const deleteUserApiKey = (provider) => api.delete(`/user/api-keys/${provider}`)

// LLM Configurations
export const getLLMConfigs = () => api.get('/llm-configs')
export const createLLMConfig = (config) => api.post('/llm-configs', config)
export const updateLLMConfig = (id, config) => api.put(`/llm-configs/${id}`, config)
export const deleteLLMConfig = (id) => api.delete(`/llm-configs/${id}`)
export const setDefaultLLMConfig = (id) => api.post(`/llm-configs/${id}/set-default`)
export const validateLLMConfig = (config) => api.post('/llm-configs/validate', config)

// Semantic Scholar API Key
export const getSemanticScholarKeyStatus = () => api.get('/settings/semantic-scholar')
export const setSemanticScholarKey = (apiKey) => api.put('/settings/semantic-scholar', { api_key: apiKey })
export const deleteSemanticScholarKey = () => api.delete('/settings/semantic-scholar')
export const validateSemanticScholarKey = (apiKey) => api.post('/settings/semantic-scholar/validate', { api_key: apiKey })

// Check operations
export const startCheck = (formData) => api.post('/check', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
  timeout: 0, // No timeout for file uploads
})

export const cancelCheck = (sessionId) => api.post(`/cancel/${sessionId}`)

// History operations
export const getHistory = (limit = 50) => api.get('/history', { params: { limit } })
export const getCheckDetail = (id) => api.get(`/history/${id}`)
export const deleteCheck = (id) => api.delete(`/history/${id}`)
export const updateCheckLabel = (id, label) => api.patch(`/history/${id}`, { custom_label: label })
export const recheck = (id) => api.post(`/recheck/${id}`)

// Admin operations
export const clearCache = () => api.delete('/admin/cache')
export const clearDatabase = () => api.delete('/admin/database')

// WebSocket connection factory
export const createWebSocket = (sessionId, handlers) => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  // Include auth token as query param (WS headers are not easily settable)
  const tokenParam = _authToken ? `?token=${encodeURIComponent(_authToken)}` : ''
  const wsUrl = `${protocol}//${host}/api/ws/${sessionId}${tokenParam}`
  
  logger.info('WebSocket', `Connecting to ${wsUrl}`)
  
  const ws = new WebSocket(wsUrl)
  
  ws.onopen = () => {
    logger.info('WebSocket', 'Connected')
    handlers.onOpen?.()
  }
  
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      logger.debug('WebSocket', `Message received: ${data.type}`, data)
      handlers.onMessage?.(data)
    } catch (e) {
      logger.error('WebSocket', 'Failed to parse message', e)
    }
  }
  
  ws.onerror = (error) => {
    logger.error('WebSocket', 'Error', error)
    handlers.onError?.(error)
  }
  
  ws.onclose = (event) => {
    logger.info('WebSocket', `Disconnected (code: ${event.code})`)
    handlers.onClose?.(event)
  }
  
  return ws
}

export default {
  health,
  getAuthProviders,
  getAuthMe,
  authLogout,
  getUserApiKeyProviders,
  setUserApiKey,
  deleteUserApiKey,
  setAuthToken,
  getLLMConfigs,
  createLLMConfig,
  updateLLMConfig,
  deleteLLMConfig,
  setDefaultLLMConfig,
  getSemanticScholarKeyStatus,
  setSemanticScholarKey,
  deleteSemanticScholarKey,
  validateSemanticScholarKey,
  startCheck,
  cancelCheck,
  getHistory,
  getCheckDetail,
  deleteCheck,
  updateCheckLabel,
  recheck,
  createWebSocket,
  clearCache,
  clearDatabase,
}

