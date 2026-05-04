"""
build_factor_panel.py — Build the factor panel for Universe A.

For each weekly rebalance date and each candidate stock, gathers:
  - in_universe (True if in Universe A on this date)
  - close, pre_close, open, high, low (from daily panel on rebalance day)
  - circ_mv, circ_mv_yi (free-float market cap)
  - amount, turnover_rate, turnover_rate_f
  - weekly_forward_return (close[t+1_rebal] / close[t_rebal] - 1)
  - mean_turnover_20d (the trailing-20-day mean of turnover_rate_f used
     by the turnover factor)

Architectural note on universe-turnover bias
--------------------------------------------
The factor panel includes EVERY candidate (every stock that's ever been
in Universe A across the panel), with `in_universe` flagged True/False
per-date. Factor signals are computed on the FULL panel so formation
windows have valid data even for stocks that were not yet in-universe.
The in_universe filter is then applied at the cross-sectional sort step.
This is the same architectural fix as Project 6 Stage 5.

Trailing turnover lookup
------------------------
For each (rebalance_date, ts_code), `mean_turnover_20d` is the mean of
turnover_rate_f over the trailing 20 calendar trading days ending on
rebalance_date - 1 (i.e. NOT including the rebalance day itself; we use
the period before signal generation). Stocks with fewer than 15 valid
observations in the window get NaN.

Forward return convention
-------------------------
weekly_forward_return[t] = close[t+1_rebal] / close[t_rebal] - 1
where t_rebal and t+1_rebal are CONSECUTIVE rebalance dates. If the next
rebalance is missing for that stock (suspended, delisted, no data), the
forward return is NaN. The last rebalance date in the panel has NaN
forward_return by construction (no next rebalance).

Adjustment
----------
We use the daily panel's `close` directly. Tushare's `daily` close is
the unadjusted close; for return computation we apply the adj_factor
panel: adjusted_close = close * adj_factor. This handles ex-div and
splits correctly. The same logic was used in Project 6.

Inputs
------
  - data/universe_membership_three.parquet
  - daily_panel/daily_<DATE>.parquet for each rebalance + window day
  - ../Project_6/data/weekly_rebalance_dates.csv

Output
------
  data/factor_panel_a.parquet keyed on (rebalance_date, ts_code) with:
    rebalance_date          str YYYY-MM-DD
    ts_code                 str
    in_universe             bool (in_A)
    close, open, high, low  float32 unadjusted prices on rebalance day
    adj_factor              float32 adjustment factor on rebalance day
    adj_close               float32 close × adj_factor
    circ_mv_yi              float32 free-float market cap, 亿 RMB
    log_mcap                float32
    amount_yi               float32 daily 成交额, 亿 RMB
    turnover_rate           float32
    turnover_rate_f         float32
    mean_turnover_20d       float32 trailing 20-day mean of turnover_rate_f
    weekly_forward_return   float32 close-to-close return to next rebalance
    next_rebalance_date     str YYYY-MM-DD (for diagnostics)

Daily forward returns and open prices are NOT in this panel; those go
into a separate daily-level panel built by the analysis script when
needed for T+1 backtest construction.

Usage
-----
    python build_factor_panel.py smoke   # 5 rebalance dates
    python build_factor_panel.py full    # all rebalance dates
    python build_factor_panel.py status  # inspect cached output
"""

import bisect
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    A_SHARE_PATTERN,
    AMOUNT_QIANYUAN_TO_YI,
    CIRC_MV_WAN_TO_YI,
    DAILY_PANEL_DIR,
    PROJECT_6_DATA_DIR,
    THREE_UNIVERSE_PANEL_PATH,
    TRADING_CALENDAR_PATH,
    WEEKLY_REBALANCE_DATES_PATH,
)


# ─── Configuration ─────────────────────────────────────────────────────

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

FACTOR_PANEL_PATH = DATA_DIR / "factor_panel_a.parquet"
ERROR_LOG = DATA_DIR / "errors_build_factor_panel.log"

COMPRESSION = "zstd"

# Trailing-turnover lookup parameters
TURNOVER_LOOKBACK_DAYS = 20
TURNOVER_MIN_OBS = 15


# ─── Error logging ─────────────────────────────────────────────────────

_logger = logging.getLogger("build_factor_panel")
_logger.setLevel(logging.WARNING)
if not _logger.handlers:
    _handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _logger.addHandler(_handler)


def _log_warn(date: str, msg: str) -> None:
    _logger.warning(f"date={date} | {msg}")


# ─── Helpers ────────────────────────────────────────────────────────────

def _get_calendar() -> list:
    if not TRADING_CALENDAR_PATH.exists():
        raise FileNotFoundError(f"{TRADING_CALENDAR_PATH} missing")
    return pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()


