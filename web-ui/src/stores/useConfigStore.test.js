import { act, renderHook } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'

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
    vi.clearAllMocks()
    localStorage.clear()
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

  it('restores string environment config selections', async () => {
    localStorage.getItem.mockImplementation((key) => (
      key === 'refchecker_selected_extraction_llm' ? 'env:anthropic' : null
    ))
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())

    expect(result.current.selectedExtractionConfigId).toBe('env:anthropic')
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

  // R34 — Chat-with-PDF and Summarize have independent model selections.
  it('exposes a separate Summarize selection trio mirroring Chat', async () => {
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())

    // Initial state slot + chat sibling both present.
    expect(result.current).toHaveProperty('selectedSummaryConfigId')
    expect(result.current.selectedSummaryConfigId).toBeNull()
    expect(typeof result.current.selectSummaryConfig).toBe('function')
    expect(typeof result.current.getSelectedSummaryConfig).toBe('function')
    expect(typeof result.current.selectChatConfig).toBe('function')
    expect(typeof result.current.getSelectedChatConfig).toBe('function')
  })

  it('selectSummaryConfig persists independently of the chat selection (R34)', async () => {
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())

    act(() => {
      useConfigStore.setState({
        configs: [
          { id: 1, provider: 'openai', model: 'gpt-4o' },
          { id: 2, provider: 'anthropic', model: 'claude-sonnet-4-6' },
        ],
        selectedChatConfigId: 1,
        selectedSummaryConfigId: 1,
      })
    })

    act(() => { result.current.selectSummaryConfig(2) })

    // Summarize moved to 2; Chat is untouched at 1 — the two routes diverge.
    expect(result.current.selectedSummaryConfigId).toBe(2)
    expect(result.current.selectedChatConfigId).toBe(1)
    expect(result.current.getSelectedSummaryConfig().id).toBe(2)
    expect(result.current.getSelectedChatConfig().id).toBe(1)
    expect(localStorage.setItem).toHaveBeenCalledWith('refchecker_selected_summary_llm', '2')
  })

  it('getSelectedSummaryConfig falls back to the chat selection when unset (R34)', async () => {
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())

    act(() => {
      useConfigStore.setState({
        configs: [
          { id: 1, provider: 'openai', model: 'gpt-4o' },
          { id: 2, provider: 'anthropic', model: 'claude-sonnet-4-6' },
        ],
        selectedChatConfigId: 2,
        selectedExtractionConfigId: 1,
        selectedSummaryConfigId: null,
      })
    })

    // No summary-specific pick → falls back to chat (2), not extraction (1).
    expect(result.current.getSelectedSummaryConfig().id).toBe(2)
  })

  it('deleteConfig resets the summary selection like the chat selection', async () => {
    const api = await import('../utils/api')
    api.deleteLLMConfig.mockResolvedValueOnce({ data: {} })
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())

    act(() => {
      useConfigStore.setState({
        configs: [
          { id: 1, provider: 'openai', model: 'gpt-4o' },
          { id: 2, provider: 'anthropic', model: 'claude-sonnet-4-6' },
        ],
        selectedChatConfigId: 2,
        selectedSummaryConfigId: 2,
      })
    })

    await act(async () => { await result.current.deleteConfig(2) })

    expect(result.current.selectedSummaryConfigId).toBe(1)
    expect(result.current.selectedChatConfigId).toBe(1)
  })

  it('does not change extraction selection when adding a hallucination config', async () => {
    const api = await import('../utils/api')
    api.createLLMConfig.mockResolvedValueOnce({
      data: { id: 9, provider: 'google', model: 'gemini-3.1-flash-lite-preview' },
    })
    const { useConfigStore } = await import('./useConfigStore')
    const { result } = renderHook(() => useConfigStore())

    act(() => {
      useConfigStore.setState({
        configs: [
          { id: 7, provider: 'anthropic', model: 'claude-sonnet-4-6' },
          { id: 8, provider: 'openai', model: 'gpt-4.1' },
        ],
        selectedConfigId: 7,
        selectedExtractionConfigId: 7,
        selectedHallucinationConfigId: 8,
      })
    })

    await act(async () => {
      await result.current.addConfig(
        { provider: 'google', model: 'gemini-3.1-flash-lite-preview' },
        { selectFor: 'hallucination' },
      )
    })

    expect(result.current.selectedConfigId).toBe(7)
    expect(result.current.selectedExtractionConfigId).toBe(7)
    expect(result.current.selectedHallucinationConfigId).toBe(9)
    expect(api.setDefaultLLMConfig).not.toHaveBeenCalledWith(9)
  })
})
