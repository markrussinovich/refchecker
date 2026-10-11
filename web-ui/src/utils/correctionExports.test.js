import { describe, expect, it } from 'vitest'
import {
  applyReferenceCorrections, hasReferenceCorrection,
  exportDiffAsMarkdown, exportDiffAsCsv, exportCorrectedListAsStyle,
  exportResultsAsBibtex,
  asCitedReference,
  exportCorrectionsOnly,
} from './formatters'

const reference = {
  title: 'A checked paper', authors: ['A. Author'], year: 2020,
  corrected_reference: null, status: 'error',
  errors: [{ error_type: 'year', cited_value: '2020', actual_value: '2024' }],
  warnings: [],
}

describe('correction exports', () => {
  it.each(['markdown', 'text', 'bibtex', 'ris', 'jsonl', 'csv'])(
    'exports citations only without findings or unchanged entries in %s', format => {
      const fixed = { ...reference, errors: [{
        error_type: 'year', ref_year_correct: 2024, error_details: 'Year mismatch finding',
      }], warnings: [{ warning_type: 'other', warning_details: 'Unresolved warning finding' }] }
      const enriched = {
        title: 'Unchanged enriched paper', year: 2020, doi: '10.1234/added',
        original_reference: { title: 'Unchanged enriched paper', year: 2020 },
        errors: [], warnings: [],
      }
      const unresolved = { title: 'Unresolved paper', errors: [{ error_type: 'unverified' }] }
      const output = exportCorrectionsOnly([fixed, enriched, unresolved], format)
      expect(output).toContain('A checked paper')
      expect(output).toContain('2024')
      expect(output).not.toContain('Unchanged enriched paper')
      expect(output).not.toContain('Unresolved paper')
      expect(output).not.toContain('Year mismatch finding')
      expect(output).not.toContain('Unresolved warning finding')
      expect(output).not.toContain('RefChecker Report')
      expect(output).not.toContain('error_count')
    },
  )
  it('preserves the extracted citation in original exports despite issue fixes', () => {
    const ref = { ...reference, authors: ['Recovered Author'],
      original_reference: { title: reference.title, authors: ['Original Author'], year: 2020 } }
    const bib = exportResultsAsBibtex({ references: [asCitedReference(ref)] })
    expect(bib).toContain('Original Author')
    expect(bib).toContain('2020')
    expect(bib).not.toContain('Recovered Author')
    expect(bib).not.toContain('2024')
  })

  it('prefers a complete typed author list over a single mismatched author', () => {
    const ref = { ...reference, errors: [{
      error_type: 'author',
      error_details: 'Author 2 mismatch:\n cited: Wrong Author\n actual: Second Author',
      ref_authors_correct: ['First Author', 'Second Author'],
    }] }
    expect(applyReferenceCorrections(ref).authors).toEqual(['First Author', 'Second Author'])
  })

  it('uses all verifier-supplied fields, not just the issue type, and does not invent a partial author list', () => {
    const ref = { ...reference, errors: [{
      error_type: 'title', ref_title_correct: 'Correct title', ref_year_correct: 2025,
    }] }
    expect(applyReferenceCorrections(ref)).toMatchObject({ title: 'Correct title', year: 2025 })
    const partial = { ...reference, errors: [{
      error_type: 'author', error_details: 'Author 2 mismatch:\n cited: Wrong\n actual: Second Author',
    }] }
    expect(applyReferenceCorrections(partial).authors).toEqual(reference.authors)
    expect(hasReferenceCorrection(partial)).toBe(false)
  })

  it('resolves stored journal and URL fixes while preserving the original URL in the diff', () => {
    const ref = { ...reference, errors: [], cited_url: 'https://example.com/wrong',
      corrected_reference: { journal: 'Correct Venue', url: 'https://example.com/correct' } }
    expect(applyReferenceCorrections(ref)).toMatchObject({
      venue: 'Correct Venue', cited_url: 'https://example.com/correct',
    })
    const md = exportDiffAsMarkdown({ references: [ref] })
    expect(md).toContain('https://example.com/wrong')
    expect(md).toContain('https://example.com/correct')
  })
  it('resolves fixes from issues even without a corrected_reference payload', () => {
    expect(hasReferenceCorrection(reference)).toBe(true)
    expect(applyReferenceCorrections(reference).year).toBe('2024')
    const markdown = exportDiffAsMarkdown({ references: [reference] })
    expect(markdown).toContain('**As cited:**')
    expect(markdown).toContain('2020')
    expect(markdown).toContain('2024')
    expect(exportDiffAsCsv({ references: [reference] })).toContain('2024')
    expect(exportCorrectedListAsStyle([reference], 'plaintext')).toContain('2024')
    expect(exportResultsAsBibtex({ references: [applyReferenceCorrections(reference)] })).toContain('2024')
  })

  it('accepts stored partial corrections without dropping unchanged metadata', () => {
    const ref = { ...reference, errors: [], corrected_reference: { year: 2025, title: null, authors: [] } }
    expect(applyReferenceCorrections(ref)).toMatchObject({ title: reference.title, authors: reference.authors, year: 2025 })
    expect(exportCorrectedListAsStyle([ref], 'plaintext')).toContain('2025')
  })

  it('uses the original snapshot on the cited side, not recovered authors', () => {
    const ref = {
      ...reference, authors: ['Actual Author'], errors: [],
      original_reference: { title: reference.title, authors: ['Wrong Author'], year: 2020 },
      corrected_reference: { authors: ['Actual Author'] },
    }
    const result = exportDiffAsMarkdown({ references: [ref], style: 'plaintext' })
    expect(result).toMatch(/\*\*As cited:\*\*[^\n]*Wrong Author/)
    expect(result).toMatch(/\*\*Corrected:\*\*[^\n]*Actual Author/)
  })

  it('exports unresolved errors honestly instead of reporting verified clean', () => {
    const ref = { ...reference, errors: [{ error_type: 'unverified', error_details: 'Paper not found' }] }
    expect(hasReferenceCorrection(ref)).toBe(false)
    expect(exportDiffAsMarkdown({ references: [ref] })).toContain('No verified correction available; review manually.')
    expect(exportDiffAsCsv({ references: [ref] })).toContain('Paper not found')
  })

  it('corrections-only excludes unchanged and unresolved references', () => {
    const clean = { ...reference, errors: [], status: 'verified' }
    const unresolved = { ...clean, errors: [{ error_type: 'unverified' }] }
    expect([reference, clean, unresolved].filter(hasReferenceCorrection)).toEqual([reference])
  })
})
