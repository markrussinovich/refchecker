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
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from refchecker.utils.text_utils import enhanced_name_match


# ── Pre-filter: which error types warrant LLM hallucination assessment ──

_SUSPICIOUS_ERROR_TYPES = frozenset({
    'unverified',       # Could not be verified by any checker
    'doi',              # DOI conflict
    'arxiv_id',         # ArXiv ID points to different paper
    'arxiv',            # ArXiv-related conflict
    'multiple',         # Multiple issues (may include title/author mismatches)
    'url',              # Cited URL is broken or points to wrong paper
})

_AUTHOR_MATCH_THRESHOLD = 0.6  # Flag if < 60% of authors match


def _split_author_string(author_str: str) -> List[str]:
    """Split a comma-separated author string into individual author names.

    Handles "LastName, Initials" bibliography format by merging initials
    back with their preceding last name.  For example:
        "Goodfellow, I. J., Bengio, Y." → ["Goodfellow, I. J.", "Bengio, Y."]
    Also handles "FirstName LastName" format (no merging needed).
    """
    raw_parts = [p.strip() for p in author_str.split(',') if p.strip()]

    # Detect "LastName, Initials" format: look for parts that are purely
    # initials (single letters with optional periods/spaces, e.g. "I. J.", "Y.")
    _INITIAL_RE = re.compile(
        r'^[A-Za-z]\.?(\s*[A-Za-z]\.?)*\.?$'
    )

    def _is_initials(part: str) -> bool:
        """Return True if *part* looks like author initials."""
        stripped = part.strip().rstrip('.')
        if not stripped:
            return False
        # All "words" are single characters
        return all(len(w.strip('.')) <= 1 for w in stripped.split())

    merged: List[str] = []
    i = 0
    while i < len(raw_parts):
        part = raw_parts[i]
        # Check if the *next* part is initials that belong to this last name
        if i + 1 < len(raw_parts) and _is_initials(raw_parts[i + 1]):
            merged.append(f"{part}, {raw_parts[i + 1]}")
            i += 2
        else:
            merged.append(part)
            i += 1

    # Filter out "et al." and similar markers
    result = []
    for name in merged:
        name_lower = name.strip().lower().rstrip('.')
        if name_lower in ('et al', 'et al.', 'others', 'and others', ''):
            continue
        result.append(name.strip())
    return result


def _compute_author_overlap(cited_authors: str, correct_authors: str) -> Optional[float]:
    """Compute fraction of cited authors that appear in the correct author list.

    Returns None if either list is empty or has fewer than 2 real authors.
    Uses enhanced_name_match() for fuzzy comparison that handles initials,
    diacritics, and name-format variations.
    """
    if not cited_authors or not correct_authors:
        return None

    cited = _split_author_string(cited_authors)
    correct = _split_author_string(correct_authors)

    if len(cited) < 2 or len(correct) < 2:
        return None

    matches = 0
    for cited_name in cited:
        for correct_name in correct:
            if enhanced_name_match(cited_name, correct_name):
                matches += 1
                break

    # With only 2 authors, having 1 correct is a normal citation error,
    # not hallucination — require at least 3 cited authors for overlap scoring
    if len(cited) <= 2 and matches >= 1:
        return None

    return matches / len(cited)


