"""
Wrapper around refchecker library with progress callbacks for real-time updates
"""
import sys
import os
import re
import asyncio
import logging
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path

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
)
from refchecker.utils.arxiv_utils import get_bibtex_content
from refchecker.utils.cache_utils import cache_bibliography, cached_bibliography, get_cached_artifact_path
from refchecker.utils.grobid import extract_pdf_references_with_grobid_fallback
import arxiv

logger = logging.getLogger(__name__)


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
                    logger.debug('Hallucination verifier initialized for web UI (provider=%s, available=%s, cache=%s)', h_provider, verifier.available, bool(cache_dir))
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
                # Map 'timeout' to 'unverified' since timeouts mean we couldn't verify
                # Preserve original e_type for info items so suggestion_type keeps the value
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
        if url:
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
            "matched_database": (verified_data or {}).get('_matched_database'),
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
        """Emit progress event to callback"""
        logger.info(f"Emitting progress: {event_type} - {str(data)[:200]}")
        if self.progress_callback:
            await self.progress_callback(event_type, data)

    async def _check_cancelled(self):
        if self.cancel_event and self.cancel_event.is_set():
            raise asyncio.CancelledError()

    async def check_paper(self, paper_source: str, source_type: str) -> Dict[str, Any]:
        """
        Check a paper and emit progress updates

        Args:
            paper_source: URL, ArXiv ID, or file path
            source_type: 'url' or 'file'

        Returns:
            Dictionary with paper title, references, and results
        """
        try:
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
                    cached_bib = cached_bibliography(self.cache_dir, paper_source)
                    if cached_bib is not None:
                        logger.info(f"Cache hit: loaded {len(cached_bib)} references for {paper_source}")
                        bibliography_source_kind = 'pdf'
                        set_extraction_method('cache')
                        # Try to get paper title from OpenReview metadata cache
                        if 'openreview.net/pdf' in paper_source.lower():
                            try:
                                from refchecker.checkers.openreview_checker import OpenReviewReferenceChecker
                                or_checker = OpenReviewReferenceChecker(request_delay=0.0)
                                or_checker.cache_dir = self.cache_dir
                                or_id = or_checker.extract_paper_id(paper_source)
                                if or_id:
                                    or_meta = or_checker.get_paper_metadata(or_id)
                                    if or_meta and or_meta.get('title'):
                                        paper_title = or_meta['title']
                                        await update_title_if_needed(paper_title)
                            except Exception:
                                pass

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
                        if 'openreview.net' in paper_source.lower():
                            try:
                                from refchecker.checkers.openreview_checker import OpenReviewReferenceChecker
                                or_checker = OpenReviewReferenceChecker(request_delay=0.0)
                                or_id = or_checker.extract_paper_id(paper_source)
                                if or_id:
                                    or_meta = or_checker.get_paper_metadata(or_id)
                                    if or_meta and or_meta.get('title'):
                                        paper_title = or_meta['title']
                                        await update_title_if_needed(paper_title)
                                        logger.info(f"Got title from OpenReview API: {paper_title}")
                            except Exception as e:
                                logger.debug(f"Could not get OpenReview metadata: {e}")

                        pdf_path_for_fallback = pdf_path
                        set_extraction_method('pdf')
                        pdf_processor = PDFProcessor()
                        paper_text = await asyncio.to_thread(pdf_processor.extract_text_from_pdf, pdf_path)

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

                    # Download from ArXiv - run in thread to avoid blocking event loop
                    def fetch_arxiv():
                        search = arxiv.Search(id_list=[arxiv_id])
                        return next(search.results())
                    
                    paper = await asyncio.to_thread(fetch_arxiv)
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
                        # Download PDF - run in thread (use cross-platform temp directory)
                        pdf_path = get_cached_artifact_path(self.cache_dir, paper_source, 'paper.pdf', create_dir=True)
                        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                            await asyncio.to_thread(paper.download_pdf, filename=pdf_path)

                        pdf_path_for_fallback = pdf_path
                        set_extraction_method('pdf')
                        # Extract text from PDF - run in thread
                        pdf_processor = PDFProcessor()
                        paper_text = await asyncio.to_thread(pdf_processor.extract_text_from_pdf, pdf_path)
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
                    paper_text = await asyncio.to_thread(pdf_processor.extract_text_from_pdf, paper_source)
                    
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
                # Don't update title for pasted text - keep the placeholder
            else:
                raise ValueError(f"Unsupported source type: {source_type}")

            # Step 2: Extract references (check disk cache first)
            references = cached_bibliography(self.cache_dir, paper_source)
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
                    cache_bibliography(self.cache_dir, paper_source, references)

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

            # Process references in parallel
            results, errors_count, warnings_count, suggestions_count, unverified_count, verified_count, refs_with_errors, refs_with_warnings_only, refs_verified, hallucination_count = \
                await self._check_references_parallel(references, total_refs)

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
                    "verified_count": verified_count,
                    "refs_with_errors": refs_with_errors,
                    "refs_with_warnings_only": refs_with_warnings_only,
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

            # Step 2: parse references (CLI logic, including LLM and post-processing) - run in thread
            refs = await asyncio.to_thread(cli_checker.parse_references, bib_section, progress_callback=_chunk_progress)
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
        
        This mirrors the CLI's extract_bibliography logic for handling BibTeX content.
        
        Returns:
            Tuple of (references list, extraction_method string)
            extraction_method is one of: 'bbl', 'bib', 'llm', or None if extraction failed
        """
        try:
            cli_checker = _make_cli_checker(self.llm)
            
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

    @staticmethod
    def _author_last_names(authors) -> set:
        """Extract lowercased last-name tokens from an author list.

        Handles both string lists (['A. Smith', 'B. Jones']) and
        dict lists ([{'name': 'A. Smith'}]).
        """
        names = set()
        for a in (authors or []):
            name = a.get('name', a) if isinstance(a, dict) else a
            parts = str(name).strip().split()
            if parts:
                # Use the last token as the surname
                names.add(parts[-1].lower().rstrip('.'))
        return names

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
            updated = apply_hallucination_verdict(result, assessment)
            return ('resolved', updated)
        elif outcome == 'skip':
            return ('skip', None)
        else:
            return ('needs_async', None)

    @staticmethod
    def _compute_ref_stats(result: Dict[str, Any]) -> Dict[str, int]:
        """Compute the stat contribution of a single reference result.

        Returns a dict of stat counters (all non-negative) representing
        what this ref contributes to the aggregate totals.
        """
        # Use the shared count_raw_errors for the error count so all
        # modes (CLI, Bulk, WebUI) apply the same filtering rules.
        # The sanitized errors list only contains error_type entries
        # (warnings/suggestions are in separate lists), so we only
        # take the error_count from count_raw_errors.
        num_errors, _, _ = count_raw_errors(result.get('errors', []))
        num_warnings = len(result.get('warnings', []))
        num_suggestions = len(result.get('suggestions', []))

        d: Dict[str, int] = {
            'errors_count': num_errors,
            'warnings_count': num_warnings,
            'suggestions_count': num_suggestions,
            'hallucination_count': 0,
            'unverified_count': 0,
            'verified_count': 0,
            'refs_verified': 0,
            'refs_with_errors': 0,
            'refs_with_warnings_only': 0,
        }

        status = result.get('status', '')
        has_unverified_error = any(
            e.get('error_type') == 'unverified' for e in result.get('errors', [])
        )

        if status == 'hallucination':
            d['hallucination_count'] = 1
        if status in ('unverified', 'hallucination') or has_unverified_error:
            d['unverified_count'] = 1
        if status in ('verified', 'suggestion'):
            d['verified_count'] = 1
            d['refs_verified'] = 1

        if status == 'error' or num_errors > 0:
            d['refs_with_errors'] = 1
        elif status == 'warning' or num_warnings > 0:
            d['refs_with_warnings_only'] = 1

        return d

    @staticmethod
    def _compute_deferred_ref_deltas(result: Dict[str, Any], old_result: Dict[str, Any] = None) -> Dict[str, int]:
        """Compute stat counter deltas for a ref whose status changed.

        When ``old_result`` is provided, returns the *difference* between
        the new and old stat contributions (new − old) so callers can
        adjust running totals incrementally.  When ``old_result`` is None,
        returns the absolute contribution of *result* (legacy behaviour).
        """
        new_d = ProgressRefChecker._compute_ref_stats(result)
        if old_result is None:
            return new_d
        old_d = ProgressRefChecker._compute_ref_stats(old_result)
        return {k: new_d[k] - old_d.get(k, 0) for k in new_d}

    def _try_arxiv_version_match(self, result: Dict[str, Any], reference: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Check if errors are explained by an older ArXiv version.

        When a paper was verified but has metadata mismatches (year, venue,
        authors), check other ArXiv versions.  If a historical version matches
        the citation well — including author name overlap — convert errors to
        warnings and return the updated result.

        Returns updated result if a better version was found, None otherwise.
        """
        import re
        import time as _time

        auth_urls = result.get('authoritative_urls') or []
        arxiv_url = next((u['url'] for u in auth_urls if u.get('type') == 'arxiv'), None)
        if not arxiv_url:
            return None

        match = re.search(r'arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5}|[a-z-]+/[0-9]{7})', arxiv_url)
        if not match:
            return None
        arxiv_id = match.group(1)

        # Skip if there's a title mismatch — the ArXiv ID points to a different paper
        raw_errors = result.get('_raw_errors', [])
        if any((e.get('error_type') or '').lower() == 'title' for e in raw_errors):
            return None

        try:
            from refchecker.checkers.arxiv_citation import ArXivCitationChecker
            checker = ArXivCitationChecker()

            latest_version = checker._get_latest_version_number(arxiv_id)
            if not latest_version or latest_version <= 1:
                return None

            cited_title = reference.get('title', '')
            cited_authors = reference.get('authors', [])
            cited_last_names = self._author_last_names(cited_authors)
            if not cited_last_names:
                return None

            best_score = 0.0
            best_version = None
            best_overlap = 0.0
            start = _time.time()

            for version_num in range(latest_version - 1, 0, -1):
                if _time.time() - start > 15:
                    logger.debug(f"ArXiv version check timed out for {arxiv_id}")
                    break
                version_data = checker._fetch_version_metadata_from_html(arxiv_id, version_num)
                if not version_data:
                    continue

                score = checker._calculate_match_score(
                    cited_title, cited_authors,
                    version_data['title'], version_data['authors'],
                )

                # Also check actual author name overlap
                version_last_names = self._author_last_names(version_data.get('authors', []))
                if cited_last_names and version_last_names:
                    overlap = len(cited_last_names & version_last_names) / len(cited_last_names)
                else:
                    overlap = 0.0

                if score > best_score:
                    best_score = score
                    best_version = version_num
                    best_overlap = overlap
                if best_score >= 0.98 and overlap >= 0.5:
                    break

            SIMILARITY_THRESHOLD = 0.75
            AUTHOR_OVERLAP_THRESHOLD = 0.4  # At least 40% of cited last names must appear

            if not best_version or best_score < SIMILARITY_THRESHOLD:
                return None
            if best_overlap < AUTHOR_OVERLAP_THRESHOLD:
                logger.debug(
                    f"ArXiv version v{best_version} title matches (score {best_score:.2f}) "
                    f"but author overlap is only {best_overlap:.0%} — not a version match"
                )
                return None

            logger.info(
                f"ArXiv version match: ref matches v{best_version} "
                f"(score {best_score:.2f}, author overlap {best_overlap:.0%}) of {arxiv_id}"
            )

            # Convert errors to warnings with version annotation
            updated = dict(result)
            version_suffix = f" (v{best_version} vs v{latest_version} update)"
            new_errors = []
            new_warnings = list(updated.get('warnings', []))
            for err in updated.get('errors', []):
                etype = err.get('error_type', '')
                if etype in ('year', 'venue', 'author') or 'mismatch' in (err.get('error_details') or '').lower():
                    new_warnings.append({
                        'error_type': etype + version_suffix,
                        'error_details': err.get('error_details', ''),
                        'is_warning': True,
                        **{k: err[k] for k in ('cited_value', 'actual_value', 'ref_authors_correct', 'ref_year_correct') if k in err},
                    })
                else:
                    new_errors.append(err)

            updated['errors'] = new_errors
            updated['warnings'] = new_warnings
            if not new_errors:
                updated['status'] = 'warning' if new_warnings else 'verified'
            updated['_raw_errors'] = []  # Clear so hallucination check is skipped

            return updated

        except Exception as exc:
            logger.debug(f"ArXiv version check failed: {exc}")
            return None

    def _run_hallucination_check_sync(self, result: Dict[str, Any], reference: Dict[str, Any]) -> Dict[str, Any]:
        """Run hallucination check synchronously and return updated result.

        Called from a thread pool *after* the initial result has already
        been streamed to the UI, so the user sees the reference immediately.
        Deterministic checks (author overlap, name order) are already handled
        by _pre_screen_hallucination — this method focuses on ArXiv version
        match and LLM assessment.
        """
        # Before running the LLM, check if metadata mismatches are explained
        # by a different ArXiv version (e.g. v1 preprint vs v2 conference).
        version_result = self._try_arxiv_version_match(result, reference)
        if version_result is not None:
            return version_result

        auth_urls = result.get('authoritative_urls') or []
        verified_url = auth_urls[0]['url'] if auth_urls else ''
        error_entry = build_hallucination_error_entry(
            result.get('_raw_errors', []), reference, verified_url=verified_url,
        )
        if error_entry is None:
            return result

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

        result = apply_hallucination_verdict(result, assessment)
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
        total_refs: int
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
        verified_count = 0
        refs_with_errors = 0
        refs_with_warnings_only = 0
        refs_verified = 0
        processed_count = 0
        checked_count = 0  # Tracks refs that finished verification (including deferred ones)
        
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
                d = self._compute_ref_stats(result)
                errors_count += d['errors_count']
                warnings_count += d['warnings_count']
                suggestions_count += d['suggestions_count']
                hallucination_count += d['hallucination_count']
                unverified_count += d['unverified_count']
                verified_count += d['verified_count']
                refs_verified += d['refs_verified']
                refs_with_errors += d['refs_with_errors']
                refs_with_warnings_only += d['refs_with_warnings_only']

                # Emit result immediately.
                # Use checked_count for progress so the UI shows verification
                # advancing in real-time.
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
                    "verified_count": verified_count,
                    "refs_with_errors": refs_with_errors,
                    "refs_with_warnings_only": refs_with_warnings_only,
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
                        d = self._compute_deferred_ref_deltas(resolved, c_result)
                        errors_count += d['errors_count']
                        warnings_count += d['warnings_count']
                        suggestions_count += d['suggestions_count']
                        hallucination_count += d['hallucination_count']
                        unverified_count += d['unverified_count']
                        verified_count += d['verified_count']
                        refs_verified += d['refs_verified']
                        refs_with_errors += d['refs_with_errors']
                        refs_with_warnings_only += d['refs_with_warnings_only']
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
                        "verified_count": verified_count,
                        "refs_with_errors": refs_with_errors,
                        "refs_with_warnings_only": refs_with_warnings_only,
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
                                        "verified_count": verified_count,
                                        "refs_with_errors": refs_with_errors,
                                        "refs_with_warnings_only": refs_with_warnings_only,
                                        "refs_verified": refs_verified,
                                        "progress_percent": round((checked_count / total_refs) * 100, 1),
                                    })
                                continue

                            updated['hallucination_check_pending'] = False

                            # Adjust stats: subtract old contribution, add new
                            d = self._compute_deferred_ref_deltas(updated, old_result)
                            errors_count += d['errors_count']
                            warnings_count += d['warnings_count']
                            suggestions_count += d['suggestions_count']
                            hallucination_count += d['hallucination_count']
                            unverified_count += d['unverified_count']
                            verified_count += d['verified_count']
                            refs_verified += d['refs_verified']
                            refs_with_errors += d['refs_with_errors']
                            refs_with_warnings_only += d['refs_with_warnings_only']

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
                                "verified_count": verified_count,
                                "refs_with_errors": refs_with_errors,
                                "refs_with_warnings_only": refs_with_warnings_only,
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
                    "verified_count": verified_count,
                    "refs_with_errors": refs_with_errors,
                    "refs_with_warnings_only": refs_with_warnings_only,
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
        
        return results_list, errors_count, warnings_count, suggestions_count, unverified_count, verified_count, refs_with_errors, refs_with_warnings_only, refs_verified, hallucination_count
