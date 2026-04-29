import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import StatsSection from './StatsSection'

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

vi.mock('../../stores/useCheckStore', () => {
  const state = { statusFilter: [], setStatusFilter: vi.fn() }
  const useCheckStore = (selector) => selector ? selector(state) : state
  useCheckStore.getState = () => state
  return { useCheckStore }
})

// Helper to build a reference object
const makeRef = (status, { errors = [], warnings = [], ...rest } = {}) => ({
  status,
  errors,
  warnings,
  ...rest,
})

describe('StatsSection warning count excludes refs that also have errors', () => {
  it('should not double-count refs with both errors and warnings', () => {
    // 3 refs with real errors; 2 of those ALSO have warnings
    // 2 refs with warnings-only (no errors)
    // 1 verified ref
    const references = [
      makeRef('error', {
        errors: [{ error_type: 'author', message: 'author mismatch' }],
        warnings: [{ message: 'year is approximate' }],
      }),
      makeRef('error', {
        errors: [{ error_type: 'title', message: 'title mismatch' }],
        warnings: [{ message: 'venue differs' }],
      }),
      makeRef('error', {
        errors: [{ error_type: 'year', message: 'wrong year' }],
      }),
      makeRef('warning', {
        warnings: [{ message: 'year off by 1' }],
      }),
      makeRef('warning', {
        warnings: [{ message: 'venue not found' }],
      }),
      makeRef('verified'),
    ]

    const stats = {
      total_refs: 6,
      processed_refs: 6,
      errors_count: 3,
      warnings_count: 4,
      suggestions_count: 0,
      unverified_count: 0,
      hallucination_count: 0,
    }

    render(
      <StatsSection
        stats={stats}
        isComplete={true}
        references={references}
        paperTitle="Test Paper"
        paperSource="https://example.com/paper"
      />
    )

    // The error badge should show 3 (refs with errors)
    // The warning badge should show 2 (refs with warnings ONLY, not 4)
    // The verified badge should show 1
    const badges = screen.getAllByRole('button')
    // Verified, Errors, Warnings badges (+ Export button)
    // Find the text content of all badge-like buttons
    const badgeTexts = badges.map(b => b.textContent.trim())

    // Verified=1, Errors=3, Warnings=2
    expect(badgeTexts).toContain('1')
    expect(badgeTexts).toContain('3')
    expect(badgeTexts).toContain('2')
    // Warnings should NOT show 4 (inclusive would count refs with both errors+warnings)
    expect(badgeTexts).not.toContain('4')
  })
})

describe('StatsSection hallucination count', () => {
  it('does not count LLM-found matching metadata as hallucinated', () => {
    const references = [
      makeRef('hallucination', {
        title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
        authors: ['Martin Balla', 'M. Long', 'George E. James Goodman'],
        year: 2024,
        hallucination_assessment: {
          verdict: 'LIKELY',
          link: 'https://arxiv.org/abs/2405.18123',
          found_title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
          found_authors: 'Martin Balla, G. E. Long, George E. James Goodman',
          found_year: '2024',
        },
      }),
    ]

    render(
      <StatsSection
        stats={{ total_refs: 1, processed_refs: 1, hallucination_count: 1 }}
        isComplete={true}
        references={references}
        paperTitle="Test Paper"
        paperSource="https://example.com/paper"
      />
    )

    expect(screen.queryByTitle(/likely hallucinated/i)).toBeNull()
  })
})
