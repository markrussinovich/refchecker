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
from dataclasses import dataclass, field
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence

from refchecker.core.hallucination_policy import check_author_hallucination, run_hallucination_check, should_check_hallucination
from refchecker.utils.arxiv_utils import get_bibtex_content
from refchecker.utils.biblatex_parser import detect_biblatex_format
from refchecker.utils.bibtex_parser import detect_bibtex_format
from refchecker.utils.text_utils import detect_latex_bibliography_format, detect_standard_acm_natbib_format, extract_latex_references, validate_parsed_references

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from refchecker.core.refchecker import ArxivReferenceChecker


def _safe_print(*args, **kwargs) -> None:
    """Print that falls back to ascii+replace when stdout can't handle Unicode."""
    import sys
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = ' '.join(str(a) for a in args)
        sys.stdout.buffer.write(text.encode('utf-8', errors='replace'))
        sys.stdout.buffer.write(b'\n')
        sys.stdout.buffer.flush()


_HALLUCINATION_MULTI_KEYWORDS = (
    'unverified',
    'non-existent',
    'does not reference',
    'could not be verified',
    'could not verify',
)


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
        self._thread.join()

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


@dataclass
class _HallucinationPayload:
    error_entry: Dict[str, Any]
    llm_verifier: Any
    web_searcher: Any


class BulkLLMExtractionBatcher:
    def __init__(self, enabled: bool = True, max_batch_size: int = 3, max_wait_seconds: float = 0.15):
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
        parsed = _extract_json_payload(response_text)
        if not isinstance(parsed, list):
            raise ValueError('Batched extraction response was not a JSON array')

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
                results.append([])
        return results


