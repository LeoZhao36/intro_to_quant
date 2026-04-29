"""
daily_panel_pull.py — Stage 0: unified daily panel pull from Tushare.

Pulls cross-sectional daily, daily_basic, and adj_factor for every trading
day in the panel range. Caches per-day as parquet. Every downstream stage
(universe construction, liquidity, factor computation, forward returns)
reads from this single source.

This is the only stage that hits Tushare. ~5,800 API calls upfront for a
clean single-source-of-truth daily panel that costs zero further calls
regardless of how many factor experiments are run on it.

Three endpoints merged per trading day:
  - daily        : OHLCV + pct_chg
  - daily_basic  : valuation snapshot (pe, pe_ttm, pb, ps, total/circ_mv, ...)
  - adj_factor   : corporate-action adjustment factor

Performance optimizations
-------------------------
  1. ThreadPoolExecutor with 6 workers in `full` mode. Sequential per-day
     latency is ~9s; concurrent execution compresses 2,018 days from
     ~5h to ~50 min. The smoke test stays sequential for clean verification.
  2. Thread-safe rate limiter (sliding 60-second window, capped at 400/min
     for safety under Tushare's documented 500/min limit on these endpoints).
  3. ZSTD parquet compression instead of Snappy. ~20% smaller files at
     near-identical read speed.
  4. float32 downcast on all numeric columns. ~40-50% size reduction on
     numeric storage with no precision loss for our use cases (sorting,
     ranking, ratio computation; float32 has ~7 significant digits).

Output
------
data/daily_panel/daily_<YYYY-MM-DD>.parquet   one file per trading day
data/trading_calendar.csv                     cached calendar over panel range
data/errors_daily_panel_pull.log              warnings (empty pulls, failures)

Usage
-----
    python daily_panel_pull.py smoke   # first 5 trading days, sequential
    python daily_panel_pull.py full    # all trading days, concurrent
    python daily_panel_pull.py status  # cache hit rate and missing dates
"""

import logging
import os
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

# tushare_setup.py lives one directory above Project_6/, alongside .env.
_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

from tushare_setup import pro

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass


# ==========================================================
# Configuration
# ==========================================================

DATA_DIR     = Path("data")
PANEL_DIR    = DATA_DIR / "daily_panel"
CALENDAR_PATH = DATA_DIR / "trading_calendar.csv"
ERROR_LOG    = DATA_DIR / "errors_daily_panel_pull.log"

DATA_DIR.mkdir(exist_ok=True)
PANEL_DIR.mkdir(exist_ok=True)

# Date range. Covers 60-day liquidity window + 12-month formation window
# before the first weekly rebalance (Wed 2019-01-09), with a small buffer.
PANEL_START = "20180101"
PANEL_END   = "20260429"

# Concurrency. With observed ~9s sequential per-day latency and 3 calls
# per day, 6 workers run at ~120 calls/min, well under the 500/min limit.
# Bump to 8 if Tushare server is responsive; drop to 3 if seeing 429 errors.
N_WORKERS = 6

# Rate limit: documented 500/min on basic tier; we cap at 400 for safety
# margin and to avoid bursts that some APIs penalize even under the limit.
MAX_CALLS_PER_MIN = 400

# Parquet compression: ZSTD over Snappy for ~20% smaller files at near-
# identical read speed. Default ZSTD level (3) is used.
COMPRESSION = "zstd"

SMOKE_DAYS = 5

# Schema. Used both as the pull spec (`fields=` arg) and as the validation
# set when reading cached parquet to detect stale schemas.
DAILY_FIELDS = (
    "ts_code,trade_date,open,high,low,close,"
    "pre_close,change,pct_chg,vol,amount"
)
DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
    "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
    "total_share,float_share,free_share,total_mv,circ_mv"
)
ADJ_FACTOR_FIELDS = "ts_code,trade_date,adj_factor"

# Final canonical column order on the merged per-day parquet. Every cached
# file is written with exactly these columns in this order, so reading the
# whole directory with pd.read_parquet returns a uniform schema.
COLUMN_ORDER = [
    "trade_date", "ts_code",
    "open", "high", "low", "close", "pre_close", "change", "pct_chg",
    "vol", "amount",
    "turnover_rate", "turnover_rate_f", "volume_ratio",
    "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm",
    "total_share", "float_share", "free_share", "total_mv", "circ_mv",
    "adj_factor",
]
EXPECTED_COLUMNS = frozenset(COLUMN_ORDER)

