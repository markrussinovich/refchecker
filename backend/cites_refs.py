"""Cites & References discovery for the Similar Papers panel (issue #63).

A CLEAN, SEPARATE path from the intricate ``_find_similar_papers_impl``
co-citation/recommendation pipeline. Instead of "papers that share the
most references", this resolves the *source* paper to a single OpenAlex
Work and reads its real citation neighbourhood:

  * ``relation='reference'`` — the works the source paper itself cites
    (``Work.referenced_works``).
  * ``relation='citation'`` — the works that cite the source paper
    (``/works?filter=cites:<workid>``).

Everything is REAL OpenAlex data. When OpenAlex returns nothing (no
match for the source paper, or an empty neighbourhood), this returns an
empty list — it never fabricates candidates.

This module depends only on the stdlib + ``httpx`` (no project deps, no
FastAPI), so it imports and unit-tests in isolation under a bare Python.
"""

from typing import Any, Callable, Dict, List, Optional

OPENALEX_BASE = "https://api.openalex.org"


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


async def fetch_cites_and_refs(
    fetch: Callable,
    candidate_key: Callable[[Optional[str], Optional[str], Optional[str]], str],
    *,
    paper_id: Optional[str],
    paper_title: Optional[str],
    limit: int = 5,
    want_references: bool = True,
    want_citations: bool = True,
) -> Dict[str, Any]:
    """Resolve the source paper on OpenAlex and return its real cites/refs.

    Returns ``{"source_work": <shortid|None>, "candidates": [...]}`` where
    each candidate carries ``relation`` in {``reference``, ``citation``}.
    Deduped via ``candidate_key`` (the same key the similar path uses).
    Empty in -> empty out; never fabricated.
    """
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

    # (a) REFERENCES — works the source paper cites.
    if want_references:
        ref_ids = [_oa_short_id(r) for r in (source.get("referenced_works") or [])]
        ref_ids = [r for r in ref_ids if r][: per_relation * 4]
        for cand in await _hydrate_works(fetch, ref_ids, "reference"):
            _add(cand)

    # (b) CITATIONS — works that cite the source paper.
    if want_citations and source_short:
        citing = await fetch(
            f"{OPENALEX_BASE}/works",
            {
                "filter": f"cites:{source_short}",
                "select": "id,title,display_name,publication_year,authorships,doi",
                "per-page": min(50, per_relation * 4),
                "sort": "cited_by_count:desc",
            },
        )
        for w in (citing or {}).get("results", []) or []:
            _add(_work_to_candidate(w, "citation"))

    return {"source_work": source_short, "candidates": candidates}
