"""
rdi_fetch.py — Tushare fetchers for the four RDI components.

Endpoints fetched (in order of dependency complexity):
  1. pro.stk_holdernumber → data/raw/holdernumber.parquet (single file)
  2. pro.fund_portfolio   → data/raw/fund_portfolio_<period>.parquet
                          → aggregated to data/fund_holding_aggregate.parquet
  3. pro.hk_hold           → data/raw/hk_hold/hk_hold_<date>.parquet (per day)
  4. pro.moneyflow         → data/raw/moneyflow/moneyflow_<date>.parquet (per day)

CLI:
  python rdi_fetch.py --dry-run         # one period / one date sample each
  python rdi_fetch.py                   # full pull, resumable
  python rdi_fetch.py holdernumber      # one endpoint at a time
  python rdi_fetch.py fund_portfolio
  python rdi_fetch.py hk_hold
  python rdi_fetch.py moneyflow

All paths are relative; CWD must be universe_exploration/.
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

import config
from tushare_helpers import (
    pro,
    RateLimiter,
    acquire_rate_token,
    retry_on_network_error,
    read_parquet_safe,
    write_parquet_atomic,
)


# Fetch start: panel begins 2019-01-09. Provide a 60-day buffer for any
# trailing-window operation (e.g. moneyflow 20-day smoothing).
FETCH_START = pd.Timestamp("2018-10-01")
FETCH_END = config.PANEL_END

WORKERS = 6
# fund_portfolio is published-rate-limited at 60/min on this account.
# Use a dedicated limiter and a single worker to avoid Tushare 429s.
FUND_PORTFOLIO_LIMITER = RateLimiter(max_calls=50, window=60.0)
FUND_PORTFOLIO_WORKERS = 1


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _trade_days_in_range(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    cal = pd.read_csv(config.TRADING_CALENDAR_PATH)
    dates = pd.to_datetime(cal["date"])
    mask = (dates >= start) & (dates <= end)
    return [d.strftime("%Y%m%d") for d in dates[mask]]


def _quarter_ends_in_range(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    """Quarter-end dates as YYYYMMDD strings."""
    qends = pd.date_range(start, end, freq="QE")
    return [d.strftime("%Y%m%d") for d in qends]


# ═══════════════════════════════════════════════════════════════════════
# 1. stk_holdernumber
# ═══════════════════════════════════════════════════════════════════════

@retry_on_network_error(max_attempts=4, label="holdernumber")
def _fetch_holdernumber_one_period(period: str) -> pd.DataFrame:
    acquire_rate_token()
    # Tushare API: pro.stk_holdernumber(start_date=, end_date=) returns
    # the cross-section across all ts_codes whose ann_date falls in window.
    # We use end_date as the period anchor and fetch a one-period window.
    df = pro.stk_holdernumber(
        start_date=period, end_date=period
    )
    if df is None:
        return pd.DataFrame()
    return df


def fetch_holdernumber(dry_run: bool = False) -> None:
    """
    Fetch stk_holdernumber by period (quarter end_date). Single output
    parquet at data/raw/holdernumber.parquet.

    Note: Tushare's stk_holdernumber may not return rows for every
    period anchor (announcement timing varies). We iterate quarterly
    windows but ALSO iterate by ann_date in 1-month windows as backup
    for robustness — most disclosures cluster around 1-2 months after
    quarter end.
    """
    print("\n=== fetch_holdernumber ===")
    out = config.HOLDERNUMBER_PATH

    if not dry_run:
        existing = read_parquet_safe(
            out,
            expected_min_rows=1000,
            expected_columns=("ts_code", "ann_date", "end_date", "holder_num"),
        )
        if existing is not None:
            print(f"  cached: {len(existing):,} rows; "
                  f"min_ann={existing['ann_date'].min()}, "
                  f"max_ann={existing['ann_date'].max()}")
            return

    # Iterate by ann_date in monthly windows from FETCH_START to FETCH_END.
    # This is more robust than period-anchored iteration because disclosures
    # arrive on rolling dates.
    start = FETCH_START
    end = FETCH_END

    months: list[tuple[str, str]] = []
    cursor = pd.Timestamp(start.year, start.month, 1)
    while cursor <= end:
        next_month = (cursor + pd.offsets.MonthEnd(1))
        a = cursor.strftime("%Y%m%d")
        b = min(next_month, end).strftime("%Y%m%d")
        months.append((a, b))
        cursor = cursor + pd.offsets.MonthBegin(1)

    if dry_run:
        months = months[-1:]
        print(f"  [dry-run] fetching just {months[0]}")

    print(f"  iterating {len(months)} monthly windows of ann_date...")

    @retry_on_network_error(max_attempts=4, label="holdernumber-month")
    def _fetch_month(start: str, end: str) -> pd.DataFrame:
        acquire_rate_token()
        df = pro.stk_holdernumber(start_date=start, end_date=end)
        return df if df is not None else pd.DataFrame()

    frames: list[pd.DataFrame] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(_fetch_month, a, b): (a, b) for a, b in months}
        done = 0
        for fut in as_completed(futures):
            a, b = futures[fut]
            try:
                df = fut.result()
            except Exception as exc:
                print(f"  [{a}~{b}] FAIL: {exc!r}")
                continue
            done += 1
            if df is not None and len(df) > 0:
                frames.append(df)
            if done % 20 == 0:
                print(f"  [{done}/{len(months)}] elapsed={time.time()-t0:.1f}s")

    if not frames:
        print("  WARN: no rows fetched")
        return

    merged = pd.concat(frames, ignore_index=True)
    # Dedupe: same ts_code, end_date may appear in multiple monthly windows.
    merged = merged.drop_duplicates(subset=["ts_code", "end_date", "ann_date"])
    merged = merged.sort_values(["ts_code", "end_date", "ann_date"]).reset_index(drop=True)
    print(f"  fetched: {len(merged):,} rows, "
          f"unique tickers={merged['ts_code'].nunique()}, "
          f"unique end_date={merged['end_date'].nunique()}, "
          f"ann range {merged['ann_date'].min()}..{merged['ann_date'].max()}")

    if dry_run:
        print(f"  [dry-run] columns: {list(merged.columns)}")
        print(merged.head())
        return

    write_parquet_atomic(merged, out)
    print(f"  wrote {out}")


# ═══════════════════════════════════════════════════════════════════════
# 2. fund_portfolio
# ═══════════════════════════════════════════════════════════════════════

@retry_on_network_error(max_attempts=4, label="fund_portfolio")
def _fetch_fund_portfolio_one_period(period: str, offset: int = 0) -> pd.DataFrame:
    # Use the dedicated 50/min limiter for fund_portfolio (Tushare caps it
    # at 60/min server-side).
    FUND_PORTFOLIO_LIMITER.acquire()
    df = pro.fund_portfolio(period=period, offset=offset, limit=5000)
    return df if df is not None else pd.DataFrame()


def _fetch_fund_portfolio_period_full(period: str) -> pd.DataFrame:
    """Paginate by offset until rows < 5000."""
    frames: list[pd.DataFrame] = []
    offset = 0
    page = 0
    while True:
        df = _fetch_fund_portfolio_one_period(period, offset=offset)
        page += 1
        if df is None or len(df) == 0:
            break
        frames.append(df)
        if len(df) < 5000:
            break
        offset += 5000
        if page > 50:  # 50 pages × 5000 = 250k rows — sanity stop
            print(f"  [fund_portfolio period={period}] hit 50-page safety limit")
            break
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_fund_portfolio(dry_run: bool = False) -> None:
    """
    Per-quarter cache files. Aggregate at the end into per-(stock × end_date)
    fund_holding_pct.
    """
    print("\n=== fetch_fund_portfolio ===")
    periods = _quarter_ends_in_range(FETCH_START, FETCH_END)
    if dry_run:
        periods = periods[-1:]
        print(f"  [dry-run] period={periods[0]}")
    print(f"  iterating {len(periods)} quarterly periods "
          f"(serial; Tushare rate-limits this endpoint to 60/min)...")

    if dry_run:
        period = periods[0]
        df = _fetch_fund_portfolio_period_full(period)
        print(f"  [dry-run] period={period} rows={len(df)} "
              f"cols={list(df.columns) if len(df) else '(empty)'}")
        if len(df):
            print(df.head())
        return

    def _fetch_one(period: str) -> tuple[str, int, str | None]:
        cache_path = config.FUND_PORTFOLIO_RAW_DIR / f"fund_portfolio_{period}.parquet"
        if read_parquet_safe(cache_path, expected_min_rows=10) is not None:
            return period, -1, None
        try:
            df = _fetch_fund_portfolio_period_full(period)
        except Exception as exc:
            return period, 0, repr(exc)
        if len(df) == 0:
            return period, 0, "no rows"
        write_parquet_atomic(df, cache_path)
        return period, len(df), None

    t0 = time.time()
    done = 0
    skipped = 0
    failed: list[str] = []
    # Serial: Tushare's published cap on fund_portfolio is 60/min and we
    # paginate ~33 pages per quarter, so a single worker is the right
    # cadence. The dedicated limiter inside _fetch_fund_portfolio_one_period
    # paces calls at 50/min for safety.
    for p in periods:
        period_, n, err = _fetch_one(p)
        if err and n == 0:
            failed.append(p)
            print(f"  [period={p}] FAIL/empty: {err}")
            continue
        if n == -1:
            skipped += 1
        else:
            done += 1
            print(f"  [{done + skipped}/{len(periods)}] {p}: rows={n:,}  "
                  f"elapsed={time.time()-t0:.1f}s")
    if failed:
        print(f"  WARN: {len(failed)} periods failed: {failed[:5]}")

    # Aggregate: per (held_stock, end_date) sum mkv across funds, divide by
    # held_stock's total_mv at end_date.
    if dry_run:
        return

    print("  aggregating per-stock × end_date...")
    files = sorted(config.FUND_PORTFOLIO_RAW_DIR.glob("fund_portfolio_*.parquet"))
    if not files:
        print("  WARN: no fund_portfolio files found")
        return
    frames = [pd.read_parquet(p) for p in files]
    raw = pd.concat(frames, ignore_index=True)
    print(f"  raw rows: {len(raw):,}")

    # Field mapping per Tushare docs:
    #   ts_code = fund code
    #   symbol  = held stock code
    #   ann_date, end_date
    #   mkv     = market value of holding (in 元)
    #   amount  = number of shares
    if "symbol" not in raw.columns:
        # Some versions use "stk_code" or similar. Probe.
        cand = [c for c in raw.columns if "code" in c.lower() and c != "ts_code"]
        if not cand:
            raise RuntimeError(
                f"fund_portfolio response missing held-stock column. "
                f"columns: {list(raw.columns)}"
            )
        raw = raw.rename(columns={cand[0]: "symbol"})

    # Tushare returns held-stock as either 6-digit or with .SH/.SZ suffix.
    # Normalize to ts_code form.
    def _to_ts_code(s):
        if not isinstance(s, str):
            return None
        if "." in s:
            return s
        if s.startswith(("60", "68")):
            return f"{s}.SH"
        if s.startswith(("00", "30")):
            return f"{s}.SZ"
        return None

    raw["held_ts_code"] = raw["symbol"].map(_to_ts_code)
    raw = raw.dropna(subset=["held_ts_code"])
    raw["mkv"] = pd.to_numeric(raw["mkv"], errors="coerce")
    raw = raw.dropna(subset=["mkv", "end_date"])

    agg = (
        raw.groupby(["held_ts_code", "end_date"], as_index=False)
        .agg(fund_total_mkv=("mkv", "sum"),
             ann_date_max=("ann_date", "max"),
             n_funds=("ts_code", "nunique"))
        .rename(columns={"held_ts_code": "ts_code"})
    )
    print(f"  aggregated: {len(agg):,} (stock × end_date) rows; "
          f"unique stocks={agg['ts_code'].nunique()}; "
          f"unique end_dates={agg['end_date'].nunique()}")

    write_parquet_atomic(agg, config.FUND_PORTFOLIO_AGGREGATE_PATH)
    print(f"  wrote {config.FUND_PORTFOLIO_AGGREGATE_PATH}")


# ═══════════════════════════════════════════════════════════════════════
# 3. hk_hold (per-stock, multi-day window)
#
# pro.hk_hold cross-sectional access (trade_date= alone) is restricted on
# this account's Tushare quota — empirically returned 0 rows when filtered
# by exchange='SH'/'SZ', and Southbound-only rows when called bare. The
# per-stock form (ts_code + start_date + end_date) does work, returning
# Northbound holdings for that A-share over the date range. We therefore
# iterate by A-share ts_code, one call per stock for the full panel window.
# ═══════════════════════════════════════════════════════════════════════

@retry_on_network_error(max_attempts=4, label="hk_hold")
def _fetch_hk_hold_one_stock(ts_code: str,
                              start: str, end: str) -> pd.DataFrame:
    acquire_rate_token()
    df = pro.hk_hold(ts_code=ts_code, start_date=start, end_date=end)
    return df if df is not None else pd.DataFrame()


def _ashare_universe_from_stock_basic() -> list[str]:
    """All A-share ts_codes (excluding 北交所) from stock_basic.csv."""
    import re as _re
    df = pd.read_csv(config.STOCK_BASIC_PATH)
    pat = _re.compile(config.A_SHARE_PATTERN)
    return [c for c in df["ts_code"].astype(str) if pat.match(c)]


def fetch_hk_hold(dry_run: bool = False) -> None:
    """
    Per-stock Northbound holdings. One call per A-share for the full window.
    Outputs cached per-stock parquet, then assembled to per-day parquets in
    a final pass to mirror the original cache layout consumed by rdi_compute.
    """
    print("\n=== fetch_hk_hold (per-stock mode) ===")
    tickers = _ashare_universe_from_stock_basic()
    print(f"  A-share ts_codes: {len(tickers)}")
    if dry_run:
        tickers = tickers[:1]
        print(f"  [dry-run] ts_code={tickers[0]}")
    start = FETCH_START.strftime("%Y%m%d")
    end = FETCH_END.strftime("%Y%m%d")

    per_stock_dir = config.RAW_DIR / "hk_hold_per_stock"
    per_stock_dir.mkdir(exist_ok=True)

    def _process(tc: str) -> tuple[str, int, str | None]:
        cache = per_stock_dir / f"hk_hold_{tc.replace('.', '_')}.parquet"
        if read_parquet_safe(cache, expected_min_rows=1) is not None:
            return tc, -1, None
        try:
            df = _fetch_hk_hold_one_stock(tc, start, end)
        except Exception as exc:
            return tc, 0, repr(exc)
        if dry_run:
            print(f"  [dry-run] ts_code={tc} rows={len(df)} "
                  f"cols={list(df.columns) if len(df) else '(empty)'}")
            if len(df):
                print(df.head())
            return tc, len(df), None
        if len(df) == 0:
            # Sentinel: stock not Stock-Connect eligible during window.
            empty = pd.DataFrame({
                "ts_code": [tc], "trade_date": [None],
                "vol": [float("nan")], "ratio": [float("nan")],
            })
            write_parquet_atomic(empty, cache)
            return tc, 0, None
        write_parquet_atomic(df, cache)
        return tc, len(df), None

    if dry_run:
        _process(tickers[0])
        return

    t0 = time.time()
    failed: list[str] = []
    skipped = 0
    fetched = 0
    eligible_stocks = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(_process, tc): tc for tc in tickers}
        for i, fut in enumerate(as_completed(futures), 1):
            tc = futures[fut]
            try:
                _, n, err = fut.result()
            except Exception as exc:
                err = repr(exc)
                n = 0
            if err:
                failed.append(tc)
                continue
            if n == -1:
                skipped += 1
            else:
                fetched += 1
                if n > 0:
                    eligible_stocks += 1
            if i % 200 == 0 or i == len(tickers):
                print(f"  [{i}/{len(tickers)}] elapsed={time.time()-t0:.1f}s "
                      f"fetched={fetched} cached_skip={skipped} "
                      f"eligible={eligible_stocks} fails={len(failed)}")
    if failed:
        print(f"  WARN: {len(failed)} stocks failed; first few: {failed[:5]}")

    # Reassemble per-day parquets so rdi_compute.load_hk_hold_for_date works.
    print("\n  reassembling to per-day parquets...")
    files = sorted(per_stock_dir.glob("hk_hold_*.parquet"))
    if not files:
        print("  WARN: no per-stock files to assemble")
        return
    frames = []
    for p in files:
        df = pd.read_parquet(p)
        if df.empty:
            continue
        # Drop sentinel rows
        df = df[df["trade_date"].notna()]
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        print("  WARN: all per-stock files were sentinels; no Northbound data")
        return
    big = pd.concat(frames, ignore_index=True)
    print(f"  combined rows: {len(big):,}")
    n_dates_written = 0
    for d, group in big.groupby("trade_date"):
        cache = config.HK_HOLD_DIR / f"hk_hold_{d}.parquet"
        if cache.exists():
            continue
        keep = ["ts_code", "trade_date", "name", "vol", "ratio", "exchange"]
        keep = [c for c in keep if c in group.columns]
        write_parquet_atomic(group[keep].reset_index(drop=True), cache)
        n_dates_written += 1
    print(f"  wrote {n_dates_written} per-day parquets")


# ═══════════════════════════════════════════════════════════════════════
# 4. moneyflow (per-day)
# ═══════════════════════════════════════════════════════════════════════

@retry_on_network_error(max_attempts=4, label="moneyflow")
def _fetch_moneyflow_one_day(trade_date: str) -> pd.DataFrame:
    acquire_rate_token()
    df = pro.moneyflow(trade_date=trade_date)
    return df if df is not None else pd.DataFrame()


def fetch_moneyflow(dry_run: bool = False) -> None:
    print("\n=== fetch_moneyflow ===")
    dates = _trade_days_in_range(FETCH_START, FETCH_END)
    if dry_run:
        dates = dates[-1:]
        print(f"  [dry-run] trade_date={dates[0]}")
    print(f"  iterating {len(dates)} trading days...")

    def _process(d: str) -> tuple[str, int, str | None]:
        cache = config.MONEYFLOW_DIR / f"moneyflow_{d}.parquet"
        if read_parquet_safe(cache, expected_min_rows=1) is not None:
            return d, -1, None
        try:
            df = _fetch_moneyflow_one_day(d)
        except Exception as exc:
            return d, 0, repr(exc)
        if dry_run:
            print(f"  [dry-run] trade_date={d} rows={len(df)} "
                  f"cols={list(df.columns) if len(df) else '(empty)'}")
            if len(df):
                print(df.head())
            return d, len(df), None
        if len(df) == 0:
            empty = pd.DataFrame({"trade_date": [d], "ts_code": [None]})
            write_parquet_atomic(empty, cache)
            return d, 0, None
        write_parquet_atomic(df, cache)
        return d, len(df), None

    if dry_run:
        _process(dates[0])
        return

    t0 = time.time()
    failed: list[str] = []
    skipped = 0
    fetched = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(_process, d): d for d in dates}
        for i, fut in enumerate(as_completed(futures), 1):
            d = futures[fut]
            try:
                _, n, err = fut.result()
            except Exception as exc:
                err = repr(exc)
                n = 0
            if err:
                failed.append(d)
                continue
            if n == -1:
                skipped += 1
            else:
                fetched += 1
            if i % 100 == 0 or i == len(dates):
                print(f"  [{i}/{len(dates)}] elapsed={time.time()-t0:.1f}s "
                      f"fetched={fetched} cached_skip={skipped} fails={len(failed)}")
    if failed:
        print(f"  WARN: {len(failed)} dates failed; first few: {failed[:5]}")


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Fetch RDI data from Tushare")
    parser.add_argument("endpoint", nargs="?", default="all",
                        choices=["all", "holdernumber", "fund_portfolio",
                                 "hk_hold", "moneyflow"])
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch one period/date sample only.")
    args = parser.parse_args()

    if args.endpoint in ("all", "holdernumber"):
        fetch_holdernumber(dry_run=args.dry_run)
    if args.endpoint in ("all", "fund_portfolio"):
        fetch_fund_portfolio(dry_run=args.dry_run)
    if args.endpoint in ("all", "hk_hold"):
        fetch_hk_hold(dry_run=args.dry_run)
    if args.endpoint in ("all", "moneyflow"):
        fetch_moneyflow(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
