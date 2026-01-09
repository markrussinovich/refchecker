import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// Mock the api module
vi.mock('../utils/api', () => ({
  getHistory: vi.fn(() => Promise.resolve({ data: [] })),
  getCheckDetail: vi.fn(() => Promise.resolve({ data: {} })),
  deleteCheck: vi.fn(() => Promise.resolve({ data: {} })),
  updateCheckLabel: vi.fn(() => Promise.resolve({ data: {} })),
}))

describe('useHistoryStore', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('should initialize with empty history', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(result.current.history).toEqual([])
    expect(result.current.selectedCheckId).toBeNull()
    expect(result.current.selectedCheck).toBeNull()
    expect(result.current.isLoading).toBe(false)
  })

  it('should have fetchHistory method', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(typeof result.current.fetchHistory).toBe('function')
  })

  it('should have selectCheck method', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(typeof result.current.selectCheck).toBe('function')
  })

  it('should have deleteCheck method', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(typeof result.current.deleteCheck).toBe('function')
  })

  it('should have updateLabel method', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(typeof result.current.updateLabel).toBe('function')
  })

  it('should have clearSelection method', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(typeof result.current.clearSelection).toBe('function')
  })
})