def _get_rebalance_dates() -> list:
    if not WEEKLY_REBALANCE_DATES_PATH.exists():
        raise FileNotFoundError(f"{WEEKLY_REBALANCE_DATES_PATH} missing")
    return pd.read_csv(WEEKLY_REBALANCE_DATES_PATH)["date"].tolist()


def _read_daily_panel(date_str: str) -> pd.DataFrame | None:
    """Read one day's parquet, return None if missing."""
    path = DAILY_PANEL_DIR / f"daily_{date_str}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


# ─── Core build ─────────────────────────────────────────────────────────

def build_panel(verbose: bool = False, n_dates_limit: int | None = None) -> pd.DataFrame:
    """
    Build the factor panel.

    Strategy:
      1. Load universe_membership_three.parquet, keep just (rebal_date, ts_code, in_A).
      2. For each rebalance date, read its daily panel parquet, filter to
         A-share equities, attach the in_A flag, compute circ_mv_yi etc.
      3. Compute mean_turnover_20d by reading the 20 trading-day window
         ending the day before each rebalance and averaging turnover_rate_f
         per ts_code.
      4. Compute weekly_forward_return by sorting (ts_code, rebal_date)
         and shifting adj_close by -1 within ts_code group. Validate that
         the shifted date is the immediate-next rebalance date (no
         multi-week gap due to suspension).
    """
    print("Loading universe membership...")
    if not THREE_UNIVERSE_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"{THREE_UNIVERSE_PANEL_PATH} not found. "
            f"Run build_three_universes.py full first."
        )
    membership = pd.read_parquet(
        THREE_UNIVERSE_PANEL_PATH,
        columns=["rebalance_date", "ts_code", "in_A"],
    )
    membership = membership.rename(columns={"in_A": "in_universe"})
    print(f"  {len(membership):,} membership rows, "
          f"{membership['ts_code'].nunique():,} unique stocks")

    rebal_dates = _get_rebalance_dates()
    if n_dates_limit is not None:
        rebal_dates = rebal_dates[:n_dates_limit]
        print(f"  smoke-limited to first {n_dates_limit} rebalance dates")

    calendar = _get_calendar()
    cal_idx = {d: i for i, d in enumerate(calendar)}

    # Step 1: per-rebalance-date snapshot
    print(f"\nStep 1: gathering per-rebalance daily snapshots...")
    snapshots = []
    n_failed = 0
    t0 = time.time()
    for i, rebal_date in enumerate(rebal_dates, 1):
        panel = _read_daily_panel(rebal_date)
        if panel is None:
            _log_warn(rebal_date, "daily panel missing")
            n_failed += 1
            continue
        # Filter to A-share equities only
        df = panel[panel["ts_code"].str.match(A_SHARE_PATTERN)].copy()
        df["rebalance_date"] = rebal_date
        snapshots.append(df)
        if verbose and (i % 50 == 0 or i == len(rebal_dates)):
            print(f"  [{i:>4}/{len(rebal_dates)}] elapsed={time.time()-t0:.1f}s")

    if not snapshots:
        raise RuntimeError("No daily snapshots loaded")

    print(f"  concatenating {len(snapshots)} snapshots...")
    snap = pd.concat(snapshots, ignore_index=True)
    print(f"  {len(snap):,} (rebalance, stock) rows")

    # Step 2: attach in_universe flag from membership
    print(f"\nStep 2: attaching in_universe flag...")
    snap = snap.merge(
        membership, on=["rebalance_date", "ts_code"], how="left"
    )
    snap["in_universe"] = snap["in_universe"].fillna(False).astype(bool)
    n_iu = int(snap["in_universe"].sum())
    print(f"  in_universe rows: {n_iu:,} of {len(snap):,} "
          f"({100*n_iu/len(snap):.1f}%)")

    # Step 3: compute derived columns
    print(f"\nStep 3: computing derived columns...")
    # Coerce critical columns to float
    for c in ("close", "open", "high", "low", "pre_close", "adj_factor",
              "circ_mv", "amount", "turnover_rate", "turnover_rate_f"):
        if c in snap.columns:
            snap[c] = pd.to_numeric(snap[c], errors="coerce")

    snap["adj_close"] = snap["close"] * snap["adj_factor"]
    snap["circ_mv_yi"] = snap["circ_mv"] * CIRC_MV_WAN_TO_YI
    snap["log_mcap"] = np.log(snap["circ_mv_yi"].where(snap["circ_mv_yi"] > 0))
    snap["amount_yi"] = snap["amount"] * AMOUNT_QIANYUAN_TO_YI

    # Step 4: trailing 20-day mean turnover_rate_f
    print(f"\nStep 4: computing trailing-20d mean turnover ({TURNOVER_LOOKBACK_DAYS} days, "
          f"min {TURNOVER_MIN_OBS} obs)...")
    snap["mean_turnover_20d"] = _compute_trailing_turnover(
        rebal_dates, calendar, cal_idx, snap,
        lookback=TURNOVER_LOOKBACK_DAYS,
        min_obs=TURNOVER_MIN_OBS,
        verbose=verbose,
    )
    n_with_turnover = int(snap["mean_turnover_20d"].notna().sum())
    print(f"  mean_turnover_20d coverage: {n_with_turnover:,} of "
          f"{len(snap):,} ({100*n_with_turnover/len(snap):.1f}%)")

    # Step 5: weekly forward return
    print(f"\nStep 5: computing weekly forward returns...")
    snap = snap.sort_values(["ts_code", "rebalance_date"]).reset_index(drop=True)
    snap["next_adj_close"] = snap.groupby("ts_code")["adj_close"].shift(-1)
    snap["next_rebalance_date"] = snap.groupby("ts_code")["rebalance_date"].shift(-1)

    # Validate: the shifted date must be the consecutive-next rebalance
    rebal_sorted = sorted(rebal_dates)
    next_rebal_map = dict(zip(rebal_sorted[:-1], rebal_sorted[1:]))
    snap["expected_next_rebalance"] = snap["rebalance_date"].map(next_rebal_map)
    valid_mask = snap["next_rebalance_date"] == snap["expected_next_rebalance"]
    snap["weekly_forward_return"] = snap["next_adj_close"] / snap["adj_close"] - 1
    snap.loc[~valid_mask, "weekly_forward_return"] = np.nan

    n_valid = int(valid_mask.sum())
    n_total = len(snap)
    n_last_date = int((snap["rebalance_date"] == rebal_sorted[-1]).sum())
    n_invalid = n_total - n_valid - n_last_date
    print(f"  forward_return valid:           {n_valid:,} "
          f"({100*n_valid/n_total:.1f}%)")
    print(f"  invalidated (suspension gap):   {n_invalid:,}")
    print(f"  last-date NaN by design:        {n_last_date:,}")

    # Step 6: final shape
    print(f"\nStep 6: building output schema...")
    out_cols = [
        "rebalance_date", "ts_code", "in_universe",
        "close", "open", "high", "low", "pre_close",
        "adj_factor", "adj_close",
        "circ_mv_yi", "log_mcap",
        "amount_yi", "turnover_rate", "turnover_rate_f",
        "mean_turnover_20d",
        "weekly_forward_return",
        "next_rebalance_date",
    ]
    out = snap[out_cols].copy()

    # Downcast numeric columns
    for c in ("close", "open", "high", "low", "pre_close",
              "adj_factor", "adj_close", "circ_mv_yi", "log_mcap",
              "amount_yi", "turnover_rate", "turnover_rate_f",
              "mean_turnover_20d", "weekly_forward_return"):
        out[c] = out[c].astype("float32")

    return out


