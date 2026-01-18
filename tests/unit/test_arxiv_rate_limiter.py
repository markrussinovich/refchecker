#!/usr/bin/env python3
"""
Unit tests for the ArXiv Rate Limiter utility.
"""

import pytest
import time
import threading

from refchecker.utils.arxiv_rate_limiter import ArXivRateLimiter


class TestArXivRateLimiter:
    """Tests for the ArXiv Rate Limiter singleton."""
    
    def setup_method(self):
        """Reset the singleton before each test."""
        ArXivRateLimiter.reset_instance()
    
    def teardown_method(self):
        """Reset the singleton after each test."""
        ArXivRateLimiter.reset_instance()
    
    def test_singleton_instance(self):
        """Test that get_instance returns the same object."""
        limiter1 = ArXivRateLimiter.get_instance()
        limiter2 = ArXivRateLimiter.get_instance()
        
        assert limiter1 is limiter2
    
    def test_reset_instance(self):
        """Test that reset_instance creates a new object."""
        limiter1 = ArXivRateLimiter.get_instance()
        ArXivRateLimiter.reset_instance()
        limiter2 = ArXivRateLimiter.get_instance()
        
        assert limiter1 is not limiter2
    
    def test_default_delay(self):
        """Test that default delay is 3 seconds (ArXiv recommended)."""
        limiter = ArXivRateLimiter.get_instance()
        
        assert limiter.delay == 3.0
    
    def test_set_delay(self):
        """Test that delay can be changed."""
        limiter = ArXivRateLimiter.get_instance()
        limiter.delay = 1.0
        
        assert limiter.delay == 1.0
    
    def test_minimum_delay_enforced(self):
        """Test that delay cannot be set below 0.5 seconds."""
        limiter = ArXivRateLimiter.get_instance()
        limiter.delay = 0.1  # Too low
        
        assert limiter.delay == 0.5  # Should be clamped
    
    def test_wait_first_call_immediate(self):
        """Test that first wait call is immediate."""
        limiter = ArXivRateLimiter.get_instance()
        limiter.delay = 1.0
        
        start = time.time()
        wait_time = limiter.wait()
        elapsed = time.time() - start
        
        # First call should be very quick (< 0.1 seconds)
        assert elapsed < 0.1
        assert wait_time == 0.0
    
    def test_wait_second_call_delayed(self):
        """Test that second wait call is delayed."""
        limiter = ArXivRateLimiter.get_instance()
        limiter.delay = 0.5  # Short delay for testing
        
        # First call
        limiter.wait()
        
        # Second call should wait
        start = time.time()
        limiter.wait()
        elapsed = time.time() - start
        
        # Should have waited close to 0.5 seconds
        assert elapsed >= 0.4  # Allow some tolerance
    
    def test_time_until_next(self):
        """Test time_until_next calculation."""
        limiter = ArXivRateLimiter.get_instance()
        limiter.delay = 1.0
        
        # Before any request
        assert limiter.time_until_next() == 0.0
        
        # After a request
        limiter.wait()
        remaining = limiter.time_until_next()
        
        # Should be close to the delay
        assert 0.9 <= remaining <= 1.0
    
    def test_mark_request(self):
        """Test mark_request updates last request time."""
        limiter = ArXivRateLimiter.get_instance()
        limiter.delay = 1.0
        
        # Mark a request
        limiter.mark_request()
        
        # Next call should wait
        remaining = limiter.time_until_next()
        assert remaining > 0.9
    
    def test_thread_safety(self):
        """Test that rate limiter is thread-safe."""
        limiter = ArXivRateLimiter.get_instance()
        limiter.delay = 0.1  # Short delay for testing
        
        call_times = []
        errors = []
        
        def make_request():
            try:
                limiter.wait()
                call_times.append(time.time())
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = [threading.Thread(target=make_request) for _ in range(5)]
        
        start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start
        
        # Should have no errors
        assert len(errors) == 0
        
        # All calls should have completed
        assert len(call_times) == 5
        
        # Calls should be spaced apart (at least some delay between them)
        # With 5 calls and 0.1s delay, minimum elapsed should be ~0.4s
        assert elapsed >= 0.3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
