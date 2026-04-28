"""
Project 5 Session 2: point-in-time universe membership construction (Tushare rebuild).

Replaces the previous baostock 8-thread pipeline. Each rebalance date now
costs 2 API calls (daily_basic + daily) instead of ~5000 per-stock calls,
collapsing the full 52-date Stage 1 from ~24 hours to ~2 minutes.

Stage 1 (this file): pull and cache per-date candidate sets.
Stage 2 (later):     trailing-20-day liquidity filter.
Stage 3 (later):     final membership table across all dates.
"""

from datetime import date
import sys
import time
import logging
from pathlib import Path

import pandas as pd

from tushare_setup import pro

# Force line-buffered stdout for clean progress output
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass


# ==========================================================
# Configuration
# ==========================================================

DATA_DIR = Path("data")
CANDIDATES_DIR = DATA_DIR / "candidates"
REBALANCE_DATES_CSV = DATA_DIR / "rebalance_dates.csv"
STOCK_BASIC_CACHE = DATA_DIR / "stock_basic.csv"
ERROR_LOG = DATA_DIR / "errors_universe_construction.log"

DATA_DIR.mkdir(exist_ok=True)
CANDIDATES_DIR.mkdir(exist_ok=True)

SAMPLE_START = "2022-01-01"
SAMPLE_END = "2026-04-23"

# A-share equity ts_code patterns:
#   60xxxx.SH  Shanghai main board
#   68xxxx.SH  科创板 (STAR Market)
#   00xxxx.SZ  Shenzhen main + SME boards
#   30xxxx.SZ  创业板 (ChiNext)
A_SHARE_PATTERN = r"^(60|68)\d{4}\.SH$|^(00|30)\d{4}\.SZ$"

# Expected schema for cached candidate CSVs. If this set is not a subset
# of the columns on disk, the cached file was produced by an older version
# of the pipeline (most often the deprecated baostock derivation) and must
# be regenerated.
EXPECTED_CANDIDATE_COLUMNS = frozenset({
    "ts_code", "trade_date", "turnover_rate", "volume_ratio",
    "pe", "pe_ttm", "pb", "ps",
    "total_share", "float_share", "total_mv", "circ_mv",
    "open", "high", "low", "close", "vol", "amount",
    "name", "circ_mv_yi",
})


# ==========================================================
# Error logging
# ==========================================================

_logger = logging.getLogger("universe_construction")
_logger.setLevel(logging.WARNING)
_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
_logger.addHandler(_handler)


def _log_error(stage, date, code, err):
    _logger.warning(
        f"stage={stage} | date={date or '-'} | code={code or '-'} | error={err}"
    )


# ==========================================================
# Reference data: stock_basic for ST filtering
# ==========================================================

def get_stock_basic():
    """
    Pull and cache the stock_basic table. Used to filter ST stocks via
    name prefix ('ST' or '*ST'). Note: this gives CURRENT names, so
    point-in-time ST status is approximated. Better point-in-time fidelity
    would require pro.namechange(); deferred for now and noted as a known
    bias.
    """
    if STOCK_BASIC_CACHE.exists():
        return pd.read_csv(STOCK_BASIC_CACHE, dtype={"ts_code": str})

    df = pro.stock_basic(
        list_status="L",
        fields="ts_code,symbol,name,area,industry,list_date"
    )
    df.to_csv(STOCK_BASIC_CACHE, index=False)
    print(f"  cached {len(df)} stock_basic rows to {STOCK_BASIC_CACHE}")
    return df


# ==========================================================
# Rebalance date generation
# ==========================================================

def _yyyymmdd(s):
    """Convert 'YYYY-MM-DD' to 'YYYYMMDD' (Tushare's date format)."""
    return s.replace("-", "")


def build_rebalance_dates():
    """
    Generate the 52 monthly rebalance dates: the 15th of each month from
    Jan 2022 through Apr 2026, rolled forward to the next trading day if
    the 15th is a weekend or holiday. Cached to rebalance_dates.csv.
    """
    if REBALANCE_DATES_CSV.exists():
        return pd.read_csv(REBALANCE_DATES_CSV)["date"].tolist()

    cal = pro.trade_cal(
        exchange="SSE",
        start_date="20220101",
        end_date="20260531",
        is_open="1"
    )
    trading_days = set(cal["cal_date"].tolist())

    dates = []
    for year in range(2022, 2027):
        for month in range(1, 13):
            if year == 2026 and month > 4:
                break
            target = pd.Timestamp(year=year, month=month, day=15)
            for _ in range(10):
                if target.strftime("%Y%m%d") in trading_days:
                    break
                target += pd.Timedelta(days=1)
            d = target.strftime("%Y-%m-%d")
            if target.strftime("%Y%m%d") in trading_days:
                dates.append(d)

    pd.DataFrame({"date": dates}).to_csv(REBALANCE_DATES_CSV, index=False)
    print(f"  saved {len(dates)} rebalance dates to {REBALANCE_DATES_CSV}")
    return dates


