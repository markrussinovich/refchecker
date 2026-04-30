"""Bulk paper review pipeline.

Keeps multi-paper scheduling, batching, progress reporting, and aggregation
out of the single-paper CLI path.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence

from refchecker.core.hallucination_policy import apply_hallucination_verdict, build_hallucination_error_entry, pre_screen_hallucination, run_hallucination_check
from refchecker.utils.arxiv_utils import get_bibtex_content
from refchecker.utils.text_utils import detect_latex_bibliography_format, extract_latex_references

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from refchecker.core.refchecker import ArxivReferenceChecker


def _safe_print(*args, **kwargs) -> None:
    """Print that falls back to ascii+replace when stdout can't handle Unicode."""
    import sys
    try:
        print(*args, **kwargs, flush=True)
    except UnicodeEncodeError:
        text = ' '.join(str(a) for a in args)
        sys.stdout.buffer.write(text.encode('utf-8', errors='replace'))
        sys.stdout.buffer.write(b'\n')
        sys.stdout.buffer.flush()


def _safe_print_labeled(emoji: str, text: str) -> None:
    """Print a multi-line error/warning with an emoji label, Unicode-safe.

    Mirrors print_labeled_multiline from error_utils but uses _safe_print
    so bulk output never crashes on Windows cp1252 consoles.
    """
    prefix = f'      {emoji} '
    lines = (text or '').splitlines() or ['']
    _safe_print(prefix + lines[0])
    indent = ' ' * 15
    for line in lines[1:]:
        _safe_print(indent + line)


def _normalize_cache_key(reference: Dict[str, Any]) -> Optional[tuple]:
    """Build a normalized cache key from a reference dict.

    Returns (title_lower, first_author_last_lower, year_str) or None if
    the reference doesn't have enough information to cache reliably.
    """
    title = (reference.get('title') or '').strip().lower()
    if not title or len(title) < 15:
        return None

    # Normalize: collapse whitespace, strip punctuation at edges
    title = re.sub(r'\s+', ' ', title).strip(' .,;:')

    authors = reference.get('authors') or []
    first_author_last = ''
    if authors and isinstance(authors, list) and authors[0]:
        # Take last token of first author as surname proxy
        parts = str(authors[0]).strip().split()
        if parts:
            first_author_last = parts[-1].lower().strip(' .,;:')

    year = str(reference.get('year') or '').strip()

    return (title, first_author_last, year)


class BulkVerificationCache:
    """Thread-safe cross-paper cache for reference verification results.

    Keyed on normalized (title, first_author_last, year).  Stores the full
    (errors, url, verified_data) tuple so subsequent papers citing the same
    reference skip the API calls entirely.
    """

    def __init__(self) -> None:
        self._cache: Dict[tuple, Any] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, reference: Dict[str, Any]) -> Optional[Any]:
        key = _normalize_cache_key(reference)
        if key is None:
            return None
        with self._lock:
            if key in self._cache:
                self.hits += 1
                return self._cache[key]
            self.misses += 1
            return None

    def put(self, reference: Dict[str, Any], result: Any) -> None:
        key = _normalize_cache_key(reference)
        if key is None:
            return
        with self._lock:
            self._cache[key] = result

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def stats_line(self) -> str:
        with self._lock:
            total = self.hits + self.misses
            pct = f'{self.hits / total * 100:.0f}%' if total else '0%'
            return f'cache: {self.size} entries, {self.hits} hits / {total} lookups ({pct})'


@dataclass
class BulkPaperJob:
    index: int
    input_spec: str


@dataclass
class BulkPaperResult:
    index: int
    input_spec: str
    paper_id: str
    title: str
    source_url: str
    elapsed_seconds: float
    references_processed: int
    total_errors_found: int
    total_warnings_found: int
    total_info_found: int
    total_unverified_refs: int
    total_arxiv_refs: int
    total_non_arxiv_refs: int
    total_other_refs: int
    papers_with_errors: int
    papers_with_warnings: int
    papers_with_info: int
    errors: List[Dict[str, Any]] = field(default_factory=list)
    fatal_error: bool = False
    fatal_error_message: Optional[str] = None
    used_regex_extraction: bool = False
    used_unreliable_extraction: bool = False


def _get_checkpoint_path(report_file: Optional[str]) -> Optional[str]:
    """Return the checkpoint file path derived from the report file."""
    if not report_file:
        return None
    base, _ = os.path.splitext(report_file)
    return base + '.checkpoint.jsonl'


def _save_checkpoint(checkpoint_path: str, result: BulkPaperResult) -> None:
    """Append a completed result to the checkpoint file (JSONL)."""
    with open(checkpoint_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(asdict(result), ensure_ascii=False) + '\n')


def _load_checkpoint(
    checkpoint_path: str, input_specs: Sequence[str]
) -> Dict[int, BulkPaperResult]:
    """Load previously completed results from a checkpoint file.

    Only returns results whose input_spec matches the current run's
    input_specs at the same index, so stale checkpoints are ignored.
    """
    result_map: Dict[int, BulkPaperResult] = {}
    if not checkpoint_path or not os.path.exists(checkpoint_path):
        return result_map
    skipped = 0
    with open(checkpoint_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                idx = data['index']
                # Validate: same spec at same index
                if idx < len(input_specs) and data.get('input_spec') == input_specs[idx]:
                    result_map[idx] = BulkPaperResult(**data)
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                skipped += 1
                logger.warning('Skipping corrupt checkpoint entry at line %d: %s', line_num, exc)
    if skipped:
        logger.warning('Loaded %d entries from checkpoint, skipped %d corrupt entries', len(result_map), skipped)
    return result_map


@dataclass
class _BatchTask:
    payload: Any
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Optional[BaseException] = None

    def wait(self) -> Any:
        self.event.wait()
        if self.error is not None:
            raise self.error
        return self.result


class _QueueBatcher:
    def __init__(
        self,
        *,
        name: str,
        process_batch: Callable[[Sequence[Any]], Sequence[Any]],
        process_single: Callable[[Any], Any],
        max_batch_size: int,
        max_wait_seconds: float,
    ):
        self.name = name
        self._process_batch = process_batch
        self._process_single = process_single
        self._max_batch_size = max(1, max_batch_size)
        self._max_wait_seconds = max(0.01, max_wait_seconds)
        self._queue: Queue[Any] = Queue()
        self._sentinel = object()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, payload: Any) -> _BatchTask:
        task = _BatchTask(payload=payload)
        self._queue.put(task)
        return task

    def close(self) -> None:
        self._queue.put(self._sentinel)
        self._thread.join(timeout=10.0)
        if self._thread.is_alive():
            logger.warning('%s batcher thread did not shut down within 10s', self.name)

    def _run(self) -> None:
        pending: List[_BatchTask] = []
        shutdown = False

        while True:
            timeout = self._max_wait_seconds if pending else None
            try:
                item = self._queue.get(timeout=timeout)
            except Empty:
                item = None

            if item is self._sentinel:
                shutdown = True
            elif item is not None:
                pending.append(item)

            should_flush = shutdown or len(pending) >= self._max_batch_size or (item is None and pending)
            if should_flush and pending:
                self._flush(pending)
                pending = []

            if shutdown:
                break

    def _flush(self, pending: List[_BatchTask]) -> None:
        payloads = [task.payload for task in pending]
        try:
            results = list(self._process_batch(payloads))
            if len(results) != len(pending):
                raise ValueError(f'{self.name} returned {len(results)} results for {len(pending)} tasks')
            for task, result in zip(pending, results):
                task.result = result
                task.event.set()
            return
        except Exception as exc:
            logger.debug('%s batch processing failed, falling back to single item execution: %s', self.name, exc)

        for task in pending:
            try:
                task.result = self._process_single(task.payload)
            except Exception as exc:
                task.error = exc
            finally:
                task.event.set()


