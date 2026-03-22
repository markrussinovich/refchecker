"""
Web Search Checker for Hallucination Detection

Searches the open web to check whether a flagged reference actually exists.
This provides a complementary signal to academic database lookups — if even
a general web search cannot find a paper, that strongly suggests it is
fabricated.

The checker is provider-agnostic: concrete ``WebSearchProvider`` subclasses
handle the API calls while ``WebSearchChecker`` owns the scoring logic.

Supported providers (reuse the same API keys used for reference extraction)
---------------------------------------------------------------------------
* **OpenAI**  – Responses API with ``web_search_preview`` tool
               (uses OPENAI_API_KEY, ~$0.01 per search)
* **Gemini**  -- Google Search grounding via ``google-genai``
               (uses GOOGLE_API_KEY)

The first available provider is used automatically (OpenAI preferred).
"""

from __future__ import annotations

import abc
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from refchecker.config.settings import resolve_api_key, resolve_endpoint

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
    result dicts, each with at least a ``link`` key.
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
# OpenAI Responses API provider (web_search_preview tool)
# ══════════════════════════════════════════════════════════════════════

class OpenAISearchProvider(WebSearchProvider):
    """OpenAI web search via the Responses API.

    Reuses the same key as reference extraction (OPENAI_API_KEY).
    Cost: ~$0.01 per search call + token costs.

    Sends the full reference metadata to the model and asks it to search
    the web and assess whether the paper exists.
    """

    name = 'openai'

    _SYSTEM_PROMPT = (
        'You are an academic reference verifier. The user will give you the '
        'title, authors, venue, and year of an academic paper. Use web search '
        'to determine whether this EXACT paper exists.\n\n'
        'Respond with EXACTLY one of these verdicts on the first line:\n'
        '  EXISTS   — you found this specific paper (matching title and at least one author)\n'
        '  NOT_FOUND — web search returned no credible evidence this paper exists\n'
        '  UNSURE   — results are ambiguous (similar but not identical papers found)\n\n'
        'Then on the following lines, briefly explain your reasoning (2-3 sentences max). '
        'If you found the paper, include the URL(s) where it appears.'
    )

    def __init__(self, api_key: Optional[str] = None, endpoint: Optional[str] = None):
        self.api_key = resolve_api_key('openai', override=api_key)
        self.endpoint = resolve_endpoint('openai', override=endpoint)
        self._client = None

        if self.api_key:
            try:
                import openai
                kwargs: Dict[str, Any] = {'api_key': self.api_key}
                if self.endpoint:
                    base = self.endpoint
                    for suffix in ('/chat/completions', '/completions'):
                        if base.endswith(suffix):
                            base = base[: -len(suffix)]
                    kwargs['base_url'] = base
                self._client = openai.OpenAI(**kwargs)
            except ImportError:
                logger.debug('openai package not installed')

    @property
    def available(self) -> bool:
        return self._client is not None

    def search(self, query: str, num_results: int = 10) -> List[Dict[str, str]]:
        response = self._client.responses.create(
            model='gpt-4o-mini',
            instructions=self._SYSTEM_PROMPT,
            tools=[{'type': 'web_search_preview'}],
            input=query,
        )

        # Extract the verdict text and any cited URLs
        verdict_text = ''
        results: List[Dict[str, str]] = []
        seen_urls: set = set()

        for item in response.output:
            content = getattr(item, 'content', None)
            if not content:
                continue
            for block in content:
                text = getattr(block, 'text', '') or ''
                if text:
                    verdict_text += text + '\n'
                for ann in getattr(block, 'annotations', []):
                    url = getattr(ann, 'url', '') or ''
                    title = getattr(ann, 'title', '') or ''
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        results.append({
                            'link': url,
                            'title': title,
                            'snippet': '',
                        })

        # Stash verdict text on the results so the checker can use it
        if results:
            results[0]['_verdict_text'] = verdict_text.strip()
        elif verdict_text.strip():
            results.append({
                'link': '',
                'title': '',
                'snippet': '',
                '_verdict_text': verdict_text.strip(),
            })

        return results


# ══════════════════════════════════════════════════════════════════════
# Google Gemini provider (Google Search grounding)
# ══════════════════════════════════════════════════════════════════════

class GeminiSearchProvider(WebSearchProvider):
    """Google Gemini with Google Search grounding.

    Reuses the same key as reference extraction (GOOGLE_API_KEY).
    """

    name = 'gemini'

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = resolve_api_key('google', override=api_key)
        self._client = None

        if self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except ImportError:
                logger.debug('google-genai package not installed')

    @property
    def available(self) -> bool:
        return self._client is not None

    def search(self, query: str, num_results: int = 10) -> List[Dict[str, str]]:
        response = self._client.models.generate_content(
            model='gemini-2.5-flash',
            contents=query,
            config={
                'tools': [{'google_search': {}}],
                'temperature': 0.0,
            },
        )

        results: List[Dict[str, str]] = []
        seen_urls: set = set()

        # Extract grounding source URLs from metadata
        candidate = response.candidates[0] if response.candidates else None
        metadata = getattr(candidate, 'grounding_metadata', None)
        chunks = getattr(metadata, 'grounding_chunks', None) or []
        for chunk in chunks:
            web = getattr(chunk, 'web', None)
            if web:
                url = getattr(web, 'uri', '') or ''
                title = getattr(web, 'title', '') or ''
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append({'link': url, 'title': title, 'snippet': ''})

        return results


