"""
composite_value_lowvol.py

Project 6 multi-factor: equal-weighted z-score composite of value (EP)
and low-volatility (vol_12_1).

Why this composite, why these two factors
-----------------------------------------
Per single-factor closeout: value (EP) BH-rejects in the low-cap tercile;
low-vol (vol_12_1) BH-rejects in the high-cap tercile. Size and momentum
are noisy nulls in our universe, so we are not including them in the
first-pass composite. They will be added later as a robustness check.

Sign convention
---------------
z_value  = +zscore(ep)        (higher EP => cheaper => expected to outperform)
z_lowvol = -zscore(vol_12_1)  (lower vol => expected to outperform)

composite = z_value + z_lowvol  (equal weighting)

Reading the sort
----------------
Higher composite => cheaper AND lower-vol => expected outperformer.
After sorting, Q5 = highest composite = expected winners,
                Q1 = lowest composite  = expected losers.

"Working" direction (composite predicts forward returns):
   Q1-Q5 < 0 (Q5 outperforms Q1)
   IC > 0    (composite positively correlated with forward return)

This matches the value_analysis.py sign convention; it differs from
lowvol_analysis.py where the raw vol column was sorted with Q1=low-vol.

Logged predictions (record before reading output)
-------------------------------------------------
Headline composite Q1-Q5:
    Pooled universe: -0.4% to -1.0%/mo, t in [-2.0, -0.5]. Two complementary
    signals partially diluted by pooling across cap terciles.

Layer 5 (cap-tercile):
    Low-cap:  -1.0% to -1.5%/mo (value-dominated, slight low-vol contribution).
              BH-rejection plausible.
    High-cap: -1.2% to -2.0%/mo (low-vol-dominated). BH-rejection plausible.
    Mid-cap:  near zero (consistent with single-factor mid-cap nulls).

Layer 4 (sector-neutral):
    Strengthens vs headline. Both single factors strengthened under
    neutralization, so the composite should too.

Cross-sectional correlation z_value vs z_lowvol per date:
    Mildly positive, +0.05 to +0.20. Cheap stocks tend to be slightly
    less volatile in our universe (utilities, banks, etc.). Uncertain.

Highest-uncertainty prediction: the magnitude of within-tercile
improvement over the single-factor result in that tercile. If the
composite low-cap Q1-Q5 = -1.10% (matching single-factor value low-cap
exactly), low-vol added nothing in that tercile. If -1.50%, it added
real signal. Anywhere in between is ambiguous and bootstrap CIs will
need to drive the call.

Prerequisite
------------
data/ep_panel.csv must exist. Run `python source_ep_data.py` first.

Run from Project_6/ as: `python composite_value_lowvol.py`
"""

from pathlib import Path

import numpy as np
import pandas as pd

from Project_6.Factor_Analysis_Monthly_Universe.factor_utils import (
    DATA_DIR,
    GRAPHS_DIR,
    load_panel,
    compute_quintile_series,
    compute_ic_series,
    summarise_long_short,
    layer_1_bootstrap_ci,
    layer_2_regime_split,
    layer_3_tradable_only,
    layer_4_sector_neutral,
    layer_5_cap_terciles,
    plot_cumulative_quintiles,
    plot_ic_series,
)

# Reuse single-factor data prep functions to avoid duplication.
from Project_6.Factor_Analysis_Monthly_Universe.value_analysis import add_ep_to_panel
from Project_6.Factor_Analysis_Monthly_Universe.lowvol_analysis import add_volatility_to_panel


# ─── Configuration ─────────────────────────────────────────────────────

LOWVOL_LOOKBACK = 3   # vol_12_1: matches the BH-rejecting single-factor cell
LOWVOL_SKIP = 1
MIN_COVERAGE = 0.75    # matches single-factor analyses

WINSORIZE = True       # winsorize before z-scoring
WINSOR_LOW = 0.01
WINSOR_HIGH = 0.99

COMPOSITE_COL = "z_composite_v_lv"
FACTOR_LABEL = "value+lowvol composite (equal-weighted z)"
OUTPUT_PREFIX = "composite_v_lv"


# ─── Z-score utility ───────────────────────────────────────────────────

