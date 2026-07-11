"""Retraction signal for cited references, from OpenAlex's real `is_retracted`.

Honesty rules (no fabricated retractions):
  * A reference is flagged "retracted" ONLY when OpenAlex reports
    is_retracted == true for its DOI.
  * No DOI            -> "no_doi"  (cannot be checked).
  * DOI not in OpenAlex -> "unknown" (absence of evidence, never "clean").
  * DOI present, not retracted -> "clean".

The HTTP fetch is injectable so the assembly logic is unit-tested without
network. OpenAlex is free and keyless; we send a mailto for the polite pool.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

_OPENALEX = "https://api.openalex.org/works"
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)


def normalize_doi(raw: Any) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip().lower()
    for pre in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if s.startswith(pre):
            s = s[len(pre):]
    m = _DOI_RE.search(s)
    if not m:
        return None
    return m.group(0).rstrip(".,;)")


def _default_fetch(dois: List[str]) -> Dict[str, Dict[str, Any]]:
    """Batch-query OpenAlex for is_retracted. Returns {doi: {is_retracted, title}}."""
    import httpx
    out: Dict[str, Dict[str, Any]] = {}
    # A '|' in a DOI would corrupt the OR-filter; such a value is not a valid
    # DOI anyway (normalize_doi would not have produced one), so drop defensively.
    dois = [d for d in dois if "|" not in d]
    for i in range(0, len(dois), 40):  # OpenAlex OR-filter caps ~50 per request
        chunk = dois[i:i + 40]
        params = {
            "filter": "doi:" + "|".join(chunk),
            "select": "doi,is_retracted,display_name",
            "per-page": 50,
            "mailto": "refchecker@local",
        }
        try:
            r = httpx.get(_OPENALEX, params=params, timeout=20.0)
            if r.status_code != 200:
                continue
            for w in (r.json().get("results") or []):
                d = normalize_doi(w.get("doi"))
                if d:
                    out[d] = {"is_retracted": bool(w.get("is_retracted")),
                              "title": w.get("display_name")}
        except Exception:
            continue
    return out


def check_retractions(references: Any,
                      fetch: Optional[Callable[[List[str]], Dict[str, Dict[str, Any]]]] = None) -> Dict[str, Any]:
    fetch = fetch or _default_fetch
    refs = references if isinstance(references, list) else []
    items: List[Dict[str, Any]] = []
    for idx, ref in enumerate(refs):
        if not isinstance(ref, dict):
            continue
        doi = normalize_doi(ref.get("doi") or ref.get("verified_doi"))
        items.append({
            "index": ref.get("index") or ref.get("ref_num") or (idx + 1),
            "title": ref.get("title") or "",
            "doi": doi,
            "status": "no_doi",
        })
    dois = list(dict.fromkeys(it["doi"] for it in items if it["doi"]))
    lookup = fetch(dois) if dois else {}
    retracted = 0
    for it in items:
        d = it["doi"]
        if not d:
            it["status"] = "no_doi"
        elif d in lookup:
            is_ret = bool(lookup[d].get("is_retracted"))
            it["status"] = "retracted" if is_ret else "clean"
            if is_ret:
                retracted += 1
                if lookup[d].get("title"):
                    it["openalex_title"] = lookup[d]["title"]
        else:
            it["status"] = "unknown"
    return {
        "checked": len(items),
        "with_doi": len(dois),
        "retracted": retracted,
        "results": items,
        "source": "openalex",
    }
