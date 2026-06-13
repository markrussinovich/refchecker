import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ReferenceCard from './ReferenceCard'

vi.mock('../../utils/formatters', async () => {
  const actual = await vi.importActual('../../utils/formatters')
  return {
    ...actual,
    copyToClipboard: vi.fn(),
  }
})

describe('ReferenceCard', () => {
  it('does not show a spinner for final unverified refs after completion', () => {
    const reference = {
      status: 'unverified',
      title: 'Unknown Paper',
      authors: ['A. Author'],
      errors: [{ error_type: 'unverified', error_details: 'Paper not found by any checker' }],
      warnings: [],
      suggestions: [],
    }

    const { container } = render(<ReferenceCard reference={reference} index={0} isCheckComplete />)

    expect(container.querySelector('svg.animate-spin')).toBeNull()
    expect(screen.getByText(/Could not verify: Unknown Paper/)).toBeTruthy()
  })

  it('renders LLM-found matching metadata without crashing', () => {
    const reference = {
      status: 'hallucination',
      title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
      authors: ['Martin Balla', 'M. Long', 'George E. James Goodman'],
      venue: 'IEEE Conference on Games',
      year: 2024,
      hallucination_assessment: {
        verdict: 'LIKELY',
        explanation: 'The paper exists with the cited metadata.',
        link: 'https://arxiv.org/abs/2405.18123',
        found_title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
        found_authors: 'Martin Balla, G. E. Long, George E. James Goodman',
        found_year: '2024',
      },
      authoritative_urls: [],
      errors: [{ error_type: 'author', error_details: 'Author mismatch' }],
      warnings: [],
      suggestions: [],
    }

    render(<ReferenceCard reference={reference} index={3} />)

    expect(screen.getByText('Pytag: Tabletop games for multi-agent reinforcement learning')).toBeTruthy()
    expect(screen.getByText('Matched DB:')).toBeTruthy()
    expect(screen.getByText('LLM search')).toBeTruthy()
    expect(screen.queryByText(/Likely hallucinated/i)).toBeNull()
  })

  it('omits no-date placeholders from reference metadata', () => {
    const reference = {
      status: 'verified',
      title: 'Afl',
      authors: [],
      venue: 'n.d.',
      year: 'n.d.',
      cited_url: 'http://lcamtuf.coredump.cx/afl/',
      errors: [],
      warnings: [],
      suggestions: [],
    }

    render(<ReferenceCard reference={reference} index={0} />)

    expect(screen.getByText('Afl')).toBeTruthy()
    expect(screen.queryByText('n.d.')).toBeNull()
  })

  it('highlights author-year citation markers inside context excerpts', () => {
    const reference = {
      status: 'verified',
      title: 'Model multiplicity: Opportunities, concerns, and solutions',
      authors: ['E. Black', 'M. Raghavan', 'S. Barocas'],
      year: 2022,
      citation_count: 1,
      citation_contexts: [{
        marker: '(Black et al., 2022)',
        sentence: 'The model can be arbitrary or random when addressing marginalized groups (Black et al., 2022).',
      }],
      errors: [],
      warnings: [],
      suggestions: [],
    }

    const { container } = render(<ReferenceCard reference={reference} index={10} />)
    fireEvent.click(screen.getByRole('button', { name: /Context/ }))

    const marker = screen.getAllByText('(Black et al., 2022)')[1]
    expect(marker).toBeInTheDocument()
    expect(marker.style.fontWeight).toBe('700')
    expect(container.textContent).toContain('groups (Black et al., 2022).')
  })
})
