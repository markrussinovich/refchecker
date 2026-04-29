import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook } from '@testing-library/react'

// Mock the api module
vi.mock('../utils/api', () => ({
  getLLMConfigs: vi.fn(() => Promise.resolve({ data: [] })),
  createLLMConfig: vi.fn(() => Promise.resolve({ data: { id: 1 } })),
  updateLLMConfig: vi.fn(() => Promise.resolve({ data: {} })),
  deleteLLMConfig: vi.fn(() => Promise.resolve({ data: {} })),
  setDefaultLLMConfig: vi.fn(() => Promise.resolve({ data: {} })),
}))

describe('useConfigStore', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('should initialize with empty configs', async () => {
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())
    
    expect(result.current.configs).toEqual([])
    expect(result.current.selectedConfigId).toBeNull()
    expect(result.current.selectedExtractionConfigId).toBeNull()
    expect(result.current.selectedHallucinationConfigId).toBeNull()
    expect(result.current.isLoading).toBe(false)
  })

  it('should have fetchConfigs method', async () => {
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())
    
    expect(typeof result.current.fetchConfigs).toBe('function')
  })

  it('should have addConfig method', async () => {
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())
    
    expect(typeof result.current.addConfig).toBe('function')
  })

  it('should have deleteConfig method', async () => {
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())
    
    expect(typeof result.current.deleteConfig).toBe('function')
  })

  it('should have selectConfig method', async () => {
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())
    
    expect(typeof result.current.selectConfig).toBe('function')
  })

  it('should have getSelectedConfig method', async () => {
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())
    
    expect(typeof result.current.getSelectedConfig).toBe('function')
  })

  it('should have mode-specific selection methods', async () => {
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())

    expect(typeof result.current.selectExtractionConfig).toBe('function')
    expect(typeof result.current.selectHallucinationConfig).toBe('function')
    expect(typeof result.current.getSelectedExtractionConfig).toBe('function')
    expect(typeof result.current.getSelectedHallucinationConfig).toBe('function')
  })
})
