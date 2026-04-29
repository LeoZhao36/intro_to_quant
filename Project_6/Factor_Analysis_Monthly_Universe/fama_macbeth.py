"""
fama_macbeth.py

Project 6 multi-factor: Fama-MacBeth cross-sectional regression of
forward returns on z-scored factor exposures.

What this answers
-----------------
For each factor, what is the average premium per unit of cross-sectional
exposure, holding the other factors constant? Standard academic
methodology for disentangling overlapping factors.

Procedure (per Brooks Ch3 multiple regression, then time-series
inference on coefficients per Fama and MacBeth 1973):
  1. For each rebalance date t, regress next-month returns on this
     date's z-scored factor exposures across the cross-section.
     This produces one set of coefficients (b_value, b_lowvol, b_size,
     b_mom, intercept) per date.
  2. Average each coefficient across dates. The average is the
     estimated factor premium.
  3. t-statistic per factor is the time-series mean divided by the
     time-series standard error of the coefficients.
  4. Bootstrap CI on each premium for distribution-free inference,
     using block bootstrap matching the rest of the project.

Sign convention
---------------
All four factors signed so that POSITIVE coefficient = "factor predicts
forward return in its expected direction" per single-factor results.

z_value  = +z(ep)         positive coefficient => cheap stocks outperform
z_lowvol = -z(vol_12_1)   positive coefficient => low-vol stocks outperform
z_size   = -z(log_mcap)   positive coefficient => small stocks outperform
z_mom    = -z(mom_12_1)   positive coefficient => recent losers outperform (reversal)

Robustness layers (parallel to single-factor analysis)
------------------------------------------------------
Headline: pooled FMB on universe.
Layer 2: regime split at PBoC stimulus.
Layer 3: tradable-only filter.
Layer 4: sector-neutralised exposures (residualise z-scores on sector
         dummies before regression).
Layer 5: cap-tercile-conditional FMB (run regression separately within
         each tercile).

Logged predictions
------------------
z_value premium:  +0.30 to +0.70%/mo, t in [+1.5, +3.0].
                  Single-factor IC was significantly positive; should
                  survive multivariate.
z_lowvol premium: +0.20 to +0.60%/mo, t in [+1.0, +2.5].
                  Single-factor BH-rejected only in high-cap; pooled
                  result will be weaker than the segment.
z_size premium:   near zero, t in [-1.0, +1.0]. Single-factor null;
                  no reason to expect surprising marginal power.
z_mom premium:    slightly positive (reversal), t in [-0.5, +1.5].
                  IC was small-negative across horizons; reversal
                  direction is the prediction but expect weak.

Cross-correlation diagnostic: z_value-z_lowvol corr +0.227 (from prior
session). FMB will adjust: z_value premium MAY drop slightly versus
single-factor IC because the +0.23 overlap will be attributed jointly.

Intercept (Jensen's alpha equivalent): close to baseline mean return,
which over our panel is roughly +1.5%/mo (universe-equal-weight).
A near-zero intercept after controlling for factors would be the
unexpected finding ("factors fully explain returns"). A large intercept
means the cross-section has structure beyond our four factors.

Failure modes
-------------
1. Multicollinearity. If two z-scored factors are highly correlated
   (>0.7), their coefficients become unstable and uninterpretable.
   We check the correlation matrix at the start; +0.23 max from prior
   work suggests no severe issue, but verify.
2. Per-date sample size. Universe has up to 1000 stocks but composite
   coverage is ~21-30%. With 4 regressors, we need at least 4+1=5 obs;
   we have hundreds. Fine.
3. Time-series sample size. ~30-40 testable dates after burn-in.
   t-stats with df ~30 require |t| > 2.04 for two-sided 5%. CIs will
   be wide. Bootstrap mitigates asymptotic-normality assumptions.
4. Coefficient interpretation drift. If sector neutralisation
   meaningfully changes the coefficients, the un-neutralised version
   was capturing sector effects. We compare both.

Run from Project_6/ as: `python fama_macbeth.py`
Prerequisites: data/ep_panel.csv (run source_ep_data.py first)
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from Project_6.Factor_Analysis_Monthly_Universe.factor_utils import (
    DATA_DIR,
    GRAPHS_DIR,
    REGIME_EVENTS,
    REGIME_SPLIT_DATE,
    SEED,
    MIN_STOCKS_PER_SECTOR,
    load_panel,
    load_sector_map,
    residualise_factor_per_date,
)
from hypothesis_testing import block_bootstrap_ci
from Project_6.Factor_Analysis_Monthly_Universe.value_analysis import add_ep_to_panel
from Project_6.Factor_Analysis_Monthly_Universe.lowvol_analysis import add_volatility_to_panel
from Project_6.Factor_Analysis_Monthly_Universe.momentum_analysis import add_momentum_to_panel
from Project_6.Factor_Analysis_Monthly_Universe.composite_value_lowvol_analysis import cross_sectional_zscore


# Configuration ---------------------------------------------------------
LOWVOL_LOOKBACK = 12
LOWVOL_SKIP = 1
MOM_LOOKBACK = 12
MOM_SKIP = 1
MIN_COVERAGE = 0.75

FACTORS = ["z_value", "z_lowvol", "z_size", "z_mom"]

OUTPUT_PREFIX = "fama_macbeth"


# Factor construction ---------------------------------------------------

def add_all_factors(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Add all four z-scored factors to the panel with sign conventions
    aligned (positive coefficient = single-factor's expected direction).
    """
    vol_col = f"vol_{LOWVOL_LOOKBACK}_{LOWVOL_SKIP}"
    mom_col = f"mom_{MOM_LOOKBACK}_{MOM_SKIP}"

    # Add raw factor columns.
    panel = add_ep_to_panel(panel)
    panel = add_volatility_to_panel(
        panel, lookback=LOWVOL_LOOKBACK, skip=LOWVOL_SKIP,
        min_coverage=MIN_COVERAGE,
    )
    panel = add_momentum_to_panel(
        panel, lookback=MOM_LOOKBACK, skip=MOM_SKIP,
        min_coverage=MIN_COVERAGE,
    )

    # Z-scores.
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


