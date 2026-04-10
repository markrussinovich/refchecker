#!/usr/bin/env python3
"""
DBLP API Client for Reference Verification

DBLP is a curated computer science bibliography with excellent coverage of
conference papers (NeurIPS, ICML, ICLR, ACL, CVPR, etc.) — exactly the venues
most commonly hallucinated by LLMs.

The API is free, requires no key, and has generous rate limits.
See: https://dblp.org/faq/How+to+use+the+dblp+search+API
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from refchecker.utils.text_utils import (
    clean_title_for_search,
    normalize_text,
)

logger = logging.getLogger(__name__)


def _normalize_for_comparison(text: str) -> str:
    """Lowercase, strip punctuation, and collapse whitespace for fuzzy title matching."""
    import re
    text = normalize_text(text).lower()
    text = re.sub(r'[^a-z0-9\s]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _title_similarity(a: str, b: str) -> float:
    """Quick word-overlap Jaccard similarity between two normalized titles."""
    words_a = set(_normalize_for_comparison(a).split())
    words_b = set(_normalize_for_comparison(b).split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


class DBLPReferenceChecker:
    """Verify references against the DBLP computer science bibliography."""

    BASE_URL = 'https://dblp.org/search/publ/api'
    REQUEST_TIMEOUT = 15
    # DBLP asks for ≤1 req/s for unauthenticated clients
    MIN_REQUEST_INTERVAL = 1.1

    def __init__(self, email: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'RefChecker/1.0.0 (https://github.com/markrussinovich/refchecker)',
        })
        self._last_request_time = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)

    def _search(self, query: str, max_hits: int = 5) -> List[Dict[str, Any]]:
        from refchecker.utils.cache_utils import cached_api_response, cache_api_response
        cache_q = f"{query}|{max_hits}"
        hit = cached_api_response(getattr(self, 'cache_dir', None), 'dblp', 'search', cache_q)
        if hit is not None:
            return hit
        result = self._search_uncached(query, max_hits)
        cache_api_response(getattr(self, 'cache_dir', None), 'dblp', 'search', cache_q, result)
        return result

    def _search_uncached(self, query: str, max_hits: int = 5) -> List[Dict[str, Any]]:
        self._throttle()
        params = {
            'q': query,
            'format': 'json',
            'h': max_hits,
        }
        last_exc = None
        for attempt in range(2):
            try:
                resp = self.session.get(self.BASE_URL, params=params, timeout=self.REQUEST_TIMEOUT)
                self._last_request_time = time.time()
                resp.raise_for_status()
                data = resp.json()
                result = data.get('result', {})
                hits_wrapper = result.get('hits', {})
                hits = hits_wrapper.get('hit', [])
                return hits if isinstance(hits, list) else []
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt == 0:
                    logger.debug(f'DBLP: search attempt {attempt+1} failed ({exc}), retrying...')
                    time.sleep(2)
        logger.debug(f'DBLP: search failed after retries: {last_exc}')
        raise last_exc

    def verify_reference(
        self, reference: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """Verify a reference against DBLP.

        Returns:
            (verified_data, errors, url) following the same contract as other checkers.
        """
        title = reference.get('title', '')
        if not title or len(title.strip()) < 5:
            return None, [], None

        search_title = clean_title_for_search(title)

        try:
            hits = self._search(search_title)
        except requests.exceptions.RequestException:
            return None, [{'error_type': 'api_failure',
                           'error_details': 'DBLP API request failed'}], None

        if not hits:
            logger.debug(f'DBLP: no results for "{search_title}"')
            return None, [], None

        # Find best matching hit
        best_hit = None
        best_score = 0.0

        for hit in hits:
            info = hit.get('info', {})
            hit_title = info.get('title', '')
            sim = _title_similarity(title, hit_title)
            if sim > best_score:
                best_score = sim
                best_hit = info

        if best_score < 0.85 or best_hit is None:
            logger.debug(f'DBLP: best match score {best_score:.2f} below threshold for "{title}"')
            return None, [], None

        # Validate author overlap to avoid false-positive title matches
        ref_authors = reference.get('authors', [])
        hit_authors_data = best_hit.get('authors', {}).get('author', [])
        if isinstance(hit_authors_data, dict):
            hit_authors_data = [hit_authors_data]
        hit_author_names = [a.get('text', '') if isinstance(a, dict) else str(a)
                            for a in hit_authors_data]

        if ref_authors and hit_author_names:
            ref_last_names = {a.split()[-1].lower() for a in ref_authors if a.strip()}
            hit_last_names = {a.split()[-1].lower() for a in hit_author_names if a.strip()}
            if ref_last_names and hit_last_names:
                overlap = ref_last_names & hit_last_names
                if not overlap:
                    logger.debug(f'DBLP: title matched but no author overlap — likely different paper')
                    return None, [], None

        # Build verified_data in the standard format
        hit_url = best_hit.get('url', '')
        hit_year = best_hit.get('year', '')

        verified_data = {
            'title': best_hit.get('title', ''),
            'authors': hit_author_names,
            'year': int(hit_year) if str(hit_year).isdigit() else None,
            'venue': best_hit.get('venue', ''),
            'url': hit_url,
            'source': 'dblp',
        }

        # Validate year
        errors: List[Dict[str, Any]] = []
        cited_year = reference.get('year')
        if cited_year and hit_year:
            try:
                if int(cited_year) != int(hit_year):
                    errors.append({
                        'warning_type': 'year',
                        'warning_details': f'Year mismatch: cited {cited_year}, DBLP has {hit_year}',
                        'ref_year_correct': int(hit_year),
                    })
            except (ValueError, TypeError):
                pass

        logger.debug(f'DBLP: verified "{title}" (score={best_score:.2f}, url={hit_url})')
        return verified_data, errors, hit_url