# ==========================================================
# Stage 1: per-date candidate pull
# ==========================================================

def _pull_candidates_for_date(date, stock_basic):
    """
    Pull one rebalance date's candidate set with TWO Tushare API calls:
    daily_basic for valuation/cap fields, daily for OHLCV. Merge, filter,
    cache. Returns the DataFrame.
    """
    cache_path = CANDIDATES_DIR / f"candidates_{date}.csv"
    if cache_path.exists():
        # Validate schema before trusting the cache. nrows=0 reads only
        # the header row, so this stays cheap even when iterating 52 dates.
        header = pd.read_csv(cache_path, nrows=0)
        missing = EXPECTED_CANDIDATE_COLUMNS - set(header.columns)
        if missing:
            print(f"[stale] {cache_path.name} missing columns {sorted(missing)}; "
                  f"deleting and re-pulling")
            cache_path.unlink()
        else:
            print(f"[cache] {cache_path.name} ok - loading")
            return pd.read_csv(cache_path, dtype={"ts_code": str})

    yyyymmdd = _yyyymmdd(date)
    print(f"[pull] {date}")

    # Call 1: cross-sectional valuation snapshot
    basic = pro.daily_basic(
        ts_code="",
        trade_date=yyyymmdd,
        fields="ts_code,trade_date,close,turnover_rate,volume_ratio,"
               "pe,pe_ttm,pb,ps,total_share,float_share,total_mv,circ_mv"
    )

    # Call 2: cross-sectional OHLCV
    daily = pro.daily(
        ts_code="",
        trade_date=yyyymmdd,
        fields="ts_code,trade_date,open,high,low,close,vol,amount"
    )

    if len(basic) == 0 or len(daily) == 0:
        _log_error("stage1", date, "?",
                   f"empty result: basic={len(basic)}, daily={len(daily)}")
        return pd.DataFrame()

    print(f"  daily_basic: {len(basic)} rows | daily: {len(daily)} rows")

    # Merge: daily.close is canonical, drop basic.close to avoid suffix
    merged = basic.drop(columns=["close"]).merge(
        daily[["ts_code", "open", "high", "low", "close", "vol", "amount"]],
        on="ts_code",
        how="inner",
    )

    # Attach name for ST filtering
    merged = merged.merge(
        stock_basic[["ts_code", "name"]],
        on="ts_code",
        how="left"
    )

    # ============================================
    # Filter chain
    # ============================================
    n_start = len(merged)

    # 1. A-share equity codes only (drops bj.*, B-shares)
    merged = merged[merged["ts_code"].str.match(A_SHARE_PATTERN)]
    n_after_ashare = len(merged)

    # Survivorship-bias visibility: rows with NaN name are A-shares that were
    # tradeable on `date` but have since delisted. They are absent from
    # stock_basic(list_status='L'), so the ST filter cannot evaluate them and
    # they pass through silently. Surface the count per date so the rate stays
    # visible across all 52 dates and any spike is noticed.
    n_unknown_name = merged["name"].isna().sum()
    if n_unknown_name > 0:
        pct = 100 * n_unknown_name / len(merged)
        print(f"  [WARN] {n_unknown_name} A-share rows ({pct:.3f}%) have NaN "
            f"name; likely delisted post-{date}, bypassing ST filter")

    # 2. Drop ST and *ST by name prefix (current names; point-in-time
    #    refinement deferred per docstring)
    merged = merged[~merged["name"].fillna("").str.startswith(("ST", "*ST"))]
    n_after_st = len(merged)

    # 3. Drop edge cases: zero turnover rate or missing market cap
    merged = merged[
        (merged["turnover_rate"] > 0)
        & (merged["circ_mv"].notna())
        & (merged["circ_mv"] > 0)
    ]
    n_after_edge = len(merged)

    print(
        f"  filters: {n_start} -> {n_after_ashare} (A-share equity) "
        f"-> {n_after_st} (非ST) -> {n_after_edge} (turn>0, circ_mv>0)"
    )

    # circ_mv comes in 万元; add 亿元 column for human readability
    merged["circ_mv_yi"] = merged["circ_mv"] / 10_000

    merged = merged.sort_values("circ_mv").reset_index(drop=True)
    merged.to_csv(cache_path, index=False)
    print(f"  saved {len(merged)} candidates to {cache_path}")
    return merged


