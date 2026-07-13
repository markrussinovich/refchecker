"""
Reference enrichment — pull display-ready signals out of whatever the
verification checker returned.

The verified `work_data` shape differs by source (OpenAlex, Crossref,
Semantic Scholar, DBLP, ACL Anthology, …). This module normalises the
useful display fields into one flat dict the UI can consume without
caring which source won the verification race.

Fields produced:
    cited_by_count       int   — works that cite this paper
    reference_count      int   — references this paper itself cites
    is_open_access       bool  — open access flag
    openalex_id          str   — OpenAlex Work ID (W…)
    pubmed_id            str   — PubMed ID if present
    pmc_id               str   — PubMed Central ID if present
    mag_id               str   — Microsoft Academic Graph ID (legacy)
    fields_of_study      list  — top concept display names
    publication_type     str   — journal-article / preprint / book / …
    is_preprint          bool  — True only when type is preprint/posted-content
    abstract             str   — abstract text (S2/Crossref/OpenAlex), ≤1500 chars
    tldr                 str   — Semantic Scholar machine TL;DR ("claim")
    oa_pdf_url           str   — open-access PDF URL when one exists
    has_funding          bool  — at least one grant/funder listed
    funders              list  — distinct funder display names
    has_affiliation      bool  — at least one author has an institution
    biblio               dict  — {volume, issue, first_page, last_page}
    links                dict  — {doi, libkey, worldcat, openalex}
    authors              list  — [{name, orcid, openalex_id, institutions}]
    source_label         str   — which checker produced the match

Anything we can't extract is left out of the dict — the UI treats
missing fields as "no signal" rather than zero.
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


def _safe_get(d: Dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _coerce_int(v: Any) -> Optional[int]:
    """Best-effort non-negative int from a count field. Accepts int or a
    clean numeric string ("182", "182.0"); rejects everything else.
    Returns None — never invents a value — so callers can distinguish
    "no signal" from a real zero."""
    if isinstance(v, bool):  # bool is a subclass of int — exclude it
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, float):
        return int(v) if v >= 0 else None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            f = float(s)
        except (TypeError, ValueError):
            return None
        return int(f) if f >= 0 else None
    return None


def _max_count(verified_data: Dict[str, Any], *keys: str) -> Optional[int]:
    """Coalesce a count across every source-shaped key present in the SAME
    payload and keep the richest (largest) real value. A payload can carry
    several source variants at once (OpenAlex `cited_by_count`,
    Semantic Scholar `citationCount`, Crossref `is-referenced-by-count`),
    and any one of them may be 0/None while another holds the real number.
    Taking the max across all present, parseable values means a real 0 is
    never picked over a real 182, and a missing primary source no longer
    suppresses a populated secondary one. Returns None when no key carries
    a parseable value — real-data only, nothing fabricated."""
    best: Optional[int] = None
    for k in keys:
        n = _coerce_int(verified_data.get(k))
        if n is None:
            continue
        if best is None or n > best:
            best = n
    return best


def _short_id(openalex_url: Optional[str]) -> Optional[str]:
    if not openalex_url:
        return None
    s = str(openalex_url).rstrip('/')
    if not s:
        return None
    # If the URL is at most the host (no ID segment after openalex.org),
    # there's nothing useful to extract.
    for host in ('openalex.org', 'orcid.org', 'doi.org'):
        if s.endswith(host) or s.endswith(host.upper()):
            return None
    if '/' in s:
        tail = s.rsplit('/', 1)[-1]
        return tail or None
    return s


def _extract_authors_with_orcid(authorships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for auth in authorships or []:
        author = auth.get('author') or {}
        name = author.get('display_name') or author.get('name')
        if not name:
            # Crossref author shape: {given, family, ORCID}
            given = auth.get('given')
            family = auth.get('family')
            name = (f"{given} {family}".strip() if given or family else None)
        if not name:
            continue
        entry: Dict[str, Any] = {'name': name}
        # S2 author-id passthrough (from the synthetic shape built in
        # build_enrichment). Lets the FE link to semanticscholar.org
        # /author/<id> even when ORCID/OpenAlex IDs aren't available.
        if auth.get('s2_author_id'):
            entry['s2_author_id'] = str(auth['s2_author_id'])
        orcid = (
            author.get('orcid')
            or auth.get('ORCID')
            or auth.get('orcid')
        )
        if orcid:
            # Canonicalise to a bare 0000-0000-0000-0000 form regardless
            # of input shape (https://orcid.org/…, http://…, or already
            # bare). The UI builds the orcid.org link itself.
            bare = str(orcid)
            for prefix in ('https://orcid.org/', 'http://orcid.org/', 'orcid.org/'):
                if bare.startswith(prefix):
                    bare = bare[len(prefix):]
                    break
            entry['orcid'] = bare
        oa_id = _short_id(author.get('id'))
        if oa_id:
            entry['openalex_id'] = oa_id
        affs = auth.get('institutions') or []
        if affs:
            inst_names = [i.get('display_name') for i in affs if i.get('display_name')]
            if inst_names:
                entry['institutions'] = inst_names[:3]
        out.append(entry)
    return out


def _fields_of_study_from_openalex(concepts: List[Dict[str, Any]]) -> List[str]:
    """OpenAlex returns concepts with `display_name` and `score`. Keep
    the top three by score that clear 0.3."""
    if not isinstance(concepts, list):
        return []
    ranked = sorted(
        (c for c in concepts if isinstance(c, dict) and (c.get('score') or 0) >= 0.3),
        key=lambda c: -(c.get('score') or 0),
    )
    return [c.get('display_name') for c in ranked[:3] if c.get('display_name')]


def _strip_jats(s: str) -> str:
    """Strip JATS/XML tags (Crossref abstracts arrive as <jats:p>…</jats:p>)."""
    import re as _re
    s = _re.sub(r'<[^>]+>', ' ', s)
    s = _re.sub(r'\s+', ' ', s)
    return s.strip()


def _reconstruct_inverted_index(inv: Any, cap: int = 1500) -> Optional[str]:
    """Rebuild abstract text from OpenAlex `abstract_inverted_index`
    ({word: [positions]}). Each word is placed at every one of its positions;
    the result is ordered by position and capped at *cap* chars. Returns None on
    empty/bad input — never fabricates."""
    if not isinstance(inv, dict) or not inv:
        return None
    positions: List[tuple] = []
    for word, idxs in inv.items():
        if not isinstance(idxs, list):
            continue
        for i in idxs:
            if isinstance(i, int) and i >= 0:
                positions.append((i, word))
    if not positions:
        return None
    positions.sort(key=lambda t: t[0])
    text = " ".join(w for _i, w in positions).strip()
    return text[:cap] if text else None


def _extract_abstract(verified_data: Dict[str, Any], cap: int = 1500) -> Optional[str]:
    """First real abstract wins: S2/Crossref plain string (JATS-stripped) →
    OpenAlex inverted index. Never synthesized from title/other fields."""
    abs_raw = verified_data.get('abstract')
    if isinstance(abs_raw, str) and abs_raw.strip():
        text = abs_raw.strip()
        if '<' in text and '>' in text:
            text = _strip_jats(text)
        return text[:cap] if text else None
    return _reconstruct_inverted_index(verified_data.get('abstract_inverted_index'), cap=cap)


def _extract_oa_pdf_url(verified_data: Dict[str, Any]) -> Optional[str]:
    """Open-access PDF URL: S2 openAccessPdf.url → OpenAlex open_access.oa_url →
    primary_location.pdf_url. Returns None when no real OA link exists."""
    for path in (('openAccessPdf', 'url'), ('open_access', 'oa_url'), ('primary_location', 'pdf_url')):
        v = _safe_get(verified_data, *path)
        if isinstance(v, str) and v.startswith('http'):
            return v
    return None


def build_enrichment(verified_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Project the heterogeneous verified payload onto a flat
    display-ready dict. Returns {} when there's nothing to surface."""
    if not isinstance(verified_data, dict):
        return {}

    enrichment: Dict[str, Any] = {}

    # cited_by_count: OpenAlex top-level `cited_by_count`; Semantic Scholar
    # uses `citationCount`; Crossref puts it in `is-referenced-by-count`.
    # Coalesce across EVERY variant present in the same payload and keep the
    # richest (largest) real value — so a source that returned 0 (or omitted
    # the field) never masks another source's real count, and the UI shows
    # the maximum confirmable citation number rather than dropping the field.
    cited_by = _max_count(
        verified_data,
        'cited_by_count',
        'citationCount',
        'is-referenced-by-count',
        'citation_count',
        'numCitedBy',
    )
    if cited_by is not None:
        enrichment['cited_by_count'] = cited_by

    # Citing-Patents counter — OpenAlex exposes this in
    # `counts_by_year[*].citing_patents` for the top-level patent-cite
    # tally we display in the SciSpace-style header. When the field
    # isn't present we just leave it off; the UI handles `null`
    # gracefully ("Citing Patents" row hidden).
    cb_year = verified_data.get('counts_by_year')
    if isinstance(cb_year, list):
        try:
            citing_patents = sum(int(y.get('citing_patents') or 0) for y in cb_year if isinstance(y, dict))
            if citing_patents > 0:
                enrichment['citing_patents_count'] = citing_patents
        except (TypeError, ValueError):
            pass

    # reference_count: OpenAlex `referenced_works` array length; S2 may
    # include `referenceCount`; Crossref `references-count`. Coalesce
    # across all variants and keep the richest (largest) value rather than
    # short-circuiting on the first key seen — an empty `referenced_works`
    # list (length 0) must NOT suppress a real Crossref `references-count`
    # carried in the same payload. The array-length and the integer counts
    # are pooled together; the maximum real value wins.
    ref_candidates: List[int] = []
    refs = verified_data.get('referenced_works')
    if isinstance(refs, list):
        ref_candidates.append(len(refs))
    for k in ('referenceCount', 'references-count', 'reference_count', 'numReferences'):
        n = _coerce_int(verified_data.get(k))
        if n is not None:
            ref_candidates.append(n)
    if ref_candidates:
        enrichment['reference_count'] = max(ref_candidates)

    # Open access flag (OpenAlex; Crossref expresses via license[].URL).
    oa_flag = _safe_get(verified_data, 'open_access', 'is_oa')
    if isinstance(oa_flag, bool):
        enrichment['is_open_access'] = oa_flag

    # External IDs — OpenAlex's `ids` dict is the most complete; fall
    # back to S2's `externalIds` and Crossref's flat fields.
    ids = verified_data.get('ids') or {}
    if isinstance(ids, dict):
        if ids.get('openalex'):
            enrichment['openalex_id'] = _short_id(ids['openalex'])
        if ids.get('pmid'):
            enrichment['pubmed_id'] = str(ids['pmid']).rsplit('/', 1)[-1]
        if ids.get('pmcid'):
            enrichment['pmc_id'] = str(ids['pmcid']).rsplit('/', 1)[-1]
        if ids.get('mag'):
            enrichment['mag_id'] = str(ids['mag'])
    if 'openalex_id' not in enrichment and verified_data.get('id'):
        enrichment['openalex_id'] = _short_id(verified_data['id'])
    s2_ext = verified_data.get('externalIds') or {}
    if isinstance(s2_ext, dict):
        if 'pubmed_id' not in enrichment and s2_ext.get('PubMed'):
            enrichment['pubmed_id'] = str(s2_ext['PubMed'])
        if 'pmc_id' not in enrichment and s2_ext.get('PubMedCentral'):
            enrichment['pmc_id'] = str(s2_ext['PubMedCentral'])
        if 'mag_id' not in enrichment and s2_ext.get('MAG'):
            enrichment['mag_id'] = str(s2_ext['MAG'])

    # Publication type — prefer the top-level `type` (OpenAlex /
    # Crossref); fall back to Semantic Scholar's nested
    # publicationVenue.type only when it's actually a dict.
    pub_type = verified_data.get('type')
    venue_struct = verified_data.get('publicationVenue')
    if not pub_type and isinstance(venue_struct, dict):
        pub_type = venue_struct.get('type')
    if isinstance(pub_type, str) and pub_type:
        enrichment['publication_type'] = pub_type

    # Venue / journal name — every source names this differently, so walk
    # ALL of them and take the first non-empty real value. OpenAlex uses
    # `primary_location.source.display_name`; Crossref puts the journal
    # title in `container-title` (list) or `journal-title`/`short-container-title`;
    # Semantic Scholar uses `venue` (str), `publicationVenue.name`, or a
    # nested `journal.name`. Coalescing across every variant means a paper
    # that matched via a source missing its primary venue key still shows
    # the venue when ANY source in the payload carries it.
    def _first_str(*vals: Any) -> Optional[str]:
        for v in vals:
            if isinstance(v, list) and v:
                v = v[0]
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    venue_name = None
    if isinstance(venue_struct, dict):
        venue_name = _first_str(venue_struct.get('name'), venue_struct.get('display_name'))
    if not venue_name:
        primary = verified_data.get('primary_location')
        if isinstance(primary, dict):
            src = primary.get('source')
            if isinstance(src, dict):
                venue_name = _first_str(src.get('display_name'), src.get('name'))
    if not venue_name:
        journal = verified_data.get('journal')
        if isinstance(journal, dict):
            venue_name = _first_str(journal.get('name'), journal.get('display_name'))
        elif isinstance(journal, str):
            venue_name = _first_str(journal)
    if not venue_name:
        venue_name = _first_str(
            verified_data.get('venue'),
            verified_data.get('container-title'),
            verified_data.get('journal-title'),
            verified_data.get('journalName'),
            verified_data.get('short-container-title'),
        )
    if isinstance(venue_name, str) and venue_name.strip():
        enrichment['venue'] = venue_name.strip()

    # OpenAlex venue (source) ID — lets the FE link the venue name to
    # the journal/conference profile page. Mirrors the OpenAlex shape
    # `primary_location.source.id` → "https://openalex.org/S12345".
    venue_id_url = None
    primary = verified_data.get('primary_location')
    if isinstance(primary, dict):
        src = primary.get('source')
        if isinstance(src, dict):
            venue_id_url = src.get('id')
    if isinstance(venue_id_url, str):
        vid = _short_id(venue_id_url)
        if vid:
            enrichment['venue_id'] = vid

    # Publication date — pretty-printed for the venue header line.
    # OpenAlex has `publication_date` (YYYY-MM-DD); Crossref has nested
    # `issued.date-parts`; Semantic Scholar uses `year` + optional
    # `publicationDate`. Output is a single human string like
    # "Oct 1, 2021" or fallback to just the year.
    pub_date_str = None
    pd = verified_data.get('publication_date') or verified_data.get('publicationDate')
    if isinstance(pd, str) and len(pd) >= 4:
        try:
            from datetime import datetime
            pub_date_str = datetime.strptime(pd[:10], "%Y-%m-%d").strftime("%b %-d, %Y")
        except (ValueError, TypeError):
            pub_date_str = pd
    if not pub_date_str:
        issued = _safe_get(verified_data, 'issued', 'date-parts')
        if isinstance(issued, list) and issued and isinstance(issued[0], list):
            parts = issued[0]
            try:
                if len(parts) >= 3:
                    from datetime import datetime
                    pub_date_str = datetime(int(parts[0]), int(parts[1]), int(parts[2])).strftime("%b %-d, %Y")
                elif len(parts) >= 1:
                    pub_date_str = str(int(parts[0]))
            except (ValueError, TypeError):
                pass
    if not pub_date_str:
        yr = verified_data.get('publication_year') or verified_data.get('year')
        if yr:
            pub_date_str = str(yr)
    if pub_date_str:
        enrichment['publication_date'] = pub_date_str

    # Fields of study — OpenAlex `concepts`; Semantic Scholar exposes a
    # plain `fieldsOfStudy` (list[str]) AND a richer `s2FieldsOfStudy`
    # (list[{category, source}]). Walk every variant in turn so a payload
    # that only carries the S2 structured form (or only OpenAlex concepts)
    # still surfaces a Field of Study chip. First non-empty real list wins;
    # capped at three for the strip.
    fos = _fields_of_study_from_openalex(verified_data.get('concepts') or [])
    if not fos:
        s2_fos = verified_data.get('fieldsOfStudy')
        if isinstance(s2_fos, list):
            fos = [f for f in s2_fos if isinstance(f, str) and f.strip()][:3]
    if not fos:
        s2_struct_fos = verified_data.get('s2FieldsOfStudy')
        if isinstance(s2_struct_fos, list):
            seen_fos = set()
            for item in s2_struct_fos:
                cat = item.get('category') if isinstance(item, dict) else item
                if isinstance(cat, str) and cat.strip() and cat not in seen_fos:
                    seen_fos.add(cat)
                    fos.append(cat.strip())
                if len(fos) >= 3:
                    break
    if fos:
        enrichment['fields_of_study'] = fos

    # Authors — multi-shape adapter. OpenAlex returns `authorships` with
    # author.{display_name, orcid, institutions}. Crossref returns
    # `author` with {given, family, ORCID}. Semantic Scholar returns
    # `authors` with {authorId, name} (no ORCID in the basic /paper
    # response; the dedicated /author endpoint has more but we don't
    # fetch it). We surface SOMETHING in all three cases so the FE's
    # AuthorsLine renders a hover for the cited name even when the
    # backing DB doesn't expose author profile IDs.
    def _s2_authors_to_authorships(raw: Any) -> List[Dict[str, Any]]:
        """Promote Semantic Scholar `authors` ({authorId, name}) into the
        OpenAlex-shaped {author: {display_name}}. We deliberately omit `id`
        because S2's authorId is NOT an OpenAlex ID and would produce a
        broken openalex.org/<id> link in the FE; `s2_author_id` is stored
        separately so the FE can link to semanticscholar.org/author/<id>."""
        out: List[Dict[str, Any]] = []
        if isinstance(raw, list):
            for a in raw:
                if isinstance(a, dict) and a.get('name'):
                    entry = {'author': {'display_name': a.get('name')}}
                    if a.get('authorId'):
                        entry['s2_author_id'] = a.get('authorId')
                    out.append(entry)
        return out

    # Authors — multi-shape adapter that coalesces across every author key a
    # source might carry (OpenAlex `authorships`, Crossref `author`,
    # Semantic Scholar `authors`). Rather than stopping at the first
    # non-empty key, normalise EACH present shape and keep the richest
    # result — the list with the most names, breaking ties toward whichever
    # carries the most ORCID/OpenAlex IDs. That way a payload whose primary
    # author key is empty/sparse still shows the fullest real author list
    # another source provided. Never fabricated.
    candidate_author_lists: List[List[Dict[str, Any]]] = []
    for raw in (
        verified_data.get('authorships'),
        verified_data.get('author') if isinstance(verified_data.get('author'), list) else None,
    ):
        if isinstance(raw, list) and raw:
            candidate_author_lists.append(_extract_authors_with_orcid(raw))
    s2_shaped = _s2_authors_to_authorships(verified_data.get('authors'))
    if s2_shaped:
        candidate_author_lists.append(_extract_authors_with_orcid(s2_shaped))

    enriched_authors: List[Dict[str, Any]] = []
    for cand in candidate_author_lists:
        if not cand:
            continue
        cand_ids = sum(1 for a in cand if a.get('orcid') or a.get('openalex_id'))
        best_ids = sum(1 for a in enriched_authors if a.get('orcid') or a.get('openalex_id'))
        if (len(cand), cand_ids) > (len(enriched_authors), best_ids):
            enriched_authors = cand
    if enriched_authors:
        enrichment['authors'] = enriched_authors

    # Funders / grants — OpenAlex returns `grants[]` with funder name;
    # Crossref/S2-shaped payloads may carry a `funders[]`/`funder[]` list of
    # {name|funder_display_name|funder}. Walk every variant present and pool the
    # distinct real funder names. Real-data only: if nothing names a funder, the
    # has_funding/funders keys are omitted (absence != "no funding").
    funders: List[str] = []
    seen: set = set()
    for source_key in ('grants', 'funders', 'funder'):
        entries = verified_data.get(source_key)
        if not isinstance(entries, list):
            continue
        for g in entries:
            if isinstance(g, dict):
                name = (
                    g.get('funder_display_name')
                    or g.get('name')
                    or g.get('funder')
                    or g.get('award_id')
                )
            elif isinstance(g, str):
                name = g
            else:
                name = None
            if name and str(name) not in seen:
                funders.append(str(name))
                seen.add(str(name))
    if funders:
        enrichment['has_funding'] = True
        enrichment['funders'] = funders[:5]

    # Affiliation badge — at least one author institution present.
    if any(a.get('institutions') for a in (enrichment.get('authors') or [])):
        enrichment['has_affiliation'] = True

    # Abstract — first real source wins (S2/Crossref string or OpenAlex
    # inverted index); omitted entirely when no source carries one.
    abstract = _extract_abstract(verified_data)
    if abstract:
        enrichment['abstract'] = abstract

    # TL;DR / "claim" — ONLY Semantic Scholar's machine-generated tldr.
    # Never synthesized from the abstract/title. S2's API returns it nested as
    # {model, text}; some flattened shapes (local DB rows, re-serialised
    # payloads) carry it as a plain string. Accept either real form; absent
    # stays absent.
    tldr_raw = verified_data.get('tldr')
    tldr = None
    if isinstance(tldr_raw, dict):
        tldr = tldr_raw.get('text')
    elif isinstance(tldr_raw, str):
        tldr = tldr_raw
    if isinstance(tldr, str) and tldr.strip():
        enrichment['tldr'] = tldr.strip()

    # Open-access PDF URL (also added to links below).
    oa_pdf_url = _extract_oa_pdf_url(verified_data)
    if oa_pdf_url:
        enrichment['oa_pdf_url'] = oa_pdf_url

    # Preprint flag — omit when not a preprint (absence != False in the UI).
    _ptype = (enrichment.get('publication_type') or '').lower()
    if _ptype in ('preprint', 'posted-content'):
        enrichment['is_preprint'] = True

    # Bibliographic detail (volume / issue / pages) — OpenAlex `biblio`
    # is exactly this shape; Crossref scatters them across top-level
    # `volume`, `issue`, `page` fields.
    biblio_src = verified_data.get('biblio')
    if isinstance(biblio_src, dict):
        biblio = {k: biblio_src.get(k) for k in ('volume', 'issue', 'first_page', 'last_page') if biblio_src.get(k)}
        if biblio:
            enrichment['biblio'] = biblio
    elif verified_data.get('volume') or verified_data.get('issue') or verified_data.get('page'):
        biblio = {}
        if verified_data.get('volume'):
            biblio['volume'] = str(verified_data['volume'])
        if verified_data.get('issue'):
            biblio['issue'] = str(verified_data['issue'])
        page = verified_data.get('page')
        if isinstance(page, str):
            # Accept ASCII hyphen, en-dash (U+2013), or em-dash (U+2014).
            import re as _re
            parts = [p.strip() for p in _re.split(r'[\-–—]', page, maxsplit=1)]
            if parts[0]:
                biblio['first_page'] = parts[0]
            if len(parts) > 1 and parts[1]:
                biblio['last_page'] = parts[1]
        elif page:
            biblio['first_page'] = str(page)
        if biblio:
            enrichment['biblio'] = biblio

    # Click-through links — built from the canonical IDs we already
    # extracted. LibKey and WorldCat are public link services (no auth
    # required), so we surface them whenever a DOI is available.
    links: Dict[str, str] = {}
    canonical_doi = (
        verified_data.get('doi')
        or verified_data.get('DOI')
        or (verified_data.get('ids') or {}).get('doi')
        or (verified_data.get('externalIds') or {}).get('DOI')
    )
    if canonical_doi:
        clean_doi = str(canonical_doi)
        for prefix in ('https://doi.org/', 'http://doi.org/', 'doi:'):
            if clean_doi.startswith(prefix):
                clean_doi = clean_doi[len(prefix):]
                break
        # Bare DOI for FE display; the resolver URL is built client-side
        # so a single value powers both label text and href.
        links['doi'] = clean_doi
        links['doi_url'] = f"https://doi.org/{clean_doi}"
        links['libkey'] = f"https://libkey.io/{clean_doi}"
        # WorldCat's `q` is a query-string value: percent-encode so
        # DOIs containing `&`, `#`, `+`, or other reserved characters
        # don't truncate the query or split it into multiple params.
        links['worldcat'] = f"https://www.worldcat.org/search?q={quote(clean_doi, safe='')}"
    if enrichment.get('openalex_id'):
        links['openalex'] = f"https://openalex.org/{enrichment['openalex_id']}"
    if oa_pdf_url:
        links['oa_pdf'] = oa_pdf_url
    if links:
        enrichment['links'] = links

    # Which checker produced this — the enhanced_hybrid_checker stamps
    # _matched_database / _matched_checker on the dict before it lands
    # here, so surface that for the UI's "Matched DB:" chip.
    if verified_data.get('_matched_database'):
        enrichment['source_label'] = verified_data['_matched_database']
    elif verified_data.get('_matched_checker'):
        enrichment['source_label'] = verified_data['_matched_checker']
    elif verified_data.get('source'):
        enrichment['source_label'] = verified_data['source']

    # Multi-source attribution: when a future cross-check phase records
    # which sources independently confirmed the same paper, the
    # verifier sets `_verified_by` to a list. Surface it so the FE
    # can render "via Semantic Scholar + Paperclip + Wikipedia"
    # instead of just the single winner. Falls back to [source_label]
    # so the FE has one consistent shape to consume.
    verified_by = verified_data.get('_verified_by')
    if isinstance(verified_by, list) and verified_by:
        enrichment['verified_by'] = [str(s) for s in verified_by if s]
    elif enrichment.get('source_label'):
        enrichment['verified_by'] = [enrichment['source_label']]

    return enrichment


