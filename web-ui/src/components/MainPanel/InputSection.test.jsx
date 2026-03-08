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
    mocks.getKey.mockImplementation((provider) => {
      if (provider === 'anthropic') return 'llm-key'
      if (provider === 'semantic_scholar') return 'ss-key'
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
        use_llm: true,
        api_key: 'llm-key',
        semantic_scholar_api_key: 'ss-key',
      })
    })

    expect(mocks.clearSelection).toHaveBeenCalledTimes(1)
    expect(mocks.registerSession).toHaveBeenCalledWith('session-1', 42)
    expect(mocks.addToHistory).toHaveBeenCalledWith(expect.objectContaining({
      id: 42,
      paper_source: '2401.12345',
      batch_id: 'batch-1',
      batch_label: '2401.12345',
    }))
    expect(mocks.selectCheck).toHaveBeenCalledWith(42)
    expect(mocks.startCheck).toHaveBeenCalledWith('session-1', 42, '2401.12345', 'url', null)
  })
})
