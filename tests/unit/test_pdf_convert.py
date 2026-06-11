"""R02 (O3) — backend docx/html → native PDF conversion.

Verifies that a non-PDF source (.docx, .html) is converted to a real,
text-bearing PDF so the same native pdf.js viewer renders it. Honesty: the
output must contain exactly the document's own text — nothing invented.
"""
from pathlib import Path

import pytest

from backend.pdf_convert import (
    convert_to_pdf,
    docx_to_pdf,
    docx_to_text,
    html_to_pdf,
    html_to_text,
)


def _pdf_text(path: str) -> str:
    """Extract the rendered text from a PDF (used to assert real content)."""
    import fitz  # PyMuPDF

    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def _make_docx(path: Path, paragraphs):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    for para in paragraphs:
        document.add_paragraph(para)
    document.save(str(path))


def test_docx_to_text_extracts_paragraphs(tmp_path):
    src = tmp_path / "sample.docx"
    _make_docx(src, ["First paragraph of the manuscript.", "Second distinct sentence here."])

    text = docx_to_text(str(src))

    assert "First paragraph of the manuscript." in text
    assert "Second distinct sentence here." in text


def test_docx_to_pdf_produces_real_pdf_with_text(tmp_path):
    pytest.importorskip("reportlab")  # optional render dep — skip on CI
    src = tmp_path / "sample.docx"
    _make_docx(src, ["The quick brown fox jumps over the lazy dog."])
    out = tmp_path / "out.pdf"

    result = docx_to_pdf(str(src), str(out), title="My Doc")

    assert result == str(out)
    assert out.exists() and out.stat().st_size > 0
    # Valid PDF magic + the document's own words are really rendered.
    assert out.read_bytes()[:5] == b"%PDF-"
    rendered = _pdf_text(str(out))
    assert "quick brown fox" in rendered
    assert "My Doc" in rendered  # title rendered as heading


def test_html_to_text_strips_markup_and_scripts():
    html = (
        "<html><head><style>p{color:red}</style>"
        "<script>var x = 'should not appear';</script></head>"
        "<body><h1>Heading</h1><p>Visible body paragraph.</p>"
        "<p>Another&nbsp;line.</p></body></html>"
    )

    text = html_to_text(html)

    assert "Visible body paragraph." in text
    assert "Heading" in text
    assert "should not appear" not in text  # script content dropped
    assert "color:red" not in text          # style content dropped


def test_html_to_pdf_produces_real_pdf_with_text(tmp_path):
    pytest.importorskip("reportlab")  # optional render dep — skip on CI
    src = tmp_path / "page.html"
    src.write_text(
        "<html><body><h1>Report</h1><p>Hyperlinked citation context here.</p></body></html>",
        encoding="utf-8",
    )
    out = tmp_path / "page.pdf"

    result = html_to_pdf(str(src), str(out), title="HTML Source")

    assert result == str(out)
    assert out.read_bytes()[:5] == b"%PDF-"
    rendered = _pdf_text(str(out))
    assert "Hyperlinked citation context here." in rendered


def test_convert_to_pdf_dispatches_by_extension(tmp_path):
    pytest.importorskip("reportlab")  # optional render dep — skip on CI
    # .docx path
    dx = tmp_path / "a.docx"
    _make_docx(dx, ["Docx dispatch content."])
    dx_out = tmp_path / "a.pdf"
    convert_to_pdf(str(dx), str(dx_out))
    assert "Docx dispatch content." in _pdf_text(str(dx_out))

    # .html path
    hx = tmp_path / "b.html"
    hx.write_text("<p>Html dispatch content.</p>", encoding="utf-8")
    hx_out = tmp_path / "b.pdf"
    convert_to_pdf(str(hx), str(hx_out))
    assert "Html dispatch content." in _pdf_text(str(hx_out))

    # plain text path
    tx = tmp_path / "c.txt"
    tx.write_text("Plain text dispatch content.", encoding="utf-8")
    tx_out = tmp_path / "c.pdf"
    convert_to_pdf(str(tx), str(tx_out))
    assert "Plain text dispatch content." in _pdf_text(str(tx_out))


def test_convert_to_pdf_rejects_unsupported_binary(tmp_path):
    src = tmp_path / "image.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError):
        convert_to_pdf(str(src), str(tmp_path / "x.pdf"))


def test_docx_to_pdf_raises_on_empty_document(tmp_path):
    pytest.importorskip("reportlab")  # optional render dep — skip on CI
    src = tmp_path / "empty.docx"
    _make_docx(src, [""])
    with pytest.raises(ValueError):
        docx_to_pdf(str(src), str(tmp_path / "empty.pdf"))
