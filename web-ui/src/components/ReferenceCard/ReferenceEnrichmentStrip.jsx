import { useState, useEffect, useId, useRef } from 'react'
import { openExternal, isTauri } from '../../utils/tauriBridge'
import { lookupOclc } from '../../utils/api'

// Module-level cache for DOI → OCLC promises. The backend already
// caches the answer on disk; this dedupes in-flight requests across
// ReferenceCard mounts so reopening the same check doesn't re-fire
// the lookup until the answer lands.
const _oclcLookupCache = new Map()

/**
 * Display-only strip rendered under each verified reference showing
 * the OpenAlex / Crossref / S2 enrichment payload.
 *
 * Layout matches the SciSpace-style multi-row card the user requested:
 *
 *   [Journal Article]  Venue, Volume: 32, Issue: 10, Pages: 2541-2556. Oct 1, 2021
 *   Citing Patents: 0 · Citing Scholarly Works: 0 · Reference Count: 51
 *   [DOI 10.1109/…] [OpenAlex W…] [LibKey] [WorldCat]
 *   Additional Info: [Funding] [Affiliation] [Field of Study]
 *
 * Quiet: when nothing useful is present (e.g. references that
 * verified via DBLP only) the component renders nothing.
 */
export default function ReferenceEnrichmentStrip({ enrichment }) {
  if (!enrichment || typeof enrichment !== 'object') return null

  const {
    cited_by_count,
    reference_count,
    citing_patents_count,
    is_open_access,
    openalex_id,
    pubmed_id,
    pmc_id,
    mag_id,
    publication_type,
    venue,
    publication_date,
    fields_of_study = [],
    authors = [],
    source_label,
    verified_by = [],
    has_funding,
    funders = [],
    has_affiliation,
    biblio,
    links = {},
  } = enrichment

  const hasAnyBadge = (
    cited_by_count != null ||
    reference_count != null ||
    citing_patents_count != null ||
    is_open_access != null ||
    openalex_id || pubmed_id || pmc_id || mag_id ||
    publication_type ||
    venue ||
    publication_date ||
    (Array.isArray(fields_of_study) && fields_of_study.length > 0) ||
    (Array.isArray(authors) && authors.some(a => a?.orcid || a?.openalex_id)) ||
    has_funding ||
    has_affiliation ||
    (biblio && (biblio.volume || biblio.issue || biblio.first_page)) ||
    links.libkey || links.worldcat || links.doi
  )
  if (!hasAnyBadge) return null

  const PUB_TYPE_LABEL = {
    'journal-article': 'Journal Article',
    'proceedings-article': 'Conference Proceedings',
    'proceedings': 'Conference Proceedings',
    'book': 'Book',
    'book-chapter': 'Book Chapter',
    'dissertation': 'Dissertation',
    'preprint': 'Preprint',
    'posted-content': 'Preprint',
    'report': 'Report',
    'review': 'Review',
    'editorial': 'Editorial',
  }
  const prettyPubType = publication_type
    ? (PUB_TYPE_LABEL[publication_type.toLowerCase()] || publication_type)
    : null

  // Row-1 metadata line: bibliographic detail ONLY (Volume / Issue /
  // Pages). The venue name is intentionally NOT repeated here — the
  // main reference-card section above already shows the venue (often
  // as an acronym like "ANZ J Surg") and its hover surfaces the
  // OpenAlex-resolved full name. Showing both as plain text below
  // produced visible duplication that the user flagged.
  const bibBits = []
  if (biblio?.volume) bibBits.push(`Volume: ${biblio.volume}`)
  if (biblio?.issue) bibBits.push(`Issue: ${biblio.issue}`)
  if (biblio?.first_page && biblio?.last_page) {
    bibBits.push(`Pages: ${biblio.first_page}-${biblio.last_page}`)
  } else if (biblio?.first_page) {
    bibBits.push(`Page: ${biblio.first_page}`)
  }
  const metaLine = bibBits.join(', ')

  // Row-2 counters (inline text, not chips — matches the target screenshot)
  const counters = []
  if (typeof citing_patents_count === 'number') {
    counters.push({ label: 'Citing Patents', value: citing_patents_count.toLocaleString() })
  }
  if (typeof cited_by_count === 'number') {
    counters.push({ label: 'Citing Scholarly Works', value: cited_by_count.toLocaleString() })
  }
  if (typeof reference_count === 'number') {
    counters.push({ label: 'Reference Count', value: reference_count.toLocaleString() })
  }

  // DOI excluded — rendered above by the Verification block; pills row
  // shows OpenAlex / PMID / PMC / LibKey / WorldCat / ORCID instead.
  const hasIdRow = !!(openalex_id || pubmed_id || pmc_id || mag_id || links.libkey || links.worldcat)
  const hasAdditional = has_funding || has_affiliation || (Array.isArray(fields_of_study) && fields_of_study.length > 0)
  const hasAuthors = Array.isArray(authors) && authors.some(a => a?.orcid || a?.openalex_id)

  return (
    <div className="flex flex-col gap-1.5 mt-2 text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>
      {/* Row 1: publication type + venue + bibliographic. The year is
          intentionally NOT repeated here — the main reference-card
          section above already renders it on its own line. */}
      {(prettyPubType || metaLine) && (
        <div className="flex flex-wrap items-center gap-2">
          {prettyPubType && <PubTypeChip>{prettyPubType}</PubTypeChip>}
          {metaLine && (
            <span style={{ color: 'var(--color-text-secondary)' }}>{metaLine}</span>
          )}
        </div>
      )}

      {/* Row 2: inline counters */}
      {counters.length > 0 && (
        <div className="flex flex-wrap items-center" style={{ color: 'var(--color-text-muted)' }}>
          {counters.map((c, i) => (
            <span key={c.label} className="flex items-center">
              {i > 0 && <span className="mx-2">·</span>}
              <span>{c.label}: </span>
              <strong className="ml-1" style={{ color: 'var(--color-text-primary)' }}>{c.value}</strong>
            </span>
          ))}
        </div>
      )}

      {/* Row 3: external ID and reader pills. DOI is intentionally NOT
          repeated here — the ReferenceCard's Verification block above
          already renders the DOI URL prominently, and the user flagged
          the duplicate-DOI display as visual noise. LibKey + WorldCat
          still use the DOI internally (passed via links), they just
          don't get their own redundant DOI pill alongside. */}
      {hasIdRow && (
        <div className="flex flex-wrap items-center gap-1.5">
          {openalex_id && (
            <PillLink href={`https://openalex.org/${openalex_id}`} variant="primary" icon="🅾" title="Open in OpenAlex">
              {openalex_id}
            </PillLink>
          )}
          {pubmed_id && (
            <PillLink href={`https://pubmed.ncbi.nlm.nih.gov/${pubmed_id}/`} variant="primary" icon="🅿" title="Open in PubMed">
              PMID {pubmed_id}
            </PillLink>
          )}
          {pmc_id && (
            <PillLink
              href={`https://www.ncbi.nlm.nih.gov/pmc/articles/PMC${pmc_id.replace(/^PMC/i, '')}/`}
              variant="primary"
              icon="📄"
              title="Open in PubMed Central"
            >
              PMC {pmc_id.replace(/^PMC/i, '')}
            </PillLink>
          )}
          {links.libkey && (
            <PillLink href={links.libkey} variant="libkey" icon="🔥" title="Open in LibKey (free public DOI resolver)">
              LibKey
            </PillLink>
          )}
          {links.worldcat && (
            <WorldCatPill searchUrl={links.worldcat} doi={links.doi} />
          )}
          {hasAuthors && <AuthorsPopover authors={authors} />}
          {/* Source attribution. Prefer the multi-source list when a
              future cross-check phase populates `verified_by` — that
              way "via Semantic Scholar + Paperclip + Wikipedia"
              renders without needing FE changes. Falls back to the
              single source_label. */}
          {(verified_by?.length || source_label) && (
            <span className="ml-1 text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
              via {verified_by?.length ? verified_by.join(' + ') : source_label}
            </span>
          )}
        </div>
      )}

      {/* Row 4: Additional Info — yellow/orange status pills */}
      {hasAdditional && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium" style={{ color: 'var(--color-text-muted)' }}>Additional Info:</span>
          {has_funding && (
            <InfoPill title={funders.length ? `Funded by ${funders.join('; ')}` : 'Funded'}>
              $ Funding
            </InfoPill>
          )}
          {has_affiliation && (
            <InfoPill title="Author institutions on file">
              🏛 Affiliation
            </InfoPill>
          )}
          {Array.isArray(fields_of_study) && fields_of_study.slice(0, 3).map(fos => (
            <InfoPill key={fos} title="Field of Study">
              🔬 {fos}
            </InfoPill>
          ))}
          {is_open_access === true && (
            <InfoPill title="Open Access" variant="success">
              🔓 Open Access
            </InfoPill>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Round "Journal Article" / "Conference Proceedings" type chip — sits
 * at the start of row 1, matching the screenshot's blue-link style.
 */
function PubTypeChip({ children }) {
  return (
    <span
      className="px-1.5 py-0.5 rounded font-medium"
      style={{
        background: 'var(--color-info-bg)',
        color: 'var(--color-info)',
        border: '1px solid var(--color-border)',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  )
}

/**
 * Colored pill link. Variants:
 *   - primary: blue, used for DOI / OpenAlex / PMID / PMC
 *   - libkey:  orange flame, matches the LibKey brand colour
 *   - worldcat: blue book, matches the WorldCat brand colour
 */
function PillLink({ href, children, variant = 'primary', icon, title }) {
  const handleClick = (e) => {
    if (!isTauri()) return
    e.preventDefault()
    try { openExternal(href) } catch { /* fall through */ }
  }
  const palette = {
    primary: { fg: 'var(--color-link, #3b82f6)', bg: 'var(--color-info-bg)' },
    libkey: { fg: '#ea580c', bg: 'rgba(234, 88, 12, 0.12)' },
    worldcat: { fg: '#0ea5e9', bg: 'rgba(14, 165, 233, 0.12)' },
  }[variant] || { fg: 'var(--color-link, #3b82f6)', bg: 'var(--color-info-bg)' }
  return (
    <a
      href={href}
      onClick={handleClick}
      target="_blank"
      rel="noopener noreferrer"
      className="px-2 py-0.5 rounded-full inline-flex items-center gap-1 hover:underline font-medium"
      style={{
        background: palette.bg,
        color: palette.fg,
        border: `1px solid ${palette.fg}33`,
        whiteSpace: 'nowrap',
      }}
      title={title || ''}
    >
      {icon && <span aria-hidden="true">{icon}</span>}
      <span>{children}</span>
    </a>
  )
}

/**
 * Bottom-row Additional-Info pill (yellow/amber by default, matching
 * the screenshot's Funding / Affiliation / Field of Study chips).
 */
function InfoPill({ children, title, variant = 'warning' }) {
  const palette = {
    warning: { fg: 'var(--color-warning)', bg: 'var(--color-warning-bg)' },
    success: { fg: 'var(--color-success)', bg: 'var(--color-success-bg)' },
    suggestion: { fg: 'var(--color-suggestion)', bg: 'var(--color-suggestion-bg)' },
  }[variant] || { fg: 'var(--color-warning)', bg: 'var(--color-warning-bg)' }
  return (
    <span
      className="px-2 py-0.5 rounded-full inline-flex items-center gap-1 font-medium"
      style={{
        background: palette.bg,
        color: palette.fg,
        border: `1px solid ${palette.fg}33`,
        whiteSpace: 'nowrap',
      }}
      title={title || ''}
    >
      {children}
    </span>
  )
}

/**
 * WorldCat pill with lazy OCLC resolution. The pre-built link is a
 * `worldcat.org/search?q={doi}` search URL — always works but lands
 * on a results page. On first hover we ask the backend for an OCLC
 * via Wikidata SPARQL; if one comes back, the pill rewrites to
 * `worldcat.org/oclc/{number}` (a direct work link). Cached so the
 * lookup runs at most once per DOI per session.
 */
function WorldCatPill({ searchUrl, doi }) {
  const [resolvedUrl, setResolvedUrl] = useState(null)
  const [resolving, setResolving] = useState(false)
  const startedRef = useRef(false)

  const triggerLookup = () => {
    if (!doi || startedRef.current || resolvedUrl) return
    startedRef.current = true
    let promise = _oclcLookupCache.get(doi)
    if (!promise) {
      promise = lookupOclc(doi)
        .then(r => r?.data?.worldcat_url || null)
        .catch(() => null)
      _oclcLookupCache.set(doi, promise)
    }
    setResolving(true)
    promise.then(url => {
      if (url) setResolvedUrl(url)
      setResolving(false)
    })
  }

  const href = resolvedUrl || searchUrl
  const isDirect = !!resolvedUrl
  const title = isDirect
    ? 'Open this work in WorldCat (resolved via Wikidata OCLC)'
    : resolving
      ? 'Looking up OCLC…'
      : 'Search WorldCat for this work (hover to look up exact OCLC)'
  return (
    <span onMouseEnter={triggerLookup} className="inline-flex">
      <PillLink href={href} variant="worldcat" icon="📚" title={title}>
        WorldCat {resolving ? '…' : (isDirect ? '' : '')}
      </PillLink>
    </span>
  )
}

function AuthorsPopover({ authors }) {
  const [open, setOpen] = useState(false)
  const [align, setAlign] = useState('left')
  const wrapperRef = useRef(null)
  const popoverRef = useRef(null)
  const baseId = useId()
  const triggerId = `${baseId}-trigger`
  const menuId = `${baseId}-menu`
  const withIds = authors.filter(a => a?.orcid || a?.openalex_id)

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  useEffect(() => {
    if (!open || !popoverRef.current) return
    const rect = popoverRef.current.getBoundingClientRect()
    if (rect.right > window.innerWidth - 8) setAlign('right')
  }, [open])

  if (withIds.length === 0) return null

  const popoverStyle = {
    top: '100%',
    minWidth: 260,
    maxWidth: 360,
    background: 'var(--color-bg-secondary)',
    border: '1px solid var(--color-border)',
    ...(align === 'right' ? { right: 0 } : { left: 0 }),
  }

  return (
    <div ref={wrapperRef} className="relative inline-block">
      <button
        id={triggerId}
        onClick={() => setOpen(v => !v)}
        className="px-2 py-0.5 rounded-full font-medium"
        style={{
          background: 'var(--color-info-bg)',
          border: '1px solid var(--color-info)33',
          color: 'var(--color-info)',
          whiteSpace: 'nowrap',
        }}
        title="Authors with ORCID / OpenAlex profiles"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls={menuId}
      >
        🆔 ORCID ({withIds.length})
      </button>
      {open && (
        <div
          ref={popoverRef}
          id={menuId}
          role="menu"
          aria-labelledby={triggerId}
          className="absolute z-50 mt-1 p-2 rounded-md shadow-lg"
          style={popoverStyle}
        >
          <div className="text-[11px] font-semibold mb-1.5" style={{ color: 'var(--color-text-primary)' }}>
            Author profiles
          </div>
          {authors.map((a, i) => (
            <div key={`${a.name || i}`} className="py-1 flex flex-wrap items-center gap-1.5 text-[11px]">
              <span style={{ color: 'var(--color-text-primary)', fontWeight: 500 }}>
                {a.name}
              </span>
              {a.orcid && (
                <PillLink href={`https://orcid.org/${a.orcid}`} variant="primary" title="Open ORCID profile">
                  ORCID {a.orcid}
                </PillLink>
              )}
              {a.openalex_id && (
                <PillLink href={`https://openalex.org/${a.openalex_id}`} variant="primary" title="Open OpenAlex author profile">
                  OpenAlex {a.openalex_id}
                </PillLink>
              )}
              {Array.isArray(a.institutions) && a.institutions.length > 0 && (
                <span className="text-[10px]" style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                  {a.institutions.slice(0, 2).join(', ')}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
