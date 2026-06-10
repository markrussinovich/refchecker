import { fireEvent, render, screen, waitFor, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the per-check usage endpoint so the badge renders in isolation.
const getLLMUsage = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({ getLLMUsage }))

import LLMUsageBadge from './LLMUsageBadge'

const CHECK_ID = 42

// A realistic snapshot shape (matches the backend /history/{id}/llm-usage and
// refchecker.llm.usage_tracker.snapshot output): per-flow + per-model breakdown.
const SNAPSHOT = {
  input_tokens: 3400,
  output_tokens: 600,
  cost_usd: 0.0151,
  calls: 4,
  by_flow: {
    hallucination: { input_tokens: 2000, output_tokens: 150, cost_usd: 0.009, calls: 1 },
    chat: { input_tokens: 800, output_tokens: 300, cost_usd: 0.004, calls: 2 },
    summarize: { input_tokens: 600, output_tokens: 150, cost_usd: 0.0021, calls: 1 },
  },
  by_model: {
    'gpt-4o-mini': { input_tokens: 3400, output_tokens: 600, cost_usd: 0.0151 },
  },
}

beforeEach(() => {
  getLLMUsage.mockReset()
  getLLMUsage.mockResolvedValue({ data: SNAPSHOT })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('LLMUsageBadge — R47 live token + $ telemetry', () => {
  it('renders live totals tokens + real cost from the snapshot', async () => {
    render(<LLMUsageBadge checkId={CHECK_ID} isComplete={false} />)
    // 4000 tokens -> "4.0K tok"; cost 0.0151 (>= 0.01) -> "$0.015" (toFixed(3))
    await screen.findByText('4.0K tok')
    expect(screen.getByText('$0.015')).toBeInTheDocument()
    expect(getLLMUsage).toHaveBeenCalledWith(CHECK_ID)
  })

  it('hover breakdown labels chat + summarize + hallucination flows', async () => {
    render(<LLMUsageBadge checkId={CHECK_ID} isComplete />)
    await screen.findByText('4.0K tok')
    fireEvent.mouseEnter(screen.getByText('LLM').parentElement)
    // The previously-$0 hallucination flow now shows under its label.
    expect(await screen.findByText('Hallucination check')).toBeInTheDocument()
    // The newly-tracked chat + summarize flows are labelled too (R47).
    expect(screen.getByText('Chat with article')).toBeInTheDocument()
    expect(screen.getByText('Article summary')).toBeInTheDocument()
  })

  it('refetches immediately on a refchecker:usage-changed event (chat/summarize tick-up)', async () => {
    render(<LLMUsageBadge checkId={CHECK_ID} isComplete />)
    await waitFor(() => expect(getLLMUsage).toHaveBeenCalledTimes(1))
    await act(async () => {
      window.dispatchEvent(new Event('refchecker:usage-changed'))
    })
    await waitFor(() => expect(getLLMUsage).toHaveBeenCalledTimes(2))
  })

  it('shows an honest $0.000 / 0-token state when nothing was spent', async () => {
    getLLMUsage.mockResolvedValue({
      data: { input_tokens: 0, output_tokens: 0, cost_usd: 0, calls: 0, by_flow: {}, by_model: {} },
    })
    render(<LLMUsageBadge checkId={CHECK_ID} isComplete />)
    await screen.findByText('$0.000')
    expect(screen.getByText('0 tok')).toBeInTheDocument()
  })

  it('renders nothing without a real check id', () => {
    const { container } = render(<LLMUsageBadge checkId={-1} isComplete />)
    expect(container).toBeEmptyDOMElement()
    expect(getLLMUsage).not.toHaveBeenCalled()
  })
})
