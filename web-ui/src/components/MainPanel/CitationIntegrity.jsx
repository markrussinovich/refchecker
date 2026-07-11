import { useState } from 'react'
import { createPortal } from 'react-dom'
import { getCitationIntegrity } from '../../utils/api'
import Button from '../common/Button'
import SplitButton from '../common/SplitButton'
import LabelSizer from '../common/LabelSizer'
import { useActionGrid } from './ActionPanelGrid'

const GRID_ID = 'citation'

// Every label the main segment can show — longest reserves the width so no swap
// between rest↔checking↔result reflows (BUTTON_DESIGN §3.1).
const CITATION_LABELS = [
  'Check citation numbering',
  'Checking numbering…',
  'Numbering consistent — re-check',
  'Numbering n/a — re-check',
  '99 numbering issues — re-check',
]

const REFRESH_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M23 4v6h-6" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" /></svg>
)
const LIST_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7V4h16v3" /><path d="M9 20h6" /><path d="M12 4v16" /></svg>
)

/**
 * Inline-citation numbering integrity badge. Parses the paper body for its
 * citation scheme and flags numbering issues (gaps, out-of-order, duplicates,
 * undefined markers, uncited references). Honest by construction: when the
 * scheme is unclear/mixed (e.g. author-year) it ABSTAINS — no false issues.
 *
 * The trigger is a button that always stays clickable (like the retraction
 * check): each click re-runs the analysis live. Its colour reports the status
 * — green/'consistent' when clean, amber when issues are found, neutral when
 * the check abstains. The result (which can get large) lives in a collapsible
 * panel rendered on its own full-width row, so it never pushes the sibling
 * controls around.
 */
const SEV_COLOR = { high: 'var(--color-error)', medium: 'var(--color-warning)', low: 'var(--color-text-secondary)' }
// Humanised messages for the backend's abstain_reason (so the UI explains WHY
// it abstained instead of a single generic line).
const ABSTAIN_MSG = {
  'author-year style has no numeric sequence': 'Author-year citation style detected — there is no numeric sequence to audit.',
  'mixed citation schemes': 'Mixed citation styles detected — not flagging to avoid false alarms.',
  'no recognizable scheme': 'No consistent numeric citation scheme detected — not flagging to avoid false alarms.',
  'too few resolved markers': 'Too few inline citation markers to audit the numbering reliably.',
  'reference list likely incomplete': 'The reference list looks incomplete relative to the citations — not flagging.',
  // Alphabetic-key scheme ([Knu97]/[ABC+20]) abstain reasons (R15).
  'too few resolved alpha-key markers': 'Too few alphabetic citation keys (e.g. [Knu97]) to audit reliably.',
  'alpha-key reference list not derivable': 'Alphabetic citation keys detected, but the reference list lacks the author/year data needed to validate them — not flagging.',
  'alpha-key reference list likely incomplete': 'The reference list looks incomplete relative to the alphabetic citation keys — not flagging.',
  'body too short': 'Not enough body text to analyze.',
  'empty input': 'No body text or references available to analyze.',
}

