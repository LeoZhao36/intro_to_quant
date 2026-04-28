"""
lowvol_analysis.py

Project 6 Session 5: low-volatility factor analysis pipeline.

Multi-horizon sweep analogous to momentum_analysis.py: runs vol_12_1,
vol_6_1, vol_3_1 in one execution and produces a cross-horizon
comparison table at the end.

vol_K_S = standard deviation of monthly forward returns over the past
K months, ending S months before the rebalance date. Larger values
mean a more volatile recent return path. The "low-vol anomaly" is the
empirical finding that lower-volatility stocks tend to outperform
higher-volatility stocks on a risk-adjusted basis (and often on an
absolute basis), opposite of what CAPM predicts.

Sign convention
---------------
Q1 = LOW volatility (least volatile recent path).
Q5 = HIGH volatility (most volatile recent path).

Low-vol hypothesis: Q1 > Q5 in future returns, i.e. Q1-Q5 > 0, IC < 0.
CAPM-style risk premium hypothesis: Q5 > Q1, i.e. Q1-Q5 < 0, IC > 0.

Logged prediction
-----------------
Q1-Q5 in [-0.2%, +1.5%]/mo at t in [-0.5, +2.5], IC in [-0.05, +0.01],
with most probability mass on POSITIVE Q1-Q5 / NEGATIVE IC. Higher
confidence than momentum (LSY 2019 documents a robust volatility
anomaly in China, and the lottery-preference mechanism is well-suited
to retail-dominated small caps), comparable to value's confidence.

Imputation handling (note vs. momentum)
---------------------------------------
For momentum, missing months in the formation window were filled
with the cross-sectional median because the factor is a cumulative
PRODUCT, where a missing month would otherwise drop a factor.
Median imputation is roughly bias-neutral for the cumulative product.

For volatility, the factor is a STANDARD DEVIATION. Imputing with
the cross-sectional median sits at the centre of the cross-section
by construction, contributing less dispersion than a real observation
would. Imputed stocks would systematically come out with artificially
low std and get sorted toward Q1, contaminating the test toward the
hypothesis we are testing for.

The cleaner alternative used here: same eligibility threshold (>= 75%
of formation-window months observed) but std computed on the OBSERVED
months only, via pandas rolling.std() with
min_periods=ceil(0.75 * lookback). No imputation enters the std
calculation itself. Stocks at exactly the 75% threshold for vol_12_1
have std computed on 9 observations instead of 12 (marginally noisier
estimate, but unbiased in the direction we care about).

Run from Project_6/ as: `python lowvol_analysis.py`
No data sourcing prerequisite.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from factor_utils import (
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


# Sweep configuration -----------------------------------------------------
HORIZON_CONFIGS = [
    (12, 1),  # vol_12_1: 12-month formation, the most stable estimator
    (6, 1),   # vol_6_1:  6-month formation
    (3, 1),   # vol_3_1:  3-month formation (very noisy with only 3 obs per std)
]

MIN_COVERAGE = 0.75

SUMMARY_CSV = DATA_DIR / "lowvol_horizons_summary.csv"


def add_volatility_to_panel(
    panel: pd.DataFrame,
    lookback: int,
    skip: int,
    min_coverage: float = MIN_COVERAGE,
    vol_col: str = None,
) -> pd.DataFrame:
    """
    Compute realised monthly volatility from forward_return inside the
    panel itself, using observed values only (no imputation).

    Uses pandas rolling().std() with min_periods, which computes std
    on whatever non-NaN values are inside the window as long as there
    are at least min_periods of them. Mirrors momentum's eligibility
    threshold (75% min coverage) but skips the median-imputation step
    because that step would bias std downward for imputed stocks.

    Parameters
    ----------
    panel : DataFrame from load_panel(), with rebalance_date, ts_code,
        forward_return.
    lookback : K in vol_K_S notation.
    skip : S in vol_K_S notation.
    min_coverage : minimum fraction of formation-window months that
        must be observed for a stock to be eligible at a given date.
    vol_col : optional column name. Defaults to f"vol_{lookback}_{skip}".

    Returns
    -------
    Panel with the volatility column added on (rebalance_date, ts_code).
    """
    if vol_col is None:
        vol_col = f"vol_{lookback}_{skip}"

    # Pivot to (date x stock) matrix of forward returns.
    fr_matrix = panel.pivot_table(
        index="rebalance_date",
        columns="ts_code",
        values="forward_return",
        aggfunc="mean",
    ).sort_index()

    # ceil ensures we round threshold UP, matching momentum's threshold.
    threshold = max(2, int(np.ceil(min_coverage * lookback)))

    # Rolling std on observed values, then shift forward by skip+1 to
    # align the formation window end (index i-skip-1) with row i.
    vol_wide = (
        fr_matrix
        .rolling(window=lookback, min_periods=threshold)
        .std()
        .shift(skip + 1)
    )

    # Stack and merge.
    vol_long = (
        vol_wide.stack()
        .rename(vol_col)
        .reset_index()
    )

    panel_out = panel.merge(
        vol_long,
        on=["rebalance_date", "ts_code"],
        how="left",
    )
    return panel_out


def run_one_horizon(
    panel_base: pd.DataFrame,
    lookback: int,
    skip: int,
    min_coverage: float,
) -> dict:
    """Add the vol column for (lookback, skip) and run all five layers."""
    name = f"vol_{lookback}_{skip}"
    label = f"volatility {lookback}-{skip} (std of past monthly returns)"

    print(f"\n\n{'#' * 76}")
    print(
        f"# Horizon: {name}  "
        f"(lookback={lookback}, skip={skip}, "
        f"min_coverage={min_coverage:.0%})"
    )
    print(f"{'#' * 76}")

    panel = add_volatility_to_panel(
        panel_base,
        lookback=lookback,
        skip=skip,
        min_coverage=min_coverage,
    )

    # Coverage diagnostics ---------------------------------------------------
    n_with_vol = int(panel[name].notna().sum())
    n_total = len(panel)
    coverage_pct = n_with_vol / n_total * 100
    print(
        f"  Coverage: {n_with_vol:,} of {n_total:,} rows ({coverage_pct:.1f}%)"
    )
    coverage_per_date = (
        panel.groupby("rebalance_date")[name]
        .apply(lambda s: s.notna().mean())
    )
    n_burn_in = int((coverage_per_date == 0).sum())
    n_test = int((coverage_per_date > 0).sum())
    if n_test > 0:
        cov_pos = coverage_per_date[coverage_per_date > 0]
        print(
            f"  Per-date coverage (where >0): "
            f"min {cov_pos.min()*100:.1f}%, "
            f"median {cov_pos.median()*100:.1f}%, "
            f"max {cov_pos.max()*100:.1f}%"
        )
    print(f"  Burn-in dates: {n_burn_in}; testable dates: {n_test}")

    # Volatility distribution sanity check ------------------------------------
    vol_clean = panel[name].dropna()
    if len(vol_clean) > 0:
        print(
            f"\n  {name} distribution (cross-section x time): "
            f"n={len(vol_clean):,}, "
            f"mean={vol_clean.mean()*100:.2f}%, "
            f"median={vol_clean.median()*100:.2f}%, "
            f"p5={vol_clean.quantile(0.05)*100:.2f}%, "
            f"p95={vol_clean.quantile(0.95)*100:.2f}%"
        )

    # Headline ---------------------------------------------------------------
    print(f"\n  --- Headline ---")
    quintiles = compute_quintile_series(panel, sort_col=name)
    headline = summarise_long_short(quintiles, "headline Q1-Q5")
    ic = compute_ic_series(panel, sort_col=name)
    print(f"  IC: mean={ic.mean():+.4f}, std={ic.std():.4f}, n={len(ic)}")
    print(
        f"  (For {name}: Q1 = LOW vol = least volatile; "
        f"Q5 = HIGH vol = most volatile.\n"
        f"   Low-vol hypothesis: Q1 > Q5, i.e. Q1-Q5 > 0, IC < 0.\n"
        f"   CAPM-style risk premium: Q5 > Q1, i.e. Q1-Q5 < 0, IC > 0.)"
    )

    # Plots ------------------------------------------------------------------
    plot_cumulative_quintiles(
        quintiles, label,
        save_path=GRAPHS_DIR / f"{name}_quintile_cumulative_returns.png",
    )
    plot_ic_series(
        ic, label,
        save_path=GRAPHS_DIR / f"{name}_ic_time_series.png",
    )

    # Robustness layers ------------------------------------------------------
    layer_1 = layer_1_bootstrap_ci(panel, factor_col=name)
    layer_2 = layer_2_regime_split(panel, factor_col=name)
    layer_3 = layer_3_tradable_only(panel, factor_col=name)
    layer_4 = layer_4_sector_neutral(panel, factor_col=name)
    layer_5 = layer_5_cap_terciles(panel, factor_col=name, cap_col="log_mcap")

    return {
        "name": name,
        "lookback": lookback,
        "skip": skip,
        "coverage_pct": coverage_pct,
        "n_test": n_test,
        "headline": headline,
        "ic_mean": float(ic.mean()),
        "ic_n": int(len(ic)),
        "layer_1": layer_1,
        "layer_2": layer_2,
        "layer_3": layer_3,
        "layer_4": layer_4,
        "layer_5": layer_5,
    }


def print_cross_horizon_table(all_results: list) -> None:
    """One-screen comparison across horizons."""
    print(f"\n\n{'=' * 110}")
    print(
        "Cross-horizon summary  "
        "(sign convention: Q1-Q5 > 0 = low-vol works, Q1-Q5 < 0 = high-vol risk premium)"
    )
    print('=' * 110)

    header = (
        f"{'Horizon':<10s} {'Cov%':>5s} {'NTest':>5s} | "
        f"{'Headline Q1-Q5':>22s} {'IC':>9s} | "
        f"{'Sec-neut Q1-Q5':>22s} | "
        f"{'Cap (lo / mid / hi)':>30s}"
    )
    print(header)
    print('-' * len(header))

    for r in all_results:
        h = r["headline"]
        if h.get("n", 0) > 0:
            head_str = f"{h['mean_monthly']*100:+.3f}% (t={h['t_stat']:+.2f})"
        else:
            head_str = "n/a"

        ic_str = f"{r['ic_mean']:+.4f}"

        l4 = r.get("layer_4")
        if l4 is not None and l4.get("n", 0) > 0:
            sn_str = f"{l4['mean_monthly']*100:+.3f}% (t={l4['t_stat']:+.2f})"
        else:
            sn_str = "n/a"

        l5 = r["layer_5"]
        cap_parts = []
        for tname in ["low", "mid", "high"]:
            t = l5.get(tname, {})
            if t.get("n", 0) > 0:
                cap_parts.append(f"{t['mean_monthly']*100:+.2f}")
            else:
                cap_parts.append("n/a")
        cap_str = " / ".join(cap_parts)

        print(
            f"{r['name']:<10s} {r['coverage_pct']:>4.1f}% {r['n_test']:>5d} | "
            f"{head_str:>22s} {ic_str:>9s} | "
            f"{sn_str:>22s} | "
            f"{cap_str:>30s}"
        )


def save_summary_csv(all_results: list, save_path: Path) -> None:
    """Persist the cross-horizon summary."""
    rows = []
    for r in all_results:
        h = r["headline"]
        l4 = r.get("layer_4") or {}
        l5 = r["layer_5"]
        rows.append({
            "horizon": r["name"],
            "lookback": r["lookback"],
            "skip": r["skip"],
            "coverage_pct": r["coverage_pct"],
            "n_test_dates": r["n_test"],
            "headline_q1q5_mo": h.get("mean_monthly"),
            "headline_q1q5_t": h.get("t_stat"),
            "headline_ic_mean": r["ic_mean"],
            "sector_neutral_q1q5_mo": l4.get("mean_monthly"),
            "sector_neutral_q1q5_t": l4.get("t_stat"),
            "cap_low_q1q5_mo": l5.get("low", {}).get("mean_monthly"),
            "cap_mid_q1q5_mo": l5.get("mid", {}).get("mean_monthly"),
            "cap_high_q1q5_mo": l5.get("high", {}).get("mean_monthly"),
            "cap_low_p": l5.get("low", {}).get("p_value"),
            "cap_mid_p": l5.get("mid", {}).get("p_value"),
            "cap_high_p": l5.get("high", {}).get("p_value"),
        })
    df = pd.DataFrame(rows)
    df.to_csv(save_path, index=False)
    print(f"\nSummary saved to {save_path}")


if __name__ == "__main__":
    panel_base = load_panel()
    print(
        f"Panel loaded: {len(panel_base):,} rows, "
        f"{panel_base['rebalance_date'].nunique()} dates"
    )
    print(
        f"Sweeping {len(HORIZON_CONFIGS)} horizons "
        f"with min_coverage={MIN_COVERAGE:.0%}"
    )

    all_results = []
    for lookback, skip in HORIZON_CONFIGS:
        result = run_one_horizon(
            panel_base,
            lookback=lookback,
            skip=skip,
            min_coverage=MIN_COVERAGE,
        )
        all_results.append(result)

    print_cross_horizon_table(all_results)
    save_summary_csv(all_results, SUMMARY_CSV)

    print(f"\n{'=' * 76}")
    print("Multi-horizon low-volatility factor analysis complete.")
    print('=' * 76)