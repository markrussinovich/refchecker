"""Unit tests for the References / Citations discovery helper.

Exercises ``backend.cites_refs.fetch_cites_and_refs`` end-to-end against a
mocked httpx transport so the real ``httpx.AsyncClient`` + JSON parsing path
runs, but no live OpenAlex call is made.

The helper surfaces OTHER papers that overlap the source paper's bibliography:

  * ``mode='references'`` — papers that SHARE REFERENCES with the source
    (other works that also cite the source's references). relation='reference'.
  * ``mode='citations'``  — papers that SHARE CITATIONS with the source
    (works co-cited alongside it by the source's citers). relation='citation'.
  * ``mode='both'``       — the union.

REAL-DATA-ONLY contract is asserted: an unresolved source paper or an empty
neighbourhood yields zero candidates, never fabricated rows.
"""

import asyncio
import re
from urllib.parse import parse_qs, urlparse

import httpx

from backend.cites_refs import fetch_cites_and_refs, normalize_mode


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

# Same dedupe key the live similar-papers path uses (backend.main._candidate_key).
def _candidate_key(title, doi, arxiv):
    if doi:
        return f"doi:{doi.strip().lower()}"
    if arxiv:
        return f"arxiv:{arxiv.strip().lower()}"
    if title:
        norm = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
        return f"title:{norm}"
    return f"ghost:{id(title)}"


def _make_client(handler):
    """Build a real httpx.AsyncClient backed by a MockTransport handler."""
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


async def _run(handler, **kwargs):
    """Drive fetch_cites_and_refs with a _fetch closure over a mocked client."""
    async with _make_client(handler) as client:
        async def _fetch(url, params=None):
            r = await client.get(url, params=params)
            if r.status_code == 200:
                return r.json()
            return None

        return await fetch_cites_and_refs(
            _fetch, _candidate_key, **kwargs
        )


# Source Work the DOI resolves to: cites two referenced works (W_R1, W_R2).
SOURCE_WORK = {
    "id": "https://openalex.org/W_SRC",
    "title": "The Source Paper",
    "publication_year": 2020,
    "referenced_works": [
        "https://openalex.org/W_R1",
        "https://openalex.org/W_R2",
    ],
}

# Papers that SHARE REFERENCES with the source: they also cite W_R1 / W_R2.
# W_SHAREREF cites both of the source's references (shared = 2); W_ONEREF
# cites only one (shared = 1).
SHAREREF_BOTH = {
    "id": "https://openalex.org/W_SHAREREF",
    "title": "Shares Both References",
    "publication_year": 2019,
    "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
    "doi": "https://doi.org/10.1/shareref",
}
SHAREREF_ONE = {
    "id": "https://openalex.org/W_ONEREF",
    "title": "Shares One Reference",
    "publication_year": 2018,
    "authorships": [{"author": {"display_name": "Alan Turing"}}],
    "doi": None,
}

# A work that cites the source (W_SRC); its bibliography co-references W_COCITE
# alongside the source, making W_COCITE "co-cited" with the source.
CITER_WORK = {
    "id": "https://openalex.org/W_CITER",
    "referenced_works": [
        "https://openalex.org/W_SRC",     # cites the source
        "https://openalex.org/W_COCITE",  # co-cited alongside the source
    ],
}
CITER_WORK_2 = {
    "id": "https://openalex.org/W_CITER2",
    "referenced_works": [
        "https://openalex.org/W_SRC",
        "https://openalex.org/W_COCITE",  # second citer co-references it -> shared=2
    ],
}
COCITE_WORK = {
    "id": "https://openalex.org/W_COCITE",
    "title": "Co-cited Work",
    "publication_year": 2017,
    "authorships": [{"author": {"display_name": "Grace Hopper"}}],
    "doi": "https://doi.org/10.2/cocite",
}


def _full_handler(request: httpx.Request) -> httpx.Response:
    """Mock OpenAlex for the full References + Citations neighbourhood."""
    url = str(request.url)
    qs = parse_qs(urlparse(url).query)
    filt = (qs.get("filter") or [""])[0]

    # Source paper resolution by DOI.
    if "/works/doi:" in url:
        return httpx.Response(200, json=SOURCE_WORK)

    # SHARED REFERENCES: works that also cite one of the source's refs.
    if filt == "cites:W_R1":
        # Both shared-ref candidates cite W_R1.
        return httpx.Response(200, json={"results": [SHAREREF_BOTH, SHAREREF_ONE]})
    if filt == "cites:W_R2":
        # Only W_SHAREREF cites W_R2 too -> it shares 2 refs, W_ONEREF shares 1.
        return httpx.Response(200, json={"results": [SHAREREF_BOTH]})

    # SHARED CITATIONS: the source's citers (with their bibliographies).
    if filt == "cites:W_SRC":
        return httpx.Response(200, json={"results": [CITER_WORK, CITER_WORK_2]})

    # Batch hydration of co-cited work ids via the openalex_id OR filter.
    if filt.startswith("openalex_id:"):
        ids = filt[len("openalex_id:"):].split("|")
        table = {"W_COCITE": COCITE_WORK}
        results = [table[i] for i in ids if i in table]
        return httpx.Response(200, json={"results": results})

    # Title search fallback (not exercised here).
    if filt.startswith("title.search:"):
        return httpx.Response(200, json={"results": []})

    return httpx.Response(404, json={"results": []})


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #

