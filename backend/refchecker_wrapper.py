"""
Wrapper around refchecker library with progress callbacks for real-time updates
"""
import sys
import os
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path

# Add src to path to import refchecker
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from refchecker.utils.text_utils import extract_arxiv_id_from_url
from refchecker.services.pdf_processor import PDFProcessor
from refchecker.llm.base import create_llm_provider, ReferenceExtractor
from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
import arxiv

logger = logging.getLogger(__name__)

# Max concurrent reference checks (similar to CLI default)
MAX_CONCURRENT_CHECKS = 6


class ProgressRefChecker:
    """
    RefChecker wrapper with progress callbacks for real-time updates
    """

    def __init__(self,
                 llm_provider: Optional[str] = None,
                 llm_model: Optional[str] = None,
                 api_key: Optional[str] = None,
                 use_llm: bool = True,
                 progress_callback: Optional[Callable] = None,
                 cancel_event: Optional[asyncio.Event] = None):
        """
        Initialize the progress-aware refchecker

        Args:
            llm_provider: LLM provider (anthropic, openai, google, etc.)
            llm_model: Specific model to use
            api_key: API key for the LLM provider
            use_llm: Whether to use LLM for reference extraction
            progress_callback: Async callback for progress updates
        """
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.api_key = api_key
        self.use_llm = use_llm
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event

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

            await self._check_cancelled()
            if source_type == "url":
                # Handle ArXiv URLs/IDs
                arxiv_id = extract_arxiv_id_from_url(paper_source)
                if not arxiv_id:
                    arxiv_id = paper_source  # Assume it's already an ID

                await self.emit_progress("extracting", {
                    "message": f"Fetching ArXiv paper {arxiv_id}..."
                })

                # Download from ArXiv
                search = arxiv.Search(id_list=[arxiv_id])
                paper = next(search.results())
                paper_title = paper.title

                # Download PDF
                pdf_path = f"/tmp/arxiv_{arxiv_id}.pdf"
                paper.download_pdf(filename=pdf_path)

                # Extract text from PDF
                pdf_processor = PDFProcessor()
                paper_text = pdf_processor.extract_text_from_pdf(pdf_path)

            elif source_type == "file":
                await self.emit_progress("extracting", {
                    "message": "Extracting text from file..."
                })

                # Handle uploaded file
                if paper_source.lower().endswith('.pdf'):
                    pdf_processor = PDFProcessor()
                    paper_text = pdf_processor.extract_text_from_pdf(paper_source)
                    paper_title = Path(paper_source).stem
                elif paper_source.lower().endswith(('.tex', '.txt')):
                    with open(paper_source, 'r', encoding='utf-8') as f:
                        paper_text = f.read()
                    paper_title = Path(paper_source).stem
                else:
                    raise ValueError(f"Unsupported file type: {paper_source}")
            elif source_type == "text":
                await self.emit_progress("extracting", {
                    "message": "Preparing pasted text..."
                })
                paper_text = paper_source
                paper_title = "Pasted Text"
            else:
                raise ValueError(f"Unsupported source type: {source_type}")

            # Step 2: Extract references
            await self.emit_progress("extracting", {
                "message": "Extracting references from paper...",
                "paper_title": paper_title
            })

            references = await self._extract_references(paper_text)

            if not references:
                return {
                    "paper_title": paper_title,
                    "paper_source": paper_source,
                    "references": [],
                    "summary": {
                        "total_refs": 0,
                        "errors_count": 0,
                        "warnings_count": 0,
                        "unverified_count": 0,
                        "verified_count": 0
                    }
                }

            # Step 3: Check references in parallel (like CLI)
            total_refs = len(references)
            await self.emit_progress("references_extracted", {
                "total_refs": total_refs,
                "references": [
                    {
                        "index": idx,
                        "title": ref.get("title", "Unknown Title"),
                        "authors": ref.get("authors", []),
                        "year": ref.get("year"),
                        "venue": ref.get("venue")
                    }
                    for idx, ref in enumerate(references, 1)
                ]
            })
            await self.emit_progress("progress", {
                "current": 0,
                "total": total_refs,
                "message": f"Checking {total_refs} references with {MAX_CONCURRENT_CHECKS} parallel workers..."
            })

            # Process references in parallel
            results, errors_count, warnings_count, unverified_count, verified_count = \
                await self._check_references_parallel(references, total_refs)

            # Step 4: Return final results
            final_result = {
                "paper_title": paper_title,
                "paper_source": paper_source,
                "references": results,
                "summary": {
                    "total_refs": total_refs,
                    "processed_refs": total_refs,
                    "errors_count": errors_count,
                    "warnings_count": warnings_count,
                    "unverified_count": unverified_count,
                    "verified_count": verified_count,
                    "progress_percent": 100.0
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
        """Extract references from paper text"""
        try:
            # First, extract just the bibliography section from the full paper text
            from refchecker.utils.bibliography_utils import find_bibliography_section, parse_references
            
            bib_section = find_bibliography_section(paper_text)
            if not bib_section:
                logger.warning("Could not find bibliography section in paper")
                # Fall back to trying the full text (might work for short texts or pasted bibliographies)
                bib_section = paper_text
            else:
                logger.info(f"Found bibliography section ({len(bib_section)} chars)")
            
            if self.llm:
                # Use LLM for extraction on the bibliography section only
                extractor = ReferenceExtractor(self.llm)
                refs = extractor.extract_references(bib_section)
                if refs:
                    # LLM returns strings in Author#Title#Venue#Year#URL format
                    # Convert to dicts
                    parsed_refs = []
                    for ref in refs:
                        if isinstance(ref, dict):
                            parsed_refs.append(ref)
                        else:
                            parsed = self._parse_llm_reference(ref)
                            if parsed:
                                parsed_refs.append(parsed)
                    
                    if parsed_refs:
                        logger.info(f"LLM extraction found {len(parsed_refs)} references")
                        return parsed_refs
                # LLM returned nothing, try fallback
                logger.warning("LLM returned no references, trying regex fallback")
            
            # Fall back to regex-based extraction
            if bib_section:
                refs = parse_references(bib_section)
                if refs:
                    logger.info(f"Regex extraction found {len(refs)} references")
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

            # Determine status
            has_errors = any(e.get('error_type') not in ['unverified'] for e in errors)
            has_warnings = any(e.get('error_type') in ['year', 'venue'] for e in errors)
            is_unverified = any(e.get('error_type') == 'unverified' for e in errors)

            if has_errors:
                status = 'error'
            elif has_warnings:
                status = 'warning'
            elif is_unverified:
                status = 'unverified'
            else:
                status = 'verified'

            # Extract authoritative URLs with proper type detection
            authoritative_urls = []
            if url:
                # Detect URL type from URL pattern
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
            if verified_data and verified_data.get('arxiv_id'):
                authoritative_urls.append({
                    "type": "arxiv",
                    "url": f"https://arxiv.org/abs/{verified_data['arxiv_id']}"
                })
            if verified_data and verified_data.get('doi'):
                authoritative_urls.append({
                    "type": "doi",
                    "url": f"https://doi.org/{verified_data['doi']}"
                })

            # Format errors and warnings
            formatted_errors = []
            formatted_warnings = []
            for err in errors:
                err_obj = {
                    "error_type": err.get('error_type', 'unknown'),
                    "error_details": err.get('error_details', ''),
                    "cited_value": err.get('cited_value'),
                    "actual_value": err.get('actual_value')
                }
                if err.get('error_type') in ['year', 'venue']:
                    formatted_warnings.append(err_obj)
                else:
                    formatted_errors.append(err_obj)

            return {
                "index": index,
                "title": reference.get('title', 'Unknown Title'),
                "authors": reference.get('authors', []),
                "year": reference.get('year'),
                "venue": reference.get('venue'),
                "cited_url": reference.get('url'),
                "status": status,
                "errors": formatted_errors,
                "warnings": formatted_warnings,
                "authoritative_urls": authoritative_urls,
                "corrected_reference": None  # TODO: Generate corrected reference
            }

        except Exception as e:
            logger.error(f"Error checking reference {index}: {e}")
            return {
                "index": index,
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

    def _check_reference_sync(self, reference: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Synchronous version of reference checking for thread pool"""
        try:
            # Run verification with timeout (handled by caller)
            verified_data, errors, url = self.checker.verify_reference(reference)

            # Determine status
            has_errors = any(e.get('error_type') not in ['unverified'] for e in errors)
            has_warnings = any(e.get('error_type') in ['year', 'venue'] for e in errors)
            is_unverified = any(e.get('error_type') == 'unverified' for e in errors)

            if has_errors:
                status = 'error'
            elif has_warnings:
                status = 'warning'
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
            if verified_data and verified_data.get('arxiv_id'):
                authoritative_urls.append({
                    "type": "arxiv",
                    "url": f"https://arxiv.org/abs/{verified_data['arxiv_id']}"
                })
            if verified_data and verified_data.get('doi'):
                authoritative_urls.append({
                    "type": "doi",
                    "url": f"https://doi.org/{verified_data['doi']}"
                })

            # Format errors and warnings
            formatted_errors = []
            formatted_warnings = []
            for err in errors:
                err_obj = {
                    "error_type": err.get('error_type', 'unknown'),
                    "error_details": err.get('error_details', ''),
                    "cited_value": err.get('cited_value'),
                    "actual_value": err.get('actual_value')
                }
                if err.get('error_type') in ['year', 'venue']:
                    formatted_warnings.append(err_obj)
                else:
                    formatted_errors.append(err_obj)

            return {
                "index": index,
                "title": reference.get('title', 'Unknown Title'),
                "authors": reference.get('authors', []),
                "year": reference.get('year'),
                "venue": reference.get('venue'),
                "cited_url": reference.get('url'),
                "status": status,
                "errors": formatted_errors,
                "warnings": formatted_warnings,
                "authoritative_urls": authoritative_urls,
                "corrected_reference": None
            }

        except Exception as e:
            logger.error(f"Error checking reference {index}: {e}")
            return {
                "index": index,
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

    async def _check_references_parallel(
        self,
        references: List[Dict[str, Any]],
        total_refs: int
    ) -> tuple:
        """
        Check references in parallel using ThreadPoolExecutor.
        
        Emits progress updates as results come in.
        Only marks references as 'checking' when they actually start.
        Returns results list and counts.
        """
        results = [None] * total_refs  # Pre-allocate for ordered results
        errors_count = 0
        warnings_count = 0
        unverified_count = 0
        verified_count = 0
        processed_count = 0
        
        loop = asyncio.get_event_loop()
        
        # Track which references are currently being checked
        active_indices = set()
        next_to_submit = 0
        
        # Create a thread pool executor
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CHECKS, thread_name_prefix="RefCheck") as executor:
            future_to_index = {}
            pending = set()
            
            # Submit initial batch (up to MAX_CONCURRENT_CHECKS)
            while next_to_submit < total_refs and len(pending) < MAX_CONCURRENT_CHECKS:
                idx = next_to_submit
                ref = references[idx]
                
                # Mark reference as checking when it actually starts
                await self.emit_progress("checking_reference", {
                    "index": idx + 1,
                    "title": ref.get("title", "Unknown Title"),
                    "total": total_refs
                })
                active_indices.add(idx)
                
                future = loop.run_in_executor(
                    executor,
                    self._check_reference_sync,
                    ref,
                    idx + 1
                )
                future_to_index[future] = idx
                pending.add(future)
                next_to_submit += 1
            
            # Process results as they complete and submit more
            while pending:
                # Check for cancellation
                await self._check_cancelled()
                
                # Wait for the next result with a short timeout to allow cancellation checks
                done, pending = await asyncio.wait(
                    pending,
                    timeout=0.5,
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                for future in done:
                    idx = future_to_index[future]
                    active_indices.discard(idx)
                    
                    try:
                        result = await asyncio.wait_for(asyncio.shield(future), timeout=60.0)
                    except asyncio.TimeoutError:
                        result = {
                            "index": idx + 1,
                            "title": references[idx].get('title', 'Unknown'),
                            "authors": references[idx].get('authors', []),
                            "year": references[idx].get('year'),
                            "venue": references[idx].get('venue'),
                            "cited_url": references[idx].get('url'),
                            "status": "error",
                            "errors": [{
                                "error_type": "timeout",
                                "error_details": "Verification timed out after 60 seconds"
                            }],
                            "warnings": [],
                            "authoritative_urls": [],
                            "corrected_reference": None
                        }
                    except Exception as e:
                        logger.error(f"Error in parallel check for reference {idx + 1}: {e}")
                        result = {
                            "index": idx + 1,
                            "title": references[idx].get('title', 'Unknown'),
                            "authors": references[idx].get('authors', []),
                            "year": references[idx].get('year'),
                            "venue": references[idx].get('venue'),
                            "cited_url": references[idx].get('url'),
                            "status": "error",
                            "errors": [{
                                "error_type": "check_failed",
                                "error_details": str(e)
                            }],
                            "warnings": [],
                            "authoritative_urls": [],
                            "corrected_reference": None
                        }
                    
                    # Store result in ordered position
                    results[idx] = result
                    processed_count += 1
                    
                    # Update counts
                    if result['status'] == 'error':
                        errors_count += 1
                    elif result['status'] == 'warning':
                        warnings_count += 1
                    elif result['status'] == 'unverified':
                        unverified_count += 1
                    elif result['status'] == 'verified':
                        verified_count += 1
                    
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
                        "unverified_count": unverified_count,
                        "verified_count": verified_count,
                        "progress_percent": round((processed_count / total_refs) * 100, 1)
                    })
                    
                    # Submit next reference if there are more
                    if next_to_submit < total_refs:
                        next_idx = next_to_submit
                        next_ref = references[next_idx]
                        
                        # Mark as checking when it starts
                        await self.emit_progress("checking_reference", {
                            "index": next_idx + 1,
                            "title": next_ref.get("title", "Unknown Title"),
                            "total": total_refs
                        })
                        active_indices.add(next_idx)
                        
                        next_future = loop.run_in_executor(
                            executor,
                            self._check_reference_sync,
                            next_ref,
                            next_idx + 1
                        )
                        future_to_index[next_future] = next_idx
                        pending.add(next_future)
                        next_to_submit += 1
        
        return results, errors_count, warnings_count, unverified_count, verified_count
