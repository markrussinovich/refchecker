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
// In-app multi-user / OAuth enablement (Settings → Enable accounts & Teams).
// getAuthConfig returns presence/state only (never secret values); setAuthConfig
// persists creds + the multiuser flag for the next backend start.
export const getAuthConfig = () => api.get('/auth/config')
export const setAuthConfig = (config) => api.put('/auth/config', config)

// User-scoped UI preferences
export const getUserPreferences = () => api.get('/user/preferences')
export const updateUserPreferences = (preferences) => api.put('/user/preferences', preferences)

// Teams (issue #66): create + list my teams, list + add members.
export const getTeams = () => api.get('/teams')
export const createTeam = (name) => api.post('/teams', { name })
export const getTeamMembers = (teamId) => api.get(`/teams/${teamId}/members`)
export const addTeamMember = (teamId, { email, user_id, role } = {}) =>
  api.post(`/teams/${teamId}/members`, { email, user_id, role })
export const removeTeamMember = (teamId, userId) =>
  api.delete(`/teams/${teamId}/members/${userId}`)
export const leaveTeam = (teamId) => api.post(`/teams/${teamId}/leave`)
export const getTeamActivity = (teamId) => api.get(`/teams/${teamId}/activity`)
// R26: checks shared with a team, and sharing a single check / whole batch.
export const getTeamChecks = (teamId) => api.get(`/teams/${teamId}/checks`)
export const shareCheckWithTeam = (checkId, teamId) =>
  api.post(`/checks/${checkId}/share`, { team_id: teamId })

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
// R26: share the whole batch with a team (team_id 0 unshares) via the extended PATCH.
export const shareBatchWithTeam = (batchId, teamId) =>
  api.patch(`/batch/${batchId}`, { team_id: teamId })
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
// Explicit (off the status-poll hot path) check for a newer model revision on HF.
export const checkAIDetectionModelUpdate = () => api.get('/ai-detection/model/update-check', { timeout: 20000 })
export const downloadAIDetectionModel = () => api.post('/ai-detection/model/download')
export const deleteAIDetectionModel = () => api.delete('/ai-detection/model')
export const getAIDetectionRuntimeStatus = () => api.get('/ai-detection/runtime/status')
export const installAIDetectionRuntime = (variant = 'torch') =>
  api.post('/ai-detection/runtime/install', null, { params: { variant } })
export const getAIDetectionDiagnostics = () => api.get('/ai-detection/diagnostics')

// R61 (I1 endpoints) — multi-detector registry. The backend lands in parallel;
// these talk to the §14-item-2 endpoint shapes. The registry lists every
// detector in DETECTOR_REGISTRY with real size/license/tier + per-detector
// install state; install/remove mirror the existing on-demand HF download
// lifecycle (returns the refreshed registry row(s)). HONESTY: an uninstalled
// detector is reported as installed:false so the FE can abstain — it never
// fabricates a number for a detector that isn't downloaded.
export const getDetectors = () => api.get('/ai-detection/detectors')
// Install (download) a single detector by key. No timeout — Tier-2 heavy
// detectors are large multi-GB downloads handled by a background job the FE
// polls via getDetectors().
export const installDetector = (key) =>
  api.post(`/ai-detection/detectors/${encodeURIComponent(key)}/install`, null, { timeout: 0 })
export const removeDetector = (key) =>
  api.delete(`/ai-detection/detectors/${encodeURIComponent(key)}`)

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
// "Add to Library": persist a single reference (+ its enrichment) into the
// global Seen-References cache. Idempotent; returns {added, times_seen}.
export const addSeenReference = (reference, checkId = null, paperTitle = null) =>
  api.post('/references/seen', { reference, check_id: checkId, paper_title: paperTitle })
// Journal/venue metadata for the venue-name hover (OpenAlex /sources + DOAJ
// guidelines). Soft-fails to { available: false }; never fabricates.
export const getVenueProfile = ({ venue_id = null, issn = null, venue_name = null } = {}) =>
  api.post('/venues/profile', { venue_id, issn, venue_name }, { timeout: 12000 })

// Related-papers discovery via real OpenAlex bibliography overlap. Resolving
// the source paper + walking its citation neighbourhood can take a while, so
// keep the generous 2-minute budget.
// `mode`: 'references' (papers that share REFERENCES with this paper —
// bibliography overlap), 'citations' (papers that share CITATIONS / are
// co-cited with it), or 'both' (the union). Legacy values ('similar',
// 'cites_refs') are accepted and mapped server-side.
export const findSimilarPapers = ({ references, paper_title, paper_id, limit = 5, mode = 'both' }) =>
  api.post('/papers/similar', { references, paper_title, paper_id, limit, mode }, { timeout: 120000 })

