import { useState } from 'react'
import { getCheckRetractions } from '../../utils/api'
import { openExternal, isTauri } from '../../utils/tauriBridge'

/**
 * On-demand "are any cited papers retracted?" check, using OpenAlex's real
 * is_retracted flag (backend /check/:id/retractions). Honest by construction:
 * only DOIs OpenAlex marks retracted are flagged; refs with no DOI or not
 * indexed are reported as such, never as "clean".
 */
export default function RetractionCheck({ checkId, references }) {
  const [state, setState] = useState({ loading: false, data: null, error: null })
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

  return (
    <div className="mb-3">
      {!d && (
        <button type="button" onClick={run} disabled={state.loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border"
          style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-primary)', borderColor: 'var(--color-border)', opacity: state.loading ? 0.6 : 1 }}
          title="Check cited DOIs against OpenAlex for retractions">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="4.9" y1="4.9" x2="19.1" y2="19.1" /></svg>
          {state.loading ? 'Checking retractions…' : 'Check for retractions'}
        </button>
      )}
      {state.error && <div className="text-xs mt-1" style={{ color: 'var(--color-error)' }}>{state.error}</div>}
      {d && retracted.length > 0 && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(239,68,68,0.10)', border: '1px solid var(--color-error, #ef4444)' }}>
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
        <div className="rounded-lg p-2.5 text-xs" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
          No retractions found in OpenAlex for the {withDoi} reference{withDoi === 1 ? '' : 's'} with a DOI
          {noDoi > 0 ? ` · ${noDoi} had no DOI to check` : ''}
          {unknown > 0 ? ` · ${unknown} not indexed by OpenAlex` : ''}.
        </div>
      )}
    </div>
  )
}
