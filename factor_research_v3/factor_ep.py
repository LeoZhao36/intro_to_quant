"""
factor_ep.py — Raw EP construction.

EP = 1 / pe_ttm where pe_ttm > 0, NaN otherwise.

We source pe_ttm from the cached daily_basic via multi_factor_x1/daily_panel/.
Repo precedent (Project_6/New_Universe_Construction/validate_pe_ttm.py)
empirically confirmed that daily_basic.pe_ttm is PIT-clean, with clean
step behaviour at earnings announcement dates.

Negative-EP handling per Q1 of the plan: drop (set NaN). Loss-making
stocks have undefined economic value yield; sign-flipping inverts the
economic meaning.

Public API:
    compute_raw_ep(date) -> Series indexed by ts_code, value = EP or NaN
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import data_loaders as dl


def compute_raw_ep(date: pd.Timestamp) -> pd.Series | None:
    """
    EP = 1 / pe_ttm at the given trade_date. NaN where pe_ttm <= 0.

    Returns a Series indexed by ts_code, name='ep'. None if the daily
    panel is missing for this date.
    """
    pe = dl.load_pe_ttm(date)
    if pe is None:
        return None
    pe = pe.astype("float64")
    ep = pd.Series(np.where(pe > 0, 1.0 / pe, np.nan),
                   index=pe.index, name="ep")
    return ep


def coverage_at(date: pd.Timestamp, ts_codes: set[str]) -> dict:
    """
    Compute pe_ttm coverage among ts_codes at date.
    Returns {n_total, n_with_pe_ttm, n_positive_ep, n_negative_ep, coverage}.
    """
    pe = dl.load_pe_ttm(date)
    if pe is None:
        return {"n_total": len(ts_codes), "n_with_pe_ttm": 0,
                "n_positive_ep": 0, "n_negative_ep": 0, "coverage": 0.0}
    pe_in = pe.reindex(list(ts_codes))
    n_total = len(ts_codes)
    n_with = int(pe_in.notna().sum())
    n_pos = int((pe_in > 0).sum())
    n_neg = int((pe_in <= 0).sum())
    return {
        "n_total": n_total,
        "n_with_pe_ttm": n_with,
        "n_positive_ep": n_pos,
        "n_negative_ep": n_neg,
        # Data-quality coverage: any pe_ttm reading present (positive or
        # negative). Negative readings are valid data; we just drop them
        # at the EP construction step.
        "coverage": n_with / n_total if n_total else 0.0,
        # Tradable-EP coverage: only positive readings (these become
        # actual EP factor values).
        "tradable_coverage": n_pos / n_total if n_total else 0.0,
    }
