import requests, time, os

headers = {}
key = os.getenv('SEMANTIC_SCHOLAR_API_KEY')
if key:
    headers['x-api-key'] = key

fields = 'title,authors,year,externalIds,url,venue,publicationVenue,journal'

# Test 1: search endpoint (current)
start = time.perf_counter()
r1 = requests.get('https://api.semanticscholar.org/graph/v1/paper/search',
    params={'query': 'Decision transformer Reinforcement learning via sequence modeling', 'limit': 10, 'fields': fields},
    headers=headers, timeout=30)
t1 = time.perf_counter() - start

time.sleep(1)

# Test 2: match endpoint (proposed)
start = time.perf_counter()
r2 = requests.get('https://api.semanticscholar.org/graph/v1/paper/search/match',
    params={'query': 'Decision transformer Reinforcement learning via sequence modeling', 'fields': fields},
    headers=headers, timeout=30)
t2 = time.perf_counter() - start

time.sleep(1)

# Test 3: direct ARXIV ID lookup
start = time.perf_counter()
r3 = requests.get('https://api.semanticscholar.org/graph/v1/paper/ARXIV:2106.01345',
    params={'fields': fields},
    headers=headers, timeout=30)
t3 = time.perf_counter() - start

print(f'Search endpoint:     {t1:.2f}s  status={r1.status_code}')
print(f'Match endpoint:      {t2:.2f}s  status={r2.status_code}')
print(f'Direct ARXIV lookup: {t3:.2f}s  status={r3.status_code}')

if r1.status_code == 200:
    d = r1.json().get('data', [])
    print(f'  Search results: {len(d)}')
if r2.status_code == 200:
    d = r2.json().get('data', [])
    print(f'  Match results: {len(d)}, title: {d[0]["title"] if d else "?"}')
if r3.status_code == 200:
    d = r3.json()
    print(f'  Direct result: {d.get("title", "?")}')
