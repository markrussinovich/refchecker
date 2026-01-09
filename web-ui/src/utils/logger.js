/**
 * Logging utility with levels for debugging
 */
import { useDebugStore } from '../stores/useDebugStore'

const LOG_LEVELS = {
  DEBUG: 0,
  INFO: 1,
  WARN: 2,
  ERROR: 3,
}

// Set minimum log level (can be changed for production)
const MIN_LOG_LEVEL = LOG_LEVELS.DEBUG

function formatTimestamp() {
  return new Date().toISOString()
}

function shouldLog(level) {
  return LOG_LEVELS[level] >= MIN_LOG_LEVEL
}

function addToDebugStore(level, component, message, data) {
  try {
    useDebugStore.getState().addLog(level, component, message, data)
  } catch (e) {
    // Ignore errors if store not ready
  }
}

export const logger = {
  debug(component, message, data = null) {
    if (!shouldLog('DEBUG')) return
    const timestamp = formatTimestamp()
    addToDebugStore('DEBUG', component, message, data)
    if (data) {
      console.debug(`[${timestamp}] [DEBUG] [${component}] ${message}`, data)
    } else {
      console.debug(`[${timestamp}] [DEBUG] [${component}] ${message}`)
    }
  },

  info(component, message, data = null) {
    if (!shouldLog('INFO')) return
    const timestamp = formatTimestamp()
    addToDebugStore('INFO', component, message, data)
    if (data) {
      console.info(`[${timestamp}] [INFO] [${component}] ${message}`, data)
    } else {
      console.info(`[${timestamp}] [INFO] [${component}] ${message}`)
    }
  },

  warn(component, message, data = null) {
    if (!shouldLog('WARN')) return
    const timestamp = formatTimestamp()
    addToDebugStore('WARN', component, message, data)
    if (data) {
      console.warn(`[${timestamp}] [WARN] [${component}] ${message}`, data)
    } else {
      console.warn(`[${timestamp}] [WARN] [${component}] ${message}`)
    }
  },

  error(component, message, error = null) {
    if (!shouldLog('ERROR')) return
    const timestamp = formatTimestamp()
    addToDebugStore('ERROR', component, message, error)
    if (error) {
      console.error(`[${timestamp}] [ERROR] [${component}] ${message}`, error)
    } else {
      console.error(`[${timestamp}] [ERROR] [${component}] ${message}`)
    }
  },
}
