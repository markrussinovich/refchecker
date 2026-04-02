#!/usr/bin/env python3
"""Re-run hallucination checks on previously-checked references.

Reads a JSON file of reference records (from results_combined),
runs run_hallucination_check on each, and writes updated records
with hallucination_assessment fields.

Usage:
    python scripts/recheck_hallucinations.py \
        --input /datadrive/iclr2026/data/verified_low_overlap_refs.json \
        --output /datadrive/iclr2026/data/rechecked_hallucinations.json \
        --llm-provider anthropic \
        --concurrency 8
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from refchecker.core.hallucination_policy import run_hallucination_check

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)


def build_error_entry(record: Dict[str, Any]) -> Dict[str, Any]:
    """Build an error_entry dict from a results_combined record."""
    return {
        'error_type': record.get('error_type', ''),
        'error_details': record.get('error_details', ''),
        'ref_title': record.get('ref_title', ''),
        'ref_authors_cited': record.get('ref_authors_cited', ''),
        'ref_authors_correct': record.get('ref_authors_correct', ''),
        'ref_year_cited': record.get('ref_year_cited'),
        'ref_venue_cited': record.get('original_reference', {}).get('venue', ''),
        'ref_url_cited': record.get('ref_url_cited', ''),
        'ref_verified_url': record.get('ref_verified_url', ''),
        'original_reference': record.get('original_reference', {}),
    }


def check_one_record(
    idx: int,
    total: int,
    record: Dict[str, Any],
    llm_client: Any,
    web_searcher: Any,
) -> Dict[str, Any]:
    """Run hallucination check on a single record and return updated record."""
    error_entry = build_error_entry(record)
    title = record.get('ref_title', '')[:60]
    paper = record.get('source_paper_id', '')

    try:
        assessment = run_hallucination_check(
            error_entry,
            llm_client=llm_client,
            web_searcher=web_searcher,
        )
    except Exception as exc:
        logger.warning(f'[{idx+1}/{total}] Error checking "{title}": {exc}')
        assessment = {
            'verdict': 'UNCERTAIN',
            'explanation': f'Assessment failed: {exc}',
            'web_search': None,
        }

    if assessment:
        record = dict(record)  # copy
        record['hallucination_assessment'] = assessment
        verdict = assessment.get('verdict', 'UNCERTAIN')
        logger.info(
            f'[{idx+1}/{total}] {verdict}: "{title}" (paper={paper})'
        )
    else:
        logger.info(
            f'[{idx+1}/{total}] No assessment: "{title}" (paper={paper})'
        )

    return record


async def run_checks(
    records: list,
    llm_client: Any,
    web_searcher: Any,
    concurrency: int = 8,
) -> list:
    """Run hallucination checks on all records with concurrency."""
    total = len(records)
    results = [None] * total
    semaphore = asyncio.Semaphore(concurrency)
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=concurrency)

    async def check_with_limit(idx: int) -> None:
        async with semaphore:
            result = await loop.run_in_executor(
                executor,
                check_one_record,
                idx, total, records[idx], llm_client, web_searcher,
            )
            results[idx] = result

    tasks = [check_with_limit(i) for i in range(total)]
    await asyncio.gather(*tasks)
    executor.shutdown(wait=False)
    return results


def main():
    parser = argparse.ArgumentParser(description='Re-run hallucination checks on references')
    parser.add_argument('--input', required=True, help='Input JSON file of reference records')
    parser.add_argument('--output', required=True, help='Output JSON file with updated records')
    parser.add_argument('--llm-provider', default='anthropic', help='LLM provider (default: anthropic)')
    parser.add_argument('--llm-model', default=None, help='LLM model (uses provider default if omitted)')
    parser.add_argument('--concurrency', type=int, default=8, help='Max concurrent LLM calls')
    parser.add_argument('--limit', type=int, default=None, help='Process only first N records (for testing)')
    args = parser.parse_args()

    # Load records
    logger.info(f'Loading records from {args.input}')
    with open(args.input) as f:
        records = json.load(f)
    logger.info(f'Loaded {len(records)} records')

    if args.limit:
        records = records[:args.limit]
        logger.info(f'Limited to {len(records)} records')

    # Initialize LLM verifier
    from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier
    verifier = LLMHallucinationVerifier(
        provider=args.llm_provider,
        model=args.llm_model,
    )
    if not verifier.available:
        logger.error('LLM verifier not available (missing API key?)')
        sys.exit(1)
    logger.info(f'LLM verifier ready: provider={verifier.provider}, model={verifier.model}')

    # Initialize web searcher
    web_searcher = None
    try:
        from refchecker.checkers.web_search import create_web_search_checker
        searcher = create_web_search_checker(preferred_provider=args.llm_provider)
        if searcher.available:
            web_searcher = searcher
            logger.info(f'Web search enabled (provider: {searcher._provider_name})')
    except Exception as exc:
        logger.warning(f'Web search not available: {exc}')

    # Run checks
    start = time.time()
    results = asyncio.run(run_checks(records, verifier, web_searcher, args.concurrency))
    elapsed = time.time() - start

    # Summary
    verdicts = {}
    for r in results:
        ha = r.get('hallucination_assessment', {})
        v = ha.get('verdict', 'NONE')
        verdicts[v] = verdicts.get(v, 0) + 1

    logger.info(f'Completed {len(results)} checks in {elapsed:.1f}s')
    logger.info(f'Verdicts: {json.dumps(verdicts, indent=2)}')

    # Save results
    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)
    logger.info(f'Saved results to {args.output}')


if __name__ == '__main__':
    main()
