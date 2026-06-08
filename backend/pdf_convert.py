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