# --------------------------------------------------------------------------- #
# Cross-source backfill (R21 / R22)                                            #
#                                                                             #
# When a non-Semantic-Scholar source (DBLP, ACL Anthology, arXiv, Crossref,   #
# …) wins the verification race, the winning `verified_data` payload often     #
# lacks the richest display signals — citation/reference COUNTS, the abstract, #
# the S2 machine TL;DR ("claim"), and funding. `build_enrichment` already      #
# coalesces ACROSS every variant present in ONE payload, but it cannot         #
# surface a signal no source put in the payload. `backfill_enrichment` closes  #
# that gap: given a winning payload + the cited reference, it resolves the      #
# canonical DOI and pulls the missing-only fields from OpenAlex / Crossref /    #
# Semantic Scholar by DOI, then merges them into the SAME `verified_data` dict  #
# so the existing `build_enrichment` projection surfaces them — with NO        #
# frontend change.                                                             #
#                                                                             #
# Contract (mirrors `_enrich_matched_paper` in semantic_scholar.py:380-388):   #
#   * NEVER overwrite a real existing value — merge only into keys the payload  #
#     lacks or whose value is empty (None / '' / [] / {}).                      #
#   * NEVER fabricate — only real provider-returned values are merged; a        #
#     source that errors/times-out/returns nothing simply contributes nothing.  #
#   * SOFT-FAIL — any exception (network, parse, timeout) is swallowed; the     #
#     verification result is never broken by a display nicety.                  #
#   * BOUNDED — per-DOI TTL cache + 1 retry + short timeout per source + a      #
#     global concurrency cap, so a 30+ ref bibliography never stalls.           #
# --------------------------------------------------------------------------- #

