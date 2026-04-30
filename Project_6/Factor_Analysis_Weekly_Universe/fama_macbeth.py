"""
fama_macbeth.py — Fama-MacBeth cross-sectional regression on the rebuilt
weekly panel.

What this answers
-----------------
For each factor, what is the average premium per unit of cross-sectional
exposure, holding the other factors constant? Standard academic methodology
for disentangling overlapping factor signals.

Procedure (Brooks Ch3 multiple regression + Fama-MacBeth 1973)
--------------------------------------------------------------
1. For each rebalance date, regress next-week returns on z-scored factor
   exposures across the cross-section. One coefficient set per date.
2. Average each coefficient across dates. The average is the estimated
   factor premium.
3. t-statistic = time-series mean / time-series standard error.
4. Block bootstrap CI on each coefficient series for distribution-free
   inference, block_size=12 (~quarterly for weekly data) preserves
   the serial correlation we saw in single-factor coefficient series.

Sign convention
---------------
All four factors signed so POSITIVE coefficient = factor predicts
forward return in its single-factor expected direction.

  z_value  = +z(ep)         positive => cheap outperforms
  z_lowvol = -z(vol_52_4)   positive => low-vol outperforms
  z_size   = -z(log_mcap)   positive => small outperforms
  z_mom    = -z(mom_4_1)    positive => recent loser outperforms (reversal)

Logged predictions for the rebuilt panel
----------------------------------------
Phase B headlines:
  value:  BH-rejects in low+mid cap, IC=+0.0317 with CI excluding zero,
          Layer 4 t=-5.04. Very strong single-factor signal.
  mom_4_1: universal BH-rejection, IC=-0.0558, t=+4.84. Strongest signal of all.
  size:    headline null, but old monthly FMB had pre-stimulus z_size BH-rejecting.
           This is the "does it survive?" test of open item 5.
  lowvol:  IC=-0.0241 has signal, Q1-Q5 null. Marginal Layer 4. Weak.

FMB predictions:
  z_value:    +0.20 to +0.40 %/wk, t in [+3.0, +5.0]. Strongest single-factor
              should survive multivariate. CI almost certainly excludes zero.
  z_mom:      +0.20 to +0.40 %/wk, t in [+4.0, +6.0]. Universal cap effect
              should be additive over value because past return is largely
              orthogonal to current cheapness.
  z_lowvol:   +0.05 to +0.20 %/wk, t in [+1.0, +3.0]. The IC-significant
              effect should appear in FMB even when Q1-Q5 didn't capture it,
              because FMB is essentially a regression analog of IC with
              additional control for other factors.
  z_size:     near zero, t in [-1.0, +1.5]. Single-factor was null;
              the old pre-stimulus BH rejection may not survive larger sample.

Cross-correlation diagnostic predictions
  z_value vs z_lowvol:  +0.10 to +0.30 (cheap stocks tend less volatile)
  z_value vs z_size:    -0.10 to +0.10 (uncertain in our universe)
  z_value vs z_mom:     near zero
  z_lowvol vs z_size:   -0.30 to -0.10 (smaller stocks more volatile)
  z_lowvol vs z_mom:    +0.05 to +0.15
  z_size vs z_mom:      -0.10 to +0.10

Maximum off-diagonal expected: ~0.30. No severe multicollinearity.

Highest-confidence prediction: z_value AND z_mom both excluding zero in
headline FMB. If only one survives, the other absorbed it (partial
overlap). If neither survives, there's a strong common factor we're
missing. If both survive, segmented strategies are well-motivated.

Lowest-confidence: pre-stimulus z_size. Could go either direction.

Failure modes specific to FMB
-----------------------------
1. Multicollinearity. We expect max correlation ~0.30; if any pair exceeds
   0.7 the coefficients become individually meaningless and we'd need to
   drop a factor.
2. Per-date sample size. With 1000 in-universe stocks and 75% complete-
   cases coverage on the four factors, expect ~700 stocks per regression.
   Plenty of degrees of freedom. The constraint is dates, not stocks.
3. Time-series sample size. ~330 testable dates after burn-in for the
   52-week formation. t-stats df ~330; 5% two-sided cutoff |t|>1.97.
   CIs from block bootstrap are the right reference, not asymptotic-normal.
4. Layer 5 z_size collinearity. Within a cap tercile, log_mcap range is
   compressed and z_size becomes nearly constant, producing unstable
   coefficients. Standard fix: drop z_size for Layer 5 only.

Run from Project_6/:
    python Factor_Analysis_Weekly_Universe/fama_macbeth.py

Prerequisites
-------------
  - data/factor_panel_weekly.parquet (run factor_panel_builder.py full first)
  - hypothesis_testing.py on the path
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from config import (
    CANDIDATE_SPLITS,
    DATA_DIR,
    GRAPHS_DIR,
    MIN_STOCKS_PER_SECTOR,
    REGIME_EVENTS,
    SEED,
)
from factor_utils import (
    load_factor_panel,
    residualise_factor_per_date,
)
from multifactor_utils import (
    add_all_factors,
    fama_macbeth,
    print_summary_table,
    report_correlation_matrix,
    summarise_coefficients,
)


# ─── Configuration ──────────────────────────────────────────────────────

# Default factor horizons reflect Phase B findings.
LOWVOL_LOOKBACK = 52
LOWVOL_SKIP = 4
MOM_LOOKBACK = 4   # mom_4_1 — only momentum horizon with single-factor signal
MOM_SKIP = 1

FACTORS = ["z_value", "z_lowvol", "z_size", "z_mom"]

OUTPUT_PREFIX = "fama_macbeth"


# ─── Layer 2: Multi-candidate regime split ─────────────────────────────

def fmb_regime_split(panel: pd.DataFrame, factor_cols: list) -> None:
    """Run FMB at each candidate split date, report pre/post separately."""
    print(f"\n{'=' * 96}")
    print(f"Layer 2: Multi-candidate regime split FMB")
    print(f"  Candidates: {[name for name, _ in CANDIDATE_SPLITS]}")
    print('=' * 96)

    for split_name, split_date in CANDIDATE_SPLITS:
        print(f"\n  --- Candidate: {split_name} ({split_date.date()}) ---")
        pre = panel[panel["rebalance_date"] < split_date]
        post = panel[panel["rebalance_date"] >= split_date]
        for sub_name, sub_panel in [("PRE", pre), ("POST", post)]:
            coefs = fama_macbeth(sub_panel, factor_cols)
            if len(coefs) < 6:
                print(f"\n    {sub_name}: only {len(coefs)} dates, skipping.")
                continue
            summary = summarise_coefficients(coefs)
            print_summary_table(
                summary, f"{split_name} {sub_name} ({len(coefs)} dates)"
            )


# ─── Layer 4: Sector-neutralized FMB ───────────────────────────────────

def fmb_sector_neutral(panel: pd.DataFrame, factor_cols: list) -> None:
    """Residualise each factor on sector dummies per date, then run FMB."""
    print(f"\n{'=' * 96}")
    print("Layer 4: Sector-neutralised exposures (SW L1, PIT)")
    print('=' * 96)

    in_univ = panel[panel["in_universe"]].copy()
    in_univ = in_univ.dropna(subset=["l1_name"])
    print(f"  in-universe rows with sector mapping: "
          f"{len(in_univ):,} of {int(panel['in_universe'].sum()):,}")

    resid_cols = []
    for fc in factor_cols:
        out_col = f"{fc}_resid"
        in_univ = residualise_factor_per_date(
            in_univ, fc, "l1_name", output_col=out_col,
            min_stocks_per_sector=MIN_STOCKS_PER_SECTOR,
        )
        resid_cols.append(out_col)
    print(f"  Residualized {len(resid_cols)} factors on l1_name dummies.")

    # Re-stamp in_universe so fama_macbeth's filter passes.
    in_univ["in_universe"] = True

    coefs = fama_macbeth(in_univ, resid_cols)
    summary = summarise_coefficients(coefs)

    # Rename rows back to factor names for readability.
    rename_map = {f"{fc}_resid": fc for fc in factor_cols}
    summary = summary.rename(index=rename_map)
    print_summary_table(summary, f"Sector-neutralised ({len(coefs)} dates)")


# ─── Layer 5: Cap-tercile FMB ──────────────────────────────────────────

def fmb_cap_terciles(panel: pd.DataFrame, factor_cols: list) -> None:
    """Run FMB separately within each cap tercile. Drops z_size (collinear)."""
    print(f"\n{'=' * 96}")
    print("Layer 5: Cap-tercile conditioning")
    print('=' * 96)

    factors_no_size = [c for c in factor_cols if c != "z_size"]
    print(f"  Note: z_size dropped within terciles "
          f"(collinear with conditioning variable).")
    print(f"  Running FMB with {factors_no_size} per tercile.")

    df = panel[panel["in_universe"]].copy()
    df["cap_tercile"] = (
        df.groupby("rebalance_date")["log_mcap"]
        .transform(
            lambda s: pd.qcut(s, 3, labels=["low", "mid", "high"],
                              duplicates="drop")
        )
    )
    df = df.dropna(subset=["cap_tercile"])

    for tname in ["low", "mid", "high"]:
        sub = df[df["cap_tercile"] == tname]
        coefs = fama_macbeth(sub, factors_no_size)
        if len(coefs) < 6:
            print(f"\n  Tercile {tname}: only {len(coefs)} dates, skipping.")
            continue
        summary = summarise_coefficients(coefs)
        print_summary_table(summary, f"Tercile {tname} ({len(coefs)} dates)")


# ─── Plotting ──────────────────────────────────────────────────────────

def plot_coefficient_series(
    coefs: pd.DataFrame, factor_cols: list, save_path,
) -> None:
    """One coefficient time-series subplot per factor."""
    fig, axes = plt.subplots(
        len(factor_cols), 1, figsize=(11, 2.5 * len(factor_cols)),
        sharex=True,
    )
    for ax, col in zip(axes, factor_cols):
        s = coefs[col].dropna() * 100  # to %/wk
        ax.bar(s.index, s.values, width=5, alpha=0.65, color="steelblue")
        ax.axhline(0, color="black", linewidth=0.7)
        ax.axhline(s.mean(), color="firebrick", linestyle="--",
                   alpha=0.85, label=f"Mean = {s.mean():+.3f}%/wk")
        ax.set_title(f"FMB coefficient time-series: {col}")
        ax.set_ylabel("%/wk")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(alpha=0.3)
        for label, event_date in REGIME_EVENTS.items():
            ax.axvline(event_date, color="grey", linestyle="--",
                       alpha=0.5, linewidth=0.8)
    axes[-1].set_xlabel("Rebalance date")
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


# ─── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    panel = load_factor_panel()
    print(f"Panel loaded: {len(panel):,} rows, "
          f"{panel['rebalance_date'].nunique()} dates")
    print(f"  in-universe rows: {int(panel['in_universe'].sum()):,}")

    panel = add_all_factors(
        panel,
        vol_lookback=LOWVOL_LOOKBACK, vol_skip=LOWVOL_SKIP,
        mom_lookback=MOM_LOOKBACK, mom_skip=MOM_SKIP,
    )

    # Coverage diagnostic on complete-cases (all four factors observed)
    n_complete = panel.dropna(
        subset=FACTORS + ["forward_return"]
    ).shape[0]
    n_total = len(panel)
    print(f"\nComplete-cases coverage (all 4 factors + return observed): "
          f"{n_complete:,} / {n_total:,} ({n_complete/n_total*100:.1f}%)")

    iu = panel[panel["in_universe"]]
    n_iu_complete = iu.dropna(subset=FACTORS + ["forward_return"]).shape[0]
    print(f"  in-universe complete-cases: "
          f"{n_iu_complete:,} / {len(iu):,} "
          f"({n_iu_complete/len(iu)*100:.1f}%)")

    cov_per_date = (
        iu.dropna(subset=FACTORS + ["forward_return"])
        .groupby("rebalance_date").size()
    )
    print(f"  Per-date in-universe complete-cases count: "
          f"min {cov_per_date.min()}, "
          f"median {int(cov_per_date.median())}, "
          f"max {cov_per_date.max()}, "
          f"n_dates_with_data {len(cov_per_date)}")

    # Multicollinearity diagnostic
    report_correlation_matrix(panel, FACTORS)

    # Headline FMB
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
          f"min {int(coefs['n'].min())}, "
          f"median {int(coefs['n'].median())}, "
          f"max {int(coefs['n'].max())}")

    summary = summarise_coefficients(coefs)
    print_summary_table(summary, "HEADLINE: Pooled FMB")

    # Save outputs
    coef_path = DATA_DIR / f"{OUTPUT_PREFIX}_coefficients.csv"
    coefs.to_csv(coef_path)
    print(f"\nCoefficient time-series saved to: {coef_path}")

    summary_path = DATA_DIR / f"{OUTPUT_PREFIX}_summary.csv"
    summary.to_csv(summary_path)
    print(f"Summary saved to:                 {summary_path}")

    plot_path = GRAPHS_DIR / f"{OUTPUT_PREFIX}_coefficients.png"
    plot_coefficient_series(coefs, FACTORS, plot_path)
    print(f"Coefficient plot saved to:        {plot_path}")

    # Robustness layers
    fmb_regime_split(panel, FACTORS)
    fmb_sector_neutral(panel, FACTORS)
    fmb_cap_terciles(panel, FACTORS)

    print(f"\n{'=' * 96}")
    print("Fama-MacBeth analysis complete.")
    print('=' * 96)