import { render, screen } from '@testing-library/react'
import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

// LLMConfigModal pulls in api/validation machinery that isn't relevant here;
// stub it out so the selector can be tested in isolation.
vi.mock('./LLMConfigModal', () => ({ default: () => null }))

import { useConfigStore } from '../../stores/useConfigStore'
import { useAuthStore } from '../../stores/useAuthStore'
import { useKeyStore } from '../../stores/useKeyStore'
import LLMSelector from './LLMSelector'

describe('LLMSelector', () => {
  beforeEach(() => {
    localStorage.clear()
    useKeyStore.setState({ keys: {} })
    useAuthStore.setState({ multiuser: true })
    useConfigStore.setState({
      configs: [{ id: 42, provider: 'anthropic', model: 'claude-sonnet-4-6', has_key: false }],
      selectedConfigId: null,
      selectedExtractionConfigId: 42,
      selectedHallucinationConfigId: null,
      selectedChatConfigId: null,
      selectedSummaryConfigId: null,
      isLoading: false,
    })
  })

  it('re-renders and shows the config as configured as soon as a browser key is set (regression test)', () => {
    render(<LLMSelector mode="extraction" />)

    // No key yet — selector should show the placeholder.
    expect(screen.getByText('No LLM configured')).toBeTruthy()

    // Simulate LLMConfigModal saving a key for this config in another part of the tree.
    act(() => {
      useKeyStore.getState().setKey('llm:42', 'sk-test-key-123')
    })

    // The selector must react to the key-store update without needing an
    // unrelated re-render to pick up the change.
    expect(screen.queryByText('No LLM configured')).toBeNull()
    expect(screen.getByText('claude-sonnet-4-6')).toBeTruthy()
  })
})
