import { useState } from 'react'
import { openExternal, isTauri } from '../../utils/tauriBridge'
import { addSeenReference } from '../../utils/api'

/**
 * "Additional Info" row under a reference: surfaces the NEW article-intelligence
 * signals (abstract, claim/TL;DR, preprint flag, open-access full text) and the
 * "Add to Library" action. Every pill is real-data-gated — it renders only when
 * its backing enrichment field is actually present, and the component renders
 * nothing when there's no real signal. Citation/reference counts are shown by
 * ReferenceEnrichmentStrip, so they are intentionally NOT duplicated here.
 */
function Pill({ onClick, href, title, color, children }) {
  const style = {
    display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 9px',
    borderRadius: 9999, fontSize: 11, fontWeight: 600, lineHeight: 1.6,
    border: '1px solid var(--color-border)',
    cursor: (onClick || href) ? 'pointer' : 'default',
    color: color || 'var(--color-text-secondary)',
    background: 'var(--color-bg-primary)', textDecoration: 'none',
  }
  if (href) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" title={title} style={style}
        onClick={(e) => { if (isTauri()) { e.preventDefault(); openExternal(href) } }}>{children}</a>
    )
  }
  return <button type="button" onClick={onClick} title={title} style={style}>{children}</button>
}

export default function AdditionalInfoBar({ reference, checkId }) {
  const e = (reference && reference.enrichment) || {}
  const [panel, setPanel] = useState(null)  // 'abstract' | 'tldr' | null
  const [lib, setLib] = useState(null)      // null | 'adding' | 'done' | 'error'
  const [libN, setLibN] = useState(0)

  const oaUrl = e.oa_pdf_url || (e.links && e.links.oa_pdf) || null
  const toggle = (p) => setPanel((cur) => (cur === p ? null : p))

  const canCache = !!(reference?.doi || reference?.verified_doi || reference?.arxiv_id || reference?.title)
  const addToLibrary = async () => {
    if (lib === 'adding') return
    setLib('adding')
    try {
      const res = await addSeenReference(reference, checkId || null, null)
      setLibN(res?.data?.times_seen || 1)
      setLib(res?.data?.added ? 'done' : 'error')
    } catch {
      setLib('error')
    }
  }

  const badges = []
  if (e.abstract) badges.push(<Pill key="ab" onClick={() => toggle('abstract')} title="Show the abstract">Abstract</Pill>)
  if (e.tldr) badges.push(<Pill key="cl" onClick={() => toggle('tldr')} title="One-line claim (Semantic Scholar TL;DR)" color="var(--color-warning)">Claim</Pill>)
  if (e.is_preprint) badges.push(<Pill key="pp" title="Preprint / posted content (not yet a journal article)" color="var(--color-warning)">Preprint</Pill>)

  const actions = []
  if (oaUrl) actions.push(<Pill key="vp" href={oaUrl} title="Open the open-access full text / PDF" color="var(--color-accent)">View full text ↗</Pill>)
  if (canCache) {
    actions.push(
      <Pill key="lib" onClick={addToLibrary}
        title="Add this reference (with its fetched data) to your library cache"
        color={lib === 'done' ? 'var(--color-success)' : lib === 'error' ? 'var(--color-error)' : undefined}>
        {lib === 'done' ? `✓ In Library${libN > 1 ? ` · ${libN}×` : ''}` : lib === 'adding' ? 'Adding…' : lib === 'error' ? 'add failed' : '+ Add to Library'}
      </Pill>
    )
  }

  if (badges.length === 0 && actions.length === 0) return null

  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {badges.length > 0 && (
          <span className="text-xs font-medium mr-0.5" style={{ color: 'var(--color-text-muted)' }}>Additional Info:</span>
        )}
        {badges}
        {actions}
      </div>
      {panel === 'abstract' && e.abstract && (
        <div className="mt-1.5 text-xs rounded-md p-2.5" style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)', lineHeight: 1.55 }}>
          {e.abstract}
        </div>
      )}
      {panel === 'tldr' && e.tldr && (
        <div className="mt-1.5 text-xs rounded-md p-2.5" style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', color: 'var(--color-text-primary)', lineHeight: 1.55 }}>
          <span style={{ fontWeight: 700 }}>Claim (TL;DR): </span>{e.tldr}
          <div className="mt-1" style={{ color: 'var(--color-text-muted)' }}>Machine-generated summary (Semantic Scholar) — verify against the article.</div>
        </div>
      )}
    </div>
  )
}