# Keys we attempt to backfill, grouped by where build_enrichment reads them.
# These are the SOURCE-SHAPED keys (what each provider returns), NOT the
# build_enrichment output keys — we write them into verified_data so the
# existing coalescing logic in build_enrichment picks the richest value.
_BACKFILL_COUNT_KEYS = (
    'cited_by_count', 'citationCount', 'is-referenced-by-count',
    'referenced_works', 'referenceCount', 'references-count',
)
_BACKFILL_RICH_KEYS = (
    'abstract', 'abstract_inverted_index', 'tldr', 'grants', 'funder', 'funders',
)

# Per-DOI TTL cache of merged-back fields. Mirrors _AUTHOR_PROFILE_CACHE in
# backend/main.py: {doi: (monotonic_ts, {field: value})}. A 30-ref
# bibliography that cites the same work twice fetches it once; a re-opened
# check served within the TTL re-uses the cached fields with no network.
_BACKFILL_CACHE: Dict[str, "tuple"] = {}
_BACKFILL_TTL_SECONDS = 6 * 60 * 60  # 6 hours
_BACKFILL_CACHE_LOCK = threading.Lock()

# Concurrency cap so a big bibliography doesn't open dozens of simultaneous
# outbound connections (and so a slow provider can't fan out into a stall).
# Acquired around the *network* portion only; cache hits never touch it.
_BACKFILL_TIMEOUT_SECONDS = 6.0
_BACKFILL_MAX_CONCURRENCY = 6
_BACKFILL_SEMAPHORE = threading.BoundedSemaphore(_BACKFILL_MAX_CONCURRENCY)


