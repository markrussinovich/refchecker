#!/usr/bin/env python3
"""Verification against official workshop and conference program pages."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from refchecker.utils.text_utils import calculate_title_similarity, compare_authors

logger = logging.getLogger(__name__)


class OfficialProceedingsChecker:
    """Verify lightly indexed works from authoritative event programs."""

    _PROGRAMS = {
        'scinlp': 'https://scinlp.org/history/{year}/',
    }

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'RefChecker/1.0 (https://github.com/markrussinovich/refchecker)',
            'Accept': 'text/html,application/xhtml+xml',
        })

    def _program_url(self, reference: Dict[str, Any]) -> Optional[str]:
        venue = ' '.join(str(reference.get(key) or '') for key in ('venue', 'journal', 'booktitle', 'raw_text'))
        venue_lower = venue.lower()
        try:
            year = int(reference.get('year'))
        except (TypeError, ValueError):
            return None

        for marker, template in self._PROGRAMS.items():
            if marker in venue_lower:
                return template.format(year=year)
        return None

    def verify_reference(
        self,
        reference: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        program_url = self._program_url(reference)
        cited_title = str(reference.get('title') or '').strip()
        if not program_url or not cited_title:
            return None, [], None

        try:
            response = self.session.get(program_url, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.debug("Official program request failed for %s: %s", program_url, exc)
            return None, [], None
        if response.status_code != 200:
            return None, [], None

        soup = BeautifulSoup(response.content, 'html.parser')
        for row in soup.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            if len(cells) < 3:
                continue

            found_title = cells[1].get_text(' ', strip=True)
            if calculate_title_similarity(cited_title, found_title) < 0.95:
                continue

            found_authors = [
                author.strip()
                for author in re.split(r'\s*,\s*', cells[2].get_text(' ', strip=True))
                if author.strip()
            ]
            cited_authors = reference.get('authors') or []
            if cited_authors and found_authors:
                authors_match, _ = compare_authors(cited_authors, found_authors)
                if not authors_match:
                    continue

            link = row.find('a', href=True)
            work_url = urljoin(program_url, link['href']) if link else program_url
            year = reference.get('year')
            data = {
                'title': found_title,
                'authors': found_authors,
                'year': year,
                'venue': reference.get('venue') or reference.get('booktitle') or 'Official workshop program',
                'url': work_url,
                '_matched_database': 'Official Workshop Program',
                '_program_url': program_url,
            }
            return data, [], work_url

        return None, [], None