# All numeric columns get downcast to float32. ts_code and trade_date stay
# as strings. float32 has ~7 significant digits, well within the noise
# floor of any field we use downstream (price, market cap, ratio, return).
NUMERIC_COLS_FLOAT32 = [
    c for c in COLUMN_ORDER if c not in ("trade_date", "ts_code")
]


# ==========================================================
# Error logging (Python's logging module is thread-safe)
# ==========================================================

_logger = logging.getLogger("daily_panel_pull")
_logger.setLevel(logging.WARNING)
_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
_logger.addHandler(_handler)


def _log_warn(date, msg):
    _logger.warning(f"date={date} | {msg}")


# ==========================================================
# Thread-safe rate limiter (sliding-window counter)
# ==========================================================

class RateLimiter:
    """
    Sliding-window rate limiter. acquire() blocks until a call slot is
    available within the rolling 60-second budget.

    Thread-safe: lock protects the deque and counter; the sleep happens
    outside the lock so other threads can still acquire while one waits.
    Each thread that needs to call a Tushare endpoint must call acquire()
    before the call; one acquire = one expected call.
    """
    def __init__(self, max_per_minute):
        self.max = max_per_minute
        self.timestamps = deque()
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.time()
                # Drop timestamps older than 60s from the head of the deque.
                while self.timestamps and now - self.timestamps[0] >= 60:
                    self.timestamps.popleft()
                if len(self.timestamps) < self.max:
                    self.timestamps.append(now)
                    return
                # Compute time until the oldest in-window call ages out.
                wait = 60 - (now - self.timestamps[0]) + 0.05
            time.sleep(wait)


_rate_limiter = RateLimiter(MAX_CALLS_PER_MIN)


# Lock for non-interleaved progress prints from worker threads.
_print_lock = threading.Lock()


# ==========================================================
# Network resilience
# ==========================================================

def _retry_on_network_error(fn, label="", max_attempts=4):
    """
    Exponential backoff: 2s, 4s, 8s. Reuses Project 5's helper pattern.
    Calls _rate_limiter.acquire() before each attempt, so a successful
    call consumes one slot and a retried call consumes one per attempt.
    """
    delays = [2, 4, 8]
    for attempt in range(max_attempts):
        try:
            _rate_limiter.acquire()
            return fn()
        except Exception as exc:
            if attempt == max_attempts - 1:
                raise
            wait = delays[min(attempt, len(delays) - 1)]
            with _print_lock:
                print(f"    [retry {attempt+1}/{max_attempts}] {label}: "
                      f"{type(exc).__name__}: {exc} (waiting {wait}s)")
            time.sleep(wait)


# ==========================================================
# Trading calendar
# ==========================================================

def _yyyymmdd(s):
    return s.replace("-", "")


def get_trading_calendar(force_refresh=False):
    """
    Return sorted list of YYYY-MM-DD trading dates over panel range.
    Auto-refreshes if the cache doesn't cover the requested range, so
    extending PANEL_START/PANEL_END later just works.
    """
    panel_start_fmt = f"{PANEL_START[:4]}-{PANEL_START[4:6]}-{PANEL_START[6:]}"
    panel_end_fmt   = f"{PANEL_END[:4]}-{PANEL_END[4:6]}-{PANEL_END[6:]}"

    if CALENDAR_PATH.exists() and not force_refresh:
        cached = pd.read_csv(CALENDAR_PATH)["date"].tolist()
        if cached and cached[0] <= panel_start_fmt and cached[-1] >= panel_end_fmt:
            return [d for d in cached
                    if panel_start_fmt <= d <= panel_end_fmt]
        print(f"  cached calendar [{cached[0]}, {cached[-1]}] does not cover "
              f"requested [{panel_start_fmt}, {panel_end_fmt}]; refreshing")

    print(f"Pulling trading calendar from Tushare...")
    cal = _retry_on_network_error(
        lambda: pro.trade_cal(
            exchange="SSE",
            start_date=PANEL_START,
            end_date=PANEL_END,
            is_open="1",
        ),
        label="trade_cal"
    )
    dates = sorted(
        f"{s[:4]}-{s[4:6]}-{s[6:]}" for s in cal["cal_date"].tolist()
    )
    pd.DataFrame({"date": dates}).to_csv(CALENDAR_PATH, index=False)
    print(f"  cached {len(dates)} trading days from {dates[0]} to "
          f"{dates[-1]} -> {CALENDAR_PATH}")
    return dates