@dataclass
class _ExtractionPayload:
    checker: Any
    bibliography_text: str


class BulkLLMExtractionBatcher:
    def __init__(self, enabled: bool = True, max_batch_size: int = 5, max_wait_seconds: float = 0.3):
        self.enabled = enabled
        self._batcher: Optional[_QueueBatcher] = None
        if enabled:
            self._batcher = _QueueBatcher(
                name='BulkLLMExtractionBatcher',
                process_batch=self._process_batch,
                process_single=self._process_single,
                max_batch_size=max_batch_size,
                max_wait_seconds=max_wait_seconds,
            )

    def extract_references(self, checker: Any, bibliography_text: str) -> List[Dict[str, Any]]:
        if not self.enabled or self._batcher is None:
            return self._process_single(_ExtractionPayload(checker=checker, bibliography_text=bibliography_text))
        return self._batcher.submit(_ExtractionPayload(checker=checker, bibliography_text=bibliography_text)).wait()

    def close(self) -> None:
        if self._batcher is not None:
            self._batcher.close()

    def _process_single(self, payload: _ExtractionPayload) -> List[Dict[str, Any]]:
        checker = payload.checker
        extractor = checker.llm_extractor
        if not extractor:
            return []
        references = extractor.extract_references(payload.bibliography_text)
        if not references:
            return []
        return checker._process_llm_extracted_references(references)

    def _process_batch(self, payloads: Sequence[_ExtractionPayload]) -> Sequence[List[Dict[str, Any]]]:
        if len(payloads) == 1:
            return [self._process_single(payloads[0])]

        first_checker = payloads[0].checker
        extractor = first_checker.llm_extractor
        if not extractor or not getattr(extractor, 'llm_provider', None):
            raise RuntimeError('LLM extractor is not available for batched extraction')

        provider = extractor.llm_provider
        cleaned_texts: List[str] = []
        for payload in payloads:
            text = payload.bibliography_text
            cleaner = getattr(provider, '_clean_bibtex_for_llm', None)
            cleaned_texts.append(cleaner(text) if callable(cleaner) else text)

        prompt_items = []
        for index, text in enumerate(cleaned_texts):
            prompt_items.append(
                f'ITEM {index}\n<<<BIBLIOGRAPHY\n{text}\nBIBLIOGRAPHY>>>'
            )

        prompt = (
            'You are extracting references for multiple bibliography blocks in one request.\n'
            'Return ONLY valid JSON.\n'
            'The output must be a JSON array with one object per item.\n'
            'Each object must have exactly these keys: index, references.\n'
            'references must be an array of strings in this format: Author1*Author2#Title#Venue#Year#URL\n'
            'If an item has no valid references, return an empty array for that item.\n'
            'Do not omit items. Do not add commentary.\n\n'
            + '\n\n'.join(prompt_items)
        )

        response_text = provider._call_llm(prompt)
        try:
            parsed = _extract_json_payload(response_text)
        except Exception:
            return [self._process_single(payload) for payload in payloads]
        if not isinstance(parsed, list):
            return [self._process_single(payload) for payload in payloads]

        grouped: Dict[int, List[str]] = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get('index'))
            except (TypeError, ValueError):
                continue
            refs = item.get('references') or []
            grouped[index] = [str(ref) for ref in refs if ref]

        results: List[List[Dict[str, Any]]] = []
        for index, payload in enumerate(payloads):
            raw_refs = grouped.get(index, [])
            if raw_refs:
                results.append(payload.checker._process_llm_extracted_references(raw_refs))
            else:
                results.append(self._process_single(payload))
        return results


class AsyncHallucinationPool:
    """Thread-pool based hallucination assessment for non-blocking operation.

    This pool runs
    hallucination LLM calls concurrently via a ThreadPoolExecutor and returns
    futures that can be collected later — allowing paper workers to proceed
    to the next paper without waiting for hallucination results.
    """

    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix='HallucinationLLM',
        )

    def submit(self, error_entry: Dict[str, Any], llm_verifier: Any, web_searcher: Any) -> Any:
        """Submit a hallucination check.  Returns a concurrent.futures.Future."""
        return self._executor.submit(
            run_hallucination_check,
            error_entry,
            llm_client=llm_verifier,
            web_searcher=web_searcher,
        )

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)


def _print_bulk_reference_block(error_entry: Dict[str, Any], ref_idx: int, total_refs: int) -> None:
    """Print a single reference with errors in bulk mode, matching single-paper CLI format.

    ref_idx: 1-based index among error references for this paper.
    total_refs: total references in the paper (for context).
    """
    ref_title = error_entry.get('ref_title', 'Untitled')
    ref_authors = error_entry.get('ref_authors_cited', '')
    ref_year = error_entry.get('ref_year_cited', '')
    ref_url = error_entry.get('ref_url_cited', '')
    ref_venue = error_entry.get('ref_venue_cited', '')
    ref_verified_url = error_entry.get('ref_verified_url', '')

    # Reference header with simple [n] index
    _safe_print(f'   [{ref_idx}] {ref_title}')
    if ref_authors:
        _safe_print(f'       {ref_authors}')
    if ref_venue:
        _safe_print(f'       {ref_venue}')
    if ref_year:
        _safe_print(f'       {ref_year}')
    if ref_url:
        _safe_print(f'       {ref_url}')

    _safe_print('')
    ref_matched_database = error_entry.get('matched_database', '')
    if ref_matched_database:
        _safe_print(f'       Matched Database: {ref_matched_database}')
    if ref_verified_url:
        _safe_print(f'       Verified URL: {ref_verified_url}')

    # Use original per-error dicts when available (preserves error/warning/info type)
    original_errors = error_entry.get('_original_errors')
    if original_errors:
        has_unverified = any(
            e.get('error_type') == 'unverified'
            or e.get('warning_type') == 'unverified'
            or e.get('info_type') == 'unverified'
            for e in original_errors
        )
        if has_unverified:
            _safe_print(f'      ❓ Could not verify: {ref_title}')
            unverified_errs = [
                e for e in original_errors
                if e.get('error_type') == 'unverified'
                   or e.get('warning_type') == 'unverified'
                   or e.get('info_type') == 'unverified'
            ]
            if unverified_errs:
                detail = (unverified_errs[0].get('error_details')
                          or unverified_errs[0].get('warning_details')
                          or unverified_errs[0].get('info_details', ''))
                if detail:
                    _safe_print(f'         Subreason: {detail}')

        for error in original_errors:
            if (error.get('error_type') == 'unverified'
                    or error.get('warning_type') == 'unverified'
                    or error.get('info_type') == 'unverified'):
                continue
            error_details = (error.get('error_details')
                             or error.get('warning_details')
                             or error.get('info_details', 'Unknown error'))
            if 'error_type' in error:
                _safe_print_labeled('❌', error_details)
            elif 'warning_type' in error:
                _safe_print_labeled('⚠️ ', error_details)
            else:
                _safe_print_labeled('ℹ️ ', error_details)
    else:
        # Fallback for entries without original errors (legacy / single-error)
        error_type = error_entry.get('error_type', '')
        error_details = error_entry.get('error_details', '')
        if error_type == 'unverified':
            _safe_print(f'      ❓ Could not verify: {ref_title}')
            if error_details:
                _safe_print(f'         Subreason: {error_details}')
        elif error_details:
            _safe_print_labeled('❌', error_details)

    # Hallucination flag (only shown for LIKELY)
    assessment = error_entry.get('hallucination_assessment', {})
    if assessment.get('verdict') == 'LIKELY':
        explanation = assessment.get('explanation', '')
        _safe_print(f'      🚩 Likely hallucinated: {explanation}')


