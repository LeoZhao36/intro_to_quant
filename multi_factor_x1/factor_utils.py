"""
factor_utils.py — Cross-sectional factor analysis primitives.

Trimmed from Project_6/Factor_Analysis_Weekly_Universe/factor_utils.py.
Just the pieces the multi_factor_x1 first-pass factor scripts need:
  - cross_sectional_zscore: per-date winsorized z-score
  - compute_quintile_series: per-date quintile sort, mean forward return
  - compute_ic_series:       per-date Spearman rank IC
  - summarise_long_short:    Q5-Q1 spread stats with one-line print

In-universe filter
------------------
The factor panel produced by build_factor_panel.py contains every
(rebalance_date, candidate_stock) pair with `in_universe` flagged True
when the stock is in Universe A on that date. Z-score and quintile-sort
functions filter to in_universe=True before computing.

Sign convention
---------------
Z-scores returned here have the SAME sign as the raw factor. Sign-flip
to align with "high z = predicted to outperform" must be done explicitly
by the caller, e.g.
    panel = cross_sectional_zscore(panel, "turnover_20d", "z_turn_raw")
    panel["z_turnover"] = -panel["z_turn_raw"]   # high z = LOW turnover
"""

import numpy as np
import pandas as pd


def cross_sectional_zscore(
    panel: pd.DataFrame,
    factor_col: str,
    out_col: str,
    date_col: str = "rebalance_date",
    winsorize: bool = True,
    low: float = 0.01,
    high: float = 0.99,
) -> pd.DataFrame:
    """
    Add per-date cross-sectional z-score column.

    For each rebalance_date: optionally winsorize at [low, high] percentiles,
    then standardize to (x - mean) / std using the cross-sectional moments
    on that date, ignoring NaN.

    Stocks with NaN factor_col remain NaN in out_col.

    Note: z-scoring runs on ALL rows at a date, not just in_universe.
    This gives a stable cross-sectional reference even for stocks
    transitioning into/out of the universe. The in_universe filter
    is applied at the quintile-sort step downstream.
    """
    df = panel.copy()

    def _zscore(s: pd.Series) -> pd.Series:
        if winsorize:
            lo = s.quantile(low)
            hi = s.quantile(high)
            s = s.clip(lo, hi)
        mean = s.mean()
        std = s.std()
        if std == 0 or pd.isna(std):
            return pd.Series(np.nan, index=s.index)
        return (s - mean) / std

    df[out_col] = df.groupby(date_col)[factor_col].transform(_zscore)
    return df


def compute_quintile_series(
    panel: pd.DataFrame,
    sort_col: str,
    return_col: str = "weekly_forward_return",
    in_universe_col: str = "in_universe",
) -> pd.DataFrame:
    """
    Per-date quintile sort on sort_col within in_universe stocks; return
    mean return_col per (date, quintile) as a wide DataFrame indexed by
    rebalance_date with columns 0..4 (Q1..Q5).

    Q1 (smallest sort_col) = column 0; Q5 (largest) = column 4.
    """
    df = panel[panel[in_universe_col]].copy()
    df["quintile"] = df.groupby("rebalance_date")[sort_col].transform(
        lambda s: pd.qcut(s, 5, labels=False, duplicates="drop")
    )
    return (
        df.groupby(["rebalance_date", "quintile"])[return_col]
        .mean()
        .unstack()
    )


def compute_ic_series(
    panel: pd.DataFrame,
    sort_col: str,
    return_col: str = "weekly_forward_return",
    in_universe_col: str = "in_universe",
) -> pd.Series:
    """Cross-sectional Spearman rank IC per rebalance_date, in-universe only."""
    df = panel[panel[in_universe_col]]
    return (
        df.dropna(subset=[return_col, sort_col])
        .groupby("rebalance_date")
        .apply(
            lambda g: g[sort_col].corr(g[return_col], method="spearman"),
            include_groups=False,
        )
        .dropna()
    )


def summarise_long_short(
    qr: pd.DataFrame, label: str, periods_per_year: int = 52,
) -> dict:
    """
    Compute Q5-Q1 spread mean, std, t-stat, naive Sharpe; print one-liner;
    return dict with the underlying series for downstream bootstrap.

    Note the sign convention: Q5-Q1 (top quintile minus bottom) is the
    standard direction. Callers should sign-flip the FACTOR, not the
    spread, so a positive Q5-Q1 always means "factor's high-z names
    outperformed factor's low-z names."
    """
    if 0 not in qr.columns or 4 not in qr.columns:
        return {"label": label, "n": 0}
    ls = (qr[4] - qr[0]).dropna()  # Q5 minus Q1
    if len(ls) < 2:
        return {"label": label, "n": int(len(ls))}
    mean = float(ls.mean())
    std = float(ls.std())
    t_stat = mean / (std / np.sqrt(len(ls))) if std > 0 else np.nan
    sharpe = mean / std * np.sqrt(periods_per_year) if std > 0 else np.nan

    print(
        f"  {label:<40s} n={len(ls):3d}  "
        f"mean={mean*100:+.3f}%  "
        f"std={std*100:.3f}%  "
        f"t={t_stat:+.2f}  Sharpe={sharpe:+.2f}"
    )
    return {
        "label": label,
        "n": int(len(ls)),
        "mean_period": mean,
        "std_period": std,
        "t_stat": float(t_stat),
        "naive_sharpe": float(sharpe),
        "ls_series": ls,
    }
