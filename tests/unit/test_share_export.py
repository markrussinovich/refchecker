"""R05 (H1) — Share 500 hardening.

Locks the share/export pipeline against the "Request failed with status code
500" failure that hit EVERY sharing type:

  * `render_export` AND the publish path's `_render_check_html` must round-trip
    for fmt in {html, md, pdf, docx} against a check whose `results` /
    `ai_detection` arrive as JSON STRINGS (the DB stores them serialized) and
    against an empty / odd-shaped check — never a raw 500.
  * The un-guarded `_render_check_html` call in `publish_check` is now wrapped:
    a serialize failure returns a stable, generic error (no leaked `str(e)`).
  * When the PDF engine (PyMuPDF / fitz) is missing/too old, the renderer raises
    a typed `PdfEngineUnavailableError`, and the HTTP layer degrades to a clear
    501 "choose HTML/MD" instead of a 500.

These exercise the real serializers (no mocks) plus the real `_render_check_html`
coroutine in `backend.main` with `db.get_check_by_id` stubbed, so the route's
own resolve+render path is covered (the direct-render tests in
test_export_formats.py skip that).
"""

import asyncio
import io
import json
import zipfile

import pytest

from backend import export
from backend import main as backend_main
from backend.auth import UserInfo


# A single-user-mode user (id 0 -> no DB filtering); see auth.get_user_id_filter.
_USER = UserInfo(id=0, provider="local")
_FORMATS = ("html", "md", "pdf", "docx")


def _run(coro):
    return asyncio.run(coro)


def _real_results():
    return [
        {
            "index": 1, "title": "Attention Is All You Need",
            "authors": [{"name": "A. Vaswani"}], "year": 2017,
            "venue": "NeurIPS", "status": "verified",
            "doi": "10.5555/3295222.3295349", "is_inline_cited": True,
            "errors": [], "warnings": [],
        },
        {
            "index": 2, "title": "A Hallucinated Paper", "authors": [],
            "status": "error",
            "errors": [{"error_type": "title", "error_details": "No matching record found"}],
            "warnings": [],
        },
    ]


def _real_ai():
    return {
        "band": "low", "overall_score": 0.2,
        "probability_distribution": {"AI": 0.1, "Mixed": 0.2, "Human": 0.7},
        "summary": "Most windows read as human-written.",
        "disclaimer": "Advisory signal only.",
    }


def _check_json_strings():
    """A check shaped EXACTLY as it comes back from the DB: results and
    ai_detection are JSON-serialized strings, not native list/dict."""
    return {
        "paper_title": "JSON-string check",
        "timestamp": "2026-06-08T10:00:00Z",
        "results": json.dumps(_real_results()),       # <- a string
        "ai_detection": json.dumps(_real_ai()),       # <- a string
    }


def _check_empty_or_odd():
    """An empty / odd-shaped check: no title, empty-string results, a non-dict
    ai_detection, and a stray non-string. Must still render, never 500."""
    return {
        "paper_title": None,
        "results": "",                  # empty string -> empty list
        "ai_detection": "not-json{",    # un-parseable -> dropped
        "custom_label": "",
        "garbage": object(),            # an unserializable stray field is ignored
    }


def _assert_format_bytes(content, fmt):
    data = content.encode("utf-8") if isinstance(content, str) else content
    assert isinstance(data, (bytes, bytearray)) and len(data) > 0
    if fmt == "html":
        assert data[:9].lower() == b"<!doctype"
    elif fmt == "md":
        assert data[:1] == b"#"
    elif fmt == "pdf":
        assert data[:5] == b"%PDF-"
    elif fmt == "docx":
        assert data[:2] == b"PK"  # zip magic


# --------------------------------------------------------------------------- #
# render_export round-trips every format for both check shapes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("fmt", _FORMATS)
def test_render_export_json_string_check(fmt):
    """results/ai_detection as JSON strings must coerce + render in every fmt."""
    content, media, ext = export.render_export(_check_json_strings(), fmt)
    _assert_format_bytes(content, fmt)
    assert ext in ("html", "md", "pdf", "docx")
    # docx is a valid OOXML zip with the title coerced from the JSON-string rows.
    if fmt == "docx":
        doc = zipfile.ZipFile(io.BytesIO(content)).read("word/document.xml").decode("utf-8")
        assert "Attention Is All You Need" in doc


@pytest.mark.parametrize("fmt", _FORMATS)
def test_render_export_empty_or_odd_check(fmt):
    """An empty/odd check (no title, empty results, junk ai_detection) renders
    without raising — the honesty path: 'No references were extracted'."""
    content, media, ext = export.render_export(_check_empty_or_odd(), fmt)
    _assert_format_bytes(content, fmt)


# --------------------------------------------------------------------------- #
# The publish path's _render_check_html resolves + renders for both shapes
# --------------------------------------------------------------------------- #

def _patch_check(monkeypatch, check):
    async def _fake_get_check_by_id(check_id, user_id=None):
        return check
    monkeypatch.setattr(backend_main.db, "get_check_by_id", _fake_get_check_by_id)


