"""Hạn chế tần suất và retry cho các gọi API."""
import time
import logging
from functools import wraps
from typing import Callable, Any
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """Bộ hạn chế tần suất đơn giản dùng cửa sổ trượt."""

    def __init__(self, max_calls: int, time_window: int = 60):
        """Khởi tạo rate limiter: `max_calls` trong `time_window` giây."""
        self.max_calls = max_calls
        self.time_window = time_window
        self.call_times = deque()
    
    def is_allowed(self) -> tuple[bool, float]:
        """Trả về (cho phép, thời_giờ_chờ_s) cho lần gọi tiếp theo."""
        now = time.time()
        
        # Remove calls outside the time window
        while self.call_times and now - self.call_times[0] >= self.time_window:
            self.call_times.popleft()
        
        # Check if we can make a new call
        if len(self.call_times) < self.max_calls:
            return True, 0.0
        
        # Calculate wait time until oldest call expires
        wait_time = self.time_window - (now - self.call_times[0])
        return False, max(0, wait_time)
    
    def add_call(self):
        """Ghi nhận một lần gọi API mới."""
        self.call_times.append(time.time())
    
    def reset(self):
        """Đặt lại bộ đếm rate limiter."""
        self.call_times.clear()


# Global rate limiters for different APIs
openai_limiter = RateLimiter(max_calls=200, time_window=60)  # 200 calls/minute
plagiarism_limiter = RateLimiter(max_calls=200, time_window=60)  # 200 calls/minute


def rate_limit(limiter: RateLimiter):
    """
    Decorator to apply rate limiting to a function.
    
    Args:
        limiter: RateLimiter instance to use
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            is_allowed, wait_time = limiter.is_allowed()
            
            if not is_allowed:
                logger.warning(f"Rate limit exceeded for {func.__name__}. Wait {wait_time:.1f}s")
                raise RateLimitError(
                    f"Đã vượt giới hạn API. Vui lòng đợi {wait_time:.0f} giây.",
                    wait_time
                )
            
            limiter.add_call()
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0
):
    """Decorator retry với backoff mũ cho lỗi rate-limit.

    Tham số: `max_retries`, `initial_delay`, `max_delay`, `exponential_base`.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    error_str = str(e).lower()
                    
                    # Check if it's a rate limit error. Be careful about negations
                    is_rate_limit = (
                        "429" in error_str or 
                        "rate limit" in error_str or 
                        "quota" in error_str or
                        isinstance(e, RateLimitError)
                    )

                    # Avoid false positives like "not a rate limit" or "no rate limit"
                    negations = [
                        "not a rate limit",
                        "not rate limit",
                        "no rate limit",
                        "not a rate-limit",
                        "not a rate limit error",
                        "is not a rate limit",
                        "isn't a rate limit",
                    ]
                    if any(neg in error_str for neg in negations):
                        is_rate_limit = False
                    
                    if not is_rate_limit or attempt == max_retries:
                        # Not a rate limit error or final attempt, raise it
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay = min(initial_delay * (exponential_base ** attempt), max_delay)
                    
                    logger.warning(
                        f"{func.__name__} rate limited (attempt {attempt + 1}/{max_retries}). "
                        f"Đợi {delay:.1f}s trước khi thử lại..."
                    )
                    
                    time.sleep(delay)
            
            # Should never reach here, but just in case
            raise last_exception
        
        return wrapper
    return decorator


class RateLimitError(Exception):
    """Exception raised when rate limit is exceeded."""
    
    def __init__(self, message: str, wait_time: float):
        self.wait_time = wait_time
        super().__init__(message)
