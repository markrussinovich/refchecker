import axios from 'axios'
import { logger } from './logger'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  withCredentials: true, // send rc_auth cookie on every request
})

// Request interceptor for logging
api.interceptors.request.use(
  (config) => {
    logger.debug('API', `${config.method?.toUpperCase()} ${config.url}`, config.data)
    return config
  },
  (error) => {
    logger.error('API', 'Request error', error)
    return Promise.reject(error)
  }
)

// Response interceptor: logging + 401 handler
api.interceptors.response.use(
  (response) => {
    logger.debug('API', `Response ${response.status} from ${response.config.url}`)
    return response
  },
  (error) => {
    if (error.response?.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'))
    }
    logger.error('API', `Error from ${error.config?.url}`, error.response?.data || error.message)
    return Promise.reject(error)
  }
)

// No-op kept for backward compat (tests may reference it)
export const setAuthToken = (_token) => {}

// Health check
export const health = () => api.get('/health')

// -----------------------------------------------------------------------
// Auth endpoints
// -----------------------------------------------------------------------
export const getAuthProviders = () => api.get('/auth/providers')
export const getAuthMe = () => api.get('/auth/me')
export const authLogout = () => api.post('/auth/logout')

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

export const startBatchCheck = (payload) => api.post('/check/batch', payload, {
  timeout: 0,
})

export const startBatchFileCheck = (formData) => api.post('/check/batch/files', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
  timeout: 0,
})

export const cancelCheck = (sessionId) => api.post(`/cancel/${sessionId}`)
export const cancelBatch = (batchId) => api.post(`/cancel/batch/${batchId}`)

// History operations
export const getHistory = (limit = 50) => api.get('/history', { params: { limit } })
export const getCheckDetail = (id) => api.get(`/history/${id}`)
export const deleteCheck = (id) => api.delete(`/history/${id}`)
export const updateCheckLabel = (id, label) => api.patch(`/history/${id}`, { custom_label: label })
export const updateBatchLabel = (batchId, label) => api.patch(`/batch/${batchId}`, { batch_label: label })
export const recheck = (id) => api.post(`/recheck/${id}`)

// Admin operations
export const clearCache = () => api.delete('/admin/cache')
export const clearDatabase = () => api.delete('/admin/database')

// WebSocket connection factory — cookie is sent automatically by browser for same-origin WS
export const createWebSocket = (sessionId, handlers) => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const wsUrl = `${protocol}//${host}/api/ws/${sessionId}`
  
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
  startBatchCheck,
  startBatchFileCheck,
  cancelCheck,
  cancelBatch,
  getHistory,
  getCheckDetail,
  deleteCheck,
  updateCheckLabel,
  updateBatchLabel,
  recheck,
  createWebSocket,
  clearCache,
  clearDatabase,
}

