#!/usr/bin/env python3
"""Quick test of Semantic Scholar batch and title-match APIs."""
import requests
import json
import time
import os

SS_API_KEY = os.getenv('SEMANTIC_SCHOLAR_API_KEY')
headers = {}
if SS_API_KEY:
    headers['x-api-key'] = SS_API_KEY
    print(f'Using SS API key: {SS_API_KEY[:8]}...')
else:
    print('No SS API key set (lower rate limits)')

# ── Test 1: POST /paper/batch with known IDs ──
batch_ids = [
    'ARXIV:1706.03762',        # Attention Is All You Need
    'ARXIV:1512.03385',        # Deep Residual Learning
    'DOI:10.18653/v1/N18-3011',  # Construction of Literature Graph
    'ARXIV:9999.99999',        # Non-existent (should return null)
]

url = 'https://api.semanticscholar.org/graph/v1/paper/batch'
params = {'fields': 'title,authors,year,externalIds,url,venue,publicationVenue,journal'}
payload = {'ids': batch_ids}

print(f'\n=== Batch API: {len(batch_ids)} papers ===')
start = time.perf_counter()
resp = requests.post(url, params=params, json=payload, headers=headers, timeout=30)
elapsed = time.perf_counter() - start
print(f'Status: {resp.status_code}, Time: {elapsed:.2f}s')

if resp.status_code == 200:
    results = resp.json()
    print(f'Results: {len(results)} items')
    for i, paper in enumerate(results):
        if paper is None:
            print(f'  [{i}] {batch_ids[i]} -> NULL (not found)')
        else:
            title = paper.get('title', '?')[:60]
            year = paper.get('year', '?')
            authors = [a.get('name', '?') for a in paper.get('authors', [])[:3]]
            print(f'  [{i}] {batch_ids[i]} -> {title} ({year}) by {", ".join(authors)}...')
else:
    print(f'Error: {resp.text[:300]}')

# ── Test 2: Compare batch vs individual timing ──
individual_ids = ['ARXIV:1706.03762', 'ARXIV:1512.03385', 'ARXIV:2106.01345', 'ARXIV:1810.04805', 'ARXIV:2005.14165']
fields = 'title,authors,year,externalIds,url,venue,publicationVenue,journal'

print(f'\n=== Timing: batch vs individual for {len(individual_ids)} papers ===')

# Individual requests
start_ind = time.perf_counter()
ind_results = []
for pid in individual_ids:
    r = requests.get(
        f'https://api.semanticscholar.org/graph/v1/paper/{pid}',
        params={'fields': fields},
        headers=headers,
        timeout=30,
    )
    ind_results.append(r.status_code)
    time.sleep(0.5)  # be polite
elapsed_ind = time.perf_counter() - start_ind

# Batch request
start_batch = time.perf_counter()
r_batch = requests.post(
    'https://api.semanticscholar.org/graph/v1/paper/batch',
    params={'fields': fields},
    json={'ids': individual_ids},
    headers=headers,
    timeout=30,
)
elapsed_batch = time.perf_counter() - start_batch

print(f'Individual: {elapsed_ind:.2f}s ({len(individual_ids)} calls, statuses: {ind_results})')
print(f'Batch:      {elapsed_batch:.2f}s (1 call, status: {r_batch.status_code})')
print(f'Speedup:    {elapsed_ind / elapsed_batch:.1f}x')

if r_batch.status_code == 200:
    batch_data = r_batch.json()
    found = sum(1 for p in batch_data if p is not None)
    print(f'Batch found: {found}/{len(individual_ids)} papers')

# ── Test 3: Title match endpoint ──
print(f'\n=== Title match API ===')
start_tm = time.perf_counter()
r_tm = requests.get(
    'https://api.semanticscholar.org/graph/v1/paper/search/match',
    params={'query': 'Attention Is All You Need', 'fields': fields},
    headers=headers,
    timeout=30,
)
elapsed_tm = time.perf_counter() - start_tm
print(f'Status: {r_tm.status_code}, Time: {elapsed_tm:.2f}s')
if r_tm.status_code == 200:
    data = r_tm.json().get('data', [])
    if data:
        p = data[0]
        print(f'  Match: {p.get("title", "?")} (score={p.get("matchScore", "?")})')
