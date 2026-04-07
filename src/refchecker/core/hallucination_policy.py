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
_AUTHOR_VERIFIED_THRESHOLD = 0.2  # Stricter: flag if < 20% match (verified refs)

# Team/organisation names that appear as first "author" in large collaborative
# papers.  These are stripped before computing author overlap because the DB
# may concatenate them with the first real author.
_TEAM_NAMES = frozenset({
    'deepseek-ai', 'qwen', 'openai', 'microsoft', 'google', 'meta',
    'team glm', 'gemini team', 'core team', 'v team',
    '01.ai', 'ai', 'lcm team', 'the lcm team',
})


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
    diacritics, name-format variations, and FirstName/LastName swaps.

    Strips known team/organisation names (e.g. "DeepSeek-AI", "Qwen") that
    the DB may concatenate with the first real author, causing false mismatches.

    For long author lists (>10 authors), compares only the first 10 from each
    list.  Database records often truncate differently, so comparing the full
    30+-author list produces false-low overlap.
    """
    if not cited_authors or not correct_authors:
        return None

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
    # For verified refs, allow 'author' and 'multiple' (they have author errors)
    if is_verified:
        if error_type not in ('author', 'multiple', ''):
            return None
    else:
        if error_type not in ('unverified', 'author', 'multiple', ''):
            return None

    cited = error_entry.get('ref_authors_cited', '')
    correct = error_entry.get('ref_authors_correct', '')

    if not cited or not correct:
        return None

    overlap = _compute_author_overlap(cited, correct)
    if overlap is None:
        return None

    # For verified references, use a stricter threshold: only flag when
    # author overlap is critically low (< 20%), indicating the LLM found
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
                       'could not be verified', 'could not verify',
                       'title mismatch', 'inaccurate title')
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
                    overlap = _compute_author_overlap(cited, correct)
                    if overlap is not None and overlap < _AUTHOR_VERIFIED_THRESHOLD:
                        pass  # Don't skip — authors critically mismatched
                    else:
                        return False
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
                overlap = _compute_author_overlap(cited, correct)
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


def run_hallucination_check(
    error_entry: Dict[str, Any],
    llm_client: Any = None,
    web_searcher: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Unified hallucination check — single entry point for CLI, WebUI, and report builder.

    Runs the deterministic author-overlap check first, then the LLM-based
    assessment.  When an LLM is available, it always runs (for any error
    type, verified or not) so it can override the deterministic verdict —
    e.g. the LLM may find a different paper that actually matches.

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
    # 1. Deterministic: check for name-ordering issues first (warning, not hallucination)
    name_order_result = detect_name_order_warning(error_entry)
    if name_order_result:
        return name_order_result

    # 1b. Detect garbled/swapped metadata fields — a PDF extraction error, not hallucination.
    #     Key signal: the author field looks like a title/description (contains colons
    #     or is very long with spaces), or the title field is extremely short and looks
    #     like an organization name while the author field looks like a title.
    garbled_result = _detect_garbled_metadata(error_entry)
    if garbled_result:
        return garbled_result

    # 2. Deterministic: author-overlap check (no LLM)
    author_result = check_author_hallucination(error_entry)

    # 3. LLM-based: always run when LLM is available, for any error type.
    #    The LLM can override the deterministic verdict — e.g. it may find
    #    a different paper with the same title where the cited authors DO
    #    match, proving the citation is real despite the DB mismatch.
    if llm_client and getattr(llm_client, 'available', False):
        if should_check_hallucination(error_entry):
            llm_result = assess_hallucination(
                error_entry, llm_client=llm_client, web_searcher=web_searcher,
            )
            if llm_result:
                return llm_result

    # Fall back to deterministic result if LLM was unavailable or didn't run
    return author_result
