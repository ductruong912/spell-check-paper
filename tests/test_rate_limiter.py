"""Unit tests for rate limiter functionality."""
import unittest
import time
from utils.rate_limiter import RateLimiter, rate_limit, retry_with_backoff, RateLimitError


class TestRateLimiter(unittest.TestCase):
    """Test RateLimiter class."""
    
    def test_basic_rate_limiting(self):
        """Test basic rate limiting allows calls within limit."""
        limiter = RateLimiter(max_calls=3, time_window=1)
        
        # First 3 calls should be allowed
        for i in range(3):
            is_allowed, wait_time = limiter.is_allowed()
            self.assertTrue(is_allowed, f"Call {i+1} should be allowed")
            self.assertEqual(wait_time, 0.0)
            limiter.add_call()
        
        # 4th call should be blocked
        is_allowed, wait_time = limiter.is_allowed()
        self.assertFalse(is_allowed, "4th call should be blocked")
        self.assertGreater(wait_time, 0, "Wait time should be > 0")
    
    def test_sliding_window(self):
        """Test sliding window allows calls after time passes."""
        limiter = RateLimiter(max_calls=2, time_window=1)
        
        # First 2 calls
        limiter.add_call()
        limiter.add_call()
        
        # 3rd call should be blocked
        is_allowed, _ = limiter.is_allowed()
        self.assertFalse(is_allowed)
        
        # Wait for window to pass
        time.sleep(1.1)
        
        # Now should be allowed again
        is_allowed, wait_time = limiter.is_allowed()
        self.assertTrue(is_allowed, "Call should be allowed after window expires")
        self.assertEqual(wait_time, 0.0)
    
    def test_reset(self):
        """Test reset clears all recorded calls."""
        limiter = RateLimiter(max_calls=2, time_window=10)
        
        # Fill up the limit
        limiter.add_call()
        limiter.add_call()
        
        # Should be blocked
        is_allowed, _ = limiter.is_allowed()
        self.assertFalse(is_allowed)
        
        # Reset
        limiter.reset()
        
        # Should be allowed now
        is_allowed, wait_time = limiter.is_allowed()
        self.assertTrue(is_allowed)
        self.assertEqual(wait_time, 0.0)


class TestRateLimitDecorator(unittest.TestCase):
    """Test rate_limit decorator."""
    
    def test_decorator_blocks_excess_calls(self):
        """Test decorator blocks calls exceeding rate limit."""
        limiter = RateLimiter(max_calls=2, time_window=10)
        
        @rate_limit(limiter)
        def test_function():
            return "success"
        
        # First 2 calls should work
        self.assertEqual(test_function(), "success")
        self.assertEqual(test_function(), "success")
        
        # 3rd call should raise RateLimitError
        with self.assertRaises(RateLimitError) as cm:
            test_function()
        
        self.assertIn("Đã vượt giới hạn API", str(cm.exception))


class TestRetryWithBackoff(unittest.TestCase):
    """Test retry_with_backoff decorator."""
    
    def test_retry_on_rate_limit(self):
        """Test retry decorator retries on rate limit errors."""
        call_count = [0]
        
        @retry_with_backoff(max_retries=2, initial_delay=0.1)
        def flaky_function():
            call_count[0] += 1
            if call_count[0] < 3:
                raise RateLimitError("Rate limited", 0.1)
            return "success"
        
        # Should succeed after 3 attempts (1 initial + 2 retries)
        result = flaky_function()
        self.assertEqual(result, "success")
        self.assertEqual(call_count[0], 3)
    
    def test_no_retry_on_non_rate_limit_error(self):
        """Test retry decorator doesn't retry on non-rate-limit errors."""
        call_count = [0]
        
        @retry_with_backoff(max_retries=2)
        def failing_function():
            call_count[0] += 1
            raise ValueError("Not a rate limit error")
        
        # Should raise immediately without retry
        with self.assertRaises(ValueError):
            failing_function()
        
        self.assertEqual(call_count[0], 1, "Should only call once")
    
    def test_max_retries_exceeded(self):
        """Test retry decorator raises after max retries."""
        call_count = [0]
        
        @retry_with_backoff(max_retries=2, initial_delay=0.01)
        def always_fails():
            call_count[0] += 1
            raise RateLimitError("Always rate limited", 0.01)
        
        # Should fail after max retries
        with self.assertRaises(RateLimitError):
            always_fails()
        
        # Should have called 3 times (1 initial + 2 retries)
        self.assertEqual(call_count[0], 3)


if __name__ == '__main__':
    unittest.main()
