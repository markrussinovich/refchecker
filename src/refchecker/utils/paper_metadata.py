"""Resolve display metadata for a paper without changing reference verdicts."""

import logging
from typing import Any, Dict, Optional

from refchecker.checkers.openalex import OpenAlexReferenceChecker
from refchecker.checkers.semantic_scholar import NonArxivReferenceChecker
from refchecker.utils.arxiv_utils import get_arxiv_paper_by_id
from refchecker.utils.enrichment import build_enrichment
from refchecker.utils.text_utils import normalize_paper_title

logger = logging.getLogger(__name__)


def resolve_paper_authors(
    title: str,
    *,
    doi: Optional[str] = None,
    arxiv_id: Optional[str] = None,
    cache_dir: Optional[str] = None,
    semantic_scholar_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Look up authors by identifier or an unambiguous, exact normalized title.

    Shared by any caller needing paper-level display metadata. Existing
    checker clients own network retries and caching; build_enrichment owns
    author/identifier normalization. No LLM or reference verification runs.
    """
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
