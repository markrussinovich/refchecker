#!/usr/bin/env python3
"""Compare benchmark results across 3 models"""
import json

results = {}
for name, f in [('GPT-5-mini', 'output/iclr10_gpt5mini_results.json'),
                ('Claude Haiku 4.5', 'output/iclr10_haiku_results.json'),
                ('GPT-5-nano', 'output/iclr10_gpt5nano_results.json')]:
    d = json.load(open(f))
    s = d.get('summary', {})
    papers = d.get('papers', [])
    results[name] = {
        'total_papers': s.get('total_papers_processed', 0),
        'total_refs': s.get('total_references_processed', 0),
        'total_errors': s.get('total_errors_found', 0),
        'total_warnings': s.get('total_warnings_found', 0),
        'total_info': s.get('total_info_found', 0),
        'total_unverified': s.get('total_unverified_refs', 0),
        'papers_with_refs': len(papers),
        'papers': papers
    }

# Timing from benchmark logs
timing = {
    'GPT-5-mini': 1304,
    'Claude Haiku 4.5': 2791,
    'GPT-5-nano': 333,
}

models = ['GPT-5-mini', 'Claude Haiku 4.5', 'GPT-5-nano']

print('=' * 90)
print('10 ICLR PAPER BENCHMARK COMPARISON')
print('=' * 90)
print()

hdr = f"{'Metric':<40} {'GPT-5-mini':>14} {'Haiku 4.5':>14} {'GPT-5-nano':>14}"
print(hdr)
print('-' * 90)

rows = [
    ('Total papers processed', 'total_papers'),
    ('Papers with refs extracted', 'papers_with_refs'),
    ('Total references checked', 'total_refs'),
    ('Total errors found', 'total_errors'),
    ('Total warnings found', 'total_warnings'),
    ('Total info found', 'total_info'),
    ('Total unverified refs', 'total_unverified'),
]

for label, key in rows:
    vals = [results[m][key] for m in models]
    print(f"{label:<40} {vals[0]:>14} {vals[1]:>14} {vals[2]:>14}")

# Failed extraction
label = 'Papers w/ extraction failure'
vals = [results[m]['total_papers'] - results[m]['papers_with_refs'] for m in models]
print(f"{label:<40} {vals[0]:>14} {vals[1]:>14} {vals[2]:>14}")

print('-' * 90)

# Timing
for m in models:
    t = timing[m]
    refs = results[m]['total_refs']
    spr = f"{t/refs:.1f}" if refs > 0 else "N/A"
    print(f"  {m}: {t}s ({t/60:.1f}min) | {spr}s/ref" + (f" ({refs} refs)" if refs > 0 else ""))

print()
print('=' * 90)
print('PER-PAPER BREAKDOWN (refs / errors / warnings)')
print('=' * 90)

# Build paper ID list from all models
all_paper_ids = {}
for m in models:
    for p in results[m]['papers']:
        pid = p.get('source_paper_id', '?')
        title = (p.get('source_title') or '?')[:42]
        all_paper_ids[pid] = title

# Create lookup
lookup = {}
for m in models:
    lookup[m] = {}
    for p in results[m]['papers']:
        lookup[m][p.get('source_paper_id')] = p

print(f"{'Paper':<44} {'GPT-5-mini':>13} {'Haiku 4.5':>13} {'GPT-5-nano':>13}")
print('-' * 90)

for pid, title in sorted(all_paper_ids.items(), key=lambda x: x[1]):
    parts = []
    for m in models:
        p = lookup[m].get(pid)
        if p:
            r = p.get('total_records', 0)
            etc = p.get('error_type_counts', {})
            errs = sum(etc.values()) if isinstance(etc, dict) else 0
            fr = p.get('flagged_records', 0)
            parts.append(f"{r}/{errs}/{fr}")
        else:
            parts.append("-/-/-")
    print(f"{title:<44} {parts[0]:>13} {parts[1]:>13} {parts[2]:>13}")

# Error type breakdown for Haiku (most complete)
print()
print('=' * 90)
print('ERROR TYPE BREAKDOWN (Claude Haiku 4.5 - most complete)')
print('=' * 90)
all_error_types = {}
for p in results['Claude Haiku 4.5']['papers']:
    etc = p.get('error_type_counts', {})
    for k, v in etc.items():
        all_error_types[k] = all_error_types.get(k, 0) + v

for etype, count in sorted(all_error_types.items(), key=lambda x: -x[1]):
    print(f"  {etype:<30} {count:>5}")

print()
print('=' * 90)
print('NOTES')
print('=' * 90)
print('- GPT-5-mini/nano: LLM reference extraction often failed (returned "Yes" or timed out)')
print('  so most papers fell back to regex/BibTeX parsing with fewer refs extracted')
print('- GPT-5-nano also hit OpenReview 429 rate limits (ran after other models)')
print('- Claude Haiku 4.5: Successfully extracted refs via LLM for all 10 papers')
print('- Haiku took longer wall-clock time due to more refs requiring Semantic Scholar API calls')
