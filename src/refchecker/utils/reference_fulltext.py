"""R43 — per-reference full-text retrieval for grounded chat.

Resolve a cited reference's open-access PDF (arXiv → OpenAlex ``best_oa_location``
/ Unpaywall → its own ``oa_pdf_url``), download it, and extract the real body
text with PyMuPDF so the per-reference Chat & Summarize assistant can answer
from the *document* instead of only the TL;DR / abstract metadata.

Honesty (by construction):
  * Only REAL fetched text is returned. If no OA PDF resolves, or the download
    / extraction fails, we return ``(None, 'tldr')`` and the caller keeps the
    existing TL;DR-only disclaimer verbatim — nothing is fabricated.
  * The grounding source is reported explicitly: ``'pdf'`` when real full text
    was extracted, ``'tldr'`` otherwise.

Operational safety:
  * Cached per identity (arXiv id / DOI / title) with a TTL so re-opening the
    same reference chat — or two refs that resolve to the same work — fetches
    once.
  * Soft-fail everywhere: any network / parse error returns the TL;DR fallback,
    never raises into the request path.
  * Bounded concurrency: a single shared semaphore caps simultaneous outbound
    downloads so a burst of opened chats can't fan out into a stall.

Top-level imports stay light (stdlib + the already-present ``url_utils`` /
``doi_utils``); ``fitz`` (PyMuPDF) and ``requests`` are imported lazily inside
the functions that need them so this module imports cleanly in the deps-free
test harness.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Below this many extracted chars we don't trust the PDF as real full text
# (a cover page, a paywall stub, or a failed extraction). Treat as a miss and
# fall back to the TL;DR rather than ground on a near-empty document.
_MIN_FULLTEXT_CHARS = 1500

# Cap the returned text so a 60-page paper can't blow the chat context budget.
# In ref-mode the fetched full text rides into the chat as a *message-history*
# turn (``ArticleAssistant.groundingPreamble``), NOT through the ``grounding``
# parameter — so the backend's only length guard,
# ``article_chat.MAX_GROUNDING_CHARS`` (applied solely in
# ``_build_document_block`` to the host-paper grounding), never truncates it.
# This cap is therefore the REAL bound on the per-reference payload, kept in
# lockstep with that chat grounding budget so the reference body + the always-
# injected host-paper grounding stay within the model context window (and don't
# silently inflate cost). It also bounds the cache entry size.
_MAX_FULLTEXT_CHARS = 48_000  # == backend.article_chat.MAX_GROUNDING_CHARS

# Per-identity TTL cache: {identity_key: (monotonic_ts, full_text_or_None)}.
# A ``None`` value is cached too (negative cache) so a known-miss reference
# isn't re-fetched on every chat open within the TTL.
_FULLTEXT_CACHE: Dict[str, Tuple[float, Optional[str]]] = {}
_FULLTEXT_TTL_SECONDS = 12 * 60 * 60  # 12 hours
_FULLTEXT_CACHE_LOCK = threading.Lock()

# Bound simultaneous OA-PDF downloads. Acquired around the network portion
# only; cache hits never touch it.
_FULLTEXT_MAX_CONCURRENCY = 4
_FULLTEXT_SEMAPHORE = threading.BoundedSemaphore(_FULLTEXT_MAX_CONCURRENCY)
_FULLTEXT_TIMEOUT_SECONDS = 30.0

# Source-resolution metadata HTTP timeout (OpenAlex / Unpaywall JSON).
_RESOLVE_TIMEOUT_SECONDS = 8.0

# Unpaywall requires a contact email in the query string. Matches the
# contact used by the Crossref backfill fetcher.
_UNPAYWALL_EMAIL = "support@refchecker.app"


def _clean_doi(raw: Any) -> Optional[str]:
    """Normalise to a bare lowercased DOI (10.xxxx/…) or None.

    Reuses the same resolver-prefix stripping + DOI-shape guard as the
    enrichment backfill so we never issue a bogus lookup.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    for prefix in (
        "https://doi.org/", "http://doi.org/",
        "https://dx.doi.org/", "http://dx.doi.org/", "doi:",
    ):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.strip().rstrip("/")
    low = s.lower()
    if not low.startswith("10.") or "/" not in low:
        return None
    return low


