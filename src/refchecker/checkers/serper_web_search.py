"""
Serper Web Search Checker for Hallucination Detection

Uses Serper's Google Search API to check whether a flagged reference
appears on the open web.  This provides a complementary signal to
academic database lookups — if even Google cannot find a paper, that
strongly suggests it is fabricated.

Runs only on already-flagged hallucination candidates as a
supplementary signal (never the sole basis for flagging).

API docs : https://serper.dev/
Free tier: 2,500 queries / month
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# Domains whose presence in search results is strong evidence a paper exists.
ACADEMIC_DOMAINS = frozenset({
    'arxiv.org',
    'semanticscholar.org',
    'scholar.google.com',
    'openreview.net',
    'aclanthology.org',
    'proceedings.mlr.press',
    'papers.nips.cc',
    'proceedings.neurips.cc',
    'ieee.org',
    'ieeexplore.ieee.org',
    'acm.org',
    'dl.acm.org',
    'springer.com',
    'link.springer.com',
    'sciencedirect.com',
    'nature.com',
    'wiley.com',
    'onlinelibrary.wiley.com',
    'plos.org',
    'biorxiv.org',
    'medrxiv.org',
    'dblp.org',
    'researchgate.net',
    'academic.oup.com',
    'pubmed.ncbi.nlm.nih.gov',
})

# Score deltas applied to the hallucination assessment.
# Negative values = evidence the paper is real (reduces suspicion).
DELTA_STRONG_HIT = -0.15     # ≥ 2 academic-domain results
DELTA_MODERATE_HIT = -0.10   # exactly 1 academic-domain result
DELTA_NO_RESULTS = 0.05      # zero organic results at all
DELTA_INCONCLUSIVE = 0.0     # non-academic results only


class SerperWebSearchChecker:
    """Verify references via Google web search using the Serper API."""

    SEARCH_URL = 'https://google.serper.dev/search'
    REQUEST_TIMEOUT = 10

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (
            api_key
            or os.getenv('SERPER_API_KEY')
            or os.getenv('REFCHECKER_SERPER_API_KEY')
        )

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_reference_exists(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Search for a flagged reference on the open web.

        Returns a dict with:
            found        – whether credible academic hits were found
            score_delta  – adjustment to hallucination score
            academic_urls – matching academic URLs (up to 5)
            query        – the search query used
        """
        title = record.get('ref_title', '')
        authors = record.get('ref_authors_cited', '')

        if not title:
            return _result(False, 0.0, [], '')

        query = f'"{title}"'
        first_author = _extract_first_author(authors)
        if first_author:
            query += f' {first_author}'

        try:
            results = self._search(query)
        except Exception as exc:
            logger.warning(f'Serper web search failed: {exc}')
            return _result(False, 0.0, [], query)

        academic_urls = _extract_academic_urls(results)

        if len(academic_urls) >= 2:
            return _result(True, DELTA_STRONG_HIT, academic_urls[:5], query)

        if len(academic_urls) == 1:
            return _result(True, DELTA_MODERATE_HIT, academic_urls, query)

        # No academic hits — check whether there are *any* organic results.
        if not results.get('organic'):
            return _result(False, DELTA_NO_RESULTS, [], query)

        return _result(False, DELTA_INCONCLUSIVE, [], query)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _search(self, query: str) -> Dict[str, Any]:
        """Execute a Serper search request."""
        resp = requests.post(
            self.SEARCH_URL,
            json={'q': query, 'num': 10},
            headers={
                'X-API-KEY': self.api_key,
                'Content-Type': 'application/json',
            },
            timeout=self.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()


# ------------------------------------------------------------------
# Module-level helpers (easier to unit-test without instantiation)
# ------------------------------------------------------------------

def _result(found: bool, score_delta: float, academic_urls: List[str], query: str) -> Dict[str, Any]:
    return {
        'found': found,
        'score_delta': score_delta,
        'academic_urls': academic_urls,
        'query': query,
    }


def _is_academic_url(url: str) -> bool:
    """Return True when *url* belongs to a known academic domain."""
    try:
        domain = urlparse(url).hostname or ''
        domain = re.sub(r'^www\.', '', domain).lower()
        return any(domain == d or domain.endswith('.' + d) for d in ACADEMIC_DOMAINS)
    except Exception:
        return False


def _extract_academic_urls(results: Dict[str, Any]) -> List[str]:
    """Filter organic search results to those on academic domains."""
    return [
        item['link']
        for item in results.get('organic', [])
        if _is_academic_url(item.get('link', ''))
    ]


def _extract_first_author(authors_str: str) -> str:
    """Return the last name of the first listed author."""
    if not authors_str:
        return ''
    first = authors_str.split(',')[0].split(' and ')[0].strip()
    parts = first.split()
    return parts[-1] if parts else ''