def _is_empty_value(v: Any) -> bool:
    """Treat None / '' (after strip) / [] / {} as "no signal" — same emptiness
    test build_enrichment and _enrich_matched_paper use to decide a field is
    missing. A real 0, a real False, or a non-empty container are NOT empty."""
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ''
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _clean_doi(raw: Any) -> Optional[str]:
    """Normalise to a bare lowercased DOI (10.xxxx/…). Strips resolver
    prefixes and a trailing slash; rejects anything that isn't DOI-shaped so
    we never issue a bogus /works/doi: lookup. Returns None on no real DOI."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    for prefix in ('https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/',
                   'http://dx.doi.org/', 'doi:'):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.strip().rstrip('/')
    low = s.lower()
    # DOI-shape guard: must start with the "10." registrant prefix and contain
    # the '/' separator. Anything else is not a DOI we can resolve.
    if not low.startswith('10.') or '/' not in low:
        return None
    return low


def _canonical_doi_for_backfill(verified_data: Dict[str, Any],
                                reference: Optional[Dict[str, Any]]) -> Optional[str]:
    """Resolve the canonical DOI to backfill against — winning payload first,
    cited reference last. Mirrors the cleaning at enhanced_hybrid_checker.py."""
    candidates = [
        verified_data.get('doi'),
        verified_data.get('DOI'),
        (verified_data.get('ids') or {}).get('doi') if isinstance(verified_data.get('ids'), dict) else None,
        (verified_data.get('externalIds') or {}).get('DOI') if isinstance(verified_data.get('externalIds'), dict) else None,
        (reference or {}).get('doi'),
    ]
    for c in candidates:
        cleaned = _clean_doi(c)
        if cleaned:
            return cleaned
    return None


def _http_get_json(url: str, *, params: Optional[Dict[str, Any]] = None,
                   headers: Optional[Dict[str, str]] = None,
                   timeout: float = _BACKFILL_TIMEOUT_SECONDS) -> Optional[Dict[str, Any]]:
    """GET → parsed JSON dict, with exactly ONE retry and a short timeout.
    Returns None on any failure (network / non-200 / non-dict body) — the
    caller soft-fails. Bounded by the module concurrency semaphore so a wide
    bibliography can't fan out into a stall."""
    try:
        import requests  # local import: keeps module import pure-stdlib for the test harness
    except Exception:  # pragma: no cover - requests is a hard dep in the app
        return None
    last_exc: Optional[Exception] = None
    for attempt in range(2):  # 1 try + 1 retry
        acquired = _BACKFILL_SEMAPHORE.acquire(timeout=timeout)
        if not acquired:
            return None
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        except Exception as exc:  # network / timeout
            last_exc = exc
            resp = None
        finally:
            _BACKFILL_SEMAPHORE.release()
        if resp is not None:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError as exc:
                    last_exc = exc
                    data = None
                if isinstance(data, dict):
                    return data
                return None
            # 404 / 410 are definitive "no such record" — don't retry.
            if resp.status_code in (404, 410):
                return None
    if last_exc is not None:
        logger.debug("backfill GET failed for %s: %s", url, last_exc)
    return None


