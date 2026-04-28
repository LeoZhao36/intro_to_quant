"""
Project 5 Session 2: point-in-time universe membership construction.

Extends Session 1's single-date pipeline to 52 monthly rebalance dates with
per-date caching, threaded baostock calls, and a trailing-20-day liquidity
filter.

This file currently contains Stage 1 (per-date candidate pull) and a smoke
test that reproduces Session 1's 2024-12-31 output for validation. Later
stages will be added after the smoke test passes.
"""

import sys
import time
import socket
import atexit
import logging
import threading
import concurrent.futures
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import baostock as bs
import pandas as pd

# Force line-buffered stdout so progress prints appear when redirected
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

# Socket-level timeout applies to all new sockets including baostock's.
# Without this, individual queries can hang forever and block the whole pool.
# 60s is generous enough for login + slow queries but still catches hangs.
socket.setdefaulttimeout(60.0)


# ==========================================================
# Configuration
# ==========================================================

DATA_DIR = Path("data")
CANDIDATES_DIR = DATA_DIR / "candidates"
AMOUNT_TS_DIR = DATA_DIR / "amount_timeseries"
REBALANCE_DATES_CSV = DATA_DIR / "rebalance_dates.csv"
UNION_CSV = DATA_DIR / "universe_candidates_union.csv"
AMOUNT_TRAILING20D_CSV = DATA_DIR / "amount_trailing20d.csv"
MEMBERSHIP_CSV = DATA_DIR / "universe_membership.csv"
ERROR_LOG = DATA_DIR / "errors_universe_construction.log"

DATA_DIR.mkdir(exist_ok=True)
CANDIDATES_DIR.mkdir(exist_ok=True)
AMOUNT_TS_DIR.mkdir(exist_ok=True)

SAMPLE_START = "2022-01-01"
SAMPLE_END = "2026-04-23"
AMOUNT_TS_START = "2021-12-01"
AMOUNT_TS_END = "2026-04-23"

LIQUIDITY_FLOOR_RMB = 30_000_000  # 3000万
TRAILING_WINDOW = 20
UNIVERSE_SIZE = 1000
N_WORKERS = 8

A_SHARE_PREFIXES = ('sh.60', 'sh.68', 'sz.00', 'sz.30')


# ==========================================================
# Error logging (thread-safe)
# ==========================================================

_log_lock = threading.Lock()
_logger = logging.getLogger("universe_construction")
_logger.setLevel(logging.WARNING)
_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
_logger.addHandler(_handler)


def _log_error(stage, date, code, err):
    with _log_lock:
        _logger.warning(
            f"stage={stage} | date={date or '-'} | code={code or '-'} | error={err}"
        )


# ==========================================================
# Per-thread persistent baostock sessions
# ==========================================================

_login_lock = threading.Lock()


def _thread_login():
    """ThreadPoolExecutor initializer. Each worker thread logs in exactly
    once at startup and holds the session for its lifetime.

    Logins are serialized with a lock to avoid overloading baostock's
    login endpoint when 8 workers spin up simultaneously (observed to
    cause 接口异常/网络接收错误). Includes retry with backoff."""
    with _login_lock:
        last_err = None
        for attempt in range(4):
            if attempt > 0:
                time.sleep(1.5 * attempt)
            lg = bs.login()
            if lg.error_code == "0":
                # small gap so the next thread's login doesn't pile on
                time.sleep(0.2)
                return
            last_err = lg.error_msg
        raise RuntimeError(f"Worker login failed after 4 attempts: {last_err}")


# ==========================================================
# Rebalance date generation
# ==========================================================

