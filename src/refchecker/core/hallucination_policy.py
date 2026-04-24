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
    'author',           # Author mismatch (may indicate fabricated citation)
    'title',            # Title mismatch (URL/ID points to a different paper)
})

_AUTHOR_MATCH_THRESHOLD = 0.6  # Flag if < 60% of authors match (unverified refs)
_AUTHOR_VERIFIED_THRESHOLD = 0.4  # Stricter: flag if < 40% match (verified refs)

# Team/organisation names that appear as first "author" in large collaborative
# papers.  These are stripped before computing author overlap because the DB
# may concatenate them with the first real author.
_TEAM_NAMES = frozenset({
    'deepseek-ai', 'qwen', 'openai', 'microsoft', 'google', 'meta',
    'team glm', 'gemini team', 'core team', 'v team',
    '01.ai', 'ai', 'lcm team', 'the lcm team',
})


def has_real_errors(error_entry: Dict[str, Any]) -> bool:
    """Return True if this error entry has real errors/warnings, not just info/suggestions.

    Matches the WebUI's ``_has_real_errors`` logic so CLI and Batch paths
    skip hallucination assessment for refs that only have informational
    suggestions (e.g. "could include arXiv URL").
    """
    # Check the consolidated error_type field
    error_type = (error_entry.get('error_type') or '').lower()

    # If '_original_errors' is present (consolidated entry), check each sub-error
    original_errors = error_entry.get('_original_errors')
    if original_errors:
        for e in original_errors:
            if e.get('error_type') and e['error_type'] != 'unverified':
                return True
            if e.get('warning_type'):
                return True
            if e.get('error_type') == 'unverified':
                return True
        return False

    # Single-error entries
    if error_type in ('info', 'suggestion', 'suggestion_type', ''):
        return False
    return True


def count_raw_errors(raw_errors: list) -> tuple:
    """Count errors, warnings, and info items in a raw verifier error list.

    This is the **single source of truth** for tallying error / warning /
    info totals.  All code paths (CLI, Batch, WebUI) must use this so
    reported counts are consistent.

    Returns (error_count, warning_count, info_count).

    An ``error_type`` entry is only counted as an error if it is NOT:
    - ``'unverified'`` (has its own category)
    - a ``'url'`` entry whose details say "url references paper"
      (informational, not a real error)
    """
    error_count = 0
    warning_count = 0
    info_count = 0
    for e in (raw_errors or []):
        if 'warning_type' in e:
            warning_count += 1
        elif 'info_type' in e:
            info_count += 1
        elif 'error_type' in e:
            etype = e['error_type']
            if etype == 'unverified':
                continue
            if (etype == 'url'
                    and 'url references paper'
                    in (e.get('error_details') or '').lower()):
                continue
            error_count += 1
    return error_count, warning_count, info_count


def has_real_raw_errors(raw_errors: list) -> bool:
    """Return True if *raw_errors* contains actual errors (not just suggestions/info).

    Works on the raw verifier format where info entries have an ``info_type``
    key (no ``error_type``/``warning_type``), and sanitised entries use
    ``is_suggestion`` / ``is_info``.  Used by the WebUI path which stores
    raw errors before consolidation.
    """
    for e in (raw_errors or []):
        if e.get('is_suggestion') or e.get('is_info'):
            continue
        if (e.get('error_type') or '').startswith('suggestion'):
            continue
        if 'info_type' in e and 'error_type' not in e and 'warning_type' not in e:
            continue
        return True
    return False


