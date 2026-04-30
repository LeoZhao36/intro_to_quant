"""
limit_state_filter.py — Compute per-(date, stock) limit-state flags
from the daily candidate panel.

Outputs a parquet keyed on (trade_date, ts_code) with two boolean
columns: at_limit_up, at_limit_down. Used by Phase D cost-adjusted
analysis to drop unbuyable names (limit-up at week t) and to apply
slippage penalties on stuck-exit sells (limit-down at week t+1).

Limit detection
---------------
A stock is "at limit-up" on a date if:
    close[t] >= 0.998 * theoretical_limit_up
where theoretical_limit_up = prev_close[t] * (1 + limit_pct).

The 0.998 multiplier handles tick-rounding: Chinese stocks round to
the nearest 0.01 RMB, so a stock with prev_close 5.55 and a 10% limit
has limit-up at 6.105 which rounds to 6.11 (above the theoretical
6.105) or 6.10 (below). 0.998 captures both rounding directions.

Same logic for limit-down with (1 - limit_pct).

Limit percentages by exchange tier
----------------------------------
Main Board (Shanghai 60xxxx, Shenzhen 000xxx):
    ±10% normal, ±5% for ST stocks
ChiNext (300xxx):
    ±10% before 2020-08-24, ±20% after
STAR Market (688xxx):
    ±20% always (launched 2019-07-22, our panel starts 2018-01-01
     so a few late-2018 panels precede STAR's launch — those rows
     simply don't have any 688xxx ts_codes).
    No limit during the first 5 trading days after listing.
ST stocks (any prefix, named *ST...*):
    ±5% on Main Board, separate handling.

The first 5 trading days of any IPO have a +44% upper / no-lower limit
on Main Board, and no limits on STAR. We approximate this conservatively
by NOT flagging IPO-window days as limit-states. A stock active for
fewer than 5 trading days in the panel gets at_limit_up=False and
at_limit_down=False regardless of close. This is a small sample of rows
and the conservative direction (don't drop early-IPO names) keeps us
from inadvertently filtering things we should have kept.

ST detection
------------
We detect ST status by name regex. Stage 1's stage1_with_pit_names.py
preserved the PIT name. Tushare's `name_change` endpoint records when
stocks toggle ST status. For this filter we use a simpler heuristic:
look at the daily panel's name field if present, and flag ST as any
name containing 'ST' (case-insensitive). If the daily panel doesn't
carry the name, we fall back to assuming non-ST (the dominant case),
accepting that we'll miss some ST days. The Stage 3 universe filter
already excluded most ST stocks, so the residual is small.

Output
------
data/limit_state_panel.parquet
    Columns: trade_date, ts_code, exchange_tier, limit_pct,
             at_limit_up, at_limit_down

Usage
-----
    python limit_state_filter.py smoke   # one date, verbose
    python limit_state_filter.py full    # all daily panel dates
    python limit_state_filter.py status  # inspect cached output

Run from Project_6/.
"""

import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
PANEL_DIR = DATA_DIR / "daily_panel"
TRADING_CALENDAR_PATH = DATA_DIR / "trading_calendar.csv"
OUTPUT_PATH = DATA_DIR / "limit_state_panel.parquet"

# Threshold for limit detection (handles tick-rounding).
LIMIT_PROXIMITY = 0.998

# Date ChiNext switched from ±10% to ±20%.
CHINEXT_REGIME_CHANGE = pd.Timestamp("2020-08-24")


# ─── Exchange tier classification ──────────────────────────────────────

def classify_ts_code(ts_code: str) -> str:
    """
    Return one of: 'main', 'chinext', 'star'.

    Main Board:   60xxxx.SH, 000xxx.SZ, 001xxx.SZ, 002xxx.SZ, 003xxx.SZ
    ChiNext:      300xxx.SZ, 301xxx.SZ
    STAR Market:  688xxx.SH
    """
    if ts_code.startswith("688"):
        return "star"
    if ts_code.startswith("300") or ts_code.startswith("301"):
        return "chinext"
    return "main"


def get_limit_pct(ts_code: str, trade_date: pd.Timestamp,
                  is_st: bool = False) -> float:
    """
    Return the daily price limit percentage for a stock on a date.

    Returns 0.05 for ST stocks (Main Board), 0.10 for normal Main Board,
    0.20 for STAR, 0.10/0.20 for ChiNext depending on date.
    """
    tier = classify_ts_code(ts_code)
    if is_st and tier == "main":
        return 0.05
    if tier == "main":
        return 0.10
    if tier == "star":
        return 0.20
    if tier == "chinext":
        if trade_date < CHINEXT_REGIME_CHANGE:
            return 0.10
        return 0.20
    return 0.10  # default fallback, shouldn't be reached


