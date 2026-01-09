import { describe, it, expect } from 'vitest'
import { formatDate, formatAuthors, truncate, formatFileSize, getStatusColors, formatReference } from './formatters'

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

    it('should handle three+ authors with et al', () => {
      const authors = ['John Smith', 'Jane Doe', 'Bob Johnson']
      expect(formatAuthors(authors)).toBe('John Smith et al.')
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
  })
})