def test_render_check_html_json_string_check(monkeypatch):
    _patch_check(monkeypatch, _check_json_strings())
    title, html = _run(backend_main._render_check_html(1, _USER))
    assert html.lower().startswith("<!doctype html>")
    assert title == "JSON-string check"
    assert "Attention Is All You Need" in html


def test_render_check_html_empty_or_odd_check(monkeypatch):
    _patch_check(monkeypatch, _check_empty_or_odd())
    title, html = _run(backend_main._render_check_html(1, _USER))
    assert html.lower().startswith("<!doctype html>")
    # No title/label -> deterministic fallback, never a crash.
    assert title == "refchecker-1"


def test_render_check_html_missing_check_is_404(monkeypatch):
    from fastapi import HTTPException
    _patch_check(monkeypatch, None)
    with pytest.raises(HTTPException) as ei:
        _run(backend_main._render_check_html(99, _USER))
    assert ei.value.status_code == 404


# --------------------------------------------------------------------------- #
# publish_check guards the (previously un-guarded) render -> stable 500
# --------------------------------------------------------------------------- #

def test_publish_check_render_failure_is_stable_500_no_leak(monkeypatch):
    """A serialize failure inside _render_check_html used to bubble up as a raw,
    detail-leaking 500. It must now be a stable, generic 500."""
    from fastapi import HTTPException

    secret = "boom-secret-internal-detail"

    async def _explode(check_id, current_user):
        raise RuntimeError(secret)

    monkeypatch.setattr(backend_main, "_render_check_html", _explode)
    req = backend_main._PublishRequest(adapter="quick_link")
    with pytest.raises(HTTPException) as ei:
        _run(backend_main.publish_check(1, req, _USER))
    assert ei.value.status_code == 500
    assert secret not in str(ei.value.detail)  # raw exception text not leaked


def test_publish_check_propagates_404_not_500(monkeypatch):
    """A 404 from the resolver must stay a 404, not be masked as a 500."""
    from fastapi import HTTPException
    _patch_check(monkeypatch, None)
    req = backend_main._PublishRequest(adapter="quick_link")
    with pytest.raises(HTTPException) as ei:
        _run(backend_main.publish_check(1, req, _USER))
    assert ei.value.status_code == 404


# --------------------------------------------------------------------------- #
# PDF engine unavailable -> typed error -> clean 501 (not a raw 500)
# --------------------------------------------------------------------------- #

def test_pdf_render_raises_typed_error_when_engine_missing(monkeypatch):
    """If PyMuPDF can't import, the renderer raises PdfEngineUnavailableError
    (a typed signal the HTTP layer maps to 501), not an opaque ImportError 500."""
    import builtins
    real_import = builtins.__import__

    def _no_fitz(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("No module named 'fitz'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_fitz)
    with pytest.raises(export.PdfEngineUnavailableError):
        export.render_check_to_pdf(_check_json_strings())


def test_render_export_pdf_engine_missing_degrades(monkeypatch):
    """render_export surfaces the typed error for the pdf fmt so the route can
    degrade to 422/501 instead of 500. Non-PDF formats are unaffected."""
    def _boom(*a, **k):
        raise export.PdfEngineUnavailableError("PDF engine unavailable")

    monkeypatch.setattr(export, "_render_pdf_from_html", _boom)
    with pytest.raises(export.PdfEngineUnavailableError):
        export.render_export(_check_json_strings(), "pdf")
    # HTML/MD/DOCX still render fine with no PDF engine.
    for fmt in ("html", "md", "docx"):
        content, _, _ = export.render_export(_check_json_strings(), fmt)
        _assert_format_bytes(content, fmt)


def test_export_file_route_maps_pdf_unavailable_to_501(monkeypatch):
    """The /api/export/{id}/file route turns a PdfEngineUnavailableError into a
    501 with the engine message, never a raw 500."""
    from fastapi import HTTPException
    _patch_check(monkeypatch, _check_json_strings())

    def _boom(*a, **k):
        raise export.PdfEngineUnavailableError("PDF engine (PyMuPDF) is unavailable — choose HTML or Markdown.")

    monkeypatch.setattr(export, "_render_pdf_from_html", _boom)
    with pytest.raises(HTTPException) as ei:
        _run(backend_main.export_check_file(1, fmt="pdf", current_user=_USER))
    assert ei.value.status_code == 501
    assert "HTML" in ei.value.detail or "Markdown" in ei.value.detail


def test_export_file_route_generic_500_no_leak(monkeypatch):
    """A non-PDF serialize failure returns a stable generic 500, not str(e)."""
    from fastapi import HTTPException
    _patch_check(monkeypatch, _check_json_strings())
    secret = "leak-me-not-internal"

    def _explode(*a, **k):
        raise RuntimeError(secret)

    monkeypatch.setattr(export, "render_export", _explode)
    with pytest.raises(HTTPException) as ei:
        _run(backend_main.export_check_file(1, fmt="html", current_user=_USER))
    assert ei.value.status_code == 500
    assert secret not in str(ei.value.detail)
