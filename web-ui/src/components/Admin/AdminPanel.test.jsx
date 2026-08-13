import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AdminPanel from './AdminPanel'

const mocks = vi.hoisted(() => ({
  getAdminOverview: vi.fn(),
  getAdminUsers: vi.fn(),
  getAdminUserSessions: vi.fn(),
  getAdminCheckDetail: vi.fn(),
}))

vi.mock('../../utils/api', () => mocks)

const overview = {
  window_days: 30,
  totals: {
    total_users: 12,
    active_users: 5,
    checks: 40,
    distinct_papers: 33,
    references_checked: 800,
    references_verified: 700,
    errors: 30,
    warnings: 12,
    unverified: 70,
    hallucinations: 9,
    hallucination_rate: 1.13,
    verified_rate: 87.5,
    avg_references_per_check: 20,
    avg_duration_ms: 4200,
  },
  daily: [
    { day: '2026-08-10', checks: 3, users: 2, references_checked: 60, hallucinations: 1 },
    { day: '2026-08-11', checks: 7, users: 3, references_checked: 140, hallucinations: 2 },
  ],
  breakdowns: {
    source_types: [{ name: 'url', count: 30 }, { name: 'pdf', count: 10 }],
    extraction_methods: [],
    models: [],
    failure_classes: [],
  },
}

const users = {
  users: [
    {
      id: 7,
      name: 'Ada Lovelace',
      email: 'ada@example.com',
      provider: 'github',
      is_admin: false,
      checks: 22,
      references_checked: 400,
      hallucinations: 5,
      last_check_at: '2026-08-11 10:00:00',
    },
  ],
  unattributed: { checks: 4, references_checked: 40, hallucinations: 0 },
}

const sessions = {
  user: { id: 7, name: 'Ada Lovelace', email: 'ada@example.com' },
  sessions: [
    {
      started_at: '2026-08-11 10:00:00',
      ended_at: '2026-08-11 10:20:00',
      duration_seconds: 1200,
      checks: 1,
      references_checked: 20,
      references_verified: 18,
      errors: 1,
      warnings: 0,
      unverified: 1,
      hallucinations: 2,
      batch_labels: [],
      items: [
        { id: 501, paper_title: 'On Computable Numbers', total_refs: 20, hallucination_count: 2 },
      ],
    },
  ],
}

const checkDetail = {
  id: 501,
  paper_title: 'On Computable Numbers',
  status: 'completed',
  timestamp: '2026-08-11 10:00:00',
  total_refs: 3,
  refs_verified: 1,
  errors_count: 1,
  hallucination_count: 1,
  llm_model: 'gpt-5',
  extraction_method: 'llm',
  references: [
    { title: 'A real paper', status: 'verified', authors: ['X Y'], year: 2020 },
    { title: 'A fake paper', status: 'hallucination', authors: ['Nobody'], year: 2021 },
    {
      title: 'A flawed paper',
      status: 'verified',
      errors: [{ error_type: 'author', error_details: 'wrong' }],
      authors: ['Z W'],
    },
  ],
}

