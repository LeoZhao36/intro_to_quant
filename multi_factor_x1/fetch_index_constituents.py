"""
fetch_index_constituents.py — Pull CSI300/500/1000/2000 constituents.

Uses pro.index_weight, which returns monthly index composition snapshots.
We pull one snapshot per (index, year-month) over the panel range, cache
each as parquet under data/index_constituents/, and never re-pull what
exists on disk.

Output schema per parquet:
    ts_code        # the constituent stock
    trade_date     # the month-end snapshot date Tushare returns
    weight         # weight in the index, percent
    index_code     # the index ts_code

Why monthly is the right resolution
-----------------------------------
CSI rebalances semi-annually with monthly weight updates. Daily index
membership is approximately the membership-as-of the most recent month-
end snapshot. For our purpose (weekly Wednesday rebalances), looking up
the most recent monthly snapshot before each rebalance date is accurate
to within a few days, well below the noise floor of weekly factor work.

API budget
----------
Per index:
  - CSI300/500/1000: ~88 monthly snapshots from 2019-01 to 2026-04
  - CSI2000: ~21 monthly snapshots from 2023-08 to 2026-04
Total: ~285 calls. At Tushare basic-tier rate (200/min) this completes
in roughly 90 seconds. Each call is rate-limited and retried on transient
failures.

CSI2000 ts_code handling
------------------------
Tushare uses "932000.CSI" or "932000.SH" depending on the data feed
version. We try CSI first, fall back to SH, log which one worked, and
proceed. If both fail, we surface the error and skip that snapshot
rather than silently producing empty parquet.

Usage
-----
    python fetch_index_constituents.py smoke   # 2 months, 4 indices
    python fetch_index_constituents.py full    # all months
    python fetch_index_constituents.py status  # show cache hit rate
"""

import logging
import os
import sys
import time
from collections import deque
from pathlib import Path
import threading

import pandas as pd

# tushare_setup.py lives at the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tushare_setup import pro

from config import (
    CSI2000_INCEPTION,
    INDEX_CONSTITUENTS_DIR,
    INDEX_TS_CODES,
    PANEL_END,
    PANEL_START,
)


# ─── Configuration ─────────────────────────────────────────────────────

ERROR_LOG = INDEX_CONSTITUENTS_DIR / "errors_fetch_index.log"
COMPRESSION = "zstd"
MAX_CALLS_PER_MIN = 180  # under the 200/min basic-tier limit


# ─── Error logging ─────────────────────────────────────────────────────

_logger = logging.getLogger("fetch_index_constituents")
_logger.setLevel(logging.WARNING)
_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
_logger.addHandler(_handler)


def _log_warn(msg: str) -> None:
    _logger.warning(msg)


# ─── Rate limiter (sliding window) ─────────────────────────────────────

class RateLimiter:
    """Sliding 60-second window. acquire() blocks if budget is exhausted."""
    def __init__(self, max_per_minute: int) -> None:
        self.max = max_per_minute
        self.timestamps: deque = deque()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.time()
                while self.timestamps and now - self.timestamps[0] >= 60:
                    self.timestamps.popleft()
                if len(self.timestamps) < self.max:
                    self.timestamps.append(now)
                    return
                wait = 60 - (now - self.timestamps[0]) + 0.05
            time.sleep(wait)


_rate_limiter = RateLimiter(MAX_CALLS_PER_MIN)


def _retry_call(fn, label: str = "", max_attempts: int = 4):
    """Exponential backoff on transient errors. Calls _rate_limiter once per attempt."""
    delays = [2, 4, 8]
    for attempt in range(max_attempts):
        try:
            _rate_limiter.acquire()
            return fn()
        except Exception as exc:
            if attempt == max_attempts - 1:
                raise
            wait = delays[min(attempt, len(delays) - 1)]
            print(f"    [retry {attempt+1}/{max_attempts}] {label}: "
                  f"{type(exc).__name__}: {exc} (wait {wait}s)")
            time.sleep(wait)


# ─── Calendar of monthly snapshot dates ────────────────────────────────

def monthly_snapshot_dates(start: pd.Timestamp, end: pd.Timestamp) -> list:
    """
    Return list of pd.Timestamp month-ends covering [start, end].
    pro.index_weight expects YYYYMMDD; we'll format at call time.
    """
    return list(pd.date_range(start=start.normalize(), end=end.normalize(),
                              freq="ME"))


