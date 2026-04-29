import { create } from 'zustand'
import { logger } from '../utils/logger'
import { useHistoryStore } from './useHistoryStore'

/**
 * Store for current check state management
 */
export const useCheckStore = create((set, get) => ({
  // State
  status: 'idle', // idle, checking, completed, cancelled, error
  sessionId: null,
  currentCheckId: null, // ID of the check in history (created immediately)
  sessionToCheckMap: {}, // Maps session_id -> check_id for routing concurrent session messages
  activeSessions: [], // List of all active session IDs (for WebSocket connections)
  paperTitle: null,
  paperSource: null, // URL or filename being checked
  sourceType: null, // 'url', 'file', or 'text'
  statusMessage: '',
  progress: 0,
  references: [],
  stats: {
    total_refs: 0,
    processed_refs: 0,
    verified_count: 0,
    errors_count: 0,
    warnings_count: 0,
    suggestions_count: 0,
    unverified_count: 0,
    hallucination_count: 0,
    refs_with_issues: 0,
    refs_with_errors: 0,
    refs_with_warnings_only: 0,
    refs_verified: 0,
    progress_percent: 0,
  },
  error: null,
  completedCheckId: null,
  statusFilter: [], // empty = show all, or array of ['verified', 'error', 'warning', 'unverified']

  // Actions
  startCheck: (sessionId, checkId = null, paperSource = null, sourceType = null, paperTitle = null) => {
    logger.info('CheckStore', `Starting check with session ${sessionId}, checkId ${checkId}, sourceType ${sourceType}, paperTitle ${paperTitle}`)
    // Record session→check mapping before overwriting state
    const prevMap = get().sessionToCheckMap
    const newMap = checkId ? { ...prevMap, [sessionId]: checkId } : prevMap
    // Add to active sessions
    const activeSessions = get().activeSessions.includes(sessionId) 
      ? get().activeSessions 
      : [...get().activeSessions, sessionId]
    set({
      status: 'checking',
      sessionId,
      currentCheckId: checkId,
      sessionToCheckMap: newMap,
      activeSessions,
      paperTitle: paperTitle,
      paperSource,
      sourceType,
      statusMessage: 'Starting check...',
      progress: 0,
      references: [],
      stats: {
        total_refs: 0,
        processed_refs: 0,
        verified_count: 0,
        errors_count: 0,
        warnings_count: 0,
        suggestions_count: 0,
        unverified_count: 0,
        hallucination_count: 0,
        refs_with_issues: 0,
        refs_with_errors: 0,
        refs_with_warnings_only: 0,
        refs_verified: 0,
        progress_percent: 0,
      },
      error: null,
      completedCheckId: null,
      statusFilter: [],
    })
  },

  // Register a session from page refresh (in_progress items with session_id)
  registerSession: (sessionId, checkId) => {
    if (!sessionId) return
    const { sessionToCheckMap, activeSessions } = get()
    const alreadyActive = activeSessions.includes(sessionId)
    logger.info('CheckStore', `Registering session ${sessionId} for check ${checkId}, alreadyActive=${alreadyActive}`)
    set({
      sessionToCheckMap: { ...sessionToCheckMap, [sessionId]: checkId },
      activeSessions: alreadyActive ? activeSessions : [...activeSessions, sessionId],
    })
  },

  // Remove a session when it completes
  unregisterSession: (sessionId) => {
    if (!sessionId) return
    const { sessionToCheckMap, activeSessions } = get()
    const newMap = { ...sessionToCheckMap }
    delete newMap[sessionId]
    set({
      sessionToCheckMap: newMap,
      activeSessions: activeSessions.filter(s => s !== sessionId),
    })
  },

  adoptSession: (payload) => {
    const {
      session_id,
      id,
      paper_title,
      paper_source,
      results = [],
      total_refs = 0,
      errors_count = 0,
      warnings_count = 0,
      suggestions_count = 0,
      unverified_count = 0,
      hallucination_count = 0,
      refs_with_issues = 0,
      refs_with_errors: payloadRefsWithErrors,
      refs_with_warnings_only: payloadRefsWithWarningsOnly,
      refs_verified: payloadRefsVerified,
    } = payload || {}

    const processed_refs = Array.isArray(results) ? results.length : 0
    const verified_count = Math.max(total_refs - errors_count - warnings_count - suggestions_count - unverified_count, 0)
    const progress_percent = total_refs > 0 ? Math.min((processed_refs / total_refs) * 100, 100) : 0

    // Compute paper-level counts from results if not provided
    let refs_with_errors = payloadRefsWithErrors ?? 0
    let refs_with_warnings_only = payloadRefsWithWarningsOnly ?? 0
    let refs_verified = payloadRefsVerified ?? 0

    if (Array.isArray(results) && results.length > 0 && 
        refs_with_errors === 0 && refs_with_warnings_only === 0 && refs_verified === 0) {
      results.forEach(ref => {
        const hasErrors = ref.errors?.some(e => e.error_type !== 'unverified')
        const hasWarnings = ref.warnings?.length > 0
        const status = (ref.status || '').toLowerCase()
        
        if (status === 'error' || hasErrors) {
          refs_with_errors++
        } else if (status === 'warning' || hasWarnings) {
          refs_with_warnings_only++
        } else if (status === 'verified' || status === 'suggestion') {
          // Suggestion-only refs are considered verified (no errors or warnings)
          refs_verified++
        }
      })
    }

    logger.info('CheckStore', `Adopting in-progress session ${session_id} for check ${id}`)

    set({
      status: 'checking',
      sessionId: session_id,
      currentCheckId: id,
      paperTitle: paper_title,
      paperSource: paper_source,
      statusMessage: 'Reconnected to in-progress check',
      progress: progress_percent,
      references: Array.isArray(results)
        ? results.map((ref, index) => ({ ...ref, index, status: ref.status || 'pending' }))
        : [],
      stats: {
        total_refs,
        processed_refs,
        verified_count,
        errors_count,
        warnings_count,
        suggestions_count,
        unverified_count,
        hallucination_count,
        refs_with_issues,
        refs_with_errors,
        refs_with_warnings_only,
        refs_verified,
        progress_percent,
      },
      error: null,
      completedCheckId: null,
      statusFilter: [],
    })
  },

  setCurrentCheckId: (checkId) => {
    set({ currentCheckId: checkId })
  },

  setStatusFilter: (filter) => {
    const currentFilters = get().statusFilter
    // Single-select: clicking active filter clears it, clicking another sets only that one
    if (currentFilters.includes(filter) && currentFilters.length === 1) {
      // Clicking the only active filter clears it
      set({ statusFilter: [] })
    } else {
      // Set only this filter (single-select)
      set({ statusFilter: [filter] })
    }
  },

  clearStatusFilter: () => {
    set({ statusFilter: [] })
  },

  setStatusMessage: (message) => {
    logger.debug('CheckStore', `Status: ${message}`)
    set({ statusMessage: message })
  },

  setProgress: (percent) => {
    set({ progress: percent })
  },

  setPaperTitle: (title) => {
    logger.info('CheckStore', `Paper title: ${title}`)
    set({ paperTitle: title })
  },

  setPaperSource: (source) => {
    logger.info('CheckStore', `Paper source: ${source}`)
    set({ paperSource: source })
  },

  setReferences: (references) => {
    logger.info('CheckStore', `References extracted: ${references.length}`)
    const existing = get().references || []
    // Build a map of existing refs that already have real (non-pending) data
    // so we never overwrite a more-advanced status with 'pending'.
    const existingByIndex = new Map()
    for (const r of existing) {
      if (r.status && r.status !== 'pending') {
        existingByIndex.set(r.index, r)
      }
    }
    const mappedRefs = references.map((ref, index) => {
      const prev = existingByIndex.get(index)
      if (prev) {
        // Keep the already-processed ref — it has more up-to-date data
        return prev
      }
      return {
        ...ref,
        index,
        status: ref.status || 'pending',
        errors: ref.errors || [],
        warnings: ref.warnings || [],
        authoritative_urls: ref.authoritative_urls || [],
      }
    })
    set({ references: mappedRefs })
  },

  updateReference: (index, data) => {
    logger.debug('CheckStore', `Reference ${index} updated`, data)
    const normalizedStatus = data?.status ? data.status.toLowerCase() : null
    // Extract data fields but preserve the local 0-based index
    const { index: _backendIndex, ...dataWithoutIndex } = data
    set(state => ({
      references: state.references.map((ref, i) => 
        i === index ? { ...ref, ...dataWithoutIndex, index: i, ...(normalizedStatus ? { status: normalizedStatus } : {}) } : ref
      )
    }))
  },

  updateStats: (stats) => {
    logger.debug('CheckStore', 'Stats updated', stats)
    if (stats && (stats.total_refs === 0 || stats.processed_refs === 0) && get().stats?.total_refs > 0) {
      console.warn('[STATS RESET DEBUG] Stats being reset to 0!', { incoming: stats, current: get().stats, stack: new Error().stack })
    }
    set({ stats, progress: stats.progress_percent || 0 })
  },

  completeCheck: (checkId) => {
    logger.info('CheckStore', `Check completed, id: ${checkId}`)
    set({
      status: 'completed',
      statusMessage: 'Check completed',
      completedCheckId: checkId,
    })
  },

  cancelCheck: () => {
    logger.info('CheckStore', 'Check cancelled')
    set({
      status: 'cancelled',
      statusMessage: 'Check cancelled',
    })
  },

  setError: (error) => {
    logger.error('CheckStore', 'Check error', error)
    // Clean up error message - remove URLs and simplify
    let cleanError = error
    if (typeof error === 'string') {
      // Remove URLs from error message
      cleanError = error.replace(/\s*\(https?:\/\/[^\s)]+\)/g, '')
      // Remove "Check failed: " prefix if it's already included
      cleanError = cleanError.replace(/^Check failed:\s*/i, '')
    }
    set({
      status: 'error',
      statusMessage: `Error: ${cleanError}`,
      error: cleanError,
    })
  },

  reset: () => {
    logger.info('CheckStore', 'Reset state')
    // Preserve sessionToCheckMap so we can still process concurrent session messages
    const prevMap = get().sessionToCheckMap
    set({
      status: 'idle',
      sessionId: null,
      currentCheckId: null,
      sessionToCheckMap: prevMap,
      paperTitle: null,
      paperSource: null,
      statusMessage: '',
      progress: 0,
      references: [],
      stats: {
        total_refs: 0,
        processed_refs: 0,
        verified_count: 0,
        errors_count: 0,
        warnings_count: 0,
        suggestions_count: 0,
        unverified_count: 0,
        hallucination_count: 0,
        refs_with_issues: 0,
        refs_with_errors: 0,
        refs_with_warnings_only: 0,
        refs_verified: 0,
        progress_percent: 0,
      },
      error: null,
      completedCheckId: null,
      statusFilter: [],
    })
  },

  // Handle WebSocket messages
  handleWebSocketMessage: (message) => {
    const { type, session_id: messageSessionId, check_id: messageCheckId, ...data } = message
    const store = get()
    const historyStore = useHistoryStore.getState()

    // Determine which check_id this message belongs to
    const checkIdForMessage = messageCheckId || store.sessionToCheckMap[messageSessionId] || store.currentCheckId

    // If this message is for a different session than the current one, route updates to history only
    const isOtherSession = messageSessionId && store.sessionId && messageSessionId !== store.sessionId
    
    if (isOtherSession) {
      if (!checkIdForMessage) {
        logger.warn('CheckStore', `Cannot route message - no check_id for session ${messageSessionId}`)
        return
      }

      // Route concurrent session updates to history - all checks are peers
      switch (type) {
        case 'started':
        case 'extracting':
          historyStore.updateHistoryProgress(checkIdForMessage, { status: 'in_progress' })
          if (data.paper_title) {
            historyStore.updateHistoryItemTitle(checkIdForMessage, data.paper_title)
          }
          break
        case 'title_updated':
          if (data.paper_title) {
            historyStore.updateHistoryItemTitle(checkIdForMessage, data.paper_title)
          }
          break
        case 'references_extracted': {
          // Store the extracted references so they can be displayed
          const extractedRefs = data.references 
            ? data.references.map((ref, index) => ({
                ...ref,
                index,
                status: 'pending',
                errors: [],
                warnings: [],
                authoritative_urls: [],
              }))
            : []
          historyStore.updateHistoryProgress(checkIdForMessage, {
            status: 'in_progress',
            total_refs: data.total_refs || data.count || 0,
            processed_refs: 0, // Reset to 0 when refs first extracted
            results: extractedRefs, // Store the full reference list
            extraction_method: data.extraction_method,
          })
          break
        }
        case 'checking_reference':
          // Mark reference as 'checking' in the history store for concurrent sessions
          if (typeof data.index === 'number') {
            historyStore.updateHistoryReference(checkIdForMessage, data.index - 1, { 
              status: 'checking' 
            })
          }
          break
        case 'reference_result':
          // Update individual reference result for concurrent session
          historyStore.updateHistoryReference(checkIdForMessage, data.index - 1, {
            ...data,
            status: data.status || 'checked',
          })
          break
        case 'summary_update':
          historyStore.updateHistoryProgress(checkIdForMessage, {
            status: 'in_progress',
            total_refs: data.total_refs,
            processed_refs: data.processed_refs,
            errors_count: data.errors_count,
            warnings_count: data.warnings_count,
            suggestions_count: data.suggestions_count,
            unverified_count: data.unverified_count,
            hallucination_count: data.hallucination_count || 0,
            verified_count: data.verified_count,
            refs_with_errors: data.refs_with_errors,
            refs_with_warnings_only: data.refs_with_warnings_only,
            refs_verified: data.refs_verified,
          })
          break
        case 'completed':
          logger.info('CheckStore', `Check ${checkIdForMessage} completed (concurrent session ${messageSessionId?.slice(0,8)})`)
          if (data.paper_title) {
            historyStore.updateHistoryItemTitle(checkIdForMessage, data.paper_title)
          }
          historyStore.updateHistoryProgress(checkIdForMessage, {
            status: 'completed',
            total_refs: data.total_refs,
            processed_refs: data.total_refs, // All refs processed when completed
            errors_count: data.errors_count,
            warnings_count: data.warnings_count,
            suggestions_count: data.suggestions_count,
            unverified_count: data.unverified_count,
            hallucination_count: data.hallucination_count || 0,
            verified_count: data.verified_count,
            refs_with_errors: data.refs_with_errors,
            refs_with_warnings_only: data.refs_with_warnings_only,
            refs_verified: data.refs_verified,
            extraction_method: data.extraction_method,
            // Clear in-memory results so selectCheck fetches authoritative data from API
            results: undefined,
          })
          store.unregisterSession(messageSessionId)
          break
        case 'error':
          logger.error('CheckStore', `Check ${checkIdForMessage} failed (concurrent session ${messageSessionId?.slice(0,8)})`, data)
          historyStore.updateHistoryProgress(checkIdForMessage, {
            status: 'error',
            results: undefined,
          })
          store.unregisterSession(messageSessionId)
          break
        case 'cancelled':
          logger.info('CheckStore', `Check ${checkIdForMessage} cancelled (concurrent session ${messageSessionId?.slice(0,8)})`)
          historyStore.updateHistoryProgress(checkIdForMessage, {
            status: 'cancelled',
            results: undefined,
          })
          store.unregisterSession(messageSessionId)
          break
        default:
          // Other message types for concurrent sessions - ignore
          break
      }
      return
    }
    
    logger.debug('CheckStore', `Processing message type: ${type}`)
    
    switch (type) {
      case 'started':
        store.setStatusMessage(`Check started: ${data.message || 'Initializing...'}`)
        // Pass paper_source from the websocket message (sent as 'source')
        if (data.source) {
          store.setPaperSource(data.source)
        }
        useHistoryStore.getState().updateHistoryProgress(store.currentCheckId, { 
          status: 'in_progress',
          paper_source: data.source || store.paperSource || '',
        })
        break
        
      case 'extracting':
        store.setStatusMessage(data.message || 'Extracting references...')
        // Only update paper_title from backend if it's a meaningful title
        // Never overwrite with "Unknown Paper" - this preserves the original filename for file uploads
        if (data.paper_title && data.paper_title !== 'Unknown Paper') {
          // Also check if current title is not already set to avoid overwriting good titles
          if (!store.paperTitle || store.paperTitle === 'Unknown Paper') {
            store.setPaperTitle(data.paper_title)
            useHistoryStore.getState().updateHistoryItemTitle(store.currentCheckId, data.paper_title)
          }
        }
        useHistoryStore.getState().updateHistoryProgress(store.currentCheckId, { status: 'in_progress' })
        break

      case 'title_updated':
        if (data.paper_title) {
          store.setPaperTitle(data.paper_title)
          useHistoryStore.getState().updateHistoryItemTitle(store.currentCheckId, data.paper_title)
        }
        break
        
      case 'references_extracted':
        store.setStatusMessage(`Found ${data.total_refs || data.count || 0} references, starting verification...`)
        if (data.references) {
          store.setReferences(data.references)
        }
        if (typeof data.total_refs === 'number') {
          useHistoryStore.getState().updateHistoryProgress(store.currentCheckId, {
            status: 'in_progress',
            total_refs: data.total_refs,
            processed_refs: 0, // Reset to 0 when refs first extracted
            extraction_method: data.extraction_method,
          })
        }
        // Store extraction_method in stats for real-time display
        if (data.extraction_method) {
          store.updateStats({ ...get().stats, extraction_method: data.extraction_method })
        }
        break
        
      case 'checking_reference':
        // Don't update status message here - it causes flashing. Let summary_update handle it.
        if (typeof data.index === 'number') {
          // Inline the update to avoid extra set() call
          set(state => ({
            references: state.references.map((ref, i) =>
              i === data.index - 1 ? { ...ref, status: 'checking' } : ref
            )
          }))
        }
        break
        
      case 'reference_result':
        // Inline the update to avoid extra set() call
        {
          const refIndex = data.index - 1
          const normalizedStatus = data?.status ? data.status.toLowerCase() : 'checked'
          const { index: _backendIndex, ...dataWithoutIndex } = data
          set(state => ({
            references: state.references.map((ref, i) =>
              i === refIndex ? { ...ref, ...dataWithoutIndex, index: i, status: normalizedStatus } : ref
            )
          }))
        }
        break
        
      case 'summary_update':
        // Batch stats + statusMessage into a single set() call
        set({
          stats: data,
          progress: data.progress_percent || 0,
          statusMessage: data.processed_refs >= data.total_refs && data.total_refs > 0
            ? 'Finishing hallucination check...'
            : `Processed ${data.processed_refs} of ${data.total_refs} references...`,
        })
        useHistoryStore.getState().updateHistoryProgress(store.currentCheckId, {
          status: 'in_progress',
          total_refs: data.total_refs,
          processed_refs: data.processed_refs,
          errors_count: data.errors_count,
          warnings_count: data.warnings_count,
          suggestions_count: data.suggestions_count,
          unverified_count: data.unverified_count,
            hallucination_count: data.hallucination_count || 0,
          verified_count: data.verified_count,
          refs_with_errors: data.refs_with_errors,
          refs_with_warnings_only: data.refs_with_warnings_only,
          refs_verified: data.refs_verified,
        })
        break
        
      case 'progress':
        store.setProgress(data.percent || data.current / data.total * 100)
        if (data.message) {
          store.setStatusMessage(data.message)
        }
        break

      case 'phase':
        if (data.message) {
          store.setStatusMessage(data.message)
        }
        break
        
      case 'completed':
        store.completeCheck(data.check_id || store.currentCheckId)
        useHistoryStore.getState().updateHistoryProgress(store.currentCheckId, {
          status: 'completed',
          total_refs: data.total_refs,
          processed_refs: data.total_refs, // All refs processed when completed
          errors_count: data.errors_count,
          warnings_count: data.warnings_count,
          suggestions_count: data.suggestions_count,
          unverified_count: data.unverified_count,
            hallucination_count: data.hallucination_count || 0,
          verified_count: data.verified_count,
          refs_with_errors: data.refs_with_errors,
          refs_with_warnings_only: data.refs_with_warnings_only,
          refs_verified: data.refs_verified,
          extraction_method: data.extraction_method,
        })
        // Session is done — remove from activeSessions so the WS isn't reconnected
        if (messageSessionId) store.unregisterSession(messageSessionId)
        break
        
      case 'cancelled':
        store.cancelCheck()
        if (messageSessionId) store.unregisterSession(messageSessionId)
        break
        
      case 'error':
        logger.error('CheckStore', 'Server error', { data, checkIdForMessage, currentCheckId: store.currentCheckId, sessionId: store.sessionId, messageSessionId })
        store.setError(data.message || data.details || 'Unknown error')
        // Update history to show error status
        if (checkIdForMessage) {
          logger.info('CheckStore', `Updating history item ${checkIdForMessage} to error status`)
          useHistoryStore.getState().updateHistoryProgress(checkIdForMessage, {
            status: 'error',
          })
        } else {
          logger.warn('CheckStore', 'No checkIdForMessage available to update history')
        }
        if (messageSessionId) store.unregisterSession(messageSessionId)
        break
        
      default:
        logger.warn('CheckStore', `Unknown message type: ${type}`, data)
    }
  },

  /**
   * Process a batch of WS messages in a single state update.
   * Called from LiveWebSocketManager's rAF flush.  Messages that arrived
   * within the same animation frame are folded into one set() call so
   * React renders only once for the whole batch.
   */
  flushBatchedMessages: (messages) => {
    if (!messages || messages.length === 0) return
    const store = get()

    // Accumulate mutations across all messages
    let latestStats = null
    let latestProgress = null
    let latestStatusMessage = null
    let historyPayload = null     // last summary_update payload for history

    // Track which refs changed to avoid unnecessary .map() per message
    const refPatches = new Map()  // index -> patch object

    for (const message of messages) {
      const { type, session_id: messageSessionId, check_id: _checkId, ...data } = message

      // Route messages from other sessions through the standard handler
      // which applies session-aware routing (updates history store, not current check).
      // Without this guard, a concurrent session's summary_update / reference_result
      // would overwrite the current session's stats and references.
      const isOtherSession = messageSessionId && store.sessionId && messageSessionId !== store.sessionId
      if (isOtherSession) {
        store.handleWebSocketMessage(message)
        continue
      }

      // Only accumulate batch patches for the current session.
      switch (type) {
        case 'checking_reference':
          if (typeof data.index === 'number') {
            const idx = data.index - 1
            refPatches.set(idx, { ...(refPatches.get(idx) || {}), status: 'checking' })
          }
          break

        case 'reference_result': {
          const idx = data.index - 1
          const normalizedStatus = data?.status ? data.status.toLowerCase() : 'checked'
          const { index: _backendIndex, ...dataWithoutIndex } = data
          refPatches.set(idx, {
            ...(refPatches.get(idx) || {}),
            ...dataWithoutIndex,
            index: idx,
            status: normalizedStatus,
          })
          break
        }

        case 'summary_update':
          latestStats = data
          latestProgress = data.progress_percent || 0
          latestStatusMessage = data.processed_refs >= data.total_refs && data.total_refs > 0
            ? 'Finishing hallucination check...'
            : `Processed ${data.processed_refs} of ${data.total_refs} references...`
          historyPayload = {
            status: 'in_progress',
            total_refs: data.total_refs,
            processed_refs: data.processed_refs,
            errors_count: data.errors_count,
            warnings_count: data.warnings_count,
            suggestions_count: data.suggestions_count,
            unverified_count: data.unverified_count,
            hallucination_count: data.hallucination_count || 0,
            verified_count: data.verified_count,
            refs_with_errors: data.refs_with_errors,
            refs_with_warnings_only: data.refs_with_warnings_only,
            refs_verified: data.refs_verified,
          }
          break

        case 'progress':
          latestProgress = data.percent || (data.current / data.total * 100)
          if (data.message) latestStatusMessage = data.message
          break

        default:
          // Non-hot-path message (started, extracting, etc.) – handle individually
          store.handleWebSocketMessage(message)
          break
      }
    }

    // Build a single state patch
    const patch = {}

    // Apply ref patches in one pass
    // Re-read references from store in case a default-case handler
    // (e.g. references_extracted) replaced them mid-batch.
    if (refPatches.size > 0) {
      const currentRefs = get().references
      patch.references = currentRefs.map((ref, i) => {
        const p = refPatches.get(i)
        return p ? { ...ref, ...p } : ref
      })
    }

    if (latestStats !== null) patch.stats = latestStats
    if (latestProgress !== null) patch.progress = latestProgress
    if (latestStatusMessage !== null) patch.statusMessage = latestStatusMessage

    // Single set() for the whole batch
    if (Object.keys(patch).length > 0) {
      set(patch)
    }

    // Update history store once with the latest payload (not per-message)
    if (historyPayload && store.currentCheckId) {
      useHistoryStore.getState().updateHistoryProgress(store.currentCheckId, historyPayload)
    }
  },
}))
