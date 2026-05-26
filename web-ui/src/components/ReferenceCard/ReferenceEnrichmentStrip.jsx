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
 * the OpenAlex / Crossref / S2 enrichment payload — cited-by count,
 * reference count, OA flag, external IDs (DOI / OpenAlex W-id /
 * PubMed / PMC / MAG), publication type, Fields of Study, and a
 * per-author popover with ORCID + OpenAlex author profile links.
 *
 * Quiet: when nothing useful is present (e.g. references that
 * verified via DBLP only) the component renders nothing.
 */
export default function ReferenceEnrichmentStrip({ enrichment }) {
  if (!enrichment || typeof enrichment !== 'object') return null

  const {
    cited_by_count,
    reference_count,
    is_open_access,
    openalex_id,
    pubmed_id,
    pmc_id,
    mag_id,
    publication_type,
    fields_of_study = [],
    authors = [],
    source_label,
    has_funding,
    funders = [],
    has_affiliation,
    biblio,
    links = {},
  } = enrichment

  // Bail when there's literally nothing to show — avoids an empty
  // strip cluttering the card.
  const hasAnyBadge = (
    cited_by_count != null ||
    reference_count != null ||
    is_open_access != null ||
    openalex_id || pubmed_id || pmc_id || mag_id ||
    publication_type ||
    (Array.isArray(fields_of_study) && fields_of_study.length > 0) ||
    (Array.isArray(authors) && authors.some(a => a?.orcid || a?.openalex_id)) ||
    has_funding ||
    has_affiliation ||
    (biblio && (biblio.volume || biblio.issue || biblio.first_page)) ||
    links.libkey || links.worldcat
  )
  if (!hasAnyBadge) return null

  // Friendly label for publication_type. Matches what users expect to
  // see at a glance ("Journal Article" / "Conference Proceedings")
  // instead of the API slugs ("journal-article" / "proceedings").
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

  // Compact bibliographic spec like "Vol. 32, Iss. 10, pp. 2541-2556"
  // — matches how the screenshot's IEEE row reads.
  const biblioBits = []
  if (biblio?.volume) biblioBits.push(`Vol. ${biblio.volume}`)
  if (biblio?.issue) biblioBits.push(`Iss. ${biblio.issue}`)
  if (biblio?.first_page && biblio?.last_page) {
    biblioBits.push(`pp. ${biblio.first_page}–${biblio.last_page}`)
  } else if (biblio?.first_page) {
    biblioBits.push(`p. ${biblio.first_page}`)
  }
  const biblioLine = biblioBits.join(', ')

  return (
    <div
      className="flex flex-wrap gap-1.5 mt-2 text-[11px] items-center"
      style={{ color: 'var(--color-text-secondary)' }}
    >
      {/* Publication type sits up front so the row reads
          "Conference Proceedings · Cited by 12 · …" like the
          screenshot. */}
      {prettyPubType && (
        <BadgeLabel color="#6366f1" title="Publication type">
          {prettyPubType}
        </BadgeLabel>
      )}
      {biblioLine && (
        <Badge title="Bibliographic detail">{biblioLine}</Badge>
      )}
      {source_label && (
        <BadgeLabel color="#3b82f6" title={`Verified via ${source_label}`}>
          {source_label}
        </BadgeLabel>
      )}
      {typeof cited_by_count === 'number' && (
        <Badge title="Citing Scholarly Works — papers that cite this one">
          Cited by <strong>{cited_by_count.toLocaleString()}</strong>
        </Badge>
      )}
      {typeof reference_count === 'number' && (
        <Badge title="Reference Count — references in this paper">
          Refs <strong>{reference_count.toLocaleString()}</strong>
        </Badge>
      )}
      {is_open_access === true && (
        <BadgeLabel color="#16a34a" title="Open Access">
          OA
        </BadgeLabel>
      )}
      {has_funding && (
        <BadgeLabel color="#a855f7" title={funders.length ? `Funded by ${funders.join('; ')}` : 'Funded'}>
          Funding
        </BadgeLabel>
      )}
      {has_affiliation && (
        <BadgeLabel color="#f97316" title="Author institutions on file">
          Affiliation
        </BadgeLabel>
      )}
      {openalex_id && (
        <ExternalIdLink
          label="OpenAlex"
          value={openalex_id}
          href={`https://openalex.org/${openalex_id}`}
          title="Open in OpenAlex"
        />
      )}
      {pubmed_id && (
        <ExternalIdLink
          label="PMID"
          value={pubmed_id}
          href={`https://pubmed.ncbi.nlm.nih.gov/${pubmed_id}/`}
          title="Open in PubMed"
        />
      )}
      {pmc_id && (
        <ExternalIdLink
          label="PMC"
          value={pmc_id.replace(/^PMC/i, '')}
          href={`https://www.ncbi.nlm.nih.gov/pmc/articles/PMC${pmc_id.replace(/^PMC/i, '')}/`}
          title="Open in PubMed Central"
        />
      )}
      {mag_id && (
        <Badge title="Microsoft Academic Graph (legacy)">
          MAG <strong>{mag_id}</strong>
        </Badge>
      )}
      {/* LibKey and WorldCat are free public link services — paste
          a DOI and they resolve to library-subscribed full text or
          to OA copies. No API call from us; we just build the URL. */}
      {links.libkey && (
        <ExternalIdLink
          label="LibKey"
          value="↗"
          href={links.libkey}
          title="Open in LibKey (free public DOI resolver)"
        />
      )}
      {links.worldcat && (
        <WorldCatChip
          searchUrl={links.worldcat}
          doi={links.doi}
        />
      )}
      {Array.isArray(fields_of_study) && fields_of_study.slice(0, 3).map(fos => (
        <BadgeLabel key={fos} color="#f59e0b" title="Field of Study">
          {fos}
        </BadgeLabel>
      ))}
      {Array.isArray(authors) && authors.some(a => a?.orcid || a?.openalex_id) && (
        <AuthorsPopover authors={authors} />
      )}
    </div>
  )
}

