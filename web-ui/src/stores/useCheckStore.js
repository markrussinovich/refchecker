import { create } from 'zustand'
import { logger } from '../utils/logger'

/**
 * Store for current check state management
 */
export const useCheckStore = create((set, get) => ({
  // State
  status: 'idle', // idle, checking, completed, cancelled, error
  sessionId: null,
  currentCheckId: null, // ID of the check in history (created immediately)
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
    set({
      status: 'checking',
      sessionId,
      currentCheckId: checkId,
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
    set({
      status: 'idle',
      sessionId: null,
      currentCheckId: null,
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
    const { type, session_id: messageSessionId, ...data } = message
    const store = get()

    // Ignore messages from stale sessions
    if (messageSessionId && store.sessionId && messageSessionId !== store.sessionId) {
      logger.debug('CheckStore', `Ignoring message for stale session ${messageSessionId}`)
      return
    }
    
    logger.debug('CheckStore', `Processing message type: ${type}`)
    
    switch (type) {
      case 'started':
        store.setStatusMessage(`Check started: ${data.message || 'Initializing...'}`)
        break
        
      case 'extracting':
        store.setStatusMessage(data.message || 'Extracting references...')
        if (data.paper_title) {
          store.setPaperTitle(data.paper_title)
        }
        break

      case 'title_updated':
        if (data.paper_title) {
          store.setPaperTitle(data.paper_title)
        }
        break
        
      case 'references_extracted':
        store.setStatusMessage(`Found ${data.total_refs || data.count || 0} references, starting verification...`)
        if (data.references) {
          store.setReferences(data.references)
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
        break
        
      case 'progress':
        store.setProgress(data.percent || data.current / data.total * 100)
        if (data.message) {
          store.setStatusMessage(data.message)
        }
        break
        
      case 'completed':
        store.completeCheck(data.check_id)
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
