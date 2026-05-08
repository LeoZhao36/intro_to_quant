"""
panel_builders.py — Per-rebalance cap_rank and tradability panels.

Two simple per-rebalance builders:
  - build_cap_rank: cross-sectional rank of total_mv within post-baseline
    universe at t, normalised to [0,1].
  - build_tradability: 60-day median amount ≥ LIQ_FLOOR_AMOUNT_YI within
    post-baseline universe at t, with min-days requirement.

Both consume the output of baseline_filter.apply_baseline_filter and
return a DataFrame with one row per (rebalance_date, ts_code).
"""

from __future__ import annotations

import pandas as pd
import numpy as np

import config
from baseline_filter import load_trading_calendar, daily_panel_path


def build_cap_rank(rebalance_date: pd.Timestamp,
                   baseline: pd.DataFrame) -> pd.DataFrame:
    """
    Cross-sectional rank of total_mv within baseline universe.
    Returns DataFrame: trade_date, ts_code, total_mv, cap_rank.
    """
    if baseline.empty:
        return pd.DataFrame(columns=["trade_date", "ts_code", "total_mv", "cap_rank"])

    df = baseline[["ts_code", "total_mv"]].copy()
    df["total_mv"] = pd.to_numeric(df["total_mv"], errors="coerce")
    df = df.dropna(subset=["total_mv"])
    if df.empty:
        return pd.DataFrame(columns=["trade_date", "ts_code", "total_mv", "cap_rank"])

    df["cap_rank"] = df["total_mv"].rank(pct=True, method="average")
    df["trade_date"] = rebalance_date
    return df[["trade_date", "ts_code", "total_mv", "cap_rank"]].reset_index(drop=True)


def build_tradability(rebalance_date: pd.Timestamp,
                      baseline: pd.DataFrame) -> pd.DataFrame:
    """
    60-day median amount panel. Returns DataFrame:
        trade_date, ts_code, amt_60d_median, n_obs_60d, tradable.

    Threshold: amt_60d_median ≥ LIQ_FLOOR_AMOUNT_YI (in 亿 RMB),
    AND n_obs_60d ≥ LIQ_FLOOR_MIN_DAYS.

    Uses the daily_panel directly (one parquet per trading day), reading
    only the trailing window. Tushare amount is in 千元: convert ×1e-5
    to 亿.
    """
    if baseline.empty:
        return pd.DataFrame(columns=[
            "trade_date", "ts_code", "amt_60d_median", "n_obs_60d", "tradable"
        ])

    cal = load_trading_calendar()
    rebal_str = rebalance_date.strftime("%Y-%m-%d")
    if rebal_str not in cal:
        return pd.DataFrame()
    end_idx = cal.index(rebal_str)
    start_idx = max(0, end_idx - config.LIQ_FLOOR_WINDOW)
    window_dates = cal[start_idx:end_idx]  # exclusive of rebalance day itself

    universe = set(baseline["ts_code"])
    rows: list[pd.DataFrame] = []
    for d in window_dates:
        path = config.DAILY_PANEL_DIR / f"daily_{d}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["ts_code", "amount"])
        df = df[df["ts_code"].isin(universe)]
        if df.empty:
            continue
        df["amount_yi"] = pd.to_numeric(df["amount"], errors="coerce") \
            * config.AMOUNT_QIANYUAN_TO_YI
        rows.append(df[["ts_code", "amount_yi"]])

    if not rows:
        return pd.DataFrame()

    long = pd.concat(rows, ignore_index=True)
    agg = (
        long.dropna(subset=["amount_yi"])
        .groupby("ts_code", as_index=False)
        .agg(amt_60d_median=("amount_yi", "median"),
             n_obs_60d=("amount_yi", "size"))
    )
    agg["tradable"] = (
        (agg["amt_60d_median"] >= config.LIQ_FLOOR_AMOUNT_YI)
        & (agg["n_obs_60d"] >= config.LIQ_FLOOR_MIN_DAYS)
    )
    agg["trade_date"] = rebalance_date

    # Stocks in baseline but with no observed amount in the window get
    # tradable=False with NaN median.
    missing = list(universe - set(agg["ts_code"]))
    if missing:
        miss_df = pd.DataFrame({
            "ts_code": missing,
            "amt_60d_median": [np.nan] * len(missing),
            "n_obs_60d": [0] * len(missing),
            "tradable": [False] * len(missing),
            "trade_date": [rebalance_date] * len(missing),
        })
        agg = pd.concat([agg, miss_df], ignore_index=True)

    return agg[["trade_date", "ts_code", "amt_60d_median",
                "n_obs_60d", "tradable"]].reset_index(drop=True)