function Badge({ children, title }) {
  return (
    <span
      className="px-1.5 py-0.5 rounded"
      style={{
        background: 'var(--color-bg-tertiary)',
        border: '1px solid var(--color-border)',
        color: 'var(--color-text-secondary)',
        whiteSpace: 'nowrap',
      }}
      title={title}
    >
      {children}
    </span>
  )
}

/**
 * WorldCat chip with lazy OCLC resolution. The pre-built link is a
 * `worldcat.org/search?q={doi}` search URL — always works but lands
 * on a results page. On first hover we ask the backend for an OCLC
 * via Wikidata SPARQL; if one comes back, the chip rewrites to
 * `worldcat.org/oclc/{number}` (a direct work link). Cached so the
 * lookup runs at most once per DOI per session.
 */
function WorldCatChip({ searchUrl, doi }) {
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
  const handleClick = (e) => {
    if (!isTauri()) return
    e.preventDefault()
    try { openExternal(href) } catch { /* fall back to native nav */ }
  }
  return (
    <a
      href={href}
      onClick={handleClick}
      onMouseEnter={triggerLookup}
      onFocus={triggerLookup}
      target="_blank"
      rel="noopener noreferrer"
      className="px-1.5 py-0.5 rounded hover:underline"
      style={{
        background: 'var(--color-bg-tertiary)',
        border: '1px solid var(--color-border)',
        color: 'var(--color-link, #3b82f6)',
        whiteSpace: 'nowrap',
        opacity: resolving ? 0.7 : 1,
      }}
      title={title}
    >
      WorldCat {resolving ? '…' : (isDirect ? '🎯' : '↗')}
    </a>
  )
}

function BadgeLabel({ children, color, title }) {
  // Coloured-pill variant for category labels (source, OA, FoS).
  return (
    <span
      className="px-1.5 py-0.5 rounded font-medium"
      style={{
        background: `${color}1a`,        // ~10% opacity tint
        border: `1px solid ${color}55`,
        color,
        whiteSpace: 'nowrap',
      }}
      title={title || ''}
    >
      {children}
    </span>
  )
}

function ExternalIdLink({ label, value, href, title }) {
  // In the Tauri shell we route through openExternal so the system
  // browser opens (the embedded webview can't render arbitrary URLs).
  // In the web build we leave the native href + target=_blank alone so
  // a transient openExternal failure can't produce a dead click.
  const handleClick = (e) => {
    if (!isTauri()) return  // browser handles the click natively
    e.preventDefault()
    try { openExternal(href) } catch { /* fall back to native nav */ }
  }
  return (
    <a
      href={href}
      onClick={handleClick}
      target="_blank"
      rel="noopener noreferrer"
      className="px-1.5 py-0.5 rounded hover:underline"
      style={{
        background: 'var(--color-bg-tertiary)',
        border: '1px solid var(--color-border)',
        color: 'var(--color-link, #3b82f6)',
        whiteSpace: 'nowrap',
      }}
      title={title || ''}
    >
      {label} <strong>{value}</strong>
    </a>
  )
}

function AuthorsPopover({ authors }) {
  // One pill that expands into a list of author chips on click. The
  // ORCID and OpenAlex links open externally; click toggles so the
  // popover works on touch too (mouseLeave-only fails on iPad).
  const [open, setOpen] = useState(false)
  // Horizontal alignment of the floating menu: 'left' (default, pinned
  // to the button) or 'right' (flipped because the menu would overflow
  // the viewport's right edge).
  const [align, setAlign] = useState('left')
  const wrapperRef = useRef(null)
  const popoverRef = useRef(null)
  // React 18 useId — guaranteed unique and SSR-safe.
  const baseId = useId()
  const triggerId = `${baseId}-trigger`
  const menuId = `${baseId}-menu`
  const withIds = authors.filter(a => a?.orcid || a?.openalex_id)

  // Close on outside click + Escape.
  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // Edge-collision: after the popover renders, check if its right edge
  // overflows the viewport; if so, flip to right-anchored.
  useEffect(() => {
    if (!open || !popoverRef.current) return
    const rect = popoverRef.current.getBoundingClientRect()
    if (rect.right > window.innerWidth - 8) {
      setAlign('right')
    }
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
        className="px-1.5 py-0.5 rounded"
        style={{
          background: 'var(--color-bg-tertiary)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-secondary)',
          whiteSpace: 'nowrap',
        }}
        title="Authors with ORCID / OpenAlex profiles"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls={menuId}
      >
        ORCID ({withIds.length})
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
                <ExternalIdLink
                  label="ORCID"
                  value={a.orcid}
                  href={`https://orcid.org/${a.orcid}`}
                  title="Open ORCID profile"
                />
              )}
              {a.openalex_id && (
                <ExternalIdLink
                  label="OpenAlex"
                  value={a.openalex_id}
                  href={`https://openalex.org/${a.openalex_id}`}
                  title="Open OpenAlex author profile"
                />
              )}
              {Array.isArray(a.institutions) && a.institutions.length > 0 && (
                <span
                  className="text-[10px]"
                  style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}
                >
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
