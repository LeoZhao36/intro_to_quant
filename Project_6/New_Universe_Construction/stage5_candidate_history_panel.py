"""
stage5_candidate_history_panel.py — Stage 5: full daily history for the union
of every weekly universe.

This is the architectural fix for the universe-turnover bias that produced
19.9% FMB coverage in Project 6. The mechanism:

  Project 6's factor pipelines read from forward_return_panel.csv, which
  is restricted to rows where in_universe=True at the date being scored.
  When a stock entered the universe at date t, its row at date t-12 did
  not exist in the file, so its 12-month formation window had no data
  even though the stock was traded and its data was pullable.

  Stage 5 fixes this by building a separate panel: for every stock that
  has EVER been in the universe across all weekly rebalances (the
  "candidate pool", typically ~4,000 stocks), extract its full daily
  history (close, adj_factor, amount, pe_ttm, sector, etc.) from the
  Stage 0 daily panel. The factor pipeline reads from this for signal
  computation, and merges with the in-universe filter only at the
  cross-sectional sort step.

  Result: stocks that were not in-universe at the formation start now
  have measurable factor values, lifting coverage from ~20% to ~70-80%.

Inputs
------
  data/daily_panel/                     Stage 0 unified daily panel
  data/universe_membership_X75_Y3000.parquet  Stage 3 universe panel
  data/sw_membership.csv                Stage 4 sector membership

Output
------
  data/candidate_history_panel.parquet  one row per (ts_code, trade_date)
                                         for every stock that has ever
                                         been in the universe, across the
                                         full panel date range.

Schema
------
  trade_date, ts_code, close, adj_factor, amount, turnover_rate, vol,
  pe_ttm, pb, total_share, float_share, total_mv, circ_mv, circ_mv_yi,
  l1_name, l2_name, l3_name

  Sector fields (l1_name, l2_name, l3_name) are filled point-in-time:
  the sector AS OF trade_date, based on Stage 4 in_date / out_date.

API calls: zero.

Usage
-----
    python stage5_candidate_history_panel.py smoke   # 5 stocks, verbose
    python stage5_candidate_history_panel.py full    # full panel
    python stage5_candidate_history_panel.py status  # inspect output
"""

import bisect
import logging
import sys
import time
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass


DATA_DIR = Path("data")
PANEL_DIR = DATA_DIR / "daily_panel"
UNIVERSE_PATH = DATA_DIR / "universe_membership_X75_Y3000.parquet"
SECTOR_PATH = DATA_DIR / "sw_membership.csv"
TRADING_CALENDAR_PATH = DATA_DIR / "trading_calendar.csv"
OUTPUT_PATH = DATA_DIR / "candidate_history_panel.parquet"
ERROR_LOG = DATA_DIR / "errors_stage5_history.log"

DATA_DIR.mkdir(exist_ok=True)

# We keep daily history for the full Stage 0 panel range, so factors with
# 12-month formation windows on early-2019 rebalance dates have full
# pre-2019 history available.
HISTORY_START = "2018-01-01"

COMPRESSION = "zstd"


_logger = logging.getLogger("stage5_history")
_logger.setLevel(logging.WARNING)
_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
_logger.addHandler(_handler)


def _log_warn(ts_code, msg):
    _logger.warning(f"ts_code={ts_code} | {msg}")


def get_candidate_pool():
    """
    Return the set of all ts_codes that were in_universe on at least one
    rebalance date across the panel. This is the candidate pool whose
    history we extract.
    """
    if not UNIVERSE_PATH.exists():
        raise FileNotFoundError(f"{UNIVERSE_PATH} not found. Run Stage 3 full first.")

    universe = pd.read_parquet(UNIVERSE_PATH, columns=["ts_code", "in_universe"])
    pool = set(universe.loc[universe["in_universe"], "ts_code"].unique())
    print(f"  candidate pool: {len(pool):,} unique stocks "
          f"(union of in_universe across all rebalances)")
    return pool


def load_sector_lookup():
    """
    Load Stage 4 sector membership and build a point-in-time lookup.

    For each ts_code, store sorted (in_date, out_date, l1_name, l2_name,
    l3_name) tuples. Lookup at date d returns the sector tuple where
    in_date <= d AND (out_date is NULL OR out_date > d).
    """
    if not SECTOR_PATH.exists():
        print(f"  [WARN] {SECTOR_PATH} not found. Run Stage 4 first.")
        print(f"  Sector fields will be NaN.")
        return {}

    sw = pd.read_csv(
        SECTOR_PATH,
        dtype={"ts_code": str, "in_date": str, "out_date": str}
    )
    print(f"  sector membership: {len(sw):,} rows for "
          f"{sw['ts_code'].nunique():,} unique stocks")

    # Group by ts_code and build lookup
    lookup = {}
    for ts_code, group in sw.groupby("ts_code"):
        # Sort by in_date so bisect works correctly
        sorted_group = group.sort_values("in_date")
        records = []
        for _, row in sorted_group.iterrows():
            records.append((
                row["in_date"],
                row.get("out_date"),
                row.get("l1_name"),
                row.get("l2_name"),
                row.get("l3_name"),
            ))
        lookup[ts_code] = records
    print(f"  built sector lookup for {len(lookup):,} ts_codes")
    return lookup


