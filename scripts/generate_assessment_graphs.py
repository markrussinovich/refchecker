#!/usr/bin/env python3
"""Generate assessment graphs from the ICLR10 results."""

import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

RESULTS_FILE = Path(__file__).resolve().parent.parent / 'output' / 'iclr10_haiku_results.json'
ASSETS_DIR = Path(__file__).resolve().parent.parent / 'paper'

with open(RESULTS_FILE) as f:
    data = json.load(f)

# Color scheme
COLORS = {
    'error': '#e74c3c',
    'warning': '#f39c12',
    'info': '#3498db',
    'clean': '#2ecc71',
}

SEVERITY_COLORS = {
    'Errors': '#e74c3c',
    'Warnings': '#f39c12',
    'Informational': '#3498db',
    'Clean': '#2ecc71',
}

# ── Compute data ──

total_refs = data['summary']['total_references_processed']
total_with_issues = data['summary']['records_written']
total_clean = total_refs - total_with_issues

# Per-severity counts
records_errors = 0
records_warnings = 0
records_info = 0
for rec in data['records']:
    orig = rec.get('_original_errors', [])
    has_err = any('error_type' in e for e in orig)
    has_warn = any('warning_type' in e for e in orig)
    if has_err:
        records_errors += 1
    elif has_warn:
        records_warnings += 1
    else:
        records_info += 1

# Error type breakdown (from original errors)
error_type_counts = {}
for rec in data['records']:
    for orig in rec.get('_original_errors', []):
        for key in ('error_type', 'warning_type', 'info_type'):
            if key in orig:
                et = orig[key]
                if et == 'venue (v1 vs v2 update)':
                    et = 'venue'
                error_type_counts[et] = error_type_counts.get(et, 0) + 1

# Per-paper data
paper_names = []
paper_err = []
paper_warn = []
paper_info = []
paper_clean = []

# We know total refs = 378, total records = 258
# Per-paper clean count is unknown. Approximate: total_refs per paper isn't stored,
# only records with issues. We'll show per-paper issues-only breakdown.
for p in data['papers']:
    pid = p['source_paper_id']
    name = p['source_title']
    if len(name) > 40:
        name = name[:37] + '...'
    paper_names.append(name)
    
    paper_recs = [r for r in data['records'] if r['source_paper_id'] == pid]
    errs = sum(1 for r in paper_recs if any('error_type' in e for e in r.get('_original_errors', [])))
    warns = sum(1 for r in paper_recs if not any('error_type' in e for e in r.get('_original_errors', []))
                and any('warning_type' in e for e in r.get('_original_errors', [])))
    infos = sum(1 for r in paper_recs if not any('error_type' in e or 'warning_type' in e for e in r.get('_original_errors', [])))
    paper_err.append(errs)
    paper_warn.append(warns)
    paper_info.append(infos)

# ── Graph 1: Overall severity pie chart ──
fig, ax = plt.subplots(figsize=(7, 5))
sizes = [records_errors, records_warnings, records_info, total_clean]
labels = [
    f'Errors ({records_errors})',
    f'Warnings ({records_warnings})',
    f'Informational ({records_info})',
    f'Clean ({total_clean})',
]
colors = [COLORS['error'], COLORS['warning'], COLORS['info'], COLORS['clean']]
wedges, texts, autotexts = ax.pie(
    sizes, labels=labels, colors=colors, autopct='%1.1f%%',
    startangle=90, textprops={'fontsize': 11}
)
for t in autotexts:
    t.set_fontsize(10)
    t.set_fontweight('bold')
ax.set_title(f'Reference Quality Distribution\n({total_refs} references across 10 ICLR 2025 papers)', fontsize=13)
plt.tight_layout()
plt.savefig(ASSETS_DIR / 'fig_severity_pie.png', dpi=150, bbox_inches='tight')
plt.close()
print('Saved fig_severity_pie.png')

# ── Graph 2: Error type bar chart ──
# Separate by severity level
error_level_types = {}
warning_level_types = {}
info_level_types = {}
for rec in data['records']:
    for orig in rec.get('_original_errors', []):
        if 'error_type' in orig:
            et = orig['error_type']
            error_level_types[et] = error_level_types.get(et, 0) + 1
        elif 'warning_type' in orig:
            et = orig['warning_type']
            if et == 'venue (v1 vs v2 update)':
                et = 'venue'
            warning_level_types[et] = warning_level_types.get(et, 0) + 1
        elif 'info_type' in orig:
            et = orig['info_type']
            info_level_types[et] = info_level_types.get(et, 0) + 1

# Combine into stacked bar chart
all_types = sorted(set(list(error_level_types.keys()) + list(warning_level_types.keys()) + list(info_level_types.keys())),
                   key=lambda t: -(error_level_types.get(t, 0) + warning_level_types.get(t, 0) + info_level_types.get(t, 0)))

