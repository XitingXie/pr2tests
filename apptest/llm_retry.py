"""Retry logic for LLM API calls with exponential backoff."""

import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 2.0  # seconds
MAX_DELAY = 30.0  # seconds


def is_retryable(exc: Exception) -> bool:
    """Check if an exception is a transient error worth retrying."""
    exc_str = str(exc)
    # Rate limit (429) or server error (5xx)
    if "429" in exc_str or "rate_limit" in exc_str.lower():
        return True
    if any(code in exc_str for code in ("500", "502", "503", "504")):
        return True
    if "timeout" in exc_str.lower() or "timed out" in exc_str.lower():
        return True
    return False


def retry_llm_call(func):
    """Decorator: retry LLM calls on transient errors with exponential backoff."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        last_exc = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt < MAX_RETRIES and is_retryable(exc):
                    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    logger.warning(
                        "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, MAX_RETRIES + 1, delay, exc,
                    )
                    time.sleep(delay)
                else:
                    raise
        raise last_exc  # unreachable, but satisfies type checker

    return wrapper
