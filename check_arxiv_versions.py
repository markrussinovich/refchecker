"""
Check ArXiv historical versions to see if cited metadata matches any version.
"""
import requests
import re
import html
import time

def fetch_version_metadata(arxiv_id: str, version: int) -> dict:
    """Fetch metadata for a specific ArXiv version."""
    url = f"https://arxiv.org/abs/{arxiv_id}v{version}"
    
    try:
        print(f"  Fetching {url}...")
        response = requests.get(url, timeout=30)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        html_content = response.text
        
        # Parse title
        title_match = re.search(r'<meta name="citation_title" content="(.*?)"', html_content)
        title = html.unescape(title_match.group(1)).strip() if title_match else ""
        
        # Parse authors
        authors = []
        for auth in re.findall(r'<meta name="citation_author" content="(.*?)"', html_content):
            authors.append(html.unescape(auth).strip())
        
        # Parse dateline
        dateline_match = re.search(r'<div class="dateline">(.*?)</div>', html_content, re.DOTALL)
        dateline = ""
        if dateline_match:
            dateline_html = dateline_match.group(1)
            dateline = re.sub(r'<[^>]+>', '', dateline_html).strip()
            dateline = html.unescape(dateline)
        
        return {
            'version': f'v{version}',
            'title': title,
            'authors': authors,
            'dateline': dateline,
            'url': url
        }
    except Exception as e:
        print(f"  Error: {e}")
        return None


def get_all_versions(arxiv_id: str) -> list:
    """Get metadata for all versions of an ArXiv paper."""
    versions = []
    for v in range(1, 20):  # Check up to v19
        time.sleep(0.5)  # Rate limiting
        meta = fetch_version_metadata(arxiv_id, v)
        if meta is None:
            break  # No more versions
        versions.append(meta)
    return versions


# Papers from the database with ArXiv errors
papers_to_check = [
    {
        'arxiv_id': '1911.11641',
        'title': 'PIQA: Reasoning about Physical Commonsense in Natural Language',
        'cited_author': 'Ari Holtzman',
        'issue': 'Author mismatch - Ari Holtzman not in author list'
    },
    {
        'arxiv_id': '2209.02299', 
        'title': 'A Survey of Machine Unlearning',
        'cited_authors_count': 6,
        'actual_authors_count': 7,
        'issue': 'Author count mismatch - 6 cited vs 7 correct (missing Zhao Ren)'
    }
]

print("="*80)
print("Checking ArXiv historical versions for papers with errors")
print("="*80)
print()

for paper in papers_to_check:
    arxiv_id = paper['arxiv_id']
    print(f"\n{'='*80}")
    print(f"Paper: {paper['title']}")
    print(f"ArXiv ID: {arxiv_id}")
    print(f"Issue: {paper['issue']}")
    print("="*80)
    
    versions = get_all_versions(arxiv_id)
    
    print(f"\nFound {len(versions)} versions:\n")
    
    for v in versions:
        print(f"  {v['version']}: {len(v['authors'])} authors")
        print(f"    Authors: {', '.join(v['authors'][:5])}{'...' if len(v['authors']) > 5 else ''}")
        print(f"    Dateline: {v['dateline']}")
        print()
    
    # Check if any version matches the cited data
    if 'cited_author' in paper:
        # Check if cited author appears in any version
        cited = paper['cited_author'].lower()
        for v in versions:
            authors_lower = [a.lower() for a in v['authors']]
            if any(cited in a for a in authors_lower):
                print(f"  ✓ MATCH FOUND: {paper['cited_author']} appears in {v['version']}")
                print(f"    This would convert the error to a warning!")
                break
        else:
            print(f"  ✗ No match: {paper['cited_author']} not found in any version")
    
    if 'cited_authors_count' in paper:
        # Check if any version has the cited author count
        for v in versions:
            if len(v['authors']) == paper['cited_authors_count']:
                print(f"  ✓ MATCH FOUND: {v['version']} has {len(v['authors'])} authors (matches cited)")
                print(f"    This would convert the error to a warning!")
                break
        else:
            print(f"  ✗ No version has {paper['cited_authors_count']} authors")

print("\n" + "="*80)
print("Summary: Papers where historical version matching would help")
print("="*80)
