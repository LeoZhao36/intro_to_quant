"""
multifactor_utils.py — Multi-factor engine for FMB and composite analyses.

Provides:
  - add_all_factors:        port of the old add_all_factors with new defaults
                             (vol_52_4, mom_4_1) reflecting Phase B findings
  - run_one_cross_section:  per-date OLS regression
  - fama_macbeth:           loop run_one_cross_section across dates
  - summarise_coefficients: time-series inference on coefficients
  - print_summary_table:    formatted output
  - report_correlation_matrix: multicollinearity diagnostic

Default factor set
------------------
After Phase B, the four-factor set with their best single-factor signals is:

  z_value  = +z(ep)              cheap outperforms (BH-rejects low+mid cap)
  z_lowvol = -z(vol_52_4)        weak — IC has signal, Q1-Q5 didn't
  z_size   = -z(log_mcap)        null at headline; was BH-rejected in old FMB
                                  (open question whether this reproduces)
  z_mom    = -z(mom_4_1)         short-term reversal, universal BH-rejection

All four sign-aligned so positive coefficient = factor's predicted direction.
Note: z_mom uses mom_4_1 (1-month formation, 1-week skip), not mom_52_4,
because the long-horizon momentum was a clean null. Using mom_4_1 in FMB
is the only choice that gives the multivariate test a fighting chance.

In-universe filter
------------------
The cross-sectional regression runs on in-universe rows only. The
candidate-history panel architecture means signals (vol, mom) are computed
on full daily history, but the sort eligibility / regression sample is
in-universe. This is the architectural fix for the universe-turnover
bias from the original Project 6 panel.
"""

import numpy as np
import pandas as pd

from hypothesis_testing import block_bootstrap_ci

from config import (
    BOOT_BLOCK_SIZE,
    BOOT_N,
    MIN_COVERAGE,
    SEED,
)
from factor_utils import cross_sectional_zscore
from lowvol_analysis import add_volatility_to_panel
from momentum_analysis import add_momentum_to_panel


# ─── Factor construction ────────────────────────────────────────────────

def add_all_factors(
    panel: pd.DataFrame,
    vol_lookback: int = 52,
    vol_skip: int = 4,
    mom_lookback: int = 4,
    mom_skip: int = 1,
    min_coverage: float = MIN_COVERAGE,
) -> pd.DataFrame:
    """
    Add all four sign-aligned z-score factors to the panel.

    Defaults reflect Phase B findings: vol_52_4 is the canonical low-vol
    horizon (and the closest to a tradable signal); mom_4_1 is the only
    momentum horizon with detectable signal.

    Sign convention: all four factors signed so that POSITIVE coefficient
    means "factor predicts forward return in its expected direction".
        z_value  = +z(ep)         positive => cheap outperforms
        z_lowvol = -z(vol_K_S)    positive => low-vol outperforms
        z_size   = -z(log_mcap)   positive => small outperforms
        z_mom    = -z(mom_K_S)    positive => recent loser outperforms (reversal)
    """
    vol_col = f"vol_{vol_lookback}_{vol_skip}"
    mom_col = f"mom_{mom_lookback}_{mom_skip}"

    # Compute raw factors (vol, mom). EP is already in the panel from
    # factor_panel_builder.py; log_mcap is too.
    panel = add_volatility_to_panel(
        panel, lookback=vol_lookback, skip=vol_skip, min_coverage=min_coverage,
    )
    panel = add_momentum_to_panel(
        panel, lookback=mom_lookback, skip=mom_skip, min_coverage=min_coverage,
    )

    # Cross-sectional z-scores per date.
    panel = cross_sectional_zscore(panel, "ep", "z_ep")
    panel = cross_sectional_zscore(panel, vol_col, "z_vol")
    panel = cross_sectional_zscore(panel, "log_mcap", "z_logmcap")
    panel = cross_sectional_zscore(panel, mom_col, "z_mom_raw")

    # Sign-align: positive coefficient = predicted-outperform direction.
    panel["z_value"]  = +panel["z_ep"]
    panel["z_lowvol"] = -panel["z_vol"]
    panel["z_size"]   = -panel["z_logmcap"]
    panel["z_mom"]    = -panel["z_mom_raw"]

    return panel


# ─── Regression engine ──────────────────────────────────────────────────

