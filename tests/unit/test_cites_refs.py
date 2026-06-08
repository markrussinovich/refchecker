"""Unit tests for the Cites & Refs discovery helper (issue #63).

Exercises ``backend.cites_refs.fetch_cites_and_refs`` end-to-end against a
mocked httpx transport so the real ``httpx.AsyncClient`` + JSON parsing path
runs, but no live OpenAlex call is made. REAL-DATA-ONLY contract is asserted:
an unresolved source paper or an empty neighbourhood yields zero candidates,
never fabricated rows.
"""

import asyncio
import re
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend.cites_refs import fetch_cites_and_refs


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

# Hydrated reference works (what referenced_works ids resolve to).
REF_WORKS = {
    "W_R1": {
        "id": "https://openalex.org/W_R1",
        "title": "Referenced Work One",
        "publication_year": 2015,
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        "doi": "https://doi.org/10.1/ref1",
    },
    "W_R2": {
        "id": "https://openalex.org/W_R2",
        "title": "Referenced Work Two",
        "publication_year": 2016,
        "authorships": [{"author": {"display_name": "Alan Turing"}}],
        "doi": None,
    },
}

# Works that cite the source paper.
CITING_WORKS = [
    {
        "id": "https://openalex.org/W_C1",
        "title": "Citing Work One",
        "publication_year": 2022,
        "authorships": [{"author": {"display_name": "Grace Hopper"}}],
        "doi": "https://doi.org/10.2/cite1",
    },
]


def _full_handler(request: httpx.Request) -> httpx.Response:
    """Mock OpenAlex: DOI resolve, batch hydrate (OR filter), cites filter."""
    url = str(request.url)
    qs = parse_qs(urlparse(url).query)
    filt = (qs.get("filter") or [""])[0]

    # Source paper resolution by DOI.
    if "/works/doi:" in url:
        return httpx.Response(200, json=SOURCE_WORK)

    # Batch hydration of referenced_works via the openalex_id OR filter.
    if filt.startswith("openalex_id:"):
        ids = filt[len("openalex_id:"):].split("|")
        results = [REF_WORKS[i] for i in ids if i in REF_WORKS]
        return httpx.Response(200, json={"results": results})

    # Works that cite the source.
    if filt.startswith("cites:"):
        return httpx.Response(200, json={"results": CITING_WORKS})

    # Title search fallback (not exercised here).
    if filt.startswith("title.search:"):
        return httpx.Response(200, json={"results": []})

    return httpx.Response(404, json={"results": []})


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #

def test_resolves_doi_and_returns_refs_and_citations():
    result = asyncio.run(
        _run(_full_handler, paper_id="10.1234/source", paper_title=None, limit=5)
    )
    assert result["source_work"] == "W_SRC"
    cands = result["candidates"]
    by_rel = {}
    for c in cands:
        by_rel.setdefault(c["relation"], []).append(c)

    # Both relations present, tagged correctly.
    assert {c["relation"] for c in cands} == {"reference", "citation"}
    assert len(by_rel["reference"]) == 2
    assert len(by_rel["citation"]) == 1

    refs = sorted(by_rel["reference"], key=lambda c: c["title"])
    assert refs[0]["title"] == "Referenced Work One"
    assert refs[0]["doi"] == "10.1/ref1"  # https://doi.org/ stripped
    assert refs[0]["openalex_id"] == "W_R1"
    assert refs[0]["authors"] == ["Ada Lovelace"]

    cite = by_rel["citation"][0]
    assert cite["title"] == "Citing Work One"
    assert cite["doi"] == "10.2/cite1"
    assert cite["openalex_id"] == "W_C1"


def test_unresolved_source_returns_empty_no_fabrication():
    """Source paper not found on OpenAlex -> empty, never invented rows."""

    def handler(request):
        # Every lookup misses.
        return httpx.Response(404, json={"results": []})

    result = asyncio.run(
        _run(handler, paper_id="10.9999/missing", paper_title="Nonexistent", limit=5)
    )
    assert result == {"source_work": None, "candidates": []}


def test_empty_neighbourhood_returns_empty_candidates():
    """Source resolves but has no refs and nothing cites it -> empty list."""

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
        _run(handler, paper_id="10.1/lonely", paper_title=None, limit=5)
    )
    assert result["source_work"] == "W_LONELY"
    assert result["candidates"] == []


def test_dedupe_collapses_duplicate_relation_rows():
    """A work appearing as both a reference id and a citing result is deduped."""

    dup_doi_work = {
        "id": "https://openalex.org/W_DUP",
        "title": "Appears Twice",
        "publication_year": 2019,
        "authorships": [],
        "doi": "https://doi.org/10.5/dup",
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
                    "referenced_works": ["https://openalex.org/W_DUP"],
                },
            )
        if filt.startswith("openalex_id:"):
            return httpx.Response(200, json={"results": [dup_doi_work]})
        if filt.startswith("cites:"):
            # Same DOI surfaces again as a citing work.
            return httpx.Response(200, json={"results": [dup_doi_work]})
        return httpx.Response(200, json={"results": []})

    result = asyncio.run(
        _run(handler, paper_id="10.5/src2", paper_title=None, limit=5)
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
        _run(handler, paper_id=None, paper_title="Found By Title", limit=5)
    )
    assert result["source_work"] == "W_TITLE"
    assert result["candidates"] == []


def test_want_flags_select_relation():
    """want_citations=False suppresses the cites filter entirely."""
    seen_filters = []

    def handler(request):
        url = str(request.url)
        qs = parse_qs(urlparse(url).query)
        filt = (qs.get("filter") or [""])[0]
        seen_filters.append(filt)
        if "/works/doi:" in url:
            return httpx.Response(200, json=SOURCE_WORK)
        if filt.startswith("openalex_id:"):
            ids = filt[len("openalex_id:"):].split("|")
            return httpx.Response(
                200, json={"results": [REF_WORKS[i] for i in ids if i in REF_WORKS]}
            )
        if filt.startswith("cites:"):
            return httpx.Response(200, json={"results": CITING_WORKS})
        return httpx.Response(404, json={"results": []})

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
    assert not any(f.startswith("cites:") for f in seen_filters)