def _fetch_openalex_by_doi(doi: str) -> Dict[str, Any]:
    """OpenAlex /works/doi:{doi} → the source-shaped fields build_enrichment
    reads: cited_by_count, referenced_works (length), abstract_inverted_index,
    grants[]. Real values only; missing fields are simply omitted."""
    data = _http_get_json(f"https://api.openalex.org/works/doi:{quote(doi, safe='')}")
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in ('cited_by_count', 'referenced_works', 'abstract_inverted_index', 'grants'):
        v = data.get(k)
        if not _is_empty_value(v):
            out[k] = v
    return out


def _fetch_crossref_by_doi(doi: str) -> Dict[str, Any]:
    """Crossref /works/{doi} → is-referenced-by-count, references-count, JATS
    abstract, funder[]. Crossref wraps the record in a `message` envelope."""
    data = _http_get_json(
        f"https://api.crossref.org/works/{quote(doi, safe='')}",
        headers={'User-Agent': 'refchecker/enrichment-backfill (mailto:support@refchecker.app)'},
    )
    msg = (data or {}).get('message') if isinstance(data, dict) else None
    if not isinstance(msg, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in ('is-referenced-by-count', 'references-count', 'abstract', 'funder'):
        v = msg.get(k)
        if not _is_empty_value(v):
            out[k] = v
    return out


def _fetch_s2_by_doi(doi: str) -> Dict[str, Any]:
    """Semantic Scholar /paper/DOI:{doi} → citationCount, referenceCount, tldr,
    abstract. tldr comes back nested as {model, text}; build_enrichment already
    accepts that shape."""
    data = _http_get_json(
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi, safe='')}",
        params={'fields': 'citationCount,referenceCount,tldr,abstract'},
    )
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in ('citationCount', 'referenceCount', 'tldr', 'abstract'):
        v = data.get(k)
        if not _is_empty_value(v):
            out[k] = v
    return out