def build_hallucination_error_entry(
    raw_errors: list,
    reference: Dict[str, Any],
    verified_url: str = '',
) -> Optional[Dict[str, Any]]:
    """Build a consolidated error_entry from raw verifier errors.

    Filters out suggestion/info entries so hallucination screening only
    sees real errors.  Returns *None* when no real errors remain.

    Parameters
    ----------
    raw_errors : list
        The raw error list from the verifier (``result['_raw_errors']``).
    reference : dict
        The parsed reference dict (title, authors, year, venue, url, …).
    verified_url : str
        Authoritative URL found by the verifier (empty string if none).
    """
    errors = []
    for e in (raw_errors or []):
        if e.get('is_suggestion') or e.get('is_info'):
            continue
        if (e.get('error_type') or '').startswith('suggestion'):
            continue
        if 'info_type' in e and 'error_type' not in e and 'warning_type' not in e:
            continue
        errors.append(e)
    if not errors:
        return None

    error_types: List[str] = []
    error_details_parts: List[str] = []
    authors_correct = None
    for err in errors:
        etype = err.get('error_type') or err.get('warning_type') or err.get('info_type', '')
        edetail = err.get('error_details') or err.get('warning_details') or err.get('info_details', '')
        if etype:
            error_types.append(etype)
        if edetail:
            error_details_parts.append(edetail)
        if err.get('ref_authors_correct'):
            authors_correct = err['ref_authors_correct']

    if not error_types:
        return None

    consolidated_type = 'multiple' if len(error_types) > 1 else error_types[0]

    # Preserve checker-supplied author metadata even for ArXiv-ID mismatches.
    # A verified reference can match the correct paper by title/authors while
    # still citing a stale or spurious ArXiv URL; downstream screening uses
    # author overlap to suppress unnecessary LLM calls for those cases.

    error_entry: Dict[str, Any] = {
        'error_type': consolidated_type,
        'error_details': '\n'.join(error_details_parts),
        'ref_title': reference.get('title', ''),
        'ref_authors_cited': ', '.join(reference.get('authors', [])),
        # Keep the original list so overlap checks don't need to
        # round-trip through a comma-joined string (which breaks when
        # an individual author name contains a comma).
        '_ref_authors_cited_list': list(reference.get('authors', [])),
        'ref_year_cited': reference.get('year'),
        'ref_venue_cited': reference.get('venue', ''),
        'ref_url_cited': reference.get('cited_url') or reference.get('url', ''),
        'ref_verified_url': verified_url,
        'original_reference': reference,
    }
    if authors_correct:
        error_entry['ref_authors_correct'] = authors_correct

    logger.debug(f"build_hallucination_error_entry: ref={reference.get('title','')[:60]!r} "
                 f"type={consolidated_type} authors_correct={'yes' if authors_correct else 'no'} "
                 f"verified_url={bool(verified_url)}")
    return error_entry


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


def _compute_author_overlap(
    cited_authors: str,
    correct_authors: str,
    cited_list: Optional[List[str]] = None,
) -> Optional[float]:
    """Compute fraction of cited authors that appear in the correct author list.

    Returns None if either list is empty or has fewer than 2 real authors.
    Uses enhanced_name_match() for fuzzy comparison that handles initials,
    diacritics, name-format variations, and FirstName/LastName swaps.

    Strips known team/organisation names (e.g. "DeepSeek-AI", "Qwen") that
    the DB may concatenate with the first real author, causing false mismatches.

    For long author lists (>10 authors), compares only the first 10 from each
    list.  Database records often truncate differently, so comparing the full
    30+-author list produces false-low overlap.

    Parameters
    ----------
    cited_list : optional
        Pre-split cited author names.  When supplied, avoids re-splitting
        the comma-joined ``cited_authors`` string (which can break when an
        individual author name contains a comma, e.g. "et al. Wallace, Eric").
    """
    if not cited_authors or not correct_authors:
        return None

    if cited_list is not None:
        # Filter out "et al." markers from the pre-split list,
        # matching the behaviour of _split_author_string.
        cited = [
            n for n in cited_list
            if n.strip().lower().rstrip('.') not in
            ('et al', 'et al.', 'others', 'and others', '')
        ]
    else:
        cited = _split_author_string(cited_authors)
    correct = _split_author_string(correct_authors)

    # Strip team-name prefixes from both lists
    cited = _strip_team_names(cited)
    correct = _strip_team_names(correct)

    if len(cited) < 2 or len(correct) < 2:
        return None

    # For long author lists, cap comparison to first N authors.
    # Databases often store author lists differently (truncated, reordered
    # after first author, different "et al." handling), so comparing the
    # full 30+-author list produces artificially low overlap.
    MAX_AUTHORS_TO_COMPARE = 10
    cited_cmp = cited[:MAX_AUTHORS_TO_COMPARE]
    correct_cmp = correct  # search against the full correct list

    matches = 0
    for cited_name in cited_cmp:
        for correct_name in correct_cmp:
            if enhanced_name_match(cited_name, correct_name):
                matches += 1
                break

    # With only 2 authors, having 1 correct is a normal citation error,
    # not hallucination — require at least 3 cited authors for overlap scoring
    if len(cited_cmp) <= 2 and matches >= 1:
        return None

    return matches / len(cited_cmp)