# ==========================================================
# Stage 1 driver
# ==========================================================

def run_full_stage1():
    """Loop over all rebalance dates. Per-date caching means safe to interrupt."""
    dates = build_rebalance_dates()
    print(f"Stage 1: {len(dates)} rebalance dates "
          f"(first={dates[0]}, last={dates[-1]})")

    stock_basic = get_stock_basic()
    print(f"  stock_basic: {len(stock_basic)} listed stocks\n")

    t_start = time.time()
    cache_hits = 0
    total_fetched = 0

    for i, date in enumerate(dates, 1):
        t0 = time.time()
        cache_path = CANDIDATES_DIR / f"candidates_{date}.csv"
        was_cached = cache_path.exists()

        try:
            df = _pull_candidates_for_date(date, stock_basic)
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
              f"wall={per_date:>4.1f}s, total={total_min:>4.1f}min")

    total_min = (time.time() - t_start) / 60
    print(f"\nStage 1 complete: {len(dates)} dates in {total_min:.1f} min "
          f"({cache_hits} cache hits, {len(dates)-cache_hits} fresh pulls)")


# ==========================================================
# Smoke test: reproduce Session 1's 2024-12-31 result
# ==========================================================

def smoke_test_2024_12_31():
    """
    Compare the new Tushare pipeline's output for 2024-12-31 against
    Session 1's frozen baostock cache. Numbers should be close but not
    identical: different sources for total_share, ST detection, etc.
    """
    print("=" * 60)
    print("SMOKE TEST - 2024-12-31 (Tushare vs Session 1 baostock)")
    print("=" * 60)

    stock_basic = get_stock_basic()
    new_df = _pull_candidates_for_date("2024-12-31", stock_basic)

    s1_path = Path("data/kdata_2024-12-31.csv")
    if not s1_path.exists():
        print(f"\nSession 1 cache missing at {s1_path} - skipping comparison.")
        return

    s1 = pd.read_csv(
        s1_path,
        dtype={"code": str, "tradestatus": str, "isST": str},
    )
    for c in ("close", "volume", "amount", "turn"):
        s1[c] = pd.to_numeric(s1[c], errors="coerce")
    s1f = s1[s1["tradestatus"] == "1"]
    s1f = s1f[s1f["isST"] == "0"]
    s1f = s1f[(s1f["volume"] > 0) & (s1f["turn"] > 0)].copy()
    s1f["float_mcap"] = s1f["close"] * s1f["volume"] / (s1f["turn"] / 100)
    s1f["circ_mv_yi_baostock"] = s1f["float_mcap"] / 1e8

    # Convert baostock codes to Tushare format for comparison
    def bs_to_ts(c):
        m, n = c.split(".")
        return f"{n}.{m.upper()}"

    s1f["ts_code"] = s1f["code"].apply(bs_to_ts)
    compare = new_df[["ts_code", "circ_mv_yi"]].merge(
        s1f[["ts_code", "circ_mv_yi_baostock"]],
        on="ts_code",
        how="inner",
    )
    compare["diff_pct"] = (
        (compare["circ_mv_yi"] - compare["circ_mv_yi_baostock"]).abs()
        / compare["circ_mv_yi_baostock"] * 100
    )

    print(f"\nUniverse counts (after filters):")
    print(f"  Tushare:       {len(new_df)}")
    print(f"  baostock S1:   {len(s1f)}")
    print(f"  shared codes:  {len(compare)}")
    print(f"\n流通市值 cross-source comparison (亿 RMB):")
    print(f"  median |diff|:  {compare['diff_pct'].median():.3f}%")
    print(f"  P95    |diff|:  {compare['diff_pct'].quantile(0.95):.3f}%")
    print(f"  max    |diff|:  {compare['diff_pct'].max():.3f}%")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "full":
        run_full_stage1()
    else:
        smoke_test_2024_12_31()