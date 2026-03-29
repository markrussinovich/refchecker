import argparse
import json
import logging
import os
import time
from contextlib import redirect_stdout
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent / 'src')
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from refchecker.config.settings import DEFAULT_EXTRACTION_MODELS
from refchecker.core.refchecker import ArxivReferenceChecker


OPENREVIEW_URL = 'https://openreview.net/pdf?id=TNqbfqSPoD'


def build_llm_config() -> dict:
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is not set')

    return {
        'provider': 'openai',
        'model': DEFAULT_EXTRACTION_MODELS['openai'],
        'api_key': api_key,
        'endpoint': None,
    }


def initialize_stats(checker: ArxivReferenceChecker, ref_count: int) -> None:
    checker.total_papers_processed = 1
    checker.total_references_processed = ref_count
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
    checker.errors = []


def build_workload(llm_config: dict, target_refs: int) -> tuple:
    extract_checker = ArxivReferenceChecker(llm_config=llm_config, enable_parallel=True, max_workers=6)

    openreview_paper = extract_checker._create_local_file_paper(OPENREVIEW_URL)
    openreview_refs = extract_checker.extract_bibliography(openreview_paper, debug_mode=False)

    sample7_paper = extract_checker._create_local_file_paper('tests/fixtures/hallucination_7ref_sample.bib')
    sample7_refs = extract_checker.extract_bibliography(sample7_paper, debug_mode=False)

    mixed_paper = extract_checker._create_local_file_paper('tests/fixtures/hallucination_mixed_sample.bib')
    mixed_refs = extract_checker.extract_bibliography(mixed_paper, debug_mode=False)

    refs = (openreview_refs + sample7_refs + mixed_refs)[:target_refs]
    if len(refs) != target_refs:
        raise RuntimeError(f'Expected {target_refs} refs, got {len(refs)}')

    return openreview_paper, refs


def main() -> int:
    parser = argparse.ArgumentParser(description='Benchmark RefChecker bulk verification throughput.')
    parser.add_argument('--refs', type=int, default=50, help='Number of references to benchmark')
    parser.add_argument('--max-workers', type=int, default=6, help='Parallel worker count')
    parser.add_argument('--output', required=True, help='Path to write JSON benchmark results')
    args = parser.parse_args()

    logging.getLogger().setLevel(logging.WARNING)

    llm_config = build_llm_config()
    source_paper, refs = build_workload(llm_config, args.refs)

    checker = ArxivReferenceChecker(
        llm_config=llm_config,
        enable_parallel=True,
        max_workers=args.max_workers,
    )
    initialize_stats(checker, len(refs))

    start = time.perf_counter()
    with open(os.devnull, 'w', encoding='utf-8') as devnull, redirect_stdout(devnull):
        checker.batch_prefetch_arxiv_references(refs)
        checker._verify_references_parallel(source_paper, refs, [], {}, 0, False)
    elapsed = time.perf_counter() - start

    payload = checker._build_structured_report_payload()
    result = {
        'refs': len(refs),
        'max_workers': args.max_workers,
        'elapsed_seconds': round(elapsed, 2),
        'seconds_per_ref': round(elapsed / len(refs), 2),
        'summary': payload['summary'],
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())