def _strip_team_names(authors: List[str]) -> List[str]:
    """Remove known team/org names from an author list.

    Also handles the DB concatenation pattern where the team name is joined
    to the first real author, e.g. "Qwen An Yang" → "An Yang".
    """
    result = []
    for i, name in enumerate(authors):
        name_lower = name.strip().lower()
        # Direct match: skip team name entirely
        if name_lower in _TEAM_NAMES:
            continue
        # Check if this name starts with a team name prefix (DB concatenation)
        # e.g. "Qwen An Yang" → extract "An Yang"
        if i == 0:
            for team in _TEAM_NAMES:
                if name_lower.startswith(team + ' '):
                    # Strip the team prefix
                    name = name[len(team):].strip()
                    break
        result.append(name)
    return result


def check_author_hallucination(error_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check if a reference is likely hallucinated based on author overlap.

    Returns a hallucination assessment dict if < 60% of cited authors match
    the correct authors, or None if this check doesn't apply.

    For verified references (found in a database), only flags hallucination
    when author overlap is critically low (< 20%) — i.e. the LLM found a
    real paper title but fabricated nearly all authors.  Moderate mismatches
    on verified papers are treated as data-quality issues, not hallucination.

    For unverified references, uses the standard 60% threshold.

    This is a deterministic check that does not require an LLM.
    """
    error_type = (error_entry.get('error_type') or '').lower()
    is_verified = bool(error_entry.get('ref_verified_url'))

    # For unverified refs, allow 'unverified', 'author', 'multiple', or empty
    # error_type.  A ref can lack ref_verified_url yet still carry an 'author'
    # error when the checker found the paper but the cited authors don't match.
    # For verified refs, always defer to the LLM (return None) so it can
    # web-search and distinguish "wrong edition matched" from "grafted ref."
    # The LLM prompt instructs it to trust web search over checker data.
    # Without an LLM, run_hallucination_check will fall back to this
    # function's result via the no-LLM path.
    if is_verified:
        if not (error_type.startswith('author') or error_type in ('multiple', '')):
            return None
    else:
        if not (error_type.startswith('author') or error_type in ('unverified', 'multiple', '')):
            return None

    cited = error_entry.get('ref_authors_cited', '')
    correct = error_entry.get('ref_authors_correct', '')

    # When the reference has an incorrect ArXiv ID that resolves to a
    # completely different paper, the "correct" authors are from the WRONG
    # paper.  Author-overlap comparison is meaningless in this case — defer
    # to the LLM which can web-search for the cited title.
    error_details = (error_entry.get('error_details') or '').lower()
    if 'incorrect arxiv id' in error_details and 'points to' in error_details:
        logger.debug(
            "check_author_hallucination: skip (incorrect ArXiv ID — correct authors are from wrong paper) "
            "ref=%r", error_entry.get('ref_title', '')[:60],
        )
        return None

    logger.debug(f"check_author_hallucination: ref={error_entry.get('ref_title','')[:60]!r} "
                 f"type={error_type} is_verified={is_verified} cited={cited[:50]!r} correct={correct[:50]!r}")

    if not cited or not correct:
        logger.debug(f"check_author_hallucination: skip (no cited/correct) ref={error_entry.get('ref_title','')[:60]!r}")
        return None

    cited_list = error_entry.get('_ref_authors_cited_list')
    overlap = _compute_author_overlap(cited, correct, cited_list=cited_list)
    if overlap is None:
        return None

    # For verified references, use a stricter threshold: only flag when
    # author overlap is critically low (< 30%), indicating the LLM found
    # a real title but fabricated the authors.
    threshold = _AUTHOR_VERIFIED_THRESHOLD if is_verified else _AUTHOR_MATCH_THRESHOLD
    if overlap < threshold:
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
            'author_overlap': overlap,
        }

    return None


def _is_name_order_swap(name1: str, name2: str) -> bool:
    """Return True if two names are the same person in different order.

    Detects "LastName FirstName" ↔ "FirstName LastName" swaps such as
    "Deng Ailin" vs "Ailin Deng".  Only for 2-part names where the
    words are the same but reversed.
    """
    parts1 = [w.lower().rstrip('.') for w in name1.strip().split() if len(w.rstrip('.')) > 1]
    parts2 = [w.lower().rstrip('.') for w in name2.strip().split() if len(w.rstrip('.')) > 1]
    if len(parts1) != 2 or len(parts2) != 2:
        return False
    return parts1[0] == parts2[1] and parts1[1] == parts2[0]


def detect_name_order_warning(error_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Detect if the author "mismatch" is just a FirstName/LastName ordering issue.

    Returns an UNLIKELY assessment with a warning explanation if most cited
    authors are the same people in reversed name order.  Returns None if
    this is not a name-ordering issue.

    This allows the reference to be treated as verified with a warning
    rather than flagged as hallucination.
    """
    cited = error_entry.get('ref_authors_cited', '')
    correct = error_entry.get('ref_authors_correct', '')
    if not cited or not correct:
        return None

    cited_list = _split_author_string(cited)
    correct_list = _split_author_string(correct)

    # Strip team names for comparison
    cited_list = _strip_team_names(cited_list)
    correct_list = _strip_team_names(correct_list)

    if len(cited_list) < 2 or len(correct_list) < 2:
        return None

    # Count how many cited names are name-order swaps of correct names
    swap_count = 0
    match_count = 0
    for cn in cited_list:
        for corr in correct_list:
            if enhanced_name_match(cn, corr):
                match_count += 1
                if _is_name_order_swap(cn, corr):
                    swap_count += 1
                break

    # If most authors match and at least some are name-order swaps, it's formatting
    if match_count / len(cited_list) >= 0.5 and swap_count >= 1:
        return {
            'verdict': 'UNLIKELY',
            'explanation': (
                f'Author names appear to use reversed ordering '
                f'(e.g. "LastName FirstName" instead of "FirstName LastName"). '
                f'{swap_count} of {len(cited_list)} names are order-swapped — '
                f'this is a formatting issue, not hallucination.'
            ),
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

    # Title-only errors on verified refs mean the paper was found but has
    # a slightly different title (e.g. paraphrase in Semantic Scholar).
    # This is a metadata quality issue, not hallucination.  Also skip
    # 'multiple' where all sub-errors are title/venue/year (no author
    # or ArXiv ID issues).
    if error_entry.get('ref_verified_url') and error_type in {'title', 'multiple'}:
        if error_type == 'title':
            return False
        # For 'multiple', check if it contains only title/venue/year issues
        details = (error_entry.get('error_details') or '').lower()
        has_suspicious = any(kw in details for kw in (
            'author', 'doi', 'arxiv_id', 'arxiv id', 'unverified',
            'could not be verified', 'could not verify',
            'does not reference', "doesn't reference",
            'non-existent', 'not found',
        ))
        if not has_suspicious:
            return False

    # "url references paper" cases are now passed to the LLM for validation.
    # The LLM can override the unverified status to verified if it confirms
    # the URL is the correct source for the reference.

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
        # A title mismatch also means the URL points to a different paper.
        url_failed = any(
            kw in error_details
            for kw in ('unverified', 'non-existent', 'does not reference',
                       "doesn't reference", 'not found',
                       'could not be verified', 'could not verify',
                       'title mismatch', 'inaccurate title',
                       'incorrect arxiv id', 'arxiv id')
        )
        if not url_failed:
            # For author-type errors (including 'multiple' with author issues),
            # a valid URL only proves the paper exists — it does not validate
            # cited authors.  If we have correct author data and overlap is
            # critically low, don't skip: the reference may cite a real title
            # with fabricated authors.
            if error_type in ('author', 'multiple'):
                cited = error_entry.get('ref_authors_cited', '')
                correct = error_entry.get('ref_authors_correct', '')
                if cited and correct:
                    cited_list = error_entry.get('_ref_authors_cited_list')
                    overlap = _compute_author_overlap(cited, correct, cited_list=cited_list)
                    if overlap is not None and overlap < _AUTHOR_VERIFIED_THRESHOLD:
                        pass  # Don't skip — authors critically mismatched
                    elif overlap is None and 'doi mismatch' in error_details:
                        # Overlap was inconclusive (e.g. single-author DB record)
                        # but DOI also doesn't match — the DB likely matched the
                        # wrong paper (e.g. a book review instead of the book).
                        # Don't skip; let LLM verify.
                        pass
                    else:
                        return False
                elif error_entry.get('ref_verified_url'):
                    # A verifier confirmed the resource exists but could not
                    # supply real author data (e.g. GitHub repos return only
                    # the org name).  Fall through to LLM assessment.
                    pass
                else:
                    return False
            else:
                return False

    # For 'multiple' type, check if it contains title or author mismatches
    # (not just year+venue)
    if error_type == 'multiple':
        details = (error_entry.get('error_details') or '').lower()
        has_major = any(kw in details for kw in ('title', 'author', 'doi', 'arxiv_id', 'arxiv id',
                                                  'unverified',
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

    # If the reference was found in a database (verified URL exists), there
    # are no title mismatches, and author overlap is reasonable (>= 60%),
    # this is a data-quality issue (version differences, et-al handling)
    # rather than hallucination.  Skip LLM assessment.
    # This generalises the ArXiv version-match shortcut to all verified refs.
    if error_entry.get('ref_verified_url') and error_type != 'unverified':
        has_title_issue = any(
            kw in error_details
            for kw in ('title mismatch', 'inaccurate title')
        )
        if not has_title_issue:
            cited = error_entry.get('ref_authors_cited', '')
            correct = error_entry.get('ref_authors_correct', '')
            if cited and correct:
                cited_list = error_entry.get('_ref_authors_cited_list')
                overlap = _compute_author_overlap(cited, correct, cited_list=cited_list)
                if overlap is not None and overlap >= _AUTHOR_MATCH_THRESHOLD:
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
    if not llm_client:
        return {
            'verdict': 'UNCERTAIN',
            'explanation': 'No LLM configured for hallucination assessment.',
            'web_search': None,
        }

    try:
        # The verifier's assess() checks its disk cache before requiring
        # a live API key, so this works even without an API key in CI.
        result = llm_client.assess(error_entry, web_searcher=web_searcher)
        return result
    except Exception as exc:
        logger.warning(f'Hallucination assessment failed: {exc}')
        return {
            'verdict': 'UNCERTAIN',
            'explanation': f'Assessment failed: {exc}',
            'web_search': None,
        }


def _detect_garbled_metadata(error_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Detect if reference metadata fields are garbled or swapped.

    Returns an UNLIKELY assessment if the title and author fields appear to be
    swapped (e.g. title contains author names, author field contains a paper
    title or description).  This is a PDF extraction error, not hallucination.

    Also detects references where the title is a list of author names
    concatenated with special characters.
    """
    title = (error_entry.get('ref_title') or '').strip()
    authors = (error_entry.get('ref_authors_cited') or '').strip()
    raw_text = ''
    orig = error_entry.get('original_reference', {})
    if orig:
        raw_text = orig.get('raw_text', '') or ''

    if not title or not authors:
        return None

    # Pattern 1: Author field looks like a title (contains colon suggesting
    # "Title: Subtitle" pattern, and title is very short / org-like)
    authors_has_colon = ':' in authors
    title_is_short = len(title) < 20
    # Common org/team names that might end up as the title
    org_names = {'alibaba', 'google', 'meta', 'microsoft', 'openai', 'deepmind',
                 'deepseek', 'qwen', 'anthropic', 'nvidia', 'kuaishou', 'baidu',
                 'tencent', 'huawei', 'bytedance', 'apple', 'amazon'}
    title_is_org = title.lower().strip() in org_names

    if authors_has_colon and (title_is_short or title_is_org):
        return {
            'verdict': 'UNLIKELY',
            'explanation': (
                f'The title and author fields appear to be swapped or garbled '
                f'(title="{title}", authors="{authors[:60]}..."). '
                f'This is a metadata extraction error, not hallucination.'
            ),
            'web_search': None,
        }

    # Pattern 2: Title field contains author names concatenated with asterisks
    # or other separators (common PDF extraction artifact)
    if '*' in title and title.count('*') >= 2:
        # Title looks like "Author1*Author2*Author3" — it's an author list
        parts = [p.strip() for p in title.split('*') if p.strip()]
        # Check if most parts look like person names (2-4 words each)
        name_like = sum(1 for p in parts if 1 <= len(p.split()) <= 5)
        if name_like >= len(parts) * 0.5:
            return {
                'verdict': 'UNLIKELY',
                'explanation': (
                    f'The title field contains what appears to be an author list '
                    f'concatenated with asterisks — this is a metadata extraction '
                    f'error, not hallucination.'
                ),
                'web_search': None,
            }

    # Pattern 3: Title is explicitly a truncation/parsing placeholder
    title_lower = title.lower().strip('() ')
    if title_lower in ('incomplete reference - truncated', 'incomplete reference',
                        'truncated', 'incomplete entry', 'incomplete reference - insufficient data',
                        'incomplete reference insufficient data'):
        return {
            'verdict': 'UNCERTAIN',
            'explanation': (
                f'The reference title is a placeholder indicating a parsing or '
                f'extraction failure ("{title}"), not an AI-fabricated citation.'
            ),
            'web_search': None,
        }

    return None


def pre_screen_hallucination(
    error_entry: Dict[str, Any],
) -> tuple:
    """Run deterministic hallucination pre-screening (no network / LLM).

    This is the **single source of truth** for deciding whether a reference
    needs LLM assessment.  All three code paths (CLI, Batch, WebUI) call
    this function so filtering logic stays consistent.

    Returns
    -------
    ('resolved', assessment_dict)
        A deterministic verdict was reached — apply immediately.
    ('skip', None)
        No hallucination check needed (no real errors, or not suspicious).
    ('needs_llm', None)
        Deterministic checks were inconclusive — run LLM assessment.
    """
    ref_title = error_entry.get('ref_title', '')[:80]

    if not has_real_errors(error_entry):
        logger.debug(f"pre_screen: skip (no real errors) ref={ref_title!r}")
        return ('skip', None)

    name_order = detect_name_order_warning(error_entry)
    if name_order:
        logger.debug(f"pre_screen: resolved (name_order) ref={ref_title!r} verdict={name_order.get('verdict')}")
        return ('resolved', name_order)

    garbled = _detect_garbled_metadata(error_entry)
    if garbled:
        logger.debug(f"pre_screen: resolved (garbled) ref={ref_title!r} verdict={garbled.get('verdict')}")
        return ('resolved', garbled)

    author_result = check_author_hallucination(error_entry)
    if author_result:
        logger.debug(f"pre_screen: resolved (author) ref={ref_title!r} verdict={author_result.get('verdict')}")
        return ('resolved', author_result)

    if not should_check_hallucination(error_entry):
        logger.debug(f"pre_screen: skip (should_check=False) ref={ref_title!r}")
        return ('skip', None)

    logger.debug(f"pre_screen: needs_llm ref={ref_title!r}")
    return ('needs_llm', None)


def run_hallucination_check(
    error_entry: Dict[str, Any],
    llm_client: Any = None,
    web_searcher: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Unified hallucination check — single entry point for CLI, WebUI, and report builder.

    Runs deterministic screening via ``pre_screen_hallucination`` first.
    If inconclusive, runs the LLM-based assessment.

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
    ref_title = error_entry.get('ref_title', '')[:80]
    outcome, assessment = pre_screen_hallucination(error_entry)
    logger.debug(f"run_hallucination_check: pre_screen outcome={outcome} ref={ref_title!r}")
    if outcome == 'resolved':
        # For verified refs where the rule-based check flagged LIKELY
        # (author mismatch), defer to LLM only when author overlap is 0%
        # — the checker may have matched a different paper with the same
        # title, and the LLM can web-search to confirm.  When overlap is
        # >0% but below threshold, some authors DO match, confirming it's
        # the same paper with garbled/fabricated authors — flag
        # deterministically without wasting an LLM call.
        is_verified = bool(error_entry.get('ref_verified_url'))
        author_overlap = assessment.get('author_overlap') if assessment else None
        if (
            is_verified
            and assessment
            and assessment.get('verdict') == 'LIKELY'
        ):
            if author_overlap is None or author_overlap == 0:
                if llm_client:
                    logger.debug(
                        "run_hallucination_check: verified ref flagged LIKELY by rules — deferring to LLM ref=%r",
                        ref_title,
                    )
                    # Fall through to LLM below
                else:
                    # No LLM available, let deterministic verdict stand
                    return assessment
            else:
                # Verified paper with >0% author overlap flagged LIKELY.
                # Only the LLM can disambiguate whether this is a genuine
                # hallucination or a parsing/edition mismatch.  Without
                # an LLM, let the deterministic verdict stand.
                if not llm_client:
                    return assessment
                # With an LLM available, defer to it for verification.
                logger.debug(
                    "run_hallucination_check: verified ref flagged LIKELY by rules "
                    "(overlap=%.0f%%) — deferring to LLM ref=%r",
                    (author_overlap or 0) * 100, ref_title,
                )
                # Fall through to LLM below
        else:
            return assessment
    if outcome == 'skip':
        return None

    # 'needs_llm' — run LLM assessment.  The verifier checks its disk
    # cache before requiring a live API key, so cached results work
    # even when no API key is configured (e.g. CI).
    if llm_client:
        logger.debug(f"run_hallucination_check: calling LLM for ref={ref_title!r}")
        llm_result = assess_hallucination(
            error_entry, llm_client=llm_client, web_searcher=web_searcher,
        )
        if llm_result:
            logger.debug(f"run_hallucination_check: LLM verdict={llm_result.get('verdict')} ref={ref_title!r}")
            return llm_result
    else:
        logger.debug(f"run_hallucination_check: no llm_client for ref={ref_title!r}")

    return None


def _reverify_with_llm_metadata(
    reference: Dict[str, Any],
    old_errors: List[Dict[str, Any]],
    assessment: Dict[str, Any],
) -> Optional[List[Dict[str, Any]]]:
    """Re-verify a reference using LLM-found metadata as the "correct" source.

    When the hallucination check finds the actual paper (UNLIKELY verdict with
    found_title/found_authors/found_year), this function re-runs the standard
    comparison logic against the LLM-found data instead of the DB data.

    This avoids special-casing: the normal error/warning paths produce the
    right output when given correct metadata.

    Returns a new error list, or None if no LLM metadata was available.
    """
    found_title = assessment.get('found_title')
    found_authors = assessment.get('found_authors')
    found_year = assessment.get('found_year')
    ha_link = assessment.get('link')

    if not any([found_title, found_authors, found_year]):
        return None

    from refchecker.utils.text_utils import (
        compare_authors,
        compare_titles_with_latex_cleaning,
        strip_latex_commands,
        are_venues_substantially_different,
    )
    from refchecker.utils.error_utils import (
        format_title_mismatch,
        validate_year,
    )

    new_errors = []

    # --- Title check ---
    cited_title = reference.get('title', '')
    if found_title and cited_title:
        SIMILARITY_THRESHOLD = 0.75
        sim = compare_titles_with_latex_cleaning(cited_title, found_title)
        if sim < SIMILARITY_THRESHOLD:
            clean_cited = strip_latex_commands(cited_title)
            new_errors.append({
                'error_type': 'title',
                'error_details': format_title_mismatch(clean_cited, found_title),
                'ref_title_correct': found_title,
            })

    # --- Author check ---
    cited_authors = reference.get('authors', [])
    if found_authors and cited_authors:
        # Parse LLM-returned author string into list-of-dicts (same format
        # as Semantic Scholar)
        llm_author_list = [
            {'name': a.strip()}
            for a in found_authors.split(',')
            if a.strip()
        ]
        if llm_author_list:
            match, err_msg = compare_authors(cited_authors, llm_author_list)
            if not match:
                correct_str = ', '.join(a['name'] for a in llm_author_list)
                new_errors.append({
                    'error_type': 'author',
                    'error_details': err_msg,
                    'ref_authors_correct': correct_str,
                })

    # --- Year check ---
    cited_year = reference.get('year', 0)
    if found_year:
        import re as _re
        year_match = _re.search(r'\d{4}', str(found_year))
        llm_year = int(year_match.group()) if year_match else None
        if llm_year:
            year_warning = validate_year(
                cited_year=cited_year,
                paper_year=llm_year,
                use_flexible_validation=True,
                context={},
            )
            if year_warning:
                new_errors.append(year_warning)

    # --- Carry forward info-only errors that aren't metadata comparisons ---
    # (e.g. "Reference could include arXiv URL", venue-missing suggestions)
    for e in old_errors:
        if 'info_type' in e and 'error_type' not in e and 'warning_type' not in e:
            new_errors.append(e)

    return new_errors


def apply_hallucination_verdict(
    result: Dict[str, Any],
    assessment: Dict[str, Any],
    reference: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Apply a hallucination assessment verdict to a reference result.

    This is the **single source of truth** for mapping verdict →
    status/errors.  All code paths (CLI, Batch, WebUI) must call this
    function so classification logic stays consistent.

    Parameters
    ----------
    result : dict
        The reference result dict.  Must contain at least ``status`` and
        ``errors``.  May also contain ``_raw_errors`` and
        ``authoritative_urls``.  A shallow copy is made internally —
        the caller's dict is not mutated.
    assessment : dict
        The hallucination assessment with ``verdict``, ``explanation``,
        and optionally ``link``, ``found_title``, ``found_authors``,
        ``found_year``.
    reference : dict, optional
        The original reference dict (with ``title``, ``authors``, ``year``
        etc.).  When provided and the LLM returned found metadata, the
        errors are re-computed by comparing the cited reference against
        the LLM-found data.

    Returns
    -------
    dict — updated copy of *result* with status and errors adjusted.
    """
    result = dict(result)
    result['hallucination_assessment'] = assessment

    verdict = assessment.get('verdict', 'UNCERTAIN')
    ha_link = assessment.get('link')
    ha_explanation = assessment.get('explanation', '')

    # Determine whether this ref can be upgraded to verified / hallucination.
    is_unverified = result.get('status') == 'unverified'
    has_unverified_error = any(
        e.get('error_type') == 'unverified'
        for e in result.get('errors', []) + (result.get('_raw_errors') or [])
    )
    url_references_paper = any(
        'url references paper' in (e.get('error_details') or '').lower()
        for e in result.get('errors', []) + (result.get('_raw_errors') or [])
    )
    is_upgradeable = (
        is_unverified
        or has_unverified_error
        or (result.get('status') == 'error' and url_references_paper)
    )

    if verdict == 'LIKELY':
        result['status'] = 'hallucination'

    elif verdict == 'UNLIKELY' and is_upgradeable:
        if ha_link and ha_link.startswith('http'):
            result['authoritative_urls'] = list(
                result.get('authoritative_urls', [])
            )
            result['authoritative_urls'].append(
                {"type": "llm_verified", "url": ha_link}
            )
            # Strip resolved errors so downstream counters are correct.
            # Remove 'unverified' errors and informational URL-references-paper
            # entries that are now obsolete (the LLM found the paper).
            # Keep substantive URL errors (e.g. "Cited URL does not reference
            # this paper") since those are real metadata issues.
            result['errors'] = [
                e for e in result.get('errors', [])
                if e.get('error_type') != 'unverified'
                and not (
                    e.get('error_type') == 'url'
                    and 'url references paper' in (e.get('error_details') or '').lower()
                )
            ]
            # Only set status to 'verified' if no real errors remain.
            remaining_errors = [
                e for e in result['errors']
                if e.get('error_type') not in ('unverified', 'info', None)
                and not e.get('is_suggestion')
            ]
            result['status'] = 'error' if remaining_errors else 'verified'
        else:
            # LLM confirmed the reference is real (UNLIKELY) but didn't
            # provide a link.  Still strip the unverified error and
            # upgrade the status so the ref isn't counted as unverified.
            result['errors'] = [
                e for e in result.get('errors', [])
                if e.get('error_type') != 'unverified'
            ]
            remaining_errors = [
                e for e in result['errors']
                if e.get('error_type') not in ('unverified', 'info', None)
                and not e.get('is_suggestion')
            ]
            result['status'] = 'error' if remaining_errors else 'verified'

    elif verdict == 'UNLIKELY' and not is_upgradeable:
        # Ref was already "verified" by a DB match, but the LLM confirmed
        # it's a real paper.  If the LLM returned metadata, re-verify the
        # cited reference against the LLM-found data (treating it like a
        # new DB result).  This naturally resolves false-positive errors
        # from wrong-edition DB matches.
        if reference is not None:
            new_errors = _reverify_with_llm_metadata(
                reference, result.get('errors', []), assessment,
            )
            if new_errors is not None:
                result['errors'] = new_errors
                # Update the verified URL to the LLM-found source
                if ha_link and ha_link.startswith('http'):
                    result['authoritative_urls'] = list(
                        result.get('authoritative_urls', [])
                    )
                    result['authoritative_urls'].append(
                        {"type": "llm_verified", "url": ha_link}
                    )
                remaining_errors = [
                    e for e in result['errors']
                    if e.get('error_type') not in ('unverified', 'info', None)
                    and not e.get('is_suggestion')
                ]
                result['status'] = 'error' if remaining_errors else 'verified'
        else:
            # No reference dict available — fall back to heuristic clearing.
            has_doi_mismatch = any(
                'doi mismatch' in (e.get('error_details') or '').lower()
                for e in result.get('errors', [])
            )
            if has_doi_mismatch:
                result['errors'] = [
                    e for e in result.get('errors', [])
                    if not any(kw in (e.get('error_details') or '').lower()
                               for kw in ('doi mismatch', 'author'))
                ]
                remaining_errors = [
                    e for e in result['errors']
                    if e.get('error_type') not in ('unverified', 'info', None)
                    and not e.get('is_suggestion')
                ]
                result['status'] = 'error' if remaining_errors else 'verified'

    elif verdict != 'LIKELY' and (is_unverified or has_unverified_error):
        # UNCERTAIN or UNLIKELY-but-not-upgradeable: annotate the
        # unverified error with the explanation if available.
        if ha_explanation:
            result['errors'] = [
                {**e, 'error_details':
                 f"Reference could not be verified — {ha_explanation}"}
                if e.get('error_type') == 'unverified' else e
                for e in result.get('errors', [])
            ]

    return result
