import { describe, expect, it } from 'vitest'
import {
  asCitedReference, applyReferenceCorrections, exportCorrectionsOnly,
  exportDiffAsCsv, exportDiffAsMarkdown, exportResultsAsBibtex,
  hasReferenceCorrection, sortReferencesForExport,
} from './formatters'

const base = {
  index: 23, title: 'Original title', authors: ['Original Author'], year: 2020,
  venue: 'Original Journal', doi: '10.1234/original', arxiv_id: '2401.00001',
  cited_url: 'https://example.com/original', errors: [], warnings: [],
}
const formats = ['markdown', 'text', 'bibtex', 'ris', 'jsonl', 'csv']
const corrections = [
  ['title', 'ref_title_correct', 'Correct title', 'title'],
  ['author', 'ref_authors_correct', ['Correct Author', 'Second Author'], 'authors'],
  ['year', 'ref_year_correct', 2024, 'year'],
  ['venue', 'ref_venue_correct', 'Correct Journal', 'venue'],
  ['doi', 'ref_doi_correct', 'https://doi.org/10.1234/correct', 'doi'],
  ['arxiv_id', 'ref_arxiv_id_correct', '2501.00001', 'arxiv_id'],
  ['url', 'ref_url_correct', 'https://example.com/correct', 'cited_url'],
]

describe('export acceptance matrix', () => {
  for (const [type, key, value, field] of corrections) {
    for (const bucket of ['errors', 'warnings']) {
      it(`${bucket}: applies only the supplied ${type} fix and preserves all other fields`, () => {
        const ref = { ...base, [bucket]: [{ error_type: type, [key]: value }] }
        const expected = { ...base, [field]: type === 'doi' ? '10.1234/correct' : value }
        const actual = applyReferenceCorrections(ref)
        for (const property of ['title', 'authors', 'year', 'venue', 'doi', 'arxiv_id', 'cited_url']) {
          expect(actual[property], property).toEqual(expected[property])
        }
        expect(hasReferenceCorrection(ref)).toBe(true)
        expect(hasReferenceCorrection(base)).toBe(false)
      })
    }
  }

  it.each(formats)('serializes all corrected citation fields in %s', format => {
    const ref = {
      ...base, doi: null, arxiv_id: null, cited_url: null,
      corrected_reference: {
        title: 'Corrected citation title', authors: ['Jane Doe', 'John Smith'],
        year: 2025, venue: 'Corrected Journal', doi: '10.1234/fixed',
      },
    }
    const output = exportCorrectionsOnly([ref], format)
    for (const value of ['Corrected citation title', 'Jane Doe', 'John Smith', '2025', 'Corrected Journal', '10.1234/fixed']) {
      expect(output).toContain(value)
    }
    expect(output).not.toContain('Original title')
    expect(output).not.toContain('Original Author')
  })

  it.each(['string', 'objects'])('exports stored corrected authors represented as %s', shape => {
    const authors = shape === 'string' ? 'Jane Doe and John Smith'
      : [{ name: 'Jane Doe' }, { name: 'John Smith' }]
    const ref = { ...base, corrected_reference: { authors } }
    for (const format of formats) {
      const output = exportCorrectionsOnly([ref], format)
      expect(output).toContain('Jane Doe')
      expect(output).toContain('John Smith')
      expect(output).not.toContain('[object Object]')
    }
  })

  it('keeps corrected arXiv identifiers and their links consistent in every format', () => {
    const ref = {
      ...base, doi: null, venue: 'arXiv preprint',
      cited_url: 'https://arxiv.org/abs/2401.00001',
      errors: [{ error_type: 'arxiv_id', ref_arxiv_id_correct: '2501.00001' }],
    }
    for (const format of formats) {
      const output = exportCorrectionsOnly([ref], format)
      expect(output).toContain('2501.00001')
      expect(output).not.toContain('2401.00001')
    }
    expect(exportCorrectionsOnly([ref], 'ris')).toContain('AN  - arXiv:2501.00001')
  })

  it('keeps corrected DOI links consistent without overwriting unrelated URLs', () => {
    const ref = { ...base, arxiv_id: null, cited_url: 'https://doi.org/10.1234/original',
      errors: [{ error_type: 'doi', ref_doi_correct: 'https://doi.org/10.1234/correct' }] }
    for (const format of formats) {
      const output = exportCorrectionsOnly([ref], format)
      expect(output).toContain('10.1234/correct')
      expect(output).not.toContain('10.1234/original')
    }
    expect(applyReferenceCorrections({ ...ref, cited_url: base.cited_url }).cited_url).toBe(base.cited_url)
  })

  it('does not let a suggested arXiv URL override an explicit identifier fix', () => {
    const ref = { ...base, doi: null,
      errors: [{ error_type: 'arxiv_id', ref_arxiv_id_correct: '2501.00001' }],
      suggestions: [{ suggestion_details: 'See https://arxiv.org/abs/2401.00001' }] }
    expect(exportCorrectionsOnly([ref], 'bibtex')).not.toContain('2401.00001')
  })

  it('retains a venue on a citation linked to an arXiv preprint', () => {
    const ref = { ...base, venue: 'ICLR', doi: null,
      cited_url: 'https://arxiv.org/abs/2401.00001',
      errors: [{ error_type: 'year', ref_year_correct: 2024 }] }
    expect(exportCorrectionsOnly([ref], 'bibtex')).toContain('ICLR')
  })

  it('does not rewrite existing BibTeX citation keys after correcting a year', () => {
    const ref = { ...base, bibtex_key: 'Original2020Key',
      errors: [{ error_type: 'year', ref_year_correct: 2024 }] }
    expect(exportCorrectionsOnly([ref], 'bibtex')).toContain('{Original2020Key,')
    expect(exportResultsAsBibtex({ references: [asCitedReference(ref)] })).toContain('{Original2020Key,')
  })

  it('shows only real fixes, not recovered metadata, on the corrected side', () => {
    const original = { ...base }
    const ref = {
      ...base, authors: ['Recovered Author'],
      original_reference: original,
      errors: [{ error_type: 'year', ref_year_correct: 2024 }],
    }
    const corrected = applyReferenceCorrections(ref)
    expect(corrected.authors).toEqual(original.authors)
    const diff = exportDiffAsMarkdown({ references: [ref], style: 'plaintext' })
    expect(diff).not.toContain('Recovered Author')
    expect(exportDiffAsCsv({ references: [ref] })).not.toContain('Recovered Author')
  })

  it('sorts by exported years, with original mode retaining the cited years', () => {
    const refs = [
      { ...base, year: 2025, errors: [{ error_type: 'year', ref_year_correct: 2020 }] },
      { ...base, title: 'Middle year', year: 2022 },
    ]
    expect(sortReferencesForExport(refs, 'year-desc').map(ref => ref.title))
      .toEqual(['Middle year', base.title])
    expect(sortReferencesForExport(refs.map(asCitedReference), 'year-desc').map(ref => ref.title))
      .toEqual([base.title, 'Middle year'])
  })
})
