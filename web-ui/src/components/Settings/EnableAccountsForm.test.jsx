import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import EnableAccountsForm from './EnableAccountsForm'

const mocks = vi.hoisted(() => ({ getAuthConfig: vi.fn(), setAuthConfig: vi.fn() }))
vi.mock('../../utils/api', () => mocks)
vi.mock('../../utils/tauriBridge', () => ({
  isTauri: () => false, invokeTauri: vi.fn(), openExternal: vi.fn(),
}))
vi.mock('../../utils/logger', () => ({ logger: { debug: vi.fn() } }))

beforeEach(() => {
  mocks.getAuthConfig.mockResolvedValue({ data: { providers: {}, multiuser_configured: false } })
  mocks.setAuthConfig.mockReset()
  mocks.setAuthConfig.mockResolvedValue({ data: { saved: true } })
})

it('accepts a registered ChatGPT public client without requiring a secret', async () => {
  render(<EnableAccountsForm accent="blue" repoUrl="https://example.com" />)
  await waitFor(() => expect(mocks.getAuthConfig).toHaveBeenCalled())
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.change(screen.getByPlaceholderText('ChatGPT Client ID'), { target: { value: 'registered-client' } })
  fireEvent.change(screen.getByPlaceholderText('Registered callback URL (optional)'), {
    target: { value: 'https://example.com/api/auth/callback/chatgpt' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Apply & restart' }))
  await waitFor(() => expect(mocks.setAuthConfig).toHaveBeenCalledWith({
    multiuser: true, chatgpt_client_id: 'registered-client',
    chatgpt_redirect_uri: 'https://example.com/api/auth/callback/chatgpt',
  }))
})
