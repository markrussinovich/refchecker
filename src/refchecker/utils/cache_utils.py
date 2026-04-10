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
