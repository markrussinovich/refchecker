import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Button from './Button'
import IconButton from './IconButton'
import LabelSizer from './LabelSizer'
import SplitButton from './SplitButton'

// R33 — unified button styling: the shared token system. R52 — click-state
// stability: no state changes a control's width/height/radius/border. jsdom does
// not run layout (getBoundingClientRect returns 0), so we assert the *geometry-
// bearing style declarations* are present and invariant across states — that IS
// what guarantees the rendered box can't reflow.

describe('Button — pill geometry (R33/R52)', () => {
  it('pill size pins height, radius, padding and box-sizing from the shared tokens', () => {
    render(<Button size="pill" variant="outline">Check for retractions</Button>)
    const btn = screen.getByRole('button')
    expect(btn.style.height).toBe('var(--control-h)')
    expect(btn.style.minHeight).toBe('var(--control-h)')
    expect(btn.style.borderRadius).toBe('var(--control-radius)')
    expect(btn.style.padding).toBe('0 var(--control-pad-x)')
    expect(btn.style.boxSizing).toBe('border-box')
    expect(btn.className).toContain('rc-control') // the focus-visible ring
  })

  it('every action variant exists and reads from a token (one family, no opaque *-bg)', () => {
    for (const variant of ['outline', 'status-success', 'status-warning', 'status-error']) {
      const { unmount } = render(<Button size="pill" variant={variant}>x</Button>)
      const btn = screen.getByRole('button')
      // fill is a token (translucent status fill / themed outline), never an opaque *-bg
      expect(btn.style.backgroundColor).toMatch(/var\(--(status-|outline-)/)
      expect(btn.style.backgroundColor).not.toMatch(/-bg\)/)
      unmount()
    }
  })

  it('loading swaps ONLY the icon slot to a spinner — the geometry-bearing styles are identical to rest', () => {
    const icon = <svg data-testid="icon" />
    const { rerender } = render(
      <Button size="pill" variant="status-success" icon={icon}>No retractions — re-check</Button>,
    )
    const idle = screen.getByRole('button')
    const idleGeom = [idle.style.height, idle.style.minHeight, idle.style.borderRadius, idle.style.padding, idle.style.boxSizing]
    expect(screen.getByTestId('icon')).toBeInTheDocument()

    rerender(
      <Button size="pill" variant="status-success" icon={icon} loading>Checking retractions…</Button>,
    )
    const busy = screen.getByRole('button')
    const busyGeom = [busy.style.height, busy.style.minHeight, busy.style.borderRadius, busy.style.padding, busy.style.boxSizing]
    // Geometry is byte-for-byte identical busy vs idle (R52 — no reflow on click).
    expect(busyGeom).toEqual(idleGeom)
    // The icon is replaced by the spinner; the icon slot itself never changes size.
    expect(screen.queryByTestId('icon')).toBeNull()
    expect(busy.querySelector('.animate-spin')).toBeTruthy()
  })

  it('disabled keeps the variant fill/border and only dims (never swaps to grey)', () => {
    const { rerender } = render(<Button size="pill" variant="status-error">x</Button>)
    const fill = screen.getByRole('button').style.backgroundColor
    rerender(<Button size="pill" variant="status-error" disabled>x</Button>)
    const dis = screen.getByRole('button')
    expect(dis.style.backgroundColor).toBe(fill)         // same fill, not grey
    expect(dis.style.opacity).toBe('0.6')                // dimmed only
    expect(dis.style.backgroundColor).not.toContain('bg-tertiary')
  })
})

describe('IconButton — fixed square (R52)', () => {
  it('is a fixed 28×28 square by default, 22×22 with size="sm", radius from token', () => {
    const { rerender } = render(<IconButton><svg /></IconButton>)
    const md = screen.getByRole('button')
    expect(md.className).toContain('rc-iconbtn')
    expect(md.className).not.toContain('rc-iconbtn-sm')
    expect(md.className).toContain('rc-control')

    rerender(<IconButton size="sm"><svg /></IconButton>)
    expect(screen.getByRole('button').className).toContain('rc-iconbtn-sm')
  })

  it('rotation is class-only (transform), so the box never reflows when toggled', () => {
    const { rerender } = render(<IconButton chevron rotated={false}><svg /></IconButton>)
    const btn = screen.getByRole('button')
    expect(btn.className).toContain('rc-iconbtn-chevron')
    expect(btn.className).not.toContain('rc-rotated')
    rerender(<IconButton chevron rotated><svg /></IconButton>)
    expect(screen.getByRole('button').className).toContain('rc-rotated')
  })
})

