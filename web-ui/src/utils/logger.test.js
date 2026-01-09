import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock localStorage
const localStorageMock = (() => {
  let store = {}
  return {
    getItem: vi.fn((key) => store[key] || null),
    setItem: vi.fn((key, value) => { store[key] = value.toString() }),
    removeItem: vi.fn((key) => { delete store[key] }),
    clear: vi.fn(() => { store = {} }),
  }
})()

Object.defineProperty(window, 'localStorage', { value: localStorageMock })

describe('logger', () => {
  beforeEach(() => {
    localStorageMock.clear()
    vi.resetAllMocks()
  })

  it('should export logger object with methods', async () => {
    const { logger } = await import('./logger')
    
    expect(logger).toBeDefined()
    expect(typeof logger.debug).toBe('function')
    expect(typeof logger.info).toBe('function')
    expect(typeof logger.warn).toBe('function')
    expect(typeof logger.error).toBe('function')
  })

  it('should not throw when logging', async () => {
    const { logger } = await import('./logger')
    
    expect(() => logger.debug('Test', 'debug message')).not.toThrow()
    expect(() => logger.info('Test', 'info message')).not.toThrow()
    expect(() => logger.warn('Test', 'warn message')).not.toThrow()
    expect(() => logger.error('Test', 'error message')).not.toThrow()
  })

  it('should handle objects in log messages', async () => {
    const { logger } = await import('./logger')
    
    expect(() => logger.info('Test', 'message', { key: 'value' })).not.toThrow()
    expect(() => logger.error('Test', 'error', new Error('test error'))).not.toThrow()
  })
})
