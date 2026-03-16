import json, re, sys

p = json.load(open(sys.argv[1], encoding='utf-8'))
records = p.get('records', [])

ax = 0
doi_count = 0
neither = 0
for r in records:
    orig = r.get('original_reference', {})
    url = orig.get('url', '') or r.get('ref_url_cited', '')
    doi = orig.get('doi', '')
    if url and re.search(r'arxiv\.org/(?:abs|pdf)/\d{4}\.\d{4,5}', url):
        ax += 1
    elif doi and doi.startswith('10.'):
        doi_count += 1
    else:
        neither += 1

t = len(records)
total_refs = p['summary']['total_references_processed']
print(f"Total refs processed: {total_refs}")
print(f"Error records: {t}")
print(f"  with ArXiv URL: {ax} ({ax*100//max(t,1)}%)")
print(f"  with DOI: {doi_count} ({doi_count*100//max(t,1)}%)")
print(f"  with NEITHER: {neither} ({neither*100//max(t,1)}%)")
print(f"Batch-eligible: {ax + doi_count} ({(ax+doi_count)*100//max(t,1)}%)")
