"""
build_three_universes.py — Build the A/B/C three-universe membership panel.

After the seven-way inspection, we settled on U6 (outside-CSI800) as the
candidate base. This script produces three variants:

  A. base:     outside-CSI800 + sub-new exclusion + ST/北交所/退市 filters
  B. price:    A + close ≥ PRICE_FLOOR_RMB on rebalance date
  C. floored:  A + parametrized liquidity floor (default: pct40, abs2000万,
                min_days=20). Pass --floor-pct / --floor-abs / --floor-days
                to sweep.

Output schema
-------------
data/universe_membership_three.parquet keyed on (rebalance_date, ts_code):

    rebalance_date    str YYYY-MM-DD
    ts_code           str
    in_A              bool   member of universe A
    in_B              bool   member of universe B
    in_C              bool   member of universe C
    circ_mv_yi        float32 流通市值 in 亿 RMB
    amount_wan        float32 daily 成交额 in 万 RMB
    close             float32 close on rebalance date
    list_date         str YYYYMMDD (for diagnostics)
    days_since_list   int    trading days since IPO at this rebalance
    exchange_tier     str    main / chinext / star
    excluded_reason   str    if not in any of A/B/C, why; else empty

Filter chain (applied in this order; order matters)
---------------------------------------------------
  1. A-share equity prefix filter (exclude 北交所 entirely)
  2. ST/*ST exclusion (point-in-time via Project 6's name history)
  3. circ_mv > 0 AND amount > 0 (drop suspended-day rows)
  4. Outside-CSI800 (NOT in CSI300 ∪ CSI500 as of most recent monthly
     index snapshot)
  5. Sub-new exclusion (≥ 120 trading days since list_date)
     -> stocks passing 1-5 are in Universe A.
  6. Price floor (close ≥ 1.5元) -> Universe B is A ∩ {close ≥ 1.5}
  7. Liquidity floor on the A pool (parametrized)
     -> Universe C is A ∩ {pct + abs + min_days all pass}

Stocks failing filter 1 don't appear in the output panel at all.
Stocks failing 2-4 are rare-but-possible to inspect; we record their
reason in `excluded_reason` and emit a row so the panel is debuggable.

Delisting handling
------------------
Tushare's `daily` endpoint stops emitting rows for delisted stocks at
their delisting date. So a stock delisted before a rebalance date
simply has no daily-panel row that day and is filtered out by step 3
naturally. 退市整理期 (the 30-day final wind-down) is NOT explicitly
detected; those rows still appear in the daily panel and pass step 3.
Most 退市整理期 stocks are also ST/*ST so they're caught at step 2.
The residual is small and unhandled; documented as a known edge case.

Usage
-----
    python build_three_universes.py smoke               # 5 dates
    python build_three_universes.py full                # all rebalances
    python build_three_universes.py status              # inspect output
    python build_three_universes.py full --floor-pct 0.50 --floor-abs 1500
                                                        # sweep alt params
"""

import argparse
import bisect
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    A_SHARE_PATTERN,
    AMOUNT_QIANYUAN_TO_WAN,
    CIRC_MV_WAN_TO_YI,
    DAILY_PANEL_DIR,
    DEFAULT_LIQUIDITY_FLOOR,
    INDEX_CONSTITUENTS_DIR,
    LiquidityFloorParams,
    PRICE_FLOOR_RMB,
    PROJECT_6_DATA_DIR,
    SUB_NEW_THRESHOLD_TRADING_DAYS,
    THREE_UNIVERSE_KEYS,
    THREE_UNIVERSE_LABELS,
    THREE_UNIVERSE_PANEL_PATH,
    TRADING_CALENDAR_PATH,
    WEEKLY_REBALANCE_DATES_PATH,
)


# ─── Configuration ─────────────────────────────────────────────────────

ERROR_LOG = Path("data") / "errors_build_three.log"
COMPRESSION = "zstd"

# Project 6 inputs we need
LIQUIDITY_PANEL_PATH = PROJECT_6_DATA_DIR / "liquidity_panel_60d.parquet"
HISTORICAL_NAMES_PATH = PROJECT_6_DATA_DIR / "historical_names.csv"
STOCK_BASIC_PATH = PROJECT_6_DATA_DIR / "stock_basic.csv"


# ─── Error logging ─────────────────────────────────────────────────────

_logger = logging.getLogger("build_three_universes")
_logger.setLevel(logging.WARNING)
if not _logger.handlers:
    Path("data").mkdir(exist_ok=True)
    _handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _logger.addHandler(_handler)


def _log_warn(date: str, msg: str) -> None:
    _logger.warning(f"date={date} | {msg}")


