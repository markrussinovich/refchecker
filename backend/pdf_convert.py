"""Lightweight, dependency-light text → PDF conversion.

Lets the native PDF viewer render *every* source uniformly: when a check's
source isn't already a PDF (pasted text, .tex, .bib, .txt, .md, an extracted
docx body, …) we render the extracted body text into a clean, paginated PDF so
the same pdf.js viewer + highlight overlay can be used instead of a separate
text widget.

Real-data only: the PDF contains exactly the extracted text — nothing is
invented. Uses reportlab (pure-Python, base-14 Helvetica, no font embedding),
and degrades by raising so callers can fall back to the text view.
"""
from __future__ import annotations

import os
import re
from typing import Optional


def _clean(text: str) -> str:
    # Normalise newlines; drop NULs and other control chars reportlab dislikes.
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return text


def text_to_pdf(text: str, out_path: str, title: Optional[str] = None) -> str:
    """Render ``text`` into a simple, readable A4 PDF at ``out_path``.

    Returns ``out_path`` on success; raises on failure (missing reportlab, IO).
    The output preserves the source's paragraph/line breaks so the viewer's
    quote→text matching lines up with what the user sees.
    """
    import reportlab
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from xml.sax.saxutils import escape

    text = _clean(text)
    if not text.strip():
        raise ValueError("no text to render")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # Embed Bitstream Vera (ships with reportlab) so the generated PDF is
    # SELF-CONTAINED — pdf.js renders it to canvas without needing the base-14
    # standard-font data, and without any change to the viewer. Fall back to the
    # base-14 Helvetica if the bundled TTF is somehow unavailable.
    font_body, font_bold = "Helvetica", "Helvetica-Bold"
    try:
        fdir = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
        if "DocBody" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DocBody", os.path.join(fdir, "Vera.ttf")))
            pdfmetrics.registerFont(TTFont("DocBodyBold", os.path.join(fdir, "VeraBd.ttf")))
        font_body, font_bold = "DocBody", "DocBodyBold"
    except Exception:
        pass  # keep base-14 Helvetica

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body", parent=styles["Normal"], fontName=font_body,
        fontSize=10.5, leading=15, alignment=TA_LEFT, spaceAfter=6,
    )
    head = ParagraphStyle(
        "Head", parent=styles["Heading2"], fontName=font_bold,
        fontSize=13, leading=17, spaceAfter=10,
    )

    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=title or "Document",
    )

    flow = []
    if title:
        flow.append(Paragraph(escape(title), head))

    # Split into paragraphs on blank lines; keep single newlines as <br/> so the
    # original line structure (and thus the cited-passage wording) is preserved.
    for block in re.split(r"\n[ \t]*\n", text):
        block = block.strip("\n")
        if not block.strip():
            flow.append(Spacer(1, 6))
            continue
        safe = escape(block).replace("\n", "<br/>")
        try:
            flow.append(Paragraph(safe, body))
        except Exception:
            # A pathological block — fall back to a plain, escaped chunk.
            flow.append(Paragraph(escape(block[:4000]), body))

    if not flow:
        raise ValueError("nothing to render")

    doc.build(flow)
    return out_path


# ---------------------------------------------------------------------------
# R02 (O3) — non-PDF source → native PDF.
#
# So the SAME pdf.js viewer (with highlights + back-links) renders docx/html
# sources too, we extract their real body text and reuse text_to_pdf. We keep
# the dependency surface light: python-docx / BeautifulSoup are used when
# present, but each has a pure-stdlib fallback so conversion still works (and
# stays honest — only the document's own text is rendered, nothing invented).
# ---------------------------------------------------------------------------


