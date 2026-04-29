"""
stage2_liquidity_panel.py — Stage 2 rewrite for the rebuilt panel.

Computes the trailing 60-day mean trading amount per (ts_code, rebalance_date)
from the unified daily panel. Output is a single parquet keyed on
(rebalance_date, ts_code) with columns:

    rebalance_date, ts_code, mean_amount_wan, n_trading_days_observed

Used by Stage 3's hybrid liquidity floor:
    in_universe = (mean_amount_wan in top X% of survivors)
                  AND (mean_amount_wan >= Y万 absolute floor)

Why 60 days, not 20 (Project 5)
-------------------------------
A 20-day mean is sensitive to single-day volume spikes. A normally illiquid
stock with one heavy-trade day can pop above the floor briefly, then drop
out the next month. This in-and-out churn pollutes the universe-turnover
analysis without reflecting persistent liquidity. 60 days smooths through
these spikes; the resulting floor crossings reflect genuine regime changes
in a stock's trading activity rather than transient bursts.

Suspended-day handling
----------------------
Tushare's `daily` endpoint omits suspended days entirely (no zero-amount
placeholder rows). So `n_trading_days_observed` is the count of actually-
traded days in the trailing 60 calendar-trading days. A stock suspended
for the entire window appears with NaN mean and n=0; Stage 3 should
exclude these (they are not tradable on the rebalance date).

A stock with, e.g., 30 observed days in the trailing 60 has a mean
computed only over those 30 days. This is the right behavior: the question
"on average, what does this stock trade per active day" is what we want.
A stock that traded heavily on the few days it was active still has high
liquidity capacity even if it was suspended half the window.

API calls: zero. Pure data manipulation on cached parquets.

Output
------
data/liquidity_panel_60d.parquet              one row per (rebalance_date, ts_code)

Usage
-----
    python stage2_liquidity_panel.py smoke   # first 5 weekly dates, verbose
    python stage2_liquidity_panel.py full    # all 381 dates
    python stage2_liquidity_panel.py status  # cache/output status
"""

import logging
import sys
import time
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass


# ==========================================================
# Configuration
# ==========================================================

DATA_DIR = Path("data")
PANEL_DIR = DATA_DIR / "daily_panel"
TRADING_CALENDAR_PATH = DATA_DIR / "trading_calendar.csv"
REBALANCE_DATES_PATH = DATA_DIR / "weekly_rebalance_dates.csv"
LIQUIDITY_PANEL_PATH = DATA_DIR / "liquidity_panel_60d.parquet"
ERROR_LOG = DATA_DIR / "errors_stage2_liquidity.log"

DATA_DIR.mkdir(exist_ok=True)

# Trailing window. Project 5 used 20; the rebuild uses 60 per user request.
WINDOW_DAYS = 60

COMPRESSION = "zstd"


# ==========================================================
# Error logging
# ==========================================================

_logger = logging.getLogger("stage2_liquidity")
_logger.setLevel(logging.WARNING)
_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
_logger.addHandler(_handler)


def _log_warn(date, msg):
    _logger.warning(f"date={date} | {msg}")


# ==========================================================
# Helpers
# ==========================================================

def get_trading_calendar():
    if not TRADING_CALENDAR_PATH.exists():
        raise FileNotFoundError(
            f"{TRADING_CALENDAR_PATH} not found. Run daily_panel_pull.py first."
        )
    return pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()


def get_rebalance_dates():
    if not REBALANCE_DATES_PATH.exists():
        raise FileNotFoundError(
            f"{REBALANCE_DATES_PATH} not found. Run stage1_with_pit_names.py first."
        )
    return pd.read_csv(REBALANCE_DATES_PATH)["date"].tolist()


def _amount_to_wan(amount_qianyuan):
    """
    Tushare's `amount` is in 千元 (thousands of yuan).
    Project 5's liquidity floor convention is 万元 (tens of thousands).
    1 万元 = 10 千元, so divide by 10.
    """
    return amount_qianyuan / 10.0


# ==========================================================
# Core computation
# ==========================================================

