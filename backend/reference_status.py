"""Canonical verification-result classification for the web backend.

Turning the checker's raw `(verified_data, errors, url)` tuple into a status and
a sanitized issue list is subtle: the checker signals severity by *which key* it
sets (`error_type` / `warning_type` / `info_type`), and several categories get
reclassified after the fact (timeouts become "unverified", a URL error against a
non-academic link is dropped when the webpage checker already confirmed the
paper, and so on).

This lived inline in `ProgressRefChecker._format_verification_result`, which
meant the single-reference re-verify endpoint in `main.py` had its own
hand-rolled copy. That copy flattened `warning_type` into `error_type` and so
could never return `error` — re-verifying a reference with a genuine author
mismatch silently downgraded it to a warning, while the very same checker output
came back as an error through the normal batch flow.

Both callers now share the implementation below.
"""

from typing import Any, Dict, List, Optional, Tuple


def sanitize_errors(errors: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Normalize raw checker findings, preserving their original severity.

    The checker distinguishes severity by key (`error_type` vs `warning_type` vs
    `info_type`); collapsing them all onto `error_type` without recording where
    they came from is what made severity unrecoverable downstream, so the origin
    is kept as the `is_warning` / `is_suggestion` flags.
    """
    sanitized: List[Dict[str, Any]] = []
    for err in (errors or []):
        e_type = err.get('error_type') or err.get('warning_type') or err.get('info_type')
        details = err.get('error_details') or err.get('warning_details') or err.get('info_details')
        if not e_type and not details:
            continue
        is_info = 'info_type' in err
        is_warning = 'warning_type' in err
        # Backfill actual_value from the typed correction fields: "missing"
        # issues (year/venue/title/authors) populate ONLY ref_*_correct, not
        # actual_value, so the corrected-bibtex builder would otherwise drop
        # exactly the value the warning told the user to add.
        _actual = err.get('actual_value')
        if not _actual:
            _actual = (err.get('ref_year_correct') or err.get('ref_venue_correct')
                       or err.get('ref_title_correct') or err.get('ref_authors_correct')
                       or err.get('ref_doi_correct'))
        _san = {
            # Map 'timeout' to 'unverified' since timeouts mean we couldn't verify.
            "error_type": 'unverified' if e_type == 'timeout' else (e_type or 'unknown'),
            "error_details": details if e_type != 'timeout' else 'Verification timed out',
            "cited_value": err.get('cited_value'),
            "actual_value": _actual,
            "is_suggestion": is_info,
            "is_warning": is_warning,
        }
        # Carry the typed correction fields through so the FE corrected-bibtex
        # builder can recover year/venue/title/authors even when the checker
        # only set the typed field.
        for _k in ("ref_year_correct", "ref_venue_correct", "ref_title_correct",
                   "ref_authors_correct", "ref_doi_correct"):
            if err.get(_k):
                _san[_k] = err.get(_k)
        sanitized.append(_san)
    return sanitized


def _is_url_references_paper(entry: Dict[str, Any]) -> bool:
    """A 'url' finding the webpage checker resolved in the reference's favour."""
    return (
        entry.get('error_type') == 'url'
        and 'url references paper' in (entry.get('error_details') or '').lower()
    )


def classify_verification_result(
    reference: Dict[str, Any],
    verified_data: Optional[Dict[str, Any]],
    errors: Optional[List[Dict[str, Any]]],
    url: Optional[str],
) -> Tuple[str, List[Dict[str, Any]]]:
    """Return `(status, sanitized_errors)` for one verified reference.

    `status` is one of: error, warning, suggestion, verified, unverified.
    """
    sanitized = sanitize_errors(errors)

    has_errors = any(
        e.get('error_type') not in ['unverified']
        and not e.get('is_suggestion')
        and not e.get('is_warning')
        # 'url' errors where the URL references the paper are informational,
        # not real errors — the webpage checker confirmed the cited URL
        # contains the paper title.
        and not _is_url_references_paper(e)
        for e in sanitized
    )
    has_warnings = any(e.get('is_warning') and not e.get('is_suggestion') for e in sanitized)
    has_suggestions = any(e.get('is_suggestion') for e in sanitized)
    is_unverified = any(e.get('error_type') == 'unverified' for e in sanitized)
    url_references_paper = any(
        'url references paper' in (e.get('error_details') or '').lower()
        for e in (errors or [])
    )

    if is_unverified:
        from refchecker.checkers.web_search import is_academic_url

        cited_url = reference.get('cited_url') or reference.get('url') or url or ''
        real_errors = [
            e for e in sanitized
            if e.get('error_type') != 'unverified'
            and not e.get('is_suggestion')
            and not e.get('is_warning')
        ]
        cited_url_lower = cited_url.lower()
        is_direct_pdf = cited_url_lower.split('?', 1)[0].endswith('.pdf')
        if (
            real_errors
            and all(e.get('error_type') == 'url' for e in real_errors)
            and not is_academic_url(cited_url)
            and (not is_direct_pdf or 'openai.com' in cited_url_lower)
        ):
            sanitized = [e for e in sanitized if e.get('error_type') != 'url']
            has_errors = False

    if has_errors:
        status = 'error'
    elif has_warnings:
        status = 'warning'
    elif has_suggestions:
        status = 'suggestion'
    elif is_unverified and url_references_paper:
        # The cited URL was checked and confirmed to contain the paper —
        # treat as verified even though it wasn't found in academic databases.
        status = 'verified'
        # Strip the unverified + url-references-paper errors since they're
        # now resolved — the URL confirms the paper exists.
        sanitized = [
            e for e in sanitized
            if e.get('error_type') != 'unverified' and not _is_url_references_paper(e)
        ]
    elif is_unverified:
        status = 'unverified'
    else:
        status = 'verified'

    return status, sanitized


def split_errors_and_warnings(
    sanitized: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split a sanitized list into the `errors` / `warnings` fields of a row.

    Keeping warnings out of `errors` matters for display as well as counts: the
    status-icon precedence is hallucination > error > warning, so a warning left
    sitting in `errors` renders an error icon that contradicts the row's own
    status.
    """
    errors = [
        e for e in sanitized
        if e.get('error_type')
        and e.get('error_type') != 'unverified'
        and not e.get('is_warning')
        and not e.get('is_suggestion')
    ]
    warnings = [e for e in sanitized if e.get('is_warning') and not e.get('is_suggestion')]
    return errors, warnings