// Real inter-reference citation graph via Semantic Scholar
export const fetchCitationGraph = ({ references, paper_title, ai_detection = false }) =>
  // Backend now fans the S2 lookups out concurrently, so this is far faster;
  // the generous ceiling covers a 60-ref bibliography plus the optional
  // offline AI-gen pass under slow networks without the old 120s cutoff.
  api.post('/papers/citation-graph', { references, paper_title, ai_detection }, { timeout: 180000 })

// One-hop expand: a paper's outgoing references for the graph view.
// `title` is optional — the backend uses it to do a title-search
// fallback when /paper/<id>/references returns nothing for the DOI.
export const expandPaper = ({ paper_id, limit = 8, title = null, ai_detection = false }) =>
  api.post('/papers/expand', { paper_id, limit, title, ai_detection })

// Enriched Semantic Scholar author profile for the hover card (cached server-side).
// Author profile for the hover card. Accepts a Semantic Scholar id (string) or
// { author_id, openalex_id } — OpenAlex is the fallback for non-S2 authors so
// h-index / citations / ORCID still appear.
export const fetchAuthorProfile = (idOrOpts) => {
  const body = typeof idOrOpts === 'string'
    ? { author_id: String(idOrOpts) }
    : { author_id: idOrOpts?.author_id ? String(idOrOpts.author_id) : null, openalex_id: idOrOpts?.openalex_id || null }
  return api.post('/authors/profile', body, { timeout: 15000 })
}

// R10 (A3): resolve a SINGLE high-confidence profile for an ID-less author from
// a bare name PLUS the citing paper's title/year. The backend only returns a
// match when the author actually appears on a work matching the title — a miss
// returns { available: false } (never a guess). Used by the AuthorChip "Find
// profile" action for authors with no s2_author_id / openalex_id.
export const findAuthorProfile = ({ name, title = null, year = null } = {}) =>
  api.post('/authors/find', { name, title, year }, { timeout: 15000 })

// Nodes + edges for the 3D Seen-References library graph.
export const fetchReferenceLibraryGraph = ({ limit = 400, min_times_seen = 1, edge_strategy = 'shared-authors' } = {}) =>
  api.get('/references/library/graph', { params: { limit, min_times_seen, edge_strategy }, timeout: 60000 })

// Locate target texts (AI-flagged passages / citation contexts) in the native
// PDF -> per-target page + normalized rects, for highlight overlays.
export const locatePdfSpans = (checkId, targets) =>
  api.post(`/preview/${checkId}/locate`, { targets }, { timeout: 30000 })

// Share / export.
export const exportCheckHtml = (checkId) =>
  api.get(`/export/${checkId}/html`, { responseType: 'blob', timeout: 30000 })
// Multi-format export: fmt ∈ html|pdf|md|docx; corrections toggles suggested
// fixes; include = array of sections (summary,ai,issues,references) to keep.
// summary (R48) = the FE's canonical buildReferenceSummary result; passing it
// makes the exported counts + citation-health byte-identical to the in-app
// Summary badge / report card (the server otherwise recomputes them and a
// style-suppressed warning could drift the verified/warning boundary).
const _exportParams = ({ fmt = 'html', corrections = false, include, summary } = {}) => {
  const p = new URLSearchParams({ fmt, corrections: corrections ? 'true' : 'false' })
  if (Array.isArray(include) && include.length) p.set('include', include.join(','))
  if (summary && typeof summary === 'object') {
    try { p.set('summary', JSON.stringify(summary)) } catch { /* skip on cycles */ }
  }
  return p.toString()
}
export const exportCheckFile = (checkId, opts = {}) =>
  api.get(`/export/${checkId}/file?${_exportParams(opts)}`, { responseType: 'blob', timeout: 60000 })
export const exportBatchFile = (batchId, opts = {}) =>
  api.get(`/export/batch/${batchId}/file?${_exportParams(opts)}`, { responseType: 'blob', timeout: 120000 })
export const publishCheck = (checkId, { adapter = 'github_gist', token = '', public: isPublic = false } = {}) =>
  api.post(`/export/${checkId}/publish`, { adapter, token, public: isPublic }, { timeout: 30000 })