# ==========================================================
# Per-day pull
# ==========================================================

def _downcast_numeric_to_float32(df):
    """
    Downcast all numeric columns in NUMERIC_COLS_FLOAT32 to float32.
    NaN-safe: pd.to_numeric with errors='coerce' converts non-numeric to
    NaN; float32 supports NaN natively. ~50% size reduction on numerics.
    """
    for col in NUMERIC_COLS_FLOAT32:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
    return df


def _pull_daily_panel_for_date(date, sanity_callback=None):
    """
    Pull and merge daily + daily_basic + adj_factor for one trading day.
    Returns the merged DataFrame with COLUMN_ORDER columns + float32 numerics.

    Each pro.* call is rate-limited via _retry_on_network_error -> _rate_limiter.
    Thread-safe: doesn't share state with other concurrent calls beyond
    the rate limiter and (optionally) the sanity_callback.
    """
    yyyymmdd = _yyyymmdd(date)

    daily = _retry_on_network_error(
        lambda: pro.daily(trade_date=yyyymmdd, fields=DAILY_FIELDS),
        label=f"daily {date}"
    )
    basic = _retry_on_network_error(
        lambda: pro.daily_basic(trade_date=yyyymmdd, fields=DAILY_BASIC_FIELDS),
        label=f"daily_basic {date}"
    )
    adj = _retry_on_network_error(
        lambda: pro.adj_factor(trade_date=yyyymmdd, fields=ADJ_FACTOR_FIELDS),
        label=f"adj_factor {date}"
    )

    if len(daily) == 0 or len(basic) == 0 or len(adj) == 0:
        _log_warn(date, f"empty result: daily={len(daily)}, "
                        f"basic={len(basic)}, adj={len(adj)}")
        with _print_lock:
            print(f"  [WARN] {date}: empty result from one or more endpoints; "
                  f"writing empty panel with canonical schema")
        empty = pd.DataFrame({c: pd.Series(dtype="float64") for c in COLUMN_ORDER})
        return _downcast_numeric_to_float32(empty)

    # Merge: daily.close is canonical (it matches the official close used
    # for return computation). Drop basic.close to avoid suffixed columns.
    basic = basic.drop(columns=["close"], errors="ignore")
    merged = daily.merge(basic, on=["ts_code", "trade_date"], how="left")
    merged = merged.merge(adj, on=["ts_code", "trade_date"], how="left")

    # Surface unexpected schema additions from Tushare (new fields appear
    # over time; we drop them but want visibility when it happens).
    extras = set(merged.columns) - EXPECTED_COLUMNS
    if extras:
        with _print_lock:
            print(f"  [INFO] {date}: extra columns from Tushare ignored: "
                  f"{sorted(extras)}")

    # Force exact column set so every per-day parquet has identical schema.
    # Missing-from-Tushare columns become NaN; extras are dropped.
    for col in COLUMN_ORDER:
        if col not in merged.columns:
            merged[col] = pd.NA
    merged = merged[COLUMN_ORDER]

    # Downcast numeric columns to float32 before write. Halves the on-disk
    # numeric storage, with no precision concerns for our downstream usage.
    merged = _downcast_numeric_to_float32(merged)

    if sanity_callback is not None:
        sanity_callback(merged, date)

    return merged


