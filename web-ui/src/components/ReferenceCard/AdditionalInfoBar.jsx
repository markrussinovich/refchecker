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

// Render an OpenAlex publication_date (an ISO "YYYY-MM-DD" string) as a
// human-readable "Published Oct 1, 2021" without timezone drift. We parse the
// parts directly instead of `new Date(str)` because the latter treats a bare
// date as UTC midnight and can render the previous day in negative-offset
// locales. Returns null when the value is absent or unparseable — never
// fabricates a date.
function formatPublicationDate(value) {
  if (!value || typeof value !== 'string') return null
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) {
    // Year-only or other shapes: surface a 4-digit year if present, else abstain.
    const y = value.match(/^(\d{4})\b/)
    return y ? y[1] : null
  }
  const [, y, mo, d] = m
  const dt = new Date(Number(y), Number(mo) - 1, Number(d))
  if (Number.isNaN(dt.getTime())) return null
  return dt.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export default function AdditionalInfoBar({ reference, checkId }) {
  const e = (reference && reference.enrichment) || {}
  const [panel, setPanel] = useState(null)  // 'abstract' | 'tldr' | null
  const [lib, setLib] = useState(null)      // null | 'adding' | 'done' | 'error'
  const [libN, setLibN] = useState(0)

  const oaUrl = e.oa_pdf_url || (e.links && e.links.oa_pdf) || null
  const toggle = (p) => setPanel((cur) => (cur === p ? null : p))

  // Real OpenAlex signals for the new badges. publication_date is an ISO
  // string; fields_of_study is an array of real OpenAlex concept names. Both
  // omit entirely when absent — no placeholders, no fabricated "description".
  const publishedLabel = formatPublicationDate(e.publication_date)
  const topics = Array.isArray(e.fields_of_study)
    ? e.fields_of_study.filter(t => typeof t === 'string' && t.trim())
    : []

  // Real verification state (not enrichment): show a live status pill only
  // while this reference is actually queued or being checked.
  const refStatus = reference && reference.status
  const statusPill = refStatus === 'checking'
    ? { label: 'Checking…', title: 'This reference is being verified', color: 'var(--color-accent)' }
    : refStatus === 'pending'
      ? { label: 'Pending', title: 'Waiting in the verification queue', color: 'var(--color-text-muted)' }
      : null

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
  if (statusPill) badges.push(<Pill key="st" title={statusPill.title} color={statusPill.color}>{statusPill.label}</Pill>)
  if (e.abstract) badges.push(<Pill key="ab" onClick={() => toggle('abstract')} title="Show the abstract">Abstract</Pill>)
  if (e.tldr) badges.push(<Pill key="cl" onClick={() => toggle('tldr')} title="One-line claim (Semantic Scholar TL;DR)" color="var(--color-warning)">Claim</Pill>)
  if (e.is_preprint) badges.push(<Pill key="pp" title="Preprint / posted content (not yet a journal article)" color="var(--color-warning)">Preprint</Pill>)
  if (publishedLabel) badges.push(<Pill key="pd" title="Publication date (OpenAlex)">Published {publishedLabel}</Pill>)
  if (topics.length > 0) badges.push(<Pill key="fos" title={`Fields of study (OpenAlex concepts): ${topics.join(', ')}`}>Topics: {topics.slice(0, 3).join(', ')}{topics.length > 3 ? ` +${topics.length - 3}` : ''}</Pill>)

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