def test_normalize_mode_maps_legacy_and_unknown():
    assert normalize_mode("references") == "references"
    assert normalize_mode("citations") == "citations"
    assert normalize_mode("both") == "both"
    # Legacy aliases.
    assert normalize_mode("cites_refs") == "both"
    assert normalize_mode("reference") == "references"
    assert normalize_mode("citation") == "citations"
    # Unknown / empty -> widest neighbourhood.
    assert normalize_mode("") == "both"
    assert normalize_mode(None) == "both"
    assert normalize_mode("similar") == "both"


def test_both_mode_returns_shared_refs_and_shared_cites():
    result = asyncio.run(
        _run(_full_handler, paper_id="10.1234/source", paper_title=None, limit=5, mode="both")
    )
    assert result["source_work"] == "W_SRC"
    cands = result["candidates"]
    by_rel = {}
    for c in cands:
        by_rel.setdefault(c["relation"], []).append(c)

    # Both relations present, tagged correctly.
    assert {c["relation"] for c in cands} == {"reference", "citation"}

    # Shared-references side: ranked by how many of the source's refs they share.
    refs = by_rel["reference"]
    assert {c["title"] for c in refs} == {"Shares Both References", "Shares One Reference"}
    top = refs[0]  # highest shared count first
    assert top["title"] == "Shares Both References"
    assert top["shared_with_source"] == 2
    assert top["doi"] == "10.1/shareref"  # https://doi.org/ stripped
    assert top["openalex_id"] == "W_SHAREREF"
    assert top["authors"] == ["Ada Lovelace"]
    one = next(c for c in refs if c["title"] == "Shares One Reference")
    assert one["shared_with_source"] == 1

    # Shared-citations side: the work co-referenced by both of the source's citers.
    cites = by_rel["citation"]
    assert len(cites) == 1
    cocite = cites[0]
    assert cocite["title"] == "Co-cited Work"
    assert cocite["doi"] == "10.2/cocite"
    assert cocite["openalex_id"] == "W_COCITE"
    assert cocite["shared_with_source"] == 2  # co-cited by 2 citers


def test_references_mode_only_returns_shared_reference_rows():
    """mode='references' suppresses the shared-citations (cites:<source>) query."""
    seen_filters = []

    def handler(request):
        qs = parse_qs(urlparse(str(request.url)).query)
        seen_filters.append((qs.get("filter") or [""])[0])
        return _full_handler(request)

    result = asyncio.run(
        _run(handler, paper_id="10.1234/source", paper_title=None, limit=5, mode="references")
    )
    assert {c["relation"] for c in result["candidates"]} == {"reference"}
    # The co-citation walk (cites:W_SRC) never runs in references-only mode.
    assert not any(f == "cites:W_SRC" for f in seen_filters)


def test_citations_mode_only_returns_shared_citation_rows():
    """mode='citations' suppresses the shared-references (cites:<refwork>) queries."""
    seen_filters = []

    def handler(request):
        qs = parse_qs(urlparse(str(request.url)).query)
        seen_filters.append((qs.get("filter") or [""])[0])
        return _full_handler(request)

    result = asyncio.run(
        _run(handler, paper_id="10.1234/source", paper_title=None, limit=5, mode="citations")
    )
    assert {c["relation"] for c in result["candidates"]} == {"citation"}
    # The shared-reference walk (cites:W_R1 / cites:W_R2) never runs.
    assert not any(f.startswith("cites:W_R") for f in seen_filters)


def test_unresolved_source_returns_empty_no_fabrication():
    """Source paper not found on OpenAlex -> empty, never invented rows."""

    def handler(request):
        # Every lookup misses.
        return httpx.Response(404, json={"results": []})

    result = asyncio.run(
        _run(handler, paper_id="10.9999/missing", paper_title="Nonexistent", limit=5, mode="both")
    )
    assert result == {"source_work": None, "candidates": []}


