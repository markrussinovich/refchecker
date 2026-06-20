"""References / Citations discovery for the Similar Papers panel.

A CLEAN, SEPARATE path from the intricate ``_find_similar_papers_impl``
co-citation/recommendation pipeline. It resolves the *source* paper to a
single OpenAlex Work and finds OTHER papers that overlap with it in two
bibliographically-distinct ways:

  * ``mode='references'`` — papers that SHARE REFERENCES with the source,
    i.e. other works whose bibliography overlaps the source's
    ``referenced_works``. Candidates are ranked by how many of the
    source's references they also cite.
  * ``mode='citations'`` — papers that SHARE CITATIONS with the source,
    i.e. other works that are co-cited alongside it. We walk the works
    that cite the source (``cites:<source>``) and surface the OTHER works
    those same citers reference; candidates are ranked by how many of the
    source's citers also cite them (co-citation strength).
  * ``mode='both'`` — the union of the two (shared-references candidates
    first, then shared-citations candidates not already surfaced).

Every candidate carries ``relation`` ('reference' for a shared-references
match, 'citation' for a shared-citations / co-cited match) plus
``shared_with_source`` (the overlap count that earned its place).

Everything is REAL OpenAlex data. When OpenAlex returns nothing (no
match for the source paper, or an empty neighbourhood), this returns an
empty list — it never fabricates candidates.

This module depends only on the stdlib + ``httpx`` (no project deps, no
FastAPI), so it imports and unit-tests in isolation under a bare Python.
"""

from typing import Any, Callable, Dict, List, Optional

OPENALEX_BASE = "https://api.openalex.org"

# Accepted public mode values plus backward-compat aliases. The Similar
# Papers panel historically shipped 'cites_refs' which meant "the source's
# direct references + the works that cite it". Its closest modern analogue
# is 'both' (shared references + shared citations), so we map it there.
_MODE_ALIASES = {
    "references": "references",
    "reference": "references",
    "citations": "citations",
    "citation": "citations",
    "both": "both",
    "cites_refs": "both",   # legacy name -> union
    "cites_and_refs": "both",
}


def normalize_mode(mode: Optional[str]) -> str:
    """Map a (possibly legacy) mode string to 'references'|'citations'|'both'.

    Unknown/empty values fall back to 'both' so an unexpected client value
    still returns the widest real neighbourhood rather than nothing.
    """
    key = (mode or "").strip().lower()
    return _MODE_ALIASES.get(key, "both")


def _oa_short_id(work_id: Optional[str]) -> Optional[str]:
    """``https://openalex.org/W123`` -> ``W123`` (leave bare ids alone)."""
    if not work_id:
        return None
    return work_id.rsplit("/", 1)[-1] or None


def _clean_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    d = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.lower().startswith(prefix):
            d = d[len(prefix):]
    return d.strip("/").strip() or None