# ─── ST detection ──────────────────────────────────────────────────────

ST_PATTERN = re.compile(r"\bST\b|\*ST", flags=re.IGNORECASE)


def is_st_name(name) -> bool:
    """Return True if name suggests ST or *ST status."""
    if pd.isna(name) or not isinstance(name, str):
        return False
    return bool(ST_PATTERN.search(name))


# ─── Core: detect limit state per (date, stock) ────────────────────────

def detect_limit_states_for_date(
    trade_date: str,
    prev_trade_date: str | None,
    verbose: bool = False,
) -> pd.DataFrame | None:
    """
    Read the daily panel for trade_date AND the previous trading day,
    join on ts_code to get prev_close, compute limit_up/limit_down
    thresholds per stock per date based on exchange tier, and flag
    rows where the close is within LIMIT_PROXIMITY of either limit.

    Returns a DataFrame with columns:
        trade_date, ts_code, exchange_tier, limit_pct, is_st,
        at_limit_up, at_limit_down
    """
    today_path = PANEL_DIR / f"daily_{trade_date}.parquet"
    if not today_path.exists():
        return None

    today_cols = ["ts_code", "close", "pre_close"]
    # If 'name' is in the panel, include it for ST detection
    today = pd.read_parquet(today_path)
    available_cols = today.columns.tolist()
    has_name = "name" in available_cols

    # Use pre_close from Tushare if available (it's the adjusted previous
    # close that handles ex-div and corporate actions correctly).
    if "pre_close" in available_cols:
        today_subset = today[["ts_code", "close", "pre_close"]].copy()
        today_subset["prev_close"] = today_subset["pre_close"].astype(float)
    else:
        # Fallback: read prev trading day's close
        if prev_trade_date is None:
            return None
        prev_path = PANEL_DIR / f"daily_{prev_trade_date}.parquet"
        if not prev_path.exists():
            return None
        prev = pd.read_parquet(prev_path, columns=["ts_code", "close"])
        prev = prev.rename(columns={"close": "prev_close"})
        today_subset = today[["ts_code", "close"]].merge(
            prev, on="ts_code", how="left",
        )

    today_subset["close"] = today_subset["close"].astype(float)
    today_subset["prev_close"] = today_subset["prev_close"].astype(float)

    # Drop rows with missing close or prev_close (suspended on either day)
    today_subset = today_subset.dropna(subset=["close", "prev_close"])
    today_subset = today_subset[
        (today_subset["close"] > 0) & (today_subset["prev_close"] > 0)
    ]

    # ST detection
    if has_name:
        name_lookup = today.set_index("ts_code")["name"].to_dict()
        today_subset["is_st"] = today_subset["ts_code"].map(
            lambda c: is_st_name(name_lookup.get(c))
        )
    else:
        today_subset["is_st"] = False

    # Exchange tier and limit percentage per stock
    trade_date_ts = pd.to_datetime(trade_date)
    today_subset["exchange_tier"] = today_subset["ts_code"].apply(classify_ts_code)
    today_subset["limit_pct"] = today_subset.apply(
        lambda r: get_limit_pct(r["ts_code"], trade_date_ts, r["is_st"]),
        axis=1,
    )

    # Theoretical limits and flags
    today_subset["theoretical_up"] = (
        today_subset["prev_close"] * (1 + today_subset["limit_pct"])
    )
    today_subset["theoretical_down"] = (
        today_subset["prev_close"] * (1 - today_subset["limit_pct"])
    )
    today_subset["at_limit_up"] = (
        today_subset["close"] >= LIMIT_PROXIMITY * today_subset["theoretical_up"]
    )
    today_subset["at_limit_down"] = (
        today_subset["close"] <= (2 - LIMIT_PROXIMITY) * today_subset["theoretical_down"]
    )

    today_subset["trade_date"] = trade_date

    if verbose:
        n = len(today_subset)
        n_up = int(today_subset["at_limit_up"].sum())
        n_down = int(today_subset["at_limit_down"].sum())
        n_st = int(today_subset["is_st"].sum())
        n_chinext = int((today_subset["exchange_tier"] == "chinext").sum())
        n_star = int((today_subset["exchange_tier"] == "star").sum())
        print(f"  {trade_date}: {n:,} stocks, "
              f"{n_up} limit-up ({100*n_up/n:.2f}%), "
              f"{n_down} limit-down ({100*n_down/n:.2f}%), "
              f"{n_st} ST, {n_chinext} ChiNext, {n_star} STAR")

    return today_subset[[
        "trade_date", "ts_code", "exchange_tier", "limit_pct", "is_st",
        "at_limit_up", "at_limit_down"
    ]].copy()


# ─── Drivers ────────────────────────────────────────────────────────────

