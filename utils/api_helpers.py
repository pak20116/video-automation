import time
import functools
import logging
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


_RETRYABLE_CODES = {429, 500, 502, 503, 504}


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc)
    return any(str(c) in msg for c in _RETRYABLE_CODES) or "UNAVAILABLE" in msg or "RATE_LIMIT" in msg


def with_retry(max_attempts: int = 6, delay_seconds: float = 5.0, backoff: float = 2.0):
    """Retry on exception with exponential backoff. Defaults tuned for Gemini 503 spikes."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            attempt = 0
            current_delay = delay_seconds
            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if attempt >= max_attempts or not _is_retryable(e):
                        logger.error(f"{func.__name__} failed after {attempt} attempts: {e}")
                        raise
                    logger.warning(
                        f"{func.__name__} attempt {attempt} failed: {e}. "
                        f"Retrying in {current_delay:.0f}s..."
                    )
                    time.sleep(current_delay)
                    current_delay = min(current_delay * backoff, 60.0)
        return wrapper
    return decorator
