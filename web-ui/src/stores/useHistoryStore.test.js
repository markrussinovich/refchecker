import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'

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

  it('should populate history results from live reference updates', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())

    act(() => {
      useHistoryStore.setState({
        history: [{ id: 42, status: 'in_progress', total_refs: 3, results: undefined }],
      })
    })

    act(() => {
      result.current.updateHistoryReference(42, 1, {
        title: 'Updated ref',
        status: 'hallucination',
        errors: [{ error_type: 'unverified' }],
      })
    })

    const updated = result.current.history.find(item => item.id === 42)
    expect(updated.results).toHaveLength(3)
    expect(updated.results[0].status).toBe('pending')
    expect(updated.results[1]).toMatchObject({
      index: 1,
      title: 'Updated ref',
      status: 'hallucination',
    })
  })

  it('should preserve live results when progress payload fields are undefined', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())

    act(() => {
      useHistoryStore.setState({
        history: [{
          id: 43,
          status: 'in_progress',
          total_refs: 1,
          results: [{ index: 0, title: 'Live ref', status: 'verified' }],
        }],
      })
    })

    act(() => {
      result.current.updateHistoryProgress(43, {
        status: 'completed',
        results: undefined,
      })
    })

    const updated = result.current.history.find(item => item.id === 43)
    expect(updated.status).toBe('completed')
    expect(updated.results).toEqual([{ index: 0, title: 'Live ref', status: 'verified' }])
  })
})