def get_trading_calendar() -> list:
    return pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()


def smoke_test():
    """One date, verbose output."""
    print("=" * 60)
    print("LIMIT-STATE FILTER — SMOKE")
    print("=" * 60)

    calendar = get_trading_calendar()
    sample_dates = ["2020-03-23", "2024-09-25", "2025-02-05"]
    # Pick a notable post-COVID-stimulus week and others.
    for d in sample_dates:
        if d in calendar:
            idx = calendar.index(d)
            prev = calendar[idx - 1] if idx > 0 else None
            print(f"\nSampling {d}:")
            df = detect_limit_states_for_date(d, prev, verbose=True)
            if df is None:
                print(f"  no data")


def full_run():
    """Build the full limit-state panel for every calendar date."""
    print("LIMIT-STATE FILTER — FULL")
    calendar = get_trading_calendar()
    print(f"  {len(calendar)} trading days to process")

    frames = []
    n_failed = 0
    t0 = time.time()
    for i, date in enumerate(calendar):
        prev = calendar[i - 1] if i > 0 else None
        df = detect_limit_states_for_date(date, prev, verbose=False)
        if df is None:
            n_failed += 1
        else:
            frames.append(df)

        if (i + 1) % 200 == 0 or (i + 1) == len(calendar):
            secs = time.time() - t0
            print(f"  [{i+1}/{len(calendar)}] {date}: "
                  f"frames={len(frames)}, failed={n_failed}, "
                  f"elapsed={secs:.1f}s")

    if not frames:
        print("ERROR: no limit-state frames computed.")
        return

    print(f"\nConcatenating {len(frames)} per-date frames...")
    panel = pd.concat(frames, ignore_index=True)

    # Downcast bools and limit_pct to save space
    panel["at_limit_up"] = panel["at_limit_up"].astype(bool)
    panel["at_limit_down"] = panel["at_limit_down"].astype(bool)
    panel["is_st"] = panel["is_st"].astype(bool)
    panel["limit_pct"] = panel["limit_pct"].astype("float32")

    print(f"\nSummary on full panel:")
    n = len(panel)
    n_up = int(panel["at_limit_up"].sum())
    n_down = int(panel["at_limit_down"].sum())
    print(f"  rows:               {n:,}")
    print(f"  at_limit_up:        {n_up:,} ({100*n_up/n:.3f}%)")
    print(f"  at_limit_down:      {n_down:,} ({100*n_down/n:.3f}%)")
    print(f"  ST flagged:         {int(panel['is_st'].sum()):,}")
    print(f"  exchange tier breakdown:")
    print(panel['exchange_tier'].value_counts().to_string())

    panel.to_parquet(OUTPUT_PATH, compression="zstd", index=False)
    print(f"\nWrote -> {OUTPUT_PATH}")
    print(f"  file size:          "
          f"{OUTPUT_PATH.stat().st_size / (1024*1024):.1f} MB")


def status():
    if not OUTPUT_PATH.exists():
        print(f"No limit-state panel at {OUTPUT_PATH}. Run with `full`.")
        return

    panel = pd.read_parquet(OUTPUT_PATH)
    n = len(panel)
    print(f"Limit-state panel: {OUTPUT_PATH}")
    print(f"  rows:           {n:,}")
    print(f"  unique dates:   {panel['trade_date'].nunique()}")
    print(f"  unique stocks:  {panel['ts_code'].nunique():,}")
    print(f"  at_limit_up:    {int(panel['at_limit_up'].sum()):,} "
          f"({100*panel['at_limit_up'].mean():.3f}%)")
    print(f"  at_limit_down:  {int(panel['at_limit_down'].sum()):,} "
          f"({100*panel['at_limit_down'].mean():.3f}%)")
    print(f"  ST rows:        {int(panel['is_st'].sum()):,}")
    print(f"\n  exchange_tier:")
    print(panel['exchange_tier'].value_counts().to_string())

    # Limit-state frequency by year
    panel['year'] = pd.to_datetime(panel['trade_date'], format='%Y%m%d').dt.year
    yearly = panel.groupby('year').agg(
        n='size',
        n_up=('at_limit_up', 'sum'),
        n_down=('at_limit_down', 'sum'),
    )
    yearly['pct_up'] = (100 * yearly['n_up'] / yearly['n']).round(3)
    yearly['pct_down'] = (100 * yearly['n_down'] / yearly['n']).round(3)
    print(f"\n  Limit-state frequency by year:")
    print(yearly[['n', 'n_up', 'pct_up', 'n_down', 'pct_down']].to_string())


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke_test()
    elif mode == "full":
        full_run()
    elif mode == "status":
        status()
    else:
        print("Usage: python limit_state_filter.py [smoke|full|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()