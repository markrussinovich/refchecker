import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

// API layer — addReferenceToCheck is the only call the add form makes (plus a
// best-effort verify which we no-op). The real useReferenceActions hook runs.
const addReferenceToCheck = vi.hoisted(() => vi.fn())
const verifyReferenceInCheck = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({
  addReferenceToCheck,
  verifyReferenceInCheck,
  removeReferenceFromCheck: vi.fn(),
  suggestAlternativeReference: vi.fn(),
}))

// Zustand stores — each hook applies the selector to a static mock state and
// exposes a matching getState(). selectedCheckId is truthy so the add form is
// enabled and handleAddRef proceeds to the API call. Built inside vi.hoisted so
// the helper is available to the hoisted vi.mock factories below.
const { historyState, checkState, styleState, mkStore } = vi.hoisted(() => {
  const mkStore = (state) => {
    const hook = (selector) => (selector ? selector(state) : state)
    hook.getState = () => state
    return hook
  }
  return {
    historyState: {
      selectedCheckId: 5,
      selectCheck: vi.fn().mockResolvedValue(undefined),
      optimisticApplyCorrection: vi.fn(),
      optimisticRevertCorrection: vi.fn(),
      optimisticRemoveReference: vi.fn(),
    },
    checkState: {
      statusFilter: [],
      references: [],
      removeReference: vi.fn(),
      restoreReference: vi.fn(),
      applyCorrectionInStore: vi.fn(),
      revertCorrectionInStore: vi.fn(),
    },
    styleState: { format: 'apa', setFormat: vi.fn(), styleOptions: {}, setStyleOptions: vi.fn() },
    mkStore,
  }
})
vi.mock('../../stores/useHistoryStore', () => ({ useHistoryStore: mkStore(historyState) }))
vi.mock('../../stores/useCheckStore', () => ({ useCheckStore: mkStore(checkState) }))
vi.mock('../../stores/useStyleStore', () => ({ useStyleStore: mkStore(styleState) }))

import CorrectionsView from './CorrectionsView'

// One flagged reference so `categorized` is non-empty and the toolbar (which
// hosts the "+ Add reference" toggle) renders instead of the empty state.
const FLAGGED_REFS = [{
  id: 'ref-1', index: 1, title: 'A Flagged Reference', status: 'error',
  errors: [{ error_type: 'doi', error_details: 'DOI mismatch' }],
  warnings: [], suggestions: [],
}]

let alertSpy
beforeEach(() => {
  addReferenceToCheck.mockReset()
  verifyReferenceInCheck.mockReset().mockResolvedValue({ data: {} })
  alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
})
afterEach(() => { alertSpy.mockRestore() })

const openAddForm = async () => {
  // The "+ Add reference" toggle button reveals the manual-add form.
  fireEvent.click(screen.getByRole('button', { name: /\+ add reference/i }))
  return screen.findByPlaceholderText('Title')
}

describe('CorrectionsView — R17 add-form 409 duplicate surfacing', () => {
  it('alerts "already reference [N]" when the backend rejects the manual add with 409', async () => {
    const err = new Error('Request failed with status code 409')
    err.response = { status: 409, data: { duplicate: true, existing_index: 4, message: 'Already reference [4] in this check.' } }
    addReferenceToCheck.mockRejectedValue(err)

    render(<CorrectionsView references={FLAGGED_REFS} isCheckComplete={true} />)
    const titleInput = await openAddForm()
    fireEvent.change(titleInput, { target: { value: 'Attention Is All You Need' } })
    fireEvent.click(screen.getByText('Save reference'))

    await waitFor(() => expect(alertSpy).toHaveBeenCalled())
    expect(alertSpy.mock.calls[0][0]).toMatch(/already reference \[4\]/i)
    // The friendly duplicate message wins over a generic "Add failed".
    expect(alertSpy.mock.calls[0][0]).not.toMatch(/add failed/i)
  })

  it('a successful add does not alert (no false duplicate path)', async () => {
    addReferenceToCheck.mockResolvedValue({ data: { reference: { id: 'manual-1' }, inserted_index: 2 } })

    render(<CorrectionsView references={FLAGGED_REFS} isCheckComplete={true} />)
    const titleInput = await openAddForm()
    fireEvent.change(titleInput, { target: { value: 'A Genuinely New Work' } })
    fireEvent.click(screen.getByText('Save reference'))

    await waitFor(() => expect(addReferenceToCheck).toHaveBeenCalled())
    expect(alertSpy).not.toHaveBeenCalled()
  })
})
