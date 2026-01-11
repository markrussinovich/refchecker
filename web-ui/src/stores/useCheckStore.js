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
  statusMessage: '',
  progress: 0,
  references: [],
  stats: {
    total_refs: 0,
    processed_refs: 0,
    verified_count: 0,
    errors_count: 0,
    warnings_count: 0,
    unverified_count: 0,
    progress_percent: 0,
  },
  error: null,
  completedCheckId: null,
  statusFilter: [], // empty = show all, or array of ['verified', 'error', 'warning', 'unverified']

  // Actions
  startCheck: (sessionId, checkId = null, paperSource = null) => {
    logger.info('CheckStore', `Starting check with session ${sessionId}, checkId ${checkId}`)
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
      paperTitle: null,
      paperSource,
      statusMessage: 'Starting check...',
      progress: 0,
      references: [],
      stats: {
        total_refs: 0,
        processed_refs: 0,
        verified_count: 0,
        errors_count: 0,
        warnings_count: 0,
        unverified_count: 0,
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
      unverified_count = 0,
    } = payload || {}

    const processed_refs = Array.isArray(results) ? results.length : 0
    const verified_count = Math.max(total_refs - errors_count - warnings_count - unverified_count, 0)
    const progress_percent = total_refs > 0 ? Math.min((processed_refs / total_refs) * 100, 100) : 0

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
        unverified_count,
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
    // Toggle: add if not present, remove if present
    if (currentFilters.includes(filter)) {
      set({ statusFilter: currentFilters.filter(f => f !== filter) })
    } else {
      set({ statusFilter: [...currentFilters, filter] })
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

  setReferences: (references) => {
    logger.info('CheckStore', `References extracted: ${references.length}`)
    set({ 
      references: references.map((ref, index) => ({
        ...ref,
        index,
        status: 'pending',
        errors: [],
        warnings: [],
        authoritative_urls: [],
      }))
    })
  },

  updateReference: (index, data) => {
    logger.debug('CheckStore', `Reference ${index} updated`, data)
    const normalizedStatus = data?.status ? data.status.toLowerCase() : null
    set(state => ({
      references: state.references.map((ref, i) => 
        i === index ? { ...ref, ...data, ...(normalizedStatus ? { status: normalizedStatus } : {}) } : ref
      )
    }))
  },

  updateStats: (stats) => {
    logger.debug('CheckStore', 'Stats updated', stats)
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
    set({
      status: 'error',
      statusMessage: `Error: ${error}`,
      error,
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
        unverified_count: 0,
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
    
    // DEBUG: Log all incoming messages with routing info
    console.log(`[DEBUG-WS] type=${type} msgSession=${messageSessionId?.slice(0,8)} currentSession=${store.sessionId?.slice(0,8)} isOther=${isOtherSession} checkIdForMsg=${checkIdForMessage} currentCheckId=${store.currentCheckId}`)
    
    if (isOtherSession) {
      console.log(`[DEBUG-WS] OTHER SESSION: Routing ${type} to history for check ${checkIdForMessage}`)
      if (!checkIdForMessage) {
        logger.warn('CheckStore', `Cannot route message - no check_id for session ${messageSessionId}`)
        return
      }

      // Route concurrent session updates to history - all checks are peers
      switch (type) {
        case 'started':
        case 'extracting':
          console.log(`[DEBUG-WS] OTHER ${type}: checkId=${checkIdForMessage}`)
          historyStore.updateHistoryProgress(checkIdForMessage, { status: 'in_progress' })
          if (data.paper_title) {
            historyStore.updateHistoryItemTitle(checkIdForMessage, data.paper_title)
          }
          break
        case 'references_extracted':
          console.log(`[DEBUG-WS] OTHER references_extracted: checkId=${checkIdForMessage} total_refs=${data.total_refs} count=${data.count} refs_count=${data.references?.length}`)
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
          console.log(`[DEBUG-WS] OTHER references_extracted: storing ${extractedRefs.length} refs for check ${checkIdForMessage}`)
          historyStore.updateHistoryProgress(checkIdForMessage, {
            status: 'in_progress',
            total_refs: data.total_refs || data.count || 0,
            processed_refs: 0, // Reset to 0 when refs first extracted
            results: extractedRefs, // Store the full reference list
          })
          // Verify it was stored
          const afterUpdate = historyStore.history.find(h => h.id === checkIdForMessage)
          console.log(`[DEBUG-WS] OTHER references_extracted AFTER: check ${checkIdForMessage} now has results=${afterUpdate?.results?.length}`)
          break
        case 'checking_reference':
          // Mark reference as 'checking' in the history store for concurrent sessions
          console.log(`[DEBUG-WS] OTHER checking_reference: checkId=${checkIdForMessage} index=${data.index} title=${data.title}`)
          if (typeof data.index === 'number') {
            historyStore.updateHistoryReference(checkIdForMessage, data.index - 1, { 
              status: 'checking' 
            })
          }
          break
        case 'reference_result':
          // Update individual reference result for concurrent session
          console.log(`[DEBUG-WS] OTHER reference_result: checkId=${checkIdForMessage} index=${data.index} status=${data.status}`)
          historyStore.updateHistoryReference(checkIdForMessage, data.index - 1, {
            ...data,
            status: data.status || 'checked',
          })
          break
        case 'summary_update':
          console.log(`[DEBUG-WS] OTHER summary_update: checkId=${checkIdForMessage} processed=${data.processed_refs}/${data.total_refs}`)
          historyStore.updateHistoryProgress(checkIdForMessage, {
            status: 'in_progress',
            total_refs: data.total_refs,
            processed_refs: data.processed_refs,
            errors_count: data.errors_count,
            warnings_count: data.warnings_count,
            unverified_count: data.unverified_count,
          })
          break
        case 'completed':
          console.log(`[DEBUG-WS] OTHER completed: checkId=${checkIdForMessage} total_refs=${data.total_refs} errors=${data.errors_count} warnings=${data.warnings_count}`)
          logger.info('CheckStore', `Check ${checkIdForMessage} completed (concurrent session ${messageSessionId?.slice(0,8)})`)
          historyStore.updateHistoryProgress(checkIdForMessage, {
            status: 'completed',
            total_refs: data.total_refs,
            processed_refs: data.total_refs, // All refs processed when completed
            errors_count: data.errors_count,
            warnings_count: data.warnings_count,
            unverified_count: data.unverified_count,
          })
          break
        default:
          // Log but don't process other message types for concurrent sessions
          console.log(`[DEBUG-WS] OTHER ${type}: checkId=${checkIdForMessage} (not updating progress)`)
      }
      return
    }
    
    logger.debug('CheckStore', `Processing message type: ${type}`)
    
    switch (type) {
      case 'started':
        store.setStatusMessage(`Check started: ${data.message || 'Initializing...'}`)
        useHistoryStore.getState().updateHistoryProgress(store.currentCheckId, { status: 'in_progress' })
        break
        
      case 'extracting':
        store.setStatusMessage(data.message || 'Extracting references...')
        if (data.paper_title) {
          store.setPaperTitle(data.paper_title)
          useHistoryStore.getState().updateHistoryItemTitle(store.currentCheckId, data.paper_title)
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
          })
        }
        break
        
      case 'checking_reference':
        store.setStatusMessage(`Verifying references in parallel (${data.total || '?'} total)...`)
        if (typeof data.index === 'number') {
          store.updateReference(data.index - 1, { status: 'checking' })
        }
        break
        
      case 'reference_result':
        store.updateReference(data.index - 1, {
          ...data,
          status: data.status || 'checked',
        })
        break
        
      case 'summary_update':
        store.updateStats(data)
        store.setStatusMessage(`Processed ${data.processed_refs} of ${data.total_refs} references`)
        useHistoryStore.getState().updateHistoryProgress(store.currentCheckId, {
          status: 'in_progress',
          total_refs: data.total_refs,
          processed_refs: data.processed_refs,
          errors_count: data.errors_count,
          warnings_count: data.warnings_count,
          unverified_count: data.unverified_count,
        })
        break
        
      case 'progress':
        store.setProgress(data.percent || data.current / data.total * 100)
        if (data.message) {
          store.setStatusMessage(data.message)
        }
        break
        
      case 'completed':
        store.completeCheck(data.check_id)
        useHistoryStore.getState().updateHistoryProgress(store.currentCheckId, {
          status: 'completed',
          total_refs: data.total_refs,
          processed_refs: data.total_refs, // All refs processed when completed
          errors_count: data.errors_count,
          warnings_count: data.warnings_count,
          unverified_count: data.unverified_count,
        })
        break
        
      case 'cancelled':
        store.cancelCheck()
        break
        
      case 'error':
        logger.error('CheckStore', 'Server error', data)
        store.setError(data.message || data.details || 'Unknown error')
        break
        
      default:
        logger.warn('CheckStore', `Unknown message type: ${type}`, data)
    }
  },
}))