def sector_as_of(ts_code, date_str, lookup):
    """
    Return (l1_name, l2_name, l3_name) for ts_code on date_str.

    Lookup logic:
      1. Find the latest record with in_date <= date_str AND
         (out_date is NULL OR out_date > date_str). Strict point-in-time match.
      2. If no PIT match exists (e.g., date_str is before the earliest
         in_date in our records), fall back to the EARLIEST record. This
         handles the common case where SW classification data was added
         to the database after our panel start: the stock has been in
         the same sector all along, but the recorded in_date is when SW
         started tracking it, not when it actually changed sectors.

    Date format: both in_date/out_date and date_str are 'YYYYMMDD' strings,
    so lexicographic string comparison gives correct chronological ordering.
    """
    if ts_code not in lookup:
        return (None, None, None)
    records = lookup[ts_code]

    # Strict PIT pass: most recent record where in_date <= date AND
    # (out_date is NULL OR out_date > date).
    for in_date, out_date, l1, l2, l3 in reversed(records):
        if in_date and in_date <= date_str:
            if out_date is None or pd.isna(out_date) or out_date > date_str:
                return (l1, l2, l3)

    # Backward-fill fallback: if date_str is before any recorded in_date,
    # use the earliest record. The risk (sector reclassification before
    # SW started tracking the stock) affects rare cases and is documented.
    if records:
        _, _, l1, l2, l3 = records[0]
        return (l1, l2, l3)

    return (None, None, None)


def get_trading_calendar():
    return pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()


def build_history_panel(candidate_pool, sector_lookup, calendar,
                       verbose=False):
    """
    Read every daily panel parquet and filter to the candidate pool.
    Concatenate. Add point-in-time sector fields. Return the full panel.

    Reading 2,018 parquets and concatenating is the bottleneck here.
    Each parquet is small (~360KB) and reads in ~5-15ms; total wall
    time is ~30-90 seconds.
    """
    print(f"\n  reading {len(calendar)} daily panels and filtering to "
          f"candidate pool...")

    # Columns to preserve from the daily panel. Keep everything factor
    # pipelines might want; sector fields are added after the merge.
    KEEP_COLS = [
        "trade_date", "ts_code", "close", "adj_factor", "amount",
        "turnover_rate", "vol", "pe_ttm", "pb", "total_share",
        "float_share", "total_mv", "circ_mv",
    ]

    frames = []
    t0 = time.time()
    n_dropped = 0
    for i, date in enumerate(calendar, 1):
        if date < HISTORY_START:
            continue
        path = PANEL_DIR / f"daily_{date}.parquet"
        if not path.exists():
            n_dropped += 1
            continue
        df = pd.read_parquet(path, columns=KEEP_COLS)
        # Filter to candidate pool only (this is the data shrink)
        df = df[df["ts_code"].isin(candidate_pool)]
        if len(df) > 0:
            frames.append(df)

        if verbose and (i % 200 == 0 or i == len(calendar)):
            secs = time.time() - t0
            n_so_far = sum(len(f) for f in frames)
            print(f"    [{i}/{len(calendar)}] rows accumulated: "
                  f"{n_so_far:,}, elapsed: {secs:.1f}s")

    if not frames:
        print("ERROR: no rows produced.")
        return None

    print(f"\n  concatenating {len(frames)} per-date frames...")
    panel = pd.concat(frames, ignore_index=True)
    if n_dropped > 0:
        print(f"  [WARN] {n_dropped} daily panels missing from "
              f"data/daily_panel/ (likely outside HISTORY_START).")

    print(f"  panel before sector merge: {len(panel):,} rows, "
          f"{panel['ts_code'].nunique():,} unique stocks")

    # circ_mv_yi convenience column (亿 RMB)
    panel["circ_mv_yi"] = (panel["circ_mv"] / 10_000.0).astype("float32")

    # Add point-in-time sector fields. This is the slowest step because
    # it's a per-row Python lookup. Vectorize by building a (ts_code,
    # date) -> sector mapping for unique pairs only.
    print(f"\n  adding point-in-time sector fields...")
    t0 = time.time()
    unique_pairs = panel[["ts_code", "trade_date"]].drop_duplicates()
    print(f"    unique (ts_code, date) pairs: {len(unique_pairs):,}")

    # Build sector mapping per unique pair
    sectors = unique_pairs.apply(
        lambda r: sector_as_of(r["ts_code"], r["trade_date"], sector_lookup),
        axis=1, result_type="expand"
    )
    sectors.columns = ["l1_name", "l2_name", "l3_name"]
    pairs_with_sectors = pd.concat([unique_pairs.reset_index(drop=True),
                                     sectors.reset_index(drop=True)], axis=1)

    # Merge back to panel
    panel = panel.merge(pairs_with_sectors, on=["ts_code", "trade_date"],
                        how="left")
    secs = time.time() - t0
    print(f"    sector merge done in {secs:.1f}s")

    # Coverage check
    n_with_l1 = int(panel["l1_name"].notna().sum())
    print(f"  rows with L1 sector: {n_with_l1:,} of {len(panel):,} "
          f"({100*n_with_l1/len(panel):.1f}%)")

    return panel


