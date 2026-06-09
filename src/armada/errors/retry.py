"""Retry logic for LLM calls and other transient failures."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    base_delay: float = 2.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0
    retryable_exceptions: tuple[type[Exception], ...] = (TimeoutError, ConnectionError)


class RetriesExhausted(Exception):
    """All retry attempts failed."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"Failed after {attempts} attempts: {last_error}")


class SkippedAfterRetry(Exception):
    """Operation was skipped after retries were exhausted."""

    def __init__(self, grain_id: str, reason: str) -> None:
        self.grain_id = grain_id
        self.reason = reason
        super().__init__(f"Skipped grain {grain_id}: {reason}")


def with_retry[T](
    fn: Callable[[], T],
    config: RetryConfig | None = None,
    operation_name: str = "operation",
) -> T:
    """Execute fn with retry logic. Raises RetriesExhausted if all attempts fail."""
    cfg = config or RetryConfig()
    last_error: Exception | None = None

    for attempt in range(1, cfg.max_attempts + 1):
        try:
            return fn()
        except cfg.retryable_exceptions as e:
            last_error = e
            if attempt == cfg.max_attempts:
                break
            delay = min(cfg.base_delay * (cfg.backoff_factor ** (attempt - 1)), cfg.max_delay)
            logger.warning(
                "%s failed (attempt %d/%d), retrying in %.1fs: %s",
                operation_name,
                attempt,
                cfg.max_attempts,
                delay,
                e,
            )
            time.sleep(delay)

    assert last_error is not None
    raise RetriesExhausted(cfg.max_attempts, last_error)
