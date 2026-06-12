import { createContext, useContext, useState } from 'react'

/**
 * Coordinator for the 2×2 action-button grid — Retractions, Gap-finder,
 * Citation-numbering and Chat & Summarize. Each child panel renders ONLY its
 * trigger pill into a fixed grid cell and PORTALS its expanded details into the
 * single full-width region rendered BELOW the grid. So the four buttons sit in
 * a clean 2×2 and never shift when a panel opens; the details always open
 * full-width underneath. One panel open at a time (accordion).
 *
 * Backward-compatible by design: a panel rendered WITHOUT this provider (unit
 * tests, or any legacy stacked usage) sees `useActionGrid() === null` and falls
 * back to its original trigger-then-content-stacked rendering. Grid mode is
 * entirely opt-in via context, so no existing behaviour changes.
 */
const ActionGridContext = createContext(null)

// eslint-disable-next-line react-refresh/only-export-components
export const useActionGrid = () => useContext(ActionGridContext)

export default function ActionPanelGrid({ children }) {
  // Which panel's details are open (null = all collapsed). Accordion: opening
  // one closes the others. The trigger pills stay put regardless.
  const [openId, setOpenId] = useState(null)
  // The full-width host node the open panel portals its content into. A
  // callback ref into state so the portal re-renders once the node exists.
  const [host, setHost] = useState(null)

  const ctx = {
    host,
    isOpen: (id) => openId === id,
    // Open this panel (closing any other). Used by the primary trigger click.
    open: (id) => setOpenId(id),
    // Toggle this panel — used by a caret / re-click that should collapse it.
    toggle: (id) => setOpenId((cur) => (cur === id ? null : id)),
    close: () => setOpenId(null),
  }

  return (
    <ActionGridContext.Provider value={ctx}>
      <div className="rc-action-grid">{children}</div>
      {/* Full-width details host. `:empty` collapses it so a closed accordion
          leaves no gap (see index.css .rc-action-grid-content). */}
      <div className="rc-action-grid-content" ref={setHost} />
    </ActionGridContext.Provider>
  )
}