class BulkHallucinationBatcher:
    def __init__(self, enabled: bool = True, max_batch_size: int = 6, max_wait_seconds: float = 0.2):
        self.enabled = enabled
        self._batcher: Optional[_QueueBatcher] = None
        if enabled:
            self._batcher = _QueueBatcher(
                name='BulkHallucinationBatcher',
                process_batch=self._process_batch,
                process_single=self._process_single,
                max_batch_size=max_batch_size,
                max_wait_seconds=max_wait_seconds,
            )

    def assess(self, error_entry: Dict[str, Any], llm_verifier: Any, web_searcher: Any) -> Optional[Dict[str, Any]]:
        if not self.enabled or self._batcher is None:
            return self._process_single(_HallucinationPayload(error_entry=error_entry, llm_verifier=llm_verifier, web_searcher=web_searcher))
        return self.submit(error_entry, llm_verifier, web_searcher).wait()

    def submit(self, error_entry: Dict[str, Any], llm_verifier: Any, web_searcher: Any) -> _BatchTask:
        payload = _HallucinationPayload(error_entry=error_entry, llm_verifier=llm_verifier, web_searcher=web_searcher)
        if not self.enabled or self._batcher is None:
            task = _BatchTask(payload=payload)
            try:
                task.result = self._process_single(payload)
            except Exception as exc:
                task.error = exc
            finally:
                task.event.set()
            return task
        return self._batcher.submit(payload)

    def close(self) -> None:
        if self._batcher is not None:
            self._batcher.close()

    def _process_single(self, payload: _HallucinationPayload) -> Optional[Dict[str, Any]]:
        return run_hallucination_check(
            payload.error_entry,
            llm_client=payload.llm_verifier,
            web_searcher=payload.web_searcher,
        )

    def _process_batch(self, payloads: Sequence[_HallucinationPayload]) -> Sequence[Optional[Dict[str, Any]]]:
        if len(payloads) == 1:
            return [self._process_single(payloads[0])]

        verifier = payloads[0].llm_verifier
        if not verifier or not getattr(verifier, 'available', False):
            raise RuntimeError('LLM verifier unavailable for batched hallucination checks')

        today = dt.date.today().isoformat()
        items: List[str] = []
        for index, payload in enumerate(payloads):
            entry = payload.error_entry
            items.append(
                '\n'.join([
                    f'ITEM {index}',
                    f"Title: {entry.get('ref_title', '')}",
                    f"Authors: {entry.get('ref_authors_cited', '')}",
                    f"Venue: {entry.get('ref_venue_cited', '')}",
                    f"Year: {entry.get('ref_year_cited', '')}",
                    f"URL: {entry.get('ref_url_cited', '')}",
                    f"Error type: {entry.get('error_type', '')}",
                    f"Error details: {entry.get('error_details', '')}",
                ])
            )

        system_prompt = (
            'You are an academic-integrity assistant that determines whether '
            'cited references are **hallucinated** (fabricated by an AI).\n\n'
            'IMPORTANT: Before rendering each verdict, search the web for the '
            'exact paper title in quotes to check whether the paper actually '
            'exists. Grounded evidence from web search always overrides your '
            'prior beliefs.\n\n'
            'Verdict definitions:\n'
            '  LIKELY    — the reference is probably FABRICATED (does not exist)\n'
            '  UNLIKELY  — the reference is probably REAL despite the errors\n'
            '  UNCERTAIN — cannot determine with confidence\n\n'
            'After searching and reasoning, return ONLY a JSON array.'
        )
        user_prompt = (
            f"Today's date is {today}.\n\n"
            'For each item below, search for the exact title, then decide '
            'whether it is a hallucinated (fabricated) citation.\n\n'
            'Key signals of hallucination (verdict should be LIKELY):\n'
            '- Paper not found in ANY academic database AND web search returns no results\n'
            '- Authors are obviously fake or don\'t work in the cited field\n'
            '- ArXiv ID or DOI points to a completely different paper\n'
            '- Title is generic/buzzwordy with no specific contribution\n\n'
            'Key signals it is NOT hallucinated (verdict should be UNLIKELY):\n'
            '- Paper found via web search or in a database, even with metadata errors\n'
            '- Year off-by-one, venue abbreviation differences, or author name formatting '
            'variations are common in real citations and NOT hallucination\n'
            '- A broken URL does NOT mean the paper is fabricated if the title/authors are real\n\n'
            'CRITICAL: If your web search finds the paper exists, the verdict MUST be UNLIKELY '
            'regardless of citation errors. A real paper with wrong metadata is NOT a hallucination.\n\n'
            'Return a JSON array where each object has keys: index, verdict, explanation.\n'
            'Do not omit items.\n\n'
            + '\n\n'.join(items)
        )

        response_text, _ = verifier._call(system_prompt, user_prompt)
        parsed = _extract_json_payload(response_text)
        if not isinstance(parsed, list):
            raise ValueError('Batched hallucination response was not a JSON array')

        grouped: Dict[int, Optional[Dict[str, Any]]] = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get('index'))
            except (TypeError, ValueError):
                continue
            verdict = str(item.get('verdict') or 'UNCERTAIN').upper()
            explanation = str(item.get('explanation') or '').strip()
            if verdict not in {'LIKELY', 'UNLIKELY', 'UNCERTAIN'}:
                verdict = 'UNCERTAIN'

            # Post-hoc consistency check: if the explanation says the paper
            # exists/is real/was found, override a contradictory LIKELY verdict.
            if verdict == 'LIKELY':
                explanation_lower = explanation.lower()
                real_signals = (
                    'exists on arxiv', 'exists on arXiv',
                    'is a well-known', 'is well-known',
                    'is a real', 'paper exists', 'paper is real',
                    'reference is valid', 'reference is real',
                    'available on arxiv', 'available on arXiv',
                    'found on arxiv', 'found on arXiv',
                    'found the paper', 'found via web',
                    'found in google scholar', 'found in semantic scholar',
                    'published in', 'appeared in',
                )
                if any(signal in explanation_lower for signal in real_signals):
                    verdict = 'UNLIKELY'
                    explanation += ' (Verdict corrected: explanation indicates paper is real.)'

            grouped[index] = {
                'verdict': verdict,
                'explanation': explanation,
                'web_search': None,
            }

        return [grouped.get(index) for index in range(len(payloads))]


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

            # ── Paper header (same format as single-paper CLI) ──
            display_title = result.title or result.paper_id or result.input_spec
            _safe_print(f'\nProcessing: {display_title}')
            if result.source_url:
                _safe_print(f'   {result.source_url}')

            # ── Only show full reference blocks for hallucination-flagged refs ──
            flagged_entries = [
                e for e in result.errors
                if e.get('hallucination_assessment', {}).get('verdict') == 'LIKELY'
            ]
            for error_entry in flagged_entries:
                ref_title = error_entry.get('ref_title', 'Untitled')
                ref_authors = error_entry.get('ref_authors_cited', '')
                ref_year = error_entry.get('ref_year_cited', '')
                ref_url = error_entry.get('ref_url_cited', '')
                ref_venue = error_entry.get('ref_venue_cited', '')
                ref_verified_url = error_entry.get('ref_verified_url', '')
                error_type = error_entry.get('error_type', '')
                error_details = error_entry.get('error_details', '')

                # Reference header (matches [N/total] Title format)
                _safe_print(f'       {ref_title}')
                if ref_authors:
                    _safe_print(f'       {ref_authors}')
                if ref_venue:
                    _safe_print(f'       {ref_venue}')
                if ref_year:
                    _safe_print(f'       {ref_year}')
                if ref_url:
                    _safe_print(f'       {ref_url}')
                _safe_print('')
                if ref_verified_url:
                    _safe_print(f'       Verified URL: {ref_verified_url}')

                # Error details
                if error_type == 'unverified' or (error_type == 'multiple' and 'unverified' in error_details.lower()):
                    _safe_print(f'      ? Could not verify: {ref_title}')
                for line in error_details.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith('- '):
                        line = line[2:]
                    if any(kw in line.lower() for kw in ('could not', 'unverified')):
                        continue
                    _safe_print(f'      X Error: {line}')

                # Hallucination flag
                assessment = error_entry.get('hallucination_assessment', {})
                explanation = assessment.get('explanation', '')
                _safe_print(f'      !! Likely hallucinated: {explanation}')

            # ── Paper summary line ──
            elapsed = f'{result.elapsed_seconds:.0f}s'
            flagged_count = len(flagged_entries)
            flag_note = f' hallucinated={flagged_count}' if flagged_count else ''
            _safe_print(
                f'\n   [{self.completed_papers}/{self.total_papers}] '
                f'refs={result.references_processed} '
                f'errors={result.total_errors_found} warnings={result.total_warnings_found} '
                f'info={result.total_info_found} unverified={result.total_unverified_refs}'
                f'{flag_note} '
                f'({elapsed})'
            )
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
        )