# ══════════════════════════════════════════════════════════════════════
# Provider-agnostic checker
# ══════════════════════════════════════════════════════════════════════

# Default preference order when auto-selecting a provider.
_PROVIDER_CLASSES: List[type] = [OpenAISearchProvider, GeminiSearchProvider]


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
            verdict       – LLM verdict (EXISTS / NOT_FOUND / UNSURE)
            explanation   – LLM reasoning text
        """
        title = record.get('ref_title', '')
        authors = record.get('ref_authors_cited', '')
        year = record.get('ref_year_cited', '')
        venue = record.get('ref_venue_cited', '') or record.get('source_title', '')

        if not title:
            return _result(False, 0.0, [], '', self._provider_name)

        # Build a rich prompt with the full reference metadata
        lines = [f'Title: {title}']
        if authors:
            lines.append(f'Authors: {authors}')
        if year:
            lines.append(f'Year: {year}')
        if venue:
            lines.append(f'Venue: {venue}')
        query = '\n'.join(lines)

        try:
            raw_results = self.provider.search(query)
        except Exception as exc:
            logger.warning(f'{self._provider_name} web search failed: {exc}')
            return _result(False, 0.0, [], query, self._provider_name)

        # Extract the LLM verdict from the stashed text
        verdict_text = ''
        for r in raw_results:
            verdict_text = r.pop('_verdict_text', '') or verdict_text

        verdict = _parse_verdict(verdict_text)
        academic_urls = _extract_academic_urls_from_results(raw_results)

        # Score based on the LLM verdict rather than just URL counting
        if verdict == 'EXISTS' and academic_urls:
            delta = DELTA_STRONG_HIT if len(academic_urls) >= 2 else DELTA_MODERATE_HIT
            return _result(True, delta, academic_urls[:5], query, self._provider_name,
                           verdict=verdict, explanation=verdict_text)

        if verdict == 'EXISTS':
            # LLM says exists but no academic URLs extracted
            return _result(True, DELTA_MODERATE_HIT, [], query, self._provider_name,
                           verdict=verdict, explanation=verdict_text)

        if verdict == 'NOT_FOUND':
            return _result(False, DELTA_NO_RESULTS, [], query, self._provider_name,
                           verdict=verdict, explanation=verdict_text)

        # UNSURE or unparseable — fall back to URL-based heuristic
        if academic_urls:
            delta = DELTA_STRONG_HIT if len(academic_urls) >= 2 else DELTA_MODERATE_HIT
            return _result(True, delta, academic_urls[:5], query, self._provider_name,
                           verdict=verdict, explanation=verdict_text)

        if not raw_results or all(not r.get('link') for r in raw_results):
            return _result(False, DELTA_NO_RESULTS, [], query, self._provider_name,
                           verdict=verdict, explanation=verdict_text)

        return _result(False, DELTA_INCONCLUSIVE, [], query, self._provider_name,
                       verdict=verdict, explanation=verdict_text)

    @property
    def _provider_name(self) -> str:
        return self.provider.name if self.provider else 'none'


def create_web_search_checker(preferred_provider: Optional[str] = None) -> WebSearchChecker:
    """Factory: auto-detect available provider from environment variables.

    Parameters
    ----------
    preferred_provider : str, optional
        Force a specific provider (``'openai'`` or ``'gemini'``).
        If *None*, tries providers in default preference order.
    """
    if preferred_provider:
        for cls in _PROVIDER_CLASSES:
            if cls.name == preferred_provider:
                provider = cls()
                if provider.available:
                    return WebSearchChecker(provider)
                logger.debug(f'{cls.name} provider requested but not available')
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
    verdict: str = '',
    explanation: str = '',
) -> Dict[str, Any]:
    return {
        'found': found,
        'score_delta': score_delta,
        'academic_urls': academic_urls,
        'query': query,
        'provider': provider,
        'verdict': verdict,
        'explanation': explanation,
    }


def _parse_verdict(text: str) -> str:
    """Extract EXISTS / NOT_FOUND / UNSURE from the first line of LLM output."""
    if not text:
        return 'UNSURE'
    first_line = text.strip().split('\n')[0].upper()
    for v in ('EXISTS', 'NOT_FOUND', 'UNSURE'):
        if v in first_line:
            return v
    return 'UNSURE'


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