def _compute_trailing_turnover(
    rebal_dates: list,
    calendar: list,
    cal_idx: dict,
    snap: pd.DataFrame,
    lookback: int,
    min_obs: int,
    verbose: bool = False,
) -> pd.Series:
    """
    Trailing N-day mean of turnover_rate_f per (rebal_date, ts_code).

    Strategy: for each rebalance date, read the prior `lookback` daily
    panel parquets, concatenate the turnover_rate_f columns, group by
    ts_code and average. Stocks with fewer than `min_obs` observations
    in the window get NaN.

    Returns a Series aligned to snap's index. snap must have rebalance_date
    and ts_code columns.
    """
    out = pd.Series(np.nan, index=snap.index, dtype="float64")
    snap_idx = snap.set_index(["rebalance_date", "ts_code"]).index

    t0 = time.time()
    for i, rebal_date in enumerate(rebal_dates, 1):
        if rebal_date not in cal_idx:
            continue
        end_idx = cal_idx[rebal_date]  # exclusive end
        start_idx = end_idx - lookback
        if start_idx < 0:
            continue
        window_dates = calendar[start_idx:end_idx]

        # Read each window day's panel, keeping only ts_code + turnover_rate_f
        frames = []
        for d in window_dates:
            p = _read_daily_panel(d)
            if p is None:
                continue
            sub = p[["ts_code", "turnover_rate_f"]].copy()
            sub["turnover_rate_f"] = pd.to_numeric(
                sub["turnover_rate_f"], errors="coerce"
            )
            frames.append(sub)
        if not frames:
            continue

        win = pd.concat(frames, ignore_index=True).dropna(
            subset=["turnover_rate_f"]
        )
        # Average per ts_code, count obs
        agg = win.groupby("ts_code")["turnover_rate_f"].agg(["mean", "count"])
        # Apply min_obs gate
        agg.loc[agg["count"] < min_obs, "mean"] = np.nan
        # Map back into out for this rebalance date
        # Index into snap_idx tuples
        for ts_code, row in agg.iterrows():
            try:
                pos = snap_idx.get_loc((rebal_date, ts_code))
                out.iloc[pos] = row["mean"]
            except KeyError:
                continue

        if verbose and (i % 25 == 0 or i == len(rebal_dates)):
            secs = time.time() - t0
            print(f"  [turnover {i:>4}/{len(rebal_dates)}] "
                  f"elapsed={secs:.1f}s")

    return out


