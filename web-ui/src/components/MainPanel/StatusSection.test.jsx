import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import StatusSection from './StatusSection'

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

vi.mock('../../stores/useCheckStore', () => {
  const state = {
    status: 'idle',
    statusMessage: '',
    progress: 0,
    stats: {},
    paperTitle: null,
    paperSource: null,
    sourceType: null,
    sessionId: null,
    currentCheckId: null,
    cancelCheck: vi.fn(),
  }
  const useCheckStore = (selector) => selector ? selector(state) : state
  useCheckStore.getState = () => state
  return { useCheckStore }
})

vi.mock('../../stores/useHistoryStore', () => {
  const state = {
    selectedCheckId: 42,
    selectedCheck: {
      id: 42,
      status: 'in_progress',
      paper_title: 'Active paper',
      paper_source: 'https://example.com/paper',
      source_type: 'url',
      total_refs: 0,
      processed_refs: 0,
      llm_provider: 'google',
      llm_model: 'gemini-3.1-flash-lite-preview',
      hallucination_provider: null,
      hallucination_model: null,
    },
    history: [],
    updateHistoryProgress: vi.fn(),
  }
  const useHistoryStore = (selector) => selector ? selector(state) : state
  useHistoryStore.getState = () => state
  return { useHistoryStore }
})

describe('StatusSection hallucination model display', () => {
  it('does not infer hallucination model from extraction-only metadata', () => {
    render(<StatusSection />)

    expect(screen.getByText('Extraction Model:')).toBeInTheDocument()
    expect(screen.getByText('google / gemini-3.1-flash-lite-preview')).toBeInTheDocument()
    expect(screen.queryByText('Hallucination Model:')).toBeNull()
  })
})
