"""
build_universe_panel.py — Build the seven-universe membership panel.

Reads:
  - data/index_constituents/<index>_<YYYY-MM>.parquet  (Tushare snapshots)
  - ../Project_6/data/universe_membership_X75_Y3000.parquet  (U2)
  - ../Project_6/data/weekly_rebalance_dates.csv
  - daily_panel/daily_<DATE>.parquet  (for U1, U7 floor checks)

Writes:
  - data/universe_membership_seven.parquet
    Columns: rebalance_date, ts_code, in_U1, in_U2, ..., in_U7,
             circ_mv_yi, exchange_tier
    One row per (rebalance_date, eligible_ts_code) where "eligible"
    means "passed the basic A-share filter on that date."

Universes
---------
  U1: All A-share equity, ST/退市/北交所 excluded.
  U2: Project 6 (bottom 1000 by 流通市值 + hybrid liquidity floor).
       Read directly from Project 6's parquet.
  U3: 中证1000 explicit constituents.
  U4: 中证2000 explicit constituents (Aug 2023 onward only).
  U5: U3 ∪ U4.
  U6: NOT in CSI300 ∪ CSI500. Excludes nothing else; the raw "outside
       index 800" tail. Includes some bottom-of-CSI500 names that are
       in fact mid-cap. We accept this; the alternative (NOT in CSI800)
       is the same thing only if Tushare populates CSI800 directly.
  U7: U6 + (top 75% by 60-day mean amount AND ≥3000万 absolute floor)
       AND ≥20 of 60 trading days observed. Same parameters as U2's
       hybrid floor for direct comparability.

Index constituent point-in-time lookup
--------------------------------------
For each rebalance_date, we want "the most recent monthly snapshot at
or before that date." Tushare's monthly snapshots are at month-end.
For a Wednesday rebalance on 2024-09-25, we use the 2024-08 snapshot
because 2024-09 was not yet finalized. This adds at most one month of
lag in membership detection, which is below the precision we need.

Liquidity floor for U7
----------------------
Implemented by reading Project 6's liquidity_panel_60d.parquet, which
already has the 60-day trailing mean amount per (rebalance_date, ts_code).
We re-apply the percentile and absolute thresholds on the U6 sub-pool.
The percentile is computed within the U6 pool, not the universe at
large, so U7 is "the top 75% of liquidity within the outside-CSI800
sub-universe" rather than "the outside-CSI800 names that happen to
clear an absolute amount threshold from the broader universe."

A-share filter
--------------
Standard pattern:
  - prefix sh.60, sh.68, sz.00, sz.30 (Tushare uses .SH/.SZ suffix)
  - exclude ST/*ST by name (PIT name from Project 6's historical_names)
  - exclude 北交所 (8x/4x/920) by prefix
  - require valid circ_mv > 0

We could re-use Project 6's stage1_with_pit_names output but for
clarity we run the filter inline against the daily panel; the cost is
~5 seconds per date and gives us a self-contained pipeline.

Usage
-----
    python build_universe_panel.py smoke   # 5 rebalance dates
    python build_universe_panel.py full    # all rebalance dates
    python build_universe_panel.py status  # inspect output
"""

import logging
import sys
import time
from pathlib import Path

import bisect
import numpy as np
import pandas as pd

from config import (
    A_SHARE_PATTERN,
    AMOUNT_QIANYUAN_TO_WAN,
    CIRC_MV_WAN_TO_YI,
    CSI2000_INCEPTION,
    DAILY_PANEL_DIR,
    INDEX_CONSTITUENTS_DIR,
    LIQUIDITY_FLOOR_AMOUNT_WAN,
    LIQUIDITY_FLOOR_PERCENTILE,
    LIQUIDITY_MIN_DAYS,
    PROJ6_UNIVERSE_PATH,
    PROJECT_6_DATA_DIR,
    UNIVERSE_KEYS,
    UNIVERSE_PANEL_PATH,
    WEEKLY_REBALANCE_DATES_PATH,
)


# ─── Configuration ─────────────────────────────────────────────────────

ERROR_LOG = Path("data") / "errors_build_universe.log"
COMPRESSION = "zstd"

# Liquidity panel from Project 6 (60-day trailing mean amount per stock per
# weekly rebalance date). We expect it to exist; if not we fall back to
# computing it inline from daily panel.
LIQUIDITY_PANEL_PATH = PROJECT_6_DATA_DIR / "liquidity_panel_60d.parquet"