class BulkProgressReporter:
    def __init__(self, total_papers: int):
        self.total_papers = total_papers
        self.completed_papers = 0
        self.total_references = 0
        self.total_errors = 0
        self.total_warnings = 0
        self.total_info = 0
        self.total_unverified = 0
        self._lock = threading.Lock()

    def report(self, result: BulkPaperResult) -> None:
        with self._lock:
            self.completed_papers += 1
            self.total_references += result.references_processed
            self.total_errors += result.total_errors_found
            self.total_warnings += result.total_warnings_found
            self.total_info += result.total_info_found
            self.total_unverified += result.total_unverified_refs

            # Paper ID is 1-based start order (result.index is 0-based)
            paper_id = result.index + 1

            # ── Paper header ──
            display_title = result.input_spec or result.paper_id or result.title
            _safe_print(f'\n📄 {dt.datetime.now().strftime("%H:%M:%S")} [{paper_id}/{self.total_papers}] {display_title}')
            if result.source_url and result.source_url != display_title:
                _safe_print(f'   {result.source_url}')

            # ── Paper stats ──
            flagged_entries = [
                e for e in result.errors
                if e.get('hallucination_assessment', {}).get('verdict') == 'LIKELY'
            ]
            flagged_count = len(flagged_entries)
            paper_unverified = max(result.total_unverified_refs, flagged_count)
            elapsed = f'{result.elapsed_seconds:.0f}s'
            flag_note = f' hallucinated={flagged_count}' if flagged_count else ''
            _safe_print(
                f'   refs={result.references_processed} '
                f'errors={result.total_errors_found} warnings={result.total_warnings_found} '
                f'info={result.total_info_found} unverified={paper_unverified}'
                f'{flag_note} '
                f'({elapsed})'
            )

            # ── Show all references with errors/warnings ──
            for ref_idx, error_entry in enumerate(result.errors, 1):
                _safe_print('')
                _print_bulk_reference_block(error_entry, ref_idx, result.references_processed)

            # ── Running totals ──
            _safe_print(
                f'   Totals: refs={self.total_references} '
                f'errors={self.total_errors} warnings={self.total_warnings} '
                f'info={self.total_info} unverified={self.total_unverified}'
            )


@dataclass
class _BulkCheckerConfig:
    checker_cls: type
    semantic_scholar_api_key: Optional[str]
    db_path: Optional[str]
    llm_config: Optional[Dict[str, Any]]
    debug_mode: bool
    enable_parallel: bool
    max_workers: int
    report_format: str
    cache_dir: Optional[str]

    @classmethod
    def from_checker(cls, checker: Any) -> '_BulkCheckerConfig':
        return cls(
            checker_cls=checker.__class__,
            semantic_scholar_api_key=getattr(checker, 'semantic_scholar_api_key', None),
            db_path=getattr(checker, 'db_path', None),
            llm_config=getattr(checker, 'llm_config_override', None),
            debug_mode=getattr(checker, 'debug_mode', False),
            enable_parallel=getattr(checker, 'enable_parallel', True),
            max_workers=getattr(checker, 'max_workers', 4),
            report_format=getattr(checker, 'report_format', 'json'),
            cache_dir=getattr(checker, 'cache_dir', None),
        )

    def create_worker_checker(self) -> Any:
        return self.checker_cls(
            semantic_scholar_api_key=self.semantic_scholar_api_key,
            db_path=self.db_path,
            output_file=None,
            llm_config=self.llm_config,
            debug_mode=self.debug_mode,
            enable_parallel=self.enable_parallel,
            max_workers=self.max_workers,
            report_file=None,
            report_format=self.report_format,
            cache_dir=self.cache_dir,
        )


def run_bulk_paper_check(root_checker: Any, input_specs: Sequence[str], debug_mode: bool = False) -> None:
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_specs: list[str] = []
    for spec in input_specs:
        normalised = spec.strip()
        if normalised not in seen:
            seen.add(normalised)
            unique_specs.append(normalised)
    dropped = len(input_specs) - len(unique_specs)
    input_specs = unique_specs

    config = _BulkCheckerConfig.from_checker(root_checker)

    # Suppress INFO and WARNING logging in bulk mode to keep output clean.
    # Only errors and paper-level progress lines are printed.
    if not debug_mode:
        logging.getLogger().setLevel(logging.ERROR)

    _safe_print(f'\nBulk check: {len(input_specs)} papers queued' + (f' ({dropped} duplicate(s) removed)' if dropped else ''))

    # --- Resume support: load checkpoint if available ---
    checkpoint_path = _get_checkpoint_path(getattr(root_checker, 'report_file', None))
    result_map: Dict[int, BulkPaperResult] = {}
    if checkpoint_path:
        result_map = _load_checkpoint(checkpoint_path, input_specs)
        if result_map:
            _safe_print(f'♻️  Resuming: {len(result_map)}/{len(input_specs)} papers already completed (checkpoint: {os.path.basename(checkpoint_path)})')

    reporter = BulkProgressReporter(total_papers=len(input_specs))
    # Fast-forward reporter counts for already-completed papers
    for prev_result in result_map.values():
        reporter.completed_papers += 1
        reporter.total_references += prev_result.references_processed
        reporter.total_errors += prev_result.total_errors_found
        reporter.total_warnings += prev_result.total_warnings_found
        reporter.total_info += prev_result.total_info_found
        reporter.total_unverified += prev_result.total_unverified_refs
    extraction_batcher = BulkLLMExtractionBatcher(enabled=bool(getattr(root_checker, 'llm_enabled', False)))
    hallucination_pool = AsyncHallucinationPool(max_workers=4)
    verification_cache = BulkVerificationCache()
    job_queue: Queue[Any] = Queue()
    result_queue: Queue[tuple] = Queue()

    remaining = 0
    for index, input_spec in enumerate(input_specs):
        if index not in result_map:
            job_queue.put(BulkPaperJob(index=index, input_spec=input_spec))
            remaining += 1

    if remaining == 0:
        _safe_print('All papers already completed in checkpoint. Generating final report.')

    if remaining > 0:
        # Process up to 3 papers concurrently. Higher values cause API rate-limit
        # contention that negates the parallelism benefit. 3 workers provide good
        # I/O overlap while keeping API call rates within limits.
        paper_worker_count = min(6, remaining)
        # Per-API semaphores inside EnhancedHybridChecker now handle rate limiting
        # independently for each API, so we no longer need a global semaphore.
        for _ in range(paper_worker_count):
            job_queue.put(None)

        def worker() -> None:
            checker = config.create_worker_checker()
            while True:
                job = job_queue.get()
                try:
                    if job is None:
                        return
                    _safe_print(f'⏳ {dt.datetime.now().strftime("%H:%M:%S")} [{job.index + 1}/{len(input_specs)}] Starting: {job.input_spec}')
                    try:
                        result, pending_halluc = _process_bulk_paper_job(
                            checker=checker,
                            job=job,
                            debug_mode=debug_mode,
                            extraction_batcher=extraction_batcher,
                            hallucination_pool=hallucination_pool,
                            verification_cache=verification_cache,
                        )
                    except Exception as exc:
                        logger.error('Unhandled exception in bulk worker for %s: %s', job.input_spec, exc)
                        _reset_worker_state(checker)
                        checker.fatal_error = True
                        checker.fatal_error_message = str(exc)
                        result = _build_bulk_result(checker, job, job.input_spec, job.input_spec, time.perf_counter())
                        pending_halluc = []
                    result_queue.put((result, pending_halluc))
                finally:
                    job_queue.task_done()

        threads = [threading.Thread(target=worker, name=f'BulkPaperWorker-{index + 1}', daemon=True) for index in range(paper_worker_count)]
        for thread in threads:
            thread.start()

        completed = 0
        while completed < remaining:
            result, pending_halluc = result_queue.get()
            # Finalize hallucination assessments (waits for pending LLM
            # futures) before reporting.  While we wait here, worker
            # threads are already verifying the next paper.
            _finalize_hallucination_on_result(result, pending_halluc)
            result_map[result.index] = result
            reporter.report(result)
            # Save to checkpoint incrementally
            if checkpoint_path:
                _save_checkpoint(checkpoint_path, result)
            completed += 1

        job_queue.join()
        # Worker threads should have finished by now; use a generous
        # timeout as a safety net so we never hang indefinitely.
        for thread in threads:
            thread.join(timeout=30.0)
    extraction_batcher.close()
    hallucination_pool.shutdown(wait=True)

    # Cache stats (use raw attributes to avoid lock contention with daemon threads)
    if verification_cache.hits > 0 or len(verification_cache._cache) > 0:
        total = verification_cache.hits + verification_cache.misses
        pct = f'{verification_cache.hits / total * 100:.0f}%' if total else '0%'
        _safe_print(
            f'   Reference cache: {len(verification_cache._cache)} entries, '
            f'{verification_cache.hits} hits / {total} lookups ({pct})'
        )

    ordered_results = [result_map[index] for index in sorted(result_map)]
    _apply_bulk_results(root_checker, ordered_results)
    _print_bulk_final_summary(root_checker)
    root_checker.write_all_errors_to_file()
    if root_checker.report_file:
        payload = root_checker._build_structured_report_payload()
        root_checker.write_structured_report(payload=payload)

    # Remove checkpoint file on successful completion unless a caller wants to
    # preserve it as an incremental corpus artifact.
    if checkpoint_path and os.getenv('REFCHECKER_KEEP_CHECKPOINT'):
        _safe_print(f'Checkpoint file kept: {os.path.basename(checkpoint_path)}')
    elif checkpoint_path and os.path.exists(checkpoint_path):
        try:
            os.remove(checkpoint_path)
            _safe_print(f'Checkpoint file removed: {os.path.basename(checkpoint_path)}')
        except OSError:
            pass