# ─── PIT name lookup (same architecture as Project 6) ──────────────────

def _build_name_lookup() -> dict:
    """Per-ts_code (sorted_starts, names) for ST detection."""
    if not HISTORICAL_NAMES_PATH.exists():
        print(f"  [WARN] {HISTORICAL_NAMES_PATH} missing; ST detection")
        print(f"         will use current names only (survivorship bias).")
        return {}
    historical = pd.read_csv(
        HISTORICAL_NAMES_PATH,
        dtype={"ts_code": str, "start_date": str, "end_date": str,
               "ann_date": str, "name": str}
    )
    lookup = {}
    for ts_code, group in historical.groupby("ts_code"):
        sorted_group = group.sort_values("start_date")
        lookup[ts_code] = (
            sorted_group["start_date"].tolist(),
            sorted_group["name"].tolist(),
        )
    return lookup


def _name_as_of(ts_code: str, date_str: str, lookup: dict,
                fallback: str | None = None) -> str | None:
    if ts_code not in lookup:
        return fallback
    starts, names = lookup[ts_code]
    idx = bisect.bisect_right(starts, date_str) - 1
    if idx < 0:
        return fallback
    return names[idx]


def _is_st(name: str | None) -> bool:
    if name is None or pd.isna(name):
        return False
    s = str(name).strip()
    return s.startswith("ST") or s.startswith("*ST")


# ─── Index constituent lookup (CSI800 = CSI300 ∪ CSI500) ───────────────

def _load_index_constituents() -> dict:
    """
    Load CSI300 and CSI500 monthly snapshots from cached parquets.
    CSI1000/CSI2000 not needed here; the U6 definition is "NOT in
    CSI300 ∪ CSI500".
    """
    out = {"csi300": [], "csi500": []}
    for index_key in out:
        files = sorted(INDEX_CONSTITUENTS_DIR.glob(f"{index_key}_*.parquet"))
        for f in files:
            year_month = f.stem.replace(f"{index_key}_", "")
            df = pd.read_parquet(f, columns=["ts_code"])
            out[index_key].append((year_month, set(df["ts_code"])))
    for k, items in out.items():
        print(f"  {k:<8s}: {len(items)} monthly snapshots loaded")
    return out


def _csi800_as_of(rebal_date: pd.Timestamp, constituents: dict) -> set:
    """CSI300 ∪ CSI500 in effect on rebal_date (most recent month-end ≤ rebal)."""
    out: set = set()
    rebal_ym = rebal_date.strftime("%Y-%m")
    for index_key in ("csi300", "csi500"):
        items = constituents.get(index_key, [])
        if not items:
            continue
        keys = [k for k, _ in items]
        idx = bisect.bisect_right(keys, rebal_ym) - 1
        if idx >= 0:
            out |= items[idx][1]
    return out


# ─── Sub-new (trading-days-since-list) lookup ──────────────────────────

def _build_list_date_map() -> dict:
    """ts_code -> list_date (YYYYMMDD) from stock_basic.csv."""
    if not STOCK_BASIC_PATH.exists():
        print(f"  [WARN] {STOCK_BASIC_PATH} missing; sub-new exclusion")
        print(f"         cannot be applied.")
        return {}
    basic = pd.read_csv(STOCK_BASIC_PATH, dtype={"ts_code": str, "list_date": str})
    return dict(zip(basic["ts_code"], basic["list_date"]))


def _build_calendar_index_map() -> dict:
    """YYYYMMDD -> position in trading calendar, for fast trading-day diffs."""
    cal = pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()
    # Calendar entries are YYYY-MM-DD; convert to YYYYMMDD for matching
    # against list_date (which Tushare returns as YYYYMMDD).
    return {d.replace("-", ""): i for i, d in enumerate(cal)}


def _trading_days_since_list(ts_code: str, rebal_date_str: str,
                              list_date_map: dict, cal_idx: dict) -> int | None:
    """
    Trading days between list_date and rebal_date (exclusive of list day).
    Returns None if list_date unknown or either date not in calendar.
    """
    list_date = list_date_map.get(ts_code)
    if list_date is None or pd.isna(list_date):
        return None
    list_pos = cal_idx.get(list_date)
    rebal_pos = cal_idx.get(rebal_date_str.replace("-", ""))
    if list_pos is None or rebal_pos is None:
        return None
    return rebal_pos - list_pos


# ─── Per-date universe builder ─────────────────────────────────────────