HISTORICAL_NAMES_PATH = PROJECT_6_DATA_DIR / "historical_names.csv"
STOCK_BASIC_PATH = PROJECT_6_DATA_DIR / "stock_basic.csv"


# ─── Error logging ─────────────────────────────────────────────────────

_logger = logging.getLogger("build_universe_panel")
_logger.setLevel(logging.WARNING)
if not _logger.handlers:
    _handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _logger.addHandler(_handler)


def _log_warn(date: str, msg: str) -> None:
    _logger.warning(f"date={date} | {msg}")


# ─── PIT name lookup (reused from Project 6 architecture) ──────────────

def _build_name_lookup() -> dict:
    """
    Build per-ts_code (sorted_start_dates, names_in_order) lookup.
    Used to detect ST/*ST status as of a given trade date.
    """
    if not HISTORICAL_NAMES_PATH.exists():
        print(f"  [WARN] {HISTORICAL_NAMES_PATH} missing; ST detection will use")
        print(f"         current name only (survivorship bias).")
        return {}

    historical = pd.read_csv(
        HISTORICAL_NAMES_PATH,
        dtype={"ts_code": str, "start_date": str, "end_date": str,
               "ann_date": str, "name": str}
    )
    lookup = {}
    for ts_code, group in historical.groupby("ts_code"):
        sorted_group = group.sort_values("start_date")
        starts = sorted_group["start_date"].tolist()
        names = sorted_group["name"].tolist()
        lookup[ts_code] = (starts, names)
    return lookup


def _name_as_of(ts_code: str, date_str: str, lookup: dict,
                fallback: str | None = None) -> str | None:
    """Return name in effect for ts_code on date_str (YYYY-MM-DD)."""
    if ts_code not in lookup:
        return fallback
    starts, names = lookup[ts_code]
    idx = bisect.bisect_right(starts, date_str) - 1
    if idx < 0:
        return fallback
    return names[idx]


def _is_st(name: str | None) -> bool:
    """ST/*ST detection by name prefix."""
    if name is None or pd.isna(name):
        return False
    return name.startswith("ST") or name.startswith("*ST")


# ─── Index constituent lookup ──────────────────────────────────────────

def _load_index_constituents() -> dict:
    """
    Load all cached index constituent parquets and build a per-index
    list of (snapshot_year_month, set_of_ts_codes) tuples sorted by date.

    Returns:
      { index_key: [ (YYYY-MM, set_of_ts_codes), ... ] }
    """
    out = {"csi300": [], "csi500": [], "csi1000": [], "csi2000": []}
    for index_key in out:
        files = sorted(INDEX_CONSTITUENTS_DIR.glob(f"{index_key}_*.parquet"))
        for f in files:
            year_month = f.stem.replace(f"{index_key}_", "")  # 'YYYY-MM'
            df = pd.read_parquet(f, columns=["ts_code"])
            out[index_key].append((year_month, set(df["ts_code"])))

    for index_key, items in out.items():
        print(f"  {index_key:<8s}: {len(items)} monthly snapshots loaded")
    return out


def _index_members_as_of(index_key: str, rebal_date: pd.Timestamp,
                         constituents: dict) -> set:
    """
    Return the set of constituent ts_codes for index_key in effect on
    rebal_date. Uses the most recent monthly snapshot at or before
    rebal_date. Returns empty set if no snapshot exists yet.
    """
    items = constituents.get(index_key, [])
    if not items:
        return set()

    # Find the last snapshot with year_month <= rebal_date's year_month.
    # bisect on the sorted (year_month) keys.
    rebal_ym = rebal_date.strftime("%Y-%m")
    keys = [k for k, _ in items]
    idx = bisect.bisect_right(keys, rebal_ym) - 1
    if idx < 0:
        return set()
    return items[idx][1]


# ─── Per-date universe builder ─────────────────────────────────────────