def test_empty_neighbourhood_returns_empty_candidates():
    """Source resolves but shares no refs and has no citers -> empty list."""

    def handler(request):
        url = str(request.url)
        qs = parse_qs(urlparse(url).query)
        filt = (qs.get("filter") or [""])[0]
        if "/works/doi:" in url:
            return httpx.Response(
                200,
                json={
                    "id": "https://openalex.org/W_LONELY",
                    "title": "A Lonely Paper",
                    "referenced_works": [],
                },
            )
        if filt.startswith("cites:"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={"results": []})

    result = asyncio.run(
        _run(handler, paper_id="10.1/lonely", paper_title=None, limit=5, mode="both")
    )
    assert result["source_work"] == "W_LONELY"
    assert result["candidates"] == []


def test_dedupe_collapses_duplicate_relation_rows():
    """A work that both shares references AND is co-cited appears once."""

    dup = {
        "id": "https://openalex.org/W_DUP",
        "title": "Appears Twice",
        "publication_year": 2019,
        "authorships": [],
        "doi": "https://doi.org/10.5/dup",
    }
    dup_citer = {
        "id": "https://openalex.org/W_DUPCITER",
        "referenced_works": [
            "https://openalex.org/W_SRC2",
            "https://openalex.org/W_DUP",  # co-cited alongside the source
        ],
    }

    def handler(request):
        url = str(request.url)
        qs = parse_qs(urlparse(url).query)
        filt = (qs.get("filter") or [""])[0]
        if "/works/doi:" in url:
            return httpx.Response(
                200,
                json={
                    "id": "https://openalex.org/W_SRC2",
                    "title": "Source Two",
                    "referenced_works": ["https://openalex.org/W_REF"],
                },
            )
        # Shared-references probe: W_DUP also cites the source's reference.
        if filt == "cites:W_REF":
            return httpx.Response(200, json={"results": [dup]})
        # Shared-citations: a citer co-references W_DUP alongside the source.
        if filt == "cites:W_SRC2":
            return httpx.Response(200, json={"results": [dup_citer]})
        if filt.startswith("openalex_id:"):
            return httpx.Response(200, json={"results": [dup]})
        return httpx.Response(200, json={"results": []})

    result = asyncio.run(
        _run(handler, paper_id="10.5/src2", paper_title=None, limit=5, mode="both")
    )
    # Deduped to a single row even though it came from both relations.
    dois = [c["doi"] for c in result["candidates"]]
    assert dois.count("10.5/dup") == 1


def test_title_only_resolution_uses_title_search():
    """No paper_id -> resolve via OpenAlex title.search filter."""

    def handler(request):
        url = str(request.url)
        qs = parse_qs(urlparse(url).query)
        filt = (qs.get("filter") or [""])[0]
        if filt.startswith("title.search:"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "https://openalex.org/W_TITLE",
                            "title": "Found By Title",
                            "referenced_works": [],
                        }
                    ]
                },
            )
        if filt.startswith("cites:"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404, json={"results": []})

    result = asyncio.run(
        _run(handler, paper_id=None, paper_title="Found By Title", limit=5, mode="both")
    )
    assert result["source_work"] == "W_TITLE"
    assert result["candidates"] == []


def test_want_flags_select_relation():
    """want_citations=False suppresses the shared-citations walk entirely."""
    seen_filters = []

    def handler(request):
        qs = parse_qs(urlparse(str(request.url)).query)
        seen_filters.append((qs.get("filter") or [""])[0])
        return _full_handler(request)

    result = asyncio.run(
        _run(
            handler,
            paper_id="10.1234/source",
            paper_title=None,
            limit=5,
            want_citations=False,
        )
    )
    assert {c["relation"] for c in result["candidates"]} == {"reference"}
    # No cites:<source> co-citation query ran.
    assert not any(f == "cites:W_SRC" for f in seen_filters)


# --------------------------------------------------------------------------- #
# R08 — surface WHICH works are shared, not just a count.                       #
# --------------------------------------------------------------------------- #

# Hydrated records for the source's reference works (the works that
# 'reference' candidates SHARE) and the co-citing works (the works that
# connect a 'citation' candidate to the source).
SHARED_REF_W_R1 = {
    "id": "https://openalex.org/W_R1",
    "title": "Foundational Reference One",
    "publication_year": 2005,
    "authorships": [{"author": {"display_name": "Ref Author 1"}}],
    "doi": "https://doi.org/10.3/r1",
}
SHARED_REF_W_R2 = {
    "id": "https://openalex.org/W_R2",
    "title": "Foundational Reference Two",
    "publication_year": 2008,
    "authorships": [],
    "doi": None,
}
CITER_W_CITER = {
    "id": "https://openalex.org/W_CITER",
    "title": "A Citing Paper",
    "publication_year": 2021,
    "authorships": [],
    "doi": "https://doi.org/10.4/citer1",
}
CITER_W_CITER2 = {
    "id": "https://openalex.org/W_CITER2",
    "title": "Another Citing Paper",
    "publication_year": 2022,
    "authorships": [],
    "doi": None,
}


