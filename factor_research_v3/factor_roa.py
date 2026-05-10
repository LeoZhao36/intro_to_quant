"""
factor_roa.py — Raw ROA construction.

ROA_TTM = ttm_ni / avg_total_assets

where ttm_ni and avg_total_assets are pre-computed (PIT-correct, with
cumulative-vs-quarterly handling) by pit_panel_builder.py.

Sign convention: higher ROA = better quality. No sign flip.

For consistency with EP, NaN out ROA when avg_total_assets <= 0 (defensive;
should be rare). We do NOT NaN out negative ROA — a loss-making stock has
a meaningful negative ROA, unlike negative EP.

Public API:
    compute_raw_roa(signal_date, pit_panel) -> Series indexed by ts_code
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_raw_roa(signal_date: pd.Timestamp,
                    pit_panel: pd.DataFrame) -> pd.Series:
    """
    ROA from the PIT TTM panel at signal_date.

    Returns Series indexed by ts_code, name='roa'. Stocks without TTM
    coverage are simply absent from the index (caller can reindex).
    """
    sub = pit_panel[pit_panel["signal_date"] == signal_date]
    if sub.empty:
        return pd.Series(dtype="float64", name="roa")
    sub = sub.dropna(subset=["ttm_ni", "avg_total_assets"])
    sub = sub[sub["avg_total_assets"] > 0]
    if sub.empty:
        return pd.Series(dtype="float64", name="roa")
    out = (sub["ttm_ni"].astype("float64")
           / sub["avg_total_assets"].astype("float64"))
    out.index = sub["ts_code"].values
    out.name = "roa"
    return out


def coverage_at(signal_date: pd.Timestamp, pit_panel: pd.DataFrame,
                ts_codes: set[str]) -> dict:
    """ROA coverage among ts_codes at signal_date."""
    roa = compute_raw_roa(signal_date, pit_panel)
    n_total = len(ts_codes)
    if roa.empty or n_total == 0:
        return {"n_total": n_total, "n_with_roa": 0,
                "n_positive_roa": 0, "n_negative_roa": 0, "coverage": 0.0}
    roa_in = roa.reindex(list(ts_codes))
    n_with = int(roa_in.notna().sum())
    n_pos = int((roa_in > 0).sum())
    n_neg = int((roa_in < 0).sum())
    return {
        "n_total": n_total,
        "n_with_roa": n_with,
        "n_positive_roa": n_pos,
        "n_negative_roa": n_neg,
        "coverage": n_with / n_total if n_total else 0.0,
    }
