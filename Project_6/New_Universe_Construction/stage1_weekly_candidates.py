"""
stage1_with_pit_names.py — Stage 1 with point-in-time ST classification.

Replaces the survivorship-bias-prone current-name-only ST filter with a
point-in-time filter built from pro.namechange(). For each (ts_code,
rebalance_date), looks up the name in effect on that date and applies
the ST/*ST prefix check against that historical name, not the current one.

Why this matters
----------------
The previous Stage 1 used pro.stock_basic(list_status='L'), which only
returns currently-listed stocks. ~213 stocks (~6% of early-2019 A-share
candidates) had no current name and bypassed the ST filter entirely.
Many of those were ST or *ST in 2019 and would have been correctly
excluded from the universe. Letting them through pollutes any small-cap
value or low-vol analysis with shell-value contamination.

Pipeline
--------
  pro.namechange()  ──>  data/historical_names.csv  (one row per name change)
                          │
                          ▼
                build name-as-of-date lookup
                          │
                          ▼
  data/daily_panel/daily_<date>.parquet  ──>  filter chain  ──>
                                              data/candidates_weekly_pit/
                                              cand_<date>.parquet

API calls: ~6 paginated calls to pro.namechange(), ~30 seconds.
After the historical names cache is built, rebuilding all 381 candidate
parquets takes ~1 minute.

Usage
-----
    python stage1_with_pit_names.py pull       # one-time historical name pull
    python stage1_with_pit_names.py smoke      # 5 dates, verbose output
    python stage1_with_pit_names.py full       # all 381 dates
    python stage1_with_pit_names.py status     # cache hit rate
"""

import bisect
import logging
import os
import sys
import time
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

DATA_DIR = Path("data")
PANEL_DIR = DATA_DIR / "daily_panel"
CANDIDATES_DIR = DATA_DIR / "candidates_weekly_pit"  # NEW: separate from old
HISTORICAL_NAMES_PATH = DATA_DIR / "historical_names.csv"
STOCK_BASIC_PATH = DATA_DIR / "stock_basic.csv"
TRADING_CALENDAR_PATH = DATA_DIR / "trading_calendar.csv"
REBALANCE_DATES_PATH = DATA_DIR / "weekly_rebalance_dates.csv"
ERROR_LOG = DATA_DIR / "errors_stage1_pit.log"

DATA_DIR.mkdir(exist_ok=True)
CANDIDATES_DIR.mkdir(exist_ok=True)

REBALANCE_START = "2019-01-02"
REBALANCE_WEEKDAY = 2  # Wednesday

A_SHARE_PATTERN = r"^(60|68)\d{4}\.SH$|^(00|30)\d{4}\.SZ$"

COMPRESSION = "zstd"

EXPECTED_CANDIDATE_COLUMNS = [
    "ts_code", "trade_date", "turnover_rate", "volume_ratio",
    "pe", "pe_ttm", "pb", "ps",
    "total_share", "float_share", "total_mv", "circ_mv",
    "open", "high", "low", "close", "vol", "amount",
    "name", "circ_mv_yi",
]


# ==========================================================
# Error logging
# ==========================================================

_logger = logging.getLogger("stage1_pit")
_logger.setLevel(logging.WARNING)
_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
_logger.addHandler(_handler)


def _log_warn(date, msg):
    _logger.warning(f"date={date} | {msg}")


# ==========================================================
# Step 1: Historical name pull via pro.namechange()
# ==========================================================