def _process_bulk_paper_job(
    *,
    checker: Any,
    job: BulkPaperJob,
    debug_mode: bool,
    extraction_batcher: BulkLLMExtractionBatcher,
    hallucination_pool: AsyncHallucinationPool,
    verification_cache: BulkVerificationCache,
) -> tuple:
    start_time = time.perf_counter()
    _reset_worker_state(checker)

    paper = None
    paper_id = ''
    title = ''
    try:
        from refchecker.core.refchecker import resolve_input_spec

        resolved_paper_id, local_path = resolve_input_spec(job.input_spec)
        if resolved_paper_id:
            paper = checker.get_paper_metadata(resolved_paper_id)
            if not paper:
                checker.fatal_error = True
                checker.fatal_error_message = f'Could not find paper with ID: {resolved_paper_id}'
                paper_id = resolved_paper_id
                title = resolved_paper_id
                return _build_bulk_result(checker, job, paper_id, title, start_time), []
        else:
            paper = checker._create_local_file_paper(local_path)

        paper._input_spec = job.input_spec
        paper_id = paper.get_short_id()
        title = getattr(paper, 'title', '') or paper_id or job.input_spec
        source_url = checker._get_source_paper_url(paper) if hasattr(checker, '_get_source_paper_url') else job.input_spec

        phase_times: Dict[str, float] = {}
        _t = time.perf_counter()

        # Check bibliography cache
        from refchecker.utils.cache_utils import cached_bibliography, cache_bibliography, llm_cache_identity_from_extractor
        llm_cache_identity = llm_cache_identity_from_extractor(checker.llm_extractor)
        bibliography = cached_bibliography(checker.cache_dir, job.input_spec, llm_cache_identity)
        if bibliography is not None:
            phase_times['extract_bib'] = time.perf_counter() - _t
        else:
            bibliography = extract_bibliography_bulk(checker, paper, debug_mode=debug_mode, extraction_batcher=extraction_batcher)
            cache_bibliography(checker.cache_dir, job.input_spec, bibliography, llm_cache_identity)
            phase_times['extract_bib'] = time.perf_counter() - _t
        if checker.fatal_error:
            return _build_bulk_result(checker, job, paper_id, title, start_time, source_url=source_url), []

        if len(bibliography) > 1:
            bibliography = checker._deduplicate_bibliography_entries(bibliography)

        checker.total_papers_processed = 1
        checker.total_references_processed = len(bibliography)
        checker.total_arxiv_refs = sum(1 for ref in bibliography if ref.get('type') == 'arxiv')
        checker.total_non_arxiv_refs = sum(1 for ref in bibliography if ref.get('type') == 'non-arxiv')
        checker.total_other_refs = sum(1 for ref in bibliography if ref.get('type') == 'other')

        _t = time.perf_counter()
        checker.batch_prefetch_arxiv_references(bibliography)
        phase_times['prefetch_arxiv'] = time.perf_counter() - _t

        _t = time.perf_counter()
        _batch_prefetch_ss_metadata(bibliography, checker, verification_cache)
        phase_times['prefetch_ss'] = time.perf_counter() - _t

        _t = time.perf_counter()
        _verify_bibliography_silent(checker, paper, bibliography, debug_mode=debug_mode, verification_cache=verification_cache)
        phase_times['verify_refs'] = time.perf_counter() - _t

        _t = time.perf_counter()
        pending_halluc = _submit_hallucination_assessments_async(checker, hallucination_pool)
        phase_times['hallucination_submit'] = time.perf_counter() - _t
        # Hallucination LLM calls run concurrently in the pool.  The
        # main loop will wait for and apply results before reporting.

        # Print phase timing and API stats for this paper
        total_elapsed = time.perf_counter() - start_time
        phase_times['total'] = total_elapsed
        hybrid_checker = getattr(checker, 'non_arxiv_checker', None)
        api_stats = getattr(hybrid_checker, 'api_stats', {}) if hybrid_checker else {}
        _safe_print(f'   ⏱️  PHASE TIMING [{paper_id}] ({len(bibliography)} refs):')
        for phase, dur in phase_times.items():
            pct = dur / total_elapsed * 100 if total_elapsed > 0 else 0
            _safe_print(f'      {phase:<20s} {dur:>7.1f}s  ({pct:>5.1f}%)')
        if api_stats:
            _safe_print(f'   📊 API STATS [{paper_id}]:')
            for api_name, stats in sorted(api_stats.items()):
                total = stats['success'] + stats['failure']
                if total > 0:
                    cum_time = getattr(hybrid_checker, '_api_total_time', {}).get(api_name, 0)
                    sem_wait = getattr(hybrid_checker, '_api_sem_wait_time', {}).get(api_name, 0)
                    _safe_print(
                        f'      {api_name:<20s} ok={stats["success"]:<4d} fail={stats["failure"]:<4d} '
                        f'throttled={stats["throttled"]:<3d} avg={stats["avg_time"]:.2f}s '
                        f'total_calls={total} cum_time={cum_time:.1f}s sem_wait={sem_wait:.1f}s'
                    )
            retry_sleep = getattr(hybrid_checker, '_api_retry_sleep_time', 0)
            if retry_sleep > 0:
                _safe_print(f'      {"retry_sleep":<20s} {retry_sleep:.1f}s (cumulative across all threads)')

        actual_errors = checker.total_errors_found
        warnings = checker.total_warnings_found
        info = checker.total_info_found
        checker.papers_with_errors = 1 if actual_errors else 0
        checker.papers_with_warnings = 1 if warnings else 0
        checker.papers_with_info = 1 if info else 0
        result = _build_bulk_result(checker, job, paper_id, title, start_time, source_url=source_url)
        return result, pending_halluc
    except Exception as exc:
        logger.error('Bulk paper job failed for %s: %s', job.input_spec, exc)
        checker.fatal_error = True
        checker.fatal_error_message = str(exc)
        return _build_bulk_result(checker, job, paper_id or job.input_spec, title or job.input_spec, start_time), []


