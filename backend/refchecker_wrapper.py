"""
Wrapper around refchecker library with progress callbacks for real-time updates
"""
import sys
import os
import re
import io
import asyncio
import logging
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from types import SimpleNamespace

# Debug file logging
DEBUG_LOG_FILE = Path(tempfile.gettempdir()) / "refchecker_debug.log"
def debug_log(msg: str):
    from datetime import datetime
    with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%H:%M:%S.%f')[:12]} {msg}\n")

# Add src to path to import refchecker when running from source
# This is only needed when not installed as a package
_src_path = str(Path(__file__).parent.parent / "src")
if _src_path not in sys.path and os.path.exists(_src_path):
    sys.path.insert(0, _src_path)

from backend.concurrency import create_limiter, get_default_max_concurrent
from backend.auth import is_multiuser_mode
from backend.database import get_data_dir

from refchecker.utils.text_utils import extract_latex_references
from refchecker.utils.url_utils import extract_arxiv_id_from_url, construct_semantic_scholar_url
from refchecker.services.pdf_processor import PDFProcessor
from refchecker.llm.base import create_llm_provider, ReferenceExtractor
from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.core.hallucination_policy import (
    apply_hallucination_verdict,
    build_hallucination_error_entry,
    count_raw_errors,
    has_real_raw_errors,
    pre_screen_hallucination,
    run_hallucination_check,
    should_defer_likely_to_llm,
)
from refchecker.utils.arxiv_utils import download_arxiv_paper_pdf, get_arxiv_paper_by_id, get_bibtex_content
from refchecker.utils.cache_utils import (
    cache_bibliography,
    cached_bibliography,
    get_cached_artifact_path,
    llm_cache_identity_from_extractor,
)
from refchecker.utils.grobid import extract_pdf_references_with_grobid_fallback
import arxiv

logger = logging.getLogger(__name__)


def _llm_found_metadata_matches_citation(result: Dict[str, Any]) -> bool:
    assessment = result.get('hallucination_assessment') or {}
    if assessment.get('verdict') != 'LIKELY' or not assessment.get('link'):
        return False

    def normalize(value: Any) -> str:
        return re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()

    cited_title = normalize(result.get('title'))
    found_title = normalize(assessment.get('found_title'))
    if not cited_title or cited_title != found_title:
        return False

    found_authors = str(assessment.get('found_authors') or '').lower()
    cited_last_names = [
        str(author or '').strip().split()[-1].lower()
        for author in (result.get('authors') or [])
        if str(author or '').strip()
    ]
    if not cited_last_names or not all(name in found_authors for name in cited_last_names):
        return False

    cited_year = result.get('year')
    found_year = str(assessment.get('found_year') or '')
    return not cited_year or str(cited_year) in found_year


def download_pdf(url: str, dest_path: str) -> None:
    """Download a PDF with browser-like headers (avoids 403 from OpenReview etc.)."""
    import tempfile, os
    from refchecker.utils.url_utils import download_pdf_bytes
    data = download_pdf_bytes(url)
    # Write to a temp file first, then atomically rename to avoid race conditions
    # where another thread sees the partially-written file.
    dir_name = os.path.dirname(dest_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.pdf.tmp')
    try:
        os.write(fd, data)
        os.close(fd)
        os.replace(tmp_path, dest_path)
    except Exception:
        os.close(fd)
        os.unlink(tmp_path)
        raise


def _process_llm_references_cli_style(references: List[Any]) -> List[Dict[str, Any]]:
    """Use the CLI's post-processing logic to structure LLM references.

    We intentionally reuse the exact methods from the CLI's ArxivReferenceChecker
    (without running its heavy __init__) to avoid diverging behavior between
    CLI and Web extraction.
    """
    cli_checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    return cli_checker._process_llm_extracted_references(references)


def _make_cli_checker(llm_provider):
    """Create a lightweight ArxivReferenceChecker instance for parsing only.

    We bypass __init__ to avoid heavy setup and set just the fields needed for
    bibliography finding and reference parsing so that logic/order matches CLI.
    """
    cli_checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    cli_checker.llm_extractor = ReferenceExtractor(llm_provider) if llm_provider else None
    cli_checker.llm_enabled = bool(llm_provider)
    cli_checker.used_regex_extraction = False
    cli_checker.used_unreliable_extraction = False
    cli_checker.fatal_error = False
    return cli_checker


_NUMERIC_MARKER_RE = None

# Common abbreviations whose trailing "." is NOT a sentence terminator —
# kept lowercase for case-insensitive comparison against the last token
# in a candidate split.
_ABBREVIATIONS = frozenset({
    "e.g.", "i.e.", "et al.", "fig.", "eq.", "tab.", "sec.", "app.",
    "ref.", "cf.", "vs.", "no.", "st.", "mr.", "dr.", "mrs.", "ms.",
    "jr.", "sr.", "inc.", "co.", "ltd.", "prof.", "univ.", "dept.",
})


def _sentence_tokenize(text):
    """Sentence-split with abbreviation guards. Python's stdlib `re` only
    supports fixed-width lookbehind, so we split aggressively on
    `[.!?] [A-Z(]` then merge any neighbouring pair whose left half ends
    with one of the known abbreviations (or a single-capital initial like
    'U.'). Good enough for grouping a citation marker with its
    surrounding clause; avoids pulling in a regex backport just for this.

    Multi-word abbreviations like "et al." are matched against the
    trailing two tokens, not just the last one — otherwise
    "Vaswani et al. (2017)" splits at the period (because the
    open-paren in the lookahead triggers a sentence break) and
    "al." alone isn't in the abbreviation list.
    """
    import re
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z\(])", text)
    if len(raw) <= 1:
        return raw
    merged = [raw[0]]
    for piece in raw[1:]:
        prev = merged[-1]
        # Find the last whitespace-separated token in prev — that's the
        # candidate "word." that triggered the split.
        last_token = prev.rsplit(" ", 1)[-1] if " " in prev else prev
        lt_lower = last_token.lower()
        # Multi-word abbreviation check: also peek at the last two tokens
        # joined so phrases like "et al." (whose last single token is
        # "al.") get caught.
        tail_two = " ".join(prev.rsplit(" ", 2)[-2:]).lower() if " " in prev else ""
        is_abbrev = lt_lower in _ABBREVIATIONS or tail_two in _ABBREVIATIONS
        # Single-capital + period (initials in author names: "J. Smith").
        is_initial = (
            len(last_token) >= 2
            and last_token[-1] == "."
            and last_token[-2].isalpha()
            and last_token[:-1].isupper()
            and len(last_token) <= 3
        )
        if is_abbrev or is_initial:
            merged[-1] = prev + " " + piece
        else:
            merged.append(piece)
    return merged


def _attach_citation_contexts(references, paper_text):
    """Find the sentences in the paper where each reference is cited.

    Two heuristics — numeric ``[N]`` markers (IEEE / ACM style) and
    author-year markers like ``(Smith et al., 2020)`` / ``Smith (2020)``
    (APA / Chicago style).

    For every reference whose `index` matches a `[N]` marker (or whose
    (first-author surname, year) matches an author-year marker) in the
    body text, attaches:

    - ``citation_count``  — how many times the ref is cited
    - ``citation_contexts`` — list of ``{sentence, marker, before, after}``
      where each entry is one occurrence with its surrounding clause and
      the literal marker text (so the frontend can render it bold). Up to
      3 occurrences per ref.
    - ``citation_context`` — legacy single-string field, kept so older UI
      paths that haven't migrated still render something. Joined with " … ".

    Heuristic only — no LLM call, runs in O(sentences × markers) and adds
    a few ms per reference for a typical paper. The sentence tokenizer
    guards against fragmenting on "et al.", "e.g.", initials, etc., so
    citation contexts read naturally instead of cutting mid-clause.
    """
    if not references or not paper_text:
        return
    import re
    global _NUMERIC_MARKER_RE
    if _NUMERIC_MARKER_RE is None:
        # Match `[12]`, `[12, 14]`, `[12-15]`, `[12–15]`, including
        # space tolerance. The outer match's group(0) is the whole marker
        # so we can highlight it; inner findall pulls the numbers out.
        _NUMERIC_MARKER_RE = re.compile(
            r"\[\s*\d{1,3}(?:\s*[\-–,;]\s*\d{1,3})*\s*\]"
        )

    sentences = _sentence_tokenize(paper_text)

    # For each numeric index N, collect a list of
    #   {sentence, marker, before, after}
    # entries — one per occurrence, with surrounding sentences trimmed
    # so the UI has a small context window without spilling the whole
    # paragraph.
    by_index = {}
    for i, sent in enumerate(sentences):
        stripped = sent.strip()
        if not stripped:
            continue
        for m in _NUMERIC_MARKER_RE.finditer(stripped):
            marker_text = m.group(0)
            nums_in_marker = [int(n) for n in re.findall(r"\d{1,3}", marker_text)]
            # Expand `[12-15]` and `[12–15]` into a contiguous range so
            # the readers see the citation even for inclusive ranges.
            expanded = set()
            range_match = re.match(r"\s*(\d+)\s*[\-–]\s*(\d+)\s*$", marker_text.strip("[]"))
            if range_match:
                lo, hi = sorted((int(range_match.group(1)), int(range_match.group(2))))
                # Cap the expansion so a typo `[1-999]` doesn't blow up.
                if hi - lo <= 50:
                    expanded.update(range(lo, hi + 1))
            for n in nums_in_marker:
                expanded.add(n)
            # Trim the sentence aggressively but keep enough on either
            # side of the marker that the citation reads naturally.
            sent_clean = re.sub(r"\s+", " ", stripped)[:420]
            before = (sentences[i - 1].strip()[:160] + " ") if i > 0 else ""
            after = (" " + sentences[i + 1].strip()[:160]) if i + 1 < len(sentences) else ""
            for n in expanded:
                lst = by_index.setdefault(n, [])
                if len(lst) >= 3:
                    continue
                lst.append({
                    "sentence": sent_clean,
                    "marker": marker_text,
                    "before": before.strip(),
                    "after": after.strip(),
                })

    # Second pass: author-year markers (APA / Chicago / natbib).
    # Handles "(Smith et al., 2024)", "Smith et al. (2024)", "(Smith and
    # Jones, 2024)", "(Smith, 2024)", "Smith (2024)". Many papers use
    # these instead of [N] markers, and the original numeric-only
    # extractor silently returned zero contexts for them. Lookup builds
    # a {(last_name_lower, year_int): ref_index} table from the
    # references list, then scans body sentences for the patterns.
    author_year_lookup = {}
    for ref in references:
        try:
            ref_idx = int(ref.get("index") or 0)
        except Exception:
            continue
        if ref_idx <= 0:
            continue
        authors = ref.get("authors") or []
        if not isinstance(authors, list) or not authors:
            continue
        year = ref.get("year")
        try:
            year_int = int(year) if year else 0
        except Exception:
            year_int = 0
        if not year_int:
            continue
        # First author's last name = last whitespace-separated token,
        # stripped of punctuation. Handles "Smith", "John Smith", "Smith,
        # John" (in which case the first word is the last name).
        first = (authors[0] or "").strip()
        if not first:
            continue
        if "," in first:
            last_name = first.split(",", 1)[0].strip()
        else:
            last_name = first.split()[-1] if first.split() else first
        last_name = re.sub(r"[^A-Za-z\-]", "", last_name).lower()
        if len(last_name) < 2:
            continue
        # First-key collisions (multiple refs with same first author +
        # year) are rare but real; keep the lowest-index winner for
        # determinism, matching numeric markers' first-occurrence behavior.
        key = (last_name, year_int)
        if key not in author_year_lookup or ref_idx < author_year_lookup[key]:
            author_year_lookup[key] = ref_idx

    if author_year_lookup:
        # Two patterns covering the common citation forms. Each one
        # captures the surface name and the year as separate groups so
        # we can look up the ref. `et al.` and `and X` are absorbed into
        # the "name" group via a non-capturing extension so the lookup
        # only sees the first author's last name.
        au_yr_patterns = [
            # "(Smith et al., 2024)" / "(Smith and Jones 2024)"
            re.compile(r"\(\s*([A-Z][A-Za-z\-']+)(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][A-Za-z\-']+)?[\s,]+(\d{4})[a-z]?\s*\)"),
            # "Smith et al. (2024)" / "Smith (2024)"
            re.compile(r"\b([A-Z][A-Za-z\-']+)(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][A-Za-z\-']+)?\s*\((\d{4})[a-z]?\)"),
        ]
        for i, sent in enumerate(sentences):
            stripped = sent.strip()
            if not stripped:
                continue
            for pat in au_yr_patterns:
                for m in pat.finditer(stripped):
                    name = re.sub(r"[^A-Za-z\-]", "", m.group(1)).lower()
                    try:
                        yr = int(m.group(2))
                    except Exception:
                        continue
                    ref_idx = author_year_lookup.get((name, yr))
                    if not ref_idx:
                        continue
                    sent_clean = re.sub(r"\s+", " ", stripped)[:420]
                    lst = by_index.setdefault(ref_idx, [])
                    if len(lst) >= 3:
                        continue
                    # Skip if this exact sentence already attributed to
                    # this ref via the numeric pass (avoid dupes when a
                    # paper uses both styles).
                    if any(existing.get("sentence") == sent_clean for existing in lst):
                        continue
                    lst.append({
                        "sentence": sent_clean,
                        "marker": m.group(0),
                        "before": (sentences[i - 1].strip()[:160] if i > 0 else "").strip(),
                        "after": (sentences[i + 1].strip()[:160] if i + 1 < len(sentences) else "").strip(),
                    })

    for ref in references:
        try:
            idx = int(ref.get("index") or 0)
        except Exception:
            continue
        if idx <= 0:
            continue
        hits = by_index.get(idx)
        if not hits:
            continue
        ref["citation_contexts"] = hits
        ref["citation_count"] = len(hits)
        # Legacy single-string field — kept so consumers that don't yet
        # know about citation_contexts still see something useful.
        ref["citation_context"] = " … ".join(h["sentence"][:240] for h in hits[:2])


