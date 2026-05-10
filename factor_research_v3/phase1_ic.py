"""
phase1_ic.py — Cross-sectional Spearman IC for EP and ROA.

For each (factor, universe, signal_date):
  - Spearman rank correlation between the residualised factor at t
    and the realised forward open-to-open T+1 return.

Then aggregate per (factor, universe):
  - Mean IC, std, t-stat, hit rate (fraction of dates IC > 0)
  - 95% block bootstrap CI on the mean IC, block_size=3, n_boot=10000

Outputs:
  data/phase1_ic_summary.csv     # one row per (factor × universe)
  data/phase1_ic_per_date.csv    # one row per (factor × universe × date)
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import fr3_config as cfg
from hypothesis_testing import block_bootstrap_ci

FACTORS = [
    ("ep", "z_ep_resid"),
    ("roa", "z_roa_resid"),
]


def _ic_one(group: pd.DataFrame, factor_col: str) -> float:
    """Spearman IC on a per-(universe, signal_date) frame."""
    g = group.dropna(subset=[factor_col, "fwd_open_to_open"])
    if len(g) < 5:
        return np.nan
    rho, _ = spearmanr(g[factor_col], g["fwd_open_to_open"])
    return float(rho)


def compute_ics(panel: pd.DataFrame) -> pd.DataFrame:
    """
    For each (factor, universe, signal_date), compute Spearman rank IC.
    Returns long DataFrame: factor, universe, signal_date, ic, n_obs.
    """
    rows = []
    for factor_name, factor_col in FACTORS:
        for u in panel["universe"].unique():
            sub = panel[panel["universe"] == u]
            for s, g in sub.groupby("signal_date"):
                ic = _ic_one(g, factor_col)
                n = g[[factor_col, "fwd_open_to_open"]].dropna().shape[0]
                rows.append({
                    "factor": factor_name,
                    "universe": u,
                    "signal_date": s,
                    "ic": ic,
                    "n_obs": n,
                })
    return pd.DataFrame(rows)


def aggregate_ics(per_date: pd.DataFrame) -> pd.DataFrame:
    """Mean IC + bootstrap CI per (factor, universe)."""
    rows = []
    for (factor, universe), g in per_date.groupby(["factor", "universe"]):
        ics = g["ic"].dropna().values
        n = len(ics)
        if n < 2 * cfg.BOOT_BLOCK_SIZE:
            rows.append({
                "factor": factor,
                "universe": universe,
                "n_dates": n,
                "mean_ic": float(np.mean(ics)) if n else np.nan,
                "std_ic": float(np.std(ics, ddof=1)) if n > 1 else np.nan,
                "t_ic": np.nan,
                "hit_rate": float((ics > 0).mean()) if n else np.nan,
                "ic_ci_low": np.nan,
                "ic_ci_high": np.nan,
            })
            continue
        mean = float(np.mean(ics))
        std = float(np.std(ics, ddof=1))
        t_stat = mean / (std / np.sqrt(n)) if std > 0 else np.nan
        boot = block_bootstrap_ci(
            ics, np.mean,
            block_size=cfg.BOOT_BLOCK_SIZE,
            n_boot=cfg.BOOT_N,
            seed=42,
        )
        rows.append({
            "factor": factor,
            "universe": universe,
            "n_dates": n,
            "mean_ic": mean,
            "std_ic": std,
            "t_ic": float(t_stat),
            "hit_rate": float((ics > 0).mean()),
            "ic_ci_low": boot["ci_low"],
            "ic_ci_high": boot["ci_high"],
        })
    return pd.DataFrame(rows)


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not cfg.FACTOR_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"Factor panel missing: {cfg.FACTOR_PANEL_PATH}. Run factor_panel.py first."
        )
    panel = pd.read_parquet(cfg.FACTOR_PANEL_PATH)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])

    print("Phase 1 IC: computing per-date Spearman IC...")
    per_date = compute_ics(panel)
    per_date.to_csv(cfg.PHASE1_IC_PER_DATE_PATH, index=False)
    print(f"  saved per-date: {cfg.PHASE1_IC_PER_DATE_PATH}")

    print("Phase 1 IC: aggregating with block bootstrap (block_size=3, n_boot=10000)...")
    summary = aggregate_ics(per_date)
    summary.to_csv(cfg.PHASE1_IC_SUMMARY_PATH, index=False)
    print(f"  saved summary: {cfg.PHASE1_IC_SUMMARY_PATH}")

    print("\nIC summary:")
    print(summary.to_string(index=False))
    return summary, per_date


def main() -> None:
    run()


if __name__ == "__main__":
    main()