def build_rebalance_dates():
    """Generate the 52 monthly rebalance dates: the 15th of each month
    from Jan 2022 through Apr 2026, rolled forward to the next trading
    day if the 15th is a weekend/holiday. Caches to rebalance_dates.csv."""
    if REBALANCE_DATES_CSV.exists():
        return pd.read_csv(REBALANCE_DATES_CSV)["date"].tolist()

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"login failed: {lg.error_msg}")
    try:
        rs = bs.query_trade_dates(start_date="2022-01-01", end_date="2026-05-31")
        if rs.error_code != "0":
            raise RuntimeError(f"query_trade_dates failed: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        cal = pd.DataFrame(rows, columns=rs.fields)
    finally:
        bs.logout()

    trading_days = set(
        cal[cal["is_trading_day"] == "1"]["calendar_date"].tolist()
    )

    dates = []
    for year in range(2022, 2027):
        for month in range(1, 13):
            if year == 2026 and month > 4:
                break
            target = pd.Timestamp(year=year, month=month, day=15)
            for _ in range(10):  # up to 10 days forward
                if target.strftime("%Y-%m-%d") in trading_days:
                    break
                target += pd.Timedelta(days=1)
            d = target.strftime("%Y-%m-%d")
            if d in trading_days:
                dates.append(d)

    pd.DataFrame({"date": dates}).to_csv(REBALANCE_DATES_CSV, index=False)
    print(f"  saved {len(dates)} rebalance dates to {REBALANCE_DATES_CSV}")
    return dates


# ==========================================================
# Stage 1: per-date candidate pull
# ==========================================================

def get_all_listings(date):
    """Pull every listed code on `date` via bs.query_all_stock."""
    rs = bs.query_all_stock(day=date)
    if rs.error_code != "0":
        raise RuntimeError(f"query_all_stock failed for {date}: {rs.error_msg}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        raise RuntimeError(f"query_all_stock returned empty for {date}")
    return pd.DataFrame(rows, columns=rs.fields)


def filter_a_shares(listings_df):
    """Keep only A-share equities from Shanghai and Shenzhen main boards,
    科创板, and 创业板. Drops B-shares, ETFs, indexes, and 北交所."""
    mask = listings_df["code"].str.startswith(A_SHARE_PREFIXES)
    return listings_df[mask].copy()


def _fetch_single_stock_kdata(code, date):
    """Worker function. Runs on a thread whose initializer already called
    bs.login(). Returns a dict with one day's fields or None on failure."""
    fields = "code,close,volume,amount,turn,tradestatus,isST"
    try:
        rs = bs.query_history_k_data_plus(
            code, fields,
            start_date=date, end_date=date,
            frequency="d", adjustflag="2",
        )
        if rs.error_code != "0":
            _log_error("stage1", date, code, rs.error_msg)
            return None
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        return dict(zip(fields.split(","), rows[0]))
    except Exception as e:
        _log_error("stage1", date, code, str(e))
        return None


def _pull_candidates_for_date(date):
    """Stage 1 inner: pull one rebalance date's candidate set, apply
    filters, compute float_mcap, cache to CSV. Returns the DataFrame."""
    cache_path = CANDIDATES_DIR / f"candidates_{date}.csv"
    if cache_path.exists():
        print(f"[cache] {cache_path.name} exists — loading")
        return pd.read_csv(
            cache_path,
            dtype={"code": str, "tradestatus": str, "isST": str},
        )

    print(f"[pull] {date}")

    # query_all_stock needs a login too; do it on the main thread
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"Main-thread login failed: {lg.error_msg}")
    try:
        listings = get_all_listings(date)
    finally:
        bs.logout()

    a_shares = filter_a_shares(listings)
    codes = a_shares["code"].tolist()
    print(f"  {len(listings)} total listings, {len(codes)} A-share equities")

    print(f"  threaded kdata pull ({N_WORKERS} workers, 1 login per worker)...")
    t0 = time.time()
    results = []
    # 40-min per-date cap. Measured throughput ~3 stocks/sec so 5122 stocks
    # finish in ~28 min; timeout gives ~30% slack for slow dates.
    overall_timeout = 2400.0
    pool = ThreadPoolExecutor(max_workers=N_WORKERS, initializer=_thread_login)
    try:
        futures = [pool.submit(_fetch_single_stock_kdata, c, date) for c in codes]
        done = 0
        try:
            for fut in as_completed(futures, timeout=overall_timeout):
                try:
                    r = fut.result()
                except Exception as e:
                    _log_error("stage1", date, "?", f"future error: {e}")
                    r = None
                if r is not None:
                    results.append(r)
                done += 1
                if done % 200 == 0:
                    rate = done / (time.time() - t0)
                    print(f"    {done}/{len(codes)} done in "
                          f"{time.time() - t0:.0f}s ({rate:.1f} stocks/sec)")
        except concurrent.futures.TimeoutError:
            hung = sum(1 for f in futures if not f.done())
            print(f"  WARNING: pool timeout after {overall_timeout:.0f}s; "
                  f"{hung} queries still running, skipping them")
            _log_error("stage1", date, "?",
                       f"pool timeout; {hung} hung queries skipped")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    elapsed = time.time() - t0
    print(f"  pulled kdata for {len(results)}/{len(codes)} stocks in {elapsed:.1f}s")

    df = pd.DataFrame(results)

    # baostock returns strings — convert numerics immediately
    for col in ("close", "volume", "amount", "turn"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["tradestatus"] = df["tradestatus"].astype(str)
    df["isST"] = df["isST"].astype(str)

    # Filter chain (order matters for diagnostic numbers)
    n_start = len(df)
    df = df[df["tradestatus"] == "1"]
    n_after_suspend = len(df)
    df = df[df["isST"] == "0"]
    n_after_st = len(df)
    df = df[(df["volume"] > 0) & (df["turn"] > 0)]
    n_after_vol = len(df)
    print(
        f"  filters: {n_start} -> {n_after_suspend} (非停牌) "
        f"-> {n_after_st} (非ST) -> {n_after_vol} (vol & turn > 0)"
    )

    # Derive 流通市值
    df["float_shares"] = df["volume"] / (df["turn"] / 100)
    df["float_mcap"] = df["close"] * df["float_shares"]

    df = df[[
        "code", "close", "volume", "amount", "turn",
        "tradestatus", "isST", "float_shares", "float_mcap",
    ]].reset_index(drop=True)
    df.to_csv(cache_path, index=False)
    print(f"  saved {len(df)} candidates to {cache_path}")
    return df


# ==========================================================
# Verification step 1: single-date smoke test
# ==========================================================

def smoke_test_2024_12_31():
    """Reproduce Session 1's 2024-12-31 output and compare."""
    print("=" * 60)
    print("STAGE 1 SMOKE TEST — 2024-12-31")
    print("=" * 60)

    my_candidates = _pull_candidates_for_date("2024-12-31")

    session1_path = Path("data/kdata_2024-12-31.csv")
    if not session1_path.exists():
        print(f"\nWARNING: Session 1 cache not found at {session1_path}")
        return

    s1 = pd.read_csv(
        session1_path,
        dtype={"code": str, "tradestatus": str, "isST": str},
    )
    for col in ("close", "volume", "amount", "turn"):
        s1[col] = pd.to_numeric(s1[col], errors="coerce")

    # Apply the same filters so the comparison is apples-to-apples
    s1f = s1[s1["tradestatus"] == "1"]
    s1f = s1f[s1f["isST"] == "0"]
    s1f = s1f[(s1f["volume"] > 0) & (s1f["turn"] > 0)].copy()
    s1f["float_shares"] = s1f["volume"] / (s1f["turn"] / 100)
    s1f["float_mcap"] = s1f["close"] * s1f["float_shares"]

    print("\nRow-count comparison (after identical filter chain):")
    print(f"  Session 2 pipeline:               {len(my_candidates)}")
    print(f"  Session 1 kdata (same filters):   {len(s1f)}")
    diff = len(my_candidates) - len(s1f)
    print(f"  Difference:                       {diff:+d}")
    print(f"  Tolerance: ±5  =>  {'PASS' if abs(diff) <= 5 else 'FAIL'}")

    # float_mcap comparison on shared codes
    merged = my_candidates[["code", "float_mcap"]].merge(
        s1f[["code", "float_mcap"]],
        on="code",
        suffixes=("_s2", "_s1"),
    )
    merged["abs_pct_diff"] = (
        (merged["float_mcap_s2"] - merged["float_mcap_s1"]).abs()
        / merged["float_mcap_s1"] * 100
    )
    print(f"\nfloat_mcap comparison across {len(merged)} shared codes:")
    print(f"  Max  abs pct diff: {merged['abs_pct_diff'].max():.6f}%")
    print(f"  P99  abs pct diff: {merged['abs_pct_diff'].quantile(0.99):.6f}%")
    print(f"  Median abs pct diff: {merged['abs_pct_diff'].median():.6f}%")

    # Sample values in 亿 RMB for human inspection
    print("\nSample float_mcap (first 10 shared codes, in 亿 RMB):")
    sample = merged.head(10).copy()
    sample["s2_亿"] = (sample["float_mcap_s2"] / 1e8).round(4)
    sample["s1_亿"] = (sample["float_mcap_s1"] / 1e8).round(4)
    sample["diff_%"] = sample["abs_pct_diff"].round(6)
    print(sample[["code", "s2_亿", "s1_亿", "diff_%"]].to_string(index=False))


def quick_threading_sanity_check():
    """Pull kdata for just 40 A-shares to validate threading works at all.
    If this takes more than ~15s, threading isn't helping and we need a
    different concurrency model."""
    print("=" * 60)
    print("QUICK THREADING SANITY CHECK — 40 stocks, 8 threads")
    print("=" * 60)
    date = "2024-12-31"

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"Main login failed: {lg.error_msg}")
    try:
        listings = get_all_listings(date)
    finally:
        bs.logout()

    a_shares = filter_a_shares(listings)
    test_codes = a_shares["code"].head(40).tolist()
    print(f"Testing with {len(test_codes)} codes, first one: {test_codes[0]}")

    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=N_WORKERS, initializer=_thread_login) as pool:
        futures = [pool.submit(_fetch_single_stock_kdata, c, date) for c in test_codes]
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            results.append(r)
            print(f"  [{i:>2}/{len(test_codes)}] elapsed {time.time()-t0:.2f}s "
                  f"code={r.get('code') if r else 'FAIL'}")
    elapsed = time.time() - t0
    print(f"\nTotal: {elapsed:.2f}s for {len(test_codes)} stocks "
          f"({len(test_codes)/elapsed:.2f} stocks/sec)")
    print(f"Extrapolated to 5000 stocks: {5000/(len(test_codes)/elapsed)/60:.1f} min")


