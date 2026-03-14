"""
Shared ArXiv Rate Limiter utility.

ArXiv requests a polite delay of 3 seconds between requests.
This module provides a centralized rate limiter to coordinate all ArXiv API calls
across different checkers and utilities.

Also provides a thread-safe HTTP response cache for ArXiv pages.  ArXiv content
is immutable per version URL, so caching HTML responses avoids redundant fetches
that would otherwise burn rate-limiter slots.

Usage:
    from refchecker.utils.arxiv_rate_limiter import ArXivRateLimiter, arxiv_cached_get
    
    # Get the shared limiter instance
    limiter = ArXivRateLimiter.get_instance()
    
    # Preferred: cached GET that respects the rate limiter automatically
    response_text = arxiv_cached_get("https://arxiv.org/abs/1706.03762v7")
    
    # Manual: wait then make your own request
    limiter.wait()
    response = requests.get(arxiv_url)
"""

import time
import threading
import logging
from typing import Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


# ── Thread-safe ArXiv response cache ──

class _ArxivCache:
    """Thread-safe in-memory cache for ArXiv HTTP GET responses."""

    def __init__(self, max_size: int = 2000):
        self._cache: Dict[str, Tuple[int, str]] = {}  # url -> (status_code, text)
        self._lock = threading.Lock()
        self._max_size = max_size
        self.hits = 0
        self.misses = 0

    def get(self, url: str) -> Optional[Tuple[int, str]]:
        with self._lock:
            entry = self._cache.get(url)
            if entry is not None:
                self.hits += 1
                return entry
            self.misses += 1
            return None

    def put(self, url: str, status_code: int, text: str) -> None:
        with self._lock:
            if len(self._cache) >= self._max_size:
                # Simple eviction: drop oldest quarter
                keys = list(self._cache.keys())
                for k in keys[: len(keys) // 4]:
                    del self._cache[k]
            self._cache[url] = (status_code, text)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                'size': len(self._cache),
                'hits': self.hits,
                'misses': self.misses,
            }


_arxiv_cache = _ArxivCache()


def arxiv_cached_get(url: str, timeout: float = 30.0) -> Optional[str]:
    """Fetch an ArXiv URL with caching and rate-limiting.

    Returns the response text (HTML/BibTeX) or None on failure.
    Raises nothing — failures are logged and return None.
    """
    cached = _arxiv_cache.get(url)
    if cached is not None:
        status, text = cached
        if status == 404:
            return None
        return text

    limiter = ArXivRateLimiter.get_instance()
    limiter.wait()

    try:
        resp = requests.get(url, timeout=timeout)
        _arxiv_cache.put(url, resp.status_code, resp.text)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as exc:
        logger.debug(f"arxiv_cached_get failed for {url}: {exc}")
        return None


def get_arxiv_cache_stats() -> Dict[str, int]:
    """Return cache hit/miss statistics."""
    return _arxiv_cache.stats()


class ArXivRateLimiter:
    """
    Singleton rate limiter for ArXiv API requests.
    
    ArXiv requests a minimum of 3 seconds between requests for polite access.
    This class ensures all ArXiv API calls from any part of refchecker
    are properly rate limited.
    """
    
    _instance: Optional['ArXivRateLimiter'] = None
    _lock = threading.Lock()
    
    # ArXiv recommends at least 3 seconds between requests
    DEFAULT_DELAY = 3.0
    
    def __init__(self):
        """Initialize the rate limiter (use get_instance() instead of direct construction)."""
        self._last_request_time: float = 0.0
        self._request_lock = threading.Lock()
        self._delay: float = self.DEFAULT_DELAY
    
    @classmethod
    def get_instance(cls) -> 'ArXivRateLimiter':
        """
        Get the singleton instance of the ArXiv rate limiter.
        
        Returns:
            The shared ArXivRateLimiter instance
        """
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """
        Reset the singleton instance (primarily for testing).
        """
        with cls._lock:
            cls._instance = None
    
    @property
    def delay(self) -> float:
        """Get the current delay between requests in seconds."""
        return self._delay
    
    @delay.setter
    def delay(self, value: float) -> None:
        """
        Set the delay between requests.
        
        Args:
            value: Delay in seconds (minimum 0.5 seconds enforced)
        """
        self._delay = max(0.5, value)
    
    def wait(self) -> float:
        """
        Wait for the rate limit before making a request.
        
        This method blocks until the required time has passed since the last request.
        It is thread-safe and can be called from multiple threads simultaneously.
        
        Returns:
            The actual time waited in seconds (0 if no wait was needed)
        """
        with self._request_lock:
            current_time = time.time()
            time_since_last = current_time - self._last_request_time
            
            if time_since_last < self._delay:
                wait_time = self._delay - time_since_last
                logger.debug(f"ArXiv rate limiter: waiting {wait_time:.2f}s")
                time.sleep(wait_time)
            else:
                wait_time = 0.0
            
            self._last_request_time = time.time()
            return wait_time
    
    def mark_request(self) -> None:
        """
        Mark that a request was just made (without waiting).
        
        Use this if you're managing timing externally but still want to
        update the rate limiter's state.
        """
        with self._request_lock:
            self._last_request_time = time.time()
    
    def time_until_next(self) -> float:
        """
        Get the time remaining until the next request is allowed.
        
        Returns:
            Time in seconds until next request (0 if allowed now)
        """
        with self._request_lock:
            current_time = time.time()
            time_since_last = current_time - self._last_request_time
            remaining = self._delay - time_since_last
            return max(0.0, remaining)
