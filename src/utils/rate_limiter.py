"""Hạn chế tần suất và retry/backoff cho các gọi API."""

import time
import logging
from functools import wraps
from typing import Callable, Any
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """Rate limiter cửa sổ trượt (max_calls / time_window)."""

    def __init__(self, max_calls: int, time_window: int = 60):
        """Giới hạn max_calls trong time_window (giây)."""
        self.max_calls = max_calls
        self.time_window = time_window
        self.call_times = deque()

    def is_allowed(self) -> tuple[bool, float]:
        """Trả (allowed, wait_seconds) cho lần gọi tiếp theo."""
        now = time.time()

        # Loại các call đã quá cửa sổ
        while self.call_times and now - self.call_times[0] >= self.time_window:
            self.call_times.popleft()

        if len(self.call_times) < self.max_calls:
            return True, 0.0

        wait_time = self.time_window - (now - self.call_times[0])
        return False, max(0, wait_time)

    def add_call(self):
        """Ghi nhận 1 lần gọi."""
        self.call_times.append(time.time())

    def reset(self):
        """Reset bộ đếm."""
        self.call_times.clear()


# ----------------------------
# Global limiters
# ----------------------------
openai_limiter = RateLimiter(max_calls=200, time_window=60)       # 200 calls/min
plagiarism_limiter = RateLimiter(max_calls=200, time_window=60)   # 200 calls/min


def rate_limit(limiter: RateLimiter):
    """Decorator: chặn khi vượt limiter."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            is_allowed, wait_time = limiter.is_allowed()

            if not is_allowed:
                logger.warning(f"Rate limit exceeded for {func.__name__}. Wait {wait_time:.1f}s")
                raise RateLimitError(
                    f"Đã vượt giới hạn API. Vui lòng đợi {wait_time:.0f} giây.",
                    wait_time,
                )

            limiter.add_call()
            return func(*args, **kwargs)

        return wrapper
    return decorator


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
):
    """Decorator: retry khi gặp rate-limit (exponential backoff)."""
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

                    is_rate_limit = (
                        "429" in error_str
                        or "rate limit" in error_str
                        or "quota" in error_str
                        or isinstance(e, RateLimitError)
                    )

                    # Tránh match nhầm các câu phủ định
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

                    if (not is_rate_limit) or attempt == max_retries:
                        raise

                    delay = min(initial_delay * (exponential_base ** attempt), max_delay)
                    logger.warning(
                        f"{func.__name__} rate limited (attempt {attempt + 1}/{max_retries}). "
                        f"Đợi {delay:.1f}s trước khi thử lại..."
                    )
                    time.sleep(delay)

            raise last_exception  # fallback

        return wrapper
    return decorator


class RateLimitError(Exception):
    """Lỗi vượt rate limit (kèm wait_time)."""

    def __init__(self, message: str, wait_time: float):
        self.wait_time = wait_time
        super().__init__(message)