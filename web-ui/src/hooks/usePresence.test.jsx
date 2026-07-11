import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Capture the handlers passed to the (mocked) presence WebSocket so the test can
// drive onMessage directly, and a close() spy for cleanup assertions.
const mocks = vi.hoisted(() => ({
  handlers: null,
  close: vi.fn(),
  updateHistoryReference: vi.fn(),
  updateHistoryProgress: vi.fn(),
  authState: { user: { id: 1 }, authRequired: true },
}))

vi.mock('../utils/api', () => ({
  createPresenceWebSocket: (_roomId, handlers) => {
    mocks.handlers = handlers
    return { close: mocks.close }
  },
}))

vi.mock('../stores/useAuthStore', () => ({
  useAuthStore: () => mocks.authState,
}))

vi.mock('../stores/useHistoryStore', () => ({
  useHistoryStore: {
    getState: () => ({
      updateHistoryReference: mocks.updateHistoryReference,
      updateHistoryProgress: mocks.updateHistoryProgress,
    }),
  },
}))

import { usePresence } from './usePresence'

describe('usePresence — batch-room live results routing (R26)', () => {
  beforeEach(() => {
    mocks.handlers = null
    mocks.close.mockClear()
    mocks.updateHistoryReference.mockClear()
    mocks.updateHistoryProgress.mockClear()
    mocks.authState = { user: { id: 1 }, authRequired: true }
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('routes a presence-socket reference_result into the history store keyed by check_id', () => {
    const { result } = renderHook(() => usePresence('batch-42'))
    expect(mocks.handlers).toBeTruthy()

    mocks.handlers.onMessage({
      type: 'reference_result',
      check_id: 99,
      index: 3, // 1-based; should map to refIndex 2
      status: 'verified',
      title: 'Some ref',
    })

    expect(mocks.updateHistoryReference).toHaveBeenCalledTimes(1)
    const [checkId, refIndex, refData] = mocks.updateHistoryReference.mock.calls[0]
    expect(checkId).toBe(99)
    expect(refIndex).toBe(2)
    expect(refData.status).toBe('verified')
    expect(refData.title).toBe('Some ref')
    // The roster must NOT be updated by a results event.
    expect(result.current).toEqual([])
  })

  it('routes a presence-socket summary_update into updateHistoryProgress', () => {
    renderHook(() => usePresence('batch-42'))

    mocks.handlers.onMessage({
      type: 'summary_update',
      check_id: 99,
      total_refs: 10,
      processed_refs: 4,
      errors_count: 1,
    })

    expect(mocks.updateHistoryProgress).toHaveBeenCalledTimes(1)
    const [checkId, payload] = mocks.updateHistoryProgress.mock.calls[0]
    expect(checkId).toBe(99)
    expect(payload.status).toBe('in_progress')
    expect(payload.total_refs).toBe(10)
    expect(payload.processed_refs).toBe(4)
  })

  it('dedups duplicate reference_result deliveries on check_id + ref index', () => {
    renderHook(() => usePresence('batch-42'))

    const msg = { type: 'reference_result', check_id: 99, index: 1, status: 'verified' }
    mocks.handlers.onMessage(msg)
    mocks.handlers.onMessage(msg) // duplicate (e.g. owner has a second socket)

    expect(mocks.updateHistoryReference).toHaveBeenCalledTimes(1)
  })

  it('still updates the roster from a presence_state/join/leave event and does not route it as a result', () => {
    const { result, rerender } = renderHook(() => usePresence('batch-42'))

    mocks.handlers.onMessage({
      type: 'presence_state',
      users: [{ user_id: 1, name: 'Me' }, { user_id: 2, name: 'Bob' }],
    })
    rerender()

    expect(result.current).toHaveLength(2)
    expect(mocks.updateHistoryReference).not.toHaveBeenCalled()
    expect(mocks.updateHistoryProgress).not.toHaveBeenCalled()
  })

  it('ignores a results event with no check_id (cannot be routed)', () => {
    renderHook(() => usePresence('batch-42'))
    mocks.handlers.onMessage({ type: 'reference_result', index: 1, status: 'verified' })
    expect(mocks.updateHistoryReference).not.toHaveBeenCalled()
  })

  it('does not connect (and routes nothing) when auth is disabled', () => {
    mocks.authState = { user: null, authRequired: false }
    const { result } = renderHook(() => usePresence('batch-42'))
    expect(mocks.handlers).toBeNull()
    expect(result.current).toEqual([])
  })
})