# Regression engine -----------------------------------------------------

def run_one_cross_section(
    df_date: pd.DataFrame,
    factor_cols: list,
    return_col: str = "forward_return",
) -> dict:
    """
    Run one OLS regression for one rebalance date.
    Returns dict with intercept, per-factor coefficients, n, r_squared.
    """
    sub = df_date.dropna(subset=[return_col] + factor_cols)
    n = len(sub)
    if n < len(factor_cols) + 5:  # need degrees of freedom
        return None

    X = np.column_stack([np.ones(n)] + [sub[c].values for c in factor_cols])
    y = sub[return_col].values

    try:
        beta, residuals, rank, _ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        return None

    if rank < X.shape[1]:
        # Singular matrix; usually means one factor is constant.
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
    Run cross-sectional regression per rebalance date. Returns a
    DataFrame indexed by rebalance_date with one row per date and
    columns for intercept, each factor's coefficient, n, r_squared.
    """
    rows = []
    for date, group in panel.groupby("rebalance_date"):
        result = run_one_cross_section(group, factor_cols, return_col)
        if result is None:
            continue
        result["rebalance_date"] = date
        rows.append(result)
    df = pd.DataFrame(rows).set_index("rebalance_date").sort_index()
    return df


# Inference -------------------------------------------------------------

def summarise_coefficients(coef_df: pd.DataFrame) -> pd.DataFrame:
    """
    Time-series mean, std, t-stat, bootstrap CI per coefficient.
    Returns DataFrame indexed by factor name.
    """
    rows = []
    coef_cols = [c for c in coef_df.columns
                 if c not in ("n", "r_squared")]
    n_dates = len(coef_df)

    for col in coef_cols:
        s = coef_df[col].dropna()
        if len(s) < 6:
            continue
        mean = float(s.mean())
        std = float(s.std())
        t_stat = mean / (std / np.sqrt(len(s))) if std > 0 else np.nan
        boot = block_bootstrap_ci(
            s.values, np.mean,
            block_size=3, n_boot=5000, seed=SEED,
        )
        null = boot["boot_distribution"] - boot["estimate"]
        p_two = float(np.mean(np.abs(null) >= abs(boot["estimate"])))
        rows.append({
            "term": col,
            "n_dates": int(len(s)),
            "mean_mo": mean,
            "std_mo": std,
            "t_stat": t_stat,
            "ci_low": boot["ci_low"],
            "ci_high": boot["ci_high"],
            "boot_p": p_two,
        })
    return pd.DataFrame(rows).set_index("term")


def print_summary_table(summary: pd.DataFrame, label: str) -> None:
    print(f"\n{'=' * 96}")
    print(f"{label}")
    print('=' * 96)
    print(
        f"{'Term':<14s} {'NDates':>7s} {'Mean%/mo':>10s} {'Std%/mo':>9s} "
        f"{'t-stat':>8s}  {'95% CI':>22s} {'Boot p':>8s}"
    )
    print("-" * 96)
    for term, row in summary.iterrows():
        ci_str = f"[{row['ci_low']*100:+.3f}, {row['ci_high']*100:+.3f}]"
        contains_zero = row["ci_low"] <= 0 <= row["ci_high"]
        marker = "    " if contains_zero else " ** "
        print(
            f"{term:<14s} {int(row['n_dates']):>7d} "
            f"{row['mean_mo']*100:>+9.3f} {row['std_mo']*100:>+8.3f} "
            f"{row['t_stat']:>+8.2f}  {ci_str:>22s} {row['boot_p']:>7.3f}"
            f"{marker}"
        )
    print("  (** = bootstrap CI excludes zero)")


def report_correlation_matrix(panel: pd.DataFrame, factor_cols: list) -> None:
    """
    Cross-sectional correlation matrix of factor exposures, averaged
    across dates. Diagnostic for multicollinearity.
    """
    print(f"\nCross-sectional factor correlation matrix (averaged over dates):")
    aligned = panel.dropna(subset=factor_cols)
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


# Robustness layers -----------------------------------------------------

def fmb_regime_split(panel: pd.DataFrame, factor_cols: list,
                     split_date: pd.Timestamp) -> None:
    """Run FMB separately in pre and post regimes."""
    print(f"\n{'=' * 96}")
    print(f"Layer 2: Regime split at {split_date.date()} (PBoC stimulus)")
    print('=' * 96)
    pre = panel[panel["rebalance_date"] < split_date]
    post = panel[panel["rebalance_date"] >= split_date]
    for name, p in [("PRE-stimulus", pre), ("POST-stimulus", post)]:
        coefs = fama_macbeth(p, factor_cols)
        if len(coefs) < 6:
            print(f"\n{name}: only {len(coefs)} dates, skipping.")
            continue
        summary = summarise_coefficients(coefs)
        print_summary_table(summary, f"{name} ({len(coefs)} dates)")


def fmb_tradable_only(panel: pd.DataFrame, factor_cols: list) -> None:
    """Run FMB on tradable-only stocks."""
    print(f"\n{'=' * 96}")
    print("Layer 3: Tradable-only filter")
    print('=' * 96)
    tradable_mask = (
        panel["entry_tradable"].fillna(False)
        & panel["exit_tradable"].fillna(False)
    )
    p = panel[tradable_mask]
    coefs = fama_macbeth(p, factor_cols)
    summary = summarise_coefficients(coefs)
    print_summary_table(summary, f"Tradable-only ({len(coefs)} dates)")


def fmb_sector_neutral(panel: pd.DataFrame, factor_cols: list) -> None:
    """Residualise each factor on sector dummies per date, then run FMB."""
    print(f"\n{'=' * 96}")
    print("Layer 4: Sector-neutralised exposures")
    print('=' * 96)
    sector_map = load_sector_map()
    if sector_map is None:
        print("  Sector mapping unavailable; skipping.")
        return
    p = panel.merge(sector_map, on="ts_code", how="left")
    p = p.dropna(subset=["l1_code"]).copy()

    resid_cols = []
    for fc in factor_cols:
        out_col = f"{fc}_resid"
        p = residualise_factor_per_date(
            p, fc, "l1_code", output_col=out_col,
            min_stocks_per_sector=MIN_STOCKS_PER_SECTOR,
        )
        resid_cols.append(out_col)

    coefs = fama_macbeth(p, resid_cols)
    summary = summarise_coefficients(coefs)

    # Rename rows back to factor names for readability.
    rename_map = {f"{fc}_resid": fc for fc in factor_cols}
    summary = summary.rename(index=rename_map)
    print_summary_table(summary, f"Sector-neutralised ({len(coefs)} dates)")


def fmb_cap_terciles(panel: pd.DataFrame, factor_cols: list) -> None:
    """Run FMB separately within each cap tercile."""
    print(f"\n{'=' * 96}")
    print("Layer 5: Cap-tercile conditioning")
    print('=' * 96)

    # z_size is collinear with the conditioning variable inside terciles
    # (each tercile has compressed cap range), so we drop it for this
    # layer and report only the other three factors.
    factors_no_size = [c for c in factor_cols if c != "z_size"]
    print(f"  Note: z_size dropped within terciles (collinear with conditioning).")
    print(f"  Running with {factors_no_size}.")

    df = panel.copy()
    df["cap_tercile"] = (
        df.groupby("rebalance_date")["log_mcap"]
        .transform(
            lambda s: pd.qcut(s, 3, labels=["low", "mid", "high"], duplicates="drop")
        )
    )

    for tname in ["low", "mid", "high"]:
        sub = df[df["cap_tercile"] == tname]
        coefs = fama_macbeth(sub, factors_no_size)
        if len(coefs) < 6:
            print(f"\nTercile {tname}: only {len(coefs)} dates, skipping.")
            continue
        summary = summarise_coefficients(coefs)
        print_summary_table(summary, f"Tercile {tname} ({len(coefs)} dates)")


# Plotting --------------------------------------------------------------

def plot_coefficient_series(coefs: pd.DataFrame, factor_cols: list,
                             save_path: Path) -> None:
    """Plot each factor's coefficient time-series."""
    fig, axes = plt.subplots(
        len(factor_cols), 1, figsize=(11, 2.5 * len(factor_cols)),
        sharex=True,
    )
    for ax, col in zip(axes, factor_cols):
        s = coefs[col].dropna() * 100  # convert to %/mo
        ax.bar(s.index, s.values, width=20, alpha=0.65, color="steelblue")
        ax.axhline(0, color="black", linewidth=0.7)
        ax.axhline(s.mean(), color="firebrick", linestyle="--",
                   alpha=0.85, label=f"Mean = {s.mean():+.3f}%/mo")
        ax.set_title(f"FMB coefficient time-series: {col}")
        ax.set_ylabel("%/mo")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(alpha=0.3)
        for label, event_date in REGIME_EVENTS.items():
            ax.axvline(event_date, color="grey", linestyle="--",
                       alpha=0.5, linewidth=0.8)
    axes[-1].set_xlabel("Rebalance date")
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


