#!/usr/bin/env python3
"""Quick analysis of a refchecker bulk JSON report."""
import json, sys, os

report_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ['TEMP'], 'refchecker_iclr2026_smoke10_v2.json')
p = json.load(open(report_path, encoding='utf-8'))
s = p['summary']

print('=== SUMMARY ===')
for k, v in s.items():
    print(f'  {k}: {v}')

print('\n=== HALLUCINATION DETAILS ===')
flagged = [r for r in p['records'] if r.get('hallucination_assessment', {}).get('verdict') == 'LIKELY']
print(f'Total LIKELY hallucinated: {len(flagged)}')
for i, r in enumerate(flagged[:15]):
    a = r.get('hallucination_assessment', {})
    title = r.get('ref_title', '?')[:70]
    etype = r.get('error_type', '?')
    expl = a.get('explanation', '')[:120]
    print(f'  {i+1}. [{etype}] {title}')
    print(f'     {expl}')
if len(flagged) > 15:
    print(f'  ... plus {len(flagged) - 15} more')

uncertain = [r for r in p['records'] if r.get('hallucination_assessment', {}).get('verdict') == 'UNCERTAIN']
unlikely = [r for r in p['records'] if r.get('hallucination_assessment', {}).get('verdict') == 'UNLIKELY']
none_assessed = [r for r in p['records'] if not r.get('hallucination_assessment')]
print(f'\nAssessment breakdown: LIKELY={len(flagged)}, UNCERTAIN={len(uncertain)}, UNLIKELY={len(unlikely)}, not-assessed={len(none_assessed)}')

print('\n=== PAPER ROLLUPS ===')
for paper in p.get('papers', []):
    title = paper.get('source_title', '?')[:55]
    print(f'  {title:55s} | records={paper["total_records"]:3d} flagged={paper["flagged_records"]:2d} level={paper.get("max_flag_level","none")}')

print('\n=== TIMING ===')
# Parse completion times from the log if available
log_path = report_path.replace('.json', '.log')
if os.path.exists(log_path):
    import re
    lines = open(log_path, encoding='utf-8').readlines()
    completions = []
    for line in lines:
        m = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] Completed (\d+)/(\d+).*refs=(\d+)', line)
        if m:
            completions.append((m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))))
    if len(completions) >= 2:
        from datetime import datetime
        fmt = '%Y-%m-%d %H:%M:%S'
        start = datetime.strptime(completions[0][1] == 1 and completions[0][0] or completions[0][0], fmt)
        end = datetime.strptime(completions[-1][0], fmt)
        total_secs = (end - start).total_seconds()
        total_refs = sum(c[3] for c in completions)
        print(f'  Wall clock: {completions[0][0]} to {completions[-1][0]} = {total_secs:.0f}s')
        print(f'  Total refs: {total_refs}')
        print(f'  Avg seconds/reference: {total_secs / total_refs:.1f}s')
        print(f'  Avg seconds/paper: {total_secs / len(completions):.1f}s')
        for ts, num, total, refs in completions:
            print(f'    Paper {num}/{total}: {refs} refs @ {ts}')
else:
    print('  (no log file found for timing analysis)')