def compute_liquidity_for_date(rebalance_date, calendar, verbose=False):
    """
    Compute trailing 60-trading-day mean amount per stock for one rebalance date.

    Reads the 60 trading-day parquets ending at rebalance_date (inclusive
    if rebalance_date is itself a trading day, which all weekly dates are
    by construction in Stage 1's roll-forward logic).

    Returns a DataFrame with columns:
        rebalance_date, ts_code, mean_amount_wan, n_trading_days_observed
    """
    # Find the rebalance_date's index in the calendar; take the prior
    # WINDOW_DAYS trading days (NOT including rebalance_date itself).
    # Rationale: at the moment of rebalance close, you have not seen
    # today's full trading volume yet for the daily-close convention.
    # Aligns with Project 5's "trailing 20 days, not including today".
    try:
        end_idx = calendar.index(rebalance_date)
    except ValueError:
        _log_warn(rebalance_date, "rebalance_date not in trading calendar")
        return None

    start_idx = end_idx - WINDOW_DAYS
    if start_idx < 0:
        _log_warn(rebalance_date,
                  f"insufficient trailing data: only {end_idx} prior days "
                  f"available (need {WINDOW_DAYS})")
        return None

    window_dates = calendar[start_idx:end_idx]  # exclusive of rebalance_date

    # Read panels for the window. Each parquet has ts_code, trade_date,
    # amount among other columns; we keep only what we need.
    frames = []
    missing = []
    for d in window_dates:
        path = PANEL_DIR / f"daily_{d}.parquet"
        if not path.exists():
            missing.append(d)
            continue
        df = pd.read_parquet(path, columns=["ts_code", "amount"])
        df["trade_date"] = d
        frames.append(df)

    if missing:
        _log_warn(rebalance_date,
                  f"{len(missing)} of {WINDOW_DAYS} window panels missing; "
                  f"first missing: {missing[0]}")
        # Continue with what we have; n_trading_days_observed will reflect this.

    if not frames:
        _log_warn(rebalance_date, "no window panels found at all")
        return None

    window = pd.concat(frames, ignore_index=True)

    # Drop rows where the stock had no trading data on the day. Tushare
    # generally omits suspended days entirely (no row), but if a row is
    # present with NaN amount we treat it as a non-traded day.
    window = window.dropna(subset=["amount"])
    window = window[window["amount"] > 0]

    # Groupby aggregation: per ts_code, compute mean amount and count of
    # observed trading days. This is the vectorised core of Stage 2.
    agg = window.groupby("ts_code").agg(
        mean_amount_qianyuan=("amount", "mean"),
        n_trading_days_observed=("amount", "size"),
    ).reset_index()

    agg["mean_amount_wan"] = _amount_to_wan(agg["mean_amount_qianyuan"])
    agg["rebalance_date"] = rebalance_date

    # Order columns canonically.
    out = agg[[
        "rebalance_date", "ts_code", "mean_amount_wan",
        "n_trading_days_observed"
    ]].copy()

    # Downcast to save space when many dates concatenated.
    out["mean_amount_wan"] = out["mean_amount_wan"].astype("float32")
    out["n_trading_days_observed"] = out["n_trading_days_observed"].astype("int16")

    if verbose:
        n = len(out)
        median_amt = out["mean_amount_wan"].median()
        median_days = out["n_trading_days_observed"].median()
        n_full = (out["n_trading_days_observed"] == WINDOW_DAYS).sum()
        n_low = (out["n_trading_days_observed"] < WINDOW_DAYS // 2).sum()
        print(f"  window: {window_dates[0]} to {window_dates[-1]} "
              f"({len(window_dates)} trading days)")
        print(f"  output: {n:,} stocks with non-zero trading in window")
        print(f"    median mean_amount_wan: {median_amt:>10,.0f} 万")
        print(f"    median n_observed:      {int(median_days):>10}")
        print(f"    full-window stocks:     {n_full:>10,}  "
              f"(traded all {WINDOW_DAYS} days)")
        print(f"    low-coverage stocks:    {n_low:>10,}  "
              f"(<{WINDOW_DAYS//2} days, likely suspended part of window)")

    return out


# ==========================================================
# Drivers
# ==========================================================

def smoke_test():
    print("=" * 60)
    print(f"STAGE 2 SMOKE: trailing-{WINDOW_DAYS}-day liquidity for first 5 dates")
    print("=" * 60)

    calendar = get_trading_calendar()
    rebalance_dates = get_rebalance_dates()
    test_dates = rebalance_dates[:5]

    t0 = time.time()
    for i, date in enumerate(test_dates, 1):
        print(f"[{i}/5] {date}")
        out = compute_liquidity_for_date(date, calendar, verbose=True)
        if out is None:
            print(f"  -> FAILED")
        print()

    print(f"Smoke done in {time.time() - t0:.1f}s. "
          f"If counts and medians look right, run with `full`.")


def full_run():
    """
    Compute liquidity panel for every rebalance date and concatenate into
    one parquet. ~30-90 seconds for 381 dates.
    """
    print(f"STAGE 2 FULL: trailing-{WINDOW_DAYS}-day liquidity, all weekly dates")

    calendar = get_trading_calendar()
    rebalance_dates = get_rebalance_dates()
    print(f"  rebalance dates: {len(rebalance_dates)}")
    print(f"  output -> {LIQUIDITY_PANEL_PATH}\n")

    t0 = time.time()
    frames = []
    n_failed = 0
    for i, date in enumerate(rebalance_dates, 1):
        out = compute_liquidity_for_date(date, calendar, verbose=False)
        if out is None:
            n_failed += 1
        else:
            frames.append(out)

        if i % 50 == 0 or i == len(rebalance_dates):
            secs = time.time() - t0
            n_ok = len(frames)
            print(f"[{i:>4}/{len(rebalance_dates)}] {date}: "
                  f"ok={n_ok}, failed={n_failed}, elapsed={secs:.1f}s")

    if not frames:
        print("ERROR: no liquidity panels computed.")
        return

    print(f"\nConcatenating {len(frames)} per-date frames...")
    panel = pd.concat(frames, ignore_index=True)
    panel.to_parquet(LIQUIDITY_PANEL_PATH, compression=COMPRESSION, index=False)

    secs = time.time() - t0
    print(f"\nFull run done in {secs:.1f}s")
    print(f"  total rows:  {len(panel):,}")
    print(f"  unique stocks across all dates: "
          f"{panel['ts_code'].nunique():,}")
    print(f"  output: {LIQUIDITY_PANEL_PATH}")
    if n_failed > 0:
        print(f"  failures: {n_failed} (see {ERROR_LOG})")


def status():
    """Inspect the cached liquidity panel if present."""
    if not LIQUIDITY_PANEL_PATH.exists():
        print(f"No liquidity panel at {LIQUIDITY_PANEL_PATH}. Run with `full`.")
        return

    panel = pd.read_parquet(LIQUIDITY_PANEL_PATH)
    print(f"Liquidity panel: {LIQUIDITY_PANEL_PATH}")
    print(f"  rows:           {len(panel):,}")
    print(f"  unique dates:   {panel['rebalance_date'].nunique():,}")
    print(f"  unique stocks:  {panel['ts_code'].nunique():,}")
    print(f"  date range:     {panel['rebalance_date'].min()} to "
          f"{panel['rebalance_date'].max()}")
    print(f"\n  mean_amount_wan summary (across all rows):")
    print(panel['mean_amount_wan'].describe().to_string())
    print(f"\n  n_trading_days_observed value counts:")
    vc = panel['n_trading_days_observed'].value_counts().sort_index()
    print(f"    full window ({WINDOW_DAYS}):  "
          f"{vc.get(WINDOW_DAYS, 0):>10,} rows")
    print(f"    < {WINDOW_DAYS//2} days:        "
          f"{(panel['n_trading_days_observed'] < WINDOW_DAYS // 2).sum():>10,} rows")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke_test()
    elif mode == "full":
        full_run()
    elif mode == "status":
        status()
    else:
        print(f"Usage: python stage2_liquidity_panel.py [smoke|full|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()