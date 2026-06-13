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

from typing import Any, Dict, List, Optional
from urllib.parse import quote


def _safe_get(d: Dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


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


def build_enrichment(verified_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Project the heterogeneous verified payload onto a flat
    display-ready dict. Returns {} when there's nothing to surface."""
    if not isinstance(verified_data, dict):
        return {}

    enrichment: Dict[str, Any] = {}

    # cited_by_count: OpenAlex top-level; Semantic Scholar uses
    # `citationCount`; Crossref puts it in `is-referenced-by-count`.
    cited_by = (
        verified_data.get('cited_by_count')
        or verified_data.get('citationCount')
        or verified_data.get('is-referenced-by-count')
    )
    if isinstance(cited_by, int):
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

    # reference_count: OpenAlex `referenced_works` array length; S2
    # may include `referenceCount`; Crossref `references-count`.
    ref_count: Optional[int] = None
    refs = verified_data.get('referenced_works')
    if isinstance(refs, list):
        ref_count = len(refs)
    elif isinstance(verified_data.get('referenceCount'), int):
        ref_count = verified_data['referenceCount']
    elif isinstance(verified_data.get('references-count'), int):
        ref_count = verified_data['references-count']
    if ref_count is not None:
        enrichment['reference_count'] = ref_count

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

    # Venue / journal name — OpenAlex uses `primary_location.source.display_name`,
    # Crossref puts the journal title in `container-title` (list), Semantic Scholar
    # uses `venue` (str) or `publicationVenue.name`.
    venue_name = None
    if isinstance(venue_struct, dict):
        venue_name = venue_struct.get('name') or venue_struct.get('display_name')
    if not venue_name:
        primary = verified_data.get('primary_location')
        if isinstance(primary, dict):
            src = primary.get('source')
            if isinstance(src, dict):
                venue_name = src.get('display_name')
    if not venue_name:
        venue_name = verified_data.get('venue')
    if not venue_name:
        ct = verified_data.get('container-title')
        if isinstance(ct, list) and ct:
            venue_name = ct[0]
        elif isinstance(ct, str):
            venue_name = ct
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

    # Fields of study — OpenAlex concepts; S2 has `fieldsOfStudy`.
    fos = _fields_of_study_from_openalex(verified_data.get('concepts') or [])
    if not fos:
        s2_fos = verified_data.get('fieldsOfStudy')
        if isinstance(s2_fos, list):
            fos = [f for f in s2_fos[:3] if f]
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
    authorships = verified_data.get('authorships')
    s2_authors_raw: List[Dict[str, Any]] = []
    if not authorships:
        # Crossref shape
        if isinstance(verified_data.get('author'), list):
            authorships = verified_data['author']
        # Semantic Scholar shape — promote {authorId, name} into
        # OpenAlex-shaped {author: {display_name}}. We deliberately
        # omit `id` because S2's authorId is NOT an OpenAlex ID and
        # would produce a broken openalex.org/<id> link in the FE.
        # `s2_author_id` is stored separately so a future FE pass can
        # link to semanticscholar.org/author/<id>.
        elif isinstance(verified_data.get('authors'), list):
            for a in verified_data['authors']:
                if isinstance(a, dict) and a.get('name'):
                    entry = {'author': {'display_name': a.get('name')}}
                    if a.get('authorId'):
                        entry['s2_author_id'] = a.get('authorId')
                    s2_authors_raw.append(entry)
            authorships = s2_authors_raw
    enriched_authors = _extract_authors_with_orcid(authorships or [])
    if enriched_authors:
        enrichment['authors'] = enriched_authors

    # Funders / grants — OpenAlex returns `grants[]` with funder name.
    grants = verified_data.get('grants')
    if isinstance(grants, list) and grants:
        funders = []
        seen = set()
        for g in grants:
            if not isinstance(g, dict):
                continue
            name = g.get('funder_display_name') or g.get('funder') or g.get('award_id')
            if name and name not in seen:
                funders.append(str(name))
                seen.add(name)
        if funders:
            enrichment['has_funding'] = True
            enrichment['funders'] = funders[:5]

    # Affiliation badge — at least one author institution present.
    if any(a.get('institutions') for a in (enrichment.get('authors') or [])):
        enrichment['has_affiliation'] = True

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
