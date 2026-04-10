"""Filesystem cache for downloaded PDFs and extracted bibliographies.

When ``--cache <dir>`` is passed on the CLI, the checker stores PDF bytes
and the final parsed reference list under deterministic keys so repeated
runs skip both the download and the (potentially LLM-based) extraction
step.

Directory layout::

    <cache_dir>/
      arxiv_2312.02091/
        paper.pdf
        bibliography.json
      openreview_H8tismBT3Q/
        paper.pdf
        bibliography.json
      url_<sha256>/
        paper.pdf
        bibliography.json

High-level API
--------------
``cached_bibliography(cache_dir, input_spec)``
    Returns cached bibliography list or None.  Single call replaces
    key derivation + load in every call site.

``cache_bibliography(cache_dir, input_spec, bibliography)``
    Saves bibliography list.  Single call replaces key derivation + save.

``cached_pdf(cache_dir, input_spec)``
    Returns cached PDF BytesIO or None.

``cache_pdf(cache_dir, input_spec, pdf_content)``
    Saves PDF bytes.
"""

import hashlib
import json
import logging
import os
import re
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


def cache_key_for_spec(input_spec: str) -> str:
    """Derive a stable, filesystem-safe cache key from a paper spec.

    Handles arXiv IDs/URLs, OpenReview forum URLs, other HTTP URLs,
    and local file paths.
    """
    spec = input_spec.strip()

    # OpenReview forum URL → openreview_{id}
    if 'openreview.net/forum' in spec or 'openreview.net/pdf' in spec:
        parsed = urlparse(spec)
        params = parse_qs(parsed.query)
        forum_id = params.get('id', [None])[0]
        if forum_id:
            return f"openreview_{forum_id}"

    # arXiv URL → arxiv_{id}
    if spec.startswith('http'):
        from refchecker.utils.url_utils import extract_arxiv_id_from_url
        arxiv_id = extract_arxiv_id_from_url(spec)
        if arxiv_id:
            return f"arxiv_{arxiv_id}"
        # Generic URL — use sha256 prefix
        url_hash = hashlib.sha256(spec.encode()).hexdigest()[:16]
        return f"url_{url_hash}"

    # Bare arXiv ID (e.g. "2312.02091" or "2312.02091v2")
    if re.match(r'^\d{4}\.\d{4,5}(v\d+)?$', spec):
        return f"arxiv_{spec}"

    # Local file — use basename + content hash if file exists
    expanded = os.path.expanduser(spec)
    if os.path.isfile(expanded):
        file_hash = hashlib.sha256(expanded.encode()).hexdigest()[:16]
        base = os.path.splitext(os.path.basename(expanded))[0]
        # Sanitise the basename for filesystem safety
        safe = re.sub(r'[^\w\-.]', '_', base)[:60]
        return f"file_{safe}_{file_hash}"

    # Fallback: hash the spec itself
    return f"spec_{hashlib.sha256(spec.encode()).hexdigest()[:16]}"


# ---------------------------------------------------------------------------
# Bibliography (parsed reference list) cache
# ---------------------------------------------------------------------------

def load_cached_bibliography(cache_dir: str, key: str) -> Optional[List[Dict[str, Any]]]:
    """Return the cached bibliography list, or *None* on miss."""
    path = os.path.join(cache_dir, key, 'bibliography.json')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            logger.info("Cache hit: loaded %d references from %s", len(data), path)
            return data
    except Exception as exc:
        logger.debug("Cache read error for %s: %s", path, exc)
    return None


def save_cached_bibliography(cache_dir: str, key: str, bibliography: List[Dict[str, Any]]) -> None:
    """Persist the parsed bibliography list to the cache directory."""
    if not bibliography:
        return
    entry_dir = os.path.join(cache_dir, key)
    os.makedirs(entry_dir, exist_ok=True)
    path = os.path.join(entry_dir, 'bibliography.json')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(bibliography, f, ensure_ascii=False, indent=2)
        logger.debug("Cached %d references to %s", len(bibliography), path)
    except Exception as exc:
        logger.warning("Failed to write bibliography cache %s: %s", path, exc)


# ---------------------------------------------------------------------------
# PDF cache
# ---------------------------------------------------------------------------

def load_cached_pdf(cache_dir: str, key: str) -> Optional[BytesIO]:
    """Return cached PDF bytes as a BytesIO, or *None* on miss."""
    path = os.path.join(cache_dir, key, 'paper.pdf')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'rb') as f:
            data = f.read()
        if data:
            logger.info("Cache hit: loaded PDF from %s (%d bytes)", path, len(data))
            return BytesIO(data)
    except Exception as exc:
        logger.debug("Cache read error for %s: %s", path, exc)
    return None


def save_cached_pdf(cache_dir: str, key: str, pdf_content: BytesIO) -> None:
    """Persist PDF bytes to the cache directory."""
    entry_dir = os.path.join(cache_dir, key)
    os.makedirs(entry_dir, exist_ok=True)
    path = os.path.join(entry_dir, 'paper.pdf')
    try:
        pdf_content.seek(0)
        with open(path, 'wb') as f:
            f.write(pdf_content.read())
        pdf_content.seek(0)
        logger.debug("Cached PDF to %s", path)
    except Exception as exc:
        logger.warning("Failed to write PDF cache %s: %s", path, exc)