// Citation health + retraction (real signals).
export const getCheckHealth = (checkId) => api.get(`/check/${checkId}/health`, { timeout: 15000 })
export const getCheckRetractions = (checkId) => api.get(`/check/${checkId}/retractions`, { timeout: 45000 })
export const getCheckGaps = (checkId) => api.get(`/check/${checkId}/gaps`, { timeout: 60000 })
export const getCitationIntegrity = (checkId) => api.get(`/check/${checkId}/citation-integrity`, { timeout: 60000 })
// Grounded Chat-with-PDF + Summarize (EPIC-D). Answers ONLY from the article's
// own text; abstains honestly when the article does not state something. The
// optional config carries {llm_config_id, provider, model, api_key}.
export const getArticleSummary = (checkId, config = {}) =>
  api.post(`/check/${checkId}/summarize`, config, { timeout: 120000 })
export const postArticleChat = (checkId, messages, config = {}) =>
  api.post(`/check/${checkId}/chat`, { ...config, messages }, { timeout: 120000 })
// R43 — per-reference chat grounded in the reference's OWN fetched full text.
// Resolves the cited reference's open-access PDF (arXiv → OpenAlex
// best_oa_location / Unpaywall), downloads + extracts it, and returns
// { source:'pdf', grounding:<full_text> } when real text was fetched, else
// { source:'tldr', grounding:null } so the UI keeps the TL;DR-only disclaimer.
// HONESTY: only real fetched text — never fabricated.
export const postReferenceFulltext = (checkId, reference) =>
  api.post(`/check/${checkId}/reference-fulltext`, {
    doi: reference?.doi || null,
    verified_doi: reference?.verified_doi || null,
    arxiv_id: reference?.arxiv_id || null,
    title: reference?.title || null,
    enrichment: reference?.enrichment || null,
  }, { timeout: 90000 })
// Read-only preview of how inline numeric markers would renumber if a new
// reference were inserted at the given 1-based printed position (omit to append).
// Abstains (empty shifts) whenever the inline-citation checker abstains.
export const getCitationRenumberPreview = (checkId, insertAt) =>
  api.get(`/check/${checkId}/citation-renumber-preview`, { params: insertAt != null ? { insert_at: insertAt } : {}, timeout: 60000 })

// R18 (G1) — the full reference list re-serialized in a citation style with new
// contiguous numbers (1..N) after an Add/renumber. Backs the "Download new
// reference list" button. `renumber=1` numbers by list position; a chosen
// `style` selects the citation format (defaults to plaintext server-side).
export const getCorrectedReferenceList = (checkId, { style = 'plaintext', renumber = true } = {}) =>
  api.get(`/check/${checkId}/corrected-reference-list`, { params: { style, renumber: renumber ? 1 : 0 }, timeout: 60000 })

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

// Extracted body text of a check's source document — used by the in-document
// highlighter to show AI-detection flagged passages in context. Larger papers
// can take a moment to extract, so give it a generous budget.
export const getPaperText = (checkId) =>
  api.get(`/paper-text/${checkId}`, { timeout: 60000 })

// Fetch the original source PDF bytes (for native PDF.js rendering). Goes
// through axios (cookies/auth) and returns an ArrayBuffer; 404 when the source
// isn't a PDF (the viewer then falls back to the extracted-text view).
export const getPaperPdf = (checkId) =>
  api.get(`/paper-pdf/${checkId}`, { responseType: 'arraybuffer', timeout: 60000 })

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

// "Remove from Library": drop a single reference from the global
// Seen-References cache. Counterpart to addSeenReference. When the ref
// already carries an `identity_key` (Seen-Refs library rows do), delete by
// path; otherwise POST the reference body so the server resolves the same
// identity key the add/upsert path computes. Returns { removed: bool }.
export const removeSeenReference = (reference) => {
  const ref = reference && typeof reference === 'object' ? reference : {}
  const identityKey = ref.identity_key
  if (identityKey) {
    return api.delete(`/references/seen/${encodeURIComponent(identityKey)}`)
  }
  return api.post('/references/seen/remove', { reference: ref })
}

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

// Presence WebSocket factory (issue #67) — connects to a shared room
// (batch/check id) so team members viewing the same batch see each other.
// Cookie auth is sent automatically by the browser for same-origin WS.
export const createPresenceWebSocket = (roomId, handlers) => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const wsUrl = `${protocol}//${host}/api/ws/presence/${encodeURIComponent(roomId)}`

  const ws = new WebSocket(wsUrl)
  ws.onopen = () => handlers.onOpen?.()
  ws.onmessage = (event) => {
    try {
      handlers.onMessage?.(JSON.parse(event.data))
    } catch (e) {
      logger.error('Presence', 'Failed to parse message', e)
    }
  }
  ws.onerror = (error) => handlers.onError?.(error)
  ws.onclose = (event) => handlers.onClose?.(event)
  return ws
}

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