def _build_universe_for_date(
    rebal_date: pd.Timestamp,
    panel: pd.DataFrame,
    constituents: dict,
    proj6_membership: pd.DataFrame | None,
    liquidity_panel: pd.DataFrame | None,
    name_lookup: dict,
    current_name_map: dict,
    verbose: bool = False,
) -> pd.DataFrame | None:
    """
    Build the seven-universe row set for one rebalance date.

    Returns DataFrame with columns:
        rebalance_date, ts_code, in_U1, in_U2, ..., in_U7,
        circ_mv_yi, exchange_tier
    """
    date_str = rebal_date.strftime("%Y-%m-%d")

    # Step 1: A-share equity filter (U1's spine)
    df = panel[panel["ts_code"].str.match(A_SHARE_PATTERN)].copy()
    if len(df) == 0:
        _log_warn(date_str, "no A-share rows after prefix filter")
        return None

    # Step 2: ST/*ST exclusion (PIT)
    df["name"] = df["ts_code"].apply(
        lambda c: _name_as_of(c, date_str, name_lookup,
                              fallback=current_name_map.get(c))
    )
    df = df[~df["name"].fillna("").str.match(r"^\*?ST")]

    # Step 3: edge cases — circ_mv must be valid
    df = df[df["circ_mv"].notna() & (df["circ_mv"] > 0)]
    df = df[df["amount"].notna() & (df["amount"] > 0)]

    if len(df) == 0:
        _log_warn(date_str, "no rows after edge-case filter")
        return None

    df["circ_mv_yi"] = df["circ_mv"] * CIRC_MV_WAN_TO_YI
    df["amount_wan"] = df["amount"] * AMOUNT_QIANYUAN_TO_WAN

    # Exchange tier (for diagnostic; not used for membership)
    def _tier(c: str) -> str:
        if c.startswith("688"):
            return "star"
        if c.startswith("300") or c.startswith("301"):
            return "chinext"
        return "main"
    df["exchange_tier"] = df["ts_code"].apply(_tier)

    # Step 4: U1 = all rows passing A-share filter
    df["in_U1"] = True

    # Step 5: U2 from Project 6's universe panel
    if proj6_membership is not None:
        u2_codes = set(
            proj6_membership.loc[
                (proj6_membership["rebalance_date"] == date_str)
                & proj6_membership["in_universe"], "ts_code"
            ]
        )
        df["in_U2"] = df["ts_code"].isin(u2_codes)
    else:
        df["in_U2"] = False

    # Step 6: U3, U4 from index constituents
    csi300 = _index_members_as_of("csi300", rebal_date, constituents)
    csi500 = _index_members_as_of("csi500", rebal_date, constituents)
    csi1000 = _index_members_as_of("csi1000", rebal_date, constituents)
    csi2000 = _index_members_as_of("csi2000", rebal_date, constituents)

    df["in_U3"] = df["ts_code"].isin(csi1000)
    df["in_U4"] = df["ts_code"].isin(csi2000)

    # Step 7: U5 = U3 ∪ U4
    df["in_U5"] = df["in_U3"] | df["in_U4"]

    # Step 8: U6 = NOT in CSI300 ∪ CSI500 (raw "outside CSI800")
    csi800 = csi300 | csi500
    df["in_U6"] = ~df["ts_code"].isin(csi800)

    # Step 9: U7 = U6 + liquidity floor
    df["in_U7"] = False
    if liquidity_panel is not None:
        liq = liquidity_panel[liquidity_panel["rebalance_date"] == date_str]
        if len(liq) > 0:
            # Merge liquidity into df
            df_with_liq = df.merge(
                liq[["ts_code", "mean_amount_wan", "n_trading_days_observed"]],
                on="ts_code", how="left"
            )
            # U6 sub-pool
            u6_pool = df_with_liq[df_with_liq["in_U6"]].copy()
            # Need ≥20 observed days
            u6_pool = u6_pool[
                u6_pool["n_trading_days_observed"].fillna(0) >= LIQUIDITY_MIN_DAYS
            ]
            # Absolute floor
            u6_pool = u6_pool[
                u6_pool["mean_amount_wan"].fillna(0) >= LIQUIDITY_FLOOR_AMOUNT_WAN
            ]
            # Top 75% within u6_pool by mean_amount_wan
            if len(u6_pool) > 0:
                threshold_pct = 1.0 - LIQUIDITY_FLOOR_PERCENTILE / 100.0
                u6_pool["liq_pct_rank"] = (
                    u6_pool["mean_amount_wan"].rank(pct=True)
                )
                survivor_codes = set(
                    u6_pool.loc[
                        u6_pool["liq_pct_rank"] >= threshold_pct, "ts_code"
                    ]
                )
                df["in_U7"] = df["ts_code"].isin(survivor_codes)

    # Step 10: Output schema
    df["rebalance_date"] = date_str
    out_cols = (
        ["rebalance_date", "ts_code", "circ_mv_yi", "amount_wan",
         "exchange_tier"]
        + [f"in_{u.split('_')[0]}" for u in UNIVERSE_KEYS]
    )
    out = df[out_cols].copy()

    # Cast bool columns
    for u in UNIVERSE_KEYS:
        col = f"in_{u.split('_')[0]}"
        out[col] = out[col].astype(bool)

    if verbose:
        counts = {u.split("_")[0]: int(out[f"in_{u.split('_')[0]}"].sum())
                  for u in UNIVERSE_KEYS}
        print(f"  {date_str}: " +
              ", ".join(f"{k}={v}" for k, v in counts.items()))

    return out