fig, ax = plt.subplots(figsize=(10, 5))
x = np.arange(len(all_types))
width = 0.6
err_vals = [error_level_types.get(t, 0) for t in all_types]
warn_vals = [warning_level_types.get(t, 0) for t in all_types]
info_vals = [info_level_types.get(t, 0) for t in all_types]

bars_err = ax.bar(x, err_vals, width, label='Error', color=COLORS['error'])
bars_warn = ax.bar(x, warn_vals, width, bottom=err_vals, label='Warning', color=COLORS['warning'])
bars_info = ax.bar(x, info_vals, width, bottom=[e + w for e, w in zip(err_vals, warn_vals)], label='Informational', color=COLORS['info'])

# Add value labels on bars
for bars in (bars_err, bars_warn, bars_info):
    for bar in bars:
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width()/2., bar.get_y() + h/2.,
                    str(int(h)), ha='center', va='center', fontsize=9, fontweight='bold', color='white')

type_labels = [t.replace('_', ' ').title() for t in all_types]
ax.set_xticks(x)
ax.set_xticklabels(type_labels, rotation=30, ha='right', fontsize=10)
ax.set_ylabel('Count', fontsize=11)
ax.set_title('Issue Types by Severity Level', fontsize=13)
ax.legend(fontsize=10)
plt.tight_layout()
plt.savefig(ASSETS_DIR / 'fig_error_types.png', dpi=150, bbox_inches='tight')
plt.close()
print('Saved fig_error_types.png')

# ── Graph 3: Per-paper stacked bar chart ──
fig, ax = plt.subplots(figsize=(12, 6))
y = np.arange(len(paper_names))
height = 0.6

bars_err = ax.barh(y, paper_err, height, label='Errors', color=COLORS['error'])
bars_warn = ax.barh(y, paper_warn, height, left=paper_err, label='Warnings', color=COLORS['warning'])
bars_info = ax.barh(y, paper_info, height,
                    left=[e + w for e, w in zip(paper_err, paper_warn)],
                    label='Informational', color=COLORS['info'])

ax.set_yticks(y)
ax.set_yticklabels(paper_names, fontsize=9)
ax.set_xlabel('Number of References with Issues', fontsize=11)
ax.set_title('Reference Issues by Paper', fontsize=13)
ax.legend(loc='lower right', fontsize=10)
ax.invert_yaxis()
plt.tight_layout()
plt.savefig(ASSETS_DIR / 'fig_per_paper.png', dpi=150, bbox_inches='tight')
plt.close()
print('Saved fig_per_paper.png')

# ── Graph 4: Most common specific issues ──
# Group by the actual detail patterns
detail_patterns = {
    'Missing URL': 0,
    'Year mismatch': 0,
    'Venue mismatch': 0,
    'Author mismatch': 0,
    'Invalid arXiv ID': 0,
    'Title mismatch': 0,
    'Unverified': 0,
    'DOI issue': 0,
}
for rec in data['records']:
    for orig in rec.get('_original_errors', []):
        details = (orig.get('error_details') or orig.get('warning_details') or orig.get('info_details') or '').lower()
        etype = orig.get('error_type') or orig.get('warning_type') or orig.get('info_type') or ''
        if etype == 'url':
            detail_patterns['Missing URL'] += 1
        elif etype == 'year':
            detail_patterns['Year mismatch'] += 1
        elif 'venue' in etype:
            detail_patterns['Venue mismatch'] += 1
        elif etype == 'author':
            detail_patterns['Author mismatch'] += 1
        elif etype == 'arxiv_id':
            detail_patterns['Invalid arXiv ID'] += 1
        elif etype == 'title':
            detail_patterns['Title mismatch'] += 1
        elif etype == 'unverified':
            detail_patterns['Unverified'] += 1
        elif etype == 'doi':
            detail_patterns['DOI issue'] += 1

fig, ax = plt.subplots(figsize=(8, 5))
sorted_patterns = sorted(detail_patterns.items(), key=lambda x: -x[1])
names = [p[0] for p in sorted_patterns if p[1] > 0]
values = [p[1] for p in sorted_patterns if p[1] > 0]
bar_colors = []
for name in names:
    if name in ('Missing URL',):
        bar_colors.append(COLORS['info'])
    elif name in ('Year mismatch', 'Venue mismatch', 'DOI issue'):
        bar_colors.append(COLORS['warning'])
    else:
        bar_colors.append(COLORS['error'])

bars = ax.barh(range(len(names)), values, color=bar_colors, height=0.6)
ax.set_yticks(range(len(names)))
ax.set_yticklabels(names, fontsize=11)
ax.set_xlabel('Count', fontsize=11)
ax.set_title('Most Common Issue Categories\n(color = typical severity)', fontsize=13)
ax.invert_yaxis()

# Add count labels
for bar, val in zip(bars, values):
    ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2., str(val),
            va='center', fontsize=10)

plt.tight_layout()
plt.savefig(ASSETS_DIR / 'fig_issue_categories.png', dpi=150, bbox_inches='tight')
plt.close()
print('Saved fig_issue_categories.png')

print('\nAll graphs generated successfully.')
