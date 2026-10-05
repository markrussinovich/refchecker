#!/usr/bin/env python3
"""
DataCite API Checker for Reference Verification

Zenodo, Figshare, OSF, Dryad, and most research-data/software DOIs are
registered through DataCite, not CrossRef. CrossRef, OpenAlex, and
Semantic Scholar only inconsistently index DataCite-registered DOIs (an
OpenAlex hit depends on whether the record happened to get crawled), so
references to these sources were falling through to "unverified" even
when the DOI is valid and resolves to exactly the cited work — the single
largest false-positive source identified in the "Detecting Hallucinated
and Suspicious Citations" study (arXiv:2607.22693), where Zenodo-DOI
references (e.g. an OpenCitations snapshot, a Zenodo-archived dataset)
were incorrectly flagged despite being genuine, resolvable citations.

This checker queries the public, unauthenticated DataCite REST API
(https://api.datacite.org/dois/{doi}) directly, so it fills that gap
regardless of which other databases happen to have indexed the record.

Usage:
    from refchecker.checkers.datacite import DataCiteChecker

    checker = DataCiteChecker()
    verified_data, errors, url = checker.verify_reference(reference)
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from refchecker.utils.doi_utils import (
    construct_doi_url,
    extract_doi_from_url,
    is_valid_doi_format,
    normalize_doi,
)
from refchecker.utils.text_utils import calculate_title_similarity, compare_authors
from refchecker.utils.error_utils import format_title_mismatch, format_year_mismatch

logger = logging.getLogger(__name__)

# DataCite's REST API is public and does not require authentication.
API_BASE = "https://api.datacite.org/dois"

# Below this title-similarity score we don't treat the DataCite record as
# confirming the citation at all (matches the pattern used by the other
# title-search checkers; a bit more lenient than CrossRef's `SIMILARITY_THRESHOLD`
# because DataCite titles for datasets/software are often terser/looser
# paraphrases of the paper title that cites them).
TITLE_MATCH_THRESHOLD = 0.6


def _extract_year(attributes: Dict[str, Any]) -> Optional[int]:
    year = attributes.get("publicationYear")
    if year is None:
        return None
    try:
        return int(year)
    except (TypeError, ValueError):
        return None


def _extract_title(attributes: Dict[str, Any]) -> str:
    titles = attributes.get("titles") or []
    for entry in titles:
        if isinstance(entry, dict) and entry.get("title"):
            return str(entry["title"]).strip()
        if isinstance(entry, str) and entry.strip():
            return entry.strip()
    return ""


def _extract_creator_names(attributes: Dict[str, Any]) -> List[str]:
    names = []
    for creator in attributes.get("creators") or []:
        if not isinstance(creator, dict):
            continue
        name = creator.get("name")
        given = creator.get("givenName")
        family = creator.get("familyName")
        if given and family:
            names.append(f"{given} {family}".strip())
        elif name:
            names.append(str(name).strip())
        elif family:
            names.append(str(family).strip())
    return [n for n in names if n]


class DataCiteChecker:
    """Verifies references whose DOI is registered via DataCite (Zenodo,
    Figshare, OSF, Dryad, and similar repositories) rather than CrossRef."""

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "RefChecker/1.0 (https://github.com/markrussinovich/refchecker)",
            "Accept": "application/vnd.api+json",
        })

    def _extract_doi(self, reference: Dict[str, Any]) -> Optional[str]:
        doi = reference.get("doi")
        if not doi:
            url = reference.get("url") or reference.get("cited_url") or ""
            doi = extract_doi_from_url(url)
        if not doi:
            return None
        doi = normalize_doi(doi)
        return doi if is_valid_doi_format(doi) else None

    def get_work_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """Fetch a single DOI record's attributes from the DataCite API."""
        try:
            resp = self.session.get(f"{API_BASE}/{doi}", timeout=self.timeout)
        except requests.RequestException as e:
            logger.debug(f"DataCite request failed for {doi}: {e}")
            return None

        if resp.status_code != 200:
            logger.debug(f"DataCite lookup for {doi} returned HTTP {resp.status_code}")
            return None

        try:
            payload = resp.json()
        except ValueError:
            return None

        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        return data.get("attributes") or {}

    def verify_reference(
        self, reference: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a reference using the DataCite API.

        Returns:
            Tuple of (verified_data, errors, url) matching the other checkers'
            contract. verified_data is a canonical dict (title/authors/year/
            venue/doi/url/_matched_database) or None if DataCite has no
            record for the DOI (e.g. it's a CrossRef DOI, or no DOI at all —
            this checker is a fallback, not a general-purpose verifier).
        """
        doi = self._extract_doi(reference)
        if not doi:
            return None, [], None

        attributes = self.get_work_by_doi(doi)
        if not attributes:
            logger.debug(f"DataCite: no record for DOI {doi}")
            return None, [], None

        title = _extract_title(attributes)
        year = _extract_year(attributes)
        creators = _extract_creator_names(attributes)
        container = attributes.get("container") or {}
        venue = ""
        if isinstance(container, dict):
            venue = container.get("title") or ""
        publisher = attributes.get("publisher") or ""
        resource_url = attributes.get("url") or construct_doi_url(doi)

        cited_title = reference.get("title", "")
        cited_year = reference.get("year", 0)
        cited_authors = reference.get("authors", [])

        errors: List[Dict[str, Any]] = []

        if cited_title and title:
            score = calculate_title_similarity(cited_title, title)
            if score < TITLE_MATCH_THRESHOLD:
                # Title doesn't match this DOI closely enough to say DataCite
                # confirms the citation — don't claim verification.
                logger.debug(
                    f"DataCite: title mismatch for {doi} (score {score:.2f}): "
                    f"'{cited_title}' vs '{title}'"
                )
                return None, [], None

            if score < 0.9:
                errors.append({
                    "warning_type": "title",
                    "warning_details": format_title_mismatch(cited_title, title),
                    "ref_title_correct": title,
                })

        if cited_authors and creators:
            authors_match, author_error = compare_authors(cited_authors, creators)
            if not authors_match:
                errors.append({
                    "error_type": "author",
                    "error_details": author_error,
                    "ref_authors_correct": ", ".join(creators),
                })

        if cited_year and year and int(cited_year) != int(year):
            try:
                gap = abs(int(cited_year) - int(year))
            except (TypeError, ValueError):
                gap = None
            if gap is None or gap > 1:
                errors.append({
                    "warning_type": "year",
                    "warning_details": format_year_mismatch(cited_year, year),
                    "ref_year_correct": year,
                })

        verified_data = {
            "title": title or cited_title,
            "authors": creators or cited_authors,
            "year": year,
            "venue": venue or publisher,
            "doi": doi,
            "url": resource_url,
            "_matched_database": "DataCite",
        }

        return verified_data, errors, resource_url
