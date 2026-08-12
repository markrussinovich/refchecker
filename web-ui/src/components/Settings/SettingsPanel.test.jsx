import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  getDatabaseStatus: vi.fn(),
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
  getDatabaseStatus: mocks.getDatabaseStatus,
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

async function savePaperclipKey() {
  render(<SettingsPanel theme="system" onThemeChange={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'API Keys' }))
  const paperclipSection = screen.getByText('Paperclip API Key').closest('.py-3')
  fireEvent.click(within(paperclipSection).getByRole('button', { name: 'Set' }))
  fireEvent.change(screen.getByPlaceholderText('Enter Paperclip API key…'), { target: { value: 'pc-key' } })
  fireEvent.click(within(paperclipSection).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(mocks.setKey.mock.calls.length + mocks.setPaperclipKey.mock.calls.length).toBeGreaterThan(0))
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

  it('stores Paperclip keys in the browser cache in multi-user mode', async () => {
    mocks.multiuser = true

    await savePaperclipKey()

    expect(mocks.setKey).toHaveBeenCalledWith('paperclip', 'pc-key')
    expect(mocks.setPaperclipKey).not.toHaveBeenCalled()
  })

  it('stores Paperclip keys in the local database in single-user mode', async () => {
    mocks.multiuser = false

    await savePaperclipKey()

    expect(mocks.setPaperclipKey).toHaveBeenCalledWith('pc-key')
    expect(mocks.deleteKey).toHaveBeenCalledWith('paperclip')
  })

  it('shows server environment keys as active for all sessions in multi-user mode', async () => {
    mocks.multiuser = true
    mocks.getSemanticScholarKeyStatus.mockResolvedValue({ data: { has_key: true, storage: 'environment' } })
    mocks.getPaperclipKeyStatus.mockResolvedValue({ data: { has_key: true, storage: 'environment' } })

    render(<SettingsPanel theme="system" onThemeChange={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'API Keys' }))

    await waitFor(() => {
      expect(screen.getAllByText(/server-provided key is active for all users/i).length).toBe(2)
    })
    // The shared env key belongs to the server — nothing user-removable
    // until a browser override key exists.
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull()
    // Status reads as configured, so both blocks offer Edit (override).
    expect(screen.getAllByRole('button', { name: 'Edit' }).length).toBe(2)
  })

  it('offers Remove for the browser override key even when a server env key exists', async () => {
    mocks.multiuser = true
    mocks.hasKey.mockReturnValue(true)
    mocks.getSemanticScholarKeyStatus.mockResolvedValue({ data: { has_key: true, storage: 'environment' } })
    mocks.getPaperclipKeyStatus.mockResolvedValue({ data: { has_key: true, storage: 'environment' } })

    render(<SettingsPanel theme="system" onThemeChange={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'API Keys' }))

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'Remove' }).length).toBe(2)
    })
  })
})

