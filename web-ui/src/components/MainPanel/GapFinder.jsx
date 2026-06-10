import { useState } from 'react'
import { getCheckGaps, addReferenceToCheck, getCitationRenumberPreview } from '../../utils/api'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { openExternal, isTauri } from '../../utils/tauriBridge'
import Button from '../common/Button'
import IconButton from '../common/IconButton'
import LabelSizer from '../common/LabelSizer'

// Pre-run trigger labels — longest reserves the width so the analyzing swap
// doesn't jump (BUTTON_DESIGN §3.1).
const GAP_LABELS = ['Did you miss these?', 'Analyzing co-citations…']

const SEARCH_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="11" y1="8" x2="11" y2="14" /><line x1="8" y1="11" x2="14" y2="11" /></svg>
)
const CHEVRON_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
)

/**
 * "Did you miss these?" — advisory gap-finder. Surfaces works frequently
 * co-cited by the bibliography's OWN references but absent from it (OpenAlex
 * referenced_works co-citation). Real data only: nothing is invented, and only
 * works OpenAlex resolves to a real title are shown. Framed as a discovery aid,
 * never as "required" citations.
 */
export default function GapFinder({ checkId, references }) {
  const [state, setState] = useState({ loading: false, data: null, error: null })
  // All hooks declared BEFORE the early return so the hook count is stable when
  // `hasDoi` flips (e.g. removing the last DOI-bearing reference) — otherwise
  // React #310 crashes the page. (rules-of-hooks)
  const [added, setAdded] = useState({})       // key -> 'adding'|'done'|'error'
  const [info, setInfo] = useState({})         // key -> { insertedIndex }
  const [preview, setPreview] = useState({})   // key -> { open, loading, data, error }
  const [diffOpen, setDiffOpen] = useState({}) // key -> bool: per-preview "show renumbering" detail toggle
  const [collapsed, setCollapsed] = useState(false) // collapse the results panel
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
    } catch {
      setAdded((a) => ({ ...a, [k]: 'error' }))
    }
  }

  const d = state.data
  const suggestions = Array.isArray(d?.suggestions) ? d.suggestions : []
  const doiLink = (doi) => `https://doi.org/${doi}`

  // Render a marker string with the digit runs that actually changed (>= the
  // insertion number) tinted in the accent colour, so the eye lands on the part
  // that renumbers. Real-data only: we tint by comparing the backend's matched
  // numbers against new_printed_number — never inventing positions.
  const renderMarker = (markerStr, changedNums, highlight) => {
    const text = String(markerStr ?? '')
    const nums = new Set((changedNums || []).map((n) => String(n)))
    const parts = text.split(/(\d+)/) // keep the digit runs as captured groups
    return parts.map((part, idx) => {
      const isChanged = /^\d+$/.test(part) && nums.has(String(parseInt(part, 10)))
      if (isChanged && highlight) {
        return <span key={idx} style={{ color: 'var(--color-accent)', fontWeight: 700 }}>{part}</span>
      }
      return <span key={idx}>{part}</span>
    })
  }

  return (
    <div className="flex flex-col" style={{ gap: 'var(--control-caption-gap)' }}>
      {!d && (
        <div>
          <Button size="pill" variant="outline" onClick={run} loading={state.loading} icon={SEARCH_ICON}
            title="Find works frequently co-cited by your references but missing from your bibliography">
            <LabelSizer candidates={GAP_LABELS}>{state.loading ? 'Analyzing co-citations…' : 'Did you miss these?'}</LabelSizer>
          </Button>
        </div>
      )}
      {state.error && <div className="text-xs" style={{ color: 'var(--color-error)' }}>{state.error}</div>}
      {d && suggestions.length > 0 && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          {/* Fixed-height (28px) header row: only the chevron rotates, the title
              text is constant — no ▸ show/▾ hide text reflow (BUTTON_DESIGN §3.3). */}
          <div className="flex items-center justify-between gap-2" style={{ height: 'var(--control-h)' }}>
            <button type="button" onClick={() => setCollapsed((c) => !c)}
              className="flex-1 flex items-center text-left rc-control"
              style={{ fontWeight: 700, color: 'var(--color-text-primary)', background: 'transparent', border: 'none' }}
              aria-expanded={!collapsed}>
              <span>{suggestions.length} work{suggestions.length === 1 ? '' : 's'} your references cite that you might add</span>
            </button>
            <IconButton chevron rotated={!collapsed} onClick={() => setCollapsed((c) => !c)}
              aria-expanded={!collapsed} title={collapsed ? 'Show' : 'Hide'}
              style={{ color: 'var(--color-text-muted)' }}>
              {CHEVRON_ICON}
            </IconButton>
          </div>
          {/* Non-reflowing grid-row expand: the header above stays put while the
              list reveals (BUTTON_DESIGN §3.3). */}
          <div className={`rc-collapse${collapsed ? ' rc-collapsed' : ''}`}>
          <div className="rc-collapse-inner">
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
                {s.resolved && s.openalex_url && (
                  <a href={s.openalex_url} onClick={(e) => { if (isTauri()) { e.preventDefault(); openExternal(s.openalex_url) } }}
                    target="_blank" rel="noopener noreferrer" className="ml-1.5 text-xs" style={{ color: 'var(--color-success)' }}
                    title="Verified: a real OpenAlex record (not AI-generated)">✓ OpenAlex ↗</a>
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
                          {pv.data && (() => {
                            const markers = pv.data.shifted_markers || []
                            const shiftCount = pv.data.shifted_count || markers.length
                            const insertAt = pv.data.new_printed_number // 1-based printed position the new ref takes
                            const numericChanges = !pv.data.abstained && markers.length > 0
                            const showDiff = diffOpen[k] !== false // default open when there are changes
                            return (
                            <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                              {/* List-level BEFORE -> AFTER: where the new reference lands. */}
                              <div className="rounded" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', overflow: 'hidden' }}>
                                <div className="grid" style={{ gridTemplateColumns: '1fr 16px 1fr' }}>
                                  <div className="px-2 py-1" style={{ borderRight: '1px solid var(--color-border)' }}>
                                    <div style={{ color: 'var(--color-text-muted)', fontWeight: 700, fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Before</div>
                                    <div className="mt-0.5" style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>
                                      {insertAt ? `…[${Math.max(1, insertAt - 1)}] (last reference)` : '(end of reference list)'}
                                    </div>
                                  </div>
                                  <div className="flex items-center justify-center" style={{ color: 'var(--color-accent)', fontWeight: 700 }}>→</div>
                                  <div className="px-2 py-1">
                                    <div style={{ color: 'var(--color-text-muted)', fontWeight: 700, fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>After</div>
                                    <div className="mt-0.5" style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>
                                      {insertAt ? <>…[{Math.max(1, insertAt - 1)}], <span style={{ color: 'var(--color-accent)', fontWeight: 700 }}>[{insertAt}] new reference</span></> : <span style={{ color: 'var(--color-success, #22c55e)', fontWeight: 700 }}>+ new reference appended</span>}
                                    </div>
                                  </div>
                                </div>
                              </div>
                              {/* Inline-marker BEFORE -> AFTER pairs (only what the backend reports). */}
                              {numericChanges ? (
                                <div className="mt-1.5">
                                  <button type="button" onClick={() => setDiffOpen((o) => ({ ...o, [k]: !showDiff }))}
                                    className="flex items-center gap-1 text-xs" style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>
                                    <span style={{ color: 'var(--color-text-muted)' }}>{showDiff ? '▾' : '▸'}</span>
                                    {shiftCount} inline marker{shiftCount === 1 ? '' : 's'} renumber
                                  </button>
                                  {showDiff && (
                                    <div className="mt-1 rounded" style={{ border: '1px solid var(--color-border)', overflow: 'hidden' }}>
                                      <div className="grid" style={{ gridTemplateColumns: '1fr 16px 1fr', background: 'var(--color-bg-secondary)' }}>
                                        <div className="px-2 py-0.5" style={{ color: 'var(--color-text-muted)', fontWeight: 700, fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.04em', borderRight: '1px solid var(--color-border)' }}>Before</div>
                                        <div />
                                        <div className="px-2 py-0.5" style={{ color: 'var(--color-text-muted)', fontWeight: 700, fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>After</div>
                                      </div>
                                      {markers.slice(0, 8).map((sm, mi) => {
                                        const changed = sm.numbers || []
                                        const changedAfter = changed.map((n) => n + 1)
                                        return (
                                          <div key={mi} className="grid" style={{ gridTemplateColumns: '1fr 16px 1fr', borderTop: '1px solid var(--color-border)', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>
                                            <div className="px-2 py-0.5" style={{ borderRight: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>{renderMarker(sm.marker, changed, false)}</div>
                                            <div className="flex items-center justify-center" style={{ color: 'var(--color-text-muted)' }}>→</div>
                                            <div className="px-2 py-0.5">{renderMarker(sm.new_marker, changedAfter, true)}</div>
                                          </div>
                                        )
                                      })}
                                      {markers.length > 8 && <div className="px-2 py-0.5" style={{ color: 'var(--color-text-muted)', borderTop: '1px solid var(--color-border)' }}>+{markers.length - 8} more marker{markers.length - 8 === 1 ? '' : 's'}…</div>}
                                    </div>
                                  )}
                                </div>
                              ) : (
                                <div className="mt-1.5" style={{ color: 'var(--color-text-muted)' }}>
                                  Existing inline citation markers are unchanged{pv.data.scheme && pv.data.scheme !== 'numeric' ? ` (${pv.data.scheme} style — renumbering not applicable)` : ''}.
                                </div>
                              )}
                              <div className="mt-1.5" style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                                Your document/PDF is not edited — only the reference list is updated. Add the inline citation in your manuscript yourself.
                              </div>
                              <div className="mt-1.5 flex items-center gap-2">
                                <Button size="pill" variant="primary" onClick={() => addToRefs(s, i)}
                                  loading={st === 'adding'} disabled={st === 'adding'}>
                                  <LabelSizer candidates={['Confirm add', 'Adding…']}>{st === 'adding' ? 'Adding…' : 'Confirm add'}</LabelSizer>
                                </Button>
                                <button type="button" onClick={() => closePreview(k)} className="text-xs underline" style={{ color: 'var(--color-text-muted)' }}>Cancel</button>
                              </div>
                            </div>
                            )
                          })()}
                        </div>
                      )}
                    </>
                  )
                })()}
              </li>
            ))}
          </ul>
          <div className="text-xs mt-1.5" style={{ color: 'var(--color-text-muted)' }}>
            Advisory only (OpenAlex co-citation). Each is a real OpenAlex-resolved work cited by your own references — not AI-generated. Judge relevance yourself.
          </div>
          </div>
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
