"""Unit tests for the reference gap-finder (OpenAlex co-citation, no fabrication)."""

from backend import gap_finder


def _refs():
    return [
        {"index": 1, "title": "Paper A", "doi": "10.1000/a"},
        {"index": 2, "title": "Paper B", "doi": "https://doi.org/10.1000/b"},
        {"index": 3, "title": "Paper C", "doi": "10.1000/c"},
        {"index": 4, "title": "No DOI"},
    ]


# Bibliography OpenAlex ids: A=W_A, B=W_B, C=W_C.
# W_MISS is co-cited by A and B (count 2) and is NOT in the bibliography -> gap.
# W_B is cited by A but it IS in the bibliography -> excluded.
# W_ONCE is cited only by C (count 1) -> below min_co.
def _fetch_refs(dois):
    table = {
        "10.1000/a": {"id": "W_A", "referenced_works": ["W_MISS", "W_B", "W_ONCE0"]},
        "10.1000/b": {"id": "W_B", "referenced_works": ["W_MISS", "W_A"]},
        "10.1000/c": {"id": "W_C", "referenced_works": ["W_ONCE"]},
    }
    return {d: table[d] for d in dois if d in table}


def _fetch_titles(ids):
    table = {
        "W_MISS": {"title": "The Missed Seminal Work", "doi": "10.9/miss", "year": 2018, "cited_by_count": 5000},
        "W_ONCE": {"title": "Cited Once", "doi": "10.9/once", "year": 2020, "cited_by_count": 3},
    }
    return {i: table[i] for i in ids if i in table}


def test_finds_co_cited_missing_work():
    res = gap_finder.find_gaps(_refs(), fetch_refs=_fetch_refs, fetch_titles=_fetch_titles, min_co=2)
    titles = [s["title"] for s in res["suggestions"]]
    assert "The Missed Seminal Work" in titles
    miss = next(s for s in res["suggestions"] if s["title"] == "The Missed Seminal Work")
    assert miss["co_citations"] == 2
    assert miss["doi"] == "10.9/miss"
    assert res["source"] == "openalex"


def test_excludes_works_already_in_bibliography():
    res = gap_finder.find_gaps(_refs(), fetch_refs=_fetch_refs, fetch_titles=_fetch_titles, min_co=2)
    # W_A / W_B are in the bibliography and must never be suggested.
    assert all(s["openalex_id"] not in ("W_A", "W_B") for s in res["suggestions"])


def test_min_co_filters_singletons():
    res = gap_finder.find_gaps(_refs(), fetch_refs=_fetch_refs, fetch_titles=_fetch_titles, min_co=2)
    assert all(s["co_citations"] >= 2 for s in res["suggestions"])
    assert all(s["title"] != "Cited Once" for s in res["suggestions"])


def test_only_resolvable_titles_surface():
    # A candidate the title-fetch cannot resolve is dropped (no fabricated title).
    res = gap_finder.find_gaps(_refs(), fetch_refs=_fetch_refs, fetch_titles=lambda ids: {}, min_co=2)
    assert res["suggestions"] == []


def test_no_dois_returns_empty_note():
    res = gap_finder.find_gaps([{"index": 1, "title": "x"}], fetch_refs=_fetch_refs, fetch_titles=_fetch_titles)
    assert res["suggestions"] == []
    assert res["checked"] == 0
    assert "note" in res
