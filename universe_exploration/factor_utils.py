"""
factor_utils.py — Cross-sectional factor analysis primitives.

Pieces the multi_factor_x1 factor scripts need:
  - cross_sectional_zscore:       per-date winsorized z-score
  - compute_quintile_series:      per-date quintile sort, mean forward return
  - compute_ic_series:             per-date Spearman rank IC
  - summarise_long_short:          Q5-Q1 spread stats with one-line print
  - residualise_factor_per_date:  per-date OLS of factor on controls;
                                   returns residuals
  - compute_trailing_beta:         stock-level trailing beta vs benchmark

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

from typing import Iterable, Optional

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


def residualise_factor_per_date(
    panel: pd.DataFrame,
    factor_col: str,
    out_col: str,
    numeric_controls: Iterable[str] = (),
    categorical_control: Optional[str] = None,
    date_col: str = "rebalance_date",
    min_obs: int = 50,
) -> pd.DataFrame:
    """
    Per-date OLS of factor_col on controls; write residuals to out_col.

    For each rebalance_date independently, fit:
        factor_col ~ const + numeric_controls + dummies(categorical_control)
    using stocks with all values non-NaN. The residuals are the part of
    factor_col not explained by the controls. Stocks with any NaN in the
    inputs get NaN residual.

    Parameters
    ----------
    panel : DataFrame with rebalance_date, ts_code, factor_col, controls.
    factor_col : str, the column to residualize.
    out_col : str, where to write residuals.
    numeric_controls : iterable of column names (e.g. log_mcap, beta_60d).
        Each enters the regression as a continuous variable.
    categorical_control : optional column name (e.g. industry_name).
        Enters as one-hot dummies with the first category dropped.
    min_obs : per-date minimum number of valid observations to fit;
        below this, all residuals on that date are set to NaN.

    Returns
    -------
    panel with the new out_col attached.

    Implementation note
    -------------------
    OLS solved via numpy least squares (np.linalg.lstsq) per date. For
    typical sizes (3000-4000 rows × ~30 dummies + 1-2 numeric per date)
    this is fast (well under 0.1 sec per date).

    The residual is computed as factor - X @ beta_hat where X is the
    design matrix and beta_hat is the OLS coefficient vector. Properties:
      - mean of residuals across observations = 0 (intercept absorbs it)
      - residuals are orthogonal to every column of X
      - therefore residuals carry no linear information about controls
    """
    df = panel.copy()
    df[out_col] = np.nan

    numeric_controls = list(numeric_controls)

    # Pre-build dummy frame once so we know the full set of categories;
    # we'll re-derive per-date dummies from the same categorical column.
    have_categorical = (
        categorical_control is not None and categorical_control in df.columns
    )

    n_dates_fitted = 0
    n_dates_skipped = 0
    for date, group in df.groupby(date_col, sort=False):
        cols_needed = [factor_col] + numeric_controls
        if have_categorical:
            cols_needed.append(categorical_control)
        valid_mask = group[cols_needed].notna().all(axis=1)
        valid = group[valid_mask]
        if len(valid) < min_obs:
            n_dates_skipped += 1
            continue

        y = valid[factor_col].values.astype(float)

        # Build design matrix
        X_parts = [np.ones((len(valid), 1))]  # intercept
        for c in numeric_controls:
            X_parts.append(valid[[c]].values.astype(float))
        if have_categorical:
            dummies = pd.get_dummies(
                valid[categorical_control], drop_first=True
            )
            if len(dummies.columns) > 0:
                X_parts.append(dummies.values.astype(float))
        X = np.hstack(X_parts)

        # OLS via lstsq, residual = y - X @ beta_hat
        try:
            beta_hat, *_ = np.linalg.lstsq(X, y, rcond=None)
            residuals = y - X @ beta_hat
        except np.linalg.LinAlgError:
            n_dates_skipped += 1
            continue

        df.loc[valid.index, out_col] = residuals
        n_dates_fitted += 1

    print(f"  residualise_factor_per_date({factor_col} -> {out_col}):")
    print(f"    controls: numeric={numeric_controls}, "
          f"categorical={categorical_control}")
    print(f"    dates fitted: {n_dates_fitted}, skipped: {n_dates_skipped}")
    coverage = df[out_col].notna().sum() / len(df) * 100
    print(f"    overall coverage: {coverage:.1f}%")

    return df


def compute_trailing_beta(
    daily_returns: pd.DataFrame,
    benchmark_returns: pd.Series,
    window: int = 60,
    min_obs: int = 40,
) -> pd.DataFrame:
    """
    Per-stock trailing beta vs a benchmark return series.

    Parameters
    ----------
    daily_returns : wide DataFrame with index=date, columns=ts_code.
        Each cell is a daily return (close-to-close).
    benchmark_returns : Series indexed by date, same calendar as
        daily_returns. The benchmark return on that date.
    window : trailing window length in trading days (default 60).
    min_obs : minimum observations required in the window to compute
        a beta. Defaults to 40 (≈ 2/3 of window).

    Returns
    -------
    DataFrame with same shape as daily_returns. Each cell is the trailing
    beta computed using observations [t - window, t - 1] (excludes day t
    itself, so beta on day t is forward-looking-safe).

    Math
    ----
    beta_t = Cov(r_stock, r_bench) / Var(r_bench), both computed over the
    trailing window. Equivalently, slope of OLS regression of stock returns
    on benchmark returns.

    Implementation
    --------------
    Vectorized: for each ts_code column, rolling cov/var on returns aligned
    with benchmark. Stocks with fewer than min_obs in the window get NaN.
    Suspended days (NaN return) are skipped, which causes the effective
    sample size to drop on stocks with frequent suspensions.

    Caveat
    ------
    Beta in thinly-traded names is noisy and can be unstable. Consider
    using only as a control variable, not as a primary signal. See
    Vasicek (1973) shrinkage for a production-grade alternative.
    """
    aligned_bench = benchmark_returns.reindex(daily_returns.index)
    bench_var = aligned_bench.rolling(window=window, min_periods=min_obs).var().shift(1)
    out = pd.DataFrame(
        np.nan, index=daily_returns.index, columns=daily_returns.columns,
        dtype="float64",
    )
    for col in daily_returns.columns:
        s = daily_returns[col]
        cov = s.rolling(window=window, min_periods=min_obs).cov(
            aligned_bench
        ).shift(1)
        out[col] = cov / bench_var
    return out