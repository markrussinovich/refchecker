import { useState } from 'react'
import { getCheckGaps, addReferenceToCheck, getCitationRenumberPreview } from '../../utils/api'
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
  const [info, setInfo] = useState({})       // key -> { insertedIndex }
  const [preview, setPreview] = useState({}) // key -> { open, loading, data, error }
  const keyOf = (s, i) => s.openalex_id || s.doi || `i${i}`

  // Step 1: show a read-only "document changes" preview before committing. The
  // new reference is APPENDED, so the backend reports how (if at all) existing
  // inline markers would renumber — honestly abstaining for non-numeric styles.
  const openPreview = async (s, i) => {
    const k = keyOf(s, i)
    setPreview((p) => ({ ...p, [k]: { open: true, loading: true, data: null, error: null } }))
    try {
      const res = await getCitationRenumberPreview(checkId) // omit insert_at => append
      setPreview((p) => ({ ...p, [k]: { open: true, loading: false, data: res.data, error: null } }))
    } catch (e) {
      setPreview((p) => ({ ...p, [k]: { open: true, loading: false, data: null, error: e?.response?.data?.detail || e?.message || 'Preview unavailable' } }))
    }
  }
  const closePreview = (k) => setPreview((p) => ({ ...p, [k]: { ...(p[k] || {}), open: false } }))

  // Step 2: commit. Uses the authoritative inserted_index/renumbering from the
  // write path to report the real list change, then refreshes the check.
  const addToRefs = async (s, i) => {
    const k = keyOf(s, i)
    setAdded((a) => ({ ...a, [k]: 'adding' }))
    try {
      const res = await addReferenceToCheck(checkId, {
        title: s.title,
        year: s.year,
        doi: s.doi || undefined,
        cited_url: s.doi ? `https://doi.org/${s.doi}` : undefined,
      })
      setInfo((m) => ({ ...m, [k]: { insertedIndex: res?.data?.inserted_index } }))
      // Refresh the check so the new reference appears in the list.
      await useHistoryStore.getState().selectCheck?.(checkId, { force: true })
      setAdded((a) => ({ ...a, [k]: 'done' }))
      closePreview(k)
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
                  const k = keyOf(s, i)
                  const st = added[k]
                  const pv = preview[k]
                  if (st === 'done') {
                    const n = info[k]?.insertedIndex
                    return <span className="ml-1.5 text-xs font-medium" style={{ color: 'var(--color-success)' }}>✓ Added{n ? ` as [${n}]` : ''}</span>
                  }
                  if (st === 'error') return <span className="ml-1.5 text-xs" style={{ color: 'var(--color-error)' }}>add failed</span>
                  return (
                    <>
                      {!(pv && pv.open) && (
                        <button type="button" onClick={() => openPreview(s, i)} disabled={st === 'adding'}
                          className="ml-1.5 text-xs underline" style={{ color: 'var(--color-accent)', opacity: st === 'adding' ? 0.6 : 1 }}
                          title="Preview the document changes, then add this work to the reference list">
                          {st === 'adding' ? 'Adding…' : '+ Add to references'}
                        </button>
                      )}
                      {pv && pv.open && (
                        <div className="mt-1.5 rounded-md p-2" style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)' }}>
                          {pv.loading && <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Checking document…</div>}
                          {pv.error && <div className="text-xs" style={{ color: 'var(--color-error)' }}>{pv.error}</div>}
                          {pv.data && (
                            <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                              <div className="rc-diff-row"><span className="rc-diff-added">+ new reference</span><span className="rc-diff-arrow">appended to the list</span></div>
                              {pv.data.abstained || !(pv.data.shifted_markers || []).length ? (
                                <div className="mt-1" style={{ color: 'var(--color-text-muted)' }}>
                                  Existing inline citation markers are unchanged{pv.data.scheme ? ` (${pv.data.scheme} style)` : ''}.
                                </div>
                              ) : (
                                <div className="mt-1">
                                  <div style={{ color: 'var(--color-text-muted)' }}>{pv.data.shifted_count} inline marker{pv.data.shifted_count === 1 ? '' : 's'} would shift:</div>
                                  {(pv.data.shifted_markers || []).slice(0, 5).map((sm, mi) => (
                                    <div key={mi} className="rc-diff-row mt-0.5">
                                      <span className="rc-diff-old">{sm.marker}</span><span className="rc-diff-arrow">→</span><span className="rc-diff-new">{sm.new_marker}</span>
                                    </div>
                                  ))}
                                  {pv.data.shifted_count > 5 && <div style={{ color: 'var(--color-text-muted)' }}>+{pv.data.shifted_count - 5} more…</div>}
                                </div>
                              )}
                              <div className="mt-1.5" style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                                Your document/PDF is not edited — only the reference list is updated. Add the inline citation in your manuscript yourself.
                              </div>
                              <div className="mt-1.5 flex items-center gap-2">
                                <button type="button" onClick={() => addToRefs(s, i)} disabled={st === 'adding'}
                                  className="px-2 py-0.5 rounded text-xs font-medium" style={{ background: 'var(--color-accent)', color: '#fff', opacity: st === 'adding' ? 0.6 : 1 }}>
                                  {st === 'adding' ? 'Adding…' : 'Confirm add'}
                                </button>
                                <button type="button" onClick={() => closePreview(k)} className="text-xs underline" style={{ color: 'var(--color-text-muted)' }}>Cancel</button>
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </>
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
