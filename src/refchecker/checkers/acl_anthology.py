#!/usr/bin/env python3
"""
ACL Anthology API Client for Reference Verification

ACL Anthology is the definitive bibliography for computational linguistics and
NLP papers — ACL, EMNLP, NAACL, EACL, COLING, TACL, and many more venues.
The search endpoint is free and requires no API key.

See: https://aclanthology.org/

Approach inspired by the hallucinator project (https://github.com/gianlucasb/hallucinator).
"""

import logging
import re
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


# Mapping from single-letter ACL Anthology paper-ID prefixes (old format) to venue names.
_OLD_PREFIX_MAP: Dict[str, str] = {
    'A': 'ACL',
    'C': 'COLING',
    'D': 'EMNLP',
    'E': 'EACL',
    'H': 'HLT',
    'I': 'IJCNLP',
    'J': 'Computational Linguistics',
    'K': 'CoNLL',
    'L': 'LREC',
    'M': 'MUC',
    'N': 'NAACL',
    'P': 'ACL',
    'Q': 'TACL',
    'R': 'RANLP',
    'S': 'SemEval',
    'T': 'Theoretical Linguistics',
    'W': 'Workshop',
    'X': 'ANLP',
    'Y': 'PACLIC',
}


def _parse_acl_id(paper_id: str) -> Tuple[Optional[int], Optional[str]]:
    """Extract year and venue abbreviation from an ACL Anthology paper ID.

    New format:  2023.acl-long.1    → (2023, "ACL")
    Old format:  D19-1019           → (2019, "EMNLP")
    """
    # New format: YYYY.venue[-type[.N]]
    new_fmt = re.match(r'^(\d{4})\.([^.\-]+)', paper_id)
    if new_fmt:
        year = int(new_fmt.group(1))
        venue_code = new_fmt.group(2).upper()
        return year, venue_code

    # Old format: X##-NNNN
    old_fmt = re.match(r'^([A-Za-z])(\d{2})-', paper_id)
    if old_fmt:
        prefix = old_fmt.group(1).upper()
        year_suffix = int(old_fmt.group(2))
        year = 2000 + year_suffix if year_suffix < 50 else 1900 + year_suffix
        return year, _OLD_PREFIX_MAP.get(prefix, prefix)

    return None, None


class ACLAnthologyReferenceChecker:
    """Verify references against the ACL Anthology bibliography."""

    SEARCH_URL = 'https://aclanthology.org/search/'
    REQUEST_TIMEOUT = 15
    # Be polite — space requests to ~1 per second
    MIN_REQUEST_INTERVAL = 1.1

    def __init__(self, email: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml',
            'User-Agent': 'RefChecker/1.0.0 (https://github.com/markrussinovich/refchecker)',
        })
        self._last_request_time = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)

    def _search(self, query: str) -> List[Dict[str, Any]]:
        from refchecker.utils.cache_utils import cached_api_response, cache_api_response
        hit = cached_api_response(getattr(self, 'cache_dir', None), 'acl_anthology', 'search', query)
        if hit is not None:
            return hit
        result = self._search_uncached(query)
        cache_api_response(getattr(self, 'cache_dir', None), 'acl_anthology', 'search', query, result)
        return result

    def _search_uncached(self, query: str) -> List[Dict[str, Any]]:
        self._throttle()
        params = {'q': query}
        last_exc: Optional[Exception] = None
        for attempt in range(2):
            try:
                resp = self.session.get(self.SEARCH_URL, params=params, timeout=self.REQUEST_TIMEOUT)
                self._last_request_time = time.time()
                resp.raise_for_status()
                return self._parse_results(resp.text)
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt == 0:
                    logger.debug(f'ACL Anthology: search attempt {attempt + 1} failed ({exc}), retrying…')
                    time.sleep(2)
        logger.debug(f'ACL Anthology: search failed after retries: {last_exc}')
        raise last_exc  # type: ignore[misc]

    def _parse_results(self, html: str) -> List[Dict[str, Any]]:
        """Parse ACL Anthology search result HTML into a list of paper dicts."""
        from bs4 import BeautifulSoup

        results: List[Dict[str, Any]] = []
        soup = BeautifulSoup(html, 'html.parser')

        for entry in soup.select('.d-sm-flex.align-items-stretch.p-2'):
            title_tag = entry.select_one('h5')
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)

            author_tags = entry.select('span.badge.badge-light')
            authors = [a.get_text(strip=True) for a in author_tags]

            link_tag = entry.select_one('a[href*="/papers/"]') or entry.select_one('a[href]')
            paper_url: Optional[str] = None
            paper_id: Optional[str] = None
            if link_tag and link_tag.get('href'):
                href = str(link_tag['href'])
                paper_url = f'https://aclanthology.org{href}' if href.startswith('/') else href
                id_match = re.search(r'/(\w[\w.\-]+?)/?$', href)
                if id_match:
                    paper_id = id_match.group(1)

            year, venue = _parse_acl_id(paper_id) if paper_id else (None, None)
            results.append({
                'title': title,
                'authors': authors,
                'year': year,
                'venue': venue,
                'url': paper_url,
            })

        return results

    def verify_reference(
        self, reference: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """Verify a reference against ACL Anthology.

        Returns:
            (verified_data, errors, url) following the same contract as other checkers.
        """
        title = reference.get('title', '')
        if not title or len(title.strip()) < 5:
            return None, [], None

        search_title = clean_title_for_search(title)

        try:
            results = self._search(search_title)
        except requests.exceptions.RequestException:
            return None, [{'error_type': 'api_failure',
                           'error_details': 'ACL Anthology API request failed'}], None

        if not results:
            logger.debug(f'ACL Anthology: no results for "{search_title}"')
            return None, [], None

        # Find best matching result by title similarity
        best_match: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for result in results:
            sim = _title_similarity(title, result['title'])
            if sim > best_score:
                best_score = sim
                best_match = result

        if best_score < 0.85 or best_match is None:
            logger.debug(f'ACL Anthology: best match score {best_score:.2f} below threshold for "{title}"')
            return None, [], None

        # Validate author overlap to avoid false-positive title matches
        ref_authors = reference.get('authors', [])
        hit_author_names: List[str] = best_match.get('authors', [])
        if ref_authors and hit_author_names:
            ref_last_names = {a.split()[-1].lower() for a in ref_authors if a.strip()}
            hit_last_names = {a.split()[-1].lower() for a in hit_author_names if a.strip()}
            if ref_last_names and hit_last_names and not (ref_last_names & hit_last_names):
                logger.debug(f'ACL Anthology: title matched but no author overlap — likely different paper')
                return None, [], None

        hit_url = best_match.get('url', '')
        hit_year = best_match.get('year')

        verified_data: Dict[str, Any] = {
            'title': best_match['title'],
            'authors': hit_author_names,
            'year': hit_year,
            'venue': best_match.get('venue', ''),
            'url': hit_url,
            'source': 'acl_anthology',
        }

        errors: List[Dict[str, Any]] = []
        cited_year = reference.get('year')
        if cited_year and hit_year:
            try:
                if int(cited_year) != int(hit_year):
                    errors.append({
                        'warning_type': 'year',
                        'warning_details': (
                            f'Year mismatch: cited {cited_year}, '
                            f'ACL Anthology has {hit_year}'
                        ),
                        'ref_year_correct': hit_year,
                    })
            except (ValueError, TypeError):
                pass

        logger.debug(f'ACL Anthology: verified "{title}" (score={best_score:.2f}, url={hit_url})')
        return verified_data, errors, hit_url
