import { describe, it, expect } from 'vitest'
import { formatDate, formatAuthors, truncate, formatFileSize, getStatusColors, formatReference, displayReferenceValue, exportReferenceAsBibtex } from './formatters'

describe('formatters', () => {
  describe('formatDate', () => {
    it('should format ISO date string', () => {
      const result = formatDate('2024-01-08T10:30:00')
      expect(result).toBeTruthy()
      expect(typeof result).toBe('string')
    })

    it('should handle today date', () => {
      const now = new Date()
      const result = formatDate(now)
      expect(result).toContain('Today')
    })

    it('should handle invalid dates', () => {
      expect(formatDate('not a date')).toBe('Invalid Date')
    })
  })

  describe('formatAuthors', () => {
    it('should format two authors with and', () => {
      const authors = ['John Smith', 'Jane Doe']
      expect(formatAuthors(authors)).toBe('John Smith and Jane Doe')
    })

    it('should handle single author', () => {
      expect(formatAuthors(['John Smith'])).toBe('John Smith')
    })

    it('should handle three+ authors by showing all', () => {
      const authors = ['John Smith', 'Jane Doe', 'Bob Johnson']
      expect(formatAuthors(authors)).toBe('John Smith, Jane Doe, Bob Johnson')
    })

    it('should handle three+ authors with et al when truncate=true', () => {
      const authors = ['John Smith', 'Jane Doe', 'Bob Johnson']
      expect(formatAuthors(authors, true)).toBe('John Smith et al.')
    })

    it('should handle empty array', () => {
      expect(formatAuthors([])).toBe('Unknown authors')
    })

    it('should handle null/undefined', () => {
      expect(formatAuthors(null)).toBe('Unknown authors')
      expect(formatAuthors(undefined)).toBe('Unknown authors')
    })
  })

  describe('truncate', () => {
    it('should not truncate short strings', () => {
      expect(truncate('Hello', 10)).toBe('Hello')
    })

    it('should truncate long strings with ellipsis', () => {
      const longText = 'This is a very long string that needs truncation'
      const result = truncate(longText, 20)
      expect(result.length).toBeLessThanOrEqual(20)
      expect(result).toContain('...')
    })

    it('should handle null/undefined', () => {
      expect(truncate(null, 10)).toBeNull()
      expect(truncate(undefined, 10)).toBeUndefined()
    })

    it('should use default max length', () => {
      const text = 'A'.repeat(100)
      const result = truncate(text)
      expect(result.length).toBeLessThanOrEqual(50)
    })
  })

  describe('formatFileSize', () => {
    it('should format 0 bytes', () => {
      expect(formatFileSize(0)).toBe('0 Bytes')
    })

    it('should format bytes', () => {
      expect(formatFileSize(500)).toBe('500 Bytes')
    })

    it('should format KB', () => {
      expect(formatFileSize(1024)).toBe('1 KB')
    })

    it('should format MB', () => {
      expect(formatFileSize(1024 * 1024)).toBe('1 MB')
    })
  })

  describe('getStatusColors', () => {
    it('should return success colors for verified', () => {
      const result = getStatusColors('verified')
      expect(result.text).toContain('success')
    })

    it('should return error colors for error', () => {
      const result = getStatusColors('error')
      expect(result.text).toContain('error')
    })

    it('should return warning colors for warning', () => {
      const result = getStatusColors('warning')
      expect(result.text).toContain('warning')
    })

    it('should return muted colors for unknown status', () => {
      const result = getStatusColors('unknown')
      expect(result.text).toContain('muted')
    })
  })

  describe('formatReference', () => {
    it('should format reference with all fields', () => {
      const ref = {
        authors: ['John Smith'],
        year: '2020',
        title: 'Test Paper',
        venue: 'Test Journal'
      }
      const result = formatReference(ref)
      expect(result).toContain('John Smith')
      expect(result).toContain('2020')
      expect(result).toContain('Test Paper')
    })

    it('should handle missing fields', () => {
      const ref = { title: 'Test Paper' }
      const result = formatReference(ref)
      expect(result).toContain('Test Paper')
    })

    it('should omit no-date placeholders', () => {
      const ref = {
        authors: ['John Smith'],
        year: 'n.d.',
        title: 'Undated Tool',
        venue: 'N. D.'
      }
      const result = formatReference(ref)
      expect(result).toBe('John Smith "Undated Tool"')
      expect(displayReferenceValue('n.d.')).toBe('')
    })
  })

  describe('exportReferenceAsBibtex — corrected values', () => {
    it('includes year + venue + DOI named by errors/warnings (no authoritative_urls)', () => {
      // Regression for #53 (R06/R07): warnings name the missing year/venue via
      // typed correction fields, and a doi-type error names the verified DOI.
      // The corrected @article{awcomparison} bibtex must carry year=2018, the
      // venue, AND doi=10.5812/ijem.12104 — with NO ref.doi and NO
      // authoritative_urls to fall back on. The verifier-named DOI wins.
      const ref = {
        title: 'Comparison of osteoporosis pharmacotherapy fracture rates',
        authors: ['Reynolds AW', 'Liu G', 'Kocis PT'],
        // ref.doi intentionally absent — the DOI must come from the error.
        errors: [
          { error_type: 'doi', actual_value: '10.5812/ijem.12104' },
        ],
        warnings: [
          { error_type: 'year', error_details: "Year missing: should include '2018'", ref_year_correct: '2018' },
          { error_type: 'venue', error_details: "Venue missing: should include 'International Journal of Endocrinology and Metabolism'", ref_venue_correct: 'International Journal of Endocrinology and Metabolism' },
        ],
      }
      const bibtex = exportReferenceAsBibtex(ref, 0)
      expect(bibtex).toContain('2018')
      expect(bibtex).toContain('International Journal of Endocrinology and Metabolism')
      expect(bibtex).toContain('doi = {10.5812/ijem.12104}')
    })

    it('R06: a verifier-named DOI wins over the (wrong) cited ref.doi', () => {
      const ref = {
        title: 'Some paper',
        authors: ['Doe J'],
        doi: '10.0000/wrong.cited',
        errors: [{ error_type: 'doi', actual_value: 'https://doi.org/10.1234/correct.5678' }],
      }
      const bibtex = exportReferenceAsBibtex(ref, 0)
      // Emitted DOI is the verified one, normalized off the https://doi.org/ prefix.
      expect(bibtex).toContain('doi = {10.1234/correct.5678}')
      expect(bibtex).not.toContain('10.0000/wrong.cited')
    })

    it('R06: DOI from ref_doi_correct (no actual_value) is emitted in bibtex', () => {
      const ref = {
        title: 'Typed-correction paper',
        authors: ['Roe J'],
        warnings: [{ error_type: 'doi', ref_doi_correct: '10.9999/typed.doi' }],
      }
      const bibtex = exportReferenceAsBibtex(ref, 0)
      expect(bibtex).toContain('doi = {10.9999/typed.doi}')
    })

    it('R06: falls back to authoritative_urls DOI when no doi-type issue exists', () => {
      const ref = {
        title: 'Fallback paper',
        authors: ['Poe J'],
        authoritative_urls: [{ type: 'doi', url: 'https://doi.org/10.5555/from.url' }],
      }
      const bibtex = exportReferenceAsBibtex(ref, 0)
      expect(bibtex).toContain('doi = {10.5555/from.url}')
    })

    it('still honours explicit actual_value when present', () => {
      const ref = {
        title: 'Some paper',
        authors: ['Doe J'],
        errors: [{ error_type: 'year', actual_value: '2020' }],
      }
      const bibtex = exportReferenceAsBibtex(ref, 0)
      expect(bibtex).toContain('2020')
    })
  })
})
