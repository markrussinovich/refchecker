#!/usr/bin/env python3
"""Verification against official workshop and conference program pages."""

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from refchecker.utils.cache_utils import cache_api_response, cached_api_response
from refchecker.utils.error_utils import format_title_mismatch
from refchecker.utils.text_utils import (
    calculate_title_similarity,
    compare_authors,
    strip_latex_commands,
)

logger = logging.getLogger(__name__)


class OfficialProceedingsChecker:
    """Verify lightly indexed works from authoritative event programs."""

    _PROGRAMS = {
        "scinlp": "https://scinlp.org/history/{year}/",
    }
    _USENIX_REQUEST_INTERVAL = 10.0
    _usenix_request_lock = threading.Lock()
    _usenix_last_request = 0.0

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.cache_dir: Optional[str] = None
        self._usenix_pages: Dict[str, Optional[BeautifulSoup]] = {}
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "RefChecker/1.0 (https://github.com/markrussinovich/refchecker)",
                "Accept": "text/html,application/xhtml+xml",
            }
        )

    @staticmethod
    def _usenix_url(url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
        except ValueError:
            logger.debug("Ignoring malformed proceedings URL: %r", url)
            return None
        if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in (
            "usenix.org",
            "www.usenix.org",
        ):
            return None
        if not re.fullmatch(
            r"/conference/usenixsecurity\d{2}"
            r"(?:/technical-sessions|/presentation/[^/]+)?/?",
            parsed.path,
        ):
            return None
        return "https://www.usenix.org" + parsed.path.rstrip("/")

    def _usenix_cited_url(self, reference: Dict[str, Any]) -> Optional[str]:
        for key in ("cited_url", "url"):
            url = self._usenix_url(str(reference.get(key) or ""))
            if url:
                return url
        return None

    def _program_url(self, reference: Dict[str, Any]) -> Optional[str]:
        usenix_url = self._usenix_cited_url(reference)
        if usenix_url:
            return (
                usenix_url.split("/presentation/")[0].removesuffix(
                    "/technical-sessions"
                )
                + "/technical-sessions"
            )

        venue = " ".join(
            str(reference.get(key) or "")
            for key in ("venue", "journal", "booktitle", "raw_text")
        )
        venue_lower = strip_latex_commands(venue).lower()
        try:
            year = int(reference.get("year"))
        except (TypeError, ValueError):
            return None

        if 2000 <= year <= 2099 and (
            re.search(r"\busenix[\s-]+security\b", venue_lower)
            or re.search(r"\bsecurity symposium\b.*\busenix\b", venue_lower)
        ):
            return (
                "https://www.usenix.org/conference/"
                f"usenixsecurity{year % 100:02d}/technical-sessions"
            )

        for marker, template in self._PROGRAMS.items():
            if marker in venue_lower:
                return template.format(year=year)
        return None

    def _usenix_page(self, url: str) -> Optional[BeautifulSoup]:
        # Serialize cache misses as well as requests across checking threads.
        with self._usenix_request_lock:
            if url in self._usenix_pages:
                return self._usenix_pages[url]
            html = cached_api_response(
                self.cache_dir,
                "official_proceedings",
                "usenix_page",
                url,
            )
            if html is None:
                delay = self._USENIX_REQUEST_INTERVAL - (
                    time.monotonic() - OfficialProceedingsChecker._usenix_last_request
                )
                if delay > 0:
                    time.sleep(delay)
                try:
                    response = self.session.get(url, timeout=self.timeout)
                finally:
                    OfficialProceedingsChecker._usenix_last_request = time.monotonic()
                if response.status_code == 404:
                    self._usenix_pages[url] = None
                    return None
                response.raise_for_status()
                html = response.content.decode("utf-8")
                cache_api_response(
                    self.cache_dir,
                    "official_proceedings",
                    "usenix_page",
                    url,
                    html,
                )
            soup = BeautifulSoup(html, "html.parser")
            self._usenix_pages[url] = soup
            return soup

    def _verify_usenix(
        self,
        reference: Dict[str, Any],
        program_url: str,
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        cited_title = str(reference.get("title") or "").strip()
        cited_authors = reference.get("authors") or []
        paper_url = self._usenix_cited_url(reference)
        direct_paper = bool(paper_url and "/presentation/" in paper_url)
        if not direct_paper:
            program = self._usenix_page(program_url)
            if program is None:
                return None, [], None
            candidates = {}
            for link in program.select("h2 a[href]"):
                url = self._usenix_url(urljoin(program_url, link["href"]))
                if not url or not url.startswith(
                    program_url.removesuffix("/technical-sessions") + "/presentation/"
                ):
                    continue
                candidates[url] = calculate_title_similarity(
                    cited_title,
                    link.get_text(" ", strip=True),
                )
            if not candidates:
                raise ValueError("USENIX program contains no paper links")
            paper_url = max(candidates, key=lambda url: candidates[url])
            if candidates[paper_url] < 0.85:
                return None, [], None

        if paper_url is None:
            return None, [], None
        paper = self._usenix_page(paper_url)
        if paper is None:
            return None, [], None

        def metadata(name: str) -> List[str]:
            return [
                str(tag["content"]).strip()
                for tag in paper.find_all("meta", attrs={"name": name, "content": True})
                if str(tag["content"]).strip()
            ]

        titles = metadata("citation_title")
        authors = metadata("citation_author")
        dates = metadata("citation_publication_date")
        venues = metadata("citation_conference_title")
        if not titles or not authors or not dates or not venues:
            raise ValueError("USENIX paper page is missing citation metadata")
        year_match = re.match(r"^\d{4}\b", dates[0])
        if not year_match:
            raise ValueError("USENIX paper page has an invalid publication date")

        title = strip_latex_commands(titles[0])
        year = int(year_match.group())
        title_similarity = calculate_title_similarity(cited_title, title)
        authors_match, author_error = compare_authors(cited_authors, authors)
        if not direct_paper and (
            title_similarity < 0.85
            or (title_similarity < 0.95 and (not cited_authors or not authors_match))
        ):
            return None, [], None

        errors = []
        if title_similarity < 0.95:
            errors.append(
                {
                    "error_type": "title",
                    "error_details": format_title_mismatch(cited_title, title),
                    "ref_title_correct": title,
                }
            )
        if cited_authors and not authors_match:
            errors.append(
                {
                    "error_type": "author",
                    "error_details": author_error,
                    "ref_authors_correct": ", ".join(authors),
                }
            )
        cited_year = reference.get("year")
        if cited_year and str(cited_year).isdigit() and abs(int(cited_year) - year) > 1:
            errors.append(
                {
                    "warning_type": "year",
                    "warning_details": f"Year mismatch: cited {cited_year}, USENIX has {year}",
                    "ref_year_correct": year,
                }
            )
        data = {
            "title": title,
            "authors": authors,
            "year": year,
            "venue": venues[0],
            "url": paper_url,
            "_matched_database": "USENIX",
            "_matched_checker": "official_proceedings",
            "_program_url": program_url,
        }
        return data, errors, paper_url

    def verify_reference(
        self,
        reference: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        program_url = self._program_url(reference)
        cited_title = str(reference.get("title") or "").strip()
        if not program_url or not cited_title:
            return None, [], None

        if self._usenix_url(program_url):
            try:
                return self._verify_usenix(reference, program_url)
            except (requests.RequestException, ValueError) as exc:
                logger.warning(
                    "USENIX proceedings check failed for %s: %s", program_url, exc
                )
                return (
                    None,
                    [
                        {
                            "error_type": "api_failure",
                            "error_details": f"USENIX proceedings check failed: {exc}",
                        }
                    ],
                    None,
                )

        try:
            response = self.session.get(program_url, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.debug("Official program request failed for %s: %s", program_url, exc)
            return None, [], None
        if response.status_code != 200:
            return None, [], None

        soup = BeautifulSoup(response.content, "html.parser")
        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            found_title = cells[1].get_text(" ", strip=True)
            if calculate_title_similarity(cited_title, found_title) < 0.95:
                continue

            found_authors = [
                author.strip()
                for author in re.split(r"\s*,\s*", cells[2].get_text(" ", strip=True))
                if author.strip()
            ]
            cited_authors = reference.get("authors") or []
            if cited_authors and found_authors:
                authors_match, _ = compare_authors(cited_authors, found_authors)
                if not authors_match:
                    continue

            link = row.find("a", href=True)
            work_url = urljoin(program_url, link["href"]) if link else program_url
            year = reference.get("year")
            data = {
                "title": found_title,
                "authors": found_authors,
                "year": year,
                "venue": reference.get("venue")
                or reference.get("booktitle")
                or "Official workshop program",
                "url": work_url,
                "_matched_database": "Official Workshop Program",
                "_program_url": program_url,
            }
            return data, [], work_url

        return None, [], None
