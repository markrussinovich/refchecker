"""
Global concurrency limiter for reference checking across all papers.

This module provides a system-wide semaphore that limits the total number
of concurrent reference checks, regardless of how many papers are being
checked simultaneously.
"""
import asyncio
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Default max concurrent reference checks
DEFAULT_MAX_CONCURRENT = 6

class GlobalConcurrencyLimiter:
    """
    System-wide concurrency limiter for reference checks.
    
    Uses a semaphore to limit total concurrent operations across
    all paper checks.
    """
    
    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT):
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_count = 0
        self._lock = asyncio.Lock()
    
    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent
    
    @property
    def active_count(self) -> int:
        return self._active_count
    
    async def set_max_concurrent(self, value: int):
        """
        Update the max concurrent limit.
        
        Note: This recreates the semaphore, so it should only be called
        when no operations are in progress, or the caller should be aware
        that current limits may temporarily exceed the new value.
        """
        if value < 1:
            value = 1
        if value > 50:
            value = 50
        
        async with self._lock:
            old_value = self._max_concurrent
            self._max_concurrent = value
            self._semaphore = asyncio.Semaphore(value)
            logger.info(f"Global concurrency limit changed from {old_value} to {value}")
    
    async def acquire(self):
        """Acquire a slot in the concurrency pool."""
        await self._semaphore.acquire()
        async with self._lock:
            self._active_count += 1
            logger.debug(f"Acquired slot, active: {self._active_count}/{self._max_concurrent}")
    
    def release(self):
        """Release a slot back to the concurrency pool."""
        self._semaphore.release()
        # Note: can't use async lock in sync context, so we do best-effort count
        self._active_count = max(0, self._active_count - 1)
        logger.debug(f"Released slot, active: {self._active_count}/{self._max_concurrent}")
    
    async def __aenter__(self):
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


# Global singleton instance
_limiter: Optional[GlobalConcurrencyLimiter] = None


def get_limiter() -> GlobalConcurrencyLimiter:
    """Get the global concurrency limiter instance."""
    global _limiter
    if _limiter is None:
        _limiter = GlobalConcurrencyLimiter()
    return _limiter


async def init_limiter(max_concurrent: int = DEFAULT_MAX_CONCURRENT):
    """Initialize or reinitialize the global limiter with a specific limit."""
    global _limiter
    if _limiter is None:
        _limiter = GlobalConcurrencyLimiter(max_concurrent)
    else:
        await _limiter.set_max_concurrent(max_concurrent)
    return _limiter