def run_bulk_paper_check(root_checker: Any, input_specs: Sequence[str], debug_mode: bool = False) -> None:
    config = _BulkCheckerConfig.from_checker(root_checker)
    reporter = BulkProgressReporter(total_papers=len(input_specs))
    extraction_batcher = BulkLLMExtractionBatcher(enabled=bool(getattr(root_checker, 'llm_enabled', False)))
    hallucination_batcher = BulkHallucinationBatcher(enabled=True)
    result_map: Dict[int, BulkPaperResult] = {}
    job_queue: Queue[Any] = Queue()
    result_queue: Queue[BulkPaperResult] = Queue()

    for index, input_spec in enumerate(input_specs):
        job_queue.put(BulkPaperJob(index=index, input_spec=input_spec))

    # Process papers one at a time to avoid cascading API rate limits.
    # Each paper already uses parallel reference verification internally.
    paper_worker_count = 1
    for _ in range(paper_worker_count):
        job_queue.put(None)

    def worker() -> None:
        checker = config.create_worker_checker()
        while True:
            job = job_queue.get()
            try:
                if job is None:
                    return
                try:
                    result = _process_bulk_paper_job(
                        checker=checker,
                        job=job,
                        debug_mode=debug_mode,
                        extraction_batcher=extraction_batcher,
                        hallucination_batcher=hallucination_batcher,
                    )
                except Exception as exc:
                    logger.error('Unhandled exception in bulk worker for %s: %s', job.input_spec, exc)
                    _reset_worker_state(checker)
                    checker.fatal_error = True
                    checker.fatal_error_message = str(exc)
                    result = _build_bulk_result(checker, job, job.input_spec, job.input_spec, time.perf_counter())
                result_queue.put(result)
            finally:
                job_queue.task_done()

    threads = [threading.Thread(target=worker, name=f'BulkPaperWorker-{index + 1}', daemon=True) for index in range(paper_worker_count)]
    for thread in threads:
        thread.start()

    completed = 0
    while completed < len(input_specs):
        result = result_queue.get()
        result_map[result.index] = result
        reporter.report(result)
        completed += 1

    job_queue.join()
    for thread in threads:
        thread.join()
    extraction_batcher.close()
    hallucination_batcher.close()

    ordered_results = [result_map[index] for index in sorted(result_map)]
    _apply_bulk_results(root_checker, ordered_results)
    _print_bulk_final_summary(root_checker)
    root_checker.write_all_errors_to_file()
    if root_checker.report_file:
        payload = root_checker._build_structured_report_payload()
        root_checker.write_structured_report(payload=payload)


