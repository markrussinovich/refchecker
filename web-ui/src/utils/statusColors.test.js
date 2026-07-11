import { describe, expect, it } from 'vitest'
import { STATUS_COLORS, getStatusColors, normalizeStatus } from './statusColors'

// The full status set produced by ReferenceCard.getStatusColor (ReferenceCard.jsx:408-421).
const FULL_STATUS_SET = [
  'verified',
  'error',
  'warning',
  'suggestion',
  'hallucination',
  'unverified',
  'checking',
  'pending',
  'unchecked',
]

describe('statusColors (R14 shared status→color map)', () => {
  it('defines a complete {fill,stroke} pair for every getStatusColor status + default', () => {
    for (const status of [...FULL_STATUS_SET, 'default']) {
      expect(STATUS_COLORS, `missing key: ${status}`).toHaveProperty(status)
      const { fill, stroke } = STATUS_COLORS[status]
      expect(fill, `${status}.fill`).toMatch(/^rgba\(/)
      expect(stroke, `${status}.stroke`).toMatch(/^rgba\(/)
    }
  })

  it('getStatusColors returns the correct consistent pair for every status', () => {
    for (const status of FULL_STATUS_SET) {
      expect(getStatusColors(status)).toEqual(STATUS_COLORS[status])
    }
  })

  it('maps the `hallucinated` alias to `hallucination`', () => {
    expect(normalizeStatus('hallucinated')).toBe('hallucination')
    expect(getStatusColors('hallucinated')).toEqual(STATUS_COLORS.hallucination)
    expect(getStatusColors('hallucinated')).toEqual(getStatusColors('hallucination'))
  })

  it('normalizes case and whitespace before lookup', () => {
    expect(getStatusColors('  VERIFIED ')).toEqual(STATUS_COLORS.verified)
    expect(getStatusColors('Hallucinated')).toEqual(STATUS_COLORS.hallucination)
  })

  it('falls back to `default` for empty/unknown status (never invisible)', () => {
    for (const bad of [undefined, null, '', '   ', 'bogus']) {
      expect(getStatusColors(bad)).toEqual(STATUS_COLORS.default)
      expect(normalizeStatus(bad)).toBe('default')
    }
  })

  it('viewers + card agree: each verification-status hue is distinct', () => {
    const fills = FULL_STATUS_SET.map((s) => STATUS_COLORS[s].fill)
    // The four primary verification verdicts must be visually distinguishable.
    const primary = ['verified', 'error', 'warning', 'hallucination'].map((s) => STATUS_COLORS[s].fill)
    expect(new Set(primary).size).toBe(primary.length)
    // Every entry is a usable rgba string.
    for (const f of fills) expect(f).toMatch(/^rgba\([\d.,\s]+\)$/)
  })
})
