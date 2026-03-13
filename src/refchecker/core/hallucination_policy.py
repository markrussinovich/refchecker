"""LLM-based hallucination assessment for reference verification results.

Requires a configured LLM (OpenAI-compatible) to evaluate whether a
reference with validation issues is likely fabricated.  The LLM receives
the full reference metadata plus the specific errors detected and returns
LIKELY, UNLIKELY, or UNCERTAIN.

A lightweight pre-filter skips entries that clearly don't warrant LLM
assessment (e.g. year-only mismatches, API failures).

A deterministic author-overlap check flags references where fewer than
60% of cited authors match the actual authors — this runs without an LLM.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ── Pre-filter: which error types warrant LLM hallucination assessment ──

_SUSPICIOUS_ERROR_TYPES = frozenset({
    'unverified',       # Could not be verified by any checker
    'doi',              # DOI conflict
    'arxiv_id',         # ArXiv ID points to different paper
    'arxiv',            # ArXiv-related conflict
    'multiple',         # Multiple issues (may include title/author mismatches)
})

_AUTHOR_MATCH_THRESHOLD = 0.6  # Flag if < 60% of authors match


def _normalize_author_name(name: str) -> str:
    """Normalize an author name for comparison (lowercase, strip initials/punctuation)."""
    name = name.strip().lower()
    # Remove common prefixes/suffixes
    name = re.sub(r'\b(jr|sr|ii|iii|iv)\b\.?', '', name)
    # Keep only last name + first significant name part
    parts = [p.strip() for p in re.split(r'[,\s]+', name) if len(p.strip()) > 1]
    return ' '.join(parts)


def _compute_author_overlap(cited_authors: str, correct_authors: str) -> Optional[float]:
    """Compute fraction of cited authors that appear in the correct author list.

    Returns None if either list is empty or has fewer than 2 authors.
    """
    if not cited_authors or not correct_authors:
        return None

    cited = [_normalize_author_name(a) for a in cited_authors.split(',') if a.strip()]
    correct = [_normalize_author_name(a) for a in correct_authors.split(',') if a.strip()]

    if len(cited) < 2 or len(correct) < 2:
        return None

    # Check how many cited author last names appear in the correct list
    correct_lastnames = set()
    for name in correct:
        parts = name.split()
        if parts:
            correct_lastnames.add(parts[-1])

    matches = 0
    for name in cited:
        parts = name.split()
        if parts and parts[-1] in correct_lastnames:
            matches += 1

    return matches / len(cited)


def check_author_hallucination(error_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check if a reference is likely hallucinated based on author overlap.

    Returns a hallucination assessment dict if < 60% of cited authors match
    the correct authors, or None if this check doesn't apply.

    This is a deterministic check that does not require an LLM.
    """
    cited = error_entry.get('ref_authors_cited', '')
    correct = error_entry.get('ref_authors_correct', '')

    if not cited or not correct:
        return None

    overlap = _compute_author_overlap(cited, correct)
    if overlap is None:
        return None

    if overlap < _AUTHOR_MATCH_THRESHOLD:
        pct = int(overlap * 100)
        return {
            'verdict': 'LIKELY',
            'explanation': f'Only {pct}% of cited authors match the actual authors — '
                           f'the reference likely cites a different or fabricated paper.',
            'web_search': None,
        }

    return None


def should_check_hallucination(error_entry: Dict[str, Any]) -> bool:
    """Return True if this error entry warrants LLM hallucination assessment.

    Skips entries that are clearly not hallucinations:
    - Year-only, venue-only, or URL-only mismatches
    - API/infrastructure failures
    - Entries with no meaningful title
    - Entries where the cited URL was checked and references the paper
    """
    error_type = (error_entry.get('error_type') or '').lower()
    error_details = (error_entry.get('error_details') or '').lower()

    if error_type in {'api_failure', 'processing_failed'}:
        return False

    if error_type in {'year', 'venue', 'url'}:
        return False

    # If the URL was checked and references the paper, it's not hallucinated
    if 'url references paper' in error_details:
        return False

    if error_type in {'api_failure', 'processing_failed'}:
        return False

    if error_type in {'year', 'venue', 'url'}:
        return False

    # For 'multiple' type, check if it contains title or author mismatches
    # (not just year+venue)
    if error_type == 'multiple':
        details = (error_entry.get('error_details') or '').lower()
        has_major = any(kw in details for kw in ('title', 'author', 'doi', 'arxiv'))
        if not has_major:
            return False

    if error_type not in _SUSPICIOUS_ERROR_TYPES:
        return False

    # Must have a meaningful title
    title = (error_entry.get('ref_title') or '').strip()
    if not title or len(title) < 10:
        return False

    return True


def assess_hallucination(
    error_entry: Dict[str, Any],
    llm_client: Any,
    web_searcher: Optional[Any] = None,
) -> Dict[str, Any]:
    """Assess whether a reference is likely hallucinated using an LLM.

    Parameters
    ----------
    error_entry : dict
        The consolidated error entry with reference metadata and errors.
    llm_client : LLMHallucinationVerifier
        An initialized LLM client with an ``assess`` method.
    web_searcher : optional
        Web search checker; the LLM decides if a search would help.

    Returns
    -------
    dict with keys:
        verdict: 'LIKELY' | 'UNLIKELY' | 'UNCERTAIN'
        explanation: str  (LLM's reasoning)
        web_search: dict | None  (web search results if performed)
    """
    if not llm_client or not llm_client.available:
        return {
            'verdict': 'UNCERTAIN',
            'explanation': 'No LLM configured for hallucination assessment.',
            'web_search': None,
        }

    try:
        result = llm_client.assess(error_entry, web_searcher=web_searcher)
        return result
    except Exception as exc:
        logger.warning(f'Hallucination assessment failed: {exc}')
        return {
            'verdict': 'UNCERTAIN',
            'explanation': f'Assessment failed: {exc}',
            'web_search': None,
        }