# ─── Cache management ──────────────────────────────────────────────────

def _cache_path(index_key: str, snapshot_date: pd.Timestamp) -> Path:
    """One parquet per (index, year-month)."""
    return INDEX_CONSTITUENTS_DIR / f"{index_key}_{snapshot_date.strftime('%Y-%m')}.parquet"


def _is_cached(index_key: str, snapshot_date: pd.Timestamp) -> bool:
    path = _cache_path(index_key, snapshot_date)
    if not path.exists():
        return False
    try:
        # Validate by opening the schema; corrupt files trigger re-pull.
        import pyarrow.parquet as pq
        pq.read_schema(path)
        return True
    except Exception as exc:
        print(f"  [corrupt] {path.name}: {exc}; will re-pull")
        return False


# ─── Per-snapshot pull ─────────────────────────────────────────────────

def _pull_one_snapshot(index_key: str, snapshot_date: pd.Timestamp,
                       verbose: bool = False) -> pd.DataFrame | None:
    """
    Call pro.index_weight for one (index, month). Returns the DataFrame
    with the 4-column schema or None if the API returned empty.

    For CSI2000 we try 932000.CSI first, fall back to 932000.SH if the
    first attempt returns empty. We log which suffix worked.
    """
    ts_code = INDEX_TS_CODES[index_key]
    # Build the start/end window covering the entire month.
    period_start = snapshot_date.replace(day=1)
    period_end = snapshot_date  # already month-end
    start_str = period_start.strftime("%Y%m%d")
    end_str = period_end.strftime("%Y%m%d")

    def _call(code: str) -> pd.DataFrame:
        return pro.index_weight(
            index_code=code, start_date=start_str, end_date=end_str
        )

    df = _retry_call(lambda: _call(ts_code),
                     label=f"{index_key} {snapshot_date.strftime('%Y-%m')}")

    # CSI2000 fallback
    if (df is None or len(df) == 0) and index_key == "csi2000":
        fallback_code = "932000.SH"
        if verbose:
            print(f"    [fallback] CSI2000 {ts_code} returned empty, trying {fallback_code}")
        df = _retry_call(lambda: _call(fallback_code),
                         label=f"{index_key} {snapshot_date.strftime('%Y-%m')} fallback")
        if df is not None and len(df) > 0:
            ts_code = fallback_code  # log which one worked

    if df is None or len(df) == 0:
        return None

    # Tushare returns columns: index_code, con_code, trade_date, weight
    df = df.rename(columns={"con_code": "ts_code"})
    df["ts_code"] = df["ts_code"].astype(str)
    df["trade_date"] = df["trade_date"].astype(str)
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").astype("float32")
    return df[["ts_code", "trade_date", "weight", "index_code"]]


def _ensure_pulled(index_key: str, snapshot_date: pd.Timestamp,
                   verbose: bool = False) -> str:
    """
    Pull and cache one snapshot if not already cached. Returns
    'cached' / 'pulled' / 'empty' / 'failed'.
    """
    if _is_cached(index_key, snapshot_date):
        return "cached"

    # CSI2000 has no data before inception; skip cleanly.
    if index_key == "csi2000" and snapshot_date < CSI2000_INCEPTION:
        return "empty"

    try:
        df = _pull_one_snapshot(index_key, snapshot_date, verbose=verbose)
    except Exception as exc:
        _log_warn(f"{index_key} {snapshot_date.strftime('%Y-%m')}: {exc}")
        if verbose:
            print(f"    [FAIL] {index_key} {snapshot_date.strftime('%Y-%m')}: {exc}")
        return "failed"

    if df is None:
        # Empty but expected for CSI2000 pre-inception or genuinely missing.
        _log_warn(f"{index_key} {snapshot_date.strftime('%Y-%m')}: empty result")
        return "empty"

    df.to_parquet(_cache_path(index_key, snapshot_date),
                  compression=COMPRESSION, index=False)
    return "pulled"


# ─── Drivers ────────────────────────────────────────────────────────────

