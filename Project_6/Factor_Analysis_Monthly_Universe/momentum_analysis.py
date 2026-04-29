"""
momentum_analysis.py

Project 6 Session 4: momentum-factor analysis pipeline.

Multi-horizon sweep: runs mom_12_1, mom_6_1, mom_3_1, mom_1_1 in one
script execution and produces a cross-horizon comparison table at the end.

Coverage relaxation
-------------------
Stocks with at least min_coverage * lookback observed months in the
formation window are eligible. Missing months for those stocks are
filled with the cross-sectional median forward return for those dates
(computed across stocks that had data on those dates), then the
cumulative product is taken across the resulting fully-populated window.

Threshold rounding: pandas integer >= float threshold effectively
rounds the threshold UP. So mom_12_1 with min_coverage=0.75 requires
9 observed months (imputes up to 3); mom_6_1 requires 5 (imputes up
to 1); mom_3_1 requires 3 (no imputation possible, all-or-nothing);
mom_1_1 requires 1 (the single formation month must be observed).

Imputation introduces a small bias: out-of-universe stocks (which were
larger by market cap) likely had different returns from in-universe
stocks during their absences, but we fill with the in-universe
cross-sectional median. Documented as a known limitation. The clean
fix is a panel-construction improvement (full return histories for all
ts_codes that ever appeared, with the universe filter applied only at
the cross-sectional sort step) deferred until after all single-factor
tests and the first multi-factor analysis are complete.

Run from Project_6/ as: `python momentum_analysis.py`
No data sourcing prerequisite.

Sign convention
---------------
Q1 = LOW past return = recent losers.
Q5 = HIGH past return = recent winners.

Continuation: Q5 > Q1, i.e. Q1-Q5 < 0, IC > 0.
Reversal:     Q1 > Q5, i.e. Q1-Q5 > 0, IC < 0.

Logged predictions across all four horizons
-------------------------------------------
Most probability mass on POSITIVE Q1-Q5 / NEGATIVE IC (reversal),
with the strongest reversal expected at the shortest horizons (mom_1_1,
mom_3_1) per LSY's "any window" claim. Magnitudes likely larger at
shorter horizons because the overreaction-then-correction mechanism
operates on faster timescales.
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


# Sweep configuration -----------------------------------------------------
# Each tuple is (lookback, skip). Edit this list to change which horizons run.
HORIZON_CONFIGS = [
    (12, 1),  # mom_12_1: JT canonical
    (6, 1),   # mom_6_1:  medium-term
    (3, 1),   # mom_3_1:  short-term
    (1, 1),   # mom_1_1:  classic short-term reversal
]

# Minimum fraction of formation-window months that must have observed
# (non-imputed) forward returns for a stock to be eligible at a given date.
MIN_COVERAGE = 0.75

SUMMARY_CSV = DATA_DIR / "momentum_horizons_summary.csv"


def add_momentum_to_panel(
    panel: pd.DataFrame,
    lookback: int,
    skip: int,
    min_coverage: float = MIN_COVERAGE,
    momentum_col: str = None,
) -> pd.DataFrame:
    """
    Compute past-return momentum from forward_return inside the panel itself,
    with optional cross-sectional median imputation for stocks that meet the
    coverage threshold but have some missing months in the formation window.

    Parameters
    ----------
    panel : DataFrame from load_panel(), with rebalance_date, ts_code,
        forward_return.
    lookback : K in mom_K_S notation.
    skip : S in mom_K_S notation. JT 1993 uses skip=1.
    min_coverage : minimum fraction of formation-window months that must
        be observed (non-imputed) for a stock to be eligible at a given
        date. Default MIN_COVERAGE (0.75).
    momentum_col : optional column name. Defaults to f"mom_{lookback}_{skip}".

    Returns
    -------
    Panel with the momentum column added.
    """
    if momentum_col is None:
        momentum_col = f"mom_{lookback}_{skip}"

    # Pivot to (date x stock) matrix of forward returns.
    fr_matrix = panel.pivot_table(
        index="rebalance_date",
        columns="ts_code",
        values="forward_return",
        aggfunc="mean",
    ).sort_index()

    # Real-data indicator: 1.0 where observed, 0.0 where missing.
    is_observed = fr_matrix.notna().astype(float)

    # Cross-sectional median per date (computed across stocks with data).
    cs_median = fr_matrix.median(axis=1)

    # Impute: fill NaN cells with the cross-sectional median for that date.
    # Use the transpose pattern so fillna aligns the median series with
    # the (now-column-indexed) dates, broadcasting across stocks.
    fr_imputed = fr_matrix.T.fillna(cs_median).T

    # log(1+r) so cumulating becomes a rolling sum.
    log_returns = np.log1p(fr_imputed)

    # Rolling sum of log returns and rolling count of OBSERVED months,
    # both shifted forward by skip+1 to align with the formation window
    # ending at index i-skip-1 for date t_i.
    log_momentum = log_returns.rolling(lookback).sum().shift(skip + 1)
    observed_count = is_observed.rolling(lookback).sum().shift(skip + 1)

    # Mask: keep momentum only where observed_count >= threshold.
    threshold = min_coverage * lookback
    log_momentum_masked = log_momentum.where(observed_count >= threshold)

    # Convert log-cumulative return back to simple cumulative return.
    momentum_wide = np.expm1(log_momentum_masked)

    # Stack to long format and merge.
    momentum_long = (
        momentum_wide.stack()
        .rename(momentum_col)
        .reset_index()
    )

    panel_out = panel.merge(
        momentum_long,
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
    """
    Add the momentum column for (lookback, skip) and run the full five-layer
    machinery. Returns a dict of summary stats for the cross-horizon table.
    """
    name = f"mom_{lookback}_{skip}"
    label = f"momentum {lookback}-{skip} (cumulative past return)"

    print(f"\n\n{'#' * 76}")
    print(
        f"# Horizon: {name}  "
        f"(lookback={lookback}, skip={skip}, "
        f"min_coverage={min_coverage:.0%})"
    )
    print(f"{'#' * 76}")

    panel = add_momentum_to_panel(
        panel_base,
        lookback=lookback,
        skip=skip,
        min_coverage=min_coverage,
    )

    # Coverage diagnostics ---------------------------------------------------
    n_with_mom = int(panel[name].notna().sum())
    n_total = len(panel)
    coverage_pct = n_with_mom / n_total * 100
    print(
        f"  Coverage: {n_with_mom:,} of {n_total:,} rows ({coverage_pct:.1f}%)"
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

    # Headline ---------------------------------------------------------------
    print(f"\n  --- Headline ---")
    quintiles = compute_quintile_series(panel, sort_col=name)
    headline = summarise_long_short(quintiles, "headline Q1-Q5")
    ic = compute_ic_series(panel, sort_col=name)
    print(f"  IC: mean={ic.mean():+.4f}, std={ic.std():.4f}, n={len(ic)}")

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
        "(sign convention: Q1-Q5 < 0 = continuation, > 0 = reversal)"
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
    """Persist the cross-horizon summary for future reference."""
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
    print("Multi-horizon momentum-factor analysis complete.")
    print('=' * 76)