def _build_bulk_result(checker: Any, job: BulkPaperJob, paper_id: str, title: str, start_time: float, source_url: str = '') -> BulkPaperResult:
    elapsed = time.perf_counter() - start_time
    return BulkPaperResult(
        index=job.index,
        input_spec=job.input_spec,
        paper_id=paper_id,
        title=title,
        source_url=source_url or job.input_spec,
        elapsed_seconds=elapsed,
        references_processed=checker.total_references_processed,
        total_errors_found=checker.total_errors_found,
        total_warnings_found=checker.total_warnings_found,
        total_info_found=checker.total_info_found,
        total_unverified_refs=checker.total_unverified_refs,
        total_arxiv_refs=checker.total_arxiv_refs,
        total_non_arxiv_refs=checker.total_non_arxiv_refs,
        total_other_refs=checker.total_other_refs,
        papers_with_errors=checker.papers_with_errors,
        papers_with_warnings=checker.papers_with_warnings,
        papers_with_info=checker.papers_with_info,
        errors=list(checker.errors),
        fatal_error=checker.fatal_error,
        fatal_error_message=checker.fatal_error_message,
        used_regex_extraction=checker.used_regex_extraction,
        used_unreliable_extraction=checker.used_unreliable_extraction,
    )


def _reset_worker_state(checker: Any) -> None:
    checker.fatal_error = False
    checker.fatal_error_message = None
    checker.last_download_error = None
    checker.total_papers_processed = 0
    checker.total_references_processed = 0
    checker.papers_with_errors = 0
    checker.papers_with_warnings = 0
    checker.papers_with_info = 0
    checker.total_errors_found = 0
    checker.total_warnings_found = 0
    checker.total_info_found = 0
    checker.total_arxiv_refs = 0
    checker.total_non_arxiv_refs = 0
    checker.total_other_refs = 0
    checker.total_unverified_refs = 0
    checker.used_regex_extraction = False
    checker.used_unreliable_extraction = False
    checker.errors = []
    checker.single_paper_mode = False
    checker.current_paper_info = None


def extract_bibliography_bulk(checker: Any, paper: Any, debug_mode: bool, extraction_batcher: BulkLLMExtractionBatcher) -> List[Dict[str, Any]]:
    paper_id = paper.get_short_id()
    logger.debug('Bulk extracting bibliography for paper %s: %s', paper_id, getattr(paper, 'title', ''))

    bibtex_content = get_bibtex_content(paper)
    if bibtex_content:
        return parse_references_bulk(checker, bibtex_content, extraction_batcher)

    if hasattr(paper, 'is_text_refs') and paper.is_text_refs:
        try:
            with open(paper.file_path, 'r', encoding='utf-8') as handle:
                bibliography_text = handle.read()
            return parse_references_bulk(checker, bibliography_text, extraction_batcher)
        except Exception as exc:
            checker._set_fatal_source_error(paper, f'Failed to read text file ({exc})', debug_mode=debug_mode)
            return []

    if hasattr(paper, 'is_latex') and paper.is_latex:
        text = checker.extract_text_from_latex(paper.file_path)
        latex_format = detect_latex_bibliography_format(text)
        if latex_format['is_latex']:
            latex_references = extract_latex_references(text, paper.file_path)
            if latex_references:
                return latex_references
    elif hasattr(paper, 'is_bibtex') and paper.is_bibtex:
        try:
            with open(paper.file_path, 'r', encoding='utf-8', errors='ignore') as handle:
                bib_content = handle.read()
            return extract_latex_references(bib_content, paper.file_path)
        except Exception as exc:
            checker._set_fatal_source_error(paper, f'Failed to read BibTeX file ({exc})', debug_mode=debug_mode)
            return []
    else:
        pdf_content = checker.download_pdf(paper)
        if not pdf_content:
            checker._set_fatal_source_error(
                paper,
                checker.last_download_error or 'Could not download PDF content',
                debug_mode=debug_mode,
            )
            return []
        text = checker.extract_text_from_pdf(pdf_content)

    if not text:
        checker._set_fatal_source_error(
            paper,
            f"Could not extract text from {'LaTeX' if hasattr(paper, 'is_latex') and paper.is_latex else 'PDF'} source",
            debug_mode=debug_mode,
        )
        return []

    bibliography_text = checker.find_bibliography_section(text)
    if not bibliography_text:
        # If bibliography not found, try pdftotext as fallback (handles garbled pypdf output)
        if hasattr(paper, 'file_path') and paper.file_path:
            try:
                import subprocess, tempfile, os as _os
                pdf_path = paper.file_path
                if not _os.path.exists(pdf_path):
                    # If it's a URL-based paper, we need to save pdf_content to disk
                    if pdf_content:
                        pdf_content.seek(0)
                        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                            tmp.write(pdf_content.read())
                            pdf_path = tmp.name
                result = subprocess.run(['pdftotext', pdf_path, '-'], capture_output=True, text=True, timeout=60)
                if pdf_path != paper.file_path:
                    _os.unlink(pdf_path)
                if result.returncode == 0 and result.stdout.strip():
                    logger.info("Retrying bibliography extraction with pdftotext fallback")
                    bibliography_text = checker.find_bibliography_section(result.stdout)
            except Exception as e:
                logger.debug(f"pdftotext fallback failed: {e}")
        # Also try for URL-based papers where pdf_content is available
        if not bibliography_text and pdf_content:
            try:
                import subprocess, tempfile, os as _os
                pdf_content.seek(0)
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                    tmp.write(pdf_content.read())
                    tmp_path = tmp.name
                result = subprocess.run(['pdftotext', tmp_path, '-'], capture_output=True, text=True, timeout=60)
                _os.unlink(tmp_path)
                if result.returncode == 0 and result.stdout.strip():
                    logger.info("Retrying bibliography extraction with pdftotext fallback (from pdf_content)")
                    bibliography_text = checker.find_bibliography_section(result.stdout)
            except Exception as e:
                logger.debug(f"pdftotext fallback from pdf_content failed: {e}")
    if not bibliography_text:
        source_url = checker._get_source_paper_url(paper) if hasattr(checker, '_get_source_paper_url') else paper_id
        _set_reference_extraction_fatal(
            checker,
            'Could not locate a bibliography/references section in the source paper '
            f'(paper_id={paper_id}, source_url={source_url}, extracted_text_chars={len(text or "")}). '
            'PDF text extraction and pdftotext fallback did not produce a recognizable bibliography section.',
        )
        return []
    references = parse_references_bulk(checker, bibliography_text, extraction_batcher)
    if references or checker.llm_extractor:
        return references

    try:
        from refchecker.utils.grobid import extract_pdf_references_with_grobid_fallback

        pdf_path = getattr(paper, 'file_path', None)
        if not pdf_path or not os.path.exists(pdf_path):
            pdf_path = None
        grobid_references, _ = extract_pdf_references_with_grobid_fallback(
            pdf_path=pdf_path,
            pdf_content=pdf_content,
            llm_available=False,
            failure_message=(
                'No LLM configured for PDF reference extraction; falling back to GROBID.'
            ),
        )
        if grobid_references:
            checker.fatal_error = False
            checker.fatal_error_message = None
            return grobid_references
    except Exception as exc:
        logger.debug('GROBID fallback failed for %s: %s', paper_id, exc)

    return references


