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
})