def _print_sanity_checks(df, date):
    """
    Surface unit and magnitude issues immediately on the first pull.
    Called via a one-shot callback so it runs at most once per session.
    """
    print(f"\n  [sanity check] {date} ({len(df):,} rows after merge):")
    print(f"    schema:  {len(df.columns)} columns, all in expected set")
    print(f"    dtypes:  ts_code/trade_date as object, all numerics as float32")
    print(f"    amount unit (Tushare returns 千元):")
    print(f"      median:  {df['amount'].median():>14,.1f}  "
          f"(typical 1k-100k for active stocks)")
    print(f"      P95:     {df['amount'].quantile(0.95):>14,.1f}")
    print(f"    circ_mv unit (Tushare returns 万元):")
    print(f"      median:  {df['circ_mv'].median():>14,.1f}")
    print(f"      P95:     {df['circ_mv'].quantile(0.95):>14,.1f}")
    print(f"    pe_ttm:")
    pe = df['pe_ttm'].dropna()
    print(f"      n_valid: {len(pe):>14,}  ({100*len(pe)/len(df):.1f}% of rows)")
    print(f"      median:  {pe.median():>14,.2f}")
    print(f"    adj_factor:")
    adj = df['adj_factor'].dropna()
    print(f"      n_valid: {len(adj):>14,}  ({100*len(adj)/len(df):.1f}% of rows)")
    print(f"      median:  {adj.median():>14,.4f}  "
          f"(>=1; rises after splits/dividends)")
    nulls = df.isnull().sum()
    high_null = nulls[nulls > len(df) * 0.10]
    if len(high_null) > 0:
        print(f"    columns with >10% nulls (review before factor work):")
        for col, n in high_null.items():
            print(f"      {col:<20} {n:>5,} ({100*n/len(df):>5.2f}%)")
    print()


# ==========================================================
# Cache management
# ==========================================================

def _cache_path(date):
    return PANEL_DIR / f"daily_{date}.parquet"


def _is_cached_with_valid_schema(date):
    """
    True iff the cache exists AND has the expected columns AND dtypes.
    Checking dtypes (not just column names) is what catches files written
    by an older version of this script (float64) versus the current one
    (float32). Without this, stale files would silently pass validation.
    """
    path = _cache_path(date)
    if not path.exists():
        return False
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        schema = pq.read_schema(path)
        cached_cols = set(schema.names)
        missing = EXPECTED_COLUMNS - cached_cols
        if missing:
            with _print_lock:
                print(f"  [stale] {path.name} missing {sorted(missing)}; "
                      f"will re-pull")
            return False
        # Every numeric column must be float32. Files from older versions
        # used float64 and need re-pulling for the size win to materialize.
        wrong_dtype = []
        for col in NUMERIC_COLS_FLOAT32:
            field = schema.field(col)
            if field.type != pa.float32():
                wrong_dtype.append(f"{col}={field.type}")
        if wrong_dtype:
            with _print_lock:
                print(f"  [stale] {path.name} dtype mismatch "
                      f"({len(wrong_dtype)} columns not float32); will re-pull")
            return False
        return True
    except Exception as exc:
        with _print_lock:
            print(f"  [corrupt] {path.name}: {exc}; will re-pull")
        return False


# ==========================================================
# Sanity check coordination (printed once across all threads)
# ==========================================================

