"""
factor_volume_reversal.py — Volume-amplified short-term reversal factor.

For each L ∈ {3,5,10,15,20} and rank_type ∈ {ts, cs}:
  ret_L                = forward-adjusted close return over the past L days
  vol_rank_ts          = clipped abnormal-volume z-score over [t-L+1, t]
                          baseline = mean/std of `amount` over [t-60-L+1, t-L]
                          mapped to [0,1] via (z + 3) / 6
  vol_rank_cs          = cross-sectional percentile rank of vol_Ld_mean
                          across the universe at date t
  score_<rank>_L       = -ret_L × vol_rank_<rank>
  resid_<rank>_L       = residual of score on (log_mcap + industry_name dummies)
  z_volrev_L_<rank>    = cross-sectional z-score of resid_<rank>_L per date

Higher z_volrev = stronger long signal (loser × high volume).

Look-ahead alignment: the 60-day baseline window ends strictly before the
L-day signal window (no overlap). See spec §4.2 and self-check 4.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

import fr_config
from factor_utils import cross_sectional_zscore, residualise_factor_per_date


def _adj_close_wide(daily_long: pd.DataFrame) -> pd.DataFrame:
    """Wide forward-adjusted close: index=date, columns=ts_code."""
    long = daily_long.copy()
    long["adj_close"] = long["close"] * long["adj_factor"]
    return long.pivot(index="trade_date", columns="ts_code",
                      values="adj_close").sort_index()


def _amount_wide(daily_long: pd.DataFrame) -> pd.DataFrame:
    return daily_long.pivot(index="trade_date", columns="ts_code",
                            values="amount").sort_index()


def _trailing_return(adj_close_w: pd.DataFrame, L: int) -> pd.DataFrame:
    """ret_L[t] = adj_close[t] / adj_close[t-L] - 1, wide."""
    return adj_close_w / adj_close_w.shift(L) - 1.0


def _vol_rank_ts(amount_w: pd.DataFrame, L: int,
                 baseline: int = 60) -> pd.DataFrame:
    """
    Time-series volume rank wide.

    L-window: [t-L+1, t] (ending at t, length L)
    Baseline: [t-baseline-L+1, t-L] (ending strictly before L-window, length=baseline)

    Implementation:
      vol_L_mean[t]    = amount.rolling(L).mean() at t  (window ends at t)
      vol_60_mean[t]   = amount.shift(L).rolling(baseline).mean() at t
      vol_60_std[t]    = amount.shift(L).rolling(baseline).std() at t
    """
    vol_L = amount_w.rolling(L, min_periods=L).mean()
    shifted = amount_w.shift(L)
    vol_b_mean = shifted.rolling(baseline, min_periods=baseline).mean()
    vol_b_std = shifted.rolling(baseline, min_periods=baseline).std()

    z = (vol_L - vol_b_mean) / vol_b_std
    z = z.where(vol_b_std > 0)  # NaN where std is 0 or NaN
    z = z.clip(fr_config.VOL_WINSOR_LOW, fr_config.VOL_WINSOR_HIGH)
    rank = (z - fr_config.VOL_WINSOR_LOW) / (
        fr_config.VOL_WINSOR_HIGH - fr_config.VOL_WINSOR_LOW
    )
    # Also expose the raw L-mean for use by cs ranking and self-checks
    return rank, vol_L


def _vol_rank_cs(vol_L_at_date: pd.Series,
                 universe_at_date: set[str]) -> pd.Series:
    """Cross-sectional percentile rank within universe at one date."""
    s = vol_L_at_date[vol_L_at_date.index.isin(universe_at_date)]
    s = s.dropna()
    return s.rank(pct=True)


def build_factor_panel(rebalance_dates: list[pd.Timestamp],
                       universe_dict: dict[pd.Timestamp, set[str]],
                       daily_long: pd.DataFrame,
                       fpa: pd.DataFrame,
                       industry_lookup: pd.DataFrame | None = None,
                       L_values: Iterable[int] = None,
                       verbose: bool = True) -> pd.DataFrame:
    """
    Build the full factor panel for the γ rebalance dates.

    Parameters
    ----------
    rebalance_dates : list of γ Wednesday rebalance Timestamps.
    universe_dict   : {date: set(ts_code)} for each rebalance date.
    daily_long      : long-format daily panel covering at least
                      [γ_start - 80 trading days, γ_end] for every L.
    fpa             : factor_panel_a DataFrame, gives log_mcap and
                      weekly_forward_return per (rebalance_date, ts_code).
                      Should already have `industry_name` attached, OR
                      an `industry_lookup` DataFrame must be provided.
    industry_lookup : optional fallback (date, ts_code, industry_name).
    L_values        : iterable of L to compute; defaults to fr_config.L_VALUES.

    Returns
    -------
    DataFrame keyed (rebalance_date, ts_code) with:
        ret_<L>  for each L
        vol_rank_ts_<L>  for each L
        vol_rank_cs_<L>  for each L
        score_ts_<L>, score_cs_<L>  for each L
        resid_ts_<L>, resid_cs_<L>  for each L (residualised on log_mcap + sector)
        z_volrev_<L>_ts, z_volrev_<L>_cs  for each L (final cross-sectional z)
        log_mcap, industry_name, weekly_forward_return, in_universe
    """
    if L_values is None:
        L_values = fr_config.L_VALUES
    L_values = list(L_values)

    if verbose:
        print(f"build_factor_panel: {len(rebalance_dates)} dates, "
              f"L ∈ {L_values}")

    # 1. Build wide series once
    adj_close_w = _adj_close_wide(daily_long)
    amount_w = _amount_wide(daily_long)
    if verbose:
        print(f"  adj_close_w shape: {adj_close_w.shape}")
        print(f"  amount_w shape:    {amount_w.shape}")

    # 2. For each L, compute return & vol_rank_ts wide
    ret_w = {L: _trailing_return(adj_close_w, L) for L in L_values}
    rank_ts_w_and_vol_L = {
        L: _vol_rank_ts(amount_w, L, fr_config.VOL_BASELINE_DAYS)
        for L in L_values
    }
    rank_ts_w = {L: r for L, (r, _) in rank_ts_w_and_vol_L.items()}
    vol_L_w = {L: v for L, (_, v) in rank_ts_w_and_vol_L.items()}

    # 3. Slice each rebalance date out of the wide frames + cs rank
    rows = []
    for d in rebalance_dates:
        if d not in adj_close_w.index:
            if verbose:
                print(f"  WARNING: rebalance date {d.date()} not in daily panel")
            continue
        u = universe_dict.get(d, set())
        if not u:
            continue

        for L in L_values:
            ret = ret_w[L].loc[d]
            rank_ts = rank_ts_w[L].loc[d]
            vol_L_d = vol_L_w[L].loc[d]
            rank_cs = _vol_rank_cs(vol_L_d, u)
            # Universe-restrict
            tickers = sorted(u & set(ret.index))
            for tk in tickers:
                rows.append({
                    "rebalance_date": d, "ts_code": tk, "L": L,
                    "ret_L": float(ret.get(tk, np.nan)),
                    "vol_rank_ts": float(rank_ts.get(tk, np.nan)),
                    "vol_rank_cs": float(rank_cs.get(tk, np.nan)),
                })

    panel = pd.DataFrame(rows)
    if verbose:
        print(f"  panel rows (long over L): {len(panel):,}")

    # 4. Pivot to wide-by-L: one row per (rebalance_date, ts_code), columns
    #    ret_L, vol_rank_ts_L, vol_rank_cs_L for each L.
    wide = panel.pivot_table(
        index=["rebalance_date", "ts_code"],
        columns="L",
        values=["ret_L", "vol_rank_ts", "vol_rank_cs"],
    )
    wide.columns = [f"{a}_{int(b)}" for a, b in wide.columns]
    wide = wide.reset_index()

    # 5. Compute scores
    for L in L_values:
        wide[f"score_ts_{L}"] = -wide[f"ret_L_{L}"] * wide[f"vol_rank_ts_{L}"]
        wide[f"score_cs_{L}"] = -wide[f"ret_L_{L}"] * wide[f"vol_rank_cs_{L}"]

    # 6. Join log_mcap, weekly_forward_return, in_universe from fpa
    fpa_cols = ["rebalance_date", "ts_code", "log_mcap",
                "weekly_forward_return", "in_universe"]
    fpa_slice = fpa[fpa_cols].copy()
    # Upcast log_mcap to float64
    fpa_slice["log_mcap"] = fpa_slice["log_mcap"].astype(np.float64)
    fpa_slice["weekly_forward_return"] = (
        fpa_slice["weekly_forward_return"].astype(np.float64)
    )
    wide = wide.merge(fpa_slice, on=["rebalance_date", "ts_code"], how="left")

    # 7. Attach industry_name (PIT) if not already present
    if "industry_name" not in wide.columns:
        if industry_lookup is None:
            from data_loaders import attach_sector
            wide = attach_sector(wide)
        else:
            wide = wide.merge(industry_lookup,
                              on=["rebalance_date", "ts_code"], how="left")

    # 8. Residualise each score on (log_mcap, industry_name) per date
    for L in L_values:
        for r in fr_config.RANK_TYPES:
            src = f"score_{r}_{L}"
            out = f"resid_{r}_{L}"
            wide = residualise_factor_per_date(
                wide, src, out,
                numeric_controls=fr_config.RESIDUALISE_NUMERIC,
                categorical_control=fr_config.RESIDUALISE_CATEGORICAL,
                date_col="rebalance_date",
                min_obs=fr_config.RESIDUALISE_MIN_OBS,
            )

    # 9. Cross-sectional z-score of the residual
    for L in L_values:
        for r in fr_config.RANK_TYPES:
            src = f"resid_{r}_{L}"
            out = f"z_volrev_{L}_{r}"
            wide = cross_sectional_zscore(
                wide, src, out,
                date_col="rebalance_date",
                winsorize=True, low=0.01, high=0.99,
            )

    if verbose:
        print(f"  final panel shape: {wide.shape}")
        print(f"  columns of interest:")
        zcols = [c for c in wide.columns if c.startswith("z_volrev_")]
        print(f"    {zcols}")

    return wide


if __name__ == "__main__":
    # Smoke run on a tiny date subset
    from data_loaders import (
        load_universe_dict, load_daily_panel_long, attach_sector
    )

    udict = load_universe_dict(gamma_only=True)
    sample_dates = sorted(udict.keys())[:3]
    print(f"smoke: dates {[d.date() for d in sample_dates]}")

    end = max(sample_dates)
    start = end - pd.Timedelta(days=120)
    dp = load_daily_panel_long(start, end)

    fpa = pd.read_parquet(fr_config.FACTOR_PANEL_A)
    fpa["rebalance_date"] = pd.to_datetime(fpa["rebalance_date"])
    fpa = fpa[fpa["rebalance_date"].isin(sample_dates)]
    fpa = attach_sector(fpa)

    panel = build_factor_panel(sample_dates, udict, dp, fpa,
                                L_values=[5], verbose=True)
    print(panel[["rebalance_date", "ts_code", "z_volrev_5_ts",
                 "z_volrev_5_cs", "weekly_forward_return"]].head())