def cross_sectional_zscore(
    panel: pd.DataFrame,
    factor_col: str,
    out_col: str,
    date_col: str = "rebalance_date",
    winsorize: bool = WINSORIZE,
    low: float = WINSOR_LOW,
    high: float = WINSOR_HIGH,
) -> pd.DataFrame:
    """
    Add a cross-sectional z-score column to `panel`.

    For each rebalance_date, optionally winsorize at [low, high] percentiles,
    then compute (x - mean(x)) / std(x) where mean and std are taken across
    the cross-section at that date, ignoring NaNs.

    Stocks with NaN in factor_col remain NaN in out_col; pd.qcut and IC
    calculations drop them naturally downstream.
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


# ─── Composite construction ────────────────────────────────────────────

def add_composite_to_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Build the value+lowvol composite z-score column on panel.

    Adds: pe_ttm, ep (from EP panel)
          vol_{LOWVOL_LOOKBACK}_{LOWVOL_SKIP} (computed from forward returns)
          z_ep, z_vol  (cross-sectional z-scores per date)
          z_value      (= +z_ep, sign convention applied)
          z_lowvol     (= -z_vol)
          z_composite_v_lv (= z_value + z_lowvol)
    """
    vol_col = f"vol_{LOWVOL_LOOKBACK}_{LOWVOL_SKIP}"

    # Add raw factor columns.
    panel = add_ep_to_panel(panel)
    panel = add_volatility_to_panel(
        panel,
        lookback=LOWVOL_LOOKBACK,
        skip=LOWVOL_SKIP,
        min_coverage=MIN_COVERAGE,
    )

    # Cross-sectional z-scores per date (winsorized by default).
    panel = cross_sectional_zscore(panel, "ep", "z_ep")
    panel = cross_sectional_zscore(panel, vol_col, "z_vol")

    # Apply sign convention: each z-component points "expected to outperform".
    panel["z_value"]  = +panel["z_ep"]
    panel["z_lowvol"] = -panel["z_vol"]

    # Equal-weighted sum.
    panel[COMPOSITE_COL] = panel["z_value"] + panel["z_lowvol"]

    return panel


# ─── Diagnostics ───────────────────────────────────────────────────────

def report_coverage(panel: pd.DataFrame) -> None:
    """Coverage diagnostics for each factor and the composite."""
    vol_col = f"vol_{LOWVOL_LOOKBACK}_{LOWVOL_SKIP}"
    n_total = len(panel)
    n_ep = int(panel["ep"].notna().sum())
    n_vol = int(panel[vol_col].notna().sum())
    n_both = int((panel["ep"].notna() & panel[vol_col].notna()).sum())
    n_comp = int(panel[COMPOSITE_COL].notna().sum())

    print(f"\nComposite coverage diagnostics:")
    print(f"  EP observed:                {n_ep:>7,} / {n_total:,} ({n_ep/n_total*100:5.1f}%)")
    print(f"  Vol observed:               {n_vol:>7,} / {n_total:,} ({n_vol/n_total*100:5.1f}%)")
    print(f"  Both observed:              {n_both:>7,} / {n_total:,} ({n_both/n_total*100:5.1f}%)")
    print(f"  Composite (post z-score):   {n_comp:>7,} / {n_total:,} ({n_comp/n_total*100:5.1f}%)")

    cov_per_date = (
        panel.groupby("rebalance_date")[COMPOSITE_COL]
        .apply(lambda s: s.notna().mean())
    )
    n_burn = int((cov_per_date == 0).sum())
    n_test = int((cov_per_date > 0).sum())
    if n_test > 0:
        cov_pos = cov_per_date[cov_per_date > 0]
        print(
            f"  Per-date composite coverage (testable dates): "
            f"min {cov_pos.min()*100:.1f}%, "
            f"median {cov_pos.median()*100:.1f}%, "
            f"max {cov_pos.max()*100:.1f}%"
        )
    print(f"  Burn-in dates: {n_burn}; testable dates: {n_test}")


def report_zscore_sanity(panel: pd.DataFrame) -> None:
    """
    Verify each z-score column has approximately mean=0, std=1 per date.
    A failed sanity check usually means winsorization or NaN handling
    introduced an unexpected bias.
    """
    print(f"\nZ-score sanity (per-date moments, averaged across dates):")
    for col in ["z_ep", "z_vol"]:
        moments = panel.groupby("rebalance_date")[col].agg(["mean", "std"]).dropna()
        print(
            f"  {col:<10s}: "
            f"mean of date-means = {moments['mean'].mean():+.4f} (expect ~0), "
            f"mean of date-stds  = {moments['std'].mean():.4f} (expect ~1)"
        )

    moments_comp = (
        panel.groupby("rebalance_date")[COMPOSITE_COL]
        .agg(["mean", "std"]).dropna()
    )
    print(
        f"  {COMPOSITE_COL}: "
        f"mean of date-means = {moments_comp['mean'].mean():+.4f} (expect ~0), "
        f"mean of date-stds  = {moments_comp['std'].mean():.4f}"
    )


