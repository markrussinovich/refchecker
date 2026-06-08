import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the grounded chat/summarize API so the component renders in isolation
// and we can assert how it reacts to the backend's honest `source` field.
const getArticleSummary = vi.hoisted(() => vi.fn())
const postArticleChat = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({ getArticleSummary, postArticleChat }))

// Config store: `configs` drives whether a Chat & Summarize model is
// considered configured; `getSelectedChatConfig` resolves the chosen config.
const configState = vi.hoisted(() => ({ configs: [], getSelectedChatConfig: vi.fn(() => null) }))
vi.mock('../../stores/useConfigStore', () => ({
  useConfigStore: (selector) => selector(configState),
}))

// Settings store: openSettings('LLM') is the deep-link the empty-state uses.
const openSettings = vi.hoisted(() => vi.fn())
vi.mock('../../stores/useSettingsStore', () => ({
  useSettingsStore: (selector) => selector({ openSettings }),
}))

import ArticleAssistant from './ArticleAssistant'

const CHECK_ID = 42

beforeEach(() => {
  getArticleSummary.mockReset()
  postArticleChat.mockReset()
  openSettings.mockReset()
  configState.configs = []
  configState.getSelectedChatConfig = vi.fn(() => null)
})

function open() {
  render(<ArticleAssistant checkId={CHECK_ID} />)
  fireEvent.click(screen.getByRole('button', { name: /Chat & Summarize/i }))
}

describe('ArticleAssistant — no model configured (honest empty-state)', () => {
  it('shows a non-blocking "Configure a Chat & Summarize model in Settings" empty-state on the Summarize tab', () => {
    open()
    expect(screen.getByText(/Configure a Chat & Summarize model in Settings/i)).toBeTruthy()
    // No silent disable: it does NOT offer the Summarize button while unconfigured.
    expect(screen.queryByRole('button', { name: /Summarize this article/i })).toBeNull()
  })

  it('deep-links to the LLM settings section when the empty-state link is clicked', () => {
    open()
    fireEvent.click(screen.getByRole('button', { name: /Configure a Chat & Summarize model in Settings/i }))
    expect(openSettings).toHaveBeenCalledWith('LLM')
  })

  it('disables the chat input and send button until a model is configured (no confusing backend error)', () => {
    open()
    fireEvent.click(screen.getByRole('button', { name: /^Chat$/i }))
    const input = screen.getByPlaceholderText(/Configure a model in Settings to chat/i)
    expect(input.disabled).toBe(true)
    expect(screen.getByRole('button', { name: /^Send$/i }).disabled).toBe(true)
    // The chat call is never made while unconfigured.
    expect(postArticleChat).not.toHaveBeenCalled()
  })
})

describe('ArticleAssistant — model configured', () => {
  beforeEach(() => {
    configState.configs = [{ id: 1, provider: 'openai', model: 'gpt-4o' }]
    configState.getSelectedChatConfig = vi.fn(() => ({ id: 1 }))
  })

  it('offers the Summarize action and hides the empty-state once a model exists', () => {
    open()
    expect(screen.queryByText(/Configure a Chat & Summarize model in Settings/i)).toBeNull()
    expect(screen.getByRole('button', { name: /Summarize this article/i })).toBeTruthy()
  })

  it('shows the honest "no document text" banner (not a red error) when chat returns source==="none"', async () => {
    postArticleChat.mockResolvedValue({ data: { source: 'none', detail: 'No text.' } })
    open()
    fireEvent.click(screen.getByRole('button', { name: /^Chat$/i }))
    fireEvent.change(screen.getByPlaceholderText(/Ask about the article/i), { target: { value: 'What is this?' } })
    fireEvent.click(screen.getByRole('button', { name: /^Send$/i }))

    await waitFor(() => expect(postArticleChat).toHaveBeenCalled())
    await screen.findByText(/No document text is available for this article/i)
    // It is surfaced as the grounding badge + banner, not assistant content.
    expect(screen.getByText(/grounded:\s*no text/i)).toBeTruthy()
  })

  it('shows the honest "no document text" banner when summarize returns source==="none"', async () => {
    getArticleSummary.mockResolvedValue({ data: { source: 'none', detail: 'No text.' } })
    open()
    fireEvent.click(screen.getByRole('button', { name: /Summarize this article/i }))

    await waitFor(() => expect(getArticleSummary).toHaveBeenCalled())
    await screen.findByText(/No document text is available for this article/i)
  })
})
