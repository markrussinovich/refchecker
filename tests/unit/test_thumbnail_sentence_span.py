"""R13 (S7) — token-anchored WHOLE-sentence span in locate_text_spans_in_pdf.

When the exact cited sentence can't be found as one contiguous string in the
PDF text layer (a soft line break / hyphenation the extracted needle lacks),
the backend must still highlight the WHOLE sentence by anchoring on its first
and last words and unioning the word rects between them — NOT degrade to a
5-word prefix fragment. The 5-word fallback fires only when token-anchoring
also fails. Rects stay normalized 0..1 and a position is never fabricated.
"""

import pytest

fitz = pytest.importorskip("fitz")

from backend.thumbnail import (
    locate_text_spans_in_pdf,
    _search_pages_for_text,
    _token_anchored_span_on_page,
)

# A sentence laid into the PDF with a HARD line break + hyphenation ("bench-\nmark")
# so `page.search_for(<joined needle>)` returns no contiguous hit, exercising the
# token-anchored path. The needle below is the clean extracted form (no break).
PDF_BODY = (
    "The proposed transformer architecture achieves state-of-the-art results "
    "on the bench-\nmark across every evaluated configuration and random seed."
)
NEEDLE = (
    "The proposed transformer architecture achieves state-of-the-art results "
    "on the benchmark across every evaluated configuration and random seed."
)


def _build_pdf(path, body):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(72, 72, 500, 300), body, fontname="helv", fontsize=11)
    doc.save(str(path))
    doc.close()