def pull_historical_names():
    """
    Pull every historical name change from pro.namechange().

    Tushare's namechange endpoint returns one row per (ts_code, name)
    historical instance with a start_date (when the name took effect)
    and end_date (when it stopped, NaN if still current). The endpoint
    paginates at 5000 rows; we loop until we've seen every row.

    Returns a DataFrame with columns ts_code, name, start_date, end_date,
    ann_date. Cached to historical_names.csv on first call.
    """
    if HISTORICAL_NAMES_PATH.exists():
        print(f"Loading cached historical names from {HISTORICAL_NAMES_PATH}")
        return pd.read_csv(
            HISTORICAL_NAMES_PATH,
            dtype={"ts_code": str, "start_date": str, "end_date": str,
                   "ann_date": str, "name": str}
        )

    print(f"Pulling historical names from pro.namechange()...")
    print(f"  Tushare paginates at 5000 rows; looping until exhausted.")

    all_frames = []
    offset = 0
    page_size = 5000

    while True:
        df = pro.namechange(
            ts_code="", start_date="", end_date="",
            offset=offset, limit=page_size,
            fields="ts_code,name,start_date,end_date,ann_date,change_reason"
        )
        if df is None or len(df) == 0:
            break
        all_frames.append(df)
        print(f"  page {len(all_frames)}: offset={offset}, rows={len(df)}")
        if len(df) < page_size:
            break
        offset += page_size
        time.sleep(0.2)  # courtesy spacing between pages

    if not all_frames:
        raise RuntimeError("pro.namechange() returned no data")

    historical = pd.concat(all_frames, ignore_index=True)

    # Tushare returns dates as 'YYYYMMDD' strings; keep as strings for
    # cheap lexicographic comparison against our 'YYYY-MM-DD' rebalance
    # dates after a quick reformat.
    for col in ["start_date", "end_date", "ann_date"]:
        if col in historical.columns:
            historical[col] = historical[col].apply(
                lambda s: f"{s[:4]}-{s[4:6]}-{s[6:]}" if pd.notna(s) and len(str(s)) == 8 else s
            )

    historical.to_csv(HISTORICAL_NAMES_PATH, index=False)

    n_unique = historical["ts_code"].nunique()
    print(f"\n  cached {len(historical):,} name records "
          f"covering {n_unique:,} unique ts_codes -> {HISTORICAL_NAMES_PATH}")
    return historical


# ==========================================================
# Step 2: Build name-as-of-date lookup
# ==========================================================

def build_name_lookup(historical):
    """
    Convert the historical names DataFrame into an efficient lookup:
    for each ts_code, store (sorted start_dates, names_in_order).

    Lookup at date d uses bisect to find the name in effect on d.
    Per (ts_code, d) lookup is O(log k) where k is the number of name
    changes for that code (typically 1-5).
    """
    lookup = {}
    for ts_code, group in historical.groupby("ts_code"):
        sorted_group = group.sort_values("start_date")
        starts = sorted_group["start_date"].tolist()
        names = sorted_group["name"].tolist()
        lookup[ts_code] = (starts, names)
    return lookup


def name_as_of(ts_code, date_str, lookup, fallback=None):
    """
    Return the name in effect for ts_code on date_str (YYYY-MM-DD).
    fallback is returned if ts_code has no historical name records OR
    if date_str is before the earliest known name change.
    """
    if ts_code not in lookup:
        return fallback
    starts, names = lookup[ts_code]
    # bisect_right finds the rightmost start_date <= date_str.
    idx = bisect.bisect_right(starts, date_str) - 1
    if idx < 0:
        return fallback
    return names[idx]


# ==========================================================
# Step 3: Weekly rebalance dates (reads cached file from earlier Stage 1)
# ==========================================================

def get_trading_calendar():
    if not TRADING_CALENDAR_PATH.exists():
        raise FileNotFoundError(
            f"{TRADING_CALENDAR_PATH} not found. Run daily_panel_pull.py first."
        )
    return pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()


def generate_weekly_rebalance_dates(force_refresh=False):
    """Same logic as the previous Stage 1; reuses the cached CSV if present."""
    if REBALANCE_DATES_PATH.exists() and not force_refresh:
        return pd.read_csv(REBALANCE_DATES_PATH)["date"].tolist()

    calendar = get_trading_calendar()
    last_trading_day = pd.to_datetime(calendar[-1])

    start_dt = pd.to_datetime(REBALANCE_START)
    days_to_wed = (REBALANCE_WEEKDAY - start_dt.weekday()) % 7
    first_wed = start_dt + pd.Timedelta(days=days_to_wed)

    rebalance_dates = []
    current = first_wed
    while current <= last_trading_day:
        wed_str = current.strftime("%Y-%m-%d")
        idx = bisect.bisect_left(calendar, wed_str)
        if idx < len(calendar):
            rebalance_dates.append(calendar[idx])
        current += pd.Timedelta(days=7)

    rebalance_dates = sorted(set(rebalance_dates))
    pd.DataFrame({"date": rebalance_dates}).to_csv(REBALANCE_DATES_PATH, index=False)
    print(f"  generated {len(rebalance_dates)} weekly rebalance dates")
    return rebalance_dates