def _identity_key(reference: Dict[str, Any]) -> Optional[str]:
    """A stable cache key for a reference, in resolution priority order.

    arXiv id > DOI > lowercased title. Returns None when the reference has no
    usable identity (so we won't attempt retrieval or cache a useless key).
    """
    arxiv_id = (reference.get("arxiv_id") or "").strip()
    if arxiv_id:
        return f"arxiv:{arxiv_id.lower()}"
    doi = _clean_doi(reference.get("doi") or reference.get("verified_doi"))
    if doi:
        return f"doi:{doi}"
    title = (reference.get("title") or "").strip().lower()
    if title:
        return f"title:{title}"
    return None


def _http_get_json(url: str, *, params: Optional[Dict[str, Any]] = None,
                   timeout: float = _RESOLVE_TIMEOUT_SECONDS) -> Optional[Dict[str, Any]]:
    """GET → parsed JSON dict; None on any failure (soft-fail, no retry)."""
    try:
        import requests
    except Exception:  # pragma: no cover - requests is a hard app dep
        return None
    try:
        resp = requests.get(url, params=params, timeout=timeout)
    except Exception as exc:
        logger.debug("reference-fulltext resolve GET failed for %s: %s", url, exc)
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _arxiv_pdf_url(reference: Dict[str, Any]) -> Optional[str]:
    """Build the arXiv PDF URL when the reference carries an arXiv id."""
    arxiv_id = (reference.get("arxiv_id") or "").strip()
    if not arxiv_id:
        return None
    try:
        from refchecker.utils.url_utils import construct_arxiv_url
        return construct_arxiv_url(arxiv_id, url_type="pdf")
    except Exception:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def _oa_pdf_url_from_openalex(doi: str) -> Optional[str]:
    """OpenAlex /works/doi:{doi} → best_oa_location.pdf_url (or oa url).

    OpenAlex exposes the curated open-access copy under ``best_oa_location``;
    we prefer its ``pdf_url`` and fall back to its landing-page ``url`` only
    when it points at a PDF.
    """
    data = _http_get_json(f"https://api.openalex.org/works/doi:{quote(doi, safe='')}")
    if not isinstance(data, dict):
        return None
    for loc_key in ("best_oa_location", "primary_location"):
        loc = data.get(loc_key)
        if isinstance(loc, dict):
            pdf = loc.get("pdf_url")
            if isinstance(pdf, str) and pdf.strip():
                return pdf.strip()
    # open_access.oa_url is a landing page; only trust it when it's a PDF link.
    oa = data.get("open_access")
    if isinstance(oa, dict):
        oa_url = oa.get("oa_url")
        if isinstance(oa_url, str) and oa_url.lower().endswith(".pdf"):
            return oa_url.strip()
    return None


