#!/usr/bin/env python3
"""
Re-verify unverified references and those with hallucination assessments.

Runs individual web searches using all available providers (OpenAI, Anthropic,
Gemini) against each flagged reference and updates the results JSON in place.
"""

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from refchecker.checkers.web_search import (
    OpenAISearchProvider,
    AnthropicSearchProvider,
    GeminiSearchProvider,
    WebSearchChecker,
    create_web_search_checker,
)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

RESULTS_FILE = Path(__file__).resolve().parent.parent / 'output' / 'iclr10_haiku_results.json'


def _build_query(rec: dict) -> str:
    """Build a search query from a record's reference metadata."""
    lines = []
    if rec.get('ref_title'):
        lines.append(f"Title: {rec['ref_title']}")
    if rec.get('ref_authors_cited'):
        lines.append(f"Authors: {rec['ref_authors_cited']}")
    if rec.get('ref_year_cited'):
        lines.append(f"Year: {rec['ref_year_cited']}")
    orig = rec.get('original_reference', {})
    if orig.get('venue'):
        lines.append(f"Venue: {orig['venue']}")
    return '\n'.join(lines)


def test_providers():
    """Test each provider is available and can perform a search."""
    test_query = "Title: Attention Is All You Need\nAuthors: Vaswani et al.\nYear: 2017"

    providers = [
        ('OpenAI', OpenAISearchProvider()),
        ('Anthropic', AnthropicSearchProvider()),
        ('Gemini', GeminiSearchProvider()),
    ]

    results = {}
    for name, provider in providers:
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing {name} provider...")
        if not provider.available:
            logger.info(f"  ✗ {name}: not available (missing API key or package)")
            results[name] = None
            continue
        try:
            search_results = provider.search(test_query)
            urls = [r['link'] for r in search_results if r.get('link')]
            verdict_text = ''
            for r in search_results:
                verdict_text = r.pop('_verdict_text', '') or verdict_text
            logger.info(f"  ✓ {name}: {len(urls)} URLs found")
            if verdict_text:
                logger.info(f"  Verdict: {verdict_text[:200]}")
            for url in urls[:5]:
                logger.info(f"    {url}")
            results[name] = {
                'urls': urls,
                'verdict': verdict_text[:500],
            }
        except Exception as exc:
            logger.info(f"  ✗ {name}: error: {exc}")
            results[name] = None

    return results


