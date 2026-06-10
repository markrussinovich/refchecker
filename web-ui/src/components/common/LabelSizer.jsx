/**
 * Invisible longest-label sizer (BUTTON_DESIGN §3.1 — the MANDATED click-state
 * stability technique). Stacks every candidate label this control can show in
 * the SAME inline-grid cell (1 / 1); the widest one sets the box width and is
 * visually hidden but occupies space. The live label is overlaid in the same
 * cell. The result: the label slot is exactly as wide as the longest real
 * string in this control's own font — never narrower (no `ch` undersizing), and
 * never resized between rest ↔ checking ↔ result. This is what keeps the button
 * width fixed across its idle↔busy/expanded states (R52).
 *
 * @param {string[]} candidates  every string the control can display
 * @param {React.ReactNode} children  the live label to show now
 */
export default function LabelSizer({ candidates = [], children }) {
  return (
    <span style={{ position: 'relative', display: 'inline-grid' }}>
      {candidates.map((t) => (
        <span
          key={t}
          aria-hidden="true"
          style={{ gridArea: '1 / 1', visibility: 'hidden', whiteSpace: 'nowrap' }}
        >
          {t}
        </span>
      ))}
      <span style={{ gridArea: '1 / 1', whiteSpace: 'nowrap', textAlign: 'left' }}>
        {children}
      </span>
    </span>
  )
}
