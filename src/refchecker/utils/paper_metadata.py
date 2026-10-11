"""Resolve display metadata for a paper without changing reference verdicts."""

import logging
import re
from typing import Any, Dict, Optional

from refchecker.checkers.openalex import OpenAlexReferenceChecker
from refchecker.checkers.semantic_scholar import NonArxivReferenceChecker
from refchecker.utils.arxiv_utils import get_arxiv_paper_by_id
from refchecker.utils.enrichment import build_enrichment
from refchecker.utils.text_utils import normalize_paper_title

logger = logging.getLogger(__name__)


def _title_page_names(text: str) -> list[str]:
    """Accept personal-name lines, not affiliations, headings or prose."""
    text = re.sub(r"[0-9*†‡§¶#⁰¹²³⁴⁵⁶⁷⁸⁹]+", "", text).strip()
    if re.search(
        r"\b(university|institute|institution|college|department|school|laboratory|"
        r"labs?|research|center|centre|corporation|company|organization|"
        r"engineering|faculty|microsoft|google|amazon|meta|ibm|"
        r"abstract|introduction|anonymous|authors?|submitted|conference|"
        r"proceedings|copyright|association|email)\b|[@:/={}]",
        text, re.I,
    ):
        return []
    names = re.split(r"\s*[,;]\s*|\s+(?:and|&)\s+|\s{3,}", text)
    result = []
    particles = {"de", "del", "di", "da", "dos", "van", "von", "der", "den", "la", "le", "al", "bin"}
    for name in names:
        words = name.split()
        if not 2 <= len(words) <= 6:
            # Unspaced CJK names are valid, but Latin single words are too
            # ambiguous to distinguish from organizations and headings.
            if len(words) == 1 and re.fullmatch(r"[\u3400-\u9fff]{2,8}", name):
                result.append(name)
                continue
            return []
        for word in words:
            if word.lower() in particles:
                continue
            if not word[0].isupper() or not any(c.isalpha() for c in word):
                return []
            if any(not (c.isalpha() or c in ".'-\u2019") for c in word):
                return []
        result.append(" ".join(words))
    return result