# ==========================================================
# Step 4: Candidate building with PIT names
# ==========================================================

def _cache_path(date):
    return CANDIDATES_DIR / f"cand_{date}.parquet"


def _is_cached_with_valid_schema(date):
    path = _cache_path(date)
    if not path.exists():
        return False
    try:
        import pyarrow.parquet as pq
        cached_cols = set(pq.read_schema(path).names)
        missing = set(EXPECTED_CANDIDATE_COLUMNS) - cached_cols
        if missing:
            print(f"  [stale] {path.name} missing {sorted(missing)}; rebuild")
            return False
        return True
    except Exception as exc:
        print(f"  [corrupt] {path.name}: {exc}")
        return False


def build_candidates_for_date(rebalance_date, name_lookup, current_name_map,
                              verbose=False):
    """
    Apply Stage 1 filters with point-in-time ST classification.

    For each candidate row, the name used for ST checking is:
      1. The historical name as of rebalance_date if present in namechange data
      2. Otherwise, the current name from stock_basic (fallback)
      3. Otherwise, NaN — these rows now produce a clean diagnostic count
         rather than silently bypassing the ST filter.
    """
    panel_path = PANEL_DIR / f"daily_{rebalance_date}.parquet"
    if not panel_path.exists():
        _log_warn(rebalance_date, f"daily panel missing: {panel_path}")
        return None

    daily = pd.read_parquet(panel_path)
    n_start = len(daily)

    # Filter 1: A-share equity codes
    daily = daily[daily["ts_code"].str.match(A_SHARE_PATTERN)].copy()
    n_after_ashare = len(daily)

    # Filter 2: PIT name lookup, then ST/*ST exclusion
    daily["name"] = daily["ts_code"].apply(
        lambda c: name_as_of(c, rebalance_date, name_lookup,
                             fallback=current_name_map.get(c))
    )

    n_truly_unknown = int(daily["name"].isna().sum())
    n_st_caught_by_pit = int(
        daily["name"].fillna("").str.startswith(("ST", "*ST")).sum()
    )

    daily = daily[~daily["name"].fillna("").str.startswith(("ST", "*ST"))]
    n_after_st = len(daily)

    # Filter 3: edge cases
    daily = daily[
        (daily["turnover_rate"] > 0)
        & (daily["circ_mv"].notna())
        & (daily["circ_mv"] > 0)
    ]
    n_after_edge = len(daily)

    daily["circ_mv_yi"] = daily["circ_mv"] / 10_000
    daily = daily.sort_values("circ_mv").reset_index(drop=True)

    if verbose:
        print(f"  filters: {n_start} -> {n_after_ashare} (A-share) "
              f"-> {n_after_st} (non-ST PIT) "
              f"-> {n_after_edge} (turn>0, circ_mv>0)")
        print(f"  PIT diagnostics: "
              f"{n_st_caught_by_pit} ST/*ST caught by PIT names, "
              f"{n_truly_unknown} truly nameless rows "
              f"({100 * n_truly_unknown / max(n_after_ashare, 1):.3f}%)")

    for col in EXPECTED_CANDIDATE_COLUMNS:
        if col not in daily.columns:
            daily[col] = pd.NA
    return daily[EXPECTED_CANDIDATE_COLUMNS]


def _ensure_candidates_built(date, name_lookup, current_name_map, verbose=False):
    if _is_cached_with_valid_schema(date):
        return "cached"

    path = _cache_path(date)
    if path.exists():
        path.unlink()

    df = build_candidates_for_date(date, name_lookup, current_name_map,
                                   verbose=verbose)
    if df is None or len(df) == 0:
        return "failed"
    df.to_parquet(path, compression=COMPRESSION, index=False)
    return "built"


# ==========================================================
# Drivers
# ==========================================================

def _load_name_resources():
    """Load historical names + current names; build the PIT lookup."""
    historical = pull_historical_names()
    name_lookup = build_name_lookup(historical)

    if STOCK_BASIC_PATH.exists():
        basic = pd.read_csv(STOCK_BASIC_PATH, dtype={"ts_code": str})
        current_name_map = dict(zip(basic["ts_code"], basic["name"]))
    else:
        current_name_map = {}

    print(f"  PIT name lookup: {len(name_lookup):,} ts_codes with history")
    print(f"  current name map: {len(current_name_map):,} listed names\n")

    return name_lookup, current_name_map