def parse_references_bulk(checker: Any, bibliography_text: str, extraction_batcher: BulkLLMExtractionBatcher) -> List[Dict[str, Any]]:
    if not bibliography_text:
        _set_reference_extraction_fatal(
            checker,
            'Reference extraction failed because no bibliography text was available',
        )
        return []

    if checker.llm_extractor:
        references = extraction_batcher.extract_references(checker, bibliography_text)
        if references:
            return references
        _set_reference_extraction_fatal(
            checker,
            _zero_reference_message(bibliography_text, 'LLM extraction'),
        )
        return []

    _set_reference_extraction_fatal(
        checker,
        'Reference extraction failed because no LLM extractor is configured '
        f'(bibliography_text_chars={len(bibliography_text)}). Configure an LLM extractor or use GROBID fallback for PDF inputs.',
    )
    return []


def _zero_reference_message(bibliography_text: str, method: str) -> str:
    return (
        f'Reference extraction produced zero references using {method} '
        f'(bibliography_text_chars={len(bibliography_text)}). '
        'The bibliography section was found, but no parser output could be converted into references.'
    )


def _set_reference_extraction_fatal(checker: Any, message: str) -> None:
    checker.fatal_error = True
    checker.fatal_error_message = message
    logger.error(message)


_SS_BATCH_URL = 'https://api.semanticscholar.org/graph/v1/paper/batch'
_SS_BATCH_FIELDS = 'title,authors,year,externalIds,url,abstract,openAccessPdf,isOpenAccess,venue,publicationVenue,journal'
_SS_BATCH_MAX = 500  # API limit


def _extract_ss_id(reference: Dict[str, Any]) -> Optional[str]:
    """Extract a Semantic Scholar batch-compatible ID from a reference.

    Returns 'ARXIV:xxxx.xxxxx' or 'DOI:10.xxx/yyy' if the reference has
    a usable identifier, otherwise None.
    """
    # Try ArXiv ID from URL
    url = reference.get('url', '')
    if url:
        import re as _re
        arxiv_match = _re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})', url, _re.IGNORECASE)
        if arxiv_match:
            return f'ARXIV:{arxiv_match.group(1)}'

    # Try DOI
    doi = reference.get('doi', '')
    if doi:
        clean = doi.strip()
        if clean.startswith('http'):
            from refchecker.utils.doi_utils import extract_doi_from_url
            clean = extract_doi_from_url(clean) or ''
        from refchecker.utils.doi_utils import is_valid_doi_format
        if clean and clean.startswith('10.') and is_valid_doi_format(clean):
            return f'DOI:{clean}'

    return None


def _batch_prefetch_ss_metadata(
    bibliography: Sequence[Dict[str, Any]],
    checker: Any,
    verification_cache: Optional[BulkVerificationCache],
) -> int:
    """Resolve DOI / ArXiv ID references via the SS batch API.

    For each reference with a known ID, fetches metadata in a single batch
    call and runs the checker's comparison logic to produce the same
    (errors, url, verified_data) tuple that verify_reference would return.
    Results are injected into the verification_cache so the normal
    verification loop skips these references entirely.

    When a local Semantic Scholar database is configured, the batch API is
    skipped — the local DB is faster, offline, and produces results
    consistent with the single-paper CLI and WebUI paths.

    Returns the number of references successfully pre-resolved.
    """
    if verification_cache is None:
        return 0

    # Skip batch API when a local DB is available — let verify_reference
    # use the local DB so results are consistent across all modes.
    if getattr(checker, 'db_path', None):
        logger.debug('Skipping SS batch prefetch — local DB is configured')
        return 0

    # Collect batch-eligible references
    id_map: Dict[int, str] = {}  # index -> SS ID
    for index, ref in enumerate(bibliography):
        # Skip if already cached
        if verification_cache.get(ref) is not None:
            continue
        ss_id = _extract_ss_id(ref)
        if ss_id:
            id_map[index] = ss_id

    if not id_map:
        return 0

    # Build headers
    headers: Dict[str, str] = {}
    ss_api_key = os.getenv('SEMANTIC_SCHOLAR_API_KEY')
    if ss_api_key:
        headers['x-api-key'] = ss_api_key

    # Batch request (respect 500-ID limit)
    indices = list(id_map.keys())
    resolved = 0

    for batch_start in range(0, len(indices), _SS_BATCH_MAX):
        batch_indices = indices[batch_start:batch_start + _SS_BATCH_MAX]
        batch_ids = [id_map[i] for i in batch_indices]

        try:
            import requests as _requests
            resp = _requests.post(
                _SS_BATCH_URL,
                params={'fields': _SS_BATCH_FIELDS},
                json={'ids': batch_ids},
                headers=headers,
                timeout=30,
            )
            if resp.status_code != 200:
                logger.debug('SS batch prefetch failed: HTTP %d', resp.status_code)
                continue

            results = resp.json()
            if not isinstance(results, list) or len(results) != len(batch_indices):
                logger.debug('SS batch prefetch returned unexpected shape')
                continue

            for idx, paper_data in zip(batch_indices, results):
                if paper_data is None:
                    continue  # Not found — let normal verification handle it

                ref = bibliography[idx]
                # Run the checker's comparison logic against the batch result
                try:
                    errors = _compare_reference_with_ss_data(checker, ref, paper_data)
                    # Build paper URL from SS data
                    paper_url = None
                    if paper_data.get('url'):
                        paper_url = paper_data['url']
                    elif paper_data.get('paperId'):
                        from refchecker.utils.url_utils import construct_semantic_scholar_url
                        paper_url = construct_semantic_scholar_url(paper_data['paperId'])

                    result_tuple = (errors if errors else None, paper_url, paper_data)
                    verification_cache.put(ref, result_tuple)
                    resolved += 1
                except Exception as exc:
                    logger.debug('SS batch comparison failed for index %d: %s', idx, exc)

        except Exception as exc:
            logger.debug('SS batch prefetch request failed: %s', exc)

    if resolved:
        logger.debug('SS batch prefetch resolved %d/%d references', resolved, len(id_map))

    return resolved


