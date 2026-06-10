/**
 * Reusable button component with variants — the SINGLE SOURCE OF TRUTH for the
 * article-level action controls (BUTTON_DESIGN §1.2). The five action panels
 * (RetractionCheck, GapFinder, CitationIntegrity, ArticleAssistant, the
 * AI-likelihood row) all render through this component plus its IconButton /
 * SplitButton siblings, so they read as ONE family.
 *
 * Click-state stability (R52 / BUTTON_DESIGN §1.3): no state changes a control's
 * width, height, border-radius, or border. Hover swaps ONLY the background to an
 * exact hoverBg token; disabled keeps the variant fill/border and only dims via
 * opacity:0.6; loading swaps ONLY the fixed icon slot to a spinner — the label
 * width is reserved by the caller's sizer-grid (§3.1).
 */
export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  icon = null,
  className = '',
  style: styleProp = {},
  ...props
}) {
  // For non-pill sizes keep the existing Tailwind look. For pill, geometry comes
  // entirely from inline --control-* tokens so height/radius are fixed.
  const baseStyles = 'inline-flex items-center justify-center font-medium transition-colors rc-control'
  const legacyShape = size === 'pill' ? '' : 'rounded-lg'

  const variants = {
    primary: {
      backgroundColor: 'var(--color-accent)',
      color: '#ffffff',
      border: 'none',
      hoverBg: 'var(--color-accent-hover)',
    },
    secondary: {
      backgroundColor: 'var(--color-bg-tertiary)',
      color: 'var(--color-text-primary)',
      border: 'none',
      hoverBg: 'var(--color-border)',
    },
    danger: {
      backgroundColor: 'var(--color-error)',
      color: '#ffffff',
      border: 'none',
      hoverBg: '#dc2626',
    },
    ghost: {
      backgroundColor: 'transparent',
      color: 'var(--color-text-secondary)',
      border: 'none',
      hoverBg: 'var(--color-bg-tertiary)',
    },
    // --- New action-family variants (BUTTON_DESIGN §1.2). Every fill/hover is an
    // exact token; border-color does NOT change on hover, so geometry is fixed. ---
    outline: {
      backgroundColor: 'var(--outline-fill)',
      color: 'var(--color-text-primary)',
      border: 'var(--control-border)',
      hoverBg: 'var(--outline-fill-hover)',
    },
    'status-success': {
      backgroundColor: 'var(--status-success-fill)',
      color: 'var(--color-success)',
      border: '1px solid var(--color-success)',
      hoverBg: 'var(--status-success-fill-hover)',
    },
    'status-warning': {
      backgroundColor: 'var(--status-warning-fill)',
      color: 'var(--color-warning)',
      border: '1px solid var(--color-warning)',
      hoverBg: 'var(--status-warning-fill-hover)',
    },
    'status-error': {
      backgroundColor: 'var(--status-error-fill)',
      color: 'var(--color-error)',
      border: '1px solid var(--color-error)',
      hoverBg: 'var(--status-error-fill-hover)',
    },
  }

  const sizes = {
    sm: 'px-2.5 py-1.5 text-sm',
    md: 'px-4 py-2 text-sm',
    lg: 'px-6 py-3 text-base',
    // pill height/padding/radius come from inline style below, not Tailwind.
    pill: '',
  }

  const style = variants[variant] || variants.primary
  const isPill = size === 'pill'

  // Pill geometry — fixed height/radius/padding so content swaps never reflow.
  const pillStyle = isPill ? {
    height: 'var(--control-h)',
    minHeight: 'var(--control-h)',
    padding: '0 var(--control-pad-x)',
    borderRadius: 'var(--control-radius)',
    fontSize: 'var(--control-font)',
    fontWeight: 'var(--control-font-weight)',
    lineHeight: 1,
    boxSizing: 'border-box',
    gap: 'var(--control-gap)',
    transition: 'var(--control-transition)',
  } : {}

  return (
    <button
      className={`${baseStyles} ${legacyShape} ${sizes[size] ?? ''} ${className}`.trim()}
      style={{
        backgroundColor: style.backgroundColor,
        // Disabled keeps the variant fill/text and only dims (BUTTON_DESIGN §1.3)
        // — swapping to grey makes a disabled pill read as a different chip (R52).
        color: style.color,
        border: style.border,
        cursor: disabled ? 'default' : 'pointer',
        opacity: (disabled || loading) ? 0.6 : 1,
        ...pillStyle,
        ...styleProp,
      }}
      disabled={disabled || loading}
      onMouseEnter={(e) => {
        if (!disabled && !loading) {
          e.currentTarget.style.backgroundColor = style.hoverBg
        }
      }}
      onMouseLeave={(e) => {
        if (!disabled && !loading) {
          e.currentTarget.style.backgroundColor = style.backgroundColor
        }
      }}
      {...props}
    >
      {/* Fixed 16×16 icon slot (BUTTON_DESIGN §1.4 / §3.1): holds the icon at
          rest and the spinner while loading. Because the box is fixed, the
          icon↔spinner swap never moves the label. Only rendered for pill size
          when there is an icon or a loading state; legacy sizes keep the old
          inline-spinner-then-children layout. */}
      {isPill && (icon || loading) ? (
        <span
          aria-hidden={loading ? 'true' : undefined}
          style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 'var(--control-icon-slot)', height: 'var(--control-icon-slot)', flex: 'none',
          }}
        >
          {loading ? <Spinner pill /> : icon}
        </span>
      ) : null}
      {!isPill && loading && <Spinner />}
      {children}
    </button>
  )
}

// Inline spinner. For the pill icon-slot it is a 14px glyph (matching
// --control-icon); for legacy sizes it keeps the original 4×4 margin layout.
function Spinner({ pill = false }) {
  return (
    <svg
      className={pill ? 'animate-spin' : 'animate-spin -ml-1 mr-2 h-4 w-4'}
      style={pill ? { width: 'var(--control-icon)', height: 'var(--control-icon)' } : undefined}
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
    </svg>
  )
}
