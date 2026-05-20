"""Shared retry helpers for Google Gemini API calls."""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')

GOOGLE_RETRY_ATTEMPTS = 5
GOOGLE_RETRY_INITIAL_DELAY_SECONDS = 1.0
GOOGLE_RETRY_MAX_DELAY_SECONDS = 60.0


def call_google_with_retry(call: Callable[[], T], *, purpose: str) -> T:
    """Call Gemini with truncated exponential backoff for transient errors."""
    for attempt in range(GOOGLE_RETRY_ATTEMPTS):
        try:
            return call()
        except Exception as exc:
            if not is_google_retryable_error(exc) or attempt == GOOGLE_RETRY_ATTEMPTS - 1:
                raise
            wait_time = min(
                GOOGLE_RETRY_MAX_DELAY_SECONDS,
                GOOGLE_RETRY_INITIAL_DELAY_SECONDS * (2 ** attempt) + random.random(),
            )
            logger.debug(
                'Google %s transient error (%s); retrying in %.1fs (%d/%d)',
                purpose,
                exc,
                wait_time,
                attempt + 2,
                GOOGLE_RETRY_ATTEMPTS,
            )
            time.sleep(wait_time)

    raise RuntimeError('unreachable Google retry state')


def extract_google_response_text(response: Any) -> str:
    """Return text from a Gemini response without fragile SDK serialization.

    ``GenerateContentResponse.text`` serializes every non-text part before
    returning text. Some preview models can include Search-like parts that are
    not compatible with that path, causing raw SDK errors such as
    ``'Search' object has no attribute 'results'``. Reading text parts directly
    keeps extraction resilient while ignoring tool metadata.
    """
    candidates = getattr(response, 'candidates', None) or []
    if candidates:
        candidate = candidates[0]
        content = getattr(candidate, 'content', None)
        parts = getattr(content, 'parts', None) or []
        text_parts = []
        for part in parts:
            try:
                if getattr(part, 'thought', False):
                    continue
                text = getattr(part, 'text', None)
            except (AttributeError, TypeError, ValueError):
                continue
            if isinstance(text, str):
                text_parts.append(text)
        if text_parts:
            return ''.join(text_parts)

    try:
        text = getattr(response, 'text', None)
    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug('Google response.text accessor failed: %s', exc)
        return ''
    return text if isinstance(text, str) else ''


def is_google_retryable_error(exc: Exception) -> bool:
    """Return True for transient Google/API transport errors worth retrying."""
    text = str(exc).lower()
    return (
        '429' in text
        or '408' in text
        or '500' in text
        or '502' in text
        or '503' in text
        or '504' in text
        or 'resource_exhausted' in text
        or 'rate limit' in text
        or 'quota' in text
        or 'timeout' in text
        or 'temporarily unavailable' in text
        or 'unavailable' in text
        or 'unexpected_eof' in text
        or 'eof occurred' in text
        or 'ssleoferror' in text
        or 'connection reset' in text
        or 'connection aborted' in text
        or 'remote end closed connection' in text
    )