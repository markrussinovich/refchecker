"""R19 (G2) — tracked was→should-be, rendered into the PDF + export diff.

Two surfaces are exercised:

  1. The corrections-annotated PDF (``GET /api/preview/<id>/corrections-annotated-pdf``
     and its ``_annotate_pdf_corrections`` worker): a real PyMuPDF artifact with
     strikeout + text-note annotations on the located cited text, plus annotated
     inline-renumber markers — or a clean 404 when there are no real corrections.

  2. The export diff markup: HTML / Markdown / PDF-HTML corrected rows must show a
     token-level was→should-be diff (red struck deletions, green insertions), not
     the old flat "Suggested:" line.

Honesty contract under test: annotations/diffs appear ONLY when a real
``corrected_reference`` exists and differs from the cited line — never a
fabricated or no-op change.
"""

import io
import os

import pytest

from backend import export


# --------------------------------------------------------------------------- #
# Fixtures: a real PDF on disk + a check whose ref #1 has a corrected_reference
# --------------------------------------------------------------------------- #

# The cited TITLE and one inline marker both appear verbatim in the PDF text so
# the locator (search_for) and the renumber marker search can anchor on them.
_CITED_TITLE = "Attention Is All You Needed"          # cited (wrong tense)
_CORRECT_TITLE = "Attention Is All You Need"           # verified should-be
_PDF_BODY = (
    "Introduction. As shown in prior work [9] the transformer architecture\n"
    f"is central. {_CITED_TITLE} was an influential paper that we build on.\n"
)


def _make_pdf(path):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 540, 760), _PDF_BODY, fontsize=11)
    doc.save(path)
    doc.close()


def _check_with_correction():
    return {
        "id": 7,
        "paper_title": "Tracked Changes Demo",
        "results": [
            {
                "index": 1,
                "title": _CITED_TITLE,
                "authors": [{"name": "A. Vaswani"}],
                "year": 2017,
                "venue": "NeurIPS",
                "status": "warning",
                "errors": [],
                "warnings": [{"warning_type": "title",
                              "warning_details": "Title differs from the verified record"}],
                "corrected_reference": {
                    "title": _CORRECT_TITLE,
                    "authors": [{"name": "A. Vaswani"}],
                    "year": 2017, "journal": "NeurIPS",
                },
            },
            {
                "index": 2, "title": "A Clean Verified Reference",
                "authors": [{"name": "K. He"}], "year": 2016,
                "status": "verified", "errors": [], "warnings": [],
            },
        ],
    }


# --------------------------------------------------------------------------- #
# 1) _annotate_pdf_corrections — real PDF round-trip
# --------------------------------------------------------------------------- #

def test_annotate_pdf_corrections_round_trip(tmp_path):
    """The worker produces a real %PDF carrying strikeout + text-note annotations
    on the located cited text (round-tripped by reopening with PyMuPDF)."""
    import fitz
    from backend import main as backend_main

    pdf = tmp_path / "paper.pdf"
    _make_pdf(str(pdf))

    targets = backend_main._correction_targets_for_check(_check_with_correction())
    # Exactly one ref carries a real, differing correction.
    assert len(targets) == 1
    assert targets[0]["corrected"]
    assert targets[0]["cited"] != targets[0]["corrected"]

    out = backend_main._annotate_pdf_corrections(
        str(pdf), targets, [], str(tmp_path), check_id=7)
    assert out and os.path.exists(out)
    with open(out, "rb") as fh:
        assert fh.read(5) == b"%PDF-"

    # Reopen and confirm the annotations are real PDF objects.
    doc = fitz.open(out)
    try:
        kinds = []
        note_texts = []
        for page in doc:
            for annot in page.annots() or []:
                kinds.append(annot.type[1])  # human-readable annot subtype
                info = annot.info or {}
                note_texts.append((info.get("content") or ""))
        doc_text = " ".join(note_texts)
    finally:
        doc.close()
    assert "StrikeOut" in kinds, kinds
    assert any(t.startswith("Text") for t in kinds), kinds  # the sticky note
    assert _CORRECT_TITLE in doc_text  # the should-be line is carried in the note


def test_annotate_renumber_markers(tmp_path):
    """An inline-renumber shift (e.g. ``[9]`` -> ``[10]``) is located on the page
    and annotated with its new form."""
    import fitz
    from backend import main as backend_main

    pdf = tmp_path / "paper.pdf"
    _make_pdf(str(pdf))

    shifts = [{"offset": 0, "marker": "[9]", "new_marker": "[10]", "numbers": [9]}]
    out = backend_main._annotate_pdf_corrections(
        str(pdf), [], shifts, str(tmp_path), check_id=7)
    assert out and os.path.exists(out)

    doc = fitz.open(out)
    try:
        contents = []
        for page in doc:
            for annot in page.annots() or []:
                contents.append((annot.info or {}).get("content") or "")
    finally:
        doc.close()
    assert any("[9]" in c and "[10]" in c for c in contents), contents


def test_annotate_returns_none_when_no_corrections(tmp_path):
    """No targets and no marker shifts -> None (the route maps this to a 404,
    never a blank artifact)."""
    from backend import main as backend_main

    pdf = tmp_path / "paper.pdf"
    _make_pdf(str(pdf))
    assert backend_main._annotate_pdf_corrections(str(pdf), [], [], str(tmp_path), 7) is None