def run_one_cross_section(
    df_date: pd.DataFrame,
    factor_cols: list,
    return_col: str = "forward_return",
) -> dict | None:
    """
    Run one OLS regression for one rebalance date.

    Drops rows with NaN in return_col or any factor_col, then regresses
    return_col on a constant + factor_cols. Returns dict with intercept,
    per-factor coefficient, n, r_squared. Returns None if the cross-section
    is too thin or the design matrix is singular.
    """
    sub = df_date.dropna(subset=[return_col] + factor_cols)
    n = len(sub)
    if n < len(factor_cols) + 5:  # need degrees of freedom
        return None

    X = np.column_stack([np.ones(n)] + [sub[c].values for c in factor_cols])
    y = sub[return_col].values

    try:
        beta, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        return None

    if rank < X.shape[1]:
        # Singular: usually means one factor is constant within this date.
        return None

    y_hat = X @ beta
    ss_res = float(((y - y_hat) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan

    out = {"intercept": float(beta[0]), "n": int(n), "r_squared": r_squared}
    for i, col in enumerate(factor_cols):
        out[col] = float(beta[i + 1])
    return out


def fama_macbeth(
    panel: pd.DataFrame,
    factor_cols: list,
    return_col: str = "forward_return",
) -> pd.DataFrame:
    """
    Run cross-sectional regression per rebalance_date on in-universe stocks.

    Returns a DataFrame indexed by rebalance_date with columns for
    intercept, each factor's coefficient, n, r_squared. The time-series
    of coefficients is the input to summarise_coefficients() for inference.
    """
    df = panel[panel["in_universe"]]
    rows = []
    for date, group in df.groupby("rebalance_date"):
        result = run_one_cross_section(group, factor_cols, return_col)
        if result is None:
            continue
        result["rebalance_date"] = date
        rows.append(result)
    return pd.DataFrame(rows).set_index("rebalance_date").sort_index()


# ─── Inference ──────────────────────────────────────────────────────────

def summarise_coefficients(coef_df: pd.DataFrame) -> pd.DataFrame:
    """
    Time-series mean, t-stat, and block-bootstrap CI per coefficient.

    Bootstrap is skipped (NaN CI) when the coefficient series has fewer
    than 2 * BOOT_BLOCK_SIZE observations — block bootstrap requires
    this minimum. Mean and t-stat are still reported so thin sub-sample
    cells (pre-COVID-lockdown FMB has ~13 weeks) produce informative
    output rather than crashing.
    """
    rows = []
    coef_cols = [c for c in coef_df.columns if c not in ("n", "r_squared")]

    for col in coef_cols:
        s = coef_df[col].dropna()
        if len(s) < 6:
            continue
        mean = float(s.mean())
        std = float(s.std())
        t_stat = mean / (std / np.sqrt(len(s))) if std > 0 else np.nan

        if len(s) >= 2 * BOOT_BLOCK_SIZE:
            boot = block_bootstrap_ci(
                s.values, np.mean,
                block_size=BOOT_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
            )
            null = boot["boot_distribution"] - boot["estimate"]
            p_two = float(np.mean(np.abs(null) >= abs(boot["estimate"])))
            ci_low = boot["ci_low"] * 100
            ci_high = boot["ci_high"] * 100
        else:
            ci_low = np.nan
            ci_high = np.nan
            p_two = np.nan

        rows.append({
            "term": col,
            "n_dates": int(len(s)),
            "mean_pct_wk": mean * 100,
            "std_pct_wk": std * 100,
            "t_stat": t_stat,
            "ci_low_pct_wk": ci_low,
            "ci_high_pct_wk": ci_high,
            "boot_p": p_two,
        })
    return pd.DataFrame(rows).set_index("term")


def print_summary_table(summary: pd.DataFrame, label: str) -> None:
    """Formatted FMB summary output; handles NaN CIs from thin sub-samples."""
    print(f"\n{'=' * 96}")
    print(f"{label}")
    print('=' * 96)
    print(
        f"{'Term':<14s} {'NDates':>7s} {'Mean%/wk':>10s} {'Std%/wk':>9s} "
        f"{'t-stat':>8s}  {'95% CI':>22s} {'Boot p':>8s}"
    )
    print("-" * 96)
    for term, row in summary.iterrows():
        if pd.isna(row['ci_low_pct_wk']):
            ci_str = "(n<24, no boot)"
            marker = "    "
            p_str = "n/a"
        else:
            ci_str = f"[{row['ci_low_pct_wk']:+.3f}, {row['ci_high_pct_wk']:+.3f}]"
            contains_zero = row["ci_low_pct_wk"] <= 0 <= row["ci_high_pct_wk"]
            marker = "    " if contains_zero else " ** "
            p_str = f"{row['boot_p']:>7.3f}"
        print(
            f"{term:<14s} {int(row['n_dates']):>7d} "
            f"{row['mean_pct_wk']:>+9.3f} {row['std_pct_wk']:>+8.3f} "
            f"{row['t_stat']:>+8.2f}  {ci_str:>22s} {p_str:>8s}"
            f"{marker}"
        )
    print("  (** = bootstrap CI excludes zero)")


def report_correlation_matrix(panel: pd.DataFrame, factor_cols: list) -> None:
    """
    Cross-sectional correlation matrix of factor exposures, averaged across
    dates. Diagnostic for multicollinearity (>0.7 is a yellow flag).
    """
    print(f"\nCross-sectional factor correlation matrix (averaged over dates):")
    df = panel[panel["in_universe"]]
    aligned = df.dropna(subset=factor_cols)
    corr_per_date = (
        aligned.groupby("rebalance_date")[factor_cols]
        .corr().reset_index()
    )
    avg_corr = corr_per_date.groupby("level_1")[factor_cols].mean()
    avg_corr = avg_corr.reindex(factor_cols)[factor_cols]
    print(avg_corr.round(3).to_string())
    max_offdiag = (
        avg_corr.abs().where(~np.eye(len(factor_cols), dtype=bool))
        .max().max()
    )
    print(f"\n  Max absolute off-diagonal correlation: {max_offdiag:.3f}")
    if max_offdiag > 0.7:
        print(f"  Warning: high correlation (>0.7) implies multicollinearity.")
    else:
        print(f"  No severe multicollinearity issue.")