def _compare_reference_with_ss_data(checker: Any, reference: Dict[str, Any], paper_data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Compare a reference against SS batch data and return errors list.

    Uses the same comparison logic as the existing checkers but operates
    on pre-fetched data instead of making API calls.
    """
    from refchecker.utils.text_utils import calculate_title_similarity, compare_authors, strip_latex_commands
    from refchecker.utils.error_utils import validate_year

    errors: List[Dict[str, Any]] = []

    # Title comparison
    cited_title = strip_latex_commands(reference.get('title', '')).strip().lower()
    actual_title = (paper_data.get('title') or '').strip().lower()
    if cited_title and actual_title:
        similarity = calculate_title_similarity(cited_title, actual_title)
        if similarity < 0.8:
            errors.append({
                'error_type': 'title',
                'error_details': f"Title mismatch:\n       cited:  {reference.get('title', '')}\n       actual: {paper_data.get('title', '')}",
                'ref_title_correct': paper_data.get('title', ''),
            })

    # Author comparison
    cited_authors = reference.get('authors', [])
    actual_authors = paper_data.get('authors', [])
    if cited_authors and actual_authors:
        author_dicts = [{'name': a.get('name', '')} for a in actual_authors if a.get('name')]
        match_result, error_msg = compare_authors(cited_authors, author_dicts)
        if not match_result and error_msg:
            correct_authors = ', '.join(a.get('name', '') for a in actual_authors[:5])
            if len(actual_authors) > 5:
                correct_authors += ' et al.'
            errors.append({
                'error_type': 'author',
                'error_details': error_msg,
                'ref_authors_correct': correct_authors,
            })

    # Year comparison
    cited_year = reference.get('year')
    actual_year = paper_data.get('year')
    year_warning = validate_year(cited_year=cited_year, paper_year=actual_year, year_tolerance=1)
    if year_warning:
        errors.append(year_warning)

    # Venue check (info-level: cite as arXiv but published at venue)
    actual_venue = paper_data.get('venue', '')
    cited_venue = (reference.get('venue', '') or reference.get('journal', '')).strip().lower()
    if actual_venue and (not cited_venue or cited_venue in ('arxiv', 'arxiv preprint', 'arxiv.org', 'preprint')):
        actual_venue_lower = actual_venue.lower().strip()
        if actual_venue_lower and actual_venue_lower not in ('arxiv', 'arxiv.org', 'preprint', '') and not actual_venue_lower.startswith('arxiv'):
            errors.append({
                'warning_type': 'venue',
                'warning_details': f"Paper was published at venue but cited as arXiv preprint:\n       cited:  arXiv\n       actual: {actual_venue}",
                'ref_venue_correct': actual_venue,
            })

    # ArXiv ID check
    arxiv_errors = checker.check_independent_arxiv_id_mismatch(reference, paper_data)
    if arxiv_errors:
        errors.extend(arxiv_errors)

    # URL info
    external_ids = paper_data.get('externalIds', {})
    cited_url = reference.get('url', '')
    if cited_url and external_ids.get('ArXiv'):
        # Don't add URL info if ArXiv ID already matched
        pass
    elif not cited_url and external_ids.get('ArXiv'):
        arxiv_url = f"https://arxiv.org/abs/{external_ids['ArXiv']}"
        errors.append({
            'info_type': 'url',
            'info_details': f"Reference could include arXiv URL: {arxiv_url}",
            'ref_url_correct': arxiv_url,
        })

    return errors if errors else None


def _verify_bibliography_silent(checker: Any, paper: Any, bibliography: Sequence[Dict[str, Any]], debug_mode: bool, verification_cache: Optional[BulkVerificationCache] = None) -> None:
    paper_errors: List[Dict[str, Any]] = []
    if not bibliography:
        return

    # No global semaphore needed — per-API semaphores inside
    # EnhancedHybridChecker limit concurrent calls to each API independently,
    # so a 429 backoff on one API doesn't block calls to other APIs.
    def _verify_ref(paper_obj: Any, ref: Dict[str, Any]) -> Any:
        return checker.verify_reference(paper_obj, ref)

    # Split references into cached hits and uncached misses
    cached_results: Dict[int, Any] = {}
    uncached_indices: List[int] = []
    for index, reference in enumerate(bibliography):
        if verification_cache is not None:
            cached = verification_cache.get(reference)
            if cached is not None:
                cached_results[index] = cached
                continue
        uncached_indices.append(index)

    # Verify only uncached references
    fresh_results: Dict[int, Any] = {}
    if uncached_indices:
        uncached_refs = [(index, bibliography[index]) for index in uncached_indices]
        if checker.enable_parallel and len(uncached_refs) > 1:
            with ThreadPoolExecutor(max_workers=checker.max_workers, thread_name_prefix='BulkReference') as executor:
                future_map = {
                    executor.submit(_verify_ref, paper, ref): idx
                    for idx, ref in uncached_refs
                }
                for future in as_completed(future_map):
                    idx = future_map[future]
                    try:
                        fresh_results[idx] = future.result()
                    except Exception as exc:
                        logger.error('Reference %d verification failed: %s', idx, exc)
                        fresh_results[idx] = ([{'error_type': 'processing_failed', 'error_details': f'Internal error: {exc}'}], None, None)
        else:
            for idx, ref in uncached_refs:
                fresh_results[idx] = _verify_ref(paper, ref)

        # Store fresh results in cache
        if verification_cache is not None:
            for idx, ref in uncached_refs:
                if idx in fresh_results:
                    verification_cache.put(ref, fresh_results[idx])

    # Merge cached + fresh in original order
    ordered_results = []
    for index in range(len(bibliography)):
        if index in cached_results:
            ordered_results.append(cached_results[index])
        else:
            ordered_results.append(fresh_results[index])

    for reference, result in zip(bibliography, ordered_results):
        errors, reference_url, verified_data = result
        _record_reference_result_silent(
            checker,
            paper,
            reference,
            errors,
            reference_url,
            paper_errors,
            debug_mode,
            verified_data=verified_data,
        )


def _record_reference_result_silent(
    checker: Any,
    paper: Any,
    reference: Dict[str, Any],
    errors: Optional[List[Dict[str, Any]]],
    reference_url: Optional[str],
    paper_errors: List[Dict[str, Any]],
    debug_mode: bool,
    verified_data: Optional[Dict[str, Any]] = None,
) -> None:
    if not errors:
        return

    has_unverified_error = any(
        error.get('error_type') == 'unverified'
        or error.get('warning_type') == 'unverified'
        or error.get('info_type') == 'unverified'
        for error in errors
    )
    if has_unverified_error:
        checker.total_unverified_refs += 1

    checker.add_error_to_dataset(paper, reference, errors, reference_url, verified_data)
    paper_errors.extend(errors)
    from refchecker.core.hallucination_policy import count_raw_errors
    ec, wc, ic = count_raw_errors(errors)
    checker.total_errors_found += ec
    checker.total_warnings_found += wc
    checker.total_info_found += ic


def _submit_hallucination_assessments_async(
    checker: Any,
    hallucination_pool: AsyncHallucinationPool,
) -> List[tuple]:
    """Submit hallucination checks without blocking.

    Runs the same deterministic pre-screening as the former
    ``_apply_batched_hallucination_assessments``.  Deterministic verdicts are
    applied immediately to the error-entry dicts.  Entries that need an LLM
    call are submitted to *hallucination_pool* and the (error_entry, future)
    pairs are returned so the caller can collect them later.
    """
    llm_verifier = checker.report_builder.llm_verifier
    web_searcher = checker.report_builder.web_searcher
    pending: List[tuple] = []

    for error_entry in checker.errors:
        reference = error_entry.get('original_reference') or {}
        raw_errors = error_entry.get('_original_errors') or []
        verified_url = error_entry.get('ref_verified_url', '')
        filtered = build_hallucination_error_entry(raw_errors, reference, verified_url=verified_url)
        if filtered is None:
            continue

        outcome, assessment = pre_screen_hallucination(filtered)
        if outcome == 'resolved':
            # Mirror the deferral logic in run_hallucination_check():
            # 0% author-overlap LIKELY verdicts, and verified LIKELY verdicts,
            # should be deferred to the LLM, which can web-search and confirm
            # whether the checker matched a different paper.
            author_overlap = assessment.get('author_overlap') if assessment else None
            should_defer_likely = (
                assessment
                and assessment.get('verdict') == 'LIKELY'
                and (author_overlap == 0 or bool(verified_url))
            )
            if (
                should_defer_likely
                and llm_verifier
                and (getattr(llm_verifier, 'available', False) or getattr(llm_verifier, 'cache_dir', None))
            ):
                # Defer to LLM instead of applying immediately
                future = hallucination_pool.submit(filtered, llm_verifier, web_searcher)
                pending.append((checker, error_entry, future))
                continue
            error_entry['hallucination_assessment'] = assessment
            continue
        if outcome == 'skip':
            continue

        # 'needs_llm' — submit to pool
        if not llm_verifier:
            continue
        if not getattr(llm_verifier, 'available', False) and not getattr(llm_verifier, 'cache_dir', None):
            continue

        future = hallucination_pool.submit(filtered, llm_verifier, web_searcher)
        pending.append((checker, error_entry, future))

    return pending


def _finalize_hallucination_on_result(
    result: BulkPaperResult,
    pending_tasks: List[tuple],
) -> None:
    """Wait for pending hallucination futures and apply results to a BulkPaperResult.

    Adjusts unverified counts for UNLIKELY verdicts and removes
    URL-verified UNLIKELY entries, matching the CLI single-paper behaviour.
    """
    # Collect LLM results
    for checker, error_entry, future in pending_tasks:
        try:
            assessment = future.result(timeout=120)
            if assessment:
                reference = error_entry.get('original_reference') or {}
                raw_errors = error_entry.get('_original_errors') or []
                has_unverified = any((e.get('error_type') or '') == 'unverified' for e in raw_errors)
                applied = apply_hallucination_verdict(
                    {'status': 'unverified' if has_unverified else 'error', 'errors': raw_errors, '_raw_errors': raw_errors},
                    assessment,
                    reference=reference,
                    standard_refchecker=lambda found_ref, checker=checker: checker.verify_reference_standard(None, found_ref),
                )
                error_entry['hallucination_assessment'] = applied.get('hallucination_assessment', assessment)
                if applied.get('matched_database'):
                    error_entry['matched_database'] = applied['matched_database']
                authoritative_urls = applied.get('authoritative_urls') or []
                if authoritative_urls:
                    error_entry['ref_verified_url'] = authoritative_urls[0].get('url', error_entry.get('ref_verified_url', ''))
        except Exception as exc:
            logger.warning('Hallucination check failed for %s: %s',
                           error_entry.get('ref_title', '?')[:60], exc)

    # Adjust unverified count for UNLIKELY verdicts
    for entry in result.errors:
        assessment = entry.get('hallucination_assessment') or {}
        if assessment.get('verdict') != 'UNLIKELY':
            continue
        raw_errors = entry.get('_original_errors') or []
        has_unverified = any(
            e.get('error_type') == 'unverified'
            or e.get('warning_type') == 'unverified'
            or e.get('info_type') == 'unverified'
            for e in raw_errors
        )
        if has_unverified and result.total_unverified_refs > 0:
            result.total_unverified_refs -= 1

    # Remove URL-verified UNLIKELY entries
    to_remove = []
    for i, entry in enumerate(result.errors):
        assessment = entry.get('hallucination_assessment') or {}
        if assessment.get('verdict') != 'UNLIKELY':
            continue
        raw_errors = entry.get('_original_errors') or []
        has_unverified = any(
            (e.get('error_type') or '') == 'unverified'
            for e in raw_errors
        )
        has_url_references = any(
            'url references paper' in (e.get('error_details') or '').lower()
            for e in raw_errors
        )
        if has_unverified and has_url_references:
            to_remove.append(i)
    for i in reversed(to_remove):
        result.errors.pop(i)


def _apply_bulk_results(root_checker: Any, results: Sequence[BulkPaperResult]) -> None:
    root_checker.total_papers_processed = len(results)
    root_checker.total_references_processed = sum(result.references_processed for result in results)
    root_checker.total_errors_found = sum(result.total_errors_found for result in results)
    root_checker.total_warnings_found = sum(result.total_warnings_found for result in results)
    root_checker.total_info_found = sum(result.total_info_found for result in results)
    root_checker.total_unverified_refs = sum(result.total_unverified_refs for result in results)
    root_checker.total_arxiv_refs = sum(result.total_arxiv_refs for result in results)
    root_checker.total_non_arxiv_refs = sum(result.total_non_arxiv_refs for result in results)
    root_checker.total_other_refs = sum(result.total_other_refs for result in results)
    root_checker.papers_with_errors = sum(result.papers_with_errors for result in results)
    root_checker.papers_with_warnings = sum(result.papers_with_warnings for result in results)
    root_checker.papers_with_info = sum(result.papers_with_info for result in results)
    root_checker.used_regex_extraction = any(result.used_regex_extraction for result in results)
    root_checker.used_unreliable_extraction = any(result.used_unreliable_extraction for result in results)
    root_checker.errors = []
    for result in results:
        root_checker.errors.extend(result.errors)
    root_checker.single_paper_mode = False
    root_checker.current_paper_info = None
    root_checker.fatal_error = False


def _print_bulk_final_summary(checker: Any) -> None:
    if checker.debug_mode or checker.fatal_error:
        return

    payload = checker._build_structured_report_payload()
    flagged_count = payload['summary'].get('flagged_records', 0)
    _safe_print(f"\n" + '=' * 60)
    _safe_print('FINAL SUMMARY')
    _safe_print('=' * 60)
    _safe_print(f'📄 Total papers processed: {checker.total_papers_processed}')
    _safe_print(f'Total references processed: {checker.total_references_processed}')
    _safe_print(f'❌ Papers with errors:   {checker.papers_with_errors}')
    _safe_print(f'         Total errors:   {checker.total_errors_found}')
    _safe_print(f'⚠️  Papers with warnings: {checker.papers_with_warnings}')
    _safe_print(f'         Total warnings: {checker.total_warnings_found}')
    _safe_print(f'ℹ️  Papers with information: {checker.papers_with_info}')
    _safe_print(f'         Total information: {checker.total_info_found}')
    total_unverified = max(checker.total_unverified_refs, flagged_count)
    _safe_print(f'❓ Total unverified: {total_unverified}')
    if flagged_count > 0:
        _safe_print(f'🚩 Total likely hallucinated: {flagged_count}')
    if checker.used_unreliable_extraction and checker.total_errors_found > 5:
        _safe_print(f'\nResults might be affected by incorrect reference extraction. Consider using LLM extraction.')
    if checker.verification_output_file:
        _safe_print(f'\nDetailed results saved to: {checker.verification_output_file}')
    if checker.report_file:
        _safe_print(f'Written report: {checker.report_file}')


def _extract_json_payload(text: str) -> Any:
    candidate = (text or '').strip()
    if not candidate:
        raise ValueError('empty response')

    fence_match = re.search(r'```(?:json)?\s*(.*?)```', candidate, re.DOTALL | re.IGNORECASE)
    if fence_match:
        candidate = fence_match.group(1).strip()

    for opener, closer in (('[', ']'), ('{', '}')):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end != -1 and end > start:
            snippet = candidate[start:end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                continue

    return json.loads(candidate)