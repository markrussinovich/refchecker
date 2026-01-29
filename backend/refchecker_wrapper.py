"""
Wrapper around refchecker library with progress callbacks for real-time updates
"""
import sys
import os
import re
import asyncio
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path

# Add src to path to import refchecker when running from source
# This is only needed when not installed as a package
_src_path = str(Path(__file__).parent.parent / "src")
if _src_path not in sys.path and os.path.exists(_src_path):
    sys.path.insert(0, _src_path)

from backend.concurrency import get_limiter

from refchecker.utils.text_utils import extract_latex_references
from refchecker.utils.url_utils import extract_arxiv_id_from_url
from refchecker.services.pdf_processor import PDFProcessor
from refchecker.llm.base import create_llm_provider, ReferenceExtractor
from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.arxiv_utils import get_bibtex_content
import arxiv

logger = logging.getLogger(__name__)


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
                 bibliography_source_callback: Optional[Callable] = None):
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

        # Initialize LLM if requested
        self.llm = None
        if use_llm and llm_provider:
            try:
                # Build config dict for the LLM provider
                llm_config = {}
                if llm_model:
                    llm_config['model'] = llm_model
                if api_key:
                    llm_config['api_key'] = api_key
                if endpoint:
                    llm_config['endpoint'] = endpoint
                self.llm = create_llm_provider(
                    provider_name=llm_provider,
                    config=llm_config
                )
                logger.info(f"Initialized LLM provider: {llm_provider}")
            except Exception as e:
                logger.error(f"Failed to initialize LLM: {e}")

        # Initialize reference checker
        self.checker = EnhancedHybridReferenceChecker(
            semantic_scholar_api_key=os.getenv('SEMANTIC_SCHOLAR_API_KEY'),
            debug_mode=False
        )

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
        for err in errors:
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
                # If it was info_type, store as 'info' to ensure proper categorization
                "error_type": 'info' if is_info else (e_type or 'unknown'),
                "error_details": details or '',
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
            e.get('error_type') not in ['unverified', 'info'] 
            and not e.get('is_suggestion')
            and not e.get('is_warning')
            for e in sanitized
        )
        has_warnings = any(
            e.get('is_warning')
            and not e.get('is_suggestion') 
            for e in sanitized
        )
        has_suggestions = any(e.get('is_suggestion') or e.get('error_type') == 'info' for e in sanitized)
        is_unverified = any(e.get('error_type') == 'unverified' for e in sanitized)

        if has_errors:
            status = 'error'
        elif has_warnings:
            status = 'warning'
        elif has_suggestions:
            status = 'suggestion'
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
                s2_url = f"https://www.semanticscholar.org/paper/{s2_paper_id}"
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
            if err.get('is_suggestion') or err.get('error_type') == 'info':
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

        result = {
            "index": index,
            "title": reference.get('title') or reference.get('cited_url') or reference.get('url') or 'Unknown Title',
            "authors": reference.get('authors', []),
            "year": reference.get('year'),
            "venue": reference.get('venue'),
            "cited_url": reference.get('cited_url') or reference.get('url'),
            "status": status,
            "errors": formatted_errors,
            "warnings": formatted_warnings,
            "suggestions": formatted_suggestions,
            "authoritative_urls": authoritative_urls,
            "corrected_reference": None
        }
        logger.debug(f"_format_verification_result output: status={status}, errors={len(formatted_errors)}, warnings={len(formatted_warnings)}, suggestions={len(formatted_suggestions)}")
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

            async def update_title_if_needed(title: str):
                nonlocal title_updated
                if not title_updated and title and title != "Unknown Paper":
                    title_updated = True
                    if self.title_update_callback and self.check_id:
                        await self.title_update_callback(self.check_id, title)
                    # Also emit via WebSocket so frontend can update
                    await self.emit_progress("title_updated", {"paper_title": title})

            await self._check_cancelled()
            # Track if we got references from ArXiv source files and the extraction method
            arxiv_source_references = None
            extraction_method = None  # 'bbl', 'bib', 'pdf', 'llm', or None
            
            if source_type == "url":
                # Check if this is a direct PDF URL (not arXiv)
                is_direct_pdf_url = (
                    paper_source.lower().endswith('.pdf') and 
                    'arxiv.org' not in paper_source.lower()
                )
                
                if is_direct_pdf_url:
                    # Handle direct PDF URLs (e.g., Microsoft Research PDFs)
                    # PDF extraction requires LLM for reliable reference extraction
                    if not self.llm:
                        raise ValueError("PDF extraction requires an LLM to be configured. Please configure an LLM provider in settings.")
                    
                    await self.emit_progress("extracting", {
                        "message": "Downloading PDF from URL..."
                    })
                    
                    # Download PDF from URL
                    import urllib.request
                    import hashlib
                    pdf_hash = hashlib.md5(paper_source.encode()).hexdigest()[:12]
                    pdf_path = os.path.join(tempfile.gettempdir(), f"refchecker_pdf_{pdf_hash}.pdf")
                    
                    def download_pdf_url():
                        urllib.request.urlretrieve(paper_source, pdf_path)
                        return pdf_path
                    
                    await asyncio.to_thread(download_pdf_url)
                    
                    # Extract title from PDF filename or URL
                    from urllib.parse import urlparse, unquote
                    url_path = urlparse(paper_source).path
                    pdf_filename = unquote(url_path.split('/')[-1])
                    paper_title = pdf_filename.replace('.pdf', '').replace('_', ' ').replace('-', ' ')
                    await update_title_if_needed(paper_title)
                    
                    extraction_method = 'pdf'
                    pdf_processor = PDFProcessor()
                    paper_text = await asyncio.to_thread(pdf_processor.extract_text_from_pdf, pdf_path)
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
                        arxiv_source_references, extraction_method = result
                        if arxiv_source_references:
                            logger.info(f"Extracted {len(arxiv_source_references)} references from ArXiv source files (method: {extraction_method})")
                        else:
                            logger.warning("Could not extract references from ArXiv source, falling back to PDF")
                    
                    # Fall back to PDF extraction if no references from source files
                    if not arxiv_source_references:
                        # PDF extraction requires LLM for reliable reference extraction
                        if not self.llm:
                            raise ValueError("PDF extraction requires an LLM to be configured. Please configure an LLM provider in settings or provide a paper with BibTeX/LaTeX source files.")
                        extraction_method = 'pdf'
                        # Download PDF - run in thread (use cross-platform temp directory)
                        pdf_path = os.path.join(tempfile.gettempdir(), f"arxiv_{arxiv_id}.pdf")
                        await asyncio.to_thread(paper.download_pdf, filename=pdf_path)

                        # Extract text from PDF - run in thread
                        pdf_processor = PDFProcessor()
                        paper_text = await asyncio.to_thread(pdf_processor.extract_text_from_pdf, pdf_path)
                    else:
                        paper_text = ""  # Not needed since we have references

            elif source_type == "file":
                extraction_method = 'file'
                await self.emit_progress("extracting", {
                    "message": "Extracting text from file..."
                })

                # Handle uploaded file - run PDF processing in thread
                # Note: paper_title is already set to the original filename in main.py
                # so we don't update it here
                if paper_source.lower().endswith('.pdf'):
                    # PDF extraction requires LLM for reliable reference extraction
                    if not self.llm:
                        raise ValueError("PDF extraction requires an LLM to be configured. Please configure an LLM provider in settings.")
                    pdf_processor = PDFProcessor()
                    paper_text = await asyncio.to_thread(pdf_processor.extract_text_from_pdf, paper_source)
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
                            extraction_method = 'bib'
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
                extraction_method = 'text'
                
                # Check if the pasted text is LaTeX thebibliography format (.bbl)
                if '\\begin{thebibliography}' in paper_text and '\\bibitem' in paper_text:
                    logger.info("Detected LaTeX thebibliography format in pasted text")
                    # Use the BibTeX extraction method instead
                    refs_result = await self._extract_references_from_bibtex(paper_text)
                    if refs_result and refs_result[0]:
                        arxiv_source_references = refs_result[0]
                        extraction_method = 'bbl'  # Mark as bbl extraction
                        logger.info(f"Extracted {len(arxiv_source_references)} references from pasted .bbl content")
                # Check if the pasted text is BibTeX format (@article, @misc, @inproceedings, etc.)
                elif re.search(r'@\s*(article|book|inproceedings|incollection|misc|techreport|phdthesis|mastersthesis|conference|inbook|proceedings)\s*\{', paper_text, re.IGNORECASE):
                    logger.info("Detected BibTeX format in pasted text")
                    refs_result = await self._extract_references_from_bibtex(paper_text)
                    if refs_result and refs_result[0]:
                        arxiv_source_references = refs_result[0]
                        extraction_method = 'bib'  # Mark as bib extraction
                        logger.info(f"Extracted {len(arxiv_source_references)} references from pasted BibTeX content")
                # Fallback: Try BibTeX parsing anyway for partial/malformed content
                # This handles cases like incomplete paste, or BibTeX-like content without standard entry types
                elif any(marker in paper_text for marker in ['title={', 'author={', 'year={', 'eprint={', '@']):
                    logger.info("Detected possible BibTeX-like content, attempting parse")
                    refs_result = await self._extract_references_from_bibtex(paper_text)
                    if refs_result and refs_result[0]:
                        arxiv_source_references = refs_result[0]
                        extraction_method = 'bib'
                        logger.info(f"Extracted {len(arxiv_source_references)} references from partial BibTeX content")
                    else:
                        logger.warning("BibTeX-like content detected but parsing failed, will try LLM extraction")
                # Don't update title for pasted text - keep the placeholder
            else:
                raise ValueError(f"Unsupported source type: {source_type}")

            # Step 2: Extract references
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
                # If we used PDF/file extraction and LLM was configured, mark as LLM-assisted
                if self.llm and extraction_method in ('pdf', 'file', 'text'):
                    extraction_method = 'llm'

            if not references:
                return {
                    "paper_title": paper_title,
                    "paper_source": paper_source,
                    "extraction_method": extraction_method,
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
            limiter = get_limiter()
            await self.emit_progress("progress", {
                "current": 0,
                "total": total_refs,
                "message": f"Checking {total_refs} references (max {limiter.max_concurrent} concurrent)..."
            })

            # Process references in parallel
            results, errors_count, warnings_count, suggestions_count, unverified_count, verified_count, refs_with_errors, refs_with_warnings_only, refs_verified = \
                await self._check_references_parallel(references, total_refs)

            # Step 4: Return final results
            final_result = {
                "paper_title": paper_title,
                "paper_source": paper_source,
                "extraction_method": extraction_method,
                "references": results,
                "summary": {
                    "total_refs": total_refs,
                    "processed_refs": total_refs,
                    "errors_count": errors_count,
                    "warnings_count": warnings_count,
                    "suggestions_count": suggestions_count,
                    "unverified_count": unverified_count,
                    "verified_count": verified_count,
                    "refs_with_errors": refs_with_errors,
                    "refs_with_warnings_only": refs_with_warnings_only,
                    "refs_verified": refs_verified,
                    "progress_percent": 100.0,
                    "extraction_method": extraction_method
                }
            }

            await self.emit_progress("completed", final_result["summary"])

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
            bib_section = await asyncio.to_thread(cli_checker.find_bibliography_section, paper_text)
            if not bib_section:
                logger.warning("Could not find bibliography section in paper")
                return []

            logger.info(f"Found bibliography section ({len(bib_section)} chars)")

            # Step 2: parse references (CLI logic, including LLM and post-processing) - run in thread
            refs = await asyncio.to_thread(cli_checker.parse_references, bib_section)
            if cli_checker.fatal_error:
                logger.error("Reference parsing failed (CLI fatal_error)")
                return []
            if refs:
                logger.info(f"Extracted {len(refs)} references via CLI parser")
                # Normalize field names (journal -> venue)
                refs = [_normalize_reference_fields(ref) for ref in refs]
                return refs

            logger.warning("No references could be extracted")
            return []
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error extracting references: {error_msg}")
            # Emit error to frontend
            await self.emit_progress("error", {
                "message": f"Failed to extract references: {error_msg}",
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
                                processed_refs = await asyncio.to_thread(cli_checker._process_llm_extracted_references, llm_refs)
                                llm_validation = await asyncio.to_thread(validate_parsed_references, processed_refs)
                                if llm_validation['quality_score'] > validation['quality_score']:
                                    logger.info(f"LLM extraction improved quality ({llm_validation['quality_score']:.2f})")
                                    # Normalize field names (journal -> venue)
                                    processed_refs = [_normalize_reference_fields(ref) for ref in processed_refs]
                                    return (processed_refs, 'llm')
                        except Exception as e:
                            logger.warning(f"LLM fallback failed: {e}")
                    
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
                    loop.run_in_executor(None, self.checker.verify_reference, reference),
                    timeout=60.0  # 60 second timeout per reference
                )
            except asyncio.TimeoutError:
                logger.warning(f"Reference {index} verification timed out")
                verified_data = None
                errors = [{"error_type": "timeout", "error_details": "Verification timed out after 60 seconds"}]
                url = None

            return self._format_verification_result(reference, index, verified_data, errors, url)

        except Exception as e:
            logger.error(f"Error checking reference {index}: {e}")
            return self._format_error_result(reference, index, e)

    def _check_reference_sync(self, reference: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Synchronous version of reference checking for thread pool"""
        try:
            # Run verification with timeout (handled by caller)
            verified_data, errors, url = self.checker.verify_reference(reference)
            return self._format_verification_result(reference, index, verified_data, errors, url)

        except Exception as e:
            logger.error(f"Error checking reference {index}: {e}")
            return self._format_error_result(reference, index, e)

    async def _check_single_reference_with_limit(
        self,
        reference: Dict[str, Any],
        idx: int,
        total_refs: int,
        loop: asyncio.AbstractEventLoop
    ) -> Dict[str, Any]:
        """
        Check a single reference with global concurrency limiting.
        
        First checks the verification cache for a previous result.
        Acquires a slot from the global limiter before starting the check,
        and releases it when done. Stores result in cache on success.
        """
        from .database import db
        
        # Check cache first
        cached_result = await db.get_cached_verification(reference)
        if cached_result:
            # Update the index to match current position
            cached_result['index'] = idx + 1
            logger.info(f"Cache hit for reference {idx + 1}: {reference.get('title', 'Unknown')[:50]}")
            return cached_result
        
        limiter = get_limiter()
        
        # Wait for a slot in the global queue
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
                # Use 240 second timeout to allow for ArXiv rate limiting with version checking
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,  # Use default executor
                        self._check_reference_sync,
                        reference,
                        idx + 1
                    ),
                    timeout=240.0  # 4 minute timeout per reference (allows for rate-limited version checking)
                )
            except asyncio.TimeoutError:
                result = {
                    "index": idx + 1,
                    "title": reference.get('title') or reference.get('cited_url') or reference.get('url') or 'Unknown',
                    "authors": reference.get('authors', []),
                    "year": reference.get('year'),
                    "venue": reference.get('venue'),
                    "cited_url": reference.get('cited_url') or reference.get('url'),
                    "status": "error",
                    "errors": [{
                        "error_type": "timeout",
                        "error_details": "Verification timed out after 240 seconds"
                    }],
                    "warnings": [],
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
        
        # Store successful results in cache (db.store_cached_verification filters out errors)
        try:
            await db.store_cached_verification(reference, result)
        except Exception as cache_error:
            logger.warning(f"Failed to cache verification result: {cache_error}")
        
        return result

    async def _check_references_parallel(
        self,
        references: List[Dict[str, Any]],
        total_refs: int
    ) -> tuple:
        """
        Check references in parallel using global concurrency limiting.
        
        All papers share the same global limit, so if you have 3 papers checking
        and concurrency is 6, each paper gets a share of the 6 slots.
        
        Emits progress updates as results come in.
        Only marks references as 'checking' when they actually start.
        Returns results list and counts.
        """
        results = {}
        errors_count = 0
        warnings_count = 0
        suggestions_count = 0
        unverified_count = 0
        verified_count = 0
        refs_with_errors = 0
        refs_with_warnings_only = 0
        refs_verified = 0
        processed_count = 0
        
        loop = asyncio.get_event_loop()
        
        # Create tasks for all references - they will be rate-limited by the global semaphore
        tasks = []
        for idx, ref in enumerate(references):
            task = asyncio.create_task(
                self._check_single_reference_with_limit(ref, idx, total_refs, loop),
                name=f"ref-check-{idx}"
            )
            tasks.append((idx, task))
        
        # Process results as they complete
        pending_tasks = {task for _, task in tasks}
        task_to_idx = {task: idx for idx, task in tasks}
        
        while pending_tasks:
            # Check for cancellation
            try:
                await self._check_cancelled()
            except asyncio.CancelledError:
                # Cancel all pending tasks
                for task in pending_tasks:
                    task.cancel()
                raise
            
            # Wait for some tasks to complete
            done, pending_tasks = await asyncio.wait(
                pending_tasks,
                timeout=0.5,
                return_when=asyncio.FIRST_COMPLETED
            )
            
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
                processed_count += 1
                
                # Count individual issues (not just references)
                # Exclude 'unverified' from error count since it has its own category
                real_errors = [e for e in result.get('errors', []) if e.get('error_type') != 'unverified']
                num_errors = len(real_errors)
                num_warnings = len(result.get('warnings', []))
                num_suggestions = len(result.get('suggestions', []))
                
                errors_count += num_errors
                warnings_count += num_warnings
                suggestions_count += num_suggestions
                
                # Count references by status for filtering
                if result['status'] == 'unverified':
                    unverified_count += 1
                elif result['status'] == 'verified':
                    verified_count += 1
                    refs_verified += 1
                elif result['status'] == 'suggestion':
                    # Suggestion-only refs are considered verified (no errors or warnings)
                    verified_count += 1
                    refs_verified += 1
                
                # Track references by issue type (excluding unverified from error check)
                if result['status'] == 'error' or num_errors > 0:
                    refs_with_errors += 1
                elif result['status'] == 'warning' or num_warnings > 0:
                    refs_with_warnings_only += 1
                
                # Emit result immediately
                await self.emit_progress("reference_result", result)
                await self.emit_progress("progress", {
                    "current": processed_count,
                    "total": total_refs
                })
                await self.emit_progress("summary_update", {
                    "total_refs": total_refs,
                    "processed_refs": processed_count,
                    "errors_count": errors_count,
                    "warnings_count": warnings_count,
                    "suggestions_count": suggestions_count,
                    "unverified_count": unverified_count,
                    "verified_count": verified_count,
                    "refs_with_errors": refs_with_errors,
                    "refs_with_warnings_only": refs_with_warnings_only,
                    "refs_verified": refs_verified,
                    "progress_percent": round((processed_count / total_refs) * 100, 1)
                })
        
        # Convert dict to ordered list
        results_list = [results.get(i) for i in range(total_refs)]
        
        return results_list, errors_count, warnings_count, suggestions_count, unverified_count, verified_count, refs_with_errors, refs_with_warnings_only, refs_verified