def _gather_backfill_fields(doi: str) -> Dict[str, Any]:
    """Fetch the union of missing-able fields for a DOI across all three
    sources, cached per-DOI with a TTL. Soft-fails per source. The merged dict
    keeps the FIRST real value seen for each source-shaped key (OpenAlex →
    Crossref → S2 order), but build_enrichment's own coalescing picks the
    richest value across whatever lands, so source order is not load-bearing
    for the displayed number."""
    now = time.monotonic()
    with _BACKFILL_CACHE_LOCK:
        cached = _BACKFILL_CACHE.get(doi)
        if cached and (now - cached[0]) < _BACKFILL_TTL_SECONDS:
            return dict(cached[1])

    merged: Dict[str, Any] = {}
    for fetcher in (_fetch_openalex_by_doi, _fetch_crossref_by_doi, _fetch_s2_by_doi):
        try:
            got = fetcher(doi)
        except Exception as exc:  # belt-and-braces: a fetcher must never raise
            logger.debug("backfill fetcher %s failed for %s: %s", getattr(fetcher, '__name__', '?'), doi, exc)
            got = {}
        for k, v in (got or {}).items():
            if k not in merged and not _is_empty_value(v):
                merged[k] = v

    with _BACKFILL_CACHE_LOCK:
        _BACKFILL_CACHE[doi] = (now, dict(merged))
    return merged