def check_author_hallucination(error_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check if a reference is likely hallucinated based on author overlap.

    Returns a hallucination assessment dict if < 60% of cited authors match
    the correct authors, or None if this check doesn't apply.

    Only applies to unverified references.  If a paper was found in a
    database (author error on a verified paper), low author overlap is
    a data-quality issue, not hallucination.

    This is a deterministic check that does not require an LLM.
    """
    # Only flag hallucination for unverified references; verified papers
    # with author mismatches are data-quality issues, not fabrications.
    error_type = (error_entry.get('error_type') or '').lower()
    if error_type not in ('unverified', 'multiple', ''):
        return None

    cited = error_entry.get('ref_authors_cited', '')
    correct = error_entry.get('ref_authors_correct', '')

    if not cited or not correct:
        return None

    overlap = _compute_author_overlap(cited, correct)
    if overlap is None:
        return None

    if overlap < _AUTHOR_MATCH_THRESHOLD:
        pct = int(overlap * 100)
        if pct == 0:
            overlap_desc = 'None of the cited authors match'
        elif overlap < 0.25:
            overlap_desc = 'Almost none of the cited authors match'
        else:
            overlap_desc = 'Less than half of the cited authors match'
        return {
            'verdict': 'LIKELY',
            'explanation': f'{overlap_desc} the actual authors — '
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
    - Web/URL references with no authors (website citations, not papers)
    """
    error_type = (error_entry.get('error_type') or '').lower()
    error_details = (error_entry.get('error_details') or '').lower()

    if error_type in {'api_failure', 'processing_failed'}:
        return False

    if error_type in {'year', 'venue'}:
        return False

    # If the URL was checked and references the paper, it's not hallucinated
    if 'url references paper' in error_details:
        return False

    # Web/URL references with no real authors are not hallucination candidates
    # (these are website citations like datasets, blog posts, tools)
    authors = error_entry.get('ref_authors_cited', '')
    orig_ref = error_entry.get('original_reference', {})
    orig_authors = orig_ref.get('authors', []) if orig_ref else []
    url = error_entry.get('ref_url_cited', '') or (orig_ref.get('url', '') if orig_ref else '')

    # If the reference has a cited URL that was already checked and confirmed
    # the paper, it's not hallucinated.  But if the URL check *failed*
    # (paper not found at URL), the reference is still suspicious.
    # Only skip when errors don't indicate URL verification failure.
    if url and url.startswith('http') and error_type != 'unverified':
        # For 'multiple' or other types, check if the URL verification failed
        # (non-existent page, doesn't reference the paper, etc.)
        url_failed = any(
            kw in error_details
            for kw in ('unverified', 'non-existent', 'does not reference',
                       'could not be verified', 'could not verify')
        )
        if not url_failed:
            return False

    # For 'multiple' type, check if it contains title or author mismatches
    # (not just year+venue)
    if error_type == 'multiple':
        details = (error_entry.get('error_details') or '').lower()
        has_major = any(kw in details for kw in ('title', 'author', 'doi', 'arxiv', 'unverified',
                                                  'non-existent', 'does not reference',
                                                  'could not be verified', 'could not verify'))
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


def run_hallucination_check(
    error_entry: Dict[str, Any],
    llm_client: Any = None,
    web_searcher: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Unified hallucination check — single entry point for CLI, WebUI, and report builder.

    Runs the deterministic author-overlap check first, then (if no flag)
    the LLM-based assessment for unverified / URL-error references.

    Parameters
    ----------
    error_entry : dict
        Reference record with at least: error_type, error_details,
        ref_title, ref_authors_cited, ref_url_cited.  May also include
        ref_authors_correct, ref_year_cited, ref_venue_cited, original_reference.
    llm_client : optional
        LLMHallucinationVerifier instance (or None to skip LLM).
    web_searcher : optional
        Web search checker passed to the LLM verifier.

    Returns
    -------
    dict with verdict/explanation/web_search, or None if no assessment needed.
    """
    # 1. Deterministic: author-overlap check (no LLM)
    author_result = check_author_hallucination(error_entry)
    if author_result:
        return author_result

    # 2. LLM-based: for unverified or URL-error references
    if not llm_client or not getattr(llm_client, 'available', False):
        return None

    error_type = (error_entry.get('error_type') or '').lower()
    is_unverified = (
        error_type == 'unverified'
        or error_type == 'url'
        or (error_type == 'multiple'
            and any(kw in (error_entry.get('error_details') or '').lower()
                    for kw in ('unverified', 'non-existent', 'does not reference',
                               'could not be verified', 'could not verify')))
    )

    if not is_unverified:
        return None

    if not should_check_hallucination(error_entry):
        return None

    return assess_hallucination(error_entry, llm_client=llm_client, web_searcher=web_searcher)