def recheck_references(results_data: dict) -> list:
    """Find and re-check all unverified/hallucination-assessed references."""
    # Identify records that need rechecking
    targets = []
    for i, rec in enumerate(results_data['records']):
        needs_recheck = False
        if rec.get('error_type') == 'unverified':
            needs_recheck = True
        if rec.get('hallucination_assessment'):
            needs_recheck = True
        # Also check 'multiple' errors that include unverified
        if rec.get('error_type') == 'multiple':
            details = (rec.get('error_details') or '').lower()
            if 'could not be verified' in details or 'unverified' in details:
                needs_recheck = True
        if needs_recheck:
            targets.append((i, rec))

    logger.info(f"\nFound {len(targets)} references to re-check")

    # Initialize all available providers
    providers = []
    for ProvCls in [OpenAISearchProvider, AnthropicSearchProvider, GeminiSearchProvider]:
        prov = ProvCls()
        if prov.available:
            providers.append(prov)
            logger.info(f"  Provider available: {prov.name}")

    if not providers:
        logger.info("  No web search providers available!")
        return []

    # Run each reference through all available providers
    recheck_results = []
    for idx, rec in targets:
        title = rec.get('ref_title', '<no title>')
        paper_id = rec.get('source_paper_id', '')
        logger.info(f"\n{'─'*60}")
        logger.info(f"Rechecking: {title}")
        logger.info(f"  Paper: {paper_id}")
        logger.info(f"  Error type: {rec.get('error_type')}")
        logger.info(f"  Existing assessment: {rec.get('hallucination_assessment', {}).get('verdict', 'none')}")

        query = _build_query(rec)
        provider_verdicts = {}

        for prov in providers:
            checker = WebSearchChecker(prov)
            try:
                result = checker.check_reference_exists(rec)
                provider_verdicts[prov.name] = result
                logger.info(f"  {prov.name}: verdict={result.get('verdict', 'N/A')}, "
                           f"found={result.get('found')}, urls={len(result.get('academic_urls', []))}")
                if result.get('explanation'):
                    logger.info(f"    {result['explanation'][:200]}")
                for url in result.get('academic_urls', [])[:3]:
                    logger.info(f"    URL: {url}")
            except Exception as exc:
                logger.warning(f"  {prov.name}: error: {exc}")
                provider_verdicts[prov.name] = {'error': str(exc)}

        # Gather all URLs from all providers
        all_urls = set()
        for v in provider_verdicts.values():
            if isinstance(v, dict):
                for url in v.get('academic_urls', []):
                    all_urls.add(url)

        # Determine consensus — be very conservative about marking LIKELY
        verdicts = [v.get('verdict', '') for v in provider_verdicts.values() if isinstance(v, dict) and 'verdict' in v]
        explanations = [v.get('explanation', '') for v in provider_verdicts.values() if isinstance(v, dict)]
        exists_count = sum(1 for v in verdicts if v == 'EXISTS')
        not_found_count = sum(1 for v in verdicts if v == 'NOT_FOUND')

        # Check for contradictions: verdict says NOT_FOUND but explanation
        # mentions the paper exists (common LLM confusion)
        contradiction_count = 0
        for v in provider_verdicts.values():
            if isinstance(v, dict) and v.get('verdict') == 'NOT_FOUND':
                expl = (v.get('explanation') or '').lower()
                if any(phrase in expl for phrase in (
                    'paper exists', 'does exist', 'is available',
                    'was published', 'is a real', 'is well-documented',
                    'is well-known', 'is hosted', 'confirmed',
                )):
                    contradiction_count += 1
                    logger.info(f"  ⚠ Contradiction detected: verdict=NOT_FOUND but explanation suggests paper exists")

        # If any provider found it with academic URLs → strong evidence it exists
        if all_urls:
            consensus = 'UNLIKELY'
            consensus_explanation = f"Multi-provider verification: academic URLs found — paper exists."
        elif exists_count >= 2 or (exists_count >= 1 and not_found_count == 0):
            consensus = 'UNLIKELY'
            consensus_explanation = f"Multi-provider verification: {exists_count}/{len(verdicts)} providers found the paper."
        elif exists_count >= 1:
            # At least one says EXISTS — mixed but leaning unlikely
            consensus = 'UNLIKELY'
            consensus_explanation = f"Multi-provider verification: {exists_count}/{len(verdicts)} providers found the paper (mixed results)."
        elif not_found_count >= 2 and contradiction_count == 0:
            # Only mark LIKELY if ALL providers genuinely couldn't find it
            # AND no explanations contradict the verdict
            consensus = 'LIKELY'
            consensus_explanation = f"Multi-provider verification: {not_found_count}/{len(verdicts)} providers could not find the paper."
        elif contradiction_count > 0:
            # Contradictory — model knows paper exists but search failed
            consensus = 'UNCERTAIN'
            consensus_explanation = f"Contradictory results: search returned NOT_FOUND but explanations suggest paper may exist."
        else:
            consensus = 'UNCERTAIN'
            consensus_explanation = f"Mixed results across {len(verdicts)} providers."

        # Build detailed explanation
        details = []
        for prov_name, v in provider_verdicts.items():
            if isinstance(v, dict) and 'verdict' in v:
                expl = (v.get('explanation') or '')[:300]
                details.append(f"{prov_name}: {v['verdict']} — {expl}")
            elif isinstance(v, dict) and 'error' in v:
                details.append(f"{prov_name}: ERROR — {v['error']}")

        full_explanation = consensus_explanation + "\n" + "\n".join(details)

        # Build updated assessment
        new_assessment = {
            'verdict': consensus,
            'explanation': full_explanation,
            'web_search': {
                'providers_used': list(provider_verdicts.keys()),
                'provider_verdicts': {k: v.get('verdict', 'ERROR') for k, v in provider_verdicts.items() if isinstance(v, dict)},
                'academic_urls': sorted(all_urls),
            },
        }

        logger.info(f"  → Consensus: {consensus}")

        recheck_results.append({
            'index': idx,
            'ref_title': title,
            'paper_id': paper_id,
            'old_assessment': rec.get('hallucination_assessment'),
            'new_assessment': new_assessment,
            'provider_verdicts': provider_verdicts,
        })

    return recheck_results


def update_results(results_data: dict, recheck_results: list) -> None:
    """Update the results data with new hallucination assessments."""
    for result in recheck_results:
        idx = result['index']
        rec = results_data['records'][idx]
        rec['hallucination_assessment'] = result['new_assessment']
        
        # Update error details for unverified refs
        verdict = result['new_assessment']['verdict']
        explanation = result['new_assessment']['explanation'].split('\n')[0]
        if rec.get('error_type') == 'unverified' and verdict != 'LIKELY':
            rec['error_details'] = f"Reference could not be verified — {explanation}"

    logger.info(f"\nUpdated {len(recheck_results)} records")


def main():
    logger.info("=" * 60)
    logger.info("Step 1: Testing all web search providers")
    logger.info("=" * 60)
    provider_results = test_providers()

    anthropic_ok = provider_results.get('Anthropic') is not None
    logger.info(f"\nAnthropic search working: {'YES' if anthropic_ok else 'NO'}")

    logger.info("\n" + "=" * 60)
    logger.info("Step 2: Loading results")
    logger.info("=" * 60)
    with open(RESULTS_FILE) as f:
        results_data = json.load(f)
    logger.info(f"Loaded {len(results_data['records'])} records from {RESULTS_FILE.name}")

    logger.info("\n" + "=" * 60)
    logger.info("Step 3: Re-checking flagged references")
    logger.info("=" * 60)
    recheck_results = recheck_references(results_data)

    if not recheck_results:
        logger.info("No references needed rechecking.")
        return

    logger.info("\n" + "=" * 60)
    logger.info("Step 4: Updating results file")
    logger.info("=" * 60)
    update_results(results_data, recheck_results)

    # Write back
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Written updated results to {RESULTS_FILE}")

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    for r in recheck_results:
        old_v = (r.get('old_assessment') or {}).get('verdict', 'none')
        new_v = r['new_assessment']['verdict']
        changed = '→' if old_v != new_v else '='
        logger.info(f"  {r['ref_title'][:60]:60s}  {old_v:10s} {changed} {new_v}")


if __name__ == '__main__':
    main()
