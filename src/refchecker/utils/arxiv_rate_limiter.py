"""
Shared ArXiv Rate Limiter utility.

ArXiv requests a polite delay of 3 seconds between requests.
This module provides a centralized rate limiter to coordinate all ArXiv API calls
across different checkers and utilities.

Usage:
    from refchecker.utils.arxiv_rate_limiter import ArXivRateLimiter
    
    # Get the shared limiter instance
    limiter = ArXivRateLimiter.get_instance()
    
    # Wait for rate limit before making a request
    limiter.wait()
    
    # Then make your request
    response = requests.get(arxiv_url)
"""

import time
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)


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