# Main ------------------------------------------------------------------

if __name__ == "__main__":
    panel = load_panel()
    print(f"Panel loaded: {len(panel):,} rows, "
          f"{panel['rebalance_date'].nunique()} dates")

    panel = add_all_factors(panel)

    # Coverage diagnostic.
    n_complete = panel.dropna(subset=FACTORS + ["forward_return"]).shape[0]
    n_total = len(panel)
    print(f"\nComplete-cases coverage (all 4 factors + return observed): "
          f"{n_complete:,} / {n_total:,} ({n_complete/n_total*100:.1f}%)")

    cov_per_date = (
        panel.dropna(subset=FACTORS + ["forward_return"])
        .groupby("rebalance_date").size()
    )
    print(f"  Per-date complete-cases count: "
          f"min {cov_per_date.min()}, "
          f"median {cov_per_date.median():.0f}, "
          f"max {cov_per_date.max()}, "
          f"n_dates_with_data {len(cov_per_date)}")

    # Multicollinearity diagnostic.
    report_correlation_matrix(panel, FACTORS)

    # Headline FMB.
    print(f"\n{'=' * 96}")
    print("Headline: Fama-MacBeth on full universe")
    print('=' * 96)
    coefs = fama_macbeth(panel, FACTORS)
    print(f"\n  Regressions run: {len(coefs)} dates")
    print(f"  Cross-sectional R-squared: "
          f"mean {coefs['r_squared'].mean():.4f}, "
          f"median {coefs['r_squared'].median():.4f}, "
          f"std {coefs['r_squared'].std():.4f}")
    print(f"  Stocks per regression: "
          f"min {coefs['n'].min()}, "
          f"median {coefs['n'].median():.0f}, "
          f"max {coefs['n'].max()}")

    summary = summarise_coefficients(coefs)
    print_summary_table(summary, "HEADLINE: Pooled FMB")

    # Save outputs.
    coef_path = DATA_DIR / f"{OUTPUT_PREFIX}_coefficients.csv"
    coefs.to_csv(coef_path)
    print(f"\nCoefficient time-series saved to: {coef_path}")

    summary_path = DATA_DIR / f"{OUTPUT_PREFIX}_summary.csv"
    summary.to_csv(summary_path)
    print(f"Summary saved to:                 {summary_path}")

    plot_path = GRAPHS_DIR / f"{OUTPUT_PREFIX}_coefficients.png"
    plot_coefficient_series(coefs, FACTORS, plot_path)
    print(f"Coefficient plot saved to:        {plot_path}")

    # Robustness layers.
    fmb_regime_split(panel, FACTORS, REGIME_SPLIT_DATE)
    fmb_tradable_only(panel, FACTORS)
    fmb_sector_neutral(panel, FACTORS)
    fmb_cap_terciles(panel, FACTORS)

    print(f"\n{'=' * 96}")
    print("Fama-MacBeth analysis complete.")
    print('=' * 96)