# ---------------------------------------------------------------------------
# High-level convenience API (derive key + load/save in one call)
# ---------------------------------------------------------------------------

def cached_bibliography(cache_dir: Optional[str], input_spec: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Return cached bibliography for *input_spec*, or None on miss/disabled."""
    if not cache_dir or not input_spec:
        return None
    return load_cached_bibliography(cache_dir, cache_key_for_spec(input_spec))


def cache_bibliography(cache_dir: Optional[str], input_spec: Optional[str], bibliography: List[Dict[str, Any]]) -> None:
    """Save *bibliography* to the cache (no-op when caching is disabled)."""
    if not cache_dir or not input_spec or not bibliography:
        return
    save_cached_bibliography(cache_dir, cache_key_for_spec(input_spec), bibliography)


def cached_pdf(cache_dir: Optional[str], input_spec: Optional[str]) -> Optional[BytesIO]:
    """Return cached PDF for *input_spec*, or None on miss/disabled."""
    if not cache_dir or not input_spec:
        return None
    return load_cached_pdf(cache_dir, cache_key_for_spec(input_spec))


def cache_pdf(cache_dir: Optional[str], input_spec: Optional[str], pdf_content: BytesIO) -> None:
    """Save *pdf_content* to the cache (no-op when caching is disabled)."""
    if not cache_dir or not input_spec or not pdf_content:
        return
    save_cached_pdf(cache_dir, cache_key_for_spec(input_spec), pdf_content)


# ---------------------------------------------------------------------------
# LLM response cache
# ---------------------------------------------------------------------------

def _llm_cache_key(model: str, *prompt_parts: str) -> str:
    """Derive a hex digest from the model name and all prompt parts."""
    h = hashlib.sha256()
    h.update(model.encode())
    for part in prompt_parts:
        h.update(part.encode())
    return h.hexdigest()


def load_cached_llm_response(cache_dir: str, key: str) -> Optional[Dict[str, Any]]:
    """Return cached LLM response dict, or None on miss."""
    path = os.path.join(cache_dir, 'llm_responses', f'{key}.json')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            logger.debug("LLM cache hit: %s", key[:16])
            return data
    except Exception as exc:
        logger.debug("LLM cache read error for %s: %s", key[:16], exc)
    return None


def save_cached_llm_response(cache_dir: str, key: str, response: Dict[str, Any]) -> None:
    """Persist an LLM response dict to the cache."""
    resp_dir = os.path.join(cache_dir, 'llm_responses')
    os.makedirs(resp_dir, exist_ok=True)
    path = os.path.join(resp_dir, f'{key}.json')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(response, f, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Failed to write LLM cache %s: %s", key[:16], exc)


def cached_llm_response(cache_dir: Optional[str], model: str, *prompt_parts: str) -> Optional[Dict[str, Any]]:
    """Return a cached LLM response, or None on miss/disabled."""
    if not cache_dir:
        return None
    key = _llm_cache_key(model, *prompt_parts)
    return load_cached_llm_response(cache_dir, key)


def cache_llm_response(cache_dir: Optional[str], model: str, *prompt_parts: str, response: Dict[str, Any]) -> None:
    """Save an LLM response (no-op when caching is disabled)."""
    if not cache_dir:
        return
    key = _llm_cache_key(model, *prompt_parts)
    save_cached_llm_response(cache_dir, key, response)


# ---------------------------------------------------------------------------
# External API response cache (Semantic Scholar, CrossRef, OpenAlex, etc.)
# ---------------------------------------------------------------------------

def _api_cache_key(service: str, method: str, query: str) -> str:
    """Derive a hex digest from service + method + exact query string."""
    h = hashlib.sha256()
    h.update(service.encode())
    h.update(b'\x00')
    h.update(method.encode())
    h.update(b'\x00')
    h.update(query.encode())
    return h.hexdigest()


def cached_api_response(cache_dir: Optional[str], service: str, method: str, query: str) -> Optional[Any]:
    """Return a cached API response, or None on miss/disabled.

    Parameters
    ----------
    cache_dir : str or None
        Root cache directory (None disables caching).
    service : str
        Service name (e.g. ``'semantic_scholar'``, ``'crossref'``).
    method : str
        Method name (e.g. ``'search_paper'``, ``'get_by_doi'``).
    query : str
        Exact query string — cache only hits on exact match.
    """
    if not cache_dir:
        return None
    key = _api_cache_key(service, method, query)
    path = os.path.join(cache_dir, 'api_cache', service, f'{key}.json')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.debug("API cache hit: %s/%s %s", service, method, key[:12])
        return data
    except Exception as exc:
        logger.debug("API cache read error for %s: %s", key[:12], exc)
    return None


def cache_api_response(cache_dir: Optional[str], service: str, method: str, query: str, response: Any) -> None:
    """Save an API response (no-op when caching is disabled or response is None)."""
    if not cache_dir or response is None:
        return
    key = _api_cache_key(service, method, query)
    resp_dir = os.path.join(cache_dir, 'api_cache', service)
    os.makedirs(resp_dir, exist_ok=True)
    path = os.path.join(resp_dir, f'{key}.json')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(response, f, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Failed to write API cache %s: %s", key[:12], exc)
