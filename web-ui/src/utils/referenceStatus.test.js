import { describe, expect, it } from 'vitest'
import { buildReferenceSummary, computeReferenceStats, getEffectiveReferenceStatus, llmFoundMetadataMatchesCitation } from './referenceStatus'

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

  it('does not treat last-name-only author overlap as matching LLM metadata', () => {
    const reference = {
      status: 'hallucination',
      title: 'Cupy: A numpy-compatible library for nvidia gpu calculations',
      authors: ['ROYUD Nishino', 'Shohei Hido Crissman Loomis'],
      year: 2017,
      errors: [{
        error_type: 'author',
        error_details: 'Author count mismatch: 2 cited vs 5 correct',
      }],
      matched_database: 'Semantic Scholar',
      authoritative_urls: [{
        type: 'semantic_scholar',
        url: 'https://api.semanticscholar.org/CorpusID:41278748',
      }],
      hallucination_assessment: {
        verdict: 'LIKELY',
        link: 'https://api.semanticscholar.org/CorpusID:41278748',
        found_title: 'CuPy: A NumPy-Compatible Library for NVIDIA GPU Calculations',
        found_authors: 'Ryosuke Okuta, Yuya Unno, Daisuke Nishino, Shohei Hido, Crissman Loomis',
        found_year: '2017',
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

  it('does not count transient unverified refs while hallucination checks are still pending', () => {
    const stats = computeReferenceStats([
      { status: 'verified', errors: [], warnings: [], suggestions: [] },
      {
        status: 'unverified',
        errors: [{ error_type: 'unverified', error_details: 'Not found' }],
        warnings: [],
        suggestions: [],
        hallucination_check_pending: true,
      },
    ], false)

    expect(stats.totalProcessed).toBe(2)
    expect(stats.count).toBe(1)
    expect(stats.verified).toBe(1)
    expect(stats.withUnverified).toBe(0)
    expect(stats.hallucinated).toBe(0)
  })

  it('counts unverified refs after the check is complete', () => {
    const stats = computeReferenceStats([
      { status: 'verified', errors: [], warnings: [], suggestions: [] },
      {
        status: 'unverified',
        errors: [{ error_type: 'unverified', error_details: 'Not found' }],
        warnings: [],
        suggestions: [],
      },
    ], true)

    expect(stats.totalProcessed).toBe(2)
    expect(stats.count).toBe(2)
    expect(stats.verified).toBe(1)
    expect(stats.withUnverified).toBe(1)
  })

  it('builds one display summary for progress, reference buckets, and issue totals', () => {
    const summary = buildReferenceSummary({
      stats: { total_refs: 9, processed_refs: 5, errors_count: 99 },
      references: [
        { status: 'verified', errors: [], warnings: [], suggestions: [] },
        { status: 'error', errors: [{ error_type: 'author' }], warnings: [], suggestions: [] },
        { status: 'warning', errors: [], warnings: [{ warning_type: 'year' }], suggestions: [] },
        { status: 'suggestion', errors: [], warnings: [], suggestions: [{ suggestion_type: 'doi' }, { suggestion_type: 'url' }] },
        { status: 'unverified', errors: [{ error_type: 'unverified' }], warnings: [], suggestions: [] },
      ],
      isComplete: true,
    })

    expect(summary.totalRefs).toBe(9)
    expect(summary.processedRefs).toBe(5)
    expect(summary.references).toMatchObject({
      verified: 2,
      errors: 1,
      warnings: 1,
      suggestions: 1,
      unverified: 1,
      hallucinated: 0,
    })
    expect(summary.issues).toMatchObject({
      errors: 1,
      warnings: 1,
      suggestions: 2,
      unverified: 1,
      hallucinated: 0,
    })
  })

  it('falls back to stored aggregate stats when references are unavailable', () => {
    const summary = buildReferenceSummary({
      stats: {
        total_refs: 12,
        processed_refs: 8,
        refs_verified: 3,
        refs_with_errors: 2,
        refs_with_warnings_only: 1,
        refs_with_suggestions_only: 4,
        errors_count: 5,
        warnings_count: 6,
        suggestions_count: 7,
        unverified_count: 8,
        hallucination_count: 9,
      },
      references: [],
      isComplete: false,
    })

    expect(summary.totalRefs).toBe(12)
    expect(summary.processedRefs).toBe(8)
    expect(summary.references).toMatchObject({
      verified: 3,
      errors: 2,
      warnings: 1,
      suggestions: 4,
      unverified: 8,
      hallucinated: 9,
    })
    expect(summary.issues).toMatchObject({
      errors: 5,
      warnings: 6,
      suggestions: 7,
      unverified: 8,
      hallucinated: 9,
    })
  })

  it('clamps progress at 100% and reconciles total when processed exceeds an early total estimate', () => {
    // Repro of "Checking references (28/23) · 122% complete": total_refs is the
    // early extraction estimate (23) but processed_refs (28) is the real count
    // after de-dup/merge/re-extraction.
    const summary = buildReferenceSummary({
      stats: { total_refs: 23, processed_refs: 28 },
      references: [],
      isComplete: true,
    })

    // Percent never exceeds 100 …
    expect(summary.progressPercent).toBe(100)
    expect(summary.progressPercent).toBeLessThanOrEqual(100)
    // … and the visible "X / Y" can never read X > Y: the total is reconciled
    // up to the real processed count instead of staying at the stale estimate.
    expect(summary.totalRefs).toBe(28)
    expect(summary.processedRefs).toBe(28)
    expect(summary.processedRefs).toBeLessThanOrEqual(summary.totalRefs)
  })
})