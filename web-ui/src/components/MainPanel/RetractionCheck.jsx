import { useState } from 'react'
import { createPortal } from 'react-dom'
import { getCheckRetractions } from '../../utils/api'
import { openExternal, isTauri } from '../../utils/tauriBridge'
import Button from '../common/Button'
import LabelSizer from '../common/LabelSizer'
import { useActionGrid } from './ActionPanelGrid'

const GRID_ID = 'retractions'

// Every label this control can show — the longest decides the reserved width so
// the rest↔checking↔result swap never resizes the button (BUTTON_DESIGN §3.1).
const RETRACTION_LABELS = [
  'Check for retractions',
  'Checking retractions…',
  'No retractions — re-check',
  '99 retracted — re-check',
]

// 14px action glyphs (BUTTON_DESIGN §1.4): refresh after a check, crossed-circle
// before. Rendered into the Button's fixed 16×16 icon slot.
const REFRESH_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M23 4v6h-6" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" /></svg>
)
const CROSS_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="4.9" y1="4.9" x2="19.1" y2="19.1" /></svg>
)

/**
 * On-demand "are any cited papers retracted?" check, using OpenAlex's real
 * is_retracted flag (backend /check/:id/retractions). Honest by construction:
 * only DOIs OpenAlex marks retracted are flagged; refs with no DOI or not
 * indexed are reported as such, never as "clean".
 */
export default function RetractionCheck({ checkId, references }) {
  const [state, setState] = useState({ loading: false, data: null, error: null })
  // Grid coordinator (null when rendered standalone / in tests → legacy layout).
  // Called before the early return so the hook order is stable (rules-of-hooks).
  const grid = useActionGrid()
  const hasDoi = Array.isArray(references) && references.some((r) => r?.doi || r?.verified_doi)
  if (!checkId || checkId <= 0 || !hasDoi) return null

  const run = async () => {
    setState({ loading: true, data: null, error: null })
    try {
      const res = await getCheckRetractions(checkId)
      setState({ loading: false, data: res.data, error: null })
    } catch (e) {
      setState({ loading: false, data: null, error: e?.response?.data?.detail || e?.message || 'Retraction check failed' })
    }
  }

  const d = state.data
  const results = Array.isArray(d?.results) ? d.results : []
  const retracted = results.filter((r) => r.status === 'retracted')
  const noDoi = results.filter((r) => r.status === 'no_doi').length
  const unknown = results.filter((r) => r.status === 'unknown').length
  const withDoi = (typeof d?.with_doi === 'number') ? d.with_doi : results.filter((r) => r.doi).length
  const doiLink = (doi) => `https://doi.org/${doi}`

  const checked = !!d
  const clean = checked && retracted.length === 0
  // The button stays clickable after a check so you can re-run it (each click
  // re-queries OpenAlex live). Its colour itself reports the status: green on a
  // clean result, red if any retraction was found — routed through the shared
  // status-* variants so border/fill come from tokens and geometry never changes
  // across rest/clean/retracted/loading (BUTTON_DESIGN §3.1, R52).
  const variant = !checked ? 'outline' : clean ? 'status-success' : 'status-error'
  const btnLabel = state.loading
    ? 'Checking retractions…'
    : !checked
      ? 'Check for retractions'
      : clean
        ? 'No retractions — re-check'
        : `${retracted.length} retracted — re-check`

  // In the 2×2 action grid, clicking the pill runs the check AND opens this
  // panel's details in the shared full-width region below the grid.
  const onTrigger = () => { run(); if (grid) grid.open(GRID_ID) }

  const trigger = (
    <Button size="pill" variant={variant} onClick={onTrigger} loading={state.loading}
      icon={checked ? REFRESH_ICON : CROSS_ICON}
      className={grid ? 'rc-grid-trigger' : ''}
      title="Check cited DOIs against OpenAlex for retractions — runs again each click">
      <LabelSizer candidates={RETRACTION_LABELS}>{btnLabel}</LabelSizer>
    </Button>
  )

  const details = (
    <>
      {state.error && <div className="text-xs" style={{ color: 'var(--color-error)' }}>{state.error}</div>}
      {d && retracted.length > 0 && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'var(--status-error-fill)', border: '1px solid var(--color-error, #ef4444)' }}>
          <div style={{ fontWeight: 700, color: 'var(--color-error, #ef4444)' }}>
            {retracted.length} cited reference{retracted.length === 1 ? ' appears' : 's appear'} to be retracted
          </div>
          <ul className="mt-1.5 space-y-1">
            {retracted.map((r, i) => (
              <li key={`${r.index}-${r.doi || i}`} style={{ color: 'var(--color-text-primary)' }}>
                <span style={{ color: 'var(--color-text-muted)' }}>[{r.index}]</span> {r.title || r.openalex_title || r.doi}
                {r.doi && (
                  <a href={doiLink(r.doi)} onClick={(e) => { if (isTauri()) { e.preventDefault(); openExternal(doiLink(r.doi)) } }}
                    target="_blank" rel="noopener noreferrer" className="ml-1.5 underline" style={{ color: 'var(--color-accent)' }}>DOI ↗</a>
                )}
              </li>
            ))}
          </ul>
          <div className="text-xs mt-1.5" style={{ color: 'var(--color-text-muted)' }}>Source: OpenAlex. Verify on the publisher page before acting.</div>
        </div>
      )}
      {d && retracted.length === 0 && (
        /* The clean-state line is a caption (BUTTON_DESIGN §2.2): plain muted
           text directly under the pill, no border/background card. */
        <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
          No retractions found in OpenAlex for the {withDoi} reference{withDoi === 1 ? '' : 's'} with a DOI
          {noDoi > 0 ? ` · ${noDoi} had no DOI to check` : ''}
          {unknown > 0 ? ` · ${unknown} not indexed by OpenAlex` : ''}.
        </div>
      )}
    </>
  )

  const hasDetails = !!(state.error || d)

  // Grid mode: trigger lives in its 2×2 cell; details portal full-width below.
  if (grid) {
    return (
      <div className="rc-grid-cell">
        {trigger}
        {grid.isOpen(GRID_ID) && hasDetails && grid.host
          ? createPortal(<div className="rc-action-details flex flex-col" style={{ gap: 'var(--control-caption-gap)' }}>{details}</div>, grid.host)
          : null}
      </div>
    )
  }

  // Legacy stacked layout (unchanged): pill then caption/card directly under it.
  return (
    <div className="flex flex-col" style={{ gap: 'var(--control-caption-gap)' }}>
      <div>{trigger}</div>
      {details}
    </div>
  )
}
