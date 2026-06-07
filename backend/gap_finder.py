"""Reference gap-finder: "papers you may have missed".

Signal (real, no fabrication): collect the works that the paper's OWN cited
references themselves cite (OpenAlex `referenced_works`), count how often each is
co-cited across the bibliography, and surface the most-frequently co-cited works
that are NOT already in the bibliography. Only works OpenAlex can resolve to a
real title are returned — nothing invented.

Framing in the UI must stay advisory: "frequently co-cited by your references,
not in your bibliography" — a discovery aid, not a claim that they are required.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Dict, List, Optional

from backend.retraction import normalize_doi

_OPENALEX = "https://api.openalex.org/works"
_MAILTO = "refchecker@local"


def _short_id(oa_id: str) -> str:
    return (oa_id or "").rstrip("/").rsplit("/", 1)[-1]


def _default_fetch_refs(dois: List[str]) -> Dict[str, Dict[str, Any]]:
    """{doi: {id, referenced_works}} for each bibliography DOI."""
    import httpx
    out: Dict[str, Dict[str, Any]] = {}
    dois = [d for d in dois if "|" not in d]
    for i in range(0, len(dois), 40):
        chunk = dois[i:i + 40]
        params = {"filter": "doi:" + "|".join(chunk),
                  "select": "id,doi,referenced_works", "per-page": 50, "mailto": _MAILTO}
        try:
            r = httpx.get(_OPENALEX, params=params, timeout=25.0)
            if r.status_code != 200:
                continue
            for w in (r.json().get("results") or []):
                d = normalize_doi(w.get("doi"))
                if d:
                    out[d] = {"id": w.get("id"), "referenced_works": w.get("referenced_works") or []}
        except Exception:
            continue
    return out


def _default_fetch_titles(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """{openalex_id: {title, doi, year, cited_by_count}} for candidate works."""
    import httpx
    out: Dict[str, Dict[str, Any]] = {}
    short = [_short_id(i) for i in ids if i]
    for k in range(0, len(short), 40):
        chunk = short[k:k + 40]
        params = {"filter": "openalex_id:" + "|".join(chunk),
                  "select": "id,title,doi,publication_year,cited_by_count", "per-page": 50, "mailto": _MAILTO}
        try:
            r = httpx.get(_OPENALEX, params=params, timeout=25.0)
            if r.status_code != 200:
                continue
            for w in (r.json().get("results") or []):
                if w.get("id"):
                    out[w["id"]] = {
                        "title": w.get("title"),
                        "doi": normalize_doi(w.get("doi")),
                        "year": w.get("publication_year"),
                        "cited_by_count": w.get("cited_by_count"),
                    }
        except Exception:
            continue
    return out


def find_gaps(references: Any,
              fetch_refs: Optional[Callable[[List[str]], Dict[str, Dict[str, Any]]]] = None,
              fetch_titles: Optional[Callable[[List[str]], Dict[str, Dict[str, Any]]]] = None,
              min_co: int = 2, top_n: int = 10) -> Dict[str, Any]:
    fetch_refs = fetch_refs or _default_fetch_refs
    fetch_titles = fetch_titles or _default_fetch_titles
    refs = references if isinstance(references, list) else []
    dois = list(dict.fromkeys(
        normalize_doi(r.get("doi") or r.get("verified_doi"))
        for r in refs if isinstance(r, dict) and normalize_doi(r.get("doi") or r.get("verified_doi"))
    ))
    if not dois:
        return {"checked": 0, "analyzed": 0, "suggestions": [], "source": "openalex",
                "note": "No DOIs in the bibliography to analyze."}

    meta = fetch_refs(dois)
    own_ids = {m["id"] for m in meta.values() if m.get("id")}
    counter: Counter = Counter()
    for m in meta.values():
        for rw in (m.get("referenced_works") or []):
            if rw and rw not in own_ids:
                counter[rw] += 1

    candidates = [(wid, c) for wid, c in counter.items() if c >= min_co]
    candidates.sort(key=lambda x: -x[1])
    top = candidates[:top_n]
    titles = fetch_titles([wid for wid, _ in top]) if top else {}

    suggestions = []
    for wid, c in top:
        t = titles.get(wid)
        if not t or not t.get("title"):
            continue  # only surface works we could resolve to a real title
        suggestions.append({"openalex_id": wid, "co_citations": c, **t})

    return {"checked": len(dois), "analyzed": len(meta),
            "suggestions": suggestions, "source": "openalex"}
