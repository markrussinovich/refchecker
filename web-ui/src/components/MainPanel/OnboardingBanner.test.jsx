import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  configs: [],
  settings: {},
  multiuser: false,
  fetchSettings: vi.fn(),
  openExternal: vi.fn(),
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

  it('does not require a local database path in multiuser mode', () => {
    mocks.multiuser = true
    mocks.configs = [{ id: 1, provider: 'openai', has_key: true }]

    const { container } = render(<OnboardingBanner onOpenSettings={vi.fn()} />)

    expect(container).toBeEmptyDOMElement()
  })
})