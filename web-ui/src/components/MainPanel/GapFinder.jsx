import { useState } from 'react'
import { getCheckGaps, addReferenceToCheck } from '../../utils/api'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { openExternal, isTauri } from '../../utils/tauriBridge'

/**
 * "Did you miss these?" — advisory gap-finder. Surfaces works frequently
 * co-cited by the bibliography's OWN references but absent from it (OpenAlex
 * referenced_works co-citation). Real data only: nothing is invented, and only
 * works OpenAlex resolves to a real title are shown. Framed as a discovery aid,
 * never as "required" citations.
 */
export default function GapFinder({ checkId, references }) {
  const [state, setState] = useState({ loading: false, data: null, error: null })
  const hasDoi = Array.isArray(references) && references.some((r) => r?.doi || r?.verified_doi)
  if (!checkId || checkId <= 0 || !hasDoi) return null

  const run = async () => {
    setState({ loading: true, data: null, error: null })
    try {
      const res = await getCheckGaps(checkId)
      setState({ loading: false, data: res.data, error: null })
    } catch (e) {
      setState({ loading: false, data: null, error: e?.response?.data?.detail || e?.message || 'Gap analysis failed' })
    }
  }

  // Per-suggestion "add to references" state: key -> 'adding'|'done'|'error'.
  const [added, setAdded] = useState({})
  const keyOf = (s, i) => s.openalex_id || s.doi || `i${i}`
  const addToRefs = async (s, i) => {
    const k = keyOf(s, i)
    setAdded((a) => ({ ...a, [k]: 'adding' }))
    try {
      await addReferenceToCheck(checkId, {
        title: s.title,
        year: s.year,
        doi: s.doi || undefined,
        cited_url: s.doi ? `https://doi.org/${s.doi}` : undefined,
      })
      // Refresh the check so the new reference appears in the list.
      await useHistoryStore.getState().selectCheck?.(checkId, { force: true })
      setAdded((a) => ({ ...a, [k]: 'done' }))
    } catch (e) {
      setAdded((a) => ({ ...a, [k]: 'error' }))
    }
  }

  const d = state.data
  const suggestions = Array.isArray(d?.suggestions) ? d.suggestions : []
  const doiLink = (doi) => `https://doi.org/${doi}`

  return (
    <div className="mb-3">
      {!d && (
        <button type="button" onClick={run} disabled={state.loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border"
          style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-primary)', borderColor: 'var(--color-border)', opacity: state.loading ? 0.6 : 1 }}
          title="Find works frequently co-cited by your references but missing from your bibliography">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="11" y1="8" x2="11" y2="14" /><line x1="8" y1="11" x2="14" y2="11" /></svg>
          {state.loading ? 'Analyzing co-citations…' : 'Did you miss these?'}
        </button>
      )}
      {state.error && <div className="text-xs mt-1" style={{ color: 'var(--color-error)' }}>{state.error}</div>}
      {d && suggestions.length > 0 && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <div style={{ fontWeight: 700, color: 'var(--color-text-primary)' }}>
            {suggestions.length} work{suggestions.length === 1 ? '' : 's'} your references cite that you might add
          </div>
          <ul className="mt-1.5 space-y-1.5">
            {suggestions.map((s, i) => (
              <li key={`${s.openalex_id}-${i}`} style={{ color: 'var(--color-text-primary)' }}>
                <span>{s.title}</span>
                <span className="ml-1.5 text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  {s.year ? `${s.year} · ` : ''}co-cited by {s.co_citations} of your refs
                  {typeof s.cited_by_count === 'number' ? ` · ${s.cited_by_count.toLocaleString()} citations` : ''}
                </span>
                {s.doi && (
                  <a href={doiLink(s.doi)} onClick={(e) => { if (isTauri()) { e.preventDefault(); openExternal(doiLink(s.doi)) } }}
                    target="_blank" rel="noopener noreferrer" className="ml-1.5 underline text-xs" style={{ color: 'var(--color-accent)' }}>DOI ↗</a>
                )}
                {(() => {
                  const st = added[keyOf(s, i)]
                  if (st === 'done') return <span className="ml-1.5 text-xs font-medium" style={{ color: 'var(--color-success)' }}>✓ Added</span>
                  if (st === 'error') return <span className="ml-1.5 text-xs" style={{ color: 'var(--color-error)' }}>add failed</span>
                  return (
                    <button type="button" onClick={() => addToRefs(s, i)} disabled={st === 'adding'}
                      className="ml-1.5 text-xs underline" style={{ color: 'var(--color-accent)', opacity: st === 'adding' ? 0.6 : 1 }}
                      title="Add this work to the reference list and re-verify">
                      {st === 'adding' ? 'Adding…' : '+ Add to references'}
                    </button>
                  )
                })()}
              </li>
            ))}
          </ul>
          <div className="text-xs mt-1.5" style={{ color: 'var(--color-text-muted)' }}>
            Advisory only (OpenAlex co-citation). These are not required citations — judge relevance yourself.
          </div>
        </div>
      )}
      {d && suggestions.length === 0 && (
        <div className="rounded-lg p-2.5 text-xs" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
          {d.note || `No frequently co-cited works are missing from your ${d.checked} DOI-bearing reference${d.checked === 1 ? '' : 's'}.`}
        </div>
      )}
    </div>
  )
}