# ==========================================================
# Drivers
# ==========================================================

def smoke_test():
    print("=" * 60)
    print(f"STAGE 5 SMOKE: history panel for 5 sample stocks")
    print("=" * 60)

    candidate_pool = get_candidate_pool()
    sample_stocks = sorted(list(candidate_pool))[:5]
    print(f"\n  sample stocks: {sample_stocks}")

    sector_lookup = load_sector_lookup()
    calendar = get_trading_calendar()

    # Filter pool to just the smoke sample for the smoke test
    panel = build_history_panel(set(sample_stocks), sector_lookup, calendar,
                                verbose=False)
    if panel is None:
        return

    print(f"\nSmoke result:")
    print(f"  total rows:  {len(panel):,}")
    print(f"  date range:  {panel['trade_date'].min()} to {panel['trade_date'].max()}")
    print(f"\nSample of rows:")
    print(panel.head(10)[["trade_date", "ts_code", "close", "circ_mv_yi",
                          "pe_ttm", "l1_name"]].to_string())


def full_run():
    print(f"STAGE 5 FULL: candidate history panel")
    candidate_pool = get_candidate_pool()
    sector_lookup = load_sector_lookup()
    calendar = get_trading_calendar()

    panel = build_history_panel(candidate_pool, sector_lookup, calendar,
                                verbose=True)
    if panel is None:
        return

    print(f"\n  writing -> {OUTPUT_PATH} (this may take a moment)...")
    panel.to_parquet(OUTPUT_PATH, compression=COMPRESSION, index=False)

    print(f"\nFull run done.")
    print(f"  total rows:                {len(panel):,}")
    print(f"  unique stocks:             {panel['ts_code'].nunique():,}")
    print(f"  unique trading days:       {panel['trade_date'].nunique():,}")
    print(f"  output:                    {OUTPUT_PATH}")
    print(f"  file size:                 "
          f"{OUTPUT_PATH.stat().st_size / (1024*1024):.1f} MB")


def status():
    if not OUTPUT_PATH.exists():
        print(f"No history panel at {OUTPUT_PATH}. Run with `full`.")
        return

    panel = pd.read_parquet(OUTPUT_PATH)
    print(f"Candidate history panel: {OUTPUT_PATH}")
    print(f"  rows:               {len(panel):,}")
    print(f"  unique stocks:      {panel['ts_code'].nunique():,}")
    print(f"  unique dates:       {panel['trade_date'].nunique():,}")
    print(f"  date range:         {panel['trade_date'].min()} to "
          f"{panel['trade_date'].max()}")
    print(f"  file size:          "
          f"{OUTPUT_PATH.stat().st_size / (1024*1024):.1f} MB")

    # Per-stock coverage stats
    per_stock = panel.groupby("ts_code").size()
    print(f"\n  Per-stock row count:")
    print(f"    mean:    {per_stock.mean():.0f}")
    print(f"    median:  {int(per_stock.median())}")
    print(f"    min:     {int(per_stock.min())}")
    print(f"    max:     {int(per_stock.max())}")

    # Coverage of fields
    print(f"\n  Field coverage (non-null fraction):")
    for col in ["close", "adj_factor", "amount", "pe_ttm", "circ_mv",
                "l1_name"]:
        nn = panel[col].notna().sum()
        print(f"    {col:<14} {100*nn/len(panel):>5.1f}%  "
              f"({nn:,} of {len(panel):,})")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke_test()
    elif mode == "full":
        full_run()
    elif mode == "status":
        status()
    else:
        print(f"Usage: python stage5_candidate_history_panel.py [smoke|full|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()