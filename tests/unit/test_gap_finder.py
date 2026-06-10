"""Unit tests for the reference gap-finder (OpenAlex co-citation, no fabrication).

Also covers the R39 route smoke test: ``GET /api/check/<id>/gaps`` must return
a real JSON envelope (not the SPA catch-all HTML), so the frontend's 404
friendly-message branch only ever fires on a genuinely missing route.
"""

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


# --------------------------------------------------------------------------- #
# R39 — route smoke test: GET /api/check/<id>/gaps returns JSON, not SPA HTML.  #
# --------------------------------------------------------------------------- #

def _gaps_test_client(monkeypatch):
    """Build a FastAPI TestClient with auth + db + find_gaps stubbed offline.

    Returns ``(client, captured)`` where ``captured`` records the references
    handed to find_gaps so the test can assert the route wired them through.
    """
    from fastapi.testclient import TestClient
    from backend import main as backend_main
    from backend.auth import UserInfo, require_user

    # Authenticated user (bypass the real OAuth dependency).
    app = backend_main.app
    app.dependency_overrides[require_user] = lambda: UserInfo(id=1, provider="test")

    # A real, owned check with two DOI-bearing references.
    fake_check = {
        "id": 42,
        "results": [
            {"index": 1, "title": "Paper A", "doi": "10.1000/a"},
            {"index": 2, "title": "Paper B", "doi": "10.1000/b"},
        ],
    }

    async def _fake_get_check_by_id(check_id, user_id=None):
        return fake_check if check_id == 42 else None

    monkeypatch.setattr(backend_main.db, "get_check_by_id", _fake_get_check_by_id)

    captured = {}

    def _fake_find_gaps(refs, **_kw):
        captured["refs"] = refs
        return {
            "source": "openalex",
            "checked": 2,
            "suggestions": [
                {"openalex_id": "W_MISS", "title": "A Missed Work", "co_citations": 2,
                 "doi": "10.9/miss", "year": 2019, "resolved": True},
            ],
            "note": None,
        }

    # The route does `from backend.gap_finder import find_gaps` at call time,
    # so patching the module attribute swaps the implementation it imports.
    monkeypatch.setattr(gap_finder, "find_gaps", _fake_find_gaps)

    return TestClient(app), captured, fake_check


def test_gaps_route_returns_json_not_spa_catch_all(monkeypatch):
    """GET /api/check/<id>/gaps -> 200 with a real JSON body (the route is
    served by the API, never falling through to the SPA index HTML)."""
    client, captured, fake_check = _gaps_test_client(monkeypatch)
    try:
        resp = client.get("/api/check/42/gaps")
        assert resp.status_code == 200
        # Genuine JSON content-type, not text/html SPA fallback.
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()  # raises if the body weren't JSON
        assert body["source"] == "openalex"
        assert isinstance(body["suggestions"], list)
        assert body["suggestions"][0]["title"] == "A Missed Work"
        # The route handed the check's references through to find_gaps.
        assert captured["refs"] == fake_check["results"]
    finally:
        client.app.dependency_overrides.clear()


def test_gaps_route_missing_check_is_404_json(monkeypatch):
    """A missing check returns a 404 with a JSON detail (the handler's own
    HTTPException), distinct from the route itself being absent."""
    client, _captured, _fake = _gaps_test_client(monkeypatch)
    try:
        resp = client.get("/api/check/999/gaps")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json().get("detail") == "Check not found"
    finally:
        client.app.dependency_overrides.clear()