def test_no_target_for_noop_or_missing_correction():
    """A ref with no corrected_reference, or a correction identical to the cited
    line, yields no target (no fabricated strikeout)."""
    from backend import main as backend_main

    check = {
        "results": [
            {"index": 1, "title": "Same", "year": 2020,
             "corrected_reference": {"title": "Same", "year": 2020}},  # no-op
            {"index": 2, "title": "No Correction", "year": 2021},      # no cr
        ]
    }
    assert backend_main._correction_targets_for_check(check) == []


# --------------------------------------------------------------------------- #
# 2) Endpoint — clean 404 when the check has no corrections
# --------------------------------------------------------------------------- #

def _client(monkeypatch, check, *, pdf_path=None, paper_text=""):
    from fastapi.testclient import TestClient
    from backend import main as backend_main
    from backend.auth import UserInfo, require_user

    app = backend_main.app
    app.dependency_overrides[require_user] = lambda: UserInfo(id=1, provider="test")

    async def _fake_get_check_by_id(check_id, user_id=None):
        return check if check_id == check.get("id", 7) else None

    monkeypatch.setattr(backend_main.db, "get_check_by_id", _fake_get_check_by_id)

    async def _fake_cache_dir():
        return os.path.dirname(pdf_path) if pdf_path else "/tmp"

    async def _fake_resolve(check_, cache_dir):
        return pdf_path

    async def _fake_text(check_id, check_):
        return paper_text

    monkeypatch.setattr(backend_main, "_get_configured_cache_dir", _fake_cache_dir)
    monkeypatch.setattr(backend_main, "_resolve_pdf_path_for_check", _fake_resolve)
    monkeypatch.setattr(backend_main, "_extract_paper_text_for_check", _fake_text)
    return TestClient(app)


def test_endpoint_404_when_no_pdf(monkeypatch):
    client = _client(monkeypatch, _check_with_correction(), pdf_path=None)
    try:
        resp = client.get("/api/preview/7/corrections-annotated-pdf")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "No PDF source for this check"
    finally:
        client.app.dependency_overrides.clear()


def test_endpoint_404_when_no_corrections(monkeypatch, tmp_path):
    pdf = tmp_path / "paper.pdf"
    _make_pdf(str(pdf))
    # A check with zero corrected references and no renumber.
    clean = {"id": 7, "paper_title": "Clean",
             "results": [{"index": 1, "title": "Verified Ref", "status": "verified"}]}
    client = _client(monkeypatch, clean, pdf_path=str(pdf), paper_text="")
    try:
        resp = client.get("/api/preview/7/corrections-annotated-pdf")
        assert resp.status_code == 404
        assert "No corrections" in resp.json()["detail"]
    finally:
        client.app.dependency_overrides.clear()


def test_endpoint_returns_annotated_pdf(monkeypatch, tmp_path):
    """The happy path: a real corrected reference yields a downloadable annotated
    PDF (application/pdf, %PDF magic, attachment disposition)."""
    pdf = tmp_path / "paper.pdf"
    _make_pdf(str(pdf))
    client = _client(monkeypatch, _check_with_correction(),
                     pdf_path=str(pdf), paper_text=_PDF_BODY)
    try:
        resp = client.get("/api/preview/7/corrections-annotated-pdf")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.headers["content-disposition"].endswith('-corrections.pdf"')
        assert resp.content[:5] == b"%PDF-"
    finally:
        client.app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# 3) word_diff + export diff markup
# --------------------------------------------------------------------------- #

def test_word_diff_matches_js_semantics():
    ops = export.word_diff("Attention Is All You Needed", "Attention Is All You Need")
    types = [(o["type"], o["word"]) for o in ops]
    # "Needed" deleted, "Need" added; the shared prefix stays equal.
    assert ("del", "Needed") in types
    assert ("add", "Need") in types
    assert ("eq", "Attention") in types


def test_word_diff_empty_baseline_all_add():
    ops = export.word_diff("", "Brand New Title")
    assert all(o["type"] == "add" for o in ops)
    assert [o["word"] for o in ops] == ["Brand", "New", "Title"]


def test_html_export_shows_word_diff_not_flat_suggested():
    html = export.serialize_check_to_html(_check_with_correction(), corrections=True)
    # The was→should-be label replaces the old flat "Suggested:".
    assert "was → should be" in html
    assert "Suggested:" not in html
    # Token-level diff colours from CorrectionsView's DiffSide.
    assert "line-through" in html                 # red struck deletion
    assert "rgba(239,68,68" in html               # red wash
    assert "rgba(34,197,94" in html               # green wash on the insertion
    # The changed tokens are individually marked, not the whole line.
    assert "Needed" in html and "Need" in html


def test_markdown_export_shows_tracked_change():
    md = export.serialize_check_to_markdown(_check_with_correction(), corrections=True)
    assert "was → should be" in md
    assert "suggested correction" not in md
    # ~~deletion~~ / **insertion** portable markup (tokens carry trailing
    # punctuation, matching wordDiff's whitespace tokenizer).
    assert "~~Needed.~~" in md
    assert "**Need.**" in md


def test_pdf_html_model_shows_diff_markup():
    m = export._model(_check_with_correction(), corrections=True, sections=None)
    pdf_html = export._pdf_html_for_model(m)
    assert "was → should be" in pdf_html
    assert "line-through" in pdf_html
    assert "Suggested:" not in pdf_html


def test_pdf_renders_with_diff(tmp_path):
    """The full PDF pipeline still produces a real %PDF with the diff rows."""
    data = export.render_check_to_pdf(_check_with_correction(), corrections=True)
    assert data[:5] == b"%PDF-"
    assert len(data) > 800
