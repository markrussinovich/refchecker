import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  addConfig: vi.fn(),
  updateConfig: vi.fn(),
  multiuser: false,
  validateLLMConfig: vi.fn(),
}))

vi.mock('../../stores/useConfigStore', () => ({
  useConfigStore: () => ({
    addConfig: mocks.addConfig,
    updateConfig: mocks.updateConfig,
  }),
}))

vi.mock('../../stores/useAuthStore', () => ({
  useAuthStore: (selector) => selector({ multiuser: mocks.multiuser }),
}))

vi.mock('../../stores/useKeyStore', () => {
  const useKeyStore = () => ({})
  useKeyStore.getState = () => ({ setKey: vi.fn(), getKey: vi.fn() })
  return { useKeyStore }
})

vi.mock('../../utils/api', () => ({
  validateLLMConfig: mocks.validateLLMConfig,
}))

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

import LLMConfigModal from './LLMConfigModal'

describe('LLMConfigModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.multiuser = false
  })

  it('shows single-user help text when not in multiuser mode', () => {
    mocks.multiuser = false
    render(<LLMConfigModal isOpen={true} onClose={vi.fn()} />)

    expect(screen.getByText('Stored securely and never shown again')).toBeTruthy()
    expect(screen.queryByText(/never saved on the server/)).toBeNull()
  })

  it('shows browser-only storage help text in multiuser mode', () => {
    mocks.multiuser = true
    render(<LLMConfigModal isOpen={true} onClose={vi.fn()} />)

    expect(screen.getByText('Stored only in your browser — never saved on the server')).toBeTruthy()
    expect(screen.queryByText('Stored securely and never shown again')).toBeNull()
  })
})