describe('AdminPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.getAdminOverview.mockResolvedValue({ data: overview })
    mocks.getAdminUsers.mockResolvedValue({ data: users })
    mocks.getAdminUserSessions.mockResolvedValue({ data: sessions })
    mocks.getAdminCheckDetail.mockResolvedValue({ data: checkDetail })
  })

  it('renders nothing and fetches nothing when closed', () => {
    const { container } = render(<AdminPanel open={false} onClose={() => {}} />)
    expect(container.firstChild).toBeNull()
    expect(mocks.getAdminOverview).not.toHaveBeenCalled()
  })

  it('shows headline totals including hallucinations', async () => {
    const { container } = render(<AdminPanel open onClose={() => {}} />)

    await waitFor(() => expect(screen.getByText('Checks')).toBeTruthy())

    // Scope each assertion to its own stat card: several totals share a value.
    const statFor = (label) => {
      const node = Array.from(container.querySelectorAll('div')).find(
        (el) => el.className.includes('text-xs') && el.textContent === label
      )
      return node?.nextElementSibling?.textContent
    }

    expect(statFor('Users')).toBe('5')
    expect(statFor('Checks')).toBe('40')
    expect(statFor('References')).toBe('800')
    expect(statFor('Hallucinated')).toBe('9')
    expect(statFor('Avg duration')).toBe('4.2s')
    expect(screen.getByText('1.1% of refs')).toBeTruthy()
    expect(screen.getByText('87.5%')).toBeTruthy()
    expect(screen.getByText('12 registered')).toBeTruthy()
  })

  it('counts only users who ran a check in the window, not all registrations', async () => {
    const { container } = render(<AdminPanel open onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText('Checks')).toBeTruthy())

    const label = Array.from(container.querySelectorAll('div')).find(
      (el) => el.className.includes('text-xs') && el.textContent === 'Users'
    )
    // active_users (5), not total_users (12).
    expect(label?.nextElementSibling?.textContent).toBe('5')
    expect(screen.getByText('12 registered')).toBeTruthy()
  })

  it('labels the checks-per-day chart with dates', async () => {
    const { container } = render(<AdminPanel open onClose={() => {}} />)

    await waitFor(() => expect(screen.getByText('Checks per day')).toBeTruthy())

    const chart = container.querySelector('svg[aria-label="Checks per day"]')
    expect(chart).toBeTruthy()
    const labels = Array.from(chart.querySelectorAll('text')).map((t) => t.textContent)
    expect(labels).toEqual(['Aug 10', 'Aug 11'])
  })

  it('thins x-axis labels on long windows but always keeps the endpoints', async () => {
    const longDaily = Array.from({ length: 30 }, (_, i) => ({
      day: `2026-07-${String(i + 1).padStart(2, '0')}`,
      checks: i,
      users: 1,
      references_checked: i * 2,
      hallucinations: 0,
    }))
    mocks.getAdminOverview.mockResolvedValue({
      data: { ...overview, daily: longDaily },
    })

    const { container } = render(<AdminPanel open onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText('Checks per day')).toBeTruthy())

    const chart = container.querySelector('svg[aria-label="Checks per day"]')
    const labels = Array.from(chart.querySelectorAll('text')).map((t) => t.textContent)

    expect(labels.length).toBeLessThanOrEqual(8)
    expect(labels[0]).toBe('Jul 1')
    expect(labels[labels.length - 1]).toBe('Jul 30')
  })

  it('drills from users through sessions to a check and its references', async () => {
    render(<AdminPanel open onClose={() => {}} />)
    await waitFor(() => expect(mocks.getAdminUsers).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: /users/i }))
    const userRow = await screen.findByText('Ada Lovelace')
    fireEvent.click(userRow)

    await waitFor(() => expect(mocks.getAdminUserSessions).toHaveBeenCalledWith(7, 30))
    const paper = await screen.findByText('On Computable Numbers')
    fireEvent.click(paper)

    await waitFor(() => expect(mocks.getAdminCheckDetail).toHaveBeenCalledWith(501))
    expect(await screen.findByText('A fake paper')).toBeTruthy()
  })

  it('labels each reference using the shared status precedence', async () => {
    render(<AdminPanel open onClose={() => {}} />)
    await waitFor(() => expect(mocks.getAdminUsers).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: /users/i }))
    fireEvent.click(await screen.findByText('Ada Lovelace'))
    fireEvent.click(await screen.findByText('On Computable Numbers'))
    await screen.findByText('A fake paper')

    // hallucination beats everything; an error beats a nominal "verified".
    expect(screen.getByLabelText('Hallucinated')).toBeTruthy()
    expect(screen.getByLabelText('Error')).toBeTruthy()
    expect(screen.getByLabelText('Verified')).toBeTruthy()
  })

  it('reports unattributed checks so the user total is not silently short', async () => {
    render(<AdminPanel open onClose={() => {}} />)
    await waitFor(() => expect(mocks.getAdminUsers).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /users/i }))

    expect(await screen.findByText(/4 checks are not attributed to a user/i)).toBeTruthy()
  })

  it('refetches when the time window changes', async () => {
    render(<AdminPanel open onClose={() => {}} />)
    await waitFor(() => expect(mocks.getAdminOverview).toHaveBeenCalledWith(30))

    fireEvent.change(screen.getByLabelText('Time window'), { target: { value: '0' } })
    await waitFor(() => expect(mocks.getAdminOverview).toHaveBeenCalledWith(0))
  })

  it('surfaces a load failure instead of rendering empty stats', async () => {
    mocks.getAdminOverview.mockRejectedValue({ response: { data: { detail: 'Admin access required' } } })
    render(<AdminPanel open onClose={() => {}} />)

    expect(await screen.findByText('Admin access required')).toBeTruthy()
  })

  it('styles every control from the theme rather than hardcoded colours', async () => {
    const { container } = render(<AdminPanel open onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText('Checks')).toBeTruthy())

    // A hardcoded hex/rgb or a Tailwind colour utility would not follow the
    // light/dark theme, which is what made the panel look out of place.
    for (const el of container.querySelectorAll('[style]')) {
      const style = el.getAttribute('style')
      expect(style).not.toMatch(/#[0-9a-f]{3,6}/i)
      expect(style).not.toMatch(/\brgb\(/)
    }
    for (const el of container.querySelectorAll('button')) {
      expect(el.className).not.toMatch(/hover:bg-(black|white|blue|red|gray|slate)/)
    }
  })

  it('marks the active tab so the selection is visible', async () => {
    render(<AdminPanel open onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText('Checks')).toBeTruthy())

    const overviewTab = screen.getByRole('button', { name: /^overview$/i })
    const usersTab = screen.getByRole('button', { name: /^users$/i })
    expect(overviewTab.getAttribute('aria-pressed')).toBe('true')
    expect(usersTab.getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(usersTab)
    expect(usersTab.getAttribute('aria-pressed')).toBe('true')
    expect(overviewTab.getAttribute('aria-pressed')).toBe('false')
  })

  it('colours hallucinations with the hallucination hue, not the error hue', async () => {
    const { container } = render(<AdminPanel open onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText('Checks')).toBeTruthy())

    const hallucinated = Array.from(container.querySelectorAll('div')).find(
      (el) => el.className.includes('text-xs') && el.textContent === 'Hallucinated'
    )
    expect(hallucinated?.nextElementSibling?.getAttribute('style')).toContain(
      'var(--color-hallucination)'
    )
  })
})