def test_broken_needle_yields_full_sentence_union_span(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _build_pdf(pdf, PDF_BODY)

    doc = fitz.open(str(pdf))
    page = doc.load_page(0)
    try:
        # Precondition: the contiguous full needle does NOT match (soft break),
        # so without token-anchoring we'd fall to a 5-word fragment.
        assert page.search_for(NEEDLE) == [], "needle should be unmatchable contiguously"

        anchored = _token_anchored_span_on_page(page, NEEDLE)
        # The sentence wrapped onto two lines → at least two unioned line rects.
        assert len(anchored) >= 2, "expected a multi-line union span, not a fragment"

        # The union must span vertically across BOTH lines (a 5-word prefix would
        # sit on a single line only).
        ys = [r[1] for r in anchored] + [r[3] for r in anchored]
        y_extent = max(ys) - min(ys)

        prefix = " ".join(NEEDLE.split()[:5])
        ph = float(page.rect.height)
        prefix_hits = page.search_for(prefix)
        assert prefix_hits, "the 5-word prefix should still be findable"
        prefix_extent = (prefix_hits[0].y1 - prefix_hits[0].y0) / ph

        # The whole-sentence span covers noticeably more vertical space than the
        # single-line 5-word prefix would — i.e. it is NOT a prefix fragment.
        assert y_extent > prefix_extent * 1.5

        # Normalized 0..1 rects, none fabricated/degenerate.
        for x0, y0, x1, y1 in anchored:
            assert 0.0 <= x0 < x1 <= 1.0
            assert 0.0 <= y0 < y1 <= 1.0
    finally:
        doc.close()


def test_search_pages_prefers_anchored_span_over_prefix(tmp_path):
    """_search_pages_for_text returns the token-anchored span (>=2 line rects)
    rather than the single 5-word-prefix rect when the contiguous needle fails."""
    pdf = tmp_path / "paper.pdf"
    _build_pdf(pdf, PDF_BODY)

    doc = fitz.open(str(pdf))
    page = doc.load_page(0)
    try:
        pno, rects = _search_pages_for_text([page], NEEDLE)
        assert pno == 0
        assert len(rects) >= 2, "should be the whole-sentence union, not a 5-word prefix"
    finally:
        doc.close()


def test_end_to_end_locate_returns_full_span(tmp_path):
    """Through the public entry point: a broken needle still highlights the whole
    sentence and never fabricates a position."""
    pdf = tmp_path / "paper.pdf"
    _build_pdf(pdf, PDF_BODY)

    targets = [{"text": NEEDLE, "span_index": 0, "span_type": "citation", "ref_id": "7"}]
    found = locate_text_spans_in_pdf(str(pdf), targets)[0]

    assert found["ref_id"] == "7"
    assert found["found"] is True
    assert found["page"] == 0
    assert len(found["rects"]) >= 2  # multi-line union, not a prefix fragment


def test_end_anchor_stops_at_real_sentence_when_tail_word_repeats(tmp_path):
    """R13 over-span regression: when the tail's first word (here the stopword
    "the") repeats LATER on the same page, the end anchor must stop at the real
    sentence end's NEAREST confirmed tail run — not run past it into unrelated
    text by anchoring on the LAST occurrence of that word.

    The needle ends "...trained on the data here." (tail = ["the","data","here"]).
    The page lays "the data here" on the real end line (after a "success-\nmark"
    soft break so the contiguous needle fails → anchored path), and "the data
    again" reappears on a much later, unrelated line ("Later we rely on the data
    again ... below."). The OLD code anchored the end to the LAST "the", walking
    "the data again" and over-spanning a full line down into the trap line; the
    fix anchors to the nearest CONFIRMED tail run and stops at the true end.
    """
    pdf = tmp_path / "paper.pdf"
    body = (
        "Our method was carefully evaluated and the final model was success-\nfully "
        "trained on the data here. Additional filler text occupies an entirely "
        "separate middle line that is unrelated to this particular citation entirely. "
        "Later we rely on the data again within a clearly different trailing line below."
    )
    _build_pdf(pdf, body)

    needle = (
        "Our method was carefully evaluated and the final model was successfully "
        "trained on the data here."
    )

    doc = fitz.open(str(pdf))
    page = doc.load_page(0)
    try:
        # Precondition: contiguous needle does not match (soft break) → anchored path.
        assert page.search_for(needle) == [], "needle should be unmatchable contiguously"

        anchored = _token_anchored_span_on_page(page, needle)
        assert anchored, "expected an anchored span"

        ph = float(page.rect.height)

        # The true sentence ends at "here" — find its y-band on the page.
        end_hits = page.search_for("here")
        assert end_hits, "the real sentence-ending word should be on the page"
        true_end_y = max(h.y1 for h in end_hits) / ph

        # The over-span trap line starts at "Later" and repeats "the data" — the
        # union must NOT reach into it.
        trap_hits = page.search_for("Later")
        assert trap_hits, "the trap line should be on the page"
        trap_y = min(h.y0 for h in trap_hits) / ph
        assert trap_y > true_end_y, "fixture sanity: trap line is below the real end"

        span_bottom = max(r[3] for r in anchored)

        # The span stops at the real sentence end and never reaches the later
        # unrelated line that repeats "the data". (Against the old LAST-occurrence
        # code this asserted ~0.142 >= trap_y ~0.124 and FAILED.)
        assert span_bottom < trap_y, (
            f"span over-ran into the trap line: bottom={span_bottom:.4f} "
            f"trap_y={trap_y:.4f}"
        )
        # And it does reach the real end (small tolerance for line-rect rounding).
        assert span_bottom <= true_end_y + 0.01, (
            f"span bottom {span_bottom:.4f} should be at the real end {true_end_y:.4f}"
        )
    finally:
        doc.close()


def test_prefix_fallback_only_when_anchoring_fails(tmp_path):
    """When the sentence is fully contiguous (no break), the normal contiguous
    match still wins; and an unmatchable sentence with absent endpoints yields
    no fabricated span."""
    pdf = tmp_path / "paper.pdf"
    # Fully contiguous body — search_for matches directly, no anchoring needed.
    _build_pdf(pdf, "A short complete sentence rendered on exactly one line here.")

    doc = fitz.open(str(pdf))
    page = doc.load_page(0)
    try:
        pno, rects = _search_pages_for_text(
            [page], "A short complete sentence rendered on exactly one line here."
        )
        assert pno == 0 and rects, "contiguous sentence should match directly"

        # A sentence whose words are simply absent: nothing fabricated.
        absent = _token_anchored_span_on_page(
            page, "Completely different words that never appear anywhere here at all."
        )
        assert absent == []
    finally:
        doc.close()
