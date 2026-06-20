import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// Keep the heavy children out of the way so we can assert the header's shared-
// primitive contract (BUTTON_DESIGN §4.5) in isolation.
vi.mock('./DocumentViewer', () => ({ default: () => <div data-testid="doc-viewer" /> }))
vi.mock('./AIDetectionVisuals', () => ({ default: () => <div data-testid="ai-visuals" /> }))
vi.mock('../../utils/tauriBridge', () => ({ isTauri: () => false, openExternal: vi.fn() }))

import AIDetectionPanel from './AIDetectionPanel'

const detection = (band) => ({
  band,
  overall_score: 0.45,
  summary: 'A summary.',
  disclaimer: 'Advisory only.',
  spans: [
    { quote: 'A flagged passage long enough to keep.', model_score: 0.9 },
    { quote: 'A second flagged passage of sufficient length.', model_score: 0.7 },
  ],
})

describe('AIDetectionPanel — §4.5 shared-primitive contract (R33/R52)', () => {
  it('the collapse chevron is a small (22×22) IconButton, rotation only', () => {
    render(<AIDetectionPanel detection={detection('medium')} checkId={5} />)
    const chevron = screen.getByTitle(/Collapse AI-text detection/i)
    expect(chevron.className).toContain('rc-iconbtn')
    expect(chevron.className).toContain('rc-iconbtn-sm')   // dense 22×22
    expect(chevron.className).toContain('rc-iconbtn-chevron')
    expect(chevron.className).toContain('rc-rotated')       // expanded ⇒ rotated
  })

  it('the likelihood pill is a dense 8px status pill filled by --status-*-fill (not the opaque *-bg)', () => {
    const { container } = render(<AIDetectionPanel detection={detection('medium')} checkId={5} />)
    const pill = container.querySelector('span[style*="--control-h-sm"]')
    expect(pill).toBeTruthy()
    expect(pill.style.borderRadius).toBe('var(--control-radius)')   // 8px, same family
    expect(pill.style.backgroundColor).toBe('var(--status-warning-fill)') // medium ⇒ warning fill
    expect(pill.style.backgroundColor).not.toMatch(/-bg\)/)         // never the brown *-bg block
    // The band label is reserved by the sizer so a band change never resizes it.
    const reserved = Array.from(pill.querySelectorAll('span[aria-hidden="true"]')).map((s) => s.textContent)
    expect(reserved).toContain('AI-likelihood: High')
    expect(reserved).toContain('AI-likelihood: Low')
  })

  it('high band uses the error fill, low band uses the success fill — same geometry, only color differs', () => {
    const { container, rerender } = render(<AIDetectionPanel detection={detection('high')} checkId={5} />)
    const highPill = container.querySelector('span[style*="--control-h-sm"]')
    const highRadius = highPill.style.borderRadius
    expect(highPill.style.backgroundColor).toBe('var(--status-error-fill)')

    rerender(<AIDetectionPanel detection={detection('low')} checkId={5} />)
    const lowPill = container.querySelector('span[style*="--control-h-sm"]')
    expect(lowPill.style.backgroundColor).toBe('var(--status-success-fill)')
    expect(lowPill.style.borderRadius).toBe(highRadius) // geometry identical across bands
  })

  it('View in document is a primary pill; Show/Hide is an outline pill with a sizer-grid for both labels', () => {
    render(<AIDetectionPanel detection={detection('high')} checkId={5} />)
    const view = screen.getByRole('button', { name: /View in document/i })
    expect(view.style.height).toBe('var(--control-h)')
    expect(view.style.borderRadius).toBe('var(--control-radius)')
    expect(view.style.backgroundColor).toBe('var(--color-accent)') // primary

    const show = screen.getByRole('button', { name: /Show 2 flagged passages/i })
    expect(show.style.backgroundColor).toBe('var(--outline-fill)') // outline
    const reserved = Array.from(show.querySelectorAll('span[aria-hidden="true"]')).map((s) => s.textContent)
    expect(reserved).toEqual(['Hide', 'Show 2 flagged passages'])
  })

  it("toggling Show↔Hide doesn't change the button's geometry (sizer holds both candidates)", () => {
    render(<AIDetectionPanel detection={detection('high')} checkId={5} />)
    const show = screen.getByRole('button', { name: /Show 2 flagged passages/i })
    const before = [show.style.height, show.style.borderRadius, show.style.padding, show.style.boxSizing]
    fireEvent.click(show)
    const hide = screen.getByRole('button', { name: /^Hide$/i })
    expect([hide.style.height, hide.style.borderRadius, hide.style.padding, hide.style.boxSizing]).toEqual(before)
  })
})