def smoke_test() -> None:
    """Pull 2 months for all 4 indices; ~8 API calls."""
    print("=" * 60)
    print("SMOKE TEST: 2 months, 4 indices")
    print("=" * 60)

    test_dates = [
        pd.Timestamp("2024-04-30"),  # NNA month
        pd.Timestamp("2024-09-30"),  # PBoC stimulus month
    ]

    for index_key in INDEX_TS_CODES:
        for d in test_dates:
            t0 = time.time()
            result = _ensure_pulled(index_key, d, verbose=True)
            elapsed = time.time() - t0
            if result in ("cached", "pulled"):
                df = pd.read_parquet(_cache_path(index_key, d))
                print(f"  {index_key:<8s} {d.strftime('%Y-%m')}: "
                      f"{result:<6s} {len(df):>5d} stocks, "
                      f"weight sum={df['weight'].sum():.1f}%, "
                      f"elapsed={elapsed:.1f}s")
            else:
                print(f"  {index_key:<8s} {d.strftime('%Y-%m')}: {result}")

    print("\nIf the constituent counts and weight sums look reasonable")
    print("(CSI300 ~300 stocks weight ~100%, CSI1000 ~1000 stocks, etc.)")
    print("then run with `full`.")


def full_pull() -> None:
    """Pull all months for all 4 indices over the panel range."""
    snapshot_dates = monthly_snapshot_dates(PANEL_START, PANEL_END)
    print(f"FULL PULL: {len(snapshot_dates)} monthly snapshots × 4 indices")
    print(f"  range: {snapshot_dates[0].strftime('%Y-%m')} to "
          f"{snapshot_dates[-1].strftime('%Y-%m')}")

    n_pulled = 0
    n_cached = 0
    n_empty = 0
    n_failed = 0
    t0 = time.time()
    total = len(snapshot_dates) * len(INDEX_TS_CODES)
    i = 0

    for index_key in INDEX_TS_CODES:
        for d in snapshot_dates:
            i += 1
            result = _ensure_pulled(index_key, d, verbose=False)
            if result == "pulled":
                n_pulled += 1
            elif result == "cached":
                n_cached += 1
            elif result == "empty":
                n_empty += 1
            else:
                n_failed += 1

            if i % 50 == 0 or i == total:
                mins = (time.time() - t0) / 60
                rate = i / max(mins, 0.001)
                print(f"  [{i:>4}/{total}] pulled={n_pulled} "
                      f"cached={n_cached} empty={n_empty} failed={n_failed} "
                      f"elapsed={mins:.1f}min rate={rate:.0f}/min")

    print(f"\nFull pull complete in {(time.time()-t0)/60:.1f} min")
    print(f"  pulled: {n_pulled}")
    print(f"  cached: {n_cached}")
    print(f"  empty:  {n_empty}  (CSI2000 pre-inception or genuinely missing)")
    print(f"  failed: {n_failed}  (see {ERROR_LOG} if non-zero)")


def status() -> None:
    """Show cache state per index."""
    snapshot_dates = monthly_snapshot_dates(PANEL_START, PANEL_END)
    print(f"Cache status under {INDEX_CONSTITUENTS_DIR}/")
    print(f"  expected window: {snapshot_dates[0].strftime('%Y-%m')} to "
          f"{snapshot_dates[-1].strftime('%Y-%m')}")
    print()

    for index_key in INDEX_TS_CODES:
        cached_dates = [
            d for d in snapshot_dates if _is_cached(index_key, d)
        ]
        # CSI2000 expected count differs.
        if index_key == "csi2000":
            expected = [d for d in snapshot_dates if d >= CSI2000_INCEPTION]
        else:
            expected = snapshot_dates

        print(f"  {index_key:<8s}: {len(cached_dates):>3} of {len(expected):>3} "
              f"snapshots cached ({100*len(cached_dates)/max(len(expected),1):.1f}%)")
        if cached_dates:
            sample = pd.read_parquet(
                _cache_path(index_key, cached_dates[-1])
            )
            print(f"           latest: {cached_dates[-1].strftime('%Y-%m')} "
                  f"({len(sample)} stocks, weight sum {sample['weight'].sum():.1f}%)")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke_test()
    elif mode == "full":
        full_pull()
    elif mode == "status":
        status()
    else:
        print("Usage: python fetch_index_constituents.py [smoke|full|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
