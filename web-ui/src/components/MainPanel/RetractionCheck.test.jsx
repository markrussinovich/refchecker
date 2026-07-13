import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getCheckRetractions = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({ getCheckRetractions }))
vi.mock('../../utils/tauriBridge', () => ({ openExternal: vi.fn(), isTauri: () => false }))

import RetractionCheck from './RetractionCheck'

const CHECK_ID = 3
const refsWithDoi = [{ doi: '10.1/x' }, { doi: '10.2/y' }]

// Geometry-bearing styles whose constancy across idle↔busy is what stops a reflow.
const geom = (el) => [el.style.height, el.style.minHeight, el.style.borderRadius, el.style.padding, el.style.boxSizing]
const sizerLabels = () => Array.from(document.querySelectorAll('span[aria-hidden="true"]')).map((s) => s.textContent)

beforeEach(() => { getCheckRetractions.mockReset() })

describe('RetractionCheck — R33 styling + R52 idle↔busy stability', () => {
  it('renders as a shared outline pill at rest with the fixed token geometry', () => {
    render(<RetractionCheck checkId={CHECK_ID} references={refsWithDoi} />)
    const pill = screen.getByRole('button')
    expect(pill.style.height).toBe('var(--control-h)')
    expect(pill.style.borderRadius).toBe('var(--control-radius)')
    expect(pill.style.boxSizing).toBe('border-box')
    expect(pill.className).toContain('rc-control')
    // Outline variant fill (not an opaque themed *-bg).
    expect(pill.style.backgroundColor).toBe('var(--outline-fill)')
  })

  it("the button's width/height/radius do not change when clicked — only icon→spinner + label", async () => {
    getCheckRetractions.mockReturnValue(new Promise(() => {})) // stay loading
    render(<RetractionCheck checkId={CHECK_ID} references={refsWithDoi} />)
    const pill = screen.getByRole('button')
    const idleGeom = geom(pill)
    // The longest real label (25 chars) is reserved by the sizer so the label
    // slot is never undersized (no `ch` jump).
    expect(sizerLabels()).toContain('No retractions — re-check')

    fireEvent.click(pill)
    await waitFor(() => expect(pill.querySelector('.animate-spin')).toBeTruthy())
    // R52: geometry byte-for-byte identical busy vs idle; sizer still reserving.
    expect(geom(pill)).toEqual(idleGeom)
    expect(sizerLabels()).toContain('No retractions — re-check')
  })

  it('a clean result recolors the pill to status-success but keeps identical geometry', async () => {
    getCheckRetractions.mockResolvedValue({ data: { results: [], with_doi: 2 } })
    render(<RetractionCheck checkId={CHECK_ID} references={refsWithDoi} />)
    const pill = screen.getByRole('button')
    const idleGeom = geom(pill)
    fireEvent.click(pill)
    await screen.findByText(/No retractions found in OpenAlex/i)
    // Color reports status; geometry never changed (R52).
    expect(pill.style.backgroundColor).toBe('var(--status-success-fill)')
    expect(geom(pill)).toEqual(idleGeom)
  })
})