def _wants_backfill(verified_data: Dict[str, Any]) -> bool:
    """True only when at least one backfill-able display signal is genuinely
    missing — so a payload that already carries counts + abstract + tldr +
    funding makes ZERO network calls. Keeps a rich-source winner free."""
    has_count = any(not _is_empty_value(verified_data.get(k)) for k in _BACKFILL_COUNT_KEYS)
    has_rich = any(not _is_empty_value(verified_data.get(k)) for k in _BACKFILL_RICH_KEYS)
    # Want backfill if EITHER the count family OR the rich family is empty.
    return (not has_count) or (not has_rich)


def backfill_enrichment(verified_data: Optional[Dict[str, Any]],
                        reference: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Backfill missing count / abstract / tldr / funding signals into
    `verified_data` by DOI from OpenAlex / Crossref / Semantic Scholar, then
    return the (mutated, for caller convenience) dict.

    Never overwrites a real value, never fabricates, soft-fails on any error,
    and is bounded (per-DOI TTL cache + 1 retry + short timeout + concurrency
    cap). Call this right before `build_enrichment` so the projection surfaces
    the enriched values with no frontend change.

    Returns the same dict it was given (mutated in place) so callers can write
    `verified_data = backfill_enrichment(verified_data, reference)`. Returns a
    non-dict input unchanged.
    """
    if not isinstance(verified_data, dict):
        return verified_data  # type: ignore[return-value]

    try:
        # Skip entirely when the winning payload is already rich — no DOI
        # lookup, no network. The common S2/OpenAlex-winner case costs nothing.
        if not _wants_backfill(verified_data):
            return verified_data

        doi = _canonical_doi_for_backfill(verified_data, reference)
        if not doi:
            # No DOI to resolve against — nothing we can honestly backfill.
            return verified_data

        fields = _gather_backfill_fields(doi)
        for key, value in fields.items():
            # NEVER overwrite a real existing value — merge only into keys the
            # payload lacks or whose value is empty. Mirrors _enrich_matched_paper.
            if _is_empty_value(value):
                continue
            if _is_empty_value(verified_data.get(key)):
                verified_data[key] = value
    except Exception as exc:  # soft-fail: a display nicety must never break verification
        logger.debug("backfill_enrichment soft-failed: %s", exc)

    return verified_data