def _build_for_date(
    rebal_date: pd.Timestamp,
    panel: pd.DataFrame,
    constituents: dict,
    liquidity_panel: pd.DataFrame | None,
    name_lookup: dict,
    current_name_map: dict,
    list_date_map: dict,
    cal_idx: dict,
    floor_params: LiquidityFloorParams,
    verbose: bool = False,
) -> pd.DataFrame | None:
    """
    Apply the 7-step filter chain for one rebalance date and return
    a long-format DataFrame with in_A / in_B / in_C bool columns.
    """
    date_str = rebal_date.strftime("%Y-%m-%d")

    # Step 1: A-share equity prefix
    df = panel[panel["ts_code"].str.match(A_SHARE_PATTERN)].copy()
    if len(df) == 0:
        _log_warn(date_str, "no A-share rows after prefix filter")
        return None
    df["excluded_reason"] = ""

    # Step 2: ST/*ST exclusion (PIT)
    df["name"] = df["ts_code"].apply(
        lambda c: _name_as_of(c, date_str, name_lookup,
                              fallback=current_name_map.get(c))
    )
    is_st = df["name"].apply(_is_st)
    df.loc[is_st, "excluded_reason"] = "st"

    # Step 3: valid trading data
    valid_data = (
        df["circ_mv"].notna() & (df["circ_mv"] > 0)
        & df["amount"].notna() & (df["amount"] > 0)
        & df["close"].notna() & (df["close"] > 0)
    )
    df.loc[~valid_data & (df["excluded_reason"] == ""), "excluded_reason"] = "invalid_data"

    # Convenience columns
    df["circ_mv_yi"] = df["circ_mv"] * CIRC_MV_WAN_TO_YI
    df["amount_wan"] = df["amount"] * AMOUNT_QIANYUAN_TO_WAN

    # Exchange tier (diagnostic)
    def _tier(c: str) -> str:
        if c.startswith("688"): return "star"
        if c.startswith("300") or c.startswith("301"): return "chinext"
        return "main"
    df["exchange_tier"] = df["ts_code"].apply(_tier)

    # Step 4: outside CSI800
    csi800 = _csi800_as_of(rebal_date, constituents)
    in_csi800 = df["ts_code"].isin(csi800)
    df.loc[in_csi800 & (df["excluded_reason"] == ""), "excluded_reason"] = "in_csi800"

    # Step 5: sub-new exclusion (≥ 120 trading days since list_date)
    df["list_date"] = df["ts_code"].map(list_date_map)
    df["days_since_list"] = df["ts_code"].apply(
        lambda c: _trading_days_since_list(c, date_str, list_date_map, cal_idx)
    )
    too_new = df["days_since_list"].apply(
        lambda d: (d is None) or (d < SUB_NEW_THRESHOLD_TRADING_DAYS)
    )
    # Don't overwrite earlier reasons; only mark stocks that survived 1-4
    df.loc[too_new & (df["excluded_reason"] == ""), "excluded_reason"] = "sub_new"

    # Universe A: passed steps 1-5
    df["in_A"] = df["excluded_reason"] == ""

    # Step 6: price floor (only computed for A)
    df["in_B"] = df["in_A"] & (df["close"].fillna(0) >= PRICE_FLOOR_RMB)

    # Step 7: liquidity floor (only computed for A)
    df["in_C"] = False
    if liquidity_panel is not None:
        liq = liquidity_panel[liquidity_panel["rebalance_date"] == date_str]
        if len(liq) > 0:
            a_pool = df[df["in_A"]].merge(
                liq[["ts_code", "mean_amount_wan", "n_trading_days_observed"]],
                on="ts_code", how="left",
            )
            # min_days
            a_pool = a_pool[
                a_pool["n_trading_days_observed"].fillna(0) >= floor_params.min_days
            ]
            # absolute floor
            a_pool = a_pool[
                a_pool["mean_amount_wan"].fillna(0) >= floor_params.abs_threshold_wan
            ]
            # percentile floor (computed within A_pool ∩ {min_days+abs})
            if len(a_pool) > 0:
                a_pool["liq_pct_rank"] = a_pool["mean_amount_wan"].rank(pct=True)
                # Keep top X% means rank ≥ (1 - X)
                survivors = set(a_pool.loc[
                    a_pool["liq_pct_rank"] >= (1.0 - floor_params.pct_threshold),
                    "ts_code"
                ])
                df["in_C"] = df["ts_code"].isin(survivors)
        else:
            _log_warn(date_str, "no liquidity panel rows for date; in_C stays False")

    # Final shape
    df["rebalance_date"] = date_str
    out_cols = [
        "rebalance_date", "ts_code",
        "in_A", "in_B", "in_C",
        "circ_mv_yi", "amount_wan", "close",
        "list_date", "days_since_list",
        "exchange_tier", "excluded_reason",
    ]
    out = df[out_cols].copy()
    for c in ("in_A", "in_B", "in_C"):
        out[c] = out[c].astype(bool)
    out["circ_mv_yi"] = out["circ_mv_yi"].astype("float32")
    out["amount_wan"] = out["amount_wan"].astype("float32")
    out["close"] = out["close"].astype("float32")

    if verbose:
        n_a = int(out["in_A"].sum())
        n_b = int(out["in_B"].sum())
        n_c = int(out["in_C"].sum())
        # Reason breakdown for diagnostics
        reasons = df["excluded_reason"].value_counts().to_dict()
        print(f"  {date_str}: A={n_a}, B={n_b}, C={n_c}")
        print(f"    exclusion reasons: {dict(sorted(reasons.items()))}")

    return out


