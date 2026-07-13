import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  users: [],
  currentUser: { id: 1, name: 'Me' },
}))

vi.mock('../../hooks/usePresence', () => ({
  usePresence: () => mocks.users,
}))

vi.mock('../../stores/useAuthStore', () => ({
  useAuthStore: () => ({ user: mocks.currentUser }),
}))

import PresenceAvatars from './PresenceAvatars'

describe('PresenceAvatars', () => {
  beforeEach(() => {
    mocks.users = []
    mocks.currentUser = { id: 1, name: 'Me' }
  })

  it('renders nothing when only the current user is present', () => {
    mocks.users = [{ user_id: 1, name: 'Me', email: 'me@x.com' }]
    const { container } = render(<PresenceAvatars roomId="batch-7" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when the roster is empty', () => {
    mocks.users = []
    const { container } = render(<PresenceAvatars roomId="batch-7" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows an avatar with initials for another viewer', () => {
    mocks.users = [
      { user_id: 1, name: 'Me', email: 'me@x.com' },
      { user_id: 2, name: 'Bob Stone', email: 'bob@x.com' },
    ]
    render(<PresenceAvatars roomId="batch-7" />)
    expect(screen.getByText('BS')).toBeInTheDocument()
    expect(screen.getByLabelText('1 other person viewing this batch')).toBeInTheDocument()
  })

  it('collapses overflow beyond five other viewers', () => {
    mocks.users = [
      { user_id: 1, name: 'Me' },
      ...Array.from({ length: 7 }, (_, i) => ({ user_id: i + 2, name: `User ${i + 2}` })),
    ]
    render(<PresenceAvatars roomId="batch-7" />)
    // 7 others → 5 shown + a "+2" overflow chip.
    expect(screen.getByText('+2')).toBeInTheDocument()
    expect(screen.getByLabelText('7 other people viewing this batch')).toBeInTheDocument()
  })
})
