"""
Web Search Checker for Hallucination Detection

Searches the open web to check whether a flagged reference actually exists.
This provides a complementary signal to academic database lookups — if even
a general web search cannot find a paper, that strongly suggests it is
fabricated.

The checker is provider-agnostic: concrete ``WebSearchProvider`` subclasses
handle the API calls while ``WebSearchChecker`` owns the scoring logic.

Supported providers
-------------------
* **Brave Search**  – https://brave.com/search/api/  (free tier ≈ 1,000 queries/month)
* **Serper**        – https://serper.dev/             (free tier: 2,500 queries/month)

Set the corresponding environment variable to enable a provider:
    BRAVE_SEARCH_API_KEY   or   SERPER_API_KEY

If multiple keys are present the first available provider is used
(Brave preferred by default — override with ``preferred_provider``).
"""

from __future__ import annotations

import abc
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Academic domain list (shared by all providers)
# ------------------------------------------------------------------

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
DELTA_STRONG_HIT = -0.15     # ≥ 2 academic-domain results
DELTA_MODERATE_HIT = -0.10   # exactly 1 academic-domain result
DELTA_NO_RESULTS = 0.05      # zero organic results at all
DELTA_INCONCLUSIVE = 0.0     # non-academic results only


# ══════════════════════════════════════════════════════════════════════
# Abstract provider
# ══════════════════════════════════════════════════════════════════════

class WebSearchProvider(abc.ABC):
    """Abstract interface for a web search backend.

    Subclasses must implement ``search`` which returns a list of
    ``SearchResult`` dicts, each with at least a ``link`` key.
    """

    name: str = 'base'

    @abc.abstractmethod
    def search(self, query: str, num_results: int = 10) -> List[Dict[str, str]]:
        """Execute a web search and return organic results.

        Each result dict must contain at least::

            {'link': 'https://...', 'title': '...', 'snippet': '...'}
        """

    @property
    @abc.abstractmethod
    def available(self) -> bool:
        """Return True when the provider has valid credentials."""


# ══════════════════════════════════════════════════════════════════════
# Brave Search provider
# ══════════════════════════════════════════════════════════════════════