# ─── Drivers ────────────────────────────────────────────────────────────

def _load_resources():
    """Static resources used by every per-date call."""
    print("Loading resources...")

    if not WEEKLY_REBALANCE_DATES_PATH.exists():
        raise FileNotFoundError(
            f"{WEEKLY_REBALANCE_DATES_PATH} missing. "
            f"Project 6 weekly_rebalance_dates.csv required."
        )
    rebal_dates = [pd.Timestamp(d) for d in pd.read_csv(
        WEEKLY_REBALANCE_DATES_PATH
    )["date"].tolist()]
    print(f"  weekly rebalance dates: {len(rebal_dates)} "
          f"({rebal_dates[0].date()} to {rebal_dates[-1].date()})")

    if LIQUIDITY_PANEL_PATH.exists():
        liq = pd.read_parquet(LIQUIDITY_PANEL_PATH)
        liq["rebalance_date"] = pd.to_datetime(
            liq["rebalance_date"]
        ).dt.strftime("%Y-%m-%d")
        print(f"  liquidity panel: {len(liq):,} rows")
    else:
        print(f"  [WARN] {LIQUIDITY_PANEL_PATH} missing; Universe C will be empty")
        liq = None

    print("  building PIT name lookup...")
    name_lookup = _build_name_lookup()
    print(f"    {len(name_lookup):,} ts_codes")

    if STOCK_BASIC_PATH.exists():
        basic = pd.read_csv(STOCK_BASIC_PATH, dtype={"ts_code": str})
        current_name_map = dict(zip(basic["ts_code"], basic["name"]))
    else:
        current_name_map = {}
    print(f"  current name map: {len(current_name_map):,} entries")

    print("  loading list_date map for sub-new exclusion...")
    list_date_map = _build_list_date_map()
    print(f"    {len(list_date_map):,} ts_codes with list_date")

    print("  building calendar index...")
    cal_idx = _build_calendar_index_map()
    print(f"    {len(cal_idx):,} trading days indexed")

    print("  loading index constituents (CSI300, CSI500)...")
    constituents = _load_index_constituents()

    return (rebal_dates, liq, name_lookup, current_name_map,
            list_date_map, cal_idx, constituents)


