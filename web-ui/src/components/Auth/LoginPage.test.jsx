import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LoginPage from './LoginPage'

const mocks = vi.hoisted(() => ({
  loginWithGoogle: vi.fn(),
  loginWithGithub: vi.fn(),
  loginWithMicrosoft: vi.fn(),
}))

vi.mock('../../stores/useAuthStore', () => ({
  useAuthStore: () => ({
    providers: ['github'],
    loginWithGoogle: mocks.loginWithGoogle,
    loginWithGithub: mocks.loginWithGithub,
    loginWithMicrosoft: mocks.loginWithMicrosoft,
    error: null,
  }),
}))

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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

  it('shows the note about browser-cached keys and non-persisted server storage', () => {
    render(<LoginPage />)

    expect(screen.getByText(/any LLM keys you enter will be stored in the browser cache/i)).toBeTruthy()
    expect(screen.getByText(/only kept in memory on the server/i)).toBeTruthy()
    expect(screen.getByText(/they are not persisted on the server/i)).toBeTruthy()
  })
})
