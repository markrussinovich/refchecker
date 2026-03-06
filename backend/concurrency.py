"""
Concurrency limiter for reference checking.

This module provides a per-session semaphore that limits the number
of concurrent reference checks within each paper check session.
Each session gets its own limiter so sessions don't block each other.
"""
import asyncio
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Default max concurrent reference checks per session
DEFAULT_MAX_CONCURRENT = 6

class SessionConcurrencyLimiter:
    """
    Per-session concurrency limiter for reference checks.
    
    Each paper check session creates its own limiter so that
    concurrent sessions don't compete for slots.
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
    
    async def acquire(self):
        """Acquire a slot in the concurrency pool."""
        await self._semaphore.acquire()
        async with self._lock:
            self._active_count += 1
            logger.debug(f"Acquired slot, active: {self._active_count}/{self._max_concurrent}")
    
    def release(self):
        """Release a slot back to the concurrency pool."""
        self._semaphore.release()
        self._active_count = max(0, self._active_count - 1)
        logger.debug(f"Released slot, active: {self._active_count}/{self._max_concurrent}")
    
    async def __aenter__(self):
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


# Global default limit (configurable via settings)
_default_max_concurrent: int = DEFAULT_MAX_CONCURRENT


def create_limiter(max_concurrent: Optional[int] = None) -> SessionConcurrencyLimiter:
    """Create a new per-session concurrency limiter."""
    limit = max_concurrent if max_concurrent is not None else _default_max_concurrent
    return SessionConcurrencyLimiter(limit)


async def set_default_max_concurrent(value: int):
    """Update the default max concurrent limit for new sessions."""
    global _default_max_concurrent
    if value < 1:
        value = 1
    if value > 50:
        value = 50
    old = _default_max_concurrent
    _default_max_concurrent = value
    logger.info(f"Default per-session concurrency limit changed from {old} to {value}")


def get_default_max_concurrent() -> int:
    """Return the current default max concurrent value."""
    return _default_max_concurrent


# Backward-compatible aliases
GlobalConcurrencyLimiter = SessionConcurrencyLimiter

_limiter: Optional[SessionConcurrencyLimiter] = None

def get_limiter() -> SessionConcurrencyLimiter:
    """Get a default limiter instance (for backward compat / settings display)."""
    global _limiter
    if _limiter is None:
        _limiter = SessionConcurrencyLimiter(_default_max_concurrent)
    return _limiter

async def init_limiter(max_concurrent: int = DEFAULT_MAX_CONCURRENT):
    """Initialize the default concurrency setting."""
    await set_default_max_concurrent(max_concurrent)
    global _limiter
    _limiter = SessionConcurrencyLimiter(max_concurrent)
    return _limiter