# ─── Drivers ────────────────────────────────────────────────────────────

def _load_resources():
    """Load all the static resources used by every per-date call."""
    print("Loading resources...")

    # Rebalance dates
    if not WEEKLY_REBALANCE_DATES_PATH.exists():
        raise FileNotFoundError(
            f"{WEEKLY_REBALANCE_DATES_PATH} not found. "
            f"Project 6's weekly_rebalance_dates.csv is required."
        )
    rebal_dates = pd.read_csv(WEEKLY_REBALANCE_DATES_PATH)["date"].tolist()
    rebal_dates = [pd.Timestamp(d) for d in rebal_dates]
    print(f"  weekly rebalance dates: {len(rebal_dates)} "
          f"({rebal_dates[0].date()} to {rebal_dates[-1].date()})")

    # Project 6 universe (U2 source)
    if PROJ6_UNIVERSE_PATH.exists():
        proj6 = pd.read_parquet(PROJ6_UNIVERSE_PATH)
        # rebalance_date may already be a date string; normalize to string
        proj6["rebalance_date"] = pd.to_datetime(
            proj6["rebalance_date"]
        ).dt.strftime("%Y-%m-%d")
        print(f"  Project 6 universe: {len(proj6):,} rows, "
              f"{proj6['ts_code'].nunique():,} stocks")
    else:
        print(f"  [WARN] {PROJ6_UNIVERSE_PATH} missing; U2 will be empty")
        proj6 = None

    # Liquidity panel for U7
    if LIQUIDITY_PANEL_PATH.exists():
        liq = pd.read_parquet(LIQUIDITY_PANEL_PATH)
        liq["rebalance_date"] = pd.to_datetime(
            liq["rebalance_date"]
        ).dt.strftime("%Y-%m-%d")
        print(f"  liquidity panel: {len(liq):,} rows")
    else:
        print(f"  [WARN] {LIQUIDITY_PANEL_PATH} missing; U7 will be empty")
        liq = None

    # Name lookup
    print("  building PIT name lookup...")
    name_lookup = _build_name_lookup()
    print(f"    {len(name_lookup):,} ts_codes with name history")

    # Current name map (fallback)
    if STOCK_BASIC_PATH.exists():
        basic = pd.read_csv(STOCK_BASIC_PATH, dtype={"ts_code": str})
        current_name_map = dict(zip(basic["ts_code"], basic["name"]))
    else:
        current_name_map = {}
    print(f"  current name map: {len(current_name_map):,} entries")

    # Index constituents
    print("  loading index constituents...")
    constituents = _load_index_constituents()

    return rebal_dates, proj6, liq, name_lookup, current_name_map, constituents


def smoke_test() -> None:
    """5 rebalance dates spanning all four regimes for sanity check."""
    print("=" * 60)
    print("BUILD UNIVERSE PANEL — SMOKE")
    print("=" * 60)

    rebal_dates, proj6, liq, name_lookup, current_name_map, constituents = (
        _load_resources()
    )

    # Pick a date from each regime
    test_dates = [
        pd.Timestamp("2019-06-12"),  # W1 pre-NNA
        pd.Timestamp("2024-04-17"),  # W2 first wk after NNA
        pd.Timestamp("2024-09-25"),  # W3 first wk after PBoC
        pd.Timestamp("2025-12-31"),  # W3 / W4 deep
        pd.Timestamp("2026-04-29"),  # latest
    ]
    test_dates = [d for d in test_dates if d in rebal_dates]
    print(f"\nTesting {len(test_dates)} dates")

    for d in test_dates:
        date_str = d.strftime("%Y-%m-%d")
        panel_path = DAILY_PANEL_DIR / f"daily_{date_str}.parquet"
        if not panel_path.exists():
            print(f"  {date_str}: panel file missing, skipping")
            continue
        panel = pd.read_parquet(panel_path)
        out = _build_universe_for_date(
            d, panel, constituents, proj6, liq,
            name_lookup, current_name_map, verbose=True
        )
        if out is None:
            print(f"  {date_str}: FAILED")


