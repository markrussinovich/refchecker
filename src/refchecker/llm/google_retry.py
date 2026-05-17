"""Shared retry helpers for Google Gemini API calls."""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

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