import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  configs: [],
  settings: {},
  multiuser: false,
  fetchSettings: vi.fn(),
  openExternal: vi.fn(),
  hasKey: vi.fn(() => false),
  getSemanticScholarKeyStatus: vi.fn(),
  getPaperclipKeyStatus: vi.fn(),
}))

vi.mock('../../stores/useConfigStore', () => ({
  useConfigStore: (selector) => selector({ configs: mocks.configs }),
}))

vi.mock('../../stores/useSettingsStore', () => ({
  useSettingsStore: (selector) => selector({
    settings: mocks.settings,
    fetchSettings: mocks.fetchSettings,
  }),
}))

vi.mock('../../stores/useAuthStore', () => ({
  useAuthStore: (selector) => selector({ multiuser: mocks.multiuser }),
}))

vi.mock('../../stores/useKeyStore', () => ({
  useKeyStore: (selector) => selector({ hasKey: mocks.hasKey }),
}))

vi.mock('../../utils/api', () => ({
  getSemanticScholarKeyStatus: mocks.getSemanticScholarKeyStatus,
  getPaperclipKeyStatus: mocks.getPaperclipKeyStatus,
}))

vi.mock('../../utils/tauriBridge', () => ({
  openExternal: mocks.openExternal,
  isTauri: () => false,
}))

import OnboardingBanner from './OnboardingBanner'

describe('OnboardingBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.getItem.mockReturnValue(null)
    mocks.configs = []
    mocks.settings = {}
    mocks.multiuser = false
    mocks.hasKey.mockReturnValue(false)
    mocks.getSemanticScholarKeyStatus.mockResolvedValue({ data: { has_key: false } })
    mocks.getPaperclipKeyStatus.mockResolvedValue({ data: { has_key: false } })
  })

  it('uses a neutral RefChecker heading in single-user mode', () => {
    render(<OnboardingBanner onOpenSettings={vi.fn()} />)

    expect(screen.getByText('Welcome to RefChecker')).toBeInTheDocument()
    expect(screen.queryByText(/RefChecker Desktop/)).not.toBeInTheDocument()
    expect(screen.getByText(/Download the offline database pack/)).toBeInTheDocument()
  })

  it('omits desktop-only database guidance in multiuser mode', () => {
    mocks.multiuser = true

    render(<OnboardingBanner onOpenSettings={vi.fn()} />)

    expect(screen.getByText('Welcome to RefChecker')).toBeInTheDocument()
    expect(screen.queryByText(/Download the offline database pack/)).not.toBeInTheDocument()
    expect(screen.queryByText(/local vLLM server/)).not.toBeInTheDocument()
    expect(screen.getByText(/OpenAI, Anthropic, Google, or Azure are supported/)).toBeInTheDocument()
  })

  it('still renders when LLM is configured — the banner now stays until the user dismisses it', () => {
    // Previous behavior auto-hid the banner once LLM (and DB) were
    // set, but that also hid the optional Paperclip / Semantic
    // Scholar bonus steps the user never had a chance to discover.
    // The banner now shows until the explicit Dismiss button is
    // clicked.
    mocks.multiuser = true
    mocks.configs = [{ id: 1, provider: 'openai', has_key: true }]

    render(<OnboardingBanner onOpenSettings={vi.fn()} />)

    expect(screen.getByText('Welcome to RefChecker')).toBeInTheDocument()
  })

  it('hides only when explicitly dismissed via localStorage', () => {
    window.localStorage.getItem.mockReturnValue('1')

    const { container } = render(<OnboardingBanner onOpenSettings={vi.fn()} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('marks Semantic Scholar and Paperclip as configured from server status', async () => {
    mocks.getSemanticScholarKeyStatus.mockResolvedValue({ data: { has_key: true } })
    mocks.getPaperclipKeyStatus.mockResolvedValue({ data: { has_key: true } })

    render(<OnboardingBanner onOpenSettings={vi.fn()} />)

    expect(screen.getByText('Bonus: Semantic Scholar API key')).toBeInTheDocument()
    expect(screen.getByText('Bonus: Paperclip key (biomedical / arXiv full-text)')).toBeInTheDocument()
    expect(await screen.findAllByText('— configured')).toHaveLength(2)
  })
})