def pull_only():
    """Just run the historical-names pull. Useful for inspection before smoke."""
    historical = pull_historical_names()
    print(f"\nSummary:")
    print(f"  total records:      {len(historical):,}")
    print(f"  unique ts_codes:    {historical['ts_code'].nunique():,}")
    print(f"  earliest start:     {historical['start_date'].min()}")
    print(f"  latest start:       {historical['start_date'].max()}")

    st_records = historical[
        historical["name"].fillna("").str.startswith(("ST", "*ST"))
    ]
    print(f"\n  records with ST/*ST in the name: {len(st_records):,}")
    print(f"  unique stocks that were ST/*ST at some point: "
          f"{st_records['ts_code'].nunique():,}")


def smoke_test():
    print("=" * 60)
    print(f"STAGE 1 PIT SMOKE: 5 weekly dates with point-in-time names")
    print("=" * 60)

    name_lookup, current_name_map = _load_name_resources()
    rebalance_dates = generate_weekly_rebalance_dates()
    test_dates = rebalance_dates[:5]

    t0 = time.time()
    for i, date in enumerate(test_dates, 1):
        print(f"[{i}/5] {date}")
        result = _ensure_candidates_built(date, name_lookup, current_name_map,
                                          verbose=True)
        if result == "failed":
            print(f"  -> FAILED")
        else:
            df = pd.read_parquet(_cache_path(date))
            print(f"  -> {result}: {len(df)} candidates, "
                  f"smallest cap {df['circ_mv_yi'].iloc[0]:.2f} 亿, "
                  f"largest cap {df['circ_mv_yi'].iloc[-1]:.2f} 亿")
        print()

    print(f"Smoke done in {time.time() - t0:.1f}s.")
    print(f"Compare candidate counts vs the previous (current-name) Stage 1:")
    print(f"  previous: ~3,372 candidates per Jan-2019 date")
    print(f"  new PIT:  should be ~50-150 fewer (the ST stocks now caught)")


def full_run():
    print(f"STAGE 1 PIT FULL: building all weekly candidate sets")
    name_lookup, current_name_map = _load_name_resources()
    rebalance_dates = generate_weekly_rebalance_dates()

    cached = [d for d in rebalance_dates if _is_cached_with_valid_schema(d)]
    pending = [d for d in rebalance_dates if not _is_cached_with_valid_schema(d)]
    print(f"  total: {len(rebalance_dates)}, cached: {len(cached)}, "
          f"pending: {len(pending)}")

    if not pending:
        print(f"  Nothing to do. Delete {CANDIDATES_DIR}/ to rebuild.")
        return

    t0 = time.time()
    n_built = 0
    n_failed = 0
    for i, date in enumerate(pending, 1):
        result = _ensure_candidates_built(date, name_lookup, current_name_map,
                                          verbose=False)
        if result == "built":
            n_built += 1
        elif result == "failed":
            n_failed += 1
        if i % 50 == 0 or i == len(pending):
            secs = time.time() - t0
            print(f"[{i:>4}/{len(pending)}] built={n_built}, "
                  f"failed={n_failed}, elapsed={secs:.1f}s")

    secs = time.time() - t0
    print(f"\nFull run: {n_built} built, {n_failed} failed in {secs:.1f}s")


def status():
    rebalance_dates = generate_weekly_rebalance_dates()
    cached = [d for d in rebalance_dates if _is_cached_with_valid_schema(d)]
    missing = [d for d in rebalance_dates if not _is_cached_with_valid_schema(d)]
    print(f"Weekly dates: {len(rebalance_dates)}")
    print(f"Cached:       {len(cached)} ({100*len(cached)/len(rebalance_dates):.1f}%)")
    print(f"Missing:      {len(missing)}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "pull":
        pull_only()
    elif mode == "smoke":
        smoke_test()
    elif mode == "full":
        full_run()
    elif mode == "status":
        status()
    else:
        print(f"Usage: python stage1_with_pit_names.py [pull|smoke|full|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()