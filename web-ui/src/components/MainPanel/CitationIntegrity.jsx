import { useState } from 'react'
import { getCitationIntegrity } from '../../utils/api'

/**
 * Inline-citation numbering integrity badge. Parses the paper body for its
 * citation scheme and flags numbering issues (gaps, out-of-order, duplicates,
 * undefined markers, uncited references). Honest by construction: when the
 * scheme is unclear/mixed (e.g. author-year) it ABSTAINS — no badge, no false
 * issues. On-demand (the parse needs the body text, which may extract once).
 */
const BADGE_BG = {
  '#22c55e': 'rgba(34,197,94,0.12)', '#84cc16': 'rgba(132,204,22,0.14)',
  '#f59e0b': 'rgba(245,158,11,0.14)', '#ef4444': 'rgba(239,68,68,0.12)',
}
const SEV_COLOR = { high: 'var(--color-error)', medium: 'var(--color-warning)', low: 'var(--color-text-secondary)' }

export default function CitationIntegrity({ checkId }) {
  const [state, setState] = useState({ loading: false, data: null, error: null })
  if (!checkId || checkId <= 0) return null

  const run = async () => {
    setState({ loading: true, data: null, error: null })
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

  return (
    <div className="mb-3">
      {!d && (
        <button type="button" onClick={run} disabled={state.loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border"
          style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-primary)', borderColor: 'var(--color-border)', opacity: state.loading ? 0.6 : 1 }}
          title="Check inline-citation numbering for gaps, out-of-order, duplicates, undefined or uncited references">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7V4h16v3" /><path d="M9 20h6" /><path d="M12 4v16" /></svg>
          {state.loading ? 'Checking numbering…' : 'Check citation numbering'}
        </button>
      )}
      {state.error && <div className="text-xs mt-1" style={{ color: 'var(--color-error)' }}>{state.error}</div>}
      {d && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <div className="flex items-center gap-2">
            <span style={{ fontWeight: 700, color: 'var(--color-text-primary)' }}>Citation numbering</span>
            <span className="px-2 py-0.5 rounded-full text-xs font-semibold"
              style={{ color, background: BADGE_BG[badge.color] || 'var(--color-bg-tertiary)', border: `1px solid ${color}` }}>
              {badge.label || 'n/a'}
            </span>
            {d.scheme && !d.abstained && (
              <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>scheme: {d.scheme}</span>
            )}
          </div>
          {d.abstained ? (
            <div className="text-xs mt-1.5" style={{ color: 'var(--color-text-muted)' }}>
              {!d.has_text ? 'No body text available to analyze.' : 'Citation scheme could not be determined confidently (e.g. author-year or too few numeric markers) — not flagging to avoid false alarms.'}
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
