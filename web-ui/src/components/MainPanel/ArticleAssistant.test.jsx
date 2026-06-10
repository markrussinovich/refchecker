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
    // The Summarize|Chat tabs are now a macOS-native segmented control with
    // role="tab" / aria-selected (BUTTON_DESIGN §3.4b), not plain buttons.
    fireEvent.click(screen.getByRole('tab', { name: /^Chat$/i }))
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
    // The Summarize|Chat tabs are now a macOS-native segmented control with
    // role="tab" / aria-selected (BUTTON_DESIGN §3.4b), not plain buttons.
    fireEvent.click(screen.getByRole('tab', { name: /^Chat$/i }))
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

// R33 unified styling + R52 click-state stability for the Summarize|Chat
// segmented control, the Send button, and the × close (BUTTON_DESIGN §3.4).
describe('ArticleAssistant — segmented tabs + Send stability (R33/R52)', () => {
  beforeEach(() => {
    configState.configs = [{ id: 1, provider: 'openai', model: 'gpt-4o' }]
    configState.getSelectedChatConfig = vi.fn(() => ({ id: 1 }))
  })

  it('renders Summarize|Chat as a non-reflowing macOS segmented control with a hidden bold sizer', () => {
    open()
    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((t) => t.getAttribute('aria-selected'))).toEqual(['true', 'false'])
    // Each tab carries a hidden 600-weight sizer that reserves the active width
    // so switching weight (active↔inactive) can never shift either tab (§3.4b).
    tabs.forEach((tab) => {
      const sizer = tab.querySelector('span[aria-hidden="true"]')
      expect(sizer).toBeTruthy()
      expect(sizer.style.fontWeight).toBe('600')
      expect(sizer.style.visibility).toBe('hidden')
      // The active indicator is a background fill on the segment, NOT an added
      // border (a border would add box height and reflow).
      expect(tab.className).toContain('rc-segment')
      expect(tab.style.border).toBe('')
    })
  })

  it('switching Summarize↔Chat moves the fill via aria-selected only — no geometry change', () => {
    open()
    const [summarize, chat] = screen.getAllByRole('tab')
    // The visible label weight is the only thing that changes; the reserved
    // (hidden) width is identical on both tabs regardless of which is active.
    fireEvent.click(chat)
    expect(chat.getAttribute('aria-selected')).toBe('true')
    expect(summarize.getAttribute('aria-selected')).toBe('false')
    // Both tabs still expose their hidden bold sizer (width still reserved).
    screen.getAllByRole('tab').forEach((t) => {
      expect(t.querySelector('span[aria-hidden="true"]').style.fontWeight).toBe('600')
    })
  })

  it('Send is a fixed-minWidth primary pill that does not resize across enabled/disabled', () => {
    open()
    fireEvent.click(screen.getByRole('tab', { name: /^Chat$/i }))
    const send = screen.getByRole('button', { name: /Send/i })
    expect(send.style.minWidth).toBe('64px')          // reserved width (§3.4d)
    expect(send.style.height).toBe('var(--control-h)') // matches the 28px input
    expect(send.style.boxSizing).toBe('border-box')
    // Sizer reserves both the Send and Sending… widths so a future label swap
    // can't grow it.
    const reserved = Array.from(send.querySelectorAll('span[aria-hidden="true"]')).map((s) => s.textContent)
    expect(reserved).toEqual(['Send', 'Sending…'])
  })

  it('the input shares the 28px height with Send via box-sizing:border-box (not 30px)', () => {
    open()
    fireEvent.click(screen.getByRole('tab', { name: /^Chat$/i }))
    const input = screen.getByPlaceholderText(/Ask about the article/i)
    expect(input.style.height).toBe('var(--control-h)')
    expect(input.style.boxSizing).toBe('border-box')
    expect(input.style.borderRadius).toBe('var(--control-radius)')
  })

  it('the close × is a fixed-square ghost IconButton (28×28, never resizes neighbors)', () => {
    open()
    const close = screen.getByRole('button', { name: /Close/i })
    expect(close.className).toContain('rc-iconbtn')
    expect(close.className).not.toContain('rc-iconbtn-sm')
    expect(close.className).toContain('rc-control')
  })
})