def run_full_stage1():
    """Loop over all 52 rebalance dates, pulling/caching candidates for each.
    Per-date caching means interruptions resume cleanly."""
    dates = build_rebalance_dates()
    print(f"Stage 1: {len(dates)} rebalance dates "
          f"(first={dates[0]}, last={dates[-1]})")

    t_start = time.time()
    cache_hits = 0
    total_fetched = 0

    for i, date in enumerate(dates, 1):
        t0 = time.time()
        cache_path = CANDIDATES_DIR / f"candidates_{date}.csv"
        was_cached = cache_path.exists()

        try:
            df = _pull_candidates_for_date(date)
        except Exception as e:
            _log_error("stage1", date, "?", f"date-level failure: {e}")
            print(f"[{i:>2}/{len(dates)}] {date}: FAILED ({e})")
            continue

        if was_cached:
            cache_hits += 1

        total_fetched += len(df)
        per_date = time.time() - t0
        total_min = (time.time() - t_start) / 60
        print(f"[{i:>2}/{len(dates)}] {date}: {len(df):>4} stocks, "
              f"wall={per_date:>5.0f}s, "
              f"total={total_min:>5.1f}min, "
              f"cache_hits={cache_hits}, "
              f"total_fetched={total_fetched}")

    total_elapsed = (time.time() - t_start) / 60
    print(f"\nStage 1 complete: {len(dates)} dates processed in "
          f"{total_elapsed:.1f} min "
          f"({cache_hits} cache hits, {len(dates)-cache_hits} fresh pulls)")


if __name__ == "__main__":
    import sys as _sys
    mode = _sys.argv[1] if len(_sys.argv) > 1 else "smoke"
    if mode == "quick":
        quick_threading_sanity_check()
    elif mode == "full":
        run_full_stage1()
    else:
        smoke_test_2024_12_31()
