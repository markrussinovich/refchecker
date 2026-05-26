import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  multiuser: false,
  hasKey: vi.fn(),
  setKey: vi.fn(),
  deleteKey: vi.fn(),
  updateSetting: vi.fn(),
  fetchSettings: vi.fn(),
  closeSettings: vi.fn(),
  getSemanticScholarKeyStatus: vi.fn(),
  validateSemanticScholarKey: vi.fn(),
  setSemanticScholarKey: vi.fn(),
  deleteSemanticScholarKey: vi.fn(),
  getPaperclipKeyStatus: vi.fn(),
  setPaperclipKey: vi.fn(),
  deletePaperclipKey: vi.fn(),
}))

vi.mock('../../stores/useSettingsStore', () => ({
  useSettingsStore: () => ({
    settings: {},
    isLoading: false,
    version: null,
    isSettingsOpen: true,
    closeSettings: mocks.closeSettings,
    updateSetting: mocks.updateSetting,
    fetchSettings: mocks.fetchSettings,
  }),
}))

vi.mock('../../stores/useKeyStore', () => ({
  useKeyStore: () => ({
    hasKey: mocks.hasKey,
    setKey: mocks.setKey,
    deleteKey: mocks.deleteKey,
  }),
}))

vi.mock('../../stores/useAuthStore', () => ({
  useAuthStore: (selector) => selector({ multiuser: mocks.multiuser, user: { is_admin: true } }),
}))

vi.mock('../Sidebar/LLMSelector', () => ({
  default: () => <div data-testid="llm-selector" />,
}))

vi.mock('../../utils/api', () => ({
  getSemanticScholarKeyStatus: mocks.getSemanticScholarKeyStatus,
  validateSemanticScholarKey: mocks.validateSemanticScholarKey,
  setSemanticScholarKey: mocks.setSemanticScholarKey,
  deleteSemanticScholarKey: mocks.deleteSemanticScholarKey,
  getPaperclipKeyStatus: mocks.getPaperclipKeyStatus,
  setPaperclipKey: mocks.setPaperclipKey,
  deletePaperclipKey: mocks.deletePaperclipKey,
}))

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

import SettingsPanel from './SettingsPanel'

async function saveSemanticScholarKey() {
  render(<SettingsPanel theme="system" onThemeChange={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'API Keys' }))
  // There are now multiple Set/Save buttons on the API Keys tab
  // (one set per API key block — Semantic Scholar, Paperclip). The
  // Semantic Scholar block is rendered first, so [0] still targets
  // it; placeholder text lookups also resolve to that block since
  // each block only shows its input while it's the one being edited.
  fireEvent.click(screen.getAllByRole('button', { name: 'Set' })[0])
  fireEvent.change(screen.getByPlaceholderText('Enter API key…'), { target: { value: 'ss-key' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(mocks.validateSemanticScholarKey).toHaveBeenCalledWith('ss-key'))
}

describe('SettingsPanel Semantic Scholar key storage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.multiuser = false
    mocks.hasKey.mockReturnValue(false)
    mocks.getSemanticScholarKeyStatus.mockResolvedValue({ data: { has_key: false, storage: 'database' } })
    mocks.validateSemanticScholarKey.mockResolvedValue({ data: { valid: true } })
    mocks.setSemanticScholarKey.mockResolvedValue({ data: { has_key: true, storage: 'database' } })
    mocks.deleteSemanticScholarKey.mockResolvedValue({ data: { has_key: false, storage: 'database' } })
    mocks.getPaperclipKeyStatus.mockResolvedValue({ data: { has_key: false, storage: 'database' } })
    mocks.setPaperclipKey.mockResolvedValue({ data: { has_key: true, storage: 'database' } })
    mocks.deletePaperclipKey.mockResolvedValue({ data: { has_key: false, storage: 'database' } })
  })

  it('stores Semantic Scholar keys in the browser cache in multi-user mode', async () => {
    mocks.multiuser = true

    await saveSemanticScholarKey()

    expect(mocks.setKey).toHaveBeenCalledWith('semantic_scholar', 'ss-key')
    expect(mocks.setSemanticScholarKey).not.toHaveBeenCalled()
  })

  it('stores Semantic Scholar keys in the local database in single-user mode', async () => {
    mocks.multiuser = false

    await saveSemanticScholarKey()

    expect(mocks.setSemanticScholarKey).toHaveBeenCalledWith('ss-key')
    expect(mocks.deleteKey).toHaveBeenCalledWith('semantic_scholar')
    expect(mocks.setKey).not.toHaveBeenCalled()
  })
})
