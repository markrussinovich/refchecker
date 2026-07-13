"""Tests for the reference-list entry-rect lookup in locate_text_spans_in_pdf.

R28 (S6): an inline citation must be able to scroll + flash its matching
reference-list entry INSIDE the same PDF. The backend locates that entry rect
for a target's ``ref_text`` (the cited reference's title), echoing ``ref_id`` for
every span and returning normalized 0..1 page coordinates. It must NEVER fabricate
a position: an entry that cannot be found returns ``ref_found=False``.
"""

import pytest

fitz = pytest.importorskip("fitz")

from backend.thumbnail import locate_text_spans_in_pdf


def _build_pdf(path, body_sentence, ref_entry):
    """A 2-page PDF: a body sentence on page 1, a reference-list entry on page 2."""
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_textbox(fitz.Rect(72, 72, 520, 200), body_sentence, fontname="helv", fontsize=11)
    page2 = doc.new_page()
    page2.insert_textbox(
        fitz.Rect(72, 72, 520, 300),
        "References\n\n" + ref_entry,
        fontname="helv",
        fontsize=11,
    )
    doc.save(str(path))
    doc.close()


def test_ref_entry_rect_located_on_its_page(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _build_pdf(
        pdf,
        "As shown by prior work, the model converges quickly in practice [3].",
        "Smith and Jones. A Study of Convergence in Deep Networks. NeurIPS 2021.",
    )

    targets = [
        {
            "text": "As shown by prior work, the model converges quickly in practice [3].",
            "span_index": 0,
            "span_type": "citation",
            "ref_id": "3",
            "ref_text": "A Study of Convergence in Deep Networks",
        }
    ]

    results = locate_text_spans_in_pdf(str(pdf), targets)
    assert len(results) == 1
    found = results[0]

    # The span's own body text is on page 1.
    assert found["ref_id"] == "3"
    assert found["found"] is True
    assert found["page"] == 0

    # The reference entry is located on page 2 (index 1) inside the same PDF.
    assert found["ref_found"] is True
    assert found["ref_page"] == 1
    assert len(found["ref_rects"]) >= 1, "expected at least one entry rect"

    # Normalized 0..1 rect.
    x0, y0, x1, y1 = found["ref_rects"][0]
    assert 0.0 <= x0 < x1 <= 1.0
    assert 0.0 <= y0 < y1 <= 1.0


def test_ref_entry_not_fabricated_when_absent(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _build_pdf(
        pdf,
        "The dataset was collected over three years across many sites [1].",
        "Doe et al. Longitudinal Data Collection Methods. JMLR 2020.",
    )

    targets = [
        {
            "text": "The dataset was collected over three years across many sites [1].",
            "span_index": 0,
            "span_type": "citation",
            "ref_id": "1",
            "ref_text": "Completely Unrelated Title That Is Not In This Document",
        }
    ]

    found = locate_text_spans_in_pdf(str(pdf), targets)[0]

    # ref_id is still echoed, but no position is fabricated for the missing entry.
    assert found["ref_id"] == "1"
    assert found["ref_found"] is False
    assert found["ref_page"] is None
    assert found["ref_rects"] == []


def test_ref_id_echoed_even_without_ref_text(tmp_path):
    """A span with no ref_text (e.g. an AI span) still gets ref_id echoed and a
    ref_found=False entry, so the frontend can branch uniformly over results."""
    pdf = tmp_path / "paper.pdf"
    _build_pdf(
        pdf,
        "A plain sentence with enough characters to be searchable.",
        "Anon. Some Reference. 2019.",
    )

    targets = [
        {
            "text": "A plain sentence with enough characters to be searchable.",
            "span_index": 0,
            "span_type": "ai",
            "ref_id": "ai:0",
            # no ref_text
        }
    ]

    found = locate_text_spans_in_pdf(str(pdf), targets)[0]

    assert found["ref_id"] == "ai:0"
    assert found["ref_found"] is False
    assert found["ref_page"] is None
    assert found["ref_rects"] == []
