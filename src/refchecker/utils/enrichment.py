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
    authors              list  — [{name, orcid, openalex_id}]
    source_label         str   — which checker produced the match

Anything we can't extract is left out of the dict — the UI treats
missing fields as "no signal" rather than zero.
"""

from typing import Any, Dict, List, Optional


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
    s = str(openalex_url)
    if 'openalex.org/' in s:
        return s.rsplit('/', 1)[-1]
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

    # Publication type
    pub_type = (
        verified_data.get('type')
        or verified_data.get('publicationVenue', {}).get('type')
        if isinstance(verified_data.get('publicationVenue'), dict)
        else None
    ) or verified_data.get('type')
    if isinstance(pub_type, str):
        enrichment['publication_type'] = pub_type

    # Fields of study — OpenAlex concepts; S2 has `fieldsOfStudy`.
    fos = _fields_of_study_from_openalex(verified_data.get('concepts') or [])
    if not fos:
        s2_fos = verified_data.get('fieldsOfStudy')
        if isinstance(s2_fos, list):
            fos = [f for f in s2_fos[:3] if f]
    if fos:
        enrichment['fields_of_study'] = fos

    # Authors with ORCID — works for OpenAlex shape (`authorships` with
    # author.display_name + author.orcid + institutions) and Crossref
    # shape (`author` with given/family/ORCID).
    authorships = verified_data.get('authorships')
    if not authorships and isinstance(verified_data.get('author'), list):
        authorships = verified_data['author']
    enriched_authors = _extract_authors_with_orcid(authorships or [])
    if enriched_authors:
        enrichment['authors'] = enriched_authors

    # Which checker produced this — the enhanced_hybrid_checker stamps
    # _matched_database / _matched_checker on the dict before it lands
    # here, so surface that for the UI's "Matched DB:" chip.
    if verified_data.get('_matched_database'):
        enrichment['source_label'] = verified_data['_matched_database']
    elif verified_data.get('_matched_checker'):
        enrichment['source_label'] = verified_data['_matched_checker']
    elif verified_data.get('source'):
        enrichment['source_label'] = verified_data['source']

    return enrichment