export default function CitationIntegrity({ checkId }) {
  const [state, setState] = useState({ loading: false, data: null, error: null })
  const [open, setOpen] = useState(true)
  // Grid coordinator (null when rendered standalone / in tests → legacy layout).
  // Called before the early return so the hook order is stable (rules-of-hooks).
  const grid = useActionGrid()
  if (!checkId || checkId <= 0) return null

  const run = async () => {
    setOpen(true)
    setState((s) => ({ loading: true, data: s.data, error: null }))
    try {
      const res = await getCitationIntegrity(checkId)
      setState({ loading: false, data: res.data, error: null })
    } catch (e) {
      setState({ loading: false, data: null, error: e?.response?.data?.detail || e?.message || 'Citation check failed' })
    }
  }

  const d = state.data
  const issues = Array.isArray(d?.issues) ? d.issues : []
  const badge = d?.badge || {}
  const color = badge.color || 'var(--color-text-muted)'

  const checked = !!d
  const abstained = checked && !!d.abstained
  const clean = checked && !abstained && issues.length === 0

  // The button stays clickable after a check so it can be re-run (each click
  // re-analyses live). Its colour itself reports the status, routed through the
  // shared status-* variants so border/fill come from tokens and geometry never
  // changes (BUTTON_DESIGN §3.1, R52): green when consistent, amber when issues
  // found, neutral (outline) before a check or when it abstains.
  const variant = (!checked || abstained) ? 'outline' : clean ? 'status-success' : 'status-warning'
  const btnLabel = state.loading
    ? 'Checking numbering…'
    : !checked
      ? 'Check citation numbering'
      : abstained
        ? 'Numbering n/a — re-check'
        : clean
          ? 'Numbering consistent — re-check'
          : `${issues.length} numbering issue${issues.length === 1 ? '' : 's'} — re-check`

  // In the 2×2 action grid the panel's open state is owned by the grid
  // coordinator (accordion); standalone it keeps its own `open` toggle.
  const isOpen = grid ? grid.isOpen(GRID_ID) : open
  const onMain = () => { run(); if (grid) grid.open(GRID_ID) }
  const onCaret = grid ? () => grid.toggle(GRID_ID) : () => setOpen((o) => !o)

  // Pre-check: a lone outline pill identical to the other action pills. Post-
  // check: the caret fades/slides in (SplitButton owns the radius transition so
  // the main segment's LEFT edge never moves) (BUTTON_DESIGN §3.2 option A).
  const mainButton = (
    <Button size="pill" variant={variant} onClick={onMain} loading={state.loading}
      icon={checked ? REFRESH_ICON : LIST_ICON}
      className={grid ? 'rc-grid-trigger' : ''}
      title="Check inline-citation numbering for gaps, out-of-order, duplicates, undefined or uncited references — runs again each click">
      <LabelSizer candidates={CITATION_LABELS}>{btnLabel}</LabelSizer>
    </Button>
  )

  const triggerRow = (
    <SplitButton
      main={mainButton}
      caret={checked}
      caretOpen={isOpen}
      onCaretToggle={onCaret}
      caretTitle={isOpen ? 'Hide details' : 'Show details'}
      fullWidth={!!grid}
    />
  )

  const detailsCard = (state.error || (d && isOpen)) ? (
    <>
      {state.error && (
        <div className="text-xs" style={{ color: 'var(--color-error)' }}>{state.error}</div>
      )}
      {d && isOpen && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', maxHeight: 360, overflowY: 'auto' }}>
          <div className="flex items-center gap-2 flex-wrap">
            <span style={{ fontWeight: 700, color: 'var(--color-text-primary)' }}>Citation numbering</span>
            <span className="px-2 py-0.5 rounded-[8px] text-xs font-semibold"
              style={{ color, background: 'var(--color-bg-tertiary)', border: `1px solid ${color}` }}>
              {badge.label || 'n/a'}
            </span>
            {d.scheme && !d.abstained && (
              <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>scheme: {d.scheme}</span>
            )}
            {d.ordering && !d.abstained && d.ordering.convention !== 'ambiguous' && (
              <span className="text-xs" title={d.ordering.reason}
                style={{ color: d.ordering.consistent === false ? 'var(--color-warning)' : 'var(--color-text-muted)' }}>
                {d.ordering.convention === 'alphabetical'
                  ? 'order: alphabetical ✓'
                  : d.ordering.convention === 'reverse-appearance'
                    ? 'order: reverse-appearance ✓'
                    : d.ordering.consistent
                      ? 'order: by appearance ✓'
                      : 'order: numbering doesn’t match ✗'}
              </span>
            )}
          </div>
          {d.abstained ? (
            <div className="text-xs mt-1.5" style={{ color: 'var(--color-text-muted)' }}>
              {!d.has_text
                ? 'No body text available to analyze.'
                : (ABSTAIN_MSG[d.abstain_reason] || 'Citation scheme could not be determined confidently (e.g. author-year or too few numeric markers) — not flagging to avoid false alarms.')}
            </div>
          ) : issues.length === 0 ? (
            <div className="text-xs mt-1.5" style={{ color: 'var(--color-success)' }}>
              No numbering issues found across {d?.counts?.total_markers ?? 0} inline citations.
            </div>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {issues.map((iss, i) => (
                <li key={i} className="flex items-start gap-2 text-xs" style={{ color: 'var(--color-text-primary)' }}>
                  <span style={{ color: SEV_COLOR[iss.severity] || 'var(--color-text-muted)', fontWeight: 700, flex: 'none' }}>
                    {iss.marker || iss.type}
                  </span>
                  <span style={{ color: 'var(--color-text-secondary)' }}>{iss.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  ) : null

  // Grid mode: SplitButton sits in its 2×2 cell; the details panel portals into
  // the shared full-width region below the grid when this panel is open.
  if (grid) {
    return (
      <div className="rc-grid-cell">
        {triggerRow}
        {grid.isOpen(GRID_ID) && detailsCard && grid.host
          ? createPortal(<div className="rc-action-details flex flex-col" style={{ gap: 'var(--control-caption-gap)' }}>{detailsCard}</div>, grid.host)
          : null}
      </div>
    )
  }

  // Legacy stacked layout (unchanged): split-button then its own full-width row.
  return (
    <div className="flex flex-col" style={{ gap: 'var(--control-caption-gap)', flexBasis: '100%', width: '100%' }}>
      <div>{triggerRow}</div>
      {detailsCard}
    </div>
  )
}