def _extract_pdf_text_cli_style(pdf_path: str, llm_provider) -> str:
    """Extract PDF text using the same method as the CLI checker.

    This keeps WebUI text extraction behavior aligned with CLI/bulk and avoids
    path-specific PDF parsing differences before bibliography detection.
    """
    cli_checker = _make_cli_checker(llm_provider)
    with open(pdf_path, 'rb') as pdf_file:
        return cli_checker.extract_text_from_pdf(io.BytesIO(pdf_file.read()))


def _normalize_reference_fields(ref: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize reference field names for consistency.
    
    The parser uses 'journal' but the rest of the pipeline expects 'venue'.
    This function normalizes field names for consistent handling.
    """
    # Map 'journal' to 'venue' if venue is not set
    if ref.get('journal') and not ref.get('venue'):
        ref['venue'] = ref['journal']
    return ref


# Default max concurrent reference checks (similar to CLI default)
# This value is now managed by the global concurrency limiter
DEFAULT_MAX_CONCURRENT_CHECKS = 6


class ProgressRefChecker:
    """
    RefChecker wrapper with progress callbacks for real-time updates
    """

    def __init__(self,
                 llm_provider: Optional[str] = None,
                 llm_model: Optional[str] = None,
                 api_key: Optional[str] = None,
                 endpoint: Optional[str] = None,
                 use_llm: bool = True,
                 progress_callback: Optional[Callable] = None,
                 cancel_event: Optional[asyncio.Event] = None,
                 check_id: Optional[int] = None,
                 title_update_callback: Optional[Callable] = None,
                 bibliography_source_callback: Optional[Callable] = None,
                 semantic_scholar_api_key: Optional[str] = None,
                 db_path: Optional[str] = None,
                 db_paths: Optional[Dict[str, str]] = None,
                 cache_dir: Optional[str] = None,
                 hallucination_provider: Optional[str] = None,
                 hallucination_model: Optional[str] = None,
                 hallucination_api_key: Optional[str] = None,
                 hallucination_endpoint: Optional[str] = None):
        """
        Initialize the progress-aware refchecker

        Args:
            llm_provider: LLM provider (anthropic, openai, google, etc.)
            llm_model: Specific model to use
            api_key: API key for the LLM provider
            use_llm: Whether to use LLM for reference extraction
            progress_callback: Async callback for progress updates
            check_id: Database ID for this check (for updating title)
            title_update_callback: Async callback to update title in DB
            bibliography_source_callback: Async callback to save bibliography source content
        """
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.api_key = api_key
        self.endpoint = endpoint
        self.use_llm = use_llm
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event
        self.check_id = check_id
        self.title_update_callback = title_update_callback
        self.bibliography_source_callback = bibliography_source_callback
        self.cache_dir = cache_dir or str(get_data_dir() / "cache")
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

        # Initialize LLM if requested
        self.llm = None
        if use_llm and llm_provider:
            if is_multiuser_mode() and llm_provider.strip().lower() == "vllm":
                raise ValueError("vLLM is only supported in single-user local deployments")
            try:
                # Build config dict for the LLM provider
                llm_config = {}
                if llm_model:
                    llm_config['model'] = llm_model
                if api_key:
                    llm_config['api_key'] = api_key
                if endpoint:
                    llm_config['endpoint'] = endpoint
                logger.info(f"Creating LLM provider '{llm_provider}' with api_key={'present' if api_key else 'MISSING'}, model={llm_model}")
                provider = create_llm_provider(
                    provider_name=llm_provider,
                    config=llm_config
                )
                if provider.is_available():
                    provider.cache_dir = cache_dir
                    self.llm = provider
                    logger.info(f"LLM provider '{llm_provider}' initialized and available")
                else:
                    logger.warning(f"LLM provider '{llm_provider}' created but NOT available (no valid API key). "
                                   f"Checked: config api_key={'present' if api_key else 'MISSING'}, "
                                   f"env REFCHECKER_ANTHROPIC_API_KEY={'set' if os.getenv('REFCHECKER_ANTHROPIC_API_KEY') else 'unset'}, "
                                   f"env ANTHROPIC_API_KEY={'set' if os.getenv('ANTHROPIC_API_KEY') else 'unset'}")
            except Exception as e:
                logger.error(f"Failed to initialize LLM: {e}")

        # Initialize reference checker
        self.hallucination_verifier = None
        try:
            from refchecker.config.settings import HALLUCINATION_CAPABLE_PROVIDERS
            from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier

            # Determine which provider to use for hallucination checking
            if hallucination_provider:
                h_provider = hallucination_provider
                h_model = hallucination_model
                h_api_key = hallucination_api_key
                h_endpoint = hallucination_endpoint
            elif llm_provider and llm_provider in HALLUCINATION_CAPABLE_PROVIDERS:
                h_provider = llm_provider
                h_model = llm_model
                h_api_key = api_key
                h_endpoint = endpoint
            else:
                h_provider = None
                h_model = None
                h_api_key = None
                h_endpoint = None

            if h_provider or cache_dir:
                verifier = LLMHallucinationVerifier(
                    provider=h_provider,
                    api_key=h_api_key,
                    endpoint=h_endpoint,
                    model=h_model,
                )
                verifier.cache_dir = cache_dir
                if verifier.available or cache_dir:
                    self.hallucination_verifier = verifier
                    logger.info(
                        'Hallucination verifier configured for web UI (provider=%s, model=%s, available=%s, key=%s, cache=%s)',
                        verifier.provider,
                        verifier.model,
                        verifier.available,
                        'present' if h_api_key else 'resolved-from-env' if verifier.available else 'missing',
                        bool(cache_dir),
                    )
        except Exception as e:
            logger.debug(f'Hallucination verifier init failed: {e}')
        # Web UI Semantic Scholar keys are supplied per request from the browser.
        ss_api_key = semantic_scholar_api_key
        if ss_api_key:
            logger.info("Semantic Scholar API key configured")
        self.checker = EnhancedHybridReferenceChecker(
            semantic_scholar_api_key=ss_api_key,
            db_path=db_path,
            db_paths=db_paths,
            debug_mode=False,
            cache_dir=cache_dir,
        )
        if db_path:
            logger.info(f"Using local Semantic Scholar database at {db_path}")

    def _format_verification_result(
        self,
        reference: Dict[str, Any],
        index: int,
        verified_data: Optional[Dict[str, Any]],
        errors: List[Dict[str, Any]],
        url: Optional[str]
    ) -> Dict[str, Any]:
        """
        Format verification result into a standardized response.
        
        Shared by both async and sync verification methods.
        """
        # Normalize errors to align with CLI behavior
        logger.info(f"_format_verification_result: raw errors={errors}")
        sanitized = []
        for err in (errors or []):
            e_type = err.get('error_type') or err.get('warning_type') or err.get('info_type')
            details = err.get('error_details') or err.get('warning_details') or err.get('info_details')
            if not e_type and not details:
                continue
            # Track if this was originally an info_type (suggestion, not error)
            is_info = 'info_type' in err
            # Track if this was originally a warning_type (warning, not error)
            is_warning = 'warning_type' in err
            logger.info(f"Sanitizing error: e_type={e_type}, is_info={is_info}, is_warning={is_warning}, keys={list(err.keys())}")
            sanitized.append({
                # Preserve original error_type for suggestion_type mapping;
                # use is_suggestion flag for categorization instead.
                # Map 'timeout' to 'unverified' since timeouts mean we couldn't verify
                "error_type": 'unverified' if e_type == 'timeout' else (e_type or 'unknown'),
                "error_details": details if e_type != 'timeout' else 'Verification timed out',
                "cited_value": err.get('cited_value'),
                "actual_value": err.get('actual_value'),
                "is_suggestion": is_info,  # Preserve info_type as suggestion flag
                "is_warning": is_warning,  # Preserve warning_type as warning flag
            })

        # Determine status - items originally from warning_type are warnings, items from error_type are errors
        # Items originally from info_type are suggestions, not errors
        # Items originally from warning_type are warnings, not errors
        # Items with error_type (including year/venue/author when missing) are errors
        has_errors = any(
            e.get('error_type') not in ['unverified'] 
            and not e.get('is_suggestion')
            and not e.get('is_warning')
            # 'url' errors where the URL references the paper are informational,
            # not real errors — the webpage checker confirmed the cited URL
            # contains the paper title.
            and not (
                e.get('error_type') == 'url'
                and 'url references paper' in (e.get('error_details') or '').lower()
            )
            for e in sanitized
        )
        has_warnings = any(
            e.get('is_warning')
            and not e.get('is_suggestion') 
            for e in sanitized
        )
        has_suggestions = any(e.get('is_suggestion') for e in sanitized)
        is_unverified = any(e.get('error_type') == 'unverified' for e in sanitized)
        # Check if the URL was confirmed to reference the paper (webpage checker verified it)
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
                if e.get('error_type') != 'unverified'
                and not (
                    e.get('error_type') == 'url'
                    and 'url references paper' in (e.get('error_details') or '').lower()
                )
            ]
        elif is_unverified:
            status = 'unverified'
        else:
            status = 'verified'

        # Extract authoritative URLs with proper type detection
        authoritative_urls = []
        verified_via_cited_url = status == 'verified' and url_references_paper
        verified_via_webpage = verified_via_cited_url or bool((verified_data or {}).get('web_metadata'))
        # Don't show verification URL as authoritative when the reference is
        # actually unverified (no database matched) — the URL may point at a
        # completely different paper.
        if verified_via_webpage:
            cited_url = reference.get('cited_url') or reference.get('url') or url or ''
            if cited_url:
                authoritative_urls.append({"type": "verified_url", "url": cited_url})
        elif url and not (is_unverified and not verified_data):
            url_type = "other"
            if "semanticscholar.org" in url:
                url_type = "semantic_scholar"
            elif "openalex.org" in url:
                url_type = "openalex"
            elif "crossref.org" in url or "doi.org" in url:
                url_type = "doi"
            elif "openreview.net" in url:
                url_type = "openreview"
            elif "arxiv.org" in url:
                url_type = "arxiv"
            authoritative_urls.append({"type": url_type, "url": url})

        # Extract external IDs from verified data (Semantic Scholar format)
        if verified_data:
            external_ids = verified_data.get('externalIds', {})

            # Add ArXiv URL if available
            arxiv_id = external_ids.get('ArXiv') or verified_data.get('arxiv_id')
            if arxiv_id:
                arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
                if not any(u.get('url') == arxiv_url for u in authoritative_urls):
                    authoritative_urls.append({"type": "arxiv", "url": arxiv_url})

            # Add DOI URL if available
            doi = external_ids.get('DOI') or verified_data.get('doi')
            if doi:
                doi_url = f"https://doi.org/{doi}"
                if not any(u.get('url') == doi_url for u in authoritative_urls):
                    authoritative_urls.append({"type": "doi", "url": doi_url})

            # Add Semantic Scholar URL if available
            s2_paper_id = external_ids.get('S2PaperId')
            if s2_paper_id:
                s2_url = construct_semantic_scholar_url(s2_paper_id)
                if not any(u.get('url') == s2_url for u in authoritative_urls):
                    authoritative_urls.append({"type": "semantic_scholar", "url": s2_url})
            
            # Also check for inline S2 URL (from merged data)
            s2_inline_url = verified_data.get('_semantic_scholar_url')
            if s2_inline_url and not any(u.get('url') == s2_inline_url for u in authoritative_urls):
                authoritative_urls.append({"type": "semantic_scholar", "url": s2_inline_url})

        # Format errors, warnings, and suggestions
        formatted_errors = []
        formatted_warnings = []
        formatted_suggestions = []
        for err in sanitized:
            err_obj = {
                "error_type": err.get('error_type', 'unknown'),
                "error_details": err.get('error_details', ''),
                "cited_value": err.get('cited_value'),
                "actual_value": err.get('actual_value')
            }
            # Check is_suggestion flag (set when original had info_type)
            if err.get('is_suggestion'):
                # Store as suggestion with full details
                formatted_suggestions.append({
                    "suggestion_type": err.get('error_type') or 'info',
                    "suggestion_details": err.get('error_details', '')
                })
            elif err.get('is_warning'):
                # Only items with is_warning flag (originally warning_type) go to warnings
                formatted_warnings.append(err_obj)
            elif err.get('error_type') == 'unverified':
                formatted_errors.append({**err_obj, "error_type": 'unverified'})
            else:
                formatted_errors.append(err_obj)

        # Run hallucination check via the shared unified logic
        # NOTE: Hallucination check is deferred to the async layer
        # (_check_single_reference_with_limit) so that the initial result
        # can be streamed to the UI immediately without waiting for the
        # slow Anthropic web-search API call.
        hallucination_assessment = None

        matched_database = (verified_data or {}).get('_matched_database') or (
            'Web page' if verified_via_webpage else None
        )

        # Enrichment payload: cited-by counts, reference count, OA flag,
        # OpenAlex / PubMed / MAG IDs, Field of Study, per-author ORCID.
        # Pulled from whatever verified_data shape the matched checker
        # returned; missing fields are left out rather than zeroed so
        # the UI can distinguish "no signal" from "zero". Wrapped in
        # try/except because this is a display nicety — failing here
        # must not break the verification result.
        enrichment_payload: Dict[str, Any] = {}
        try:
            from refchecker.utils.enrichment import build_enrichment
            enrichment_payload = build_enrichment(verified_data) or {}
        except Exception as e:
            logger.debug("enrichment build failed: %s", e)

        result = {
            "index": index,
            "title": reference.get('title') or reference.get('cited_url') or reference.get('url') or 'Unknown Title',
            "authors": reference.get('authors', []),
            "year": reference.get('year') or None,
            "venue": reference.get('venue'),
            "cited_url": reference.get('cited_url') or reference.get('url'),
            "status": status,
            "errors": formatted_errors,
            "warnings": formatted_warnings,
            "suggestions": formatted_suggestions,
            "authoritative_urls": authoritative_urls,
            "matched_database": matched_database,
            "enrichment": enrichment_payload,
            "corrected_reference": None,
            "hallucination_assessment": hallucination_assessment,
            "_raw_errors": errors,  # Stashed for deferred hallucination check
        }
        logger.info(f"_format_verification_result output: suggestions={formatted_suggestions}, status={status}")
        return result

    def _format_error_result(
        self,
        reference: Dict[str, Any],
        index: int,
        error: Exception
    ) -> Dict[str, Any]:
        """Format an error result when verification fails."""
        return {
            "index": index,
            "title": reference.get('title') or reference.get('cited_url') or reference.get('url') or 'Unknown',
            "authors": reference.get('authors', []),
            "year": reference.get('year'),
            "venue": reference.get('venue'),
            "cited_url": reference.get('cited_url') or reference.get('url'),
            "status": "error",
            "errors": [{
                "error_type": "check_failed",
                "error_details": str(error)
            }],
            "warnings": [],
            "suggestions": [],
            "authoritative_urls": [],
            "corrected_reference": None
        }

    async def emit_progress(self, event_type: str, data: Dict[str, Any]):
        """Emit progress event to callback.

        Side effect for ``reference_result`` events: persist the verified
        reference into the global identity cache (DOI / arXiv / normalized
        title key) BEFORE emitting. Every code path that surfaces a
        verified ref to the UI flows through here, so this single hook
        guarantees the cache stays in sync no matter which downstream
        rewriter (hallucination resolver / context attacher / etc.) was
        the last to touch the result.
        """
        if event_type == "reference_result" and isinstance(data, dict):
            try:
                from .database import db as _db
                upsert_key = await _db.upsert_verified_reference(data)
                if upsert_key is not None:
                    if not hasattr(self, "_global_cache_writes"):
                        self._global_cache_writes = 0
                    self._global_cache_writes += 1
            except Exception as _e:
                logger.warning("Global cache upsert failed in emit_progress: %s", _e)
        logger.info(f"Emitting progress: {event_type} - {str(data)[:200]}")
        if self.progress_callback:
            await self.progress_callback(event_type, data)

    async def _check_cancelled(self):
        if self.cancel_event and self.cancel_event.is_set():
            raise asyncio.CancelledError()

    def _bibliography_cache_identity(self) -> str:
        return llm_cache_identity_from_extractor(SimpleNamespace(llm_provider=self.llm) if self.llm else None)

    async def check_paper(self, paper_source: str, source_type: str) -> Dict[str, Any]:
        """
        Check a paper and emit progress updates

        Args:
            paper_source: URL, ArXiv ID, or file path
            source_type: 'url' or 'file'

        Returns:
            Dictionary with paper title, references, and results
        """
        # Reset the per-check LLM usage accumulator so the $ badge starts
        # at zero for this run, then bind this check_id to the current
        # thread so provider-level usage records attribute correctly.
        try:
            from refchecker.llm import usage_tracker
            if self.check_id is not None:
                usage_tracker.reset(self.check_id)
                usage_tracker.set_current_check(self.check_id)
        except Exception:
            pass

        try:
            # Reset per-check counters so the UI token meter reflects what
            # THIS check spent, not lifetime totals across the session.
            try:
                from . import usage_tracker as _usage
                _usage.reset_usage()
            except Exception as _e:
                logger.debug("Could not reset usage tracker: %s", _e)
            self._global_cache_writes = 0

            # Step 1: Get paper content
            await self.emit_progress("started", {
                "message": "Starting reference check...",
                "source": paper_source
            })

            paper_title = "Unknown Paper"
            paper_text = ""
            title_updated = False
            pdf_path_for_fallback = None

            async def update_title_if_needed(title: str):
                nonlocal title_updated
                if not title_updated and title and title != "Unknown Paper":
                    title_updated = True
                    if self.title_update_callback and self.check_id:
                        await self.title_update_callback(self.check_id, title)
                    # Also emit via WebSocket so frontend can update
                    await self.emit_progress("title_updated", {"paper_title": title})

            await self._check_cancelled()
            # Track if we got references from ArXiv source files and the extraction method.
            # extraction_method describes the operational path and may become 'cache'.
            # bibliography_source_kind preserves the original provenance for UI display.
            arxiv_source_references = None
            extraction_method = None  # 'bbl', 'bib', 'pdf', 'llm', 'cache', or None
            bibliography_source_kind = None

            def set_extraction_method(method: Optional[str]) -> None:
                nonlocal extraction_method, bibliography_source_kind
                extraction_method = method
                if not method:
                    return
                normalized = method.lower()
                if normalized == 'cache':
                    return
                bibliography_source_kind = 'pdf' if normalized in {'file', 'pdf'} else normalized

            async def maybe_extract_grobid_references(pdf_path: str, failure_message: str):
                refs, method = await asyncio.to_thread(
                    extract_pdf_references_with_grobid_fallback,
                    pdf_path=pdf_path,
                    llm_available=bool(self.llm),
                    failure_message=failure_message,
                )
                if refs:
                    logger.info(f"Extracted {len(refs)} references via GROBID")
                return refs, method

            bibliography_cache_identity = self._bibliography_cache_identity()

            async def maybe_update_title_from_direct_pdf(pdf_url: str) -> None:
                nonlocal paper_title
                if paper_title != "Unknown Paper":
                    return

                if 'openreview.net' in pdf_url.lower():
                    try:
                        from refchecker.checkers.openreview_checker import OpenReviewReferenceChecker
                        or_checker = OpenReviewReferenceChecker(request_delay=0.0)
                        or_checker.cache_dir = self.cache_dir
                        or_id = or_checker.extract_paper_id(pdf_url)
                        if or_id:
                            or_meta = await asyncio.to_thread(or_checker.get_paper_metadata, or_id)
                            if or_meta and or_meta.get('title'):
                                paper_title = or_meta['title']
                                await update_title_if_needed(paper_title)
                                logger.info(f"Got title from OpenReview metadata: {paper_title}")
                                return
                    except Exception as e:
                        logger.debug(f"Could not get OpenReview metadata: {e}")

                cached_pdf_path = get_cached_artifact_path(self.cache_dir, pdf_url, 'paper.pdf')
                if cached_pdf_path and os.path.exists(cached_pdf_path) and os.path.getsize(cached_pdf_path) > 0:
                    try:
                        pdf_processor = PDFProcessor()
                        extracted_title = await asyncio.to_thread(pdf_processor.extract_title_from_pdf, cached_pdf_path)
                        if extracted_title:
                            paper_title = extracted_title
                            await update_title_if_needed(paper_title)
                            logger.info(f"Extracted title from cached PDF: {paper_title}")
                    except Exception as e:
                        logger.warning(f"Could not extract title from cached PDF: {e}")
            
            if source_type == "url":
                # Check if this is an OpenReview URL — convert to PDF download
                if 'openreview.net/forum' in paper_source.lower():
                    from urllib.parse import urlparse, parse_qs
                    parsed = urlparse(paper_source)
                    params = parse_qs(parsed.query)
                    or_paper_id = params.get('id', [None])[0]
                    if or_paper_id:
                        paper_source = f"https://openreview.net/pdf?id={or_paper_id}"
                    else:
                        raise ValueError(f"Could not extract paper ID from OpenReview URL: {paper_source}")

                # Check if this is a direct PDF URL (not arXiv)
                is_direct_pdf_url = (
                    (paper_source.lower().endswith('.pdf') or 'openreview.net/pdf' in paper_source.lower()) and 
                    'arxiv.org' not in paper_source.lower()
                )
                
                if is_direct_pdf_url:
                    # Check bibliography cache first — avoids PDF download
                    # entirely when references are already cached.
                    cached_bib = cached_bibliography(self.cache_dir, paper_source, bibliography_cache_identity)
                    if cached_bib is not None:
                        logger.info(f"Cache hit: loaded {len(cached_bib)} references for {paper_source}")
                        bibliography_source_kind = 'pdf'
                        set_extraction_method('cache')
                        await maybe_update_title_from_direct_pdf(paper_source)

                    # Handle direct PDF URLs (e.g., Microsoft Research PDFs)
                    else:
                        await self.emit_progress("extracting", {
                            "message": "Downloading PDF from URL..."
                        })

                        # Download PDF from URL
                        pdf_path = get_cached_artifact_path(self.cache_dir, paper_source, 'paper.pdf', create_dir=True)

                        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                            await asyncio.to_thread(download_pdf, paper_source, pdf_path)

                        # For OpenReview PDFs, try to get metadata from the API
                        await maybe_update_title_from_direct_pdf(paper_source)

                        pdf_path_for_fallback = pdf_path
                        set_extraction_method('pdf')
                        pdf_processor = PDFProcessor()
                        paper_text = await asyncio.to_thread(_extract_pdf_text_cli_style, pdf_path, self.llm)

                        # Try to extract the paper title from the PDF content
                        # (only if we don't already have a title from the API)
                        if paper_title == "Unknown Paper":
                            try:
                                extracted_title = await asyncio.to_thread(pdf_processor.extract_title_from_pdf, pdf_path)
                                if extracted_title:
                                    paper_title = extracted_title
                                    await update_title_if_needed(paper_title)
                                    logger.info(f"Extracted title from PDF URL: {paper_title}")
                                else:
                                    # Fallback to URL filename
                                    from urllib.parse import urlparse, unquote
                                    url_path = urlparse(paper_source).path
                                    pdf_filename = unquote(url_path.split('/')[-1])
                                    if pdf_filename and pdf_filename.lower() not in ('pdf', 'download', 'content'):
                                        paper_title = pdf_filename.replace('.pdf', '').replace('_', ' ').replace('-', ' ')
                                        await update_title_if_needed(paper_title)
                            except Exception as e:
                                logger.warning(f"Could not extract title from PDF: {e}")
                else:
                    # Handle ArXiv URLs/IDs
                    arxiv_id = extract_arxiv_id_from_url(paper_source)
                    if not arxiv_id:
                        arxiv_id = paper_source  # Assume it's already an ID

                    await self.emit_progress("extracting", {
                        "message": f"Fetching ArXiv paper {arxiv_id}..."
                    })

                    # Download from ArXiv - run in thread to avoid blocking event loop.
                    # Newer arxiv lib (>=2.0) removed Search.results() — use the
                    # Client.results(search) idiom instead.
                    def fetch_arxiv():
                        return get_arxiv_paper_by_id(arxiv_id)
                    
                    paper = await asyncio.to_thread(fetch_arxiv)
                    if not paper:
                        raise ValueError(f"ArXiv paper not found: {arxiv_id}")
                    paper_title = paper.title
                    await update_title_if_needed(paper_title)

                    # Try to get BibTeX content from ArXiv source files first
                    # This uses the .bbl file preference logic for papers with large .bib files
                    await self.emit_progress("extracting", {
                        "message": f"Checking ArXiv source for bibliography files..."
                    })
                    
                    bibtex_content = await asyncio.to_thread(get_bibtex_content, paper)
                    
                    if bibtex_content:
                        logger.info(f"Found BibTeX/BBL content from ArXiv source for {arxiv_id}")
                        # Save the bibliography content for later viewing
                        if self.bibliography_source_callback and self.check_id:
                            await self.bibliography_source_callback(self.check_id, bibtex_content, arxiv_id)
                        # Extract references from the BibTeX content (returns tuple)
                        result = await self._extract_references_from_bibtex(bibtex_content)
                        arxiv_source_references, extracted_method = result
                        set_extraction_method(extracted_method)
                        if arxiv_source_references:
                            logger.info(f"Extracted {len(arxiv_source_references)} references from ArXiv source files (method: {extraction_method})")
                        else:
                            logger.warning("Could not extract references from ArXiv source, falling back to PDF")
                    
                    # Fall back to PDF extraction if no references from source files
                    if not arxiv_source_references:
                        # Download PDF - run in thread (use cross-platform temp directory).
                        # arxiv lib's Result.download_pdf has been deprecated/removed in
                        # newer versions ("Use result.pdf_url directly"). Pull the URL
                        # off the Result and run it through our own downloader instead.
                        pdf_path = get_cached_artifact_path(self.cache_dir, paper_source, 'paper.pdf', create_dir=True)
                        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                            await asyncio.to_thread(download_arxiv_paper_pdf, paper, pdf_path, arxiv_id)

                        pdf_path_for_fallback = pdf_path
                        set_extraction_method('pdf')
                        # Extract text using the same CLI path for parity.
                        paper_text = await asyncio.to_thread(_extract_pdf_text_cli_style, pdf_path, self.llm)
                    else:
                        paper_text = ""  # Not needed since we have references

            elif source_type == "file":
                set_extraction_method('file')
                await self.emit_progress("extracting", {
                    "message": "Extracting text from file..."
                })

                # Handle uploaded file - run PDF processing in thread
                if paper_source.lower().endswith('.pdf'):
                    pdf_processor = PDFProcessor()
                    pdf_path_for_fallback = paper_source
                    paper_text = await asyncio.to_thread(_extract_pdf_text_cli_style, paper_source, self.llm)
                    
                    # Try to extract the paper title from the PDF
                    try:
                        extracted_title = await asyncio.to_thread(pdf_processor.extract_title_from_pdf, paper_source)
                        if extracted_title:
                            paper_title = extracted_title
                            await update_title_if_needed(paper_title)
                            logger.info(f"Extracted title from PDF: {paper_title}")
                    except Exception as e:
                        logger.warning(f"Could not extract title from PDF: {e}")
                elif paper_source.lower().endswith(('.tex', '.txt', '.bib')):
                    def read_file():
                        with open(paper_source, 'r', encoding='utf-8') as f:
                            return f.read()
                    paper_text = await asyncio.to_thread(read_file)
                    
                    # For .bib files, extract references directly using BibTeX parser
                    if paper_source.lower().endswith('.bib'):
                        logger.info("Processing uploaded .bib file as BibTeX")
                        refs_result = await self._extract_references_from_bibtex(paper_text)
                        if refs_result and refs_result[0]:
                            arxiv_source_references = refs_result[0]
                            set_extraction_method('bib')
                            logger.info(f"Extracted {len(arxiv_source_references)} references from .bib file")
                    # For .txt files, treat entire content as bibliography
                    # (matching CLI behavior for text files with no section header)
                    elif paper_source.lower().endswith('.txt'):
                        logger.info("Processing uploaded .txt file as plain text references")
                        cli_checker = _make_cli_checker(self.llm)
                        refs = await asyncio.to_thread(cli_checker.parse_references, paper_text)
                        if refs:
                            arxiv_source_references = [_normalize_reference_fields(r) for r in refs]
                            set_extraction_method('text')
                            logger.info(f"Extracted {len(arxiv_source_references)} references from .txt file")
                else:
                    raise ValueError(f"Unsupported file type: {paper_source}")
            elif source_type == "text":
                await self.emit_progress("extracting", {
                    "message": "Preparing pasted text..."
                })
                # paper_source is now a file path - read the actual text content
                if os.path.exists(paper_source):
                    def read_text_file():
                        with open(paper_source, 'r', encoding='utf-8') as f:
                            return f.read()
                    paper_text = await asyncio.to_thread(read_text_file)
                else:
                    # Fallback: paper_source is the actual text (legacy behavior)
                    paper_text = paper_source
                paper_title = "Pasted Text"
                set_extraction_method('text')
                
                # Check if the pasted text is LaTeX thebibliography format (.bbl)
                if '\\begin{thebibliography}' in paper_text and '\\bibitem' in paper_text:
                    logger.info("Detected LaTeX thebibliography format in pasted text")
                    # Use the BibTeX extraction method instead
                    refs_result = await self._extract_references_from_bibtex(paper_text)
                    if refs_result and refs_result[0]:
                        arxiv_source_references = refs_result[0]
                        set_extraction_method('bbl')  # Mark as bbl extraction
                        logger.info(f"Extracted {len(arxiv_source_references)} references from pasted .bbl content")
                # Check if the pasted text is BibTeX format (@article, @misc, @inproceedings, etc.)
                elif re.search(r'@\s*(article|book|inproceedings|incollection|misc|techreport|phdthesis|mastersthesis|conference|inbook|proceedings)\s*\{', paper_text, re.IGNORECASE):
                    logger.info("Detected BibTeX format in pasted text")
                    refs_result = await self._extract_references_from_bibtex(paper_text)
                    if refs_result and refs_result[0]:
                        arxiv_source_references = refs_result[0]
                        set_extraction_method('bib')  # Mark as bib extraction
                        logger.info(f"Extracted {len(arxiv_source_references)} references from pasted BibTeX content")
                # Fallback: Try BibTeX parsing anyway for partial/malformed content
                # This handles cases like incomplete paste, or BibTeX-like content without standard entry types
                elif any(marker in paper_text for marker in ['title={', 'author={', 'year={', 'eprint={', '@']):
                    logger.info("Detected possible BibTeX-like content, attempting parse")
                    refs_result = await self._extract_references_from_bibtex(paper_text)
                    if refs_result and refs_result[0]:
                        arxiv_source_references = refs_result[0]
                        set_extraction_method('bib')
                        logger.info(f"Extracted {len(arxiv_source_references)} references from partial BibTeX content")
                    else:
                        logger.warning("BibTeX-like content detected but parsing failed, will try LLM extraction")
                # For plain text without any structured format markers, treat
                # the entire text as bibliography content (matching CLI behavior
                # for .txt files).  This avoids find_bibliography_section failing
                # on text that has no "References" section header.
                if not arxiv_source_references:
                    logger.info("Plain text input — treating entire text as bibliography")
                    cli_checker = _make_cli_checker(self.llm)
                    refs = await asyncio.to_thread(cli_checker.parse_references, paper_text)
                    if refs:
                        arxiv_source_references = [_normalize_reference_fields(r) for r in refs]
                        set_extraction_method('text')
                        logger.info(f"Extracted {len(arxiv_source_references)} references from plain text")
                # Don't update title for pasted text - keep the placeholder
            else:
                raise ValueError(f"Unsupported source type: {source_type}")

            # Step 2: Extract references (check disk cache first)
            references = cached_bibliography(self.cache_dir, paper_source, bibliography_cache_identity)
            if references is not None:
                set_extraction_method('cache')
                logger.info(f"Cache hit: loaded {len(references)} references for {paper_source}")
            else:
                await self.emit_progress("extracting", {
                    "message": "Extracting references from paper...",
                    "paper_title": paper_title,
                    "extraction_method": extraction_method
                })

                # Use ArXiv source references if available, otherwise extract from text
                if arxiv_source_references:
                    references = arxiv_source_references
                    logger.info(f"Using {len(references)} references from ArXiv source files (method: {extraction_method})")
                else:
                    references = await self._extract_references(paper_text)
                    if not references and pdf_path_for_fallback:
                        fallback_refs, fallback_method = await maybe_extract_grobid_references(
                            pdf_path_for_fallback,
                            "No LLM or GROBID available for PDF reference extraction. Please configure an API key in Settings, or ensure Docker is installed so GROBID can auto-start.",
                        )
                        if fallback_refs:
                            references = fallback_refs
                            set_extraction_method(fallback_method)
                    # If we used PDF/file extraction and LLM was configured, mark as LLM-assisted
                    if self.llm and extraction_method in ('pdf', 'file', 'text'):
                        set_extraction_method('llm')

                # Save to disk cache
                if references:
                    cache_bibliography(self.cache_dir, paper_source, references, bibliography_cache_identity)
                # Attach citation contexts (sentence around [N] / author-year
                # patterns in the source text) so the UI can show
                # 'context: "as demonstrated in [12]..."' on each ref card.
                _attach_citation_contexts(references, paper_text)
                _ctx_attached = sum(1 for r in (references or []) if r.get("citation_context"))
                logger.info(
                    "Citation contexts: %d/%d refs got an inline sentence (paper_text=%d chars)",
                    _ctx_attached, len(references or []), len(paper_text or ""),
                )

            if not references:
                await self.emit_progress("completed", {
                    "total_refs": 0,
                    "errors_count": 0,
                    "warnings_count": 0,
                    "suggestions_count": 0,
                    "unverified_count": 0,
                    "hallucination_count": 0,
                    "verified_count": 0,
                    "extraction_method": extraction_method,
                    "message": "No references could be extracted from this paper.",
                    "check_id": self.check_id,
                })
                return {
                    "paper_title": paper_title,
                    "paper_source": paper_source,
                    "extraction_method": extraction_method,
                    "bibliography_source_kind": bibliography_source_kind,
                    "references": [],
                    "summary": {
                        "total_refs": 0,
                        "errors_count": 0,
                        "warnings_count": 0,
                        "suggestions_count": 0,
                        "unverified_count": 0,
                        "verified_count": 0
                    }
                }

            # Step 3: Check references in parallel (like CLI)
            total_refs = len(references)
            await self.emit_progress("references_extracted", {
                "total_refs": total_refs,
                "extraction_method": extraction_method,
                "references": [
                    {
                        "index": idx,
                        "title": ref.get("title") or ref.get("cited_url") or ref.get("url") or "Unknown Title",
                        "authors": ref.get("authors", []),
                        "year": ref.get("year"),
                        "venue": ref.get("venue"),
                        "cited_url": ref.get("cited_url") or ref.get("url")
                    }
                    for idx, ref in enumerate(references, 1)
                ]
            })
            limiter = create_limiter()
            await self.emit_progress("progress", {
                "current": 0,
                "total": total_refs,
                "message": f"Checking {total_refs} references..."
            })

            # Process references in parallel.
            # `extraction_method` is the bibliography-extraction stage we
            # took (bbl / bib / pdf / file / text / llm / cache / None).
            # _check_references_parallel uses it for the Summary chip's
            # Regex-vs-LLM split. Pass it explicitly — earlier the method
            # read it as a closure-free free name and crashed with
            # NameError on every text-paste run.
            results, errors_count, warnings_count, suggestions_count, unverified_count, verified_count, refs_with_errors, refs_with_warnings_only, refs_with_suggestions_only, refs_verified, hallucination_count = \
                await self._check_references_parallel(references, total_refs, extraction_method=extraction_method)

            # Per-stage extraction counts for the Summary chip
            # (Regex / LLM / Hallucination LLM). The deterministic
            # parsers ('bbl', 'bib') count as regex; the LLM extractor
            # counts as llm; cache and pdf-only paths report zeros for
            # both since we don't know the split. Hallucination LLM
            # invocations are counted from refs whose assessment came
            # back via the LLM path (assessment carries 'source').
            _regex_methods = {"bbl", "bib", "regex"}
            if extraction_method in _regex_methods:
                regex_count = total_refs
                llm_count = 0
            elif extraction_method == "llm":
                regex_count = 0
                llm_count = total_refs
            else:
                regex_count = 0
                llm_count = 0
            hallucination_llm_count = sum(
                1 for r in results
                if isinstance(r, dict)
                and isinstance(r.get("hallucination_assessment"), dict)
                and r["hallucination_assessment"].get("source")
            )

            # Step 4: Return final results
            final_result = {
                "paper_title": paper_title,
                "paper_source": paper_source,
                "extraction_method": extraction_method,
                "bibliography_source_kind": bibliography_source_kind,
                "references": results,
                "summary": {
                    "total_refs": total_refs,
                    "processed_refs": total_refs,
                    "errors_count": errors_count,
                    "warnings_count": warnings_count,
                    "suggestions_count": suggestions_count,
                    "unverified_count": unverified_count,
                    "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                    "verified_count": verified_count,
                    "refs_with_errors": refs_with_errors,
                    "refs_with_warnings_only": refs_with_warnings_only,
                    "refs_with_suggestions_only": refs_with_suggestions_only,
                    "refs_verified": refs_verified,
                    "progress_percent": 100.0,
                    "extraction_method": extraction_method
                }
            }

            await self.emit_progress("completed", {**final_result["summary"], "check_id": self.check_id, "paper_title": paper_title})

            return final_result

        except Exception as e:
            logger.error(f"Error checking paper: {e}", exc_info=True)
            await self.emit_progress("error", {
                "message": str(e),
                "details": type(e).__name__
            })
            raise

    def _parse_llm_reference(self, ref_string: str) -> Optional[Dict[str, Any]]:
        """Parse a single LLM reference string into a structured dict.
        
        LLM returns strings in format: Authors#Title#Venue#Year#URL
        Authors are separated by asterisks (*).
        Also handles plain text references that don't follow the format.
        """
        import re
        
        if not ref_string:
            return None
        
        # If it's already a dict, return as-is
        if isinstance(ref_string, dict):
            return ref_string
            
        if not isinstance(ref_string, str):
            ref_string = str(ref_string)
        
        ref_string = ref_string.strip()
        if not ref_string:
            return None
        
        # Skip LLM explanatory responses (not actual references)
        skip_patterns = [
            r'^I cannot extract',
            r'^No valid.*references',
            r'^This text (does not|doesn\'t) contain',
            r'^The (provided|given) text',
            r'^I was unable to',
            r'^There are no.*references',
            r'^I don\'t see any',
            r'^Unable to extract',
            r'^No references found',
            r'^This appears to be',
            r'^This section',
            r'^The text (appears|seems) to',
        ]
        for pattern in skip_patterns:
            if re.match(pattern, ref_string, re.IGNORECASE):
                logger.debug(f"Skipping LLM explanatory text: {ref_string[:60]}...")
                return None
        
        # Check if this looks like a citation key (e.g., "JLZ+22", "ZNIS23")
        # Citation keys are typically short alphanumeric strings, possibly with + or -
        citation_key_pattern = r'^[A-Za-z]+[+\-]?\d{2,4}$'
        is_citation_key = bool(re.match(citation_key_pattern, ref_string.replace('#', '').replace(' ', '')))
        
        # Check if it follows the # format
        parts = ref_string.split('#')
        
        if len(parts) >= 2:
            # Parse parts: Authors#Title#Venue#Year#URL
            authors_str = parts[0].strip() if len(parts) > 0 else ''
            title = parts[1].strip() if len(parts) > 1 else ''
            venue = parts[2].strip() if len(parts) > 2 else ''
            year_str = parts[3].strip() if len(parts) > 3 else ''
            url = parts[4].strip() if len(parts) > 4 else ''
            
            # Check if this is a malformed reference (citation key with empty fields)
            # If most fields are empty and authors looks like a citation key, skip it
            non_empty_fields = sum(1 for f in [title, venue, year_str, url] if f)
            authors_is_citation_key = bool(re.match(citation_key_pattern, authors_str.replace(' ', '')))
            
            if non_empty_fields == 0 and authors_is_citation_key:
                # This is just a citation key, not a real reference - skip it
                logger.debug(f"Skipping malformed reference (citation key only): {ref_string}")
                return None
            
            # Also skip if title is just a citation key or year
            if title and re.match(citation_key_pattern, title.replace(' ', '')):
                logger.debug(f"Skipping reference with citation key as title: {ref_string}")
                return None
            
            # Skip if title looks like it's just a year
            if title and re.match(r'^\d{4}$', title.strip()):
                logger.debug(f"Skipping reference with year as title: {ref_string}")
                return None
            
            # Parse authors (separated by *)
            authors = []
            if authors_str:
                # Don't treat citation keys as authors
                if not authors_is_citation_key:
                    authors = [a.strip() for a in authors_str.split('*') if a.strip()]
            
            # Parse year as integer
            year_int = None
            if year_str:
                year_match = re.search(r'\b(19|20)\d{2}\b', year_str)
                if year_match:
                    year_int = int(year_match.group())
            
            # Ensure we have a valid title - don't use the raw string if it's mostly separators
            if not title:
                # If there's no title and no meaningful content, skip this reference
                if non_empty_fields == 0:
                    return None
                # Otherwise try to clean up the raw string for display
                clean_raw = ref_string.replace('#', ' ').strip()
                clean_raw = re.sub(r'\s+', ' ', clean_raw)
                title = clean_raw[:100] if len(clean_raw) > 100 else clean_raw
            
            return {
                'title': title,
                'authors': authors,
                'year': year_int,
                'venue': venue or None,
                'url': url or None,
                'raw_text': ref_string
            }
        else:
            # Not in expected format, parse as plain text reference
            
            # Skip very short strings (likely citation keys or garbage)
            if len(ref_string) < 15:
                logger.debug(f"Skipping short string: {ref_string}")
                return None
            
            # Try to extract structured data from plain text
            title = ref_string
            authors = []
            year_int = None
            venue = None
            url = None
            
            # Try to extract year from plain text
            year_match = re.search(r'\b(19|20)\d{2}\b', ref_string)
            if year_match:
                year_int = int(year_match.group())
            
            # Try to extract URL from plain text
            url_match = re.search(r'https?://[^\s]+', ref_string)
            if url_match:
                url = url_match.group()
            
            # Clean up title - remove year and URL if found
            if year_match:
                title = title.replace(year_match.group(), '').strip()
            if url_match:
                title = title.replace(url_match.group(), '').strip()
            
            # Remove common delimiters from start/end
            title = title.strip('.,;:-() ')
            
            return {
                'title': title if title else ref_string[:100],
                'authors': authors,
                'year': year_int,
                'venue': venue,
                'url': url,
                'raw_text': ref_string
            }

    async def _extract_references(self, paper_text: str) -> List[Dict[str, Any]]:
        """Extract references using the same pipeline/order as the CLI."""
        try:
            cli_checker = _make_cli_checker(self.llm)

            # Step 1: find bibliography section (CLI logic) - run in thread
            await self.emit_progress("extracting", {
                "message": "Finding bibliography section..."
            })
            bib_section = await asyncio.to_thread(cli_checker.find_bibliography_section, paper_text)
            if not bib_section:
                logger.warning("Could not find bibliography section in paper")
                await self.emit_progress("extracting", {
                    "message": "Could not find bibliography section in paper."
                })
                return []

            logger.info(f"Found bibliography section ({len(bib_section)} chars)")
            await self.emit_progress("extracting", {
                "message": "Found bibliography section. Parsing references..."
            })

            # Create a thread-safe callback to emit chunk progress back to the event loop
            loop = asyncio.get_event_loop()

            def _chunk_progress(completed: int, total: int):
                if total > 1:
                    asyncio.run_coroutine_threadsafe(
                        self.emit_progress("extracting", {
                            "message": f"Extracting references via LLM (chunk {completed}/{total})..."
                        }),
                        loop,
                    )

            # Step 2: parse references (CLI logic, including LLM and post-processing) - run in thread.
            # Tag any LLM calls under the 'extract' flow so the $ badge attributes correctly.
            from refchecker.llm import usage_tracker as _usage_tracker
            _check_id_for_thread = self.check_id

            def _parse_with_scope():
                if _check_id_for_thread is not None:
                    _usage_tracker.set_current_check(str(_check_id_for_thread))
                with _usage_tracker.FlowScope("extract"):
                    return cli_checker.parse_references(bib_section, progress_callback=_chunk_progress)

            refs = await asyncio.to_thread(_parse_with_scope)
            if cli_checker.fatal_error:
                logger.error("Reference parsing failed (CLI fatal_error)")
                return []
            if refs:
                logger.info(f"Extracted {len(refs)} references via CLI parser")
                # DEBUG: Log problematic references where year looks like title
                for idx, ref in enumerate(refs):
                    title = ref.get('title', '')
                    if title and (title.isdigit() or len(title) < 10):
                        debug_log(f"PARSE ISSUE ref {idx+1}: title='{title}' authors={ref.get('authors', [])[:2]} year={ref.get('year')}")
                # Normalize field names (journal -> venue)
                refs = [_normalize_reference_fields(ref) for ref in refs]
                return refs

            logger.warning("No references could be extracted")
            return []
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error extracting references: {error_msg}")
            # Surface quota/rate-limit errors clearly so the user knows why extraction failed
            error_lower = error_msg.lower()
            if "429" in error_msg or "quota" in error_lower or "rate" in error_lower or "exceeded" in error_lower:
                user_msg = "LLM API quota exceeded — your API key is valid but the account has insufficient quota. Check your billing details."
            elif "401" in error_msg or "unauthorized" in error_lower:
                user_msg = "LLM API key is invalid or expired. Please update your API key in Settings."
            else:
                user_msg = f"Failed to extract references: {error_msg}"
            # Emit error to frontend
            await self.emit_progress("error", {
                "message": user_msg,
                "details": type(e).__name__
            })
            raise

    async def _extract_references_from_bibtex(self, bibtex_content: str) -> tuple:
        """Extract references from BibTeX/BBL content (from ArXiv source files).

        Honors the user-set extraction_mode:
          - 'cascade' (default): try the deterministic LaTeX/BibTeX parser
            first; only fall back to the LLM when the parser fails OR the
            parsed output looks low-quality (validate_parsed_references).
          - 'llm-only': skip the deterministic parser entirely and send
            the raw content straight to the LLM. Costs more tokens but
            handles weirdly-formatted .bib files the parser chokes on.

        Returns (references list, extraction_method) where extraction_method
        is one of 'bbl', 'bib', 'llm', or None.
        """
        try:
            cli_checker = _make_cli_checker(self.llm)
            extraction_mode = (os.environ.get('REFCHECKER_EXTRACTION_MODE') or 'cascade').lower()
            if extraction_mode == 'llm-only' and self.llm:
                logger.info("extraction_mode=llm-only: bypassing deterministic bibtex/bbl parser")
                try:
                    llm_refs = await asyncio.to_thread(cli_checker.llm_extractor.extract_references, bibtex_content)
                    if llm_refs:
                        processed = await asyncio.to_thread(cli_checker._process_llm_extracted_references, llm_refs)
                        return processed, 'llm'
                except Exception as e:
                    logger.warning(f"llm-only extraction failed, falling back to cascade: {e}")
            
            # Check if this is LaTeX thebibliography format (e.g., from .bbl files)
            if '\\begin{thebibliography}' in bibtex_content and '\\bibitem' in bibtex_content:
                logger.info("Detected LaTeX thebibliography format from .bbl file")
                # Use extract_latex_references for .bbl format
                refs = await asyncio.to_thread(extract_latex_references, bibtex_content, None)
                
                if refs:
                    # Validate the parsed references
                    from refchecker.utils.text_utils import validate_parsed_references
                    validation = await asyncio.to_thread(validate_parsed_references, refs)
                    
                    if not validation['is_valid'] and self.llm:
                        logger.debug(f"LaTeX parsing validation failed (quality: {validation['quality_score']:.2f}), trying LLM fallback")
                        # Try LLM fallback
                        try:
                            llm_refs = await asyncio.to_thread(cli_checker.llm_extractor.extract_references, bibtex_content)
                            if llm_refs:
                                # DEBUG: Log raw LLM output
                                debug_log(f"LLM raw output ({len(llm_refs)} refs):")
                                for i, r in enumerate(llm_refs[:5]):
                                    debug_log(f"  [{i+1}] {str(r)[:150]}")
                                processed_refs = await asyncio.to_thread(cli_checker._process_llm_extracted_references, llm_refs)
                                # DEBUG: Log processed refs with potential issues
                                for idx, ref in enumerate(processed_refs):
                                    title = ref.get('title', '')
                                    if title and (title.isdigit() or len(title) < 10):
                                        debug_log(f"PARSE ISSUE after LLM ref {idx+1}: title='{title}' authors={ref.get('authors', [])[:2]}")
                                llm_validation = await asyncio.to_thread(validate_parsed_references, processed_refs)
                                if llm_validation['quality_score'] > validation['quality_score']:
                                    logger.info(f"LLM extraction improved quality ({llm_validation['quality_score']:.2f})")
                                    # Normalize field names (journal -> venue)
                                    processed_refs = [_normalize_reference_fields(ref) for ref in processed_refs]
                                    return (processed_refs, 'llm')
                        except Exception as e:
                            error_msg = str(e)
                            error_lower = error_msg.lower()
                            logger.warning(f"LLM fallback failed: {e}")
                            # Surface quota/auth errors so the user knows
                            if "429" in error_msg or "quota" in error_lower or "rate" in error_lower or "exceeded" in error_lower:
                                await self.emit_progress("extracting", {
                                    "message": "LLM extraction skipped — API quota exceeded. Using standard parser instead."
                                })
                            elif "401" in error_msg or "unauthorized" in error_lower:
                                await self.emit_progress("extracting", {
                                    "message": "LLM extraction skipped — invalid API key. Using standard parser instead."
                                })
                    
                    logger.info(f"Extracted {len(refs)} references from .bbl content")
                    # Normalize field names (journal -> venue)
                    refs = [_normalize_reference_fields(ref) for ref in refs]
                    return (refs, 'bbl')
            else:
                # Parse as BibTeX format
                logger.info("Detected BibTeX format from .bib file")
                refs = await asyncio.to_thread(cli_checker.parse_references, bibtex_content)
                if cli_checker.fatal_error:
                    logger.error("BibTeX parsing failed")
                    return ([], None)
                if refs:
                    logger.info(f"Extracted {len(refs)} references from .bib content")
                    # Normalize field names (journal -> venue)
                    refs = [_normalize_reference_fields(ref) for ref in refs]
                    return (refs, 'bib')
            
            return ([], None)
        except Exception as e:
            logger.error(f"Error extracting references from BibTeX: {e}")
            return ([], None)

    async def _check_reference(self, reference: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Check a single reference and format result"""
        try:
            # Global cache short-circuit: if this reference has been verified
            # before (DOI / arXiv / title+year match), reuse the stored result
            # rather than re-hitting external APIs.
            try:
                from .database import db as _db
                cached = await _db.lookup_verified_reference(reference)
                if cached and isinstance(cached.get("result"), dict) and cached["result"]:
                    cached_result = dict(cached["result"])
                    cached_result["index"] = index
                    cached_result["from_cache"] = True
                    return cached_result
            except Exception as _e:
                logger.debug("Global cache lookup skipped: %s", _e)

            # Use the hybrid checker with timeout protection
            import asyncio
            loop = asyncio.get_event_loop()

            # Run verification in a thread with timeout
            try:
                verified_data, errors, url = await asyncio.wait_for(
                    loop.run_in_executor(None, self._verify_reference, reference),
                    timeout=90.0  # 90 second timeout per reference
                )
            except asyncio.TimeoutError:
                logger.warning(f"Reference {index} verification timed out")
                verified_data = None
                errors = [{"error_type": "unverified", "error_details": "Verification timed out"}]
                url = None

            return self._format_verification_result(reference, index, verified_data, errors, url)

        except Exception as e:
            logger.error(f"Error checking reference {index}: {e}")
            return self._format_error_result(reference, index, e)

    def _verify_reference(self, reference: Dict[str, Any]):
        """Verify a reference, checking GitHub repos first (matches CLI path).

        Returns (verified_data, errors, url) — same contract as
        ``EnhancedHybridReferenceChecker.verify_reference``.
        """
        # Tag every LLM call made anywhere inside this verification
        # (hybrid checker title-match LLM, etc.) under the "verify" flow
        # so the $ badge's per-flow breakdown actually populates the
        # verify bucket instead of "other". asyncio.to_thread reused this
        # worker thread for many refs, so the check id + flow must be
        # rebound on every call.
        from refchecker.llm import usage_tracker as _usage_tracker
        if self.check_id is not None:
            _usage_tracker.set_current_check(str(self.check_id))
        with _usage_tracker.FlowScope("verify"):
            return self._verify_reference_body(reference)

    def _verify_reference_body(self, reference: Dict[str, Any]):
        # GitHub references bypass the hybrid checker (same as CLI's
        # verify_reference_standard → verify_github_reference).
        github_url = None
        if reference.get('url') and 'github.com' in reference['url']:
            github_url = reference['url']
        elif reference.get('venue') and 'github.com' in (reference.get('venue') or ''):
            for part in reference['venue'].split():
                if 'github.com' in part:
                    github_url = part
                    break

        if github_url:
            from refchecker.checkers.github_checker import GitHubChecker
            github_checker = GitHubChecker()
            verified_data, errors, paper_url = github_checker.verify_reference(reference)
            if verified_data:
                # Re-format to preserve warning_type / info_type keys
                formatted = []
                for error in (errors or []):
                    fe = {}
                    for key in ('error_type', 'error_details', 'warning_type',
                                'warning_details', 'info_type', 'info_details',
                                'ref_year_correct', 'ref_url_correct'):
                        if key in error:
                            fe[key] = error[key]
                    formatted.append(fe)
                return verified_data, formatted or None, paper_url
            else:
                formatted = []
                for error in errors:
                    fe = {}
                    if 'error_type' in error:
                        fe['error_type'] = error['error_type']
                        fe['error_details'] = error['error_details']
                    formatted.append(fe)
                return None, formatted or [{"error_type": "unverified", "error_details": "GitHub repository could not be verified"}], paper_url

        return self.checker.verify_reference(reference)

    def _standard_refcheck_for_hallucination(self, reference: Dict[str, Any]):
        """Run the normal WebUI verifier for LLM-found metadata.

        The shared hallucination policy expects the CLI tuple order
        ``(errors, url, verified_data)``; WebUI's internal verifier returns
        ``(verified_data, errors, url)``.
        """
        verified_data, errors, url = self._verify_reference(dict(reference))
        return errors, url, verified_data

    def _check_reference_sync(self, reference: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Synchronous version of reference checking for thread pool"""
        try:
            # Run verification with timeout (handled by caller)
            verified_data, errors, url = self._verify_reference(reference)
            return self._format_verification_result(reference, index, verified_data, errors, url)
        except UnicodeEncodeError as e:
            # Handle Windows encoding issues with special characters (e.g., Greek letters in titles)
            logger.warning(f"Unicode encoding error checking reference {index}: {e}")
            return self._format_error_result(reference, index, 
                Exception(f"Unicode encoding error - title may contain special characters"))
        except Exception as e:
            logger.error(f"Error checking reference {index}: {e}")
            return self._format_error_result(reference, index, e)

    def _pre_screen_hallucination(
        self, result: Dict[str, Any], reference: Dict[str, Any]
    ) -> tuple:
        """Run instant deterministic hallucination checks (no network/LLM).

        Delegates to the shared ``pre_screen_hallucination`` in
        hallucination_policy so all three code paths (CLI, Batch, WebUI)
        use identical filtering and deterministic verdict logic.

        Returns
        -------
        ('resolved', updated_result)
            Deterministic verdict — apply immediately, no async task needed.
        ('skip', None)
            No hallucination check needed — leave result as-is.
        ('needs_async', None)
            Needs LLM and/or ArXiv version check — create async task.
        """
        auth_urls = result.get('authoritative_urls') or []
        verified_url = auth_urls[0]['url'] if auth_urls else ''
        error_entry = build_hallucination_error_entry(
            result.get('_raw_errors', []), reference, verified_url=verified_url,
        )
        if error_entry is None:
            return ('skip', None)

        outcome, assessment = pre_screen_hallucination(error_entry)
        if outcome == 'resolved':
            if should_defer_likely_to_llm(assessment, verified_url):
                # Defer to async LLM check instead of applying immediately
                return ('needs_async', None)
            updated = apply_hallucination_verdict(
                result,
                assessment,
                reference=reference,
                standard_refchecker=self._standard_refcheck_for_hallucination,
                llm_client=self.hallucination_verifier,
                web_searcher=getattr(self, 'web_searcher', None),
            )
            return ('resolved', updated)
        elif outcome == 'skip':
            return ('skip', None)
        else:
            return ('needs_async', None)

    @staticmethod
    def _compute_ref_stats(result: Dict[str, Any], is_complete: bool = True) -> Dict[str, int]:
        """Compute the stat contribution of a single reference result.

        Returns a dict of stat counters (all non-negative) representing
        what this ref contributes to the aggregate totals.
        """
        # Use the shared count_raw_errors for the error count so all
        # modes (CLI, Bulk, WebUI) apply the same filtering rules.
        # The sanitized errors list only contains error_type entries
        # (warnings/suggestions are in separate lists), so we only
        # take the error_count from count_raw_errors.
        llm_match_overrides = _llm_found_metadata_matches_citation(result)
        num_errors, _, _ = count_raw_errors(result.get('errors', []))
        num_warnings = len(result.get('warnings', []))
        if llm_match_overrides:
            num_errors = 0
            num_warnings = 0
        num_suggestions = len(result.get('suggestions', []))

        d: Dict[str, int] = {
            'errors_count': num_errors,
            'warnings_count': num_warnings,
            'suggestions_count': num_suggestions,
            'hallucination_count': 0,
            'hallucination_llm_count': 0,
            'unverified_count': 0,
            'verified_count': 0,
            'refs_verified': 0,
            'refs_with_errors': 0,
            'refs_with_warnings_only': 0,
            'refs_with_suggestions_only': 0,
        }
        # An assessment with a `source` field means the LLM (or web
        # search) was invoked. pre-screen-only assessments have no
        # source — they're deterministic.
        ha = result.get('hallucination_assessment')
        if isinstance(ha, dict) and ha.get('source'):
            d['hallucination_llm_count'] = 1

        status = result.get('status', '')
        has_unverified_error = any(
            e.get('error_type') == 'unverified' for e in result.get('errors', [])
        )
        has_pending_hallucination_check = (
            result.get('hallucination_check_pending')
            and not result.get('hallucination_assessment')
        )
        is_transient_unverified = (
            status == 'unverified'
            and not result.get('hallucination_assessment')
            and not is_complete
        )
        can_count_unverified = not has_pending_hallucination_check and not is_transient_unverified

        if status == 'hallucination' and not llm_match_overrides:
            d['hallucination_count'] = 1
        if (
            not llm_match_overrides
            and can_count_unverified
            and (status in ('unverified', 'hallucination') or has_unverified_error)
        ):
            d['unverified_count'] = 1
        if (
            llm_match_overrides
            or status in ('verified', 'suggestion')
            or (status not in ('unverified', 'hallucination') and num_errors == 0 and num_warnings == 0)
        ):
            d['verified_count'] = 1
            d['refs_verified'] = 1

        if num_errors > 0:
            d['refs_with_errors'] = 1
        elif num_warnings > 0:
            d['refs_with_warnings_only'] = 1
        elif num_suggestions > 0:
            d['refs_with_suggestions_only'] = 1

        return d

    @staticmethod
    def _compute_deferred_ref_deltas(result: Dict[str, Any], old_result: Dict[str, Any] = None, is_complete: bool = True) -> Dict[str, int]:
        """Compute stat counter deltas for a ref whose status changed.

        When ``old_result`` is provided, returns the *difference* between
        the new and old stat contributions (new − old) so callers can
        adjust running totals incrementally.  When ``old_result`` is None,
        returns the absolute contribution of *result* (legacy behaviour).
        """
        new_d = ProgressRefChecker._compute_ref_stats(result, is_complete=is_complete)
        if old_result is None:
            return new_d
        old_d = ProgressRefChecker._compute_ref_stats(old_result, is_complete=is_complete)
        return {k: new_d[k] - old_d.get(k, 0) for k in new_d}

    def _run_hallucination_check_sync(self, result: Dict[str, Any], reference: Dict[str, Any]) -> Dict[str, Any]:
        """Run hallucination check synchronously and return updated result.

        Called from a thread pool *after* the initial result has already
        been streamed to the UI, so the user sees the reference immediately.
        Deterministic checks (author overlap, name order) are already handled
        by _pre_screen_hallucination. ArXiv version-update normalization lives
        in the shared EnhancedHybridReferenceChecker postprocess path.
        """
        auth_urls = result.get('authoritative_urls') or []
        verified_url = auth_urls[0]['url'] if auth_urls else ''
        error_entry = build_hallucination_error_entry(
            result.get('_raw_errors', []), reference, verified_url=verified_url,
        )
        if error_entry is None:
            return result

        # Tag any LLM calls made by the hallucination verifier under the
        # "hallucination" flow so the $ badge breakdown attributes
        # correctly. asyncio.to_thread runs us on a fresh worker, so the
        # check id + flow must be (re)bound here.
        from refchecker.llm import usage_tracker as _usage_tracker
        if self.check_id is not None:
            _usage_tracker.set_current_check(str(self.check_id))
        with _usage_tracker.FlowScope("hallucination"):
            assessment = run_hallucination_check(
                error_entry,
                llm_client=self.hallucination_verifier,
                web_searcher=getattr(self, 'web_searcher', None),
            )
        if not assessment:
            return result

        # Match single-paper CLI behaviour: when a ref has the
        # "url references paper" pattern and the LLM says UNLIKELY,
        # the CLI returns early without recording the ref as an error.
        # Here we drop the assessment so the ref stays verified with
        # no hallucination verdict — identical to the CLI path.
        raw_errors = result.get('_raw_errors') or []
        has_url_refs_paper = any(
            'url references paper' in (e.get('error_details') or '').lower()
            for e in raw_errors
        )
        if has_url_refs_paper and assessment.get('verdict') == 'UNLIKELY':
            return result

        with _usage_tracker.FlowScope("hallucination"):
            result = apply_hallucination_verdict(
                result,
                assessment,
                reference=reference,
                standard_refchecker=self._standard_refcheck_for_hallucination,
                llm_client=self.hallucination_verifier,
                web_searcher=getattr(self, 'web_searcher', None),
            )
        return result

    async def _check_single_reference_with_limit(
        self,
        reference: Dict[str, Any],
        idx: int,
        total_refs: int,
        loop: asyncio.AbstractEventLoop,
        limiter=None
    ) -> Dict[str, Any]:
        """
        Check a single reference with per-session concurrency limiting.
        
        First checks the verification cache for a previous result.
        Acquires a slot from the session limiter before starting the check,
        and releases it when done. Stores result in cache on success.
        """
        if limiter is None:
            limiter = create_limiter()
        
        # Wait for a slot in the session queue
        async with limiter:
            # Check for cancellation before starting
            await self._check_cancelled()
            
            # Emit that this reference is now being checked
            await self.emit_progress("checking_reference", {
                "index": idx + 1,
                "title": reference.get("title") or reference.get("cited_url") or reference.get("url") or "Unknown Title",
                "total": total_refs
            })

            # Global cache short-circuit before kicking off network checks
            try:
                from .database import db as _db
                cached = await _db.lookup_verified_reference(reference)
                if cached and isinstance(cached.get("result"), dict) and cached["result"]:
                    cached_result = dict(cached["result"])
                    cached_result["index"] = idx + 1
                    cached_result["from_cache"] = True
                    return cached_result
            except Exception as _e:
                logger.debug("Global cache lookup skipped: %s", _e)

            try:
                # Run the sync check in a thread
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,  # Use default executor
                        self._check_reference_sync,
                        reference,
                        idx + 1
                    ),
                    timeout=90.0  # 90 second timeout per reference
                )
            except asyncio.TimeoutError:
                result = {
                    "index": idx + 1,
                    "title": reference.get('title') or reference.get('cited_url') or reference.get('url') or 'Unknown',
                    "authors": reference.get('authors', []),
                    "year": reference.get('year'),
                    "venue": reference.get('venue'),
                    "cited_url": reference.get('cited_url') or reference.get('url'),
                    "status": "unverified",
                    "errors": [{
                        "error_type": "unverified",
                        "error_details": "Verification timed out"
                    }],
                    "warnings": [],
                    "suggestions": [],
                    "authoritative_urls": [],
                    "corrected_reference": None
                }
            except asyncio.CancelledError:
                raise  # Re-raise cancellation
            except Exception as e:
                logger.error(f"Error checking reference {idx + 1}: {e}")
                result = {
                    "index": idx + 1,
                    "title": reference.get('title', 'Unknown'),
                    "authors": reference.get('authors', []),
                    "year": reference.get('year'),
                    "venue": reference.get('venue'),
                    "cited_url": reference.get('url'),
                    "status": "error",
                    "errors": [{
                        "error_type": "check_failed",
                        "error_details": str(e)
                    }],
                    "warnings": [],
                    "authoritative_urls": [],
                    "corrected_reference": None
                }
        
        return result

    async def _check_references_parallel(
        self,
        references: List[Dict[str, Any]],
        total_refs: int,
        extraction_method: Optional[str] = None,
    ) -> tuple:
        """
        Check references in parallel using per-session concurrency limiting.
        
        Each paper check session gets its own concurrency limiter, so
        concurrent sessions don't block each other.
        
        Emits progress updates as results come in.
        Only marks references as 'checking' when they actually start.
        Returns results list and counts.
        """
        results = {}
        errors_count = 0
        warnings_count = 0
        suggestions_count = 0
        unverified_count = 0
        hallucination_count = 0
        hallucination_llm_count = 0  # Refs where the hallucination LLM was actually invoked.
        verified_count = 0
        refs_with_errors = 0
        refs_with_warnings_only = 0
        refs_with_suggestions_only = 0
        refs_verified = 0
        processed_count = 0
        checked_count = 0  # Tracks refs that finished verification (including deferred ones)

        # Per-stage extraction counts surfaced in the Summary chip
        # (Regex / LLM / Hallucination LLM). The deterministic parsers
        # (.bbl, .bib) all count as "regex"; the LLM extractor counts
        # as "llm"; cache hits keep the stage from the original run.
        _regex_methods = {"bbl", "bib", "regex"}
        if extraction_method in _regex_methods:
            regex_count = total_refs
            llm_count = 0
        elif extraction_method == "llm":
            regex_count = 0
            llm_count = total_refs
        else:
            # 'pdf', 'file', 'text', 'cache', None — we genuinely
            # don't know the per-stage split for these, so attribute
            # to whichever flag the underlying CLI checker raised.
            regex_count = 0
            llm_count = 0
        
        loop = asyncio.get_event_loop()
        
        start_time = time.time()
        debug_log(f"[TIMING] Starting parallel check of {total_refs} references")
        
        # Create tasks for all references - they will be rate-limited by the per-session semaphore
        session_limiter = create_limiter()
        tasks = []
        for idx, ref in enumerate(references):
            task = asyncio.create_task(
                self._check_single_reference_with_limit(ref, idx, total_refs, loop, limiter=session_limiter),
                name=f"ref-check-{idx}"
            )
            tasks.append((idx, task))
        
        task_creation_time = time.time()
        debug_log(f"[TIMING] Tasks created in {task_creation_time - start_time:.3f}s")
        
        # Process results as they complete
        pending_tasks = {task for _, task in tasks}
        task_to_idx = {task: idx for idx, task in tasks}
        
        iteration = 0
        while pending_tasks:
            iteration += 1
            iter_start = time.time()
            
            # Check for cancellation
            try:
                await self._check_cancelled()
            except asyncio.CancelledError:
                # Cancel all pending tasks
                for task in pending_tasks:
                    task.cancel()
                raise
            
            # Wait for some tasks to complete - no timeout needed, just wait for first completed
            done, pending_tasks = await asyncio.wait(
                pending_tasks,
                return_when=asyncio.FIRST_COMPLETED
            )
            
            wait_time = time.time() - iter_start
            debug_log(f"[TIMING] Iteration {iteration}: wait took {wait_time:.3f}s, {len(done)} done, {len(pending_tasks)} pending")
            
            for task in done:
                idx = task_to_idx[task]
                
                try:
                    result = task.result()
                except asyncio.CancelledError:
                    # Task was cancelled, create cancelled result
                    result = {
                        "index": idx + 1,
                        "title": references[idx].get('title', 'Unknown'),
                        "authors": references[idx].get('authors', []),
                        "year": references[idx].get('year'),
                        "venue": references[idx].get('venue'),
                        "cited_url": references[idx].get('url'),
                        "status": "cancelled",
                        "errors": [],
                        "warnings": [],
                        "authoritative_urls": [],
                        "corrected_reference": None
                    }
                except Exception as e:
                    logger.error(f"Unexpected error for reference {idx + 1}: {e}")
                    result = {
                        "index": idx + 1,
                        "title": references[idx].get('title', 'Unknown'),
                        "authors": references[idx].get('authors', []),
                        "year": references[idx].get('year'),
                        "venue": references[idx].get('venue'),
                        "cited_url": references[idx].get('url'),
                        "status": "error",
                        "errors": [{
                            "error_type": "unexpected_error",
                            "error_details": str(e)
                        }],
                        "warnings": [],
                        "authoritative_urls": [],
                        "corrected_reference": None
                    }
                
                # Store result
                results[idx] = result

                # Sanitize year: never send 0 to the frontend
                if not result.get('year'):
                    result['year'] = None

                # Count individual issues (not just references)
                # If hallucination verifier is enabled, refs with real errors
                # (not just suggestions/info) are deferred — they'll get a
                # deterministic or LLM check after all refs are processed.
                # Stats are always counted immediately so the UI updates in
                # real-time; the hallucination phase will adjust them later
                # (subtract old contribution, add new) when status changes.
                is_pending_hallucination_check = (
                    self.hallucination_verifier
                    and has_real_raw_errors(result.get('_raw_errors'))
                )

                # Always count stats for all refs so the UI updates progressively.
                # Use the shared _compute_ref_stats to avoid duplicated logic.
                checked_count += 1
                processed_count += 1
                d = self._compute_ref_stats(result, is_complete=False)
                errors_count += d['errors_count']
                warnings_count += d['warnings_count']
                suggestions_count += d['suggestions_count']
                hallucination_count += d['hallucination_count']
                hallucination_llm_count += d.get('hallucination_llm_count', 0)
                unverified_count += d['unverified_count']
                verified_count += d['verified_count']
                refs_verified += d['refs_verified']
                refs_with_errors += d['refs_with_errors']
                refs_with_warnings_only += d['refs_with_warnings_only']
                refs_with_suggestions_only += d['refs_with_suggestions_only']

                # Emit result immediately. emit_progress() now upserts
                # the verified ref into the global identity cache as a
                # side effect, so we no longer need to do it here.
                emit_start = time.time()
                await self.emit_progress("reference_result", result)
                await self.emit_progress("progress", {
                    "current": checked_count,
                    "total": total_refs
                })
                await self.emit_progress("summary_update", {
                    "total_refs": total_refs,
                    "processed_refs": checked_count,
                    "errors_count": errors_count,
                    "warnings_count": warnings_count,
                    "suggestions_count": suggestions_count,
                    "unverified_count": unverified_count,
                    "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                    "verified_count": verified_count,
                    "refs_with_errors": refs_with_errors,
                    "refs_with_warnings_only": refs_with_warnings_only,
                    "refs_with_suggestions_only": refs_with_suggestions_only,
                    "refs_verified": refs_verified,
                    "progress_percent": round((checked_count / total_refs) * 100, 1)
                })
                emit_time = time.time() - emit_start
                if emit_time > 0.1:
                    debug_log(f"[TIMING] Emit for ref {idx + 1} took {emit_time:.3f}s")
                
                # Yield to event loop to allow WebSocket messages to flush
                # This prevents stalls when many cache hits complete rapidly
                await asyncio.sleep(0)
        
        total_time = time.time() - start_time
        debug_log(f"[TIMING] Total parallel check completed in {total_time:.3f}s for {total_refs} refs")
        
        # Small delay to ensure all WebSocket messages are sent before returning
        # This prevents the 'completed' event from arriving before final progress updates
        await asyncio.sleep(0.1)

        # ── Deferred hallucination checks ──
        # Run hallucination checks AFTER all refs are verified and streamed
        # to the UI, so users see results immediately.
        if self.hallucination_verifier:
            # Collect refs that were deferred (real errors, not suggestion-only)
            ha_candidates = [
                (idx, results[idx], references[idx])
                for idx in range(total_refs)
                if results.get(idx) and has_real_raw_errors(results[idx].get('_raw_errors'))
            ]
            if ha_candidates:
                debug_log(f"[TIMING] Running deferred hallucination checks for {len(ha_candidates)} refs")
                await self.emit_progress("phase", {"message": "Running hallucination detection..."})

                # ── Phase 1: deterministic pre-screen (instant, no network/LLM) ──
                needs_async = []
                for c_idx, c_result, c_ref in ha_candidates:
                    outcome, resolved = self._pre_screen_hallucination(c_result, c_ref)
                    if outcome == 'resolved':
                        resolved['hallucination_check_pending'] = False
                        # Adjust stats: subtract old contribution, add new
                        d = self._compute_deferred_ref_deltas(resolved, c_result, is_complete=False)
                        errors_count += d['errors_count']
                        warnings_count += d['warnings_count']
                        suggestions_count += d['suggestions_count']
                        hallucination_count += d['hallucination_count']
                        hallucination_llm_count += d.get('hallucination_llm_count', 0)
                        unverified_count += d['unverified_count']
                        verified_count += d['verified_count']
                        refs_verified += d['refs_verified']
                        refs_with_errors += d['refs_with_errors']
                        refs_with_warnings_only += d['refs_with_warnings_only']
                        refs_with_suggestions_only += d['refs_with_suggestions_only']
                        results[c_idx] = resolved
                        await self.emit_progress("reference_result", resolved)
                    elif outcome == 'skip':
                        # No hallucination check needed — no stat change
                        c_result['hallucination_check_pending'] = False
                        await self.emit_progress("reference_result", c_result)
                    else:
                        # needs_async — will go to LLM/ArXiv pool
                        needs_async.append((c_idx, c_result, c_ref))

                det_count = len(ha_candidates) - len(needs_async)
                if det_count:
                    debug_log(f"[TIMING] {det_count} refs resolved deterministically, {len(needs_async)} need LLM/ArXiv")
                    # Emit summary after deterministic phase so stats update in UI
                    await self.emit_progress("summary_update", {
                        "total_refs": total_refs,
                        "processed_refs": checked_count,
                        "errors_count": errors_count,
                        "warnings_count": warnings_count,
                        "suggestions_count": suggestions_count,
                        "unverified_count": unverified_count,
                        "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                        "verified_count": verified_count,
                        "refs_with_errors": refs_with_errors,
                        "refs_with_warnings_only": refs_with_warnings_only,
                        "refs_with_suggestions_only": refs_with_suggestions_only,
                        "refs_verified": refs_verified,
                        "progress_percent": round((checked_count / total_refs) * 100, 1),
                    })

                # ── Phase 2: async tasks for refs needing LLM/ArXiv (smaller pool) ──
                if needs_async:
                    # Mark only async refs as pending
                    for c_idx, c_result, _c_ref in needs_async:
                        c_result['hallucination_check_pending'] = True
                        await self.emit_progress("reference_result", c_result)

                    ha_tasks = []
                    for c_idx, c_result, c_ref in needs_async:
                        ha_task = asyncio.create_task(
                            asyncio.wait_for(
                                loop.run_in_executor(
                                    None, self._run_hallucination_check_sync, c_result, c_ref
                                ),
                                timeout=150.0,
                            ),
                            name=f"hallucination-{c_idx}",
                        )
                        ha_tasks.append((c_idx, ha_task))

                    ha_pending = {t for _, t in ha_tasks}
                    ha_task_to_idx = {t: i for i, t in ha_tasks}

                    while ha_pending:
                        try:
                            await self._check_cancelled()
                        except asyncio.CancelledError:
                            for t in ha_pending:
                                t.cancel()
                            raise

                        ha_done, ha_pending = await asyncio.wait(
                            ha_pending, return_when=asyncio.FIRST_COMPLETED
                        )

                        for ha_task in ha_done:
                            ha_idx = ha_task_to_idx[ha_task]
                            old_result = results.get(ha_idx, {})

                            try:
                                updated = ha_task.result()
                            except Exception as ha_err:
                                logger.debug(f"Hallucination check failed for ref {ha_idx + 1}: {ha_err}")
                                # Clear pending flag — no stat change since result unchanged
                                if results.get(ha_idx):
                                    results[ha_idx]['hallucination_check_pending'] = False
                                    await self.emit_progress("reference_result", results[ha_idx])
                                    await self.emit_progress("summary_update", {
                                        "total_refs": total_refs,
                                        "processed_refs": checked_count,
                                        "errors_count": errors_count,
                                        "warnings_count": warnings_count,
                                        "suggestions_count": suggestions_count,
                                        "unverified_count": unverified_count,
                                        "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                                        "verified_count": verified_count,
                                        "refs_with_errors": refs_with_errors,
                                        "refs_with_warnings_only": refs_with_warnings_only,
                                        "refs_with_suggestions_only": refs_with_suggestions_only,
                                        "refs_verified": refs_verified,
                                        "progress_percent": round((checked_count / total_refs) * 100, 1),
                                    })
                                continue

                            updated['hallucination_check_pending'] = False

                            # Adjust stats: subtract old contribution, add new
                            d = self._compute_deferred_ref_deltas(updated, old_result, is_complete=False)
                            errors_count += d['errors_count']
                            warnings_count += d['warnings_count']
                            suggestions_count += d['suggestions_count']
                            hallucination_count += d['hallucination_count']
                            hallucination_llm_count += d.get('hallucination_llm_count', 0)
                            unverified_count += d['unverified_count']
                            verified_count += d['verified_count']
                            refs_verified += d['refs_verified']
                            refs_with_errors += d['refs_with_errors']
                            refs_with_warnings_only += d['refs_with_warnings_only']
                            refs_with_suggestions_only += d['refs_with_suggestions_only']

                            results[ha_idx] = updated
                            # Emit ref update and summary so the UI updates progressively.
                            await self.emit_progress("reference_result", updated)
                            await self.emit_progress("summary_update", {
                                "total_refs": total_refs,
                                "processed_refs": checked_count,
                                "errors_count": errors_count,
                                "warnings_count": warnings_count,
                                "suggestions_count": suggestions_count,
                                "unverified_count": unverified_count,
                                "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                                "verified_count": verified_count,
                                "refs_with_errors": refs_with_errors,
                                "refs_with_warnings_only": refs_with_warnings_only,
                                "refs_with_suggestions_only": refs_with_suggestions_only,
                                "refs_verified": refs_verified,
                                "progress_percent": round((checked_count / total_refs) * 100, 1),
                            })
                            await asyncio.sleep(0)

                # Emit a final summary_update after all hallucination checks complete
                await self.emit_progress("summary_update", {
                    "total_refs": total_refs,
                    "processed_refs": checked_count,
                    "errors_count": errors_count,
                    "warnings_count": warnings_count,
                    "suggestions_count": suggestions_count,
                    "unverified_count": unverified_count,
                    "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                    "verified_count": verified_count,
                    "refs_with_errors": refs_with_errors,
                    "refs_with_warnings_only": refs_with_warnings_only,
                    "refs_with_suggestions_only": refs_with_suggestions_only,
                    "refs_verified": refs_verified,
                    "progress_percent": round((checked_count / total_refs) * 100, 1),
                })

                debug_log(f"[TIMING] Hallucination checks completed in {time.time() - total_time - start_time:.3f}s")

        # Clean up _raw_errors from final results (internal field)
        for idx in range(total_refs):
            if results.get(idx):
                results[idx].pop('_raw_errors', None)
        
        # Convert dict to ordered list
        results_list = [results.get(i) for i in range(total_refs)]

        # Final aggregates should be derived from the settled reference objects,
        # not only from incremental deltas emitted during streaming.
        errors_count = warnings_count = suggestions_count = 0
        unverified_count = verified_count = hallucination_count = 0
        hallucination_llm_count = 0
        refs_with_errors = refs_with_warnings_only = refs_with_suggestions_only = refs_verified = 0
        for result in results_list:
            if not result:
                continue
            d = self._compute_ref_stats(result)
            errors_count += d['errors_count']
            warnings_count += d['warnings_count']
            suggestions_count += d['suggestions_count']
            hallucination_count += d['hallucination_count']
            hallucination_llm_count += d.get('hallucination_llm_count', 0)
            unverified_count += d['unverified_count']
            verified_count += d['verified_count']
            refs_verified += d['refs_verified']
            refs_with_errors += d['refs_with_errors']
            refs_with_warnings_only += d['refs_with_warnings_only']
            refs_with_suggestions_only += d['refs_with_suggestions_only']
        
        return results_list, errors_count, warnings_count, suggestions_count, unverified_count, verified_count, refs_with_errors, refs_with_warnings_only, refs_with_suggestions_only, refs_verified, hallucination_count