def _process_bulk_paper_job(
    *,
    checker: Any,
    job: BulkPaperJob,
    debug_mode: bool,
    extraction_batcher: BulkLLMExtractionBatcher,
    hallucination_batcher: BulkHallucinationBatcher,
) -> BulkPaperResult:
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
                return _build_bulk_result(checker, job, paper_id, title, start_time)
        else:
            paper = checker._create_local_file_paper(local_path)

        paper_id = paper.get_short_id()
        title = getattr(paper, 'title', '') or paper_id or job.input_spec
        source_url = checker._get_source_paper_url(paper) if hasattr(checker, '_get_source_paper_url') else job.input_spec
        bibliography = extract_bibliography_bulk(checker, paper, debug_mode=debug_mode, extraction_batcher=extraction_batcher)
        if checker.fatal_error:
            return _build_bulk_result(checker, job, paper_id, title, start_time, source_url=source_url)

        if len(bibliography) > 1:
            bibliography = checker._deduplicate_bibliography_entries(bibliography)

        checker.total_papers_processed = 1
        checker.total_references_processed = len(bibliography)
        checker.total_arxiv_refs = sum(1 for ref in bibliography if ref.get('type') == 'arxiv')
        checker.total_non_arxiv_refs = sum(1 for ref in bibliography if ref.get('type') == 'non-arxiv')
        checker.total_other_refs = sum(1 for ref in bibliography if ref.get('type') == 'other')

        checker.batch_prefetch_arxiv_references(bibliography)
        _verify_bibliography_silent(checker, paper, bibliography, debug_mode=debug_mode)
        _apply_batched_hallucination_assessments(checker, hallucination_batcher)

        actual_errors = checker.total_errors_found
        warnings = checker.total_warnings_found
        info = checker.total_info_found
        checker.papers_with_errors = 1 if actual_errors else 0
        checker.papers_with_warnings = 1 if warnings else 0
        checker.papers_with_info = 1 if info else 0
        return _build_bulk_result(checker, job, paper_id, title, start_time, source_url=source_url)
    except Exception as exc:
        logger.error('Bulk paper job failed for %s: %s', job.input_spec, exc)
        checker.fatal_error = True
        checker.fatal_error_message = str(exc)
        return _build_bulk_result(checker, job, paper_id or job.input_spec, title or job.input_spec, start_time)


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
        if '\\begin{thebibliography}' in bibtex_content and '\\bibitem' in bibtex_content:
            references = extract_latex_references(bibtex_content, None)
            validation = validate_parsed_references(references)
            if not validation['is_valid'] and checker.llm_extractor:
                llm_refs = extraction_batcher.extract_references(checker, bibtex_content)
                if llm_refs:
                    llm_validation = validate_parsed_references(llm_refs)
                    if llm_validation['quality_score'] > validation['quality_score']:
                        references = llm_refs
            return references
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
        return []
    return parse_references_bulk(checker, bibliography_text, extraction_batcher)