describe('LabelSizer — reserves the longest-label width (R52, BUTTON_DESIGN §3.1)', () => {
  it('renders every candidate as a hidden, non-reflowing, aria-hidden sizer plus the live label', () => {
    const candidates = ['Check for retractions', 'Checking retractions…', 'No retractions — re-check']
    render(<LabelSizer candidates={candidates}>Checking retractions…</LabelSizer>)
    // The live label is visible exactly once (the visible overlay).
    const visible = document.querySelector('span[style*="text-align: left"]')
    expect(visible.textContent).toBe('Checking retractions…')
    // Every candidate is present as a hidden sizer so the box is as wide as the
    // longest real string — never narrower, so swaps can't shrink/grow it.
    const hidden = Array.from(document.querySelectorAll('span[aria-hidden="true"]'))
    expect(hidden.map((s) => s.textContent)).toEqual(candidates)
    hidden.forEach((s) => {
      expect(s.style.visibility).toBe('hidden')
      expect(s.style.whiteSpace).toBe('nowrap')   // each candidate occupies space, can't wrap
    })
  })
})

describe('SplitButton — caret is a post-result addition (R52, BUTTON_DESIGN §3.2)', () => {
  const main = <Button size="pill" variant="outline">Numbering consistent — re-check</Button>

  it('pre-result renders a lone pill: no caret segment, full radius on the main wrapper', () => {
    const { container } = render(<SplitButton main={main} caret={false} />)
    // Exactly one button (the main); no caret IconButton yet.
    expect(container.querySelectorAll('button').length).toBe(1)
    const wrapper = container.querySelector('span > span > span')
    expect(wrapper.style.borderRadius).toBe('var(--control-radius)')
  })

  it('post-result adds the caret and flattens ONLY the main right corners (left edge unchanged)', () => {
    const { container } = render(
      <SplitButton main={main} caret caretOpen={false} onCaretToggle={() => {}} />,
    )
    // Now two buttons: main + caret. The caret animates in (rc-caret-in).
    const buttons = container.querySelectorAll('button')
    expect(buttons.length).toBe(2)
    const caret = container.querySelector('.rc-caret-in')
    expect(caret).toBeTruthy()
    expect(caret.style.borderLeft).toBe('var(--control-border)')      // single divider
    expect(caret.style.borderRadius).toBe('0 var(--control-radius) var(--control-radius) 0')
    // Main wrapper flattens its RIGHT corners only — its left corners (the edge
    // the reviewer must not see "pop") keep the radius.
    const wrapper = container.querySelector('span > span > span')
    expect(wrapper.style.borderRadius).toBe('var(--control-radius) 0 0 var(--control-radius)')
  })

  it('the caret menu anchors bottom-right and only renders when open (no button shift)', () => {
    const { rerender, container } = render(
      <SplitButton main={main} caret menu={<div data-testid="menu" />} menuOpen={false} onCaretToggle={() => {}} />,
    )
    expect(screen.queryByTestId('menu')).toBeNull()
    rerender(
      <SplitButton main={main} caret menu={<div data-testid="menu" />} menuOpen onCaretToggle={() => {}} />,
    )
    const anchor = screen.getByTestId('menu').parentElement
    expect(anchor.style.position).toBe('absolute')
    expect(anchor.style.right).toBe('0px')
    // The group wrapper keeps overflow:visible so the menu + focus ring escape.
    expect(container.firstChild.style.overflow).toBe('visible')
  })

  it('toggling the caret fires onCaretToggle', () => {
    let n = 0
    render(<SplitButton main={main} caret onCaretToggle={() => { n += 1 }} />)
    fireEvent.click(document.querySelector('.rc-caret-in'))
    expect(n).toBe(1)
  })
})
