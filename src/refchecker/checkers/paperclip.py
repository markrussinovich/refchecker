"""
Paperclip (paperclip.gxl.ai) as an OPTIONAL secondary verification
tier. Wraps the `gxl-paperclip` Python SDK and exposes the same
verify_reference shape as the other checkers in this package.

Why optional:
- Paperclip is an authenticated commercial service (API key required).
- Pricing and rate limits are not publicly documented as of 2026-05.
- Its real differentiator over the existing five sources (S2,
  OpenAlex, Crossref, DBLP, ACL Anthology) is biomedical FULL-TEXT
  search (PMC, bioRxiv, medRxiv) — for plain metadata lookups it
  largely overlaps with what we already query.

The `gxl-paperclip` SDK ships pre-installed (it's in requirements.txt
so the Tauri sidecar bundles it automatically). Activation reduces to
a single user-visible step:

  1. Set `PAPERCLIP_API_KEY` in the env (or in Settings → API keys).

The check is also gated by `enable_paperclip=True` on the
EnhancedHybridReferenceChecker constructor, which defaults to False
so the tier remains opt-in at the application level.

When the API key is missing OR the import unexpectedly fails OR
enable_paperclip is False, every public method returns the empty /
no-match result so the surrounding pipeline behaves identically to
the pre-Paperclip baseline.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _looks_like_match(candidate: Dict[str, Any], title: str, year: Optional[int],
                      authors: Optional[List[str]]) -> float:
    """
    Lightweight score for a Paperclip candidate against the cited ref.
    Paperclip doesn't return a relevance score in its JSON, so we
    derive one — title token overlap (Jaccard on lowercased word
    sets) plus a small year bonus and a first-author bonus. Anything
    >= 0.55 is treated as a hit.
    """
    cand_title = (candidate.get('title') or '').strip().lower()
    cited_title = (title or '').strip().lower()
    if not cand_title or not cited_title:
        return 0.0
    cand_tokens = set(t for t in cand_title.replace('-', ' ').split() if len(t) > 2)
    cited_tokens = set(t for t in cited_title.replace('-', ' ').split() if len(t) > 2)
    if not cand_tokens or not cited_tokens:
        return 0.0
    overlap = len(cand_tokens & cited_tokens)
    union = len(cand_tokens | cited_tokens)
    score = overlap / union if union else 0.0

    cand_year = candidate.get('pub_year') or candidate.get('year')
    if year and cand_year:
        try:
            gap = abs(int(year) - int(cand_year))
            if gap == 0:
                score += 0.10
            elif gap == 1:
                score += 0.05
            elif gap > 3:
                score -= 0.20
        except (TypeError, ValueError):
            pass

    if authors:
        first_cited = str(authors[0]).strip().lower()
        cand_authors = candidate.get('authors') or []
        if cand_authors:
            first_cand = cand_authors[0]
            if isinstance(first_cand, dict):
                first_cand = first_cand.get('name', '')
            first_cand = str(first_cand).strip().lower()
            # Cheap surname check — share any 3+-char token.
            cited_tokens = {t for t in first_cited.split() if len(t) > 2}
            cand_tokens = {t for t in first_cand.split() if len(t) > 2}
            if cited_tokens & cand_tokens:
                score += 0.15

    return score


class PaperclipReferenceChecker:
    """
    Optional secondary verifier backed by Paperclip's lookup/search.
    Disabled by default; enabled when PAPERCLIP_API_KEY is set AND
    the SDK is installed.
    """

    SCORE_THRESHOLD = 0.55

    def __init__(self, api_key: Optional[str] = None, sources: Optional[List[str]] = None):
        self.client = None
        self.cache_dir = None
        self.enabled = False
        # Sources we'd ask Paperclip to search — defaults to biomedical
        # full-text + arXiv since that's the corpus delta vs the existing
        # checkers. Caller can override (e.g. ['pmc'] for strict biomed).
        self.sources = sources or ['pmc', 'biorxiv', 'medrxiv', 'arxiv']

        key = api_key or os.environ.get('PAPERCLIP_API_KEY')
        if not key:
            logger.debug("Paperclip disabled — PAPERCLIP_API_KEY not set")
            return

        try:
            # Lazy import so this module loads even on the unusual path
            # where gxl-paperclip is somehow missing from a custom
            # install (e.g. user-built sidecar without the bundled
            # requirements.txt). The SDK is shipped by default.
            from gxl_paperclip import PaperclipClient  # type: ignore
        except ImportError:
            logger.info(
                "Paperclip enabled but gxl-paperclip not importable; "
                "reinstall requirements.txt to restore the bundled SDK."
            )
            return

        try:
            self.client = PaperclipClient(api_key=key)
            self.enabled = True
            logger.debug("Paperclip checker initialized")
        except Exception as e:
            logger.warning(f"Paperclip client init failed: {e}")
            self.client = None

    def _safe_call(self, func, *args, **kwargs) -> List[Dict[str, Any]]:
        """
        Wrap an SDK call in a uniform try/except so a transient failure
        in a secondary verifier never breaks the primary pipeline.
        """
        if not self.enabled or self.client is None:
            return []
        try:
            t0 = time.time()
            result = func(*args, **kwargs)
            logger.debug(f"Paperclip call took {time.time() - t0:.2f}s")
            # SDK returns either a list of dicts or an iterable; normalise.
            if result is None:
                return []
            if hasattr(result, 'results'):
                return list(result.results)
            if isinstance(result, list):
                return list(result)
            try:
                return list(result)
            except TypeError:
                return []
        except Exception as e:
            logger.debug(f"Paperclip request failed (ignored): {e}")
            return []

    def lookup_by_doi(self, doi: str) -> List[Dict[str, Any]]:
        if not doi:
            return []
        return self._safe_call(self.client.lookup, 'doi', doi)

    def lookup_by_title(self, title: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not title:
            return []
        return self._safe_call(self.client.lookup, 'title', title, limit=limit)

    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Match a parsed reference against Paperclip. Designed to be a
        tiebreaker / existence check, NOT a metadata source — Paperclip's
        responses don't include enough structured fields to drive the
        full author/year/venue diff. So the return is:
          - work_data: the matched candidate (or None) — callers can use
            this to confirm existence
          - errors: empty list (we don't surface paperclip-specific
            mismatches; the primary checkers own that)
          - url: Paperclip's URL to the paper if available
        """
        if not self.enabled:
            return None, [], None

        doi = reference.get('doi')
        title = reference.get('title', '')
        year = reference.get('year')
        authors = reference.get('authors') or []
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(',') if a.strip()]

        # 1) DOI lookup — highest confidence, single API call.
        if doi:
            candidates = self.lookup_by_doi(doi)
            for cand in candidates[:3]:
                if (cand.get('doi') or '').lower() == doi.lower():
                    return cand, [], cand.get('url')

        # 2) Title lookup — score each candidate and accept if any clears
        # the threshold. Without an SDK-provided relevance score we score
        # locally on title/year/author overlap.
        if title:
            candidates = self.lookup_by_title(title, limit=5)
            best, best_score = None, 0.0
            for cand in candidates:
                s = _looks_like_match(cand, title, year, authors)
                if s > best_score:
                    best_score = s
                    best = cand
            if best is not None and best_score >= self.SCORE_THRESHOLD:
                logger.debug(f"Paperclip matched '{title[:50]}' with score {best_score:.2f}")
                return best, [], best.get('url')

        return None, [], None
