import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LoginPage from './LoginPage'

const mocks = vi.hoisted(() => ({
  loginWithGoogle: vi.fn(),
  loginWithGithub: vi.fn(),
  loginWithMicrosoft: vi.fn(),
  loginWithChatGPT: vi.fn(),
  providers: ['github'],
}))

vi.mock('../../stores/useAuthStore', () => ({
  useAuthStore: () => ({
    providers: mocks.providers,
    loginWithGoogle: mocks.loginWithGoogle,
    loginWithGithub: mocks.loginWithGithub,
    loginWithMicrosoft: mocks.loginWithMicrosoft,
    loginWithChatGPT: mocks.loginWithChatGPT,
    error: null,
  }),
}))

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.providers = ['github']
  })

  it('shows ChatGPT only when configured and redirects through its login action', () => {
    mocks.providers = ['google', 'github', 'chatgpt']
    render(<LoginPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Continue with ChatGPT' }))
    expect(mocks.loginWithChatGPT).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: 'Continue with Google' })).toBeDisabled()
    expect(mocks.loginWithGoogle).not.toHaveBeenCalled()
  })

  it('does not advertise an unconfigured ChatGPT provider', () => {
    render(<LoginPage />)
    expect(screen.queryByRole('button', { name: 'Continue with ChatGPT' })).toBeNull()
  })

  it('shows the expanded hosted-mode description and GitHub repo link', () => {
    render(<LoginPage />)

    expect(screen.getByRole('heading', { name: 'RefChecker' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Verify citations against real sources' })).toBeTruthy()
    expect(screen.getByText(/RefChecker helps researchers inspect paper references/i)).toBeTruthy()
    expect(screen.getByText(/It supports URL, arXiv, file, and pasted-text workflows/i)).toBeTruthy()

    const repoLink = screen.getByRole('link', { name: /View the project on GitHub/i })
    expect(repoLink).toBeTruthy()
    expect(repoLink.getAttribute('href')).toBe('https://github.com/markrussinovich/refchecker')
  })

  it('shows the note about encrypted browser-cached keys and non-persisted server storage', () => {
    render(<LoginPage />)

    expect(screen.getByText(/any LLM keys you enter are retrieved from the encrypted browser cache/i)).toBeTruthy()
    expect(screen.getByText(/only kept in memory on the server/i)).toBeTruthy()
    expect(screen.getByText(/they are not stored in the local database or on the server/i)).toBeTruthy()
  })
})