describe('SettingsPanel local database status', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.multiuser = true
    mocks.hasKey.mockReturnValue(false)
    mocks.getSemanticScholarKeyStatus.mockResolvedValue({ data: {} })
    mocks.getPaperclipKeyStatus.mockResolvedValue({ data: {} })
  })

  it('warns an admin when the local S2 snapshot has stopped updating', async () => {
    mocks.getDatabaseStatus.mockResolvedValue({
      data: {
        databases: [
          {
            database: 's2',
            label: 'Semantic Scholar',
            path: '/data/semantic_scholar.db',
            exists: true,
            size_bytes: 90_000_000_000,
            snapshot: '2025-01-15',
            snapshot_age_days: 420,
            snapshot_stale: true,
            ingest_complete: true,
          },
        ],
        active: ['s2'],
        using_local_s2: true,
        refresh_interval_hours: 24,
      },
    })

    render(<SettingsPanel theme="system" onThemeChange={vi.fn()} />)

    expect(await screen.findByText(/Semantic Scholar — present/)).toBeInTheDocument()
    expect(screen.getByText(/420 days old — not updating/)).toBeInTheDocument()
  })

  it('reports a missing local database instead of silently omitting it', async () => {
    mocks.getDatabaseStatus.mockResolvedValue({
      data: {
        databases: [
          {
            database: 's2',
            label: 'Semantic Scholar',
            path: '/data/semantic_scholar.db',
            exists: false,
            size_bytes: null,
            snapshot: null,
            snapshot_age_days: null,
            snapshot_stale: false,
          },
        ],
        active: [],
        using_local_s2: false,
        refresh_interval_hours: 24,
      },
    })

    render(<SettingsPanel theme="system" onThemeChange={vi.fn()} />)

    expect(await screen.findByText(/Semantic Scholar — missing/)).toBeInTheDocument()
  })

  it('names a missing API key as the reason refreshes are failing', async () => {
    // The hosted deployment sat five months on a stale snapshot because the
    // datasets API 401s without a key and nothing ever said so.
    mocks.getDatabaseStatus.mockResolvedValue({
      data: {
        databases: [
          {
            database: 's2',
            label: 'Semantic Scholar',
            path: '/data/semantic_scholar.db',
            exists: true,
            size_bytes: 90_000_000_000,
            snapshot: '2026-03-10',
            snapshot_age_days: 155,
            snapshot_stale: true,
            ingest_complete: true,
            api_key_configured: false,
          },
        ],
        active: ['s2'],
        using_local_s2: true,
        refresh_interval_hours: 24,
      },
    })

    render(<SettingsPanel theme="system" onThemeChange={vi.fn()} />)

    expect(await screen.findByText(/SEMANTIC_SCHOLAR_API_KEY is not set/)).toBeInTheDocument()
  })

  it('stays quiet about the API key when one is configured', async () => {
    mocks.getDatabaseStatus.mockResolvedValue({
      data: {
        databases: [
          {
            database: 's2',
            label: 'Semantic Scholar',
            path: '/data/semantic_scholar.db',
            exists: true,
            size_bytes: 90_000_000_000,
            snapshot: '2026-08-05',
            snapshot_age_days: 2,
            snapshot_stale: false,
            ingest_complete: true,
            api_key_configured: true,
          },
        ],
        active: ['s2'],
        using_local_s2: true,
        refresh_interval_hours: 24,
      },
    })

    render(<SettingsPanel theme="system" onThemeChange={vi.fn()} />)

    expect(await screen.findByText(/Semantic Scholar — present/)).toBeInTheDocument()
    expect(screen.queryByText(/SEMANTIC_SCHOLAR_API_KEY is not set/)).not.toBeInTheDocument()
  })
})

describe('SettingsPanel local database disk', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.multiuser = true
    mocks.hasKey.mockReturnValue(false)
    mocks.getSemanticScholarKeyStatus.mockResolvedValue({ data: {} })
    mocks.getPaperclipKeyStatus.mockResolvedValue({ data: {} })
  })

  it('surfaces a nearly full data disk and leftover refresh staging dirs', async () => {
    mocks.getDatabaseStatus.mockResolvedValue({
      data: {
        databases: [
          {
            database: 's2',
            label: 'Semantic Scholar',
            path: '/data/semantic_scholar.db',
            exists: true,
            size_bytes: 90_000_000_000,
            snapshot: '2026-08-05',
            snapshot_age_days: 7,
            snapshot_stale: false,
            ingest_complete: true,
          },
        ],
        disk: {
          path: '/data',
          total_bytes: 100_000_000_000,
          free_bytes: 1_000_000_000,
          used_bytes: 99_000_000_000,
          orphaned_staging_dirs: ['tmpabc'],
        },
        active: ['s2'],
        using_local_s2: true,
        refresh_interval_hours: 24,
      },
    })

    render(<SettingsPanel theme="system" onThemeChange={vi.fn()} />)

    expect(await screen.findByText(/1.0 GB free of 100 GB/)).toBeInTheDocument()
    expect(screen.getByText(/1 leftover refresh staging dir/)).toBeInTheDocument()
  })
})
