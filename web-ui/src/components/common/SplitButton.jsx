import IconButton from './IconButton'

/**
 * Split-button group (BUTTON_DESIGN §1.4, §3.2): a main <Button> with an
 * attached caret <IconButton>, sharing one height, the outer-corner-only radius,
 * and a single 1px divider, plus a relative wrapper that anchors the caret menu.
 *
 * Resolving "identical at rest" vs. the always-reserved caret (§3.2 option A):
 * the caret/divider only EXIST after the first result. Pre-result the group is a
 * lone pill, visually identical to the sibling action pills. When `caret` turns
 * true the caret fades+slides in (opacity 0→1, translateX(-4px)→0) over 120ms,
 * and the main segment's right corners flatten 8px→0 over the same 120ms, so the
 * main segment's LEFT edge never moves. The caret is explicitly exempt from the
 * "identical at rest" criterion because at rest it does not exist.
 *
 * @param {React.ReactNode} main      a <Button size="pill"> element (the main segment)
 * @param {boolean} caret             whether the caret segment exists (post-result)
 * @param {boolean} caretOpen         whether the caret menu is open (rotates the chevron)
 * @param {function} onCaretToggle    caret click handler
 * @param {boolean} caretDisabled     disable the caret
 * @param {React.ReactNode} menu      dropdown content (absolutely positioned)
 * @param {boolean} menuOpen          whether to render the menu
 */
export default function SplitButton({
  main,
  caret = false,
  caretOpen = false,
  onCaretToggle,
  caretDisabled = false,
  menu = null,
  menuOpen = false,
  caretTitle = 'Show details',
  fullWidth = false,
}) {
  return (
    // overflow:visible so the focus ring (§1.2) and the menu are never clipped.
    // fullWidth (used inside the 2×2 action grid) makes the group fill its cell:
    // the main segment flex-grows while the caret keeps its fixed square width.
    <span style={{ position: 'relative', display: 'inline-flex', overflow: 'visible', width: fullWidth ? '100%' : undefined }}>
      <span style={{ display: 'inline-flex', alignItems: 'stretch', width: fullWidth ? '100%' : undefined }}>
        {/* The main segment. When the caret exists, flatten its right corners and
            drop its right border so exactly one 1px divider shows; the caret keeps
            its left border. The transition makes that corner flatten smoothly. */}
        <span
          style={{
            display: 'inline-flex',
            flexGrow: fullWidth ? 1 : undefined,
            minWidth: fullWidth ? 0 : undefined,
            borderRadius: caret
              ? 'var(--control-radius) 0 0 var(--control-radius)'
              : 'var(--control-radius)',
            transition: 'border-radius 120ms ease',
          }}
        >
          {main}
        </span>
        {caret && (
          <IconButton
            chevron
            rotated={caretOpen}
            onClick={onCaretToggle}
            disabled={caretDisabled}
            aria-expanded={menuOpen}
            title={caretTitle}
            className="rc-caret-in"
            style={{
              width: 'var(--control-caret-w)',
              minWidth: 'var(--control-caret-w)',
              height: 'var(--control-h)',
              borderRadius: '0 var(--control-radius) var(--control-radius) 0',
              borderLeft: 'var(--control-border)',
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </IconButton>
        )}
      </span>
      {caret && menuOpen && menu && (
        <div
          style={{
            position: 'absolute', top: 'calc(100% + 4px)', right: 0,
            minWidth: 200, zIndex: 20,
          }}
        >
          {menu}
        </div>
      )}
    </span>
  )
}
