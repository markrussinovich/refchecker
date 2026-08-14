import { render, cleanup, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// The share dialog's report options (which sections to include, and whether to
// add suggested corrections) were only ever applied to the DOWNLOAD. Both
// publish paths — "Publish to web" and "Quick link" — called publishCheck with
// nothing but the adapter/token, so the server re-rendered the full default
// report. A user who unchecked "AI-text detection" and published a link still
// published the AI section. Nothing reported the discrepancy.

vi.mock('./ShareAnimationCanvas', () => ({
  default: () => <div data-testid="share-video" />,
}))

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

const publishCheck = vi.fn(() => Promise.resolve({ data: { url: 'https://example.com/r' } }))
const exportCheckFile = vi.fn(() => Promise.resolve({ data: new Blob(['x']) }))
vi.mock('../../utils/api', () => ({
  exportCheckFile: (...a) => exportCheckFile(...a),
  exportBatchFile: vi.fn(),
  publishCheck: (...a) => publishCheck(...a),
}))

const checkState = { references: [], aiDetection: null, stats: {} }
vi.mock('../../stores/useCheckStore', () => {
  const useCheckStore = (selector) => (selector ? selector(checkState) : checkState)
  useCheckStore.getState = () => checkState
  return { useCheckStore }
})

let historyState = { selectedCheck: null }
vi.mock('../../stores/useHistoryStore', () => {
  const useHistoryStore = (selector) => (selector ? selector(historyState) : historyState)
  useHistoryStore.getState = () => historyState
  return { useHistoryStore }
})

let styleState = { format: 'ieee' }
vi.mock('../../stores/useStyleStore', () => {
  const useStyleStore = (selector) => (selector ? selector(styleState) : styleState)
  useStyleStore.getState = () => styleState
  return { useStyleStore }
})

import ShareModal from './ShareModal'

const references = [
  { status: 'verified', errors: [], warnings: [] },
  { status: 'error', errors: [{ error_type: 'author', message: 'author mismatch' }], warnings: [] },
]

beforeEach(() => {
  historyState = {
    selectedCheck: {
      status: 'completed',
      references,
      ai_detection: { band: 'high', overall_score: 0.9 },
    },
  }
  styleState = { format: 'ieee' }
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const open = () => render(<ShareModal checkId={42} title="Parity Paper" onClose={() => {}} />)

const uncheck = (label) => {
  const box = screen.getByLabelText(label, { exact: false })
  fireEvent.click(box)
}

describe('publish paths carry the dialog’s report options', () => {
  it('quick link sends the selected sections', async () => {
    open()
    uncheck('AI-text detection')
    fireEvent.click(screen.getByText('Quick link'))

    await waitFor(() => expect(publishCheck).toHaveBeenCalled())
    const [, opts] = publishCheck.mock.calls[0]
    expect(opts.adapter).toBe('quick_link')
    expect(opts.include).toBeTruthy()
    expect(opts.include.split(',')).not.toContain('ai')
    expect(opts.include.split(',')).toContain('references')
  })

  it('publish to web sends the selected sections and the corrections flag', async () => {
    open()
    uncheck('Full reference list')
    uncheck('Include suggested corrections')
    fireEvent.click(screen.getByText('Publish to web'))
    fireEvent.change(screen.getByPlaceholderText(/GitHub token/i), { target: { value: 'tok' } })
    fireEvent.click(screen.getByText('Publish & get link'))

    await waitFor(() => expect(publishCheck).toHaveBeenCalled())
    const [, opts] = publishCheck.mock.calls[0]
    expect(opts.adapter).toBe('github_gist')
    expect(opts.corrections).toBe(true)
    expect(opts.include.split(',')).not.toContain('references')
  })

  it('publishes the same canonical summary the download uses', async () => {
    open()
    fireEvent.click(screen.getByText('Quick link'))
    await waitFor(() => expect(publishCheck).toHaveBeenCalled())
    const publishSummary = publishCheck.mock.calls[0][1].summary

    fireEvent.click(screen.getByText(/^Download/))
    await waitFor(() => expect(exportCheckFile).toHaveBeenCalled())
    const downloadSummary = exportCheckFile.mock.calls[0][1].summary

    // Same numbers in the published link as in the downloaded file — otherwise
    // a shared report disagrees with the badge the user is looking at.
    expect(publishSummary).toEqual(downloadSummary)
    expect(publishSummary).toBeTruthy()
  })
})
