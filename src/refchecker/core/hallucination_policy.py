"""LLM-based hallucination assessment for reference verification results.

Requires a configured LLM (OpenAI-compatible) to evaluate whether a
reference with validation issues is likely fabricated.  The LLM receives
the full reference metadata plus the specific errors detected and returns
LIKELY, UNLIKELY, or UNCERTAIN.

A lightweight pre-filter skips entries that clearly don't warrant LLM
assessment (e.g. year-only mismatches, API failures).
"""

from __future__ import annotations

import logging
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


def should_check_hallucination(error_entry: Dict[str, Any]) -> bool:
    """Return True if this error entry warrants LLM hallucination assessment.

    Skips entries that are clearly not hallucinations:
    - Year-only, venue-only, or URL-only mismatches
    - API/infrastructure failures
    - Entries with no meaningful title
    """
    error_type = (error_entry.get('error_type') or '').lower()

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
