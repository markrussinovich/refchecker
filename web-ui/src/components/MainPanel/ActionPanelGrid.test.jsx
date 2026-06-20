import { render, screen, fireEvent, within } from '@testing-library/react'
import { createPortal } from 'react-dom'
import { describe, expect, it } from 'vitest'
import ActionPanelGrid, { useActionGrid } from './ActionPanelGrid'

// A minimal panel that exercises the coordinator contract exactly like the real
// ones: it renders its trigger into the grid cell and PORTALS its details into
// the shared host when it is the open panel.
function TestPanel({ id, label }) {
  const grid = useActionGrid()
  return (
    <div className="rc-grid-cell">
      <button type="button" onClick={() => grid.open(id)}>{label}</button>
      {grid.isOpen(id) && grid.host
        ? createPortal(<div data-testid={`details-${id}`}>{label} details</div>, grid.host)
        : null}
    </div>
  )
}

describe('ActionPanelGrid coordinator (2×2 accordion, full-width details)', () => {
  const renderGrid = () =>
    render(
      <ActionPanelGrid>
        <TestPanel id="a" label="Alpha" />
        <TestPanel id="b" label="Beta" />
      </ActionPanelGrid>
    )

  it('renders every child trigger inside the grid and nothing is open initially', () => {
    const { container } = renderGrid()
    expect(container.querySelector('.rc-action-grid')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Alpha' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Beta' })).toBeInTheDocument()
    // Details host exists but is empty until a panel opens.
    const host = container.querySelector('.rc-action-grid-content')
    expect(host).toBeTruthy()
    expect(host).toBeEmptyDOMElement()
  })

  it('opens a panel’s details into the shared host below the grid on click', () => {
    const { container } = renderGrid()
    fireEvent.click(screen.getByRole('button', { name: 'Alpha' }))
    const host = container.querySelector('.rc-action-grid-content')
    // The details render INSIDE the full-width host, not in the trigger cell.
    expect(within(host).getByTestId('details-a')).toBeInTheDocument()
    expect(host).not.toBeEmptyDOMElement()
  })

  it('is an accordion: opening one panel closes the other; triggers never disappear', () => {
    renderGrid()
    fireEvent.click(screen.getByRole('button', { name: 'Alpha' }))
    expect(screen.getByTestId('details-a')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Beta' }))
    // Beta now open, Alpha closed — only one set of details at a time.
    expect(screen.getByTestId('details-b')).toBeInTheDocument()
    expect(screen.queryByTestId('details-a')).toBeNull()

    // Both trigger buttons remain mounted in their cells throughout (they never
    // shift or unmount when the open panel changes).
    expect(screen.getByRole('button', { name: 'Alpha' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Beta' })).toBeInTheDocument()
  })

  it('standalone panels (no provider) see a null grid — legacy mode', () => {
    // Outside the provider, useActionGrid() is null so a real panel falls back
    // to its stacked layout. We assert the hook returns null here.
    let captured = 'unset'
    function Probe() { captured = useActionGrid(); return null }
    render(<Probe />)
    expect(captured).toBeNull()
  })
})
