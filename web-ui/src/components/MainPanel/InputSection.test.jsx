import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import InputSection from './InputSection'

const mocks = vi.hoisted(() => ({
  startBatchCheck: vi.fn(),
  startCheck: vi.fn(),
  cancelCheckStore: vi.fn(),
  reset: vi.fn(),
  setError: vi.fn(),
  fetchHistory: vi.fn(),
  clearSelection: vi.fn(),
  selectCheck: vi.fn(),
  addToHistory: vi.fn(),
  registerSession: vi.fn(),
  getSelectedConfig: vi.fn(),
  getSelectedExtractionConfig: vi.fn(),
  getSelectedHallucinationConfig: vi.fn(),
  getKey: vi.fn(),
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}))

vi.mock('../../utils/api', () => ({
  startBatchCheck: mocks.startBatchCheck,
  startBatchFileCheck: vi.fn(),
  startCheck: vi.fn(),
  cancelCheck: vi.fn(),
}))

vi.mock('../../utils/logger', () => ({
  logger: mocks.logger,
}))

vi.mock('../../stores/useCheckStore', () => {
  const useCheckStore = () => ({
    status: 'idle',
    startCheck: mocks.startCheck,
    reset: mocks.reset,
    cancelCheck: mocks.cancelCheckStore,
    setError: mocks.setError,
  })

  useCheckStore.getState = () => ({
    registerSession: mocks.registerSession,
    sessionId: null,
  })

  return { useCheckStore }
})

vi.mock('../../stores/useConfigStore', () => ({
  useConfigStore: () => ({
    getSelectedConfig: mocks.getSelectedConfig,
    getSelectedExtractionConfig: mocks.getSelectedExtractionConfig,
    getSelectedHallucinationConfig: mocks.getSelectedHallucinationConfig,
  }),
}))

vi.mock('../../stores/useHistoryStore', () => {
  const useHistoryStore = () => ({
    fetchHistory: mocks.fetchHistory,
    clearSelection: mocks.clearSelection,
    selectCheck: mocks.selectCheck,
  })

  useHistoryStore.getState = () => ({
    addToHistory: mocks.addToHistory,
    selectedCheckId: -1,
  })

  return { useHistoryStore }
})

vi.mock('../../stores/useKeyStore', () => {
  const useKeyStore = () => ({})

  useKeyStore.getState = () => ({
    getKey: mocks.getKey,
  })

  return { useKeyStore }
})

vi.mock('../../hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    file: null,
    isDragging: false,
    error: null,
    handleDragEnter: vi.fn(),
    handleDragLeave: vi.fn(),
    handleDragOver: vi.fn(),
    handleDrop: vi.fn(),
    handleInputChange: vi.fn(),
    clearFile: vi.fn(),
  }),
}))

