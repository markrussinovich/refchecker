import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const apiInstance = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  }

  return {
    apiInstance,
    create: vi.fn(() => apiInstance),
  }
})

vi.mock('axios', () => ({
  default: {
    create: mocks.create,
  },
}))

import * as api from './api'

describe('batch api helpers', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('posts JSON to the batch URL endpoint', () => {
    const payload = { urls: ['2401.12345'], use_llm: false }

    api.startBatchCheck(payload)

    expect(mocks.apiInstance.post).toHaveBeenCalledWith('/check/batch', payload, {
      timeout: 0,
    })
  })

  it('posts multipart form data to the batch files endpoint', () => {
    const formData = new FormData()
    formData.append('batch_label', 'Batch files')

    api.startBatchFileCheck(formData)

    expect(mocks.apiInstance.post).toHaveBeenCalledWith('/check/batch/files', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0,
    })
  })

  it('posts to the batch cancellation endpoint', () => {
    api.cancelBatch('batch-123')

    expect(mocks.apiInstance.post).toHaveBeenCalledWith('/cancel/batch/batch-123')
  })

  it('patches the batch label endpoint', () => {
    api.updateBatchLabel('batch-123', 'Renamed batch')

    expect(mocks.apiInstance.patch).toHaveBeenCalledWith('/batch/batch-123', {
      batch_label: 'Renamed batch',
    })
  })
})