def parse_references_bulk(checker: Any, bibliography_text: str, extraction_batcher: BulkLLMExtractionBatcher) -> List[Dict[str, Any]]:
    if not bibliography_text:
        return []

    if detect_standard_acm_natbib_format(bibliography_text):
        checker.used_regex_extraction = True
        return checker._parse_standard_acm_natbib_references(bibliography_text)

    if detect_bibtex_format(bibliography_text):
        checker.used_regex_extraction = True
        return checker._parse_bibtex_references(bibliography_text)

    if detect_biblatex_format(bibliography_text):
        checker.used_regex_extraction = True
        biblatex_refs = checker._parse_biblatex_references(bibliography_text)
        if biblatex_refs:
            return biblatex_refs
        if checker.llm_extractor:
            return extraction_batcher.extract_references(checker, bibliography_text)
        return []

    if checker.llm_extractor:
        references = extraction_batcher.extract_references(checker, bibliography_text)
        if references:
            return references
        checker.fatal_error = True
        return []

    checker.fatal_error = True
    return []


def _verify_bibliography_silent(checker: Any, paper: Any, bibliography: Sequence[Dict[str, Any]], debug_mode: bool) -> None:
    paper_errors: List[Dict[str, Any]] = []
    if not bibliography:
        return

    if checker.enable_parallel and len(bibliography) > 1:
        results: Dict[int, Any] = {}
        with ThreadPoolExecutor(max_workers=checker.max_workers, thread_name_prefix='BulkReference') as executor:
            future_map = {
                executor.submit(checker.verify_reference, paper, reference): index
                for index, reference in enumerate(bibliography)
            }
            for future in as_completed(future_map):
                index = future_map[future]
                try:
                    results[index] = future.result()
                except Exception as exc:
                    logger.error('Reference %d verification failed: %s', index, exc)
                    results[index] = ([{'error_type': 'processing_failed', 'error_details': f'Internal error: {exc}'}], None, None)
        ordered_results = [results[index] for index in range(len(bibliography))]
    else:
        ordered_results = [checker.verify_reference(paper, reference) for reference in bibliography]

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
    checker.total_errors_found += sum(1 for error in errors if 'error_type' in error and error['error_type'] != 'unverified')
    checker.total_warnings_found += sum(1 for error in errors if 'warning_type' in error)
    checker.total_info_found += sum(1 for error in errors if 'info_type' in error)


def _apply_batched_hallucination_assessments(checker: Any, hallucination_batcher: BulkHallucinationBatcher) -> None:
    llm_verifier = checker.report_builder.llm_verifier
    web_searcher = checker.report_builder.web_searcher
    tasks: List[tuple[Dict[str, Any], _BatchTask]] = []

    for error_entry in checker.errors:
        author_result = check_author_hallucination(error_entry)
        if author_result:
            error_entry['hallucination_assessment'] = author_result
            continue

        if not llm_verifier or not getattr(llm_verifier, 'available', False):
            continue
        if not _needs_llm_hallucination(error_entry):
            continue
        if not should_check_hallucination(error_entry):
            continue

        tasks.append((error_entry, hallucination_batcher.submit(error_entry, llm_verifier, web_searcher)))

    for error_entry, task in tasks:
        assessment = task.wait()
        if assessment:
            error_entry['hallucination_assessment'] = assessment


def _needs_llm_hallucination(error_entry: Dict[str, Any]) -> bool:
    error_type = (error_entry.get('error_type') or '').lower()
    if error_type in {'unverified', 'url'}:
        return True
    if error_type != 'multiple':
        return False
    details = (error_entry.get('error_details') or '').lower()
    return any(keyword in details for keyword in _HALLUCINATION_MULTI_KEYWORDS)


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
    _safe_print(f'Total papers processed: {checker.total_papers_processed}')
    _safe_print(f'Total references processed: {checker.total_references_processed}')
    _safe_print(f'Papers with errors:   {checker.papers_with_errors}')
    _safe_print(f'         Total errors:   {checker.total_errors_found}')
    _safe_print(f'Papers with warnings: {checker.papers_with_warnings}')
    _safe_print(f'         Total warnings: {checker.total_warnings_found}')
    _safe_print(f'Papers with information: {checker.papers_with_info}')
    _safe_print(f'         Total information: {checker.total_info_found}')
    _safe_print(f'Total unverified: {checker.total_unverified_refs}')
    if flagged_count > 0:
        _safe_print(f'Total likely hallucinated: {flagged_count}')
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