describe('InputSection bulk mode', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    mocks.getSelectedConfig.mockReturnValue({
      id: 7,
      provider: 'anthropic',
      model: 'claude-4',
      name: 'Hosted Claude',
    })
    mocks.getSelectedExtractionConfig.mockReturnValue({
      id: 7,
      provider: 'anthropic',
      model: 'claude-4',
      name: 'Hosted Claude',
    })
    mocks.getSelectedHallucinationConfig.mockReturnValue({
      id: 8,
      provider: 'google',
      model: 'gemini-2.5-flash',
      name: 'Hosted Gemini',
    })
    mocks.getKey.mockImplementation((provider) => {
      if (provider === 'anthropic') return 'llm-key'
      if (provider === 'google') return 'hallucination-key'
      if (provider === 'semantic_scholar') return 'ss-key'
      if (provider === 'paperclip') return 'paperclip-key'
      return null
    })
    mocks.startBatchCheck.mockResolvedValue({
      data: {
        batch_id: 'batch-1',
        batch_label: '2401.12345',
        checks: [
          {
            session_id: 'session-1',
            check_id: 42,
            source: '2401.12345',
          },
        ],
      },
    })
  })

  it('forwards browser-stored keys when starting a bulk URL batch', async () => {
    render(<InputSection />)

    fireEvent.click(screen.getByRole('button', { name: 'Bulk' }))
    fireEvent.change(screen.getByPlaceholderText(/Enter one URL or ArXiv ID per line/i), {
      target: { value: '2401.12345' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Check 1 Paper' }))

    await waitFor(() => {
      expect(mocks.startBatchCheck).toHaveBeenCalledWith({
        urls: ['2401.12345'],
        batch_label: '2401.12345',
        llm_config_id: 7,
        llm_provider: 'anthropic',
        llm_model: 'claude-4',
        hallucination_config_id: 8,
        hallucination_provider: 'google',
        hallucination_model: 'gemini-2.5-flash',
        use_llm: true,
        api_key: 'llm-key',
        hallucination_api_key: 'hallucination-key',
        semantic_scholar_api_key: 'ss-key',
        paperclip_api_key: 'paperclip-key',
      })
    })

    expect(mocks.clearSelection).toHaveBeenCalledTimes(1)
    expect(mocks.registerSession).toHaveBeenCalledWith('session-1', 42)
    expect(mocks.addToHistory).toHaveBeenCalledWith(expect.objectContaining({
      id: 42,
      paper_source: '2401.12345',
      llm_provider: 'anthropic',
      llm_model: 'claude-4',
      hallucination_provider: 'google',
      hallucination_model: 'gemini-2.5-flash',
      batch_id: 'batch-1',
      batch_label: '2401.12345',
    }))
    expect(mocks.selectCheck).toHaveBeenCalledWith(42)
    expect(mocks.startCheck).toHaveBeenCalledWith('session-1', 42, '2401.12345', 'url', null)
  })
})

describe('InputSection mode tabs — hover state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.getSelectedConfig.mockReturnValue(null)
    mocks.getSelectedExtractionConfig.mockReturnValue(null)
    mocks.getSelectedHallucinationConfig.mockReturnValue(null)
    mocks.getKey.mockReturnValue(null)
  })

  // Regression: hover used to be applied by mutating the DOM style directly and
  // reset only when the tab was NOT selected. Clicking a hovered tab therefore
  // left the grey hover fill stranded on it forever.
  it('does not leave a stale hover background on a tab after it is selected then deselected', () => {
    render(<InputSection />)

    const fileTab = screen.getByRole('button', { name: 'Upload File' })
    const urlTab = screen.getByRole('button', { name: 'URL / ArXiv ID' })

    fireEvent.mouseEnter(fileTab)
    expect(fileTab.style.backgroundColor).toBe('var(--color-bg-hover)')

    // Select it while hovered, then move the pointer away.
    fireEvent.click(fileTab)
    fireEvent.mouseLeave(fileTab)
    expect(fileTab.style.backgroundColor).toBe('var(--color-bg-primary)')

    // Switching back must not leave the previously-hovered tab greyed out.
    fireEvent.click(urlTab)
    expect(fileTab.style.backgroundColor).toBe('var(--color-bg-primary)')
    expect(fileTab.style.border).toBe('1px solid var(--color-border)')
  })

  it('keeps the active tab unhighlighted by hover and restores hover on re-enter', () => {
    render(<InputSection />)

    const urlTab = screen.getByRole('button', { name: 'URL / ArXiv ID' })
    const textTab = screen.getByRole('button', { name: 'Paste Text' })

    // Active tab never takes the hover fill.
    fireEvent.mouseEnter(urlTab)
    expect(urlTab.style.backgroundColor).toBe('var(--color-bg-primary)')
    fireEvent.mouseLeave(urlTab)

    fireEvent.mouseEnter(textTab)
    expect(textTab.style.backgroundColor).toBe('var(--color-bg-hover)')
    fireEvent.mouseLeave(textTab)
    expect(textTab.style.backgroundColor).toBe('var(--color-bg-primary)')
  })
})
