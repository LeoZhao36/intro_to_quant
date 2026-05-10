"""
flight_to_quality.py — ROA defense diagnostic.

For each (universe, top_n) of ROA results under headline cost:
  excess[period] = quality_basket_return_net - benchmark_return
  rho = Pearson correlation between excess and benchmark across γ periods
  95% block bootstrap CI on rho (block_size=3, n_boot=10000)

Interpretation:
  - rho < 0: ROA is a defense factor (excess inversely tied to regime)
  - rho > 0: pro-cyclical alpha
  - rho ≈ 0: pure factor alpha (uncorrelated with regime)

Required for the ROA defense-criterion verdict — without it, the quality
factor cannot be evaluated against pre-commit thresholds.

Output: data/flight_to_quality.csv (one row per (universe × top_n))
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import fr3_config as cfg
from hypothesis_testing import block_bootstrap_ci


def run() -> pd.DataFrame:
    if not cfg.PHASE2_PERIOD_RETURNS_PATH.exists():
        raise FileNotFoundError(
            f"Phase 2 period returns missing: {cfg.PHASE2_PERIOD_RETURNS_PATH}. "
            f"Run phase2_backtest.py first."
        )
    pr = pd.read_csv(cfg.PHASE2_PERIOD_RETURNS_PATH)

    # Filter to ROA × headline cost only
    roa = pr[(pr["factor"] == "roa") & (pr["cost_regime"] == "headline")].copy()
    if roa.empty:
        print("No ROA × headline rows in phase2_period_returns; nothing to test.")
        return pd.DataFrame()

    rows = []
    for (u, n), g in roa.groupby(["universe", "top_n"]):
        g = g.sort_values("signal_date")
        bench = g["benchmark_return"].values
        net = g["basket_return_net"].values
        excess = net - bench
        # Mask NaN
        mask = ~(np.isnan(bench) | np.isnan(excess))
        bench, excess = bench[mask], excess[mask]
        n_periods = len(bench)
        if n_periods < 2 * cfg.BOOT_BLOCK_SIZE:
            rows.append({
                "universe": u, "top_n": n, "n_periods": n_periods,
                "rho_pearson": np.nan,
                "rho_ci_low": np.nan, "rho_ci_high": np.nan,
                "interpretation": "insufficient data",
            })
            continue

        rho_point = float(np.corrcoef(excess, bench)[0, 1])

        # Block bootstrap CI on Pearson rho. We need to resample paired
        # (excess, bench) blocks together so the correlation is well-defined.
        rng = np.random.default_rng(42)
        block_size = cfg.BOOT_BLOCK_SIZE
        max_start = n_periods - block_size
        n_blocks = (n_periods + block_size - 1) // block_size
        offsets = np.arange(block_size)
        boot_rhos = np.empty(cfg.BOOT_N)
        for b in range(cfg.BOOT_N):
            starts = rng.integers(0, max_start + 1, size=n_blocks)
            idx = (starts[:, None] + offsets[None, :]).ravel()[:n_periods]
            e_resamp = excess[idx]
            b_resamp = bench[idx]
            if np.std(e_resamp) == 0 or np.std(b_resamp) == 0:
                boot_rhos[b] = np.nan
            else:
                boot_rhos[b] = np.corrcoef(e_resamp, b_resamp)[0, 1]
        valid = boot_rhos[~np.isnan(boot_rhos)]
        if len(valid) < 100:
            ci_low, ci_high = np.nan, np.nan
        else:
            ci_low, ci_high = np.quantile(valid, [0.025, 0.975])

        if rho_point < 0 and ci_high < 0:
            interp = "defense (significant)"
        elif rho_point < 0:
            interp = "defense (point estimate, CI spans 0)"
        elif rho_point > 0 and ci_low > 0:
            interp = "pro-cyclical (significant)"
        elif rho_point > 0:
            interp = "pro-cyclical (point estimate, CI spans 0)"
        else:
            interp = "pure alpha (≈0)"

        rows.append({
            "universe": u, "top_n": n, "n_periods": n_periods,
            "rho_pearson": rho_point,
            "rho_ci_low": float(ci_low),
            "rho_ci_high": float(ci_high),
            "interpretation": interp,
        })

    out = pd.DataFrame(rows)
    out.to_csv(cfg.FLIGHT_TO_QUALITY_PATH, index=False)
    print(f"Saved: {cfg.FLIGHT_TO_QUALITY_PATH}")
    print(out.to_string(index=False))
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