def _oa_pdf_url_from_unpaywall(doi: str) -> Optional[str]:
    """Unpaywall /v2/{doi} → best_oa_location.url_for_pdf."""
    data = _http_get_json(
        f"https://api.unpaywall.org/v2/{quote(doi, safe='')}",
        params={"email": _UNPAYWALL_EMAIL},
    )
    if not isinstance(data, dict):
        return None
    best = data.get("best_oa_location")
    if isinstance(best, dict):
        for k in ("url_for_pdf", "url"):
            v = best.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    # Fall back to scanning all OA locations for a direct PDF.
    for loc in (data.get("oa_locations") or []):
        if isinstance(loc, dict):
            v = loc.get("url_for_pdf")
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _resolve_oa_pdf_url(reference: Dict[str, Any]) -> Optional[str]:
    """Resolve a downloadable OA PDF URL for the reference, or None.

    Priority: a PDF URL we already hold (enrichment.oa_pdf_url) → arXiv (no
    network needed) → OpenAlex best_oa_location → Unpaywall. Each step
    soft-fails; the first real URL wins.
    """
    # 0) Already-resolved OA PDF carried on the enrichment payload.
    enrichment = reference.get("enrichment") or {}
    if isinstance(enrichment, dict):
        held = enrichment.get("oa_pdf_url")
        if isinstance(held, str) and held.strip():
            return held.strip()
        links = enrichment.get("links")
        if isinstance(links, dict):
            held = links.get("oa_pdf")
            if isinstance(held, str) and held.strip():
                return held.strip()

    # 1) arXiv — deterministic URL, no metadata round-trip.
    arxiv_url = _arxiv_pdf_url(reference)
    if arxiv_url:
        return arxiv_url

    # 2/3) DOI → OpenAlex best_oa_location, else Unpaywall.
    doi = _clean_doi(reference.get("doi") or reference.get("verified_doi"))
    if doi:
        for resolver in (_oa_pdf_url_from_openalex, _oa_pdf_url_from_unpaywall):
            try:
                url = resolver(doi)
            except Exception as exc:
                logger.debug("OA resolve %s failed for %s: %s",
                             getattr(resolver, "__name__", "?"), doi, exc)
                url = None
            if url:
                return url
    return None


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract body text from PDF bytes with PyMuPDF (fitz). '' on failure."""
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover - fitz is bundled in the app
        logger.debug("PyMuPDF unavailable for reference full text: %s", exc)
        return ""
    try:
        parts = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                parts.append(page.get_text("text") or "")
        return "\n".join(parts).strip()
    except Exception as exc:
        logger.debug("PyMuPDF extraction failed for reference PDF: %s", exc)
        return ""


def _download_and_extract(url: str) -> Optional[str]:
    """Download the OA PDF and extract its text. None on any failure.

    Bounded by the module concurrency semaphore around the network +
    extraction work so a burst of opened chats can't fan out into a stall.
    """
    acquired = _FULLTEXT_SEMAPHORE.acquire(timeout=_FULLTEXT_TIMEOUT_SECONDS)
    if not acquired:
        logger.debug("reference-fulltext concurrency cap hit; skipping %s", url)
        return None
    try:
        from refchecker.utils.url_utils import download_pdf_bytes
        # Keep the per-reference retrieval snappy: short-ish timeout and a
        # bounded retry budget so a slow mirror can't wedge the chat open.
        data = download_pdf_bytes(url, timeout=30, max_retry_seconds=45.0)
    except Exception as exc:
        logger.debug("reference-fulltext download failed for %s: %s", url, exc)
        return None
    finally:
        _FULLTEXT_SEMAPHORE.release()

    if not data:
        return None
    text = _extract_pdf_text(data)
    if len(text) < _MIN_FULLTEXT_CHARS:
        return None
    if len(text) > _MAX_FULLTEXT_CHARS:
        text = text[:_MAX_FULLTEXT_CHARS]
    return text


def get_reference_fulltext(reference: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Retrieve a reference's REAL OA full text for grounded chat.

    Returns ``(full_text, 'pdf')`` when a genuine OA PDF was fetched and
    extracted, else ``(None, 'tldr')`` — the caller then keeps the TL;DR /
    metadata grounding and its existing disclaimer verbatim. Never raises:
    every failure mode soft-fails to the TL;DR fallback.

    Cached per identity (arXiv id / DOI / title) with a TTL, including a
    negative cache for known misses.
    """
    if not isinstance(reference, dict):
        return None, "tldr"
    key = _identity_key(reference)
    if not key:
        return None, "tldr"

    now = time.monotonic()
    with _FULLTEXT_CACHE_LOCK:
        cached = _FULLTEXT_CACHE.get(key)
        if cached and (now - cached[0]) < _FULLTEXT_TTL_SECONDS:
            text = cached[1]
            return (text, "pdf") if text else (None, "tldr")

    text: Optional[str] = None
    try:
        url = _resolve_oa_pdf_url(reference)
        if url:
            text = _download_and_extract(url)
    except Exception as exc:  # belt-and-braces: retrieval must never raise
        logger.debug("reference-fulltext retrieval errored for %s: %s", key, exc)
        text = None

    with _FULLTEXT_CACHE_LOCK:
        _FULLTEXT_CACHE[key] = (now, text)

    return (text, "pdf") if text else (None, "tldr")


def clear_cache() -> None:
    """Drop the full-text cache (used by tests to isolate runs)."""
    with _FULLTEXT_CACHE_LOCK:
        _FULLTEXT_CACHE.clear()
