"""R17 (G3) — dedup/validity guard on the manual "add reference" path.

`POST /api/history/<id>/references` must reject a reference that already exists
in the check (by normalized DOI, arXiv id, or lowercased title) with HTTP 409
and a ``{duplicate, existing_index}`` envelope, so the UI can say "already
reference [N]" instead of silently creating a duplicate row that would pollute
the renumbering map and the exported reference list.
"""

import pytest


@pytest.fixture
def add_ref_client(monkeypatch):
    """FastAPI TestClient over the real route with auth + db stubbed offline.

    The stubbed ``db`` holds a small in-memory reference list (a verified DOI,
    an arXiv-only ref, and a title-only ref) and records every
    ``replace_check_references`` so a test can assert whether an insert actually
    happened.
    """
    from fastapi.testclient import TestClient
    from backend import main as backend_main
    from backend.auth import UserInfo, require_user

    app = backend_main.app
    app.dependency_overrides[require_user] = lambda: UserInfo(id=1, provider="test")

    existing = [
        {"id": "a", "index": 1, "title": "Attention Is All You Need",
         "doi": "https://doi.org/10.5555/ABC.123"},
        {"id": "b", "index": 2, "title": "BERT Pretraining",
         "arxiv_id": "arXiv:1810.04805v2"},
        {"id": "c", "index": 3, "title": "A Title-Only Reference"},
    ]
    captured = {"replaced": None}

    async def _get_check_references(check_id, user_id=None):
        if check_id != 42:
            return None
        # Return a copy so the route mutating it doesn't corrupt our fixture.
        return [dict(r) for r in existing]

    async def _replace_check_references(check_id, results, user_id=None):
        captured["replaced"] = results
        return True

    monkeypatch.setattr(backend_main.db, "get_check_references", _get_check_references)
    monkeypatch.setattr(backend_main.db, "replace_check_references", _replace_check_references)

    client = TestClient(app)
    try:
        yield client, captured
    finally:
        app.dependency_overrides.clear()


def _post(client, payload):
    return client.post("/api/history/42/references", json=payload)


def test_duplicate_doi_different_casing_and_prefix_is_409(add_ref_client):
    """A DOI that differs only by resolver prefix + casing is a duplicate."""
    client, captured = add_ref_client
    # Stored as https://doi.org/10.5555/ABC.123 — submit the bare, lowercased form.
    resp = _post(client, {"title": "Whatever", "doi": "10.5555/abc.123"})
    assert resp.status_code == 409
    body = resp.json()
    assert body["duplicate"] is True
    assert body["existing_index"] == 1
    # Nothing was written — the duplicate was rejected before the insert.
    assert captured["replaced"] is None


def test_duplicate_title_only_case_insensitive_is_409(add_ref_client):
    """A title-only match (no DOI/arXiv on either side) is a duplicate too."""
    client, captured = add_ref_client
    resp = _post(client, {"title": "  a TITLE-only   reference  "})
    assert resp.status_code == 409
    assert resp.json()["existing_index"] == 3
    assert captured["replaced"] is None


def test_duplicate_arxiv_version_normalized_is_409(add_ref_client):
    """arXiv ids compare equal across scheme prefix + version suffix."""
    client, captured = add_ref_client
    resp = _post(client, {"title": "BERT, again", "arxiv_id": "1810.04805"})
    assert resp.status_code == 409
    assert resp.json()["existing_index"] == 2
    assert captured["replaced"] is None


def test_new_reference_is_inserted(add_ref_client):
    """A genuinely new reference (no DOI/arXiv/title collision) is added."""
    client, captured = add_ref_client
    resp = _post(client, {"title": "A Brand New Work", "doi": "10.1234/new", "year": 2024})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_refs"] == 4
    assert body["inserted_index"] == 4
    # The insert was actually persisted.
    assert captured["replaced"] is not None
    assert any(r.get("doi") == "10.1234/new" for r in captured["replaced"])


def test_missing_check_is_404(add_ref_client):
    client, _captured = add_ref_client
    resp = client.post("/api/history/999/references", json={"title": "x"})
    assert resp.status_code == 404
