"""
Parallel reference processing system for RefChecker.

This module provides parallelized reference verification with ordered result output.
It maintains the same error detection quality as sequential processing while
dramatically improving performance for large bibliographies.
"""

import time
import logging
from queue import Queue
from threading import Thread, Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple, Callable
from refchecker.utils.text_utils import deduplicate_urls

logger = logging.getLogger(__name__)


@dataclass
class ReferenceWorkItem:
    """Work item for the reference verification queue."""
    index: int
    source_paper: Any
    reference: Dict[str, Any]
    timestamp: float


@dataclass
class ReferenceResult:
    """Result of a reference verification."""
    index: int
    errors: Optional[List[Dict[str, Any]]]
    url: Optional[str]
    processing_time: float
    reference: Dict[str, Any]
    verified_data: Optional[Dict[str, Any]] = None


class ParallelReferenceProcessor:
    """
    Parallel reference verification processor with ordered output.
    
    This class manages a pool of worker threads that verify references independently
    while ensuring results are printed in the original order (1, 2, 3...).
    """
    
    def __init__(self, base_checker: Any, max_workers: int = 6, enable_progress: bool = True):
        """
        Initialize the parallel processor.
        
        Args:
            base_checker: The base reference checker instance
            max_workers: Maximum number of worker threads
            enable_progress: Whether to show progress indicators
        """
        self.base_checker = base_checker
        self.max_workers = max_workers
        self.enable_progress = enable_progress
        
        # Threading components
        self.work_queue = Queue()
        self.result_queue = Queue()
        self.result_buffer = {}  # index -> ReferenceResult
        self.buffer_lock = Lock()
        
        # State tracking
        self.next_print_index = 0
        self.total_references = 0
        self.completed_count = 0
        self.start_time = 0
        
        # Statistics
        self.processing_stats = {
            'total_processed': 0,
            'total_errors': 0,
            'avg_processing_time': 0,
            'fastest_time': float('inf'),
            'slowest_time': 0
        }
    
    def verify_references_parallel(self, source_paper: Any, bibliography: List[Dict[str, Any]], 
                                 result_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Verify references in parallel with ordered output.
        
        Args:
            source_paper: The source paper containing the references
            bibliography: List of references to verify
            result_callback: Optional callback for each completed result
            
        Returns:
            Dictionary with processing statistics
        """
        if not bibliography:
            logger.info("No references to verify")
            return self._get_stats()
        
        self.total_references = len(bibliography)
        self.start_time = time.time()
        self.next_print_index = 0
        self.completed_count = 0
        self.result_buffer.clear()
        
        logger.debug(f"Starting parallel verification of {self.total_references} references with {self.max_workers} workers")
        
        # Populate work queue
        for i, reference in enumerate(bibliography):
            work_item = ReferenceWorkItem(
                index=i,
                source_paper=source_paper,
                reference=reference,
                timestamp=time.time()
            )
            self.work_queue.put(work_item)
        
        # Add sentinel values to signal workers to stop (one per worker)
        for _ in range(self.max_workers):
            self.work_queue.put(None)  # None signals end of work
        
        # Start result printer thread
        printer_thread = Thread(target=self._ordered_result_printer, args=(result_callback,))
        printer_thread.daemon = True
        printer_thread.start()
        
        # Start worker threads
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="RefWorker") as executor:
            # Submit worker tasks
            futures = []
            for worker_id in range(self.max_workers):
                future = executor.submit(self._worker_loop, worker_id)
                futures.append(future)
            
            # Wait for all workers to complete
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Worker thread failed: {e}")
        
        # Wait for printer to finish
        printer_thread.join()
        
        # Final stats printing disabled
        # if self.enable_progress:
        #     self._print_final_stats()
        
        return self._get_stats()
    
    def _worker_loop(self, worker_id: int) -> None:
        """
        Main loop for worker threads - no timeouts, only exit when queue is empty.
        
        Args:
            worker_id: Unique identifier for this worker
        """
        processed_count = 0
        logger.debug(f"Worker {worker_id} started")
        
        while True:
            try:
                # Get work item - blocks until available
                work_item = self.work_queue.get(block=True)
                
                # Check for sentinel value (signals end of work)
                if work_item is None:
                    self.work_queue.task_done()
                    break
                
                try:
                    # Perform reference verification using base checker
                    start_time = time.time()
                    errors, url, verified_data = self.base_checker.verify_reference(
                        work_item.source_paper,
                        work_item.reference
                    )
                    processing_time = time.time() - start_time
                    
                    # Create result
                    result = ReferenceResult(
                        index=work_item.index,
                        errors=errors,
                        url=url,
                        processing_time=processing_time,
                        reference=work_item.reference,
                        verified_data=verified_data
                    )
                    
                    # Put result in queue
                    self.result_queue.put(result)
                    processed_count += 1
                    
                    logger.debug(f"Worker {worker_id} completed reference {work_item.index} in {processing_time:.2f}s")
                    
                except Exception as e:
                    # Handle verification errors gracefully
                    logger.error(f"Worker {worker_id} failed to verify reference {work_item.index}: {e}")
                    
                    error_result = ReferenceResult(
                        index=work_item.index,
                        errors=[{"error_type": "processing_failed", "error_details": f"Internal processing error: {str(e)}"}],
                        url=None,
                        processing_time=time.time() - work_item.timestamp,
                        reference=work_item.reference
                    )
                    self.result_queue.put(error_result)
                
                finally:
                    self.work_queue.task_done()
                    
            except Exception as e:
                logger.error(f"Worker {worker_id} encountered unexpected error: {e}")
                break
        
        logger.debug(f"Worker {worker_id} finished after processing {processed_count} items")
    
    def _ordered_result_printer(self, result_callback: Optional[Callable] = None) -> None:
        """
        Print results in order and handle callbacks.
        
        Args:
            result_callback: Optional callback function for each result
        """
        logger.debug("Result printer started")
        
        while self.next_print_index < self.total_references:
            try:
                # Get result - blocks until available
                result = self.result_queue.get(block=True)
                
                # Store result in buffer
                with self.buffer_lock:
                    self.result_buffer[result.index] = result
                    self._update_stats(result)
                
                # Print any consecutive results starting from next_print_index
                with self.buffer_lock:
                    while self.next_print_index in self.result_buffer:
                        current_result = self.result_buffer[self.next_print_index]
                        
                        # Print the result using base checker's output methods
                        self._print_reference_result(current_result)
                        
                        # Call callback if provided
                        if result_callback:
                            try:
                                result_callback(current_result)
                            except Exception as e:
                                logger.error(f"Result callback failed for reference {current_result.index}: {e}")
                        
                        # Clean up and advance
                        del self.result_buffer[self.next_print_index]
                        self.next_print_index += 1
                        self.completed_count += 1
                        
                        # Show progress (disabled)
                        # if self.enable_progress and self.completed_count % 10 == 0:
                        #     self._print_progress()
                
            except Exception as e:
                logger.error(f"Result printer error: {e}")
                continue
        
        logger.debug("Result printer finished")
    
    
    def _print_reference_result(self, result: ReferenceResult) -> None:
        """
        Print a single reference result using the base checker's format.
        
        Args:
            result: The reference result to print
        """
        reference = result.reference
        
        # Print reference info in the same format as sequential mode
        raw_title = reference.get('title', 'Untitled')
        # Clean LaTeX commands from title for display
        from refchecker.utils.text_utils import strip_latex_commands
        title = strip_latex_commands(raw_title)
        from refchecker.utils.text_utils import format_authors_for_display
        authors = format_authors_for_display(reference.get('authors', []))
        year = reference.get('year', '')
        # Get venue from either 'venue' or 'journal' field and clean it up
        venue = reference.get('venue', '') or reference.get('journal', '')
        if venue:
            from refchecker.utils.error_utils import clean_venue_for_comparison
            venue = clean_venue_for_comparison(venue)
        url = reference.get('url', '')
        doi = reference.get('doi', '')
        
        # Extract actual reference number from raw text for accurate display
        import re
        raw_text = reference.get('raw_text', '')
        match = re.match(r'\[(\d+)\]', raw_text)
        ref_num = match.group(1) if match else str(result.index + 1)
        print(f"[{ref_num}/{self.total_references}] {title}")
        if authors:
            print(f"       {authors}")
        if venue:
            print(f"       {venue}")
        if year:
            print(f"       {year}")
        if doi:
            print(f"       {doi}")
        # Show cited URL if available
        if url:
            print(f"       {url}")
        
        # Get the appropriate verified URL using shared logic from base checker
        verified_url_to_show = self.base_checker._get_verified_url(result.verified_data, result.url, result.errors)
        
        # Show the verified URL with appropriate label
        print("")
        if verified_url_to_show:
            print(f"       Verified URL: {verified_url_to_show}")
        
        # Show correct ArXiv URL if available from verified data and different from cited
        if result.verified_data:
            external_ids = result.verified_data.get('externalIds', {})
            if external_ids.get('ArXiv'):
                correct_arxiv_url = f"https://arxiv.org/abs/{external_ids['ArXiv']}"
                # Only show if it's different from the cited URL
                if correct_arxiv_url != url:
                    print(f"       ArXiv URL: {correct_arxiv_url}")
        
        # Show additional external ID URLs if available and different
        if result.verified_data:
            external_ids = result.verified_data.get('externalIds', {})
            
            # Show DOI URL if available and different from what's already shown
            if external_ids.get('DOI'):
                from refchecker.utils.doi_utils import construct_doi_url
                doi_url = construct_doi_url(external_ids['DOI'])
                if doi_url != verified_url_to_show and doi_url != url:
                    print(f"       DOI URL: {doi_url}")
            
            # Show any other URL from verified data if different
            if result.verified_data.get('url') and result.verified_data['url'] != verified_url_to_show and result.verified_data['url'] != url:
                print(f"       {result.verified_data['url']}")
            
        # Display errors and warnings
        if result.errors:
            # Check if there's an unverified error
            has_unverified_error = any(e.get('error_type') == 'unverified' or e.get('warning_type') == 'unverified' or e.get('info_type') == 'unverified' for e in result.errors)
            
            if has_unverified_error:
                # Use the centralized unverified error display function from base checker
                self.base_checker._display_unverified_error_with_subreason(reference, result.url, result.errors, debug_mode=False, print_output=True)
            
            # Display all non-unverified errors and warnings
            for error in result.errors:
                if error.get('error_type') != 'unverified' and error.get('warning_type') != 'unverified' and error.get('info_type') != 'unverified':
                    error_type = error.get('error_type') or error.get('warning_type') or error.get('info_type')
                    error_details = error.get('error_details') or error.get('warning_details') or error.get('info_details', 'Unknown error')
                    
                    from refchecker.utils.error_utils import print_labeled_multiline

                    if error_type == 'arxiv_id':
                        # Keep existing style for arXiv ID errors
                        print(f"      ❌ {error_details}")
                    elif 'error_type' in error:
                        print_labeled_multiline("❌ Error", error_details)
                    elif 'warning_type' in error:
                        print_labeled_multiline("⚠️  Warning", error_details)
                    else:
                        print_labeled_multiline("ℹ️  Information", error_details)
        
        # Show timing info for slow references
        if result.processing_time > 5.0:
            logger.debug(f"Reference {result.index + 1} took {result.processing_time:.2f}s to verify: {title}")
            logger.debug(f"Raw text: {reference.get('raw_text', '')}")
    
    def _update_stats(self, result: ReferenceResult) -> None:
        """Update processing statistics."""
        self.processing_stats['total_processed'] += 1
        
        if result.errors:
            self.processing_stats['total_errors'] += len(result.errors)
        
        # Update timing stats
        proc_time = result.processing_time
        self.processing_stats['fastest_time'] = min(self.processing_stats['fastest_time'], proc_time)
        self.processing_stats['slowest_time'] = max(self.processing_stats['slowest_time'], proc_time)
        
        # Update average
        total = self.processing_stats['total_processed']
        current_avg = self.processing_stats['avg_processing_time']
        self.processing_stats['avg_processing_time'] = ((current_avg * (total - 1)) + proc_time) / total
    
    def _print_progress(self) -> None:
        """Print progress information."""
        # Progress printing disabled to avoid noise
        pass
    
    def _print_final_stats(self) -> None:
        """Print final processing statistics."""
        # Final stats printing disabled to avoid noise
        pass
    
    def _get_stats(self) -> Dict[str, Any]:
        """Get processing statistics."""
        total_time = time.time() - self.start_time if self.start_time > 0 else 0
        
        return {
            'total_references': self.total_references,
            'total_time': total_time,
            'references_per_second': self.total_references / total_time if total_time > 0 else 0,
            'total_errors': self.processing_stats['total_errors'],
            'avg_processing_time': self.processing_stats['avg_processing_time'],
            'fastest_time': self.processing_stats['fastest_time'] if self.processing_stats['fastest_time'] != float('inf') else 0,
            'slowest_time': self.processing_stats['slowest_time']
        }