def report_factor_correlation(panel: pd.DataFrame) -> None:
    """
    Cross-sectional Pearson correlation between z_value and z_lowvol per date.
    Diagnostic for whether the composite genuinely combines two distinct
    signals or just rescales one. High |corr| (say >0.6) means the composite
    is mostly one factor in disguise; near-zero means truly independent.
    """
    corr_per_date = (
        panel.dropna(subset=["z_value", "z_lowvol"])
        .groupby("rebalance_date")
        .apply(
            lambda g: g["z_value"].corr(g["z_lowvol"]),
            include_groups=False,
        )
        .dropna()
    )
    print(
        f"\nCross-sectional correlation z_value vs z_lowvol per date:"
    )
    print(
        f"  mean   {corr_per_date.mean():+.3f}, "
        f"median {corr_per_date.median():+.3f}, "
        f"std    {corr_per_date.std():.3f}, "
        f"n={len(corr_per_date)}"
    )
    print(
        f"  min    {corr_per_date.min():+.3f}, "
        f"max    {corr_per_date.max():+.3f}"
    )
    print(
        f"  (Interpretation: |corr| near 0 => independent signals; "
        f"|corr| near 1 => composite is mostly one factor.)"
    )


# ─── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    panel = load_panel()
    print(
        f"Panel loaded: {len(panel):,} rows, "
        f"{panel['rebalance_date'].nunique()} dates"
    )

    panel = add_composite_to_panel(panel)

    print(f"\n{'=' * 76}")
    print(
        f"Composite construction: value (EP) + low-vol "
        f"(vol_{LOWVOL_LOOKBACK}_{LOWVOL_SKIP}), equal-weighted z-score"
    )
    print(f"  Sign convention: z_value = +z(ep), z_lowvol = -z(vol)")
    print(f"  Higher composite => cheaper AND lower-vol => expected outperformer")
    print(f"  Working direction: Q1-Q5 < 0, IC > 0")
    print(
        f"  Winsorization: "
        f"{'on at [' + format(WINSOR_LOW, '.0%') + ', ' + format(WINSOR_HIGH, '.0%') + ']' if WINSORIZE else 'off'}"
    )
    print(f"{'=' * 76}")

    report_coverage(panel)
    report_zscore_sanity(panel)
    report_factor_correlation(panel)

    # Headline ----------------------------------------------------------
    print("\n" + "=" * 72)
    print("Headline (composite Q1-Q5)")
    print("=" * 72)
    quintiles = compute_quintile_series(panel, sort_col=COMPOSITE_COL)
    headline = summarise_long_short(quintiles, "headline composite Q1-Q5")
    ic = compute_ic_series(panel, sort_col=COMPOSITE_COL)
    print(f"  IC: mean={ic.mean():+.4f}, std={ic.std():.4f}, n={len(ic)}")
    print(
        f"  (For composite: Q1 = LOW score = expensive AND high-vol; "
        f"Q5 = HIGH score = cheap AND low-vol.\n"
        f"   Working direction: Q5 > Q1, i.e. Q1-Q5 < 0, IC > 0.)"
    )

    # Plots -------------------------------------------------------------
    plot_cumulative_quintiles(
        quintiles, FACTOR_LABEL,
        save_path=GRAPHS_DIR / f"{OUTPUT_PREFIX}_quintile_cumulative_returns.png",
    )
    plot_ic_series(
        ic, FACTOR_LABEL,
        save_path=GRAPHS_DIR / f"{OUTPUT_PREFIX}_ic_time_series.png",
    )

    # Pass 1 robustness -------------------------------------------------
    layer_1 = layer_1_bootstrap_ci(panel, factor_col=COMPOSITE_COL)
    layer_2 = layer_2_regime_split(panel, factor_col=COMPOSITE_COL)
    layer_3 = layer_3_tradable_only(panel, factor_col=COMPOSITE_COL)

    # Pass 2 robustness -------------------------------------------------
    layer_4 = layer_4_sector_neutral(panel, factor_col=COMPOSITE_COL)
    layer_5 = layer_5_cap_terciles(
        panel, factor_col=COMPOSITE_COL, cap_col="log_mcap",
    )

    print("\n" + "=" * 76)
    print("Composite (value + low-vol) factor analysis complete.")
    print("=" * 76)