def _extract_pdf_authors_with_pypdf(pdf_path: str, title: str) -> list[dict]:
    """Text-layout fallback for core-only installations without PyMuPDF."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        with open(pdf_path, "rb") as source:
            reader = PdfReader(source)
            if not reader.pages:
                return []
            lines = [line.strip() for line in reader.pages[0].extract_text(extraction_mode="layout").splitlines()
                     if line.strip()]
    except PdfReadError as exc:
        logger.warning("Unable to read PDF authors from %s: %s", pdf_path, exc)
        return []
    normalized_title = normalize_paper_title(title)
    for index in range(min(len(lines), 20)):
        for length in range(1, 5):
            if normalize_paper_title(" ".join(lines[index:index + length])) != normalized_title:
                continue
            authors = []
            for line in lines[index + length:index + length + 15]:
                if re.match(r"^(?:abstract|(?:1[.\s]+)?introduction)\b", line, re.I):
                    break
                for name in _title_page_names(line):
                    if not any(author["name"] == name for author in authors):
                        authors.append({"name": name})
            return authors
    logger.info("No matching PDF title found for text author extraction: %r", title)
    return []


def extract_pdf_paper_authors(pdf_path: str, title: str = "") -> list[dict]:
    """Read author lines below the actual first-page title, using PDF geometry.

    Small superscripts are excluded before parsing names. Affiliation and body
    text cannot supply authors, and only rows matching the author typography
    are accepted once the byline has started.
    """
    if not title:
        from refchecker.services.pdf_processor import PDFProcessor
        title = PDFProcessor().extract_title_from_pdf(pdf_path) or ""
    normalized_title = normalize_paper_title(title)
    if not normalized_title:
        return []
    try:
        import fitz
    except ImportError:
        logger.info("PyMuPDF unavailable; extracting PDF byline with pypdf text layout")
        return _extract_pdf_authors_with_pypdf(pdf_path, title)
    try:
        with fitz.open(pdf_path) as document:
            if not len(document):
                return []
            page = document[0]
            lines = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    spans = [span for span in line["spans"] if span["text"].strip()]
                    if not spans:
                        continue
                    size = max(span["size"] for span in spans)
                    # Keep explicit spaces as well as words, but not footnote markers.
                    text = "".join(span["text"] for span in line["spans"]
                                   if span["size"] >= size * 0.8).strip()
                    lines.append({"text": text, "size": size, "bbox": line["bbox"]})
            lines.sort(key=lambda line: (round(line["bbox"][1] / 3), line["bbox"][0]))
            title_end = None
            for index, line in enumerate(lines):
                if line["bbox"][1] > page.rect.height * 0.5:
                    break
                for length in range(1, 5):
                    group = lines[index:index + length]
                    if normalize_paper_title(" ".join(item["text"] for item in group)) == normalized_title:
                        title_end = max(item["bbox"][3] for item in group)
                        break
                if title_end is not None:
                    break
            if title_end is None:
                logger.info("No matching PDF title found for author extraction: %r", title)
                return []
            authors = []
            author_size = None
            for line in lines:
                top = line["bbox"][1]
                if top < title_end - 1:
                    continue
                if top > min(title_end + 220, page.rect.height * 0.6):
                    break
                if re.match(r"^(?:abstract|(?:1[.\s]+)?introduction)\b", line["text"], re.I):
                    break
                names = _title_page_names(line["text"])
                if not names:
                    continue
                if author_size is None:
                    author_size = line["size"]
                if abs(line["size"] - author_size) > 0.6:
                    continue
                for name in names:
                    if not any(author["name"] == name for author in authors):
                        authors.append({"name": name})
            if not authors:
                logger.info("No confident PDF title-page authors found for %r", title)
            return authors
    except (fitz.FileDataError, fitz.EmptyFileError) as exc:
        logger.warning("Unable to read PDF title-page authors from %s: %s", pdf_path, exc)
        return []


def resolve_paper_authors(
    title: str,
    *,
    doi: Optional[str] = None,
    arxiv_id: Optional[str] = None,
    cache_dir: Optional[str] = None,
    semantic_scholar_api_key: Optional[str] = None,
    pdf_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract PDF authors or look up an unambiguous indexed paper.

    Shared by any caller needing paper-level display metadata. Existing
    checker clients own network retries and caching; build_enrichment owns
    author/identifier normalization. No LLM or reference verification runs.
    """
    if pdf_path:
        authors = extract_pdf_paper_authors(pdf_path, title)
        if authors:
            return {"available": True, "authors": authors, "title": title, "year": None, "source": "pdf"}
    work = None
    source = "semantic_scholar"
    if arxiv_id:
        s2 = NonArxivReferenceChecker(api_key=semantic_scholar_api_key)
        s2.cache_dir = cache_dir
        try:
            work = s2.get_paper_by_arxiv_id(arxiv_id)
        finally:
            s2._session.close()
        if not work or not build_enrichment(work).get("authors"):
            # arXiv itself remains authoritative for new papers that have not
            # reached the scholarly indexes (or when S2 is rate-limited).
            paper = get_arxiv_paper_by_id(arxiv_id)
            if paper:
                work = {
                    "title": paper.title,
                    "year": paper.published.year,
                    "authors": [{"name": author.name} for author in paper.authors],
                }
                source = "arxiv"
    openalex = OpenAlexReferenceChecker()
    openalex.cache_dir = cache_dir
    if not work or not build_enrichment(work).get("authors"):
        work = openalex.get_work_by_doi(doi) if doi else None
        source = "openalex"
    normalized_title = normalize_paper_title(title)
    if not work and normalized_title and title.strip().lower() not in {
        "unknown paper", "pasted text", "uploaded paper",
    }:
        matches = [
            candidate for candidate in openalex.search_works(title)
            if normalize_paper_title(candidate.get("title") or "") == normalized_title
            and build_enrichment(candidate).get("authors")
        ]
        # Duplicate preprint/published records are safe only if their author
        # lists agree. Never choose the first of two unrelated same-title works.
        author_lists = {
            tuple(normalize_paper_title(a["name"]) for a in build_enrichment(w)["authors"])
            for w in matches
        }
        if len(author_lists) == 1:
            work = matches[0]
        elif len(author_lists) > 1:
            logger.info("Ambiguous paper-author lookup for title %r", title)

    if doi and (not work or not build_enrichment(work).get("authors")):
        s2 = NonArxivReferenceChecker(api_key=semantic_scholar_api_key)
        s2.cache_dir = cache_dir
        try:
            work = s2.get_paper_by_doi(doi)
        finally:
            s2._session.close()
        source = "semantic_scholar"

    authors = build_enrichment(work).get("authors") or []
    if not authors:
        logger.info("No indexed paper authors found for %r", title)
        return {
            "available": False, "authors": [],
            "reason": "No confident indexed author list was found for this paper.",
        }
    return {
        "available": True,
        "authors": authors,
        "title": work.get("title") or title,
        "year": work.get("publication_year") or work.get("year"),
        "source": source,
    }