class SanityCheckOnce:
    """
    Ensures _print_sanity_checks runs at most once across all threads.
    Workers call .maybe_print(df, date); only the first one to acquire
    the lock prints. Subsequent calls return immediately.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.done = False

    def maybe_print(self, df, date):
        with self.lock:
            if self.done:
                return
            _print_sanity_checks(df, date)
            self.done = True


# ==========================================================
# Per-day work unit (used by both sequential and threaded drivers)
# ==========================================================

def _ensure_pulled(date, sanity):
    """
    Pull and cache one date if not already cached. Returns 'cached' if
    the cache was used, 'pulled' if a fresh pull happened. Thread-safe;
    each thread writes its own file.
    """
    if _is_cached_with_valid_schema(date):
        return "cached"

    path = _cache_path(date)
    if path.exists():
        path.unlink()

    df = _pull_daily_panel_for_date(date, sanity_callback=sanity.maybe_print)
    df.to_parquet(path, compression=COMPRESSION, index=False)
    return "pulled"


# ==========================================================
# Drivers
# ==========================================================

def smoke_test():
    """
    Pull first 5 uncached trading days SEQUENTIALLY for clean verification
    output. The full pull uses threading; smoke stays sequential so you can
    inspect each pull's timing and sanity check independently.
    """
    print("=" * 60)
    print(f"SMOKE TEST: pulling up to {SMOKE_DAYS} trading days "
          f"(sequential)")
    print("=" * 60)

    calendar = get_trading_calendar()
    test_dates = calendar[:SMOKE_DAYS]
    sanity = SanityCheckOnce()
    t0 = time.time()

    for i, date in enumerate(test_dates, 1):
        result = _ensure_pulled(date, sanity)
        elapsed = time.time() - t0
        print(f"[{i}/{SMOKE_DAYS}] {date}: {result} (elapsed {elapsed:.1f}s)")

    print(f"\nSmoke test done. Sequential per-day timing should be ~5-10s.")
    print(f"Full pull with {N_WORKERS} workers will compress this to "
          f"~{9/N_WORKERS:.1f}s/day average.")
    print(f"\nIf sanity checks look right, run with `full`.")


def full_pull():
    """
    Concurrent pull across N_WORKERS threads. Resumable on interrupt:
    each completed date writes its own parquet, and re-running picks up
    only the missing dates.
    """
    calendar = get_trading_calendar()
    print(f"FULL PULL: {len(calendar)} trading days "
          f"({calendar[0]} to {calendar[-1]})")

    cached_dates = [d for d in calendar if _is_cached_with_valid_schema(d)]
    pending_dates = [d for d in calendar if not _is_cached_with_valid_schema(d)]

    print(f"  already cached:  {len(cached_dates):>5}")
    print(f"  remaining:       {len(pending_dates):>5}")
    if not pending_dates:
        print(f"  Nothing to do. To re-pull, delete files in {PANEL_DIR}/")
        return

    # Estimate: at ~9s/day sequential, divided by N_WORKERS, plus ~10% overhead.
    est_min = (len(pending_dates) * 9 / N_WORKERS * 1.1) / 60
    print(f"  workers:         {N_WORKERS}")
    print(f"  rate cap:        {MAX_CALLS_PER_MIN}/min total "
          f"({MAX_CALLS_PER_MIN/3:.0f} dates/min ceiling)")
    print(f"  estimated wall time: ~{est_min:.0f} min "
          f"(~{len(pending_dates) * 3:,} API calls)")
    print()

    sanity = SanityCheckOnce()
    t0 = time.time()
    n_pulled = 0
    n_failed = 0

    with ThreadPoolExecutor(max_workers=N_WORKERS) as executor:
        future_to_date = {
            executor.submit(_ensure_pulled, d, sanity): d
            for d in pending_dates
        }

        for i, future in enumerate(as_completed(future_to_date), 1):
            date = future_to_date[future]
            try:
                result = future.result()
                if result == "pulled":
                    n_pulled += 1
            except Exception as exc:
                n_failed += 1
                _log_warn(date, f"thread failure: {exc}")
                with _print_lock:
                    print(f"  [FAIL] {date}: {type(exc).__name__}: {exc}")

            if i % 50 == 0 or i == len(pending_dates):
                mins = (time.time() - t0) / 60
                rate = i / max(mins, 0.001)
                with _print_lock:
                    print(f"[{i:>4}/{len(pending_dates)}] "
                          f"pulled={n_pulled}, failed={n_failed}, "
                          f"elapsed={mins:.1f} min, "
                          f"rate={rate:.1f} dates/min")

    mins = (time.time() - t0) / 60
    print(f"\nFull pull complete: {n_pulled} fresh pulls, "
          f"{n_failed} failures in {mins:.1f} min")
    if n_failed > 0:
        print(f"  Failures logged to {ERROR_LOG}. Re-run to retry.")


def status():
    """Cache hit rate and missing dates. No API calls."""
    calendar = get_trading_calendar()
    cached = [d for d in calendar if _is_cached_with_valid_schema(d)]
    missing = [d for d in calendar if not _is_cached_with_valid_schema(d)]

    print(f"Panel range: {calendar[0]} to {calendar[-1]}")
    print(f"Trading days in calendar:  {len(calendar):>5}")
    print(f"Cached with valid schema:  {len(cached):>5} "
          f"({100*len(cached)/len(calendar):.1f}%)")
    print(f"Missing or stale:          {len(missing):>5}")
    if missing:
        print(f"\nFirst 20 missing dates:")
        for d in missing[:20]:
            print(f"  {d}")
        if len(missing) > 20:
            print(f"  ... and {len(missing) - 20} more")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke_test()
    elif mode == "full":
        full_pull()
    elif mode == "status":
        status()
    else:
        print(f"Usage: python daily_panel_pull.py [smoke|full|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()