def _looks_like_arxiv(paper_id: str) -> bool:
    pid = paper_id.strip().lower()
    if pid.startswith("arxiv:"):
        return True
    # modern (2304.01234) or legacy (cs/0112017) arXiv id shapes
    import re as _re
    return bool(_re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", pid) or "/" in pid and _re.match(r"^[a-z\-]+/\d{7}", pid))


def _work_to_candidate(w: Dict[str, Any], relation: str) -> Dict[str, Any]:
    """Normalise an OpenAlex Work record into a Similar-Papers candidate."""
    doi = _clean_doi(w.get("doi"))
    authors = [
        a.get("author", {}).get("display_name")
        for a in (w.get("authorships") or [])
        if a.get("author", {}).get("display_name")
    ]
    work_id = w.get("id")
    return {
        "title": w.get("title") or w.get("display_name"),
        "year": w.get("publication_year"),
        "authors": authors,
        "doi": doi,
        "arxiv_id": None,
        "openalex_id": _oa_short_id(work_id),
        "url": (f"https://doi.org/{doi}" if doi else work_id),
        "relation": relation,
    }


async def _resolve_source_work(
    fetch: Callable,
    *,
    paper_id: Optional[str],
    paper_title: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Resolve the SOURCE paper to a single OpenAlex Work.

    Order: DOI (from ``paper_id``) -> arXiv id -> title search. Returns
    the raw OpenAlex Work dict (with ``id`` and ``referenced_works``) or
    ``None`` when nothing matches. ``fetch(url, params)`` is an awaitable
    that returns the parsed JSON or ``None``.
    """
    select = "id,title,display_name,publication_year,referenced_works"
    pid = (paper_id or "").strip()

    if pid:
        doi = _clean_doi(pid)
        # A DOI input looks like 10.xxxx/...; arXiv ids don't start with "10."
        if doi and doi.lower().startswith("10."):
            data = await fetch(f"{OPENALEX_BASE}/works/doi:{doi}", {"select": select})
            if data and data.get("id"):
                return data
        if _looks_like_arxiv(pid):
            arxiv_clean = pid.split(":", 1)[-1] if ":" in pid else pid
            # OpenAlex indexes arXiv works; filter on the arXiv landing url.
            data = await fetch(
                f"{OPENALEX_BASE}/works",
                {
                    "filter": f"locations.landing_page_url:https://arxiv.org/abs/{arxiv_clean}",
                    "select": select,
                    "per-page": 1,
                },
            )
            results = (data or {}).get("results") or []
            if results:
                return results[0]

    if paper_title and paper_title.strip():
        data = await fetch(
            f"{OPENALEX_BASE}/works",
            {"filter": f"title.search:{paper_title.strip()}", "select": select, "per-page": 1},
        )
        results = (data or {}).get("results") or []
        if results and results[0].get("id"):
            return results[0]

    return None


async def _hydrate_works(
    fetch: Callable,
    work_ids: List[str],
    relation: str,
) -> List[Dict[str, Any]]:
    """Batch-resolve OpenAlex short ids to full candidate records.

    Uses the OpenAlex ``openalex_id`` OR filter (``W1|W2|...``) so each
    HTTP call hydrates up to 50 works at once. Real data only; ids that
    OpenAlex can't return simply don't appear.
    """
    out: List[Dict[str, Any]] = []
    select = "id,title,display_name,publication_year,authorships,doi"
    for i in range(0, len(work_ids), 50):
        batch = [wid for wid in work_ids[i : i + 50] if wid]
        if not batch:
            continue
        data = await fetch(
            f"{OPENALEX_BASE}/works",
            {"filter": f"openalex_id:{'|'.join(batch)}", "select": select, "per-page": 50},
        )
        for w in (data or {}).get("results", []) or []:
            out.append(_work_to_candidate(w, relation))
    return out


async def _shared_reference_candidates(
    fetch: Callable,
    *,
    source_short: str,
    referenced_works: List[str],
    per_relation: int,
) -> List[Dict[str, Any]]:
    """Papers that SHARE REFERENCES with the source.

    For each of the source's referenced works we ask OpenAlex which OTHER
    works also cite it (``cites:<refwork>``). A candidate that turns up
    across several of the source's references shares that many references
    with it; we rank by that shared count (then citation count). Real
    data only — when the source has no referenced works, this returns
    ``[]``.
    """
    ref_ids = [r for r in (_oa_short_id(r) for r in referenced_works) if r]
    if not ref_ids:
        return []

    # Probe a bounded sample of the source's references so a huge
    # bibliography doesn't fan out into hundreds of HTTP calls. The most
    # informative shared references are still captured for ranking.
    probe = ref_ids[: max(per_relation * 4, 12)]

    # work short id -> {record, shared, shared_ids} so we can tally overlap,
    # dedupe, and remember WHICH of the source's references each candidate
    # shares (the actual overlapping reference works — R08).
    tally: Dict[str, Dict[str, Any]] = {}
    select = "id,title,display_name,publication_year,authorships,doi"
    for ref_id in probe:
        data = await fetch(
            f"{OPENALEX_BASE}/works",
            {
                "filter": f"cites:{ref_id}",
                "select": select,
                "per-page": min(50, per_relation * 4),
                "sort": "cited_by_count:desc",
            },
        )
        for w in (data or {}).get("results", []) or []:
            wid = _oa_short_id(w.get("id"))
            if not wid or wid == source_short:
                continue
            entry = tally.get(wid)
            if entry is None:
                tally[wid] = {
                    "record": _work_to_candidate(w, "reference"),
                    "shared": 1,
                    # Set of the source's reference works this candidate also
                    # cites — the concrete shared works behind the count.
                    "shared_ids": {ref_id},
                }
            else:
                entry["shared"] += 1
                entry["shared_ids"].add(ref_id)

    ranked = sorted(tally.values(), key=lambda e: e["shared"], reverse=True)
    out: List[Dict[str, Any]] = []
    for entry in ranked:
        cand = dict(entry["record"])
        cand["shared_with_source"] = entry["shared"]
        # Ordered, stable list of the shared reference short ids (the works
        # that are actually shared) so the caller can hydrate their titles.
        cand["shared_ids"] = sorted(entry["shared_ids"])
        out.append(cand)
    return out


async def _shared_citation_candidates(
    fetch: Callable,
    *,
    source_short: str,
    per_relation: int,
) -> List[Dict[str, Any]]:
    """Papers that SHARE CITATIONS with the source (co-cited works).

    We walk the works that cite the source (``cites:<source>``) and look
    at what ELSE each of those citers references. A work that is
    referenced by several of the source's citers is co-cited with the
    source that many times; we rank by that co-citation count. Real data
    only — when nothing cites the source, this returns ``[]``.
    """
    # Pull the source's citers, including their bibliographies so we can
    # see which works they co-reference alongside the source.
    citing = await fetch(
        f"{OPENALEX_BASE}/works",
        {
            "filter": f"cites:{source_short}",
            "select": "id,referenced_works",
            "per-page": min(50, max(per_relation * 4, 10)),
            "sort": "cited_by_count:desc",
        },
    )
    citers = (citing or {}).get("results", []) or []
    if not citers:
        return []

    # co-referenced work short id -> times co-cited with the source.
    tally: Dict[str, int] = {}
    # co-referenced work short id -> set of the source's citers that co-cite
    # it. These citing works ARE the shared works behind a co-citation count
    # (the papers that reference both the source and this candidate) — R08.
    shared_citers: Dict[str, set] = {}
    for citer in citers:
        citer_short = _oa_short_id(citer.get("id"))
        for ref in (citer.get("referenced_works") or []):
            ref_short = _oa_short_id(ref)
            # Skip the source itself and the citer's self-reference.
            if not ref_short or ref_short == source_short or ref_short == citer_short:
                continue
            tally[ref_short] = tally.get(ref_short, 0) + 1
            if citer_short:
                shared_citers.setdefault(ref_short, set()).add(citer_short)

    if not tally:
        return []

    # Keep only genuinely co-cited works (shared by >= 2 citers) when we
    # have enough signal, so we don't surface every incidental reference.
    multi = {wid: n for wid, n in tally.items() if n >= 2}
    chosen = multi if multi else tally
    ranked = sorted(chosen.items(), key=lambda kv: kv[1], reverse=True)
    top_ids = [wid for wid, _ in ranked[: max(per_relation * 4, 12)]]

    hydrated = await _hydrate_works(fetch, top_ids, "citation")
    by_id = {c.get("openalex_id"): c for c in hydrated}
    out: List[Dict[str, Any]] = []
    for wid, n in ranked:
        cand = by_id.get(wid)
        if not cand:
            continue
        cand = dict(cand)
        cand["shared_with_source"] = n
        # The source's citers that co-cite this candidate (short ids) — the
        # concrete works that connect this candidate to the source.
        cand["shared_ids"] = sorted(shared_citers.get(wid, set()))
        out.append(cand)
    return out


async def fetch_cites_and_refs(
    fetch: Callable,
    candidate_key: Callable[[Optional[str], Optional[str], Optional[str]], str],
    *,
    paper_id: Optional[str],
    paper_title: Optional[str],
    limit: int = 5,
    mode: str = "both",
    want_references: Optional[bool] = None,
    want_citations: Optional[bool] = None,
) -> Dict[str, Any]:
    """Resolve the source paper on OpenAlex and return its real overlap.

    ``mode`` selects what kind of overlap to surface:

      * ``'references'`` — papers that share REFERENCES with the source
        (bibliography overlap). Each candidate carries
        ``relation='reference'``.
      * ``'citations'``  — papers that share CITATIONS with the source
        (co-cited works). Each candidate carries ``relation='citation'``.
      * ``'both'``       — the union of the two (references first).

    Legacy mode names ('cites_refs') are mapped via ``normalize_mode``.
    ``want_references`` / ``want_citations`` are kept for backward
    compatibility: when either is supplied it overrides ``mode`` and the
    corresponding overlap kind is included/excluded directly.

    Returns ``{"source_work": <shortid|None>, "candidates": [...]}``.
    Each candidate also carries ``shared_with_source`` (the overlap
    count that earned it a place). Deduped via ``candidate_key`` (the
    same key the similar path uses). Empty in -> empty out; never
    fabricated.
    """
    # Backward-compat: explicit want_* flags (old call sites) override mode.
    if want_references is not None or want_citations is not None:
        do_refs = True if want_references is None else bool(want_references)
        do_cites = True if want_citations is None else bool(want_citations)
    else:
        resolved = normalize_mode(mode)
        do_refs = resolved in ("references", "both")
        do_cites = resolved in ("citations", "both")

    source = await _resolve_source_work(fetch, paper_id=paper_id, paper_title=paper_title)
    if not source or not source.get("id"):
        return {"source_work": None, "candidates": []}

    source_short = _oa_short_id(source.get("id"))
    per_relation = max(1, int(limit or 5))

    candidates: List[Dict[str, Any]] = []
    seen: set = set()

    def _add(cand: Dict[str, Any]) -> None:
        key = candidate_key(cand.get("title"), cand.get("doi"), cand.get("arxiv_id"))
        # Don't let the source paper surface as its own neighbour.
        if cand.get("openalex_id") and cand["openalex_id"] == source_short:
            return
        if key in seen:
            return
        seen.add(key)
        candidates.append(cand)

    # (a) REFERENCES — papers that share references with the source.
    if do_refs:
        ref_cands = await _shared_reference_candidates(
            fetch,
            source_short=source_short,
            referenced_works=source.get("referenced_works") or [],
            per_relation=per_relation,
        )
        for cand in ref_cands:
            _add(cand)

    # (b) CITATIONS — papers that share citations with the source (co-cited).
    if do_cites and source_short:
        cite_cands = await _shared_citation_candidates(
            fetch,
            source_short=source_short,
            per_relation=per_relation,
        )
        for cand in cite_cands:
            _add(cand)

    # R08 — hydrate the shared OVERLAP works so the panel can show WHICH
    # works are shared (titles + links), not just a count. Each candidate
    # carries ``shared_ids`` (OpenAlex short ids of the works that connect it
    # to the source: shared references for 'reference' rows, co-citing works
    # for 'citation' rows). We resolve them all in one batched hydration pass
    # (cap to keep the call bounded) and project the real records onto each
    # candidate as ``shared_works`` / ``shared_works_titles``. Real data only:
    # ids OpenAlex can't return simply don't appear; never fabricated.
    await _attach_shared_works(fetch, candidates)

    return {"source_work": source_short, "candidates": candidates}


# How many shared works to hydrate per candidate at most, so a huge overlap
# set doesn't bloat the payload. The full count is always preserved via
# ``shared_with_source`` / ``shared_overlap_count``.
_MAX_SHARED_WORKS_PER_CAND = 10


async def _attach_shared_works(fetch: Callable, candidates: List[Dict[str, Any]]) -> None:
    """Resolve each candidate's ``shared_ids`` to real OpenAlex records.

    Mutates ``candidates`` in place, adding:

      * ``shared_works`` — up to ``_MAX_SHARED_WORKS_PER_CAND`` records
        ``{openalex_id, title, doi, url, year}`` for the works actually shared
        with the source (shared references for 'reference' rows, co-citing
        works for 'citation' rows).
      * ``shared_works_titles`` — the same works' titles (FE convenience).
      * ``shared_overlap_count`` — the true number of shared works.

    One batched hydration pass over the union of every candidate's
    (capped) shared ids. Real data only; unresolved ids are dropped.
    """
    # Collect the capped id set we actually want to show, union across rows.
    wanted: List[str] = []
    seen_ids: set = set()
    for cand in candidates:
        ids = cand.get("shared_ids") or []
        cand["shared_overlap_count"] = len(ids)
        for wid in ids[:_MAX_SHARED_WORKS_PER_CAND]:
            if wid and wid not in seen_ids:
                seen_ids.add(wid)
                wanted.append(wid)

    by_id: Dict[str, Dict[str, Any]] = {}
    if wanted:
        # 'shared' is just a hydration tag here; the records are projected
        # below — the relation tag on the OUTER candidate is what matters.
        hydrated = await _hydrate_works(fetch, wanted, "shared")
        for rec in hydrated:
            oid = rec.get("openalex_id")
            if oid:
                by_id[oid] = rec

    for cand in candidates:
        ids = (cand.get("shared_ids") or [])[:_MAX_SHARED_WORKS_PER_CAND]
        works: List[Dict[str, Any]] = []
        for wid in ids:
            rec = by_id.get(wid)
            if not rec:
                continue
            works.append({
                "openalex_id": rec.get("openalex_id"),
                "title": rec.get("title"),
                "doi": rec.get("doi"),
                "url": rec.get("url"),
                "year": rec.get("year"),
            })
        cand["shared_works"] = works
        cand["shared_works_titles"] = [w["title"] for w in works if w.get("title")]
        # Drop the internal id set from the public payload — the hydrated
        # works carry everything the FE needs.
        cand.pop("shared_ids", None)
