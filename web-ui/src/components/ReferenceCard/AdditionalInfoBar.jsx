import { useState } from 'react'
import { openExternal, isTauri } from '../../utils/tauriBridge'
import { addSeenReference } from '../../utils/api'

/**
 * "Additional Info" row under a reference: surfaces the NEW article-intelligence
 * signals (abstract, claim/TL;DR, preprint flag, open-access full text) and an
 * honest "✓ In Library" state (checked refs are auto-saved to the
 * Seen-References library — no redundant "Add" button). Every pill is
 * real-data-gated — it renders only when
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
  // Info-only pills (Topics, Preprint, Funding, status) have no action — render
  // them as a plain span so they don't look/behave like a clickable button.
  if (!onClick) {
    return <span title={title} style={style}>{children}</span>
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

  // Primary URL for the "Full link" action: prefer the open-access PDF, then the
  // reference's own url, then a DOI resolved to https://doi.org/<doi>. Stays null
  // when none exists so the action is real-data-gated (never a dead link).
  const doi = reference?.doi || reference?.verified_doi || null
  const fullLink = oaUrl
    || reference?.url
    || (doi ? `https://doi.org/${String(doi).replace(/^https?:\/\/(dx\.)?doi\.org\//i, '')}` : null)

  // Real OpenAlex signals for the new badges. fields_of_study is an array of real
  // OpenAlex concept names; funders is an array of real funder names. Both omit
  // entirely when absent — no placeholders, no fabricated "description".
  const topics = Array.isArray(e.fields_of_study)
    ? e.fields_of_study.filter(t => typeof t === 'string' && t.trim())
    : []
  const funders = Array.isArray(e.funders)
    ? e.funders.filter(f => typeof f === 'string' && f.trim())
    : []

  // Real verification state (not enrichment): show a live status pill only
  // while this reference is actually queued or being checked.
  const refStatus = reference && reference.status
  const statusPill = refStatus === 'checking'
    ? { label: 'Checking…', title: 'This reference is being verified', color: 'var(--color-accent)' }
    : refStatus === 'pending'
      ? { label: 'Pending', title: 'Waiting in the verification queue', color: 'var(--color-text-muted)' }
      : null

  // Checked references are ALREADY auto-added to the Seen-References library:
  // when a check completes the backend upserts every reference into the global
  // identity index (the "Seen-Refs backstop" — see upsert_verified_reference).
  // So a "+ Add to Library" action is redundant + misleading. Instead we surface
  // the HONEST saved state and let the user CONFIRM it on demand. The only
  // read-the-real-state path the FE has is the idempotent POST itself (it
  // returns {added, times_seen} for the existing row without creating a
  // duplicate), so "confirm" re-reads the live count rather than fabricating it.
  // NOTE: there is no per-reference remove endpoint on the backend (only a
  // wipe-everything DELETE /references/seen). We therefore do NOT render a
  // per-reference "Remove" control — a non-functional / whole-library-clearing
  // button here would be misleading. Removal stays on the Seen References tab.
  const canCache = !!(reference?.doi || reference?.verified_doi || reference?.arxiv_id || reference?.title)
  const confirmInLibrary = async () => {
    if (lib === 'adding') return
    setLib('adding')
    try {
      const res = await addSeenReference(reference, checkId || null, null)
      setLibN(res?.data?.times_seen || 1)
      // Idempotent upsert: if it returns a row (added OR already present), it's
      // confirmed in the library. added=false with no row => no identity key.
      setLib(res?.data ? 'done' : 'error')
    } catch {
      setLib('error')
    }
  }

  const badges = []
  if (statusPill) badges.push(<Pill key="st" title={statusPill.title} color={statusPill.color}>{statusPill.label}</Pill>)
  if (e.abstract) badges.push(<Pill key="ab" onClick={() => toggle('abstract')} title="Show the abstract">Abstract</Pill>)
  if (e.tldr) badges.push(<Pill key="cl" onClick={() => toggle('tldr')} title="One-line claim (Semantic Scholar TL;DR)" color="var(--color-warning)">Claim</Pill>)
  if (e.is_preprint) badges.push(<Pill key="pp" title="Preprint / posted content (not yet a journal article)" color="var(--color-warning)">Preprint</Pill>)
  if (topics.length > 0) badges.push(<Pill key="fos" title={`Fields of study (OpenAlex concepts): ${topics.join(', ')}`}>Topics: {topics.slice(0, 3).join(', ')}{topics.length > 3 ? ` +${topics.length - 3}` : ''}</Pill>)
  if (funders.length > 0) badges.push(<Pill key="fund" title={`Funding (OpenAlex grants): ${funders.join(', ')}`}>Funding: {funders.slice(0, 2).join(', ')}{funders.length > 2 ? ` +${funders.length - 2}` : ''}</Pill>)

  const actions = []
  if (oaUrl) actions.push(<Pill key="vp" href={oaUrl} title="Open the open-access full text / PDF" color="var(--color-accent)">View full text ↗</Pill>)
  // "Full link" opens the reference's primary URL (url / DOI). Only shown when it
  // resolves to something other than the open-access PDF already linked above, so
  // we never render two pills pointing at the same destination.
  if (fullLink && fullLink !== oaUrl) actions.push(<Pill key="fl" href={fullLink} title={`Open the reference link: ${fullLink}`} color="var(--color-accent)">Full link ↗</Pill>)
  if (canCache) {
    // Honest in-library state. Checked refs are auto-saved on check, so the
    // resting label is "✓ In Library" (not a misleading "+ Add"). Clicking
    // re-confirms the live times_seen count via the idempotent upsert (no
    // duplicate row, no fabricated number). Removal isn't offered here because
    // the backend has no per-reference remove endpoint (only a full cache wipe
    // on the Seen References tab) — see the note above confirmInLibrary().
    const libLabel = lib === 'adding'
      ? 'Confirming…'
      : lib === 'error'
        ? 'Not in library'
        : lib === 'done'
          ? `✓ In Library${libN > 1 ? ` · ${libN}×` : ''}`
          : '✓ In Library'
    const libTitle = lib === 'error'
      ? 'This reference has no stable identity key (DOI / arXiv / title), so it could not be saved to the library.'
      : lib === 'done'
        ? `Saved in your Seen-References library${libN > 1 ? ` · seen ${libN}×` : ''}. Manage or remove it from the Seen References tab. Click to re-confirm the live count.`
        : 'Auto-saved to your Seen-References library when this reference was checked. Click to confirm the live count. Remove it from the Seen References tab.'
    actions.push(
      <Pill key="lib" onClick={confirmInLibrary}
        title={libTitle}
        color={lib === 'error' ? 'var(--color-error)' : 'var(--color-success)'}>
        {libLabel}
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
