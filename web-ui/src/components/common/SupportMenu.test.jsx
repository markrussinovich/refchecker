import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// R46: the Email-support control must route the mailto: through the OS handler
// (openExternal in the desktop shell, window.location on web) — NOT a bare
// <a href="mailto:"> which renders a blank page in the webview / a blank tab.

const openExternal = vi.fn()
let tauriFlag = true
vi.mock('../../utils/tauriBridge', () => ({
  isTauri: () => tauriFlag,
  openExternal: (...args) => openExternal(...args),
}))

import SupportMenu from './SupportMenu'

function openMenu() {
  render(<SupportMenu />)
  fireEvent.click(screen.getByLabelText('Help & support'))
}

describe('SupportMenu — email support (R46)', () => {
  beforeEach(() => {
    openExternal.mockClear()
    tauriFlag = true
  })

  it('renders Email support as a button, not a bare mailto anchor', () => {
    openMenu()
    const email = screen.getByText('Email support')
    expect(email.closest('a')).toBeNull()
    expect(email.closest('button')).not.toBeNull()
  })

  it('routes the mailto through openExternal in the desktop shell, with both recipients', () => {
    tauriFlag = true
    openMenu()
    fireEvent.click(screen.getByText('Email support'))
    expect(openExternal).toHaveBeenCalledTimes(1)
    const url = openExternal.mock.calls[0][0]
    expect(url).toMatch(/^mailto:/)
    expect(url).toContain('cc=') // second recipient preserved as Cc
    expect(url).toContain('subject=')
  })

  it('on web, navigates the current tab to the mailto URL (no openExternal, no new tab)', () => {
    tauriFlag = false
    const orig = window.location
    const setHref = vi.fn()
    delete window.location
    window.location = { ...orig, set href(v) { setHref(v) } }
    openMenu()
    fireEvent.click(screen.getByText('Email support'))
    expect(openExternal).not.toHaveBeenCalled()
    expect(setHref).toHaveBeenCalledTimes(1)
    expect(setHref.mock.calls[0][0]).toMatch(/^mailto:/)
    window.location = orig
  })
})
