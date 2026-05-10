"""
factor_utils.py — v3-local FWL primitives.

Trimmed local port of multi_factor_x1/factor_utils.py.

Provides:
  - residualise_factor_per_date: per-date OLS of factor on numeric +
    categorical controls; returns residuals
  - cross_sectional_zscore: per-date winsorized z-score
"""

from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd


def residualise_factor_per_date(
    panel: pd.DataFrame,
    factor_col: str,
    out_col: str,
    numeric_controls: Iterable[str] = (),
    categorical_control: Optional[str] = None,
    date_col: str = "signal_date",
    min_obs: int = 30,
) -> pd.DataFrame:
    """
    Per-date OLS of factor_col on intercept + numeric_controls + dummies(categorical_control).
    Writes residuals to out_col. Stocks with any NaN in inputs get NaN residual.

    Float64 is required on factor + numeric controls before calling (May 7
    lesson). The caller must upcast — this function does not.
    """
    df = panel.copy()
    df[out_col] = np.nan
    numeric_controls = list(numeric_controls)
    have_categorical = (
        categorical_control is not None and categorical_control in df.columns
    )

    n_fitted = 0
    n_skipped = 0
    for date, group in df.groupby(date_col, sort=False):
        cols = [factor_col] + numeric_controls
        if have_categorical:
            cols.append(categorical_control)
        valid_mask = group[cols].notna().all(axis=1)
        valid = group[valid_mask]
        if len(valid) < min_obs:
            n_skipped += 1
            continue

        y = valid[factor_col].values.astype(float)
        X_parts = [np.ones((len(valid), 1))]
        for c in numeric_controls:
            X_parts.append(valid[[c]].values.astype(float))
        if have_categorical:
            dummies = pd.get_dummies(
                valid[categorical_control], drop_first=True
            )
            if len(dummies.columns) > 0:
                X_parts.append(dummies.values.astype(float))
        X = np.hstack(X_parts)

        try:
            beta_hat, *_ = np.linalg.lstsq(X, y, rcond=None)
            residuals = y - X @ beta_hat
        except np.linalg.LinAlgError:
            n_skipped += 1
            continue

        df.loc[valid.index, out_col] = residuals
        n_fitted += 1

    coverage = df[out_col].notna().sum() / len(df) * 100 if len(df) else 0
    print(f"    residualise({factor_col}->{out_col}): fitted={n_fitted}, "
          f"skipped={n_skipped}, coverage={coverage:.1f}%")
    return df


def cross_sectional_zscore(
    panel: pd.DataFrame,
    factor_col: str,
    out_col: str,
    date_col: str = "signal_date",
    winsorize: bool = True,
    low: float = 0.01,
    high: float = 0.99,
) -> pd.DataFrame:
    """Per-date winsorized z-score."""
    df = panel.copy()

    def _z(s: pd.Series) -> pd.Series:
        if winsorize:
            lo = s.quantile(low)
            hi = s.quantile(high)
            s = s.clip(lo, hi)
        m, sd = s.mean(), s.std()
        if sd == 0 or pd.isna(sd):
            return pd.Series(np.nan, index=s.index)
        return (s - m) / sd

    df[out_col] = df.groupby(date_col)[factor_col].transform(_z)
    return df
