import { describe, expect, it } from 'vitest'
import { getEffectiveReferenceStatus, llmFoundMetadataMatchesCitation } from './referenceStatus'

describe('referenceStatus', () => {
  it('treats LLM-found matching metadata as verified, not hallucinated', () => {
    const reference = {
      status: 'hallucination',
      title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
      authors: ['Martin Balla', 'M. Long', 'George E. James Goodman'],
      year: 2024,
      hallucination_assessment: {
        verdict: 'LIKELY',
        explanation: 'The paper exists with the cited metadata.',
        link: 'https://arxiv.org/abs/2405.18123',
        found_title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
        found_authors: 'Martin Balla, G. E. Long, George E. James Goodman',
        found_year: '2024',
      },
    }

    expect(llmFoundMetadataMatchesCitation(reference)).toBe(true)
    expect(getEffectiveReferenceStatus(reference, true)).toBe('verified')
  })

  it('keeps genuine hallucination verdicts hallucinated', () => {
    const reference = {
      status: 'hallucination',
      title: 'Evaluating large language models with grid-based game competitions',
      authors: ['Oguzhan Topsakal', 'Mete Cicek'],
      year: 2024,
      hallucination_assessment: {
        verdict: 'LIKELY',
        link: 'https://arxiv.org/abs/2407.07796',
        found_title: 'Evaluating Large Language Models with Grid-Based Game Competitions: An Extensible LLM Benchmark and Leaderboard',
        found_authors: 'Oguzhan Topsakal, Colby Jacob Edell, Jackson Bailey Harper',
        found_year: '2024',
      },
    }

    expect(llmFoundMetadataMatchesCitation(reference)).toBe(false)
    expect(getEffectiveReferenceStatus(reference, true)).toBe('hallucination')
  })

  it('prioritizes hallucination over errors and warnings', () => {
    const reference = {
      status: 'hallucination',
      errors: [{ error_type: 'author', error_details: 'Author mismatch' }],
      warnings: [{ error_type: 'year', error_details: 'Year mismatch' }],
    }

    expect(getEffectiveReferenceStatus(reference, true)).toBe('hallucination')
  })

  it('prioritizes errors over warnings', () => {
    const reference = {
      status: 'verified',
      errors: [{ error_type: 'author', error_details: 'Author mismatch' }],
      warnings: [{ error_type: 'year', error_details: 'Year mismatch' }],
    }

    expect(getEffectiveReferenceStatus(reference, true)).toBe('error')
  })

  it('returns warning when no hallucination or errors exist', () => {
    const reference = {
      status: 'verified',
      warnings: [{ error_type: 'venue', error_details: 'Venue mismatch' }],
    }

    expect(getEffectiveReferenceStatus(reference, true)).toBe('warning')
  })

  it('does not show error for an LLM-validated reference with no remaining errors', () => {
    const reference = {
      status: 'error',
      errors: [],
      warnings: [],
      suggestions: [{ suggestion_type: 'arxiv', suggestion_details: 'Reference could include arXiv URL' }],
      matched_database: 'LLM search',
      authoritative_urls: [{ type: 'llm_verified', url: 'https://arxiv.org/abs/2002.09518' }],
      hallucination_assessment: {
        verdict: 'UNLIKELY',
        link: 'https://arxiv.org/abs/2002.09518',
      },
    }

    expect(getEffectiveReferenceStatus(reference, true)).toBe('suggestion')
  })

  it('does not show hidden errors when LLM-found metadata matches the citation', () => {
    const reference = {
      status: 'error',
      title: 'Memory-based graph networks',
      authors: ['Amir Hosein Khas Ahmadi'],
      year: 2020,
      errors: [{ error_type: 'author', error_details: 'Author mismatch' }],
      warnings: [{ error_type: 'year', error_details: 'Year mismatch' }],
      suggestions: [{ suggestion_type: 'arxiv', suggestion_details: 'Reference could include arXiv URL' }],
      authoritative_urls: [{ type: 'llm_verified', url: 'https://arxiv.org/abs/2002.09518' }],
      hallucination_assessment: {
        verdict: 'LIKELY',
        link: 'https://arxiv.org/abs/2002.09518',
        found_title: 'Memory-based graph networks',
        found_authors: 'Amir Hosein Khas Ahmadi',
        found_year: '2020',
      },
    }

    expect(llmFoundMetadataMatchesCitation(reference)).toBe(true)
    expect(getEffectiveReferenceStatus(reference, true)).toBe('suggestion')
  })
})