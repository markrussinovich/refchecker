"""Regression: GET /api/paper-text/{id} must surface the body for a *pasted*
text / .bib / .bbl source (source_type == 'text').

BUG: the DocumentViewer ("native viewer for extracted context") showed nothing
for checks created by pasting a bibliography or text. The endpoint only handled
source_type=='file' and the cached-PDF lookup; a structured/text source matched
neither, so it returned available=False and the viewer said "the original
document text isn't available". The fix reads the saved text file (or an inline
paste) for source_type=='text'.
"""
import pytest
from fastapi.testclient import TestClient

from backend import main as backend_main
from backend.auth import UserInfo, require_user


def _client_for(check, monkeypatch):
    app = backend_main.app
    app.dependency_overrides[require_user] = lambda: UserInfo(id=1, provider="test")

    async def _fake_owned(check_id, user):
        return dict(check, id=check_id)
    monkeypatch.setattr(backend_main, "_get_owned_check_or_404", _fake_owned)

    # Skip the disk cache layer so only the source resolution under test runs.
    async def _no_cache():
        return None
    monkeypatch.setattr(backend_main, "_get_configured_cache_dir", _no_cache)

    return TestClient(app)


def test_pasted_bib_file_is_readable(tmp_path, monkeypatch):
    body = tmp_path / "saved_content.bib"
    body.write_text("@article{k, title={A Real Paper}, author={Doe, J}, year={2020}}\n" * 5)

    client = _client_for({"source_type": "text", "paper_source": str(body)}, monkeypatch)
    try:
        resp = client.get("/api/paper-text/77")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert "A Real Paper" in data["text"]
    finally:
        backend_main.app.dependency_overrides.clear()


def test_inline_pasted_text_is_returned(tmp_path, monkeypatch):
    # Some pastes are stored inline (paper_source IS the text, not a path).
    inline = "Introduction. " + ("This is the manuscript body. " * 30)
    client = _client_for({"source_type": "text", "paper_source": inline}, monkeypatch)
    try:
        resp = client.get("/api/paper-text/78")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert "manuscript body" in data["text"]
    finally:
        backend_main.app.dependency_overrides.clear()


def test_missing_source_is_honestly_unavailable(monkeypatch):
    # A text source that no longer resolves must report unavailable, not crash.
    client = _client_for({"source_type": "text", "paper_source": "/no/such/file.bib"}, monkeypatch)
    try:
        resp = client.get("/api/paper-text/79")
        assert resp.status_code == 200
        assert resp.json()["available"] is False
    finally:
        backend_main.app.dependency_overrides.clear()
