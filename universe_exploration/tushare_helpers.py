"""
tushare_helpers.py — Shared Tushare-side utilities for universe_exploration/.

Provides:
  - `pro` singleton (imported from repo-root tushare_setup via sys.path.append)
  - RateLimiter class (thread-safe sliding-window throttle)
  - retry_on_network_error decorator
  - read_parquet_safe (cache validation per feedback_cache_validation memory)

Mirrors patterns from Project_6/New_Universe_Construction/daily_panel_pull.py
and Project_5/liquidity_panel.py without copying them, so the new workspace
is self-contained.
"""

from __future__ import annotations

import sys
import time
import threading
import functools
from collections import deque
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

# ─── tushare_setup import (May-7 handover rule: APPEND, not insert(0)) ──
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))
from tushare_setup import pro  # noqa: E402

import config  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════
# RateLimiter — thread-safe sliding-window throttle
# ═══════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Sliding-window rate limiter shared across threads."""

    def __init__(
        self,
        max_calls: int = config.TUSHARE_MAX_CALLS_PER_MIN,
        window: float = config.TUSHARE_RATE_LIMIT_WINDOW,
    ) -> None:
        self.max_calls = max_calls
        self.window = window
        self._lock = threading.Lock()
        self._timestamps: deque[float] = deque()

    def acquire(self) -> None:
        """Block until adding a call would not exceed max_calls/window."""
        while True:
            with self._lock:
                now = time.time()
                while self._timestamps and (now - self._timestamps[0]) > self.window:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_calls:
                    self._timestamps.append(now)
                    return
                wait_for = self.window - (now - self._timestamps[0]) + 0.05
            time.sleep(max(0.05, wait_for))


_rate_limiter = RateLimiter()


def acquire_rate_token() -> None:
    """Module-level entry to the shared limiter."""
    _rate_limiter.acquire()


# ═══════════════════════════════════════════════════════════════════════
# Retry decorator
# ═══════════════════════════════════════════════════════════════════════

_TRANSIENT_ERRORS = (
    requests.exceptions.ReadTimeout,
    requests.exceptions.ConnectTimeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


def retry_on_network_error(
    max_attempts: int = 4,
    base_delay: float = 2.0,
    label: str = "",
) -> Callable:
    """
    Decorator: retry on transient network exceptions with exp backoff.

    Usage:
        @retry_on_network_error(max_attempts=4, label="hk_hold")
        def fetch_one(date): ...
    """

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except _TRANSIENT_ERRORS as exc:
                    last_err = exc
                    if attempt == max_attempts:
                        break
                    delay = base_delay * (2 ** (attempt - 1))
                    print(
                        f"  [retry {label}] attempt {attempt} failed "
                        f"({type(exc).__name__}); sleeping {delay:.1f}s"
                    )
                    time.sleep(delay)
            raise last_err  # type: ignore[misc]

        return wrapper

    return deco


# ═══════════════════════════════════════════════════════════════════════
# Cache validation
# ═══════════════════════════════════════════════════════════════════════

def read_parquet_safe(
    path: Path,
    expected_min_rows: int = 1,
    expected_columns: tuple[str, ...] = (),
) -> pd.DataFrame | None:
    """
    Load a cached parquet, validating row count and column presence.

    Returns None if file does not exist, is below expected_min_rows, or
    is missing any column in expected_columns. The caller decides whether
    to re-fetch on None.

    Per `feedback_cache_validation.md`: mid-write failures otherwise
    silently bias downstream results. Catch them at load time.
    """
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        print(f"  [cache invalid] {path.name}: read failed ({exc!r}); re-fetch")
        return None
    if len(df) < expected_min_rows:
        print(
            f"  [cache invalid] {path.name}: only {len(df)} rows "
            f"(expected >= {expected_min_rows}); re-fetch"
        )
        return None
    missing = [c for c in expected_columns if c not in df.columns]
    if missing:
        print(
            f"  [cache invalid] {path.name}: missing columns {missing}; re-fetch"
        )
        return None
    return df


def write_parquet_atomic(df: pd.DataFrame, path: Path) -> None:
    """Atomic parquet write: write to tmp then rename. Avoids partial caches."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, compression="zstd")
    tmp.replace(path)


__all__ = [
    "pro",
    "RateLimiter",
    "acquire_rate_token",
    "retry_on_network_error",
    "read_parquet_safe",
    "write_parquet_atomic",
]