def _r08_handler(request: httpx.Request) -> httpx.Response:
    """Like _full_handler but ALSO hydrates the shared reference works
    (W_R1/W_R2) and the co-citing works (W_CITER/W_CITER2) so the R08
    overlap-hydration pass returns real titles, not just ids."""
    url = str(request.url)
    qs = parse_qs(urlparse(url).query)
    filt = (qs.get("filter") or [""])[0]

    if "/works/doi:" in url:
        return httpx.Response(200, json=SOURCE_WORK)
    if filt == "cites:W_R1":
        return httpx.Response(200, json={"results": [SHAREREF_BOTH, SHAREREF_ONE]})
    if filt == "cites:W_R2":
        return httpx.Response(200, json={"results": [SHAREREF_BOTH]})
    if filt == "cites:W_SRC":
        return httpx.Response(200, json={"results": [CITER_WORK, CITER_WORK_2]})
    if filt.startswith("openalex_id:"):
        ids = filt[len("openalex_id:"):].split("|")
        table = {
            "W_COCITE": COCITE_WORK,
            "W_R1": SHARED_REF_W_R1,
            "W_R2": SHARED_REF_W_R2,
            "W_CITER": CITER_W_CITER,
            "W_CITER2": CITER_W_CITER2,
        }
        return httpx.Response(200, json={"results": [table[i] for i in ids if i in table]})
    if filt.startswith("title.search:"):
        return httpx.Response(200, json={"results": []})
    return httpx.Response(404, json={"results": []})


def test_reference_candidate_carries_hydrated_shared_works():
    """A 'reference' candidate exposes the ACTUAL shared reference works
    (hydrated titles + links), not just a shared count."""
    result = asyncio.run(
        _run(_r08_handler, paper_id="10.1234/source", paper_title=None, limit=5, mode="references")
    )
    cands = result["candidates"]
    shareref = next(c for c in cands if c["title"] == "Shares Both References")
    # Internal id set is dropped from the public payload.
    assert "shared_ids" not in shareref
    # The hydrated shared works carry real titles + the true overlap count.
    assert shareref["shared_overlap_count"] == 2
    titles = {w["title"] for w in shareref["shared_works"]}
    assert titles == {"Foundational Reference One", "Foundational Reference Two"}
    assert shareref["shared_works_titles"] == [w["title"] for w in shareref["shared_works"] if w.get("title")]
    # Real provenance flows through (a DOI on the one that has it).
    r1 = next(w for w in shareref["shared_works"] if w["title"] == "Foundational Reference One")
    assert r1["openalex_id"] == "W_R1"
    assert r1["doi"] == "10.3/r1"
    # The candidate that shares only one ref shows exactly that one work.
    oneref = next(c for c in cands if c["title"] == "Shares One Reference")
    assert oneref["shared_overlap_count"] == 1
    assert [w["title"] for w in oneref["shared_works"]] == ["Foundational Reference One"]


def test_citation_candidate_carries_hydrated_cociting_works():
    """A 'citation' (co-cited) candidate exposes the ACTUAL co-citing works
    that connect it to the source — the works shared between them."""
    result = asyncio.run(
        _run(_r08_handler, paper_id="10.1234/source", paper_title=None, limit=5, mode="citations")
    )
    cocite = next(c for c in result["candidates"] if c["title"] == "Co-cited Work")
    assert cocite["shared_overlap_count"] == 2
    titles = {w["title"] for w in cocite["shared_works"]}
    assert titles == {"A Citing Paper", "Another Citing Paper"}


def test_shared_works_empty_when_overlap_unresolvable_no_fabrication():
    """When the shared overlap ids can't be hydrated, shared_works is empty —
    the count is still reported, but no titles are invented (real-data gate)."""

    def handler(request):
        url = str(request.url)
        qs = parse_qs(urlparse(url).query)
        filt = (qs.get("filter") or [""])[0]
        if "/works/doi:" in url:
            return httpx.Response(200, json=SOURCE_WORK)
        if filt in ("cites:W_R1", "cites:W_R2"):
            return httpx.Response(200, json={"results": [SHAREREF_BOTH]})
        if filt == "cites:W_SRC":
            return httpx.Response(200, json={"results": []})
        # Hydration of the shared reference works returns NOTHING.
        if filt.startswith("openalex_id:"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404, json={"results": []})

    result = asyncio.run(
        _run(handler, paper_id="10.1234/source", paper_title=None, limit=5, mode="references")
    )
    shareref = next(c for c in result["candidates"] if c["title"] == "Shares Both References")
    # Count preserved, but no fabricated titles.
    assert shareref["shared_overlap_count"] == 2
    assert shareref["shared_works"] == []
    assert shareref["shared_works_titles"] == []