class BraveSearchProvider(WebSearchProvider):
    """Brave Search API provider.

    Docs : https://api.search.brave.com/app/documentation/web-search
    Free : ~1,000 queries/month ($5 credit)
    Key  : BRAVE_SEARCH_API_KEY or REFCHECKER_BRAVE_SEARCH_API_KEY
    """

    name = 'brave'
    SEARCH_URL = 'https://api.search.brave.com/res/v1/web/search'
    REQUEST_TIMEOUT = 10

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (
            api_key
            or os.getenv('BRAVE_SEARCH_API_KEY')
            or os.getenv('REFCHECKER_BRAVE_SEARCH_API_KEY')
        )

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, num_results: int = 10) -> List[Dict[str, str]]:
        resp = requests.get(
            self.SEARCH_URL,
            params={'q': query, 'count': num_results},
            headers={
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip',
                'X-Subscription-Token': self.api_key,
            },
            timeout=self.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in (data.get('web', {}).get('results', [])):
            results.append({
                'link': item.get('url', ''),
                'title': item.get('title', ''),
                'snippet': item.get('description', ''),
            })
        return results


# ══════════════════════════════════════════════════════════════════════
# Serper (Google) provider
# ══════════════════════════════════════════════════════════════════════

class SerperSearchProvider(WebSearchProvider):
    """Serper Google Search API provider.

    Docs : https://serper.dev/
    Free : 2,500 queries/month
    Key  : SERPER_API_KEY or REFCHECKER_SERPER_API_KEY
    """

    name = 'serper'
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

    def search(self, query: str, num_results: int = 10) -> List[Dict[str, str]]:
        resp = requests.post(
            self.SEARCH_URL,
            json={'q': query, 'num': num_results},
            headers={
                'X-API-KEY': self.api_key,
                'Content-Type': 'application/json',
            },
            timeout=self.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get('organic', []):
            results.append({
                'link': item.get('link', ''),
                'title': item.get('title', ''),
                'snippet': item.get('snippet', ''),
            })
        return results


# ══════════════════════════════════════════════════════════════════════
# Provider-agnostic checker
# ══════════════════════════════════════════════════════════════════════

# Default preference order when auto-selecting a provider.
_PROVIDER_CLASSES: List[type] = [BraveSearchProvider, SerperSearchProvider]


class WebSearchChecker:
    """Verify references via web search using any ``WebSearchProvider``."""

    def __init__(self, provider: Optional[WebSearchProvider] = None):
        self.provider = provider

    @property
    def available(self) -> bool:
        return self.provider is not None and self.provider.available

    def check_reference_exists(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Search for a flagged reference on the open web.

        Returns a dict with:
            found         – whether credible academic hits were found
            score_delta   – adjustment to hallucination score
            academic_urls – matching academic URLs (up to 5)
            query         – the search query used
            provider      – name of the search provider used
        """
        title = record.get('ref_title', '')
        authors = record.get('ref_authors_cited', '')

        if not title:
            return _result(False, 0.0, [], '', self._provider_name)

        query = f'"{title}"'
        first_author = _extract_first_author(authors)
        if first_author:
            query += f' {first_author}'

        try:
            organic = self.provider.search(query)
        except Exception as exc:
            logger.warning(f'{self._provider_name} web search failed: {exc}')
            return _result(False, 0.0, [], query, self._provider_name)

        academic_urls = _extract_academic_urls_from_results(organic)

        if len(academic_urls) >= 2:
            return _result(True, DELTA_STRONG_HIT, academic_urls[:5], query, self._provider_name)

        if len(academic_urls) == 1:
            return _result(True, DELTA_MODERATE_HIT, academic_urls, query, self._provider_name)

        if not organic:
            return _result(False, DELTA_NO_RESULTS, [], query, self._provider_name)

        return _result(False, DELTA_INCONCLUSIVE, [], query, self._provider_name)

    @property
    def _provider_name(self) -> str:
        return self.provider.name if self.provider else 'none'


def create_web_search_checker(preferred_provider: Optional[str] = None) -> WebSearchChecker:
    """Factory: auto-detect available provider from environment variables.

    Parameters
    ----------
    preferred_provider : str, optional
        Force a specific provider (``'brave'`` or ``'serper'``).
        If *None*, tries providers in default preference order.
    """
    if preferred_provider:
        for cls in _PROVIDER_CLASSES:
            if cls.name == preferred_provider:
                provider = cls()
                if provider.available:
                    return WebSearchChecker(provider)
                logger.debug(f'{cls.name} provider requested but no API key found')
                return WebSearchChecker(None)

    for cls in _PROVIDER_CLASSES:
        provider = cls()
        if provider.available:
            logger.debug(f'Auto-selected web search provider: {cls.name}')
            return WebSearchChecker(provider)

    return WebSearchChecker(None)


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _result(
    found: bool,
    score_delta: float,
    academic_urls: List[str],
    query: str,
    provider: str = '',
) -> Dict[str, Any]:
    return {
        'found': found,
        'score_delta': score_delta,
        'academic_urls': academic_urls,
        'query': query,
        'provider': provider,
    }


def is_academic_url(url: str) -> bool:
    """Return True when *url* belongs to a known academic domain."""
    try:
        domain = urlparse(url).hostname or ''
        domain = re.sub(r'^www\.', '', domain).lower()
        return any(domain == d or domain.endswith('.' + d) for d in ACADEMIC_DOMAINS)
    except Exception:
        return False


def _extract_academic_urls_from_results(results: List[Dict[str, str]]) -> List[str]:
    """Filter search results to those on academic domains."""
    return [r['link'] for r in results if is_academic_url(r.get('link', ''))]


def _extract_first_author(authors_str: str) -> str:
    """Return the last name of the first listed author."""
    if not authors_str:
        return ''
    first = authors_str.split(',')[0].split(' and ')[0].strip()
    parts = first.split()
    return parts[-1] if parts else ''
