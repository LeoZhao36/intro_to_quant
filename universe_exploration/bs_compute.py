"""
bs_compute.py — Per-rebalance Behavioural Score components.

Four components, each cross-sectionally rank-transformed within the
post-baseline universe at t and normalised to [0,1]:

  BS_idiovol  : 60-day std of daily residuals from
                ret_i = β_i × synthetic_EW_market_ret + ε_i
                Computed via the algebraic identity
                  Var(ε) = Var(r_i) - Cov(r_i, m)² / Var(m)
                so we never materialize residuals.
  BS_max      : 30-day max of daily returns (Bali-Cakici-Whitelaw MAX).
  BS_skew     : 60-day skewness of daily returns.
  BS_lowprice : INVERTED rank of close at t. Lower price → higher BS_lowprice.

All four cross-sectionally ranked, then composite = mean of four ranks.

The synthetic-EW benchmark mirrors the construction in
multi_factor_x1/turnover_neutralized.py: equal-weight return of all
A-share equities (regex A_SHARE_PATTERN) on each date. Pre-load done once
via prepare_returns_panel().
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

import config
from baseline_filter import load_trading_calendar


_LOADED: dict = {}


def prepare_returns_panel(
    start: pd.Timestamp,
    end: pd.Timestamp,
    verbose: bool = True,
) -> dict:
    """
    Load daily returns and close into wide DataFrames covering [start, end].
    Returns a dict with keys:
      - returns_wide : DataFrame, index=date (str YYYY-MM-DD), cols=ts_code
      - close_wide   : DataFrame, same shape
      - bench_series : Series of synthetic-EW market return per date
      - dates        : sorted list of available dates

    Float64 enforced (handover hard rule). Re-call resets the cache.
    """
    cal = load_trading_calendar()
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    use_dates = [d for d in cal if start_str <= d <= end_str]

    if verbose:
        print(f"  loading daily panel for {len(use_dates)} dates "
              f"[{start_str} .. {end_str}]")

    ret_frames: list[pd.DataFrame] = []
    close_frames: list[pd.DataFrame] = []
    bench_pairs: list[tuple[str, float]] = []

    t0 = time.time()
    for i, d in enumerate(use_dates, 1):
        path = config.DAILY_PANEL_DIR / f"daily_{d}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=[
            "ts_code", "close", "pre_close", "pct_chg",
        ])
        df["ts_code"] = df["ts_code"].astype(str)
        df = df[df["ts_code"].str.match(config.A_SHARE_PATTERN)].copy()

        # Returns (prefer pct_chg if present)
        if "pct_chg" in df.columns and df["pct_chg"].notna().any():
            ret = pd.to_numeric(df["pct_chg"], errors="coerce") / 100.0
        else:
            close = pd.to_numeric(df["close"], errors="coerce")
            pre = pd.to_numeric(df["pre_close"], errors="coerce")
            ret = close / pre - 1.0

        df["__ret"] = ret.astype(np.float64)
        df["__close"] = pd.to_numeric(df["close"], errors="coerce").astype(np.float64)
        df["__date"] = d

        valid = df.dropna(subset=["__ret"])
        if not valid.empty:
            bench_pairs.append((d, float(valid["__ret"].mean())))
            ret_frames.append(valid[["__date", "ts_code", "__ret"]])
            close_frames.append(df[["__date", "ts_code", "__close"]])

        if verbose and (i % 200 == 0 or i == len(use_dates)):
            print(f"  [{i:>4}/{len(use_dates)}] elapsed={time.time()-t0:.1f}s")

    if not ret_frames:
        raise RuntimeError("prepare_returns_panel: no data loaded")

    long_ret = pd.concat(ret_frames, ignore_index=True)
    long_close = pd.concat(close_frames, ignore_index=True)

    returns_wide = long_ret.pivot(index="__date", columns="ts_code",
                                   values="__ret").sort_index()
    close_wide = long_close.pivot(index="__date", columns="ts_code",
                                   values="__close").sort_index()
    returns_wide = returns_wide.astype(np.float64)
    close_wide = close_wide.astype(np.float64)

    bench_df = pd.DataFrame(bench_pairs, columns=["__date", "bench"]) \
        .set_index("__date").sort_index()
    bench_series = bench_df["bench"].astype(np.float64) \
        .reindex(returns_wide.index)

    if verbose:
        print(f"  returns_wide shape={returns_wide.shape}  "
              f"close_wide shape={close_wide.shape}  "
              f"bench_series len={len(bench_series)}")

    _LOADED["returns_wide"] = returns_wide
    _LOADED["close_wide"] = close_wide
    _LOADED["bench_series"] = bench_series
    _LOADED["dates"] = sorted(returns_wide.index.tolist())
    return _LOADED


def _ensure_loaded() -> dict:
    if not _LOADED:
        raise RuntimeError(
            "bs_compute: returns panel not loaded; "
            "call prepare_returns_panel() first."
        )
    return _LOADED


# ═══════════════════════════════════════════════════════════════════════
# Component computations (rolling, vectorized)
# ═══════════════════════════════════════════════════════════════════════

def _compute_idiovol_panel() -> pd.DataFrame:
    """
    Rolling 60-day idiosyncratic vol via the cov/var identity:
      Var(ε) = Var(r) - Cov(r, m)² / Var(m)
    Returns wide DataFrame (date × ts_code) of idiovol_t = sqrt(Var(ε)).
    """
    L = _ensure_loaded()
    ret = L["returns_wide"]
    bench = L["bench_series"]

    rolling = ret.rolling(window=config.BS_IDIOVOL_WINDOW,
                           min_periods=config.BS_IDIOVOL_MIN_OBS)
    var_r = rolling.var()
    cov_rm = rolling.cov(bench)
    bench_var = bench.rolling(window=config.BS_IDIOVOL_WINDOW,
                               min_periods=config.BS_IDIOVOL_MIN_OBS).var()
    bench_var = bench_var.where(bench_var > 1e-12, np.nan)
    idio_var = var_r.subtract(
        cov_rm.pow(2).div(bench_var, axis=0), fill_value=0.0
    )
    idio_var = idio_var.where(idio_var > 0, 0.0)
    return idio_var.pow(0.5)


def _compute_max_panel() -> pd.DataFrame:
    L = _ensure_loaded()
    return L["returns_wide"].rolling(
        window=config.BS_MAX_WINDOW,
        min_periods=max(10, config.BS_MAX_WINDOW // 3),
    ).max()


def _compute_skew_panel() -> pd.DataFrame:
    L = _ensure_loaded()
    return L["returns_wide"].rolling(
        window=config.BS_SKEW_WINDOW,
        min_periods=config.BS_SKEW_MIN_OBS,
    ).skew()


# ═══════════════════════════════════════════════════════════════════════
# Per-rebalance assembly
# ═══════════════════════════════════════════════════════════════════════

_PANELS: dict = {}


def precompute_bs_panels(verbose: bool = True) -> None:
    """Compute the three rolling panels once for fast per-rebalance lookup."""
    if verbose:
        t0 = time.time()
        print("  computing rolling idiovol panel...")
    _PANELS["idiovol"] = _compute_idiovol_panel()
    if verbose:
        print(f"    elapsed={time.time()-t0:.1f}s")
        t0 = time.time()
        print("  computing rolling MAX panel...")
    _PANELS["max"] = _compute_max_panel()
    if verbose:
        print(f"    elapsed={time.time()-t0:.1f}s")
        t0 = time.time()
        print("  computing rolling skew panel...")
    _PANELS["skew"] = _compute_skew_panel()
    if verbose:
        print(f"    elapsed={time.time()-t0:.1f}s")


def _rank_keep_sign(s: pd.Series) -> pd.Series:
    if s.empty:
        return s
    return s.rank(pct=True, method="average")


def _rank_invert(s: pd.Series) -> pd.Series:
    if s.empty:
        return s
    return 1.0 - s.rank(pct=True, method="average")


def compute_bs_for_date(
    rebalance_date: pd.Timestamp,
    baseline: pd.DataFrame,
) -> pd.DataFrame:
    """
    Per-rebalance BS components. Looks up the rolling panels at the
    trading day BEFORE rebalance_date. Cross-sectional rank within the
    post-baseline universe.

    Returns DataFrame: trade_date, ts_code, bs_idiovol, bs_max, bs_skew,
    bs_lowprice, bs_score.
    """
    if baseline.empty:
        return pd.DataFrame()
    if not _PANELS:
        raise RuntimeError("bs_compute: call precompute_bs_panels() first.")

    cal = load_trading_calendar()
    rebal_str = rebalance_date.strftime("%Y-%m-%d")
    if rebal_str not in cal:
        return pd.DataFrame()
    end_idx = cal.index(rebal_str)
    if end_idx == 0:
        return pd.DataFrame()
    prev_day = cal[end_idx - 1]

    universe = sorted(set(baseline["ts_code"]))

    def _row_for(panel: pd.DataFrame) -> pd.Series:
        if prev_day not in panel.index:
            return pd.Series(dtype=float)
        return panel.loc[prev_day].reindex(universe)

    idio_raw = _row_for(_PANELS["idiovol"])
    max_raw = _row_for(_PANELS["max"])
    skew_raw = _row_for(_PANELS["skew"])

    # close at rebalance day for low-price component
    close_wide = _LOADED["close_wide"]
    close_at_t = (close_wide.loc[rebal_str] if rebal_str in close_wide.index
                   else pd.Series(dtype=float))
    close_at_t = close_at_t.reindex(universe)

    # Cross-sectional ranks. All four high-rank = retail-behavioural-strong.
    bs_idiovol = _rank_keep_sign(idio_raw.dropna()).reindex(universe)
    bs_max = _rank_keep_sign(max_raw.dropna()).reindex(universe)
    bs_skew = _rank_keep_sign(skew_raw.dropna()).reindex(universe)
    bs_lowprice = _rank_invert(close_at_t.dropna()).reindex(universe)

    out = pd.DataFrame({
        "ts_code": universe,
        "bs_idiovol": bs_idiovol.values,
        "bs_max": bs_max.values,
        "bs_skew": bs_skew.values,
        "bs_lowprice": bs_lowprice.values,
    })
    out["bs_score"] = out[["bs_idiovol", "bs_max", "bs_skew", "bs_lowprice"]] \
        .mean(axis=1, skipna=True)
    out["trade_date"] = rebalance_date
    return out[[
        "trade_date", "ts_code",
        "bs_idiovol", "bs_max", "bs_skew", "bs_lowprice", "bs_score",
    ]]
