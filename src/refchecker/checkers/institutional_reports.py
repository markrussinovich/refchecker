#!/usr/bin/env python3
"""Verification against official institutional technical-report indexes."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from refchecker.utils.text_utils import calculate_title_similarity, compare_authors

logger = logging.getLogger(__name__)


class InstitutionalReportsChecker:
    """Resolve unindexed reports through their issuing institution's catalog."""

    _INDEXES = (
        {
            'venue_markers': ('university of chicago', 'statistics', 'tech. rep'),
            'url': (
                'https://stat.uchicago.edu/about/statistics-resources/'
                'department-library/technical-reports-2/'
            ),
            'venue': 'University of Chicago Department of Statistics Technical Reports',
        },
    )

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'RefChecker/1.0 (https://github.com/markrussinovich/refchecker)',
            'Accept': 'text/html,application/xhtml+xml',
        })

    def _index_for_reference(self, reference: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        venue = ' '.join(
            str(reference.get(key) or '')
            for key in ('venue', 'journal', 'booktitle', 'raw_text')
        ).lower()
        for index in self._INDEXES:
            if all(marker in venue for marker in index['venue_markers']):
                return index
        return None

    def verify_reference(
        self,
        reference: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        index = self._index_for_reference(reference)
        title = str(reference.get('title') or '').strip()
        report_number = str(reference.get('volume') or reference.get('number') or '').strip()
        year = reference.get('year')
        if not index or not title or not report_number or not report_number.isdigit():
            return None, [], None

        try:
            response = self.session.get(index['url'], timeout=self.timeout)
        except requests.RequestException as exc:
            logger.debug("Institutional report index request failed: %s", exc)
            return None, [], None
        if response.status_code != 200:
            return None, [], None

        soup = BeautifulSoup(response.content, 'html.parser')
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) < 4 or cells[0].get_text(' ', strip=True) != report_number:
                continue

            found_authors_text = cells[1].get_text(' ', strip=True)
            found_date = cells[2].get_text(' ', strip=True)
            found_title = cells[3].get_text(' ', strip=True)
            if calculate_title_similarity(title, found_title) < 0.95:
                continue
            if year and str(year) not in found_date:
                continue

            found_authors = [
                author.strip()
                for author in re.split(r'\s+(?:and|&)\s+', found_authors_text)
                if author.strip()
            ]
            cited_authors = reference.get('authors') or []
            if cited_authors and found_authors:
                authors_match, _ = compare_authors(cited_authors, found_authors)
                if not authors_match:
                    continue

            link = cells[3].find('a', href=True)
            report_url = urljoin(index['url'], link['href']) if link else index['url']
            data = {
                'title': found_title,
                'authors': found_authors,
                'year': year,
                'venue': index['venue'],
                'volume': report_number,
                'url': report_url,
                '_matched_database': 'Official Institutional Report Index',
                '_index_url': index['url'],
            }
            return data, [], report_url

        return None, [], None