def docx_to_text(path: str) -> str:
    """Extract the body text of a .docx file as newline-separated paragraphs.

    Uses python-docx when available; otherwise reads the OOXML directly with the
    stdlib (zipfile + ElementTree). Returns "" when the file has no readable
    text. Raises only on a genuinely unreadable/corrupt file.
    """
    # Preferred: python-docx (handles tables, sections, etc.).
    try:
        import docx  # type: ignore

        document = docx.Document(path)
        paras = [p.text for p in document.paragraphs]
        # Include table cell text so tabular content isn't silently dropped.
        for table in getattr(document, "tables", []):
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    paras.append("\t".join(cells))
        return "\n".join(p for p in paras if p is not None).strip()
    except ImportError:
        pass

    # Fallback: parse word/document.xml directly. Each <w:p> is a paragraph;
    # text lives in <w:t> runs. Namespace-agnostic localname matching keeps this
    # resilient to the OOXML namespace prefix.
    import zipfile
    import xml.etree.ElementTree as ET

    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    with zipfile.ZipFile(path) as zf:
        try:
            xml_bytes = zf.read("word/document.xml")
        except KeyError as exc:  # not a Word doc
            raise ValueError("not a .docx file (no word/document.xml)") from exc

    root = ET.fromstring(xml_bytes)
    paragraphs = []
    for para in root.iter():
        if _local(para.tag) != "p":
            continue
        runs = [node.text or "" for node in para.iter() if _local(node.tag) == "t"]
        text = "".join(runs).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs).strip()


def html_to_text(html: str) -> str:
    """Extract readable text from an HTML string (drops script/style/markup).

    Uses BeautifulSoup when available; otherwise a small stdlib HTMLParser that
    strips tags and skips <script>/<style> content. Block-level tags become line
    breaks so the rendered PDF keeps a sensible paragraph structure.
    """
    if not html:
        return ""

    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        # Newlines around block elements so paragraphs survive get_text.
        for br in soup.find_all("br"):
            br.replace_with("\n")
        text = soup.get_text("\n")
        # Collapse runs of blank lines but keep paragraph separation.
        lines = [ln.strip() for ln in text.splitlines()]
        return "\n".join(ln for ln in lines if ln).strip()
    except ImportError:
        pass

    from html.parser import HTMLParser
    import html as _htmllib

    _BLOCK = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "header", "footer", "ul", "ol", "table", "blockquote",
    }

    class _TextExtractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self._chunks: list[str] = []
            self._skip = 0

        def handle_starttag(self, tag, attrs):  # noqa: D401
            if tag in ("script", "style", "noscript"):
                self._skip += 1
            elif tag in _BLOCK:
                self._chunks.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript") and self._skip:
                self._skip -= 1
            elif tag in _BLOCK:
                self._chunks.append("\n")

        def handle_data(self, data):
            if not self._skip and data:
                self._chunks.append(data)

    parser = _TextExtractor()
    parser.feed(_htmllib.unescape(html))
    raw = "".join(parser._chunks)
    lines = [ln.strip() for ln in raw.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def docx_to_pdf(src_path: str, out_path: str, title: Optional[str] = None) -> str:
    """Convert a .docx file at ``src_path`` to a native PDF at ``out_path``."""
    text = docx_to_text(src_path)
    if not text.strip():
        raise ValueError("no extractable text in .docx")
    return text_to_pdf(text, out_path, title=title)


def html_to_pdf(src_path: str, out_path: str, title: Optional[str] = None) -> str:
    """Convert an .html/.htm file at ``src_path`` to a native PDF at ``out_path``."""
    with open(src_path, "r", encoding="utf-8", errors="replace") as fh:
        html = fh.read()
    text = html_to_text(html)
    if not text.strip():
        raise ValueError("no extractable text in HTML")
    return text_to_pdf(text, out_path, title=title)


def convert_to_pdf(src_path: str, out_path: str, title: Optional[str] = None) -> str:
    """Dispatch a non-PDF source file to a native PDF by extension.

    Supports .docx and .html/.htm directly; .txt/.md/.tex/.bib (and unknown
    text-like files) are read and rendered via text_to_pdf. Raises on an
    unsupported binary type or when no text could be extracted, so the caller
    can fall back to the extracted-text view.
    """
    ext = os.path.splitext(src_path)[1].lower()
    if ext == ".docx":
        return docx_to_pdf(src_path, out_path, title=title)
    if ext in (".html", ".htm"):
        return html_to_pdf(src_path, out_path, title=title)
    if ext in (".txt", ".md", ".tex", ".bib", ".rst", ""):
        with open(src_path, "r", encoding="utf-8", errors="replace") as fh:
            return text_to_pdf(fh.read(), out_path, title=title)
    raise ValueError(f"unsupported source type for PDF conversion: {ext or '<none>'}")