# ─── Drivers ────────────────────────────────────────────────────────────

def smoke_test() -> None:
    print("=" * 60)
    print("BUILD FACTOR PANEL — SMOKE (first 10 rebalance dates)")
    print("=" * 60)

    t0 = time.time()
    out = build_panel(verbose=True, n_dates_limit=10)
    elapsed = time.time() - t0

    print(f"\nSmoke result:")
    print(f"  rows:                {len(out):,}")
    print(f"  unique stocks:       {out['ts_code'].nunique():,}")
    print(f"  unique dates:        {out['rebalance_date'].nunique()}")
    print(f"  in_universe rows:    {int(out['in_universe'].sum()):,}")
    print(f"  elapsed:             {elapsed:.1f}s")

    print(f"\n  Field coverage on in_universe rows:")
    iu = out[out["in_universe"]]
    for col in ["close", "adj_close", "log_mcap", "turnover_rate_f",
                "mean_turnover_20d", "weekly_forward_return"]:
        cov = iu[col].notna().mean() * 100
        print(f"    {col:<24s} {cov:>5.1f}%")

    # Per-date in-universe count
    iu_per_date = out[out["in_universe"]].groupby("rebalance_date").size()
    print(f"\n  in_universe count per date:")
    print(f"    min={iu_per_date.min()}, "
          f"median={int(iu_per_date.median())}, "
          f"max={iu_per_date.max()}")

    # Forward return sanity
    fr = iu.dropna(subset=["weekly_forward_return"])["weekly_forward_return"]
    if len(fr) > 0:
        print(f"\n  weekly_forward_return sanity (in_universe, all dates):")
        print(f"    n           {len(fr):,}")
        print(f"    mean        {fr.mean()*100:+.3f}%/wk  "
              f"(annualized ~{fr.mean()*52*100:+.1f}%)")
        print(f"    std         {fr.std()*100:.3f}%/wk")
        print(f"    p1, p99     {fr.quantile(0.01)*100:+.2f}%, "
              f"{fr.quantile(0.99)*100:+.2f}%")


def full_run() -> None:
    print("=" * 60)
    print("BUILD FACTOR PANEL — FULL")
    print("=" * 60)

    t0 = time.time()
    out = build_panel(verbose=True, n_dates_limit=None)

    print(f"\nWriting -> {FACTOR_PANEL_PATH}...")
    out.to_parquet(FACTOR_PANEL_PATH, compression=COMPRESSION, index=False)

    print(f"\nFull run complete in {time.time()-t0:.1f}s")
    print(f"  rows:          {len(out):,}")
    print(f"  unique stocks: {out['ts_code'].nunique():,}")
    print(f"  unique dates:  {out['rebalance_date'].nunique()}")
    print(f"  in_universe:   {int(out['in_universe'].sum()):,}")
    print(f"  output:        {FACTOR_PANEL_PATH}")
    print(f"  size:          {FACTOR_PANEL_PATH.stat().st_size / 1024**2:.1f} MB")


def status() -> None:
    if not FACTOR_PANEL_PATH.exists():
        print(f"No factor panel at {FACTOR_PANEL_PATH}. Run with `full`.")
        return

    out = pd.read_parquet(FACTOR_PANEL_PATH)
    print(f"Factor panel: {FACTOR_PANEL_PATH}")
    print(f"  rows:          {len(out):,}")
    print(f"  unique stocks: {out['ts_code'].nunique():,}")
    print(f"  unique dates:  {out['rebalance_date'].nunique()}")
    print(f"  date range:    {out['rebalance_date'].min()} to "
          f"{out['rebalance_date'].max()}")
    print(f"  in_universe:   {int(out['in_universe'].sum()):,}")
    print(f"  size:          {FACTOR_PANEL_PATH.stat().st_size / 1024**2:.1f} MB")

    print(f"\n  Field coverage (in_universe rows):")
    iu = out[out["in_universe"]]
    for col in ["close", "adj_close", "log_mcap", "turnover_rate_f",
                "mean_turnover_20d", "weekly_forward_return"]:
        cov = iu[col].notna().mean() * 100
        print(f"    {col:<24s} {cov:>5.1f}%")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke_test()
    elif mode == "full":
        full_run()
    elif mode == "status":
        status()
    else:
        print("Usage: python build_factor_panel.py [smoke|full|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
