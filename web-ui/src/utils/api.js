import axios from 'axios'
import { logger } from './logger'

const api = axios.create({
  baseURL: '/api',
  // 90 s default. v0.7.46: bumped from 30 s because /history queries
  // started timing out at the FE while a giant batch was concurrently
  // writing to SQLite. The backend itself still has per-endpoint
  // timeouts; this just gives the FE more patience before declaring
  // a request lost.
  timeout: 90000,
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
// Fast-timeout endpoints (v0.7.54 per full-stack review): if the
// backend is unreachable the splash spinner / status bar must
// fail-fast, not hang for the 90 s default. 5 s for liveness probes,
// 8 s for auth bootstrap.
export const health = () => api.get('/health', { timeout: 5000 })

// -----------------------------------------------------------------------
// Auth endpoints
// -----------------------------------------------------------------------
export const getAuthProviders = () => api.get('/auth/providers')
export const getAuthMe = () => api.get('/auth/me', { timeout: 8000 })
export const authLogout = () => api.post('/auth/logout')

// User-scoped UI preferences
export const getUserPreferences = () => api.get('/user/preferences')
export const updateUserPreferences = (preferences) => api.put('/user/preferences', preferences)

// LLM Configurations
export const getLLMConfigs = () => api.get('/llm-configs')
export const createLLMConfig = (config) => api.post('/llm-configs', config)
export const updateLLMConfig = (id, config) => api.put(`/llm-configs/${id}`, config)
export const deleteLLMConfig = (id) => api.delete(`/llm-configs/${id}`)
export const setDefaultLLMConfig = (id) => api.post(`/llm-configs/${id}/set-default`)
export const validateLLMConfig = (config) => api.post('/llm-configs/validate', config)

// Semantic Scholar API Key management
export const validateSemanticScholarKey = (apiKey) => api.post('/settings/semantic-scholar/validate', { api_key: apiKey })
export const getSemanticScholarKeyStatus = () => api.get('/settings/semantic-scholar')
export const setSemanticScholarKey = (apiKey) => api.put('/settings/semantic-scholar', { api_key: apiKey })
export const deleteSemanticScholarKey = () => api.delete('/settings/semantic-scholar')

// Paperclip secondary verification tier — biomedical full-text +
// arXiv. Single-user mode stores the key in the local database; multi-user
// mode keeps it in the browser key cache and sends it per request.
export const getPaperclipKeyStatus = () => api.get('/settings/paperclip')
export const setPaperclipKey = (apiKey) => api.put('/settings/paperclip', { api_key: apiKey })
export const deletePaperclipKey = () => api.delete('/settings/paperclip')

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
// Batch summary + aggregated LLM usage (v0.7.45)
export const getBatch = (batchId) => api.get(`/batch/${batchId}`)
export const getBatchLLMUsage = (batchId) => api.get(`/batch/${batchId}/llm-usage`)

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

// Local database downloader (used by the desktop app's first-run flow)
export const triggerDatabaseDownload = (payload) => api.post('/databases/download', payload)
export const getDatabaseDownloadStatus = () => api.get('/databases/download/status')
export const cancelDatabaseDownload = (database) => api.post('/databases/download/cancel', { database })

// AI-generated-text detection: local model management
export const getAIDetectionModelStatus = () => api.get('/ai-detection/model/status')
export const downloadAIDetectionModel = () => api.post('/ai-detection/model/download')
export const deleteAIDetectionModel = () => api.delete('/ai-detection/model')

// OpenReview venue scanning
export const fetchOpenReviewList = (venue, status = 'accepted') =>
  api.post('/openreview/list', { venue, status })

// One-click "use default location" for cache_dir / db_path
export const autoCreatePath = (setting) =>
  api.post('/settings/auto-create-path', { setting })

// Live model lookup for the LLM config modal (combobox source)
export const listLLMModels = (provider, api_key, endpoint) =>
  api.post('/llm-configs/models', { provider, api_key, endpoint })

// Global identity-keyed reference cache ("Seen References" tab)
export const listSeenReferences = (limit = 200, offset = 0, q = null) =>
  api.get('/references/seen', { params: { limit, offset, ...(q ? { q } : {}) } })

// Similar-papers recommendations + co-citation tally — Semantic Scholar's
// /recommendations endpoint is slow, so this can legitimately take longer
// than the default 30s. Give it a 2-minute budget.
export const findSimilarPapers = ({ references, paper_title, paper_id, limit = 5 }) =>
  api.post('/papers/similar', { references, paper_title, paper_id, limit }, { timeout: 120000 })

// Real inter-reference citation graph via Semantic Scholar
export const fetchCitationGraph = ({ references, paper_title }) =>
  api.post('/papers/citation-graph', { references, paper_title }, { timeout: 120000 })

// One-hop expand: a paper's outgoing references for the graph view.
// `title` is optional — the backend uses it to do a title-search
// fallback when /paper/<id>/references returns nothing for the DOI.
export const expandPaper = ({ paper_id, limit = 8, title = null, ai_detection = false }) =>
  api.post('/papers/expand', { paper_id, limit, title, ai_detection })

// Per-check edit endpoints (Add/Remove citation, regenerate health stats)
export const addReferenceToCheck = (checkId, payload) =>
  api.post(`/history/${checkId}/references`, payload)
export const removeReferenceFromCheck = (checkId, refId) =>
  api.delete(`/history/${checkId}/references/${encodeURIComponent(refId)}`)
export const suggestAlternativeReference = (checkId, refId) =>
  api.post(`/history/${checkId}/references/${encodeURIComponent(refId)}/suggest-alternative`)
export const verifyReferenceInCheck = (checkId, refId, opts = {}) =>
  api.post(`/history/${checkId}/references/${encodeURIComponent(refId)}/verify`, opts)

// Per-check LLM token + cost accumulator for the $ badge
export const getLLMUsage = (checkId) =>
  api.get(`/history/${checkId}/llm-usage`)

// Resolve a DOI to title/authors/year/venue via CrossRef
export const resolveDoi = (doi) =>
  api.get('/doi/resolve', { params: { doi } })

// Best-effort DOI -> OCLC via Wikidata SPARQL. Cached server-side
// and returns `{ oclc: null }` when no match (typical: article-level
// hit rate is <10%; books / journal-level entries do much better).
export const lookupOclc = (doi) =>
  api.get('/oclc-lookup', { params: { doi } })

// Clear the global Seen References cache
export const clearSeenReferences = () =>
  api.delete('/references/seen')

// Manually re-run the Seen-Refs backfill from check_history. Returns
// diagnostic counters (walked / inserted / updated / skipped) so the
// FE can show the user whether their checks ARE producing new identity
// keys or whether the count is genuinely stuck. Can take a few seconds
// on libraries with thousands of historic checks — give it a longer
// budget than the default 30s.
export const backfillSeenReferences = () =>
  api.post('/references/seen/backfill', null, { timeout: 120000 })

// Per-provider LLM token + cost totals
export const fetchUsageTotals = () => api.get('/usage/totals')
export const resetUsageTotals = () => api.delete('/usage/totals')

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
  validateLLMConfig,
  validateSemanticScholarKey,
  getSemanticScholarKeyStatus,
  setSemanticScholarKey,
  deleteSemanticScholarKey,
  getPaperclipKeyStatus,
  setPaperclipKey,
  deletePaperclipKey,
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