def smoke_test(floor_params: LiquidityFloorParams) -> None:
    print("=" * 60)
    print("BUILD THREE UNIVERSES — SMOKE")
    print(f"  floor params: {floor_params}")
    print("=" * 60)

    (rebal_dates, liq, name_lookup, current_name_map,
     list_date_map, cal_idx, constituents) = _load_resources()

    # Pick dates spanning regimes
    test_dates = [
        pd.Timestamp("2019-06-12"),  # β early
        pd.Timestamp("2022-09-28"),  # β mid
        pd.Timestamp("2024-04-17"),  # γ first week
        pd.Timestamp("2024-09-25"),  # γ post-PBoC first week
        pd.Timestamp("2026-04-29"),  # γ latest
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
        out = _build_for_date(
            d, panel, constituents, liq, name_lookup,
            current_name_map, list_date_map, cal_idx,
            floor_params, verbose=True,
        )
        if out is None:
            print(f"  {date_str}: FAILED")


def full_run(floor_params: LiquidityFloorParams,
             output_path: Path = THREE_UNIVERSE_PANEL_PATH) -> None:
    print("=" * 60)
    print("BUILD THREE UNIVERSES — FULL")
    print(f"  floor params: {floor_params}")
    print(f"  output:       {output_path}")
    print("=" * 60)

    (rebal_dates, liq, name_lookup, current_name_map,
     list_date_map, cal_idx, constituents) = _load_resources()

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
        out = _build_for_date(
            d, panel, constituents, liq, name_lookup,
            current_name_map, list_date_map, cal_idx,
            floor_params, verbose=False,
        )
        if out is None:
            n_failed += 1
            continue
        frames.append(out)

        if i % 50 == 0 or i == len(rebal_dates):
            secs = time.time() - t0
            print(f"  [{i:>4}/{len(rebal_dates)}] frames={len(frames)} "
                  f"failed={n_failed} elapsed={secs:.1f}s")

    if not frames:
        print("ERROR: no frames produced.")
        return

    print(f"\nConcatenating {len(frames)} frames...")
    out_df = pd.concat(frames, ignore_index=True)
    out_df.to_parquet(output_path, compression=COMPRESSION, index=False)

    print(f"\nFull run complete in {time.time()-t0:.1f}s")
    print(f"  rows:   {len(out_df):,}")
    print(f"  dates:  {out_df['rebalance_date'].nunique()}")
    print(f"  output: {output_path}")
    print(f"  size:   {output_path.stat().st_size / 1024**2:.1f} MB")

    # Quick summary by universe
    print(f"\nPer-universe membership counts (across all dates):")
    for u in THREE_UNIVERSE_KEYS:
        col = f"in_{u.split('_')[0]}"
        n = int(out_df[col].sum())
        n_unique = out_df.loc[out_df[col], "ts_code"].nunique()
        n_dates = out_df.loc[out_df[col], "rebalance_date"].nunique()
        print(f"  {u:<18s} {n:>9,} rows  "
              f"({n_unique:,} unique stocks across {n_dates} dates)")

    # Mean per-date counts
    print(f"\nMean per-date membership:")
    for u in THREE_UNIVERSE_KEYS:
        col = f"in_{u.split('_')[0]}"
        mean_n = out_df.groupby("rebalance_date")[col].sum().mean()
        print(f"  {u:<18s} mean {mean_n:.0f} stocks/date")


def status() -> None:
    if not THREE_UNIVERSE_PANEL_PATH.exists():
        print(f"No universe panel at {THREE_UNIVERSE_PANEL_PATH}.")
        print(f"Run with `full`.")
        return

    df = pd.read_parquet(THREE_UNIVERSE_PANEL_PATH)
    print(f"Three-universe panel: {THREE_UNIVERSE_PANEL_PATH}")
    print(f"  rows:    {len(df):,}")
    print(f"  dates:   {df['rebalance_date'].nunique()}")
    print(f"  stocks:  {df['ts_code'].nunique():,}")
    print(f"  range:   {df['rebalance_date'].min()} to "
          f"{df['rebalance_date'].max()}")

    print(f"\n  Per-universe membership:")
    for u in THREE_UNIVERSE_KEYS:
        col = f"in_{u.split('_')[0]}"
        n = int(df[col].sum())
        n_unique = df.loc[df[col], "ts_code"].nunique()
        mean_n = df.groupby("rebalance_date")[col].sum().mean()
        print(f"    {THREE_UNIVERSE_LABELS[u]:<55s} "
              f"{n:>9,} rows  (mean {mean_n:.0f}/date, {n_unique:,} unique)")

    print(f"\n  Exclusion reasons (across all candidate-pool rows):")
    reasons = df["excluded_reason"].value_counts()
    for reason, count in reasons.items():
        label = "(passed all filters)" if reason == "" else reason
        print(f"    {label:<25s} {count:>10,} ({100*count/len(df):.1f}%)")

    # Sub-new diagnostic
    if "days_since_list" in df.columns:
        print(f"\n  Sub-new diagnostic:")
        sub_new_mask = df["days_since_list"].fillna(0) < 120
        print(f"    rows with <120 trading days since IPO: "
              f"{int(sub_new_mask.sum()):,} "
              f"({100*sub_new_mask.mean():.2f}%)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["smoke", "full", "status"])
    ap.add_argument("--floor-pct", type=float,
                    default=DEFAULT_LIQUIDITY_FLOOR.pct_threshold,
                    help="C: percentile threshold (top X%%)")
    ap.add_argument("--floor-abs", type=int,
                    default=DEFAULT_LIQUIDITY_FLOOR.abs_threshold_wan,
                    help="C: absolute threshold in 万元")
    ap.add_argument("--floor-days", type=int,
                    default=DEFAULT_LIQUIDITY_FLOOR.min_days,
                    help="C: minimum observed trading days in 60-day window")
    args = ap.parse_args()

    floor_params = LiquidityFloorParams(
        pct_threshold=args.floor_pct,
        abs_threshold_wan=args.floor_abs,
        min_days=args.floor_days,
    )

    if args.mode == "smoke":
        smoke_test(floor_params)
    elif args.mode == "full":
        full_run(floor_params)
    elif args.mode == "status":
        status()


if __name__ == "__main__":
    main()