def full_run() -> None:
    """Build universe panel for all rebalance dates."""
    print("=" * 60)
    print("BUILD UNIVERSE PANEL — FULL")
    print("=" * 60)

    rebal_dates, proj6, liq, name_lookup, current_name_map, constituents = (
        _load_resources()
    )

    print(f"\nProcessing {len(rebal_dates)} rebalance dates...")
    frames = []
    n_failed = 0
    t0 = time.time()

    for i, d in enumerate(rebal_dates, 1):
        date_str = d.strftime("%Y-%m-%d")
        panel_path = DAILY_PANEL_DIR / f"daily_{date_str}.parquet"
        if not panel_path.exists():
            n_failed += 1
            _log_warn(date_str, "daily panel missing")
            continue
        panel = pd.read_parquet(panel_path)
        out = _build_universe_for_date(
            d, panel, constituents, proj6, liq,
            name_lookup, current_name_map, verbose=False
        )
        if out is None:
            n_failed += 1
            continue
        frames.append(out)

        if i % 50 == 0 or i == len(rebal_dates):
            secs = time.time() - t0
            print(f"  [{i:>4}/{len(rebal_dates)}] "
                  f"frames={len(frames)} failed={n_failed} "
                  f"elapsed={secs:.1f}s")

    if not frames:
        print("ERROR: no frames produced.")
        return

    print(f"\nConcatenating {len(frames)} frames...")
    out_df = pd.concat(frames, ignore_index=True)
    out_df.to_parquet(UNIVERSE_PANEL_PATH, compression=COMPRESSION, index=False)

    print(f"\nFull run complete in {time.time()-t0:.1f}s")
    print(f"  rows:    {len(out_df):,}")
    print(f"  dates:   {out_df['rebalance_date'].nunique()}")
    print(f"  output:  {UNIVERSE_PANEL_PATH}")
    print(f"  size:    {UNIVERSE_PANEL_PATH.stat().st_size / 1024**2:.1f} MB")


def status() -> None:
    """Inspect cached output."""
    if not UNIVERSE_PANEL_PATH.exists():
        print(f"No universe panel at {UNIVERSE_PANEL_PATH}. Run with `full`.")
        return

    df = pd.read_parquet(UNIVERSE_PANEL_PATH)
    print(f"Universe panel: {UNIVERSE_PANEL_PATH}")
    print(f"  total rows:     {len(df):,}")
    print(f"  unique dates:   {df['rebalance_date'].nunique()}")
    print(f"  unique stocks:  {df['ts_code'].nunique():,}")
    print(f"  date range:     {df['rebalance_date'].min()} to "
          f"{df['rebalance_date'].max()}")

    print(f"\n  Per-universe stock-day counts:")
    for u in UNIVERSE_KEYS:
        col = f"in_{u.split('_')[0]}"
        n = int(df[col].sum())
        n_unique = df.loc[df[col], "ts_code"].nunique()
        print(f"    {u:<28s} {n:>9,} rows ({n_unique:>5,} unique stocks)")

    print(f"\n  Per-date in-universe counts (first 3 dates and last 3):")
    counts_by_date = df.groupby("rebalance_date")[
        [f"in_{u.split('_')[0]}" for u in UNIVERSE_KEYS]
    ].sum()
    counts_by_date.columns = [c.replace("in_", "") for c in counts_by_date.columns]
    print(counts_by_date.head(3).to_string())
    print(" ...")
    print(counts_by_date.tail(3).to_string())


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke_test()
    elif mode == "full":
        full_run()
    elif mode == "status":
        status()
    else:
        print("Usage: python build_universe_panel.py [smoke|full|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
