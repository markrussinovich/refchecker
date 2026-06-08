import { useState } from 'react'
import { getCitationIntegrity } from '../../utils/api'

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
  'body too short': 'Not enough body text to analyze.',
  'empty input': 'No body text or references available to analyze.',
}

export default function CitationIntegrity({ checkId }) {
  const [state, setState] = useState({ loading: false, data: null, error: null })
  const [open, setOpen] = useState(true)
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
  // re-analyses live). Its colour itself reports the status: green when the
  // numbering is consistent, amber when issues were found, neutral otherwise.
  const btnStyle = !checked || abstained
    ? { background: 'var(--color-bg-secondary)', color: 'var(--color-text-primary)', borderColor: 'var(--color-border)' }
    : clean
      ? { background: 'rgba(16,185,129,0.12)', color: 'var(--color-success, #10b981)', borderColor: 'var(--color-success, #10b981)' }
      : { background: 'rgba(245,158,11,0.14)', color: 'var(--color-warning, #f59e0b)', borderColor: 'var(--color-warning, #f59e0b)' }
  const btnLabel = state.loading
    ? 'Checking numbering…'
    : !checked
      ? 'Check citation numbering'
      : abstained
        ? 'Numbering n/a — re-check'
        : clean
          ? 'Numbering consistent — re-check'
          : `${issues.length} numbering issue${issues.length === 1 ? '' : 's'} — re-check`

  return (
    <div className="mb-3 flex flex-wrap items-start gap-2" style={{ flexBasis: '100%', width: '100%' }}>
      <div className="inline-flex items-stretch">
        <button type="button" onClick={run} disabled={state.loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border"
          style={{
            ...btnStyle,
            opacity: state.loading ? 0.6 : 1,
            cursor: state.loading ? 'default' : 'pointer',
            borderRadius: checked ? '6px 0 0 6px' : '6px',
            borderRight: checked ? 'none' : undefined,
            transition: 'background 120ms ease, color 120ms ease, border-color 120ms ease',
          }}
          title="Check inline-citation numbering for gaps, out-of-order, duplicates, undefined or uncited references — runs again each click">
          {checked && !state.loading ? (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M23 4v6h-6" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" /></svg>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7V4h16v3" /><path d="M9 20h6" /><path d="M12 4v16" /></svg>
          )}
          {btnLabel}
        </button>
        {checked && (
          <button type="button" onClick={() => setOpen((o) => !o)}
            className="inline-flex items-center px-2 border text-xs font-medium"
            style={{
              ...btnStyle,
              borderRadius: '0 6px 6px 0',
              cursor: 'pointer',
              transition: 'background 120ms ease, color 120ms ease, border-color 120ms ease',
            }}
            aria-expanded={open}
            title={open ? 'Hide details' : 'Show details'}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 150ms ease' }}>
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
        )}
      </div>

      {state.error && (
        <div className="text-xs" style={{ color: 'var(--color-error)', flexBasis: '100%', width: '100%' }}>{state.error}</div>
      )}

      {d && open && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', flexBasis: '100%', width: '100%', maxHeight: 360, overflowY: 'auto' }}>
          <div className="flex items-center gap-2 flex-wrap">
            <span style={{ fontWeight: 700, color: 'var(--color-text-primary)' }}>Citation numbering</span>
            <span className="px-2 py-0.5 rounded-full text-xs font-semibold"
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
    </div>
  )
}
