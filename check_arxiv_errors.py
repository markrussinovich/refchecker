import sqlite3
import json

conn = sqlite3.connect('backend/refchecker_history.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get table schema
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print('Tables:', [t[0] for t in tables])

# Check the structure of check_history
cursor.execute('PRAGMA table_info(check_history)')
cols = cursor.fetchall()
print('\ncheck_history columns:', [c[1] for c in cols])

# Get all check results
cursor.execute("SELECT id, paper_title, results_json FROM check_history WHERE results_json IS NOT NULL LIMIT 5")
rows = cursor.fetchall()

print(f"\nSample of {len(rows)} check history entries:\n")

for row in rows:
    print(f"Check #{row['id']}: {row['paper_title']}")
    try:
        results = json.loads(row['results_json'])
        if results and len(results) > 0:
            # Show first result structure
            first = results[0]
            print(f"  First ref keys: {list(first.keys()) if isinstance(first, dict) else type(first)}")
            if isinstance(first, dict):
                print(f"  Title: {first.get('title', '')[:60]}")
                print(f"  URL: {first.get('url', '')}")
                print(f"  Errors: {first.get('errors', [])}")
                print(f"  Warnings: {first.get('warnings', [])}")
    except Exception as e:
        print(f"  Error parsing: {e}")
    print()

# Now look for ALL arxiv references
print("\n" + "="*80)
print("Looking for ArXiv references with any errors or warnings...")
print("="*80 + "\n")

cursor.execute("SELECT id, paper_title, results_json FROM check_history WHERE results_json IS NOT NULL")
rows = cursor.fetchall()

arxiv_refs = []

for row in rows:
    check_id = row['id']
    paper_title = row['paper_title']
    try:
        results = json.loads(row['results_json'])
        if not results:
            continue
            
        for ref in results:
            if not isinstance(ref, dict):
                continue
            
            # Look for ArXiv references - check more fields
            url = str(ref.get('url', '') or '')
            verified_url = str(ref.get('verified_url', '') or '')
            raw_text = str(ref.get('raw_text', '') or '')
            venue = str(ref.get('venue', '') or '')
            cited_url = str(ref.get('cited_url', '') or '')
            auth_urls = ref.get('authoritative_urls', []) or []
            auth_urls_str = ' '.join(str(u) for u in auth_urls) if auth_urls else ''
            
            all_text = f"{url} {verified_url} {raw_text} {venue} {cited_url} {auth_urls_str}".lower()
            is_arxiv = 'arxiv' in all_text
            
            if is_arxiv:
                errors = ref.get('errors', [])
                warnings = ref.get('warnings', [])
                
                # Check for title, author, or year issues
                has_relevant_issue = False
                issues = []
                
                for err in (errors if errors else []):
                    if isinstance(err, dict):
                        err_type = err.get('error_type', '')
                        if err_type in ['title', 'author', 'year']:
                            has_relevant_issue = True
                            issues.append(('ERROR', err))
                
                for warn in (warnings if warnings else []):
                    if isinstance(warn, dict):
                        warn_type = warn.get('warning_type', '')
                        if warn_type in ['title', 'author', 'year', 'version']:
                            issues.append(('WARNING', warn))
                
                if has_relevant_issue or issues:
                    arxiv_refs.append({
                        'check_id': check_id,
                        'paper': paper_title,
                        'ref_title': ref.get('title', '')[:80],
                        'url': url or verified_url or cited_url or (auth_urls[0] if auth_urls else ''),
                        'venue': venue,
                        'issues': issues,
                        'has_error': has_relevant_issue
                    })
    except json.JSONDecodeError:
        continue

print(f"Found {len(arxiv_refs)} ArXiv references with title/author/year issues:\n")

# Group by those with errors (candidates for conversion to warnings)
error_refs = [r for r in arxiv_refs if r['has_error']]
print(f"Of these, {len(error_refs)} have ERRORS (would be converted to warnings if version matches):\n")

for i, ref in enumerate(error_refs[:30]):
    print(f"{i+1}. Check #{ref['check_id']} - {ref['paper']}")
    print(f"   Ref: {ref['ref_title']}")
    print(f"   Venue: {ref['venue']}")
    print(f"   URL: {ref['url']}")
    for issue_type, issue in ref['issues']:
        print(f"   {issue_type}: {issue}")
    print()

conn.close()
