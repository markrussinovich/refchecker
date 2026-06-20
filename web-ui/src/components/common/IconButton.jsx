/**
 * Fixed-square icon button (BUTTON_DESIGN §1.4). A 28×28 box by default, or
 * 22×22 when size="sm", with the token radius (8px) and a ghost fill. It centers
 * a single 14px (--control-icon) glyph. Because the square is fixed, it never
 * reflows — used for the split-button caret, the gap-finder header chevron, the
 * AI collapse chevron, and the assistant × close.
 *
 * Carries .rc-control for the :focus-visible ring. When `rotated` is set, the
 * child SVG rotates 180° (the chevron-open affordance) with no layout cost.
 */
export default function IconButton({
  children,
  size = 'md',
  rotated = false,
  chevron = false,
  disabled = false,
  className = '',
  style: styleProp = {},
  ...props
}) {
  const cls = [
    'rc-iconbtn',
    'rc-control',
    size === 'sm' ? 'rc-iconbtn-sm' : '',
    chevron ? 'rc-iconbtn-chevron' : '',
    chevron && rotated ? 'rc-rotated' : '',
    className,
  ].filter(Boolean).join(' ')

  return (
    <button
      type="button"
      className={cls}
      disabled={disabled}
      style={styleProp}
      {...props}
    >
      {children}
    </button>
  )
}
