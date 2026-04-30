"""
momentum_analysis.py — Momentum factor (cumulative past return) on the
rebuilt weekly panel. Multi-horizon sweep across mom_52_4, mom_26_4,
mom_13_4, and mom_4_1.

Architectural change vs old monthly code
-----------------------------------------
The old `add_momentum_to_panel` imputed missing months in the formation
window with the cross-sectional median, because the universe-turnover
bias meant stocks transitioning into the universe had no formation-
window data. That hack introduced documented bias.

The rebuilt candidate-history panel gives every candidate stock its
full daily price history, so we compute momentum directly on observed
weekly returns with a coverage threshold. No imputation. Stocks below
75% coverage of the formation window get NaN momentum and drop out of
the sort. The headline impact: momentum signal quality should be
materially cleaner than the old monthly result, especially for stocks
that were transitioning in/out of the universe in their formation window.

Sign convention
---------------
Q1 = LOW past return (recent losers).
Q5 = HIGH past return (recent winners).

Continuation: Q5 > Q1, Q1-Q5 < 0 / IC > 0.
Reversal:     Q1 > Q5, Q1-Q5 > 0 / IC < 0.

Horizons swept
--------------
mom_52_4: 52-week formation, 4-week skip ≈ 12-month / 1-month (canonical)
mom_26_4: 26-week formation, 4-week skip ≈ 6-month / 1-month
mom_13_4: 13-week formation, 4-week skip ≈ 3-month / 1-month
mom_4_1:  4-week formation, 1-week skip ≈ short-term-reversal canonical

The skip is in weeks; for the 12-month-equivalent horizon we use 4
weeks (~1 month) to match the standard "skip the most recent month
to avoid bid-ask bounce" convention from Jegadeesh-Titman 1993 and the
LSY 2019 China replication.

Reference (old monthly result on 51 months, 2022-2026)
------------------------------------------------------
Most horizons: noisy nulls. mom_12_1 headline was a small null with
some hint of weak reversal. The strongest signal was at mom_1_1
(short-term reversal), consistent with LSY's "any window" claim that
A-share momentum operates more as reversal than continuation.

Logged predictions for the rebuilt panel
----------------------------------------
Direction-uncertain at long horizons; short-horizon reversal
(mom_4_1) most likely to show signal.

  mom_52_4 (long): Q1-Q5 in [-0.10%, +0.20%]/wk, IC in [-0.01, +0.02].
                   Most probability mass on weak reversal or null.
  mom_26_4 (med):  similar to mom_52_4.
  mom_13_4 (med):  slightly stronger reversal; Q1-Q5 in [+0.00%, +0.20%]/wk.
  mom_4_1 (STR):   Q1-Q5 in [+0.10%, +0.40%]/wk, IC negative.
                   Highest-confidence horizon to show signal.

Layer 2: pre-COVID growth-rally years may show continuation
         (winners kept winning). Post-2024-stimulus may show reversal.
         Layer expected to disagree across candidates.
Layer 4: little expected change vs headline. Sector concentration in
         past returns is moderate but not dominant.
Layer 5: cap-tercile interesting because mom_4_1 reversal in small caps
         is a known retail-overreaction phenomenon. Low-cap could
         BH-reject at mom_4_1 even if other terciles fail.

Failure modes specific to momentum
----------------------------------
1. Reversal vs continuation is regime-dependent. Bull markets favor
   continuation, bear markets and choppy periods favor reversal. Pooling
   across both produces noise. Layer 2 should surface this.
2. Coverage at long horizons. mom_52_4 needs >=39 observed weeks in the
   trailing 52-week formation. IPOs younger than ~10 months get NaN.
   Late-panel coverage on long horizons may thin if many recent IPOs
   entered the universe.
3. The skip parameter prevents bid-ask-bounce contamination but reduces
   signal recency. mom_4_1 with skip=1 is more aggressive about recency
   and may be more susceptible to microstructure noise than the
   skip=4 horizons.

Run from Project_6/:
    python Factor_Analysis_Weekly_Universe/momentum_analysis.py
"""

import numpy as np
import pandas as pd

from config import DATA_DIR, GRAPHS_DIR, MIN_COVERAGE
from factor_utils import (
    load_factor_panel,
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
    report_coverage_by_year,
    collect_factor_results,
)


# ─── Sweep configuration ────────────────────────────────────────────────

HORIZON_CONFIGS = [
    (52, 4),   # mom_52_4: 12-month formation, 1-month skip (canonical)
    (26, 4),   # mom_26_4: 6-month formation, 1-month skip
    (13, 4),   # mom_13_4: 3-month formation, 1-month skip
    (4, 1),    # mom_4_1:  short-term reversal canonical
]

OUTPUT_PREFIX = "momentum"
SUMMARY_CSV = DATA_DIR / f"single_factor_{OUTPUT_PREFIX}_results.csv"


# ─── Factor construction ────────────────────────────────────────────────

def add_momentum_to_panel(
    panel: pd.DataFrame,
    lookback: int,
    skip: int,
    min_coverage: float = MIN_COVERAGE,
    momentum_col: str | None = None,
) -> pd.DataFrame:
    """
    Compute cumulative-past-return momentum on observed weekly returns.

    No imputation: stocks below the coverage threshold get NaN.
    Mathematically: momentum = exp(sum(log(1+r))) - 1, computed on the
    rolling formation window with min_periods enforcing the coverage
    threshold. Pandas rolling.sum() skips NaN values within the window
    when min_periods is met, which is what we want — a stock with 50
    observed and 2 missing weeks in its 52-week window gets a 50-week
    cumulative return, slightly noisier than 52 but unbiased.
    """
    if momentum_col is None:
        momentum_col = f"mom_{lookback}_{skip}"

    fr_matrix = panel.pivot_table(
        index="rebalance_date",
        columns="ts_code",
        values="forward_return",
        aggfunc="mean",
    ).sort_index()

    threshold = max(2, int(np.ceil(min_coverage * lookback)))

    log_returns = np.log1p(fr_matrix)
    log_momentum = (
        log_returns.rolling(window=lookback, min_periods=threshold)
        .sum()
        .shift(skip + 1)
    )
    momentum_wide = np.expm1(log_momentum)

    momentum_long = (
        momentum_wide.stack().rename(momentum_col).reset_index()
    )
    return panel.merge(
        momentum_long, on=["rebalance_date", "ts_code"], how="left"
    )


# ─── Per-horizon driver ─────────────────────────────────────────────────

def run_one_horizon(
    panel_base: pd.DataFrame,
    lookback: int,
    skip: int,
) -> tuple[dict, list]:
    """Compute one horizon, run all five layers, return summary + result rows."""
    name = f"mom_{lookback}_{skip}"
    label = f"momentum {lookback}-{skip} (cumulative past return)"

    print(f"\n\n{'#' * 76}")
    print(f"# Horizon: {name}  (lookback={lookback}, skip={skip}, "
          f"min_coverage={MIN_COVERAGE:.0%})")
    print(f"{'#' * 76}")

    panel = add_momentum_to_panel(panel_base, lookback=lookback, skip=skip)
    report_coverage_by_year(panel, name)

    # Headline
    print("\n  --- Headline ---")
    quintiles = compute_quintile_series(panel, sort_col=name)
    headline = summarise_long_short(quintiles, "headline Q1-Q5")
    ic = compute_ic_series(panel, sort_col=name)
    print(f"  IC: mean={ic.mean():+.4f}, std={ic.std():.4f}, n={len(ic)}")
    print(f"  (Q1=losers, Q5=winners. Continuation: Q1-Q5<0 / IC>0. "
          f"Reversal: Q1-Q5>0 / IC<0.)")

    # Plots
    plot_cumulative_quintiles(
        quintiles, label,
        save_path=GRAPHS_DIR / f"{name}_quintile_cumulative_returns.png",
    )
    plot_ic_series(
        ic, label,
        save_path=GRAPHS_DIR / f"{name}_ic_time_series.png",
    )

    # Layers
    layer_1 = layer_1_bootstrap_ci(panel, factor_col=name)
    layer_2 = layer_2_regime_split(panel, factor_col=name)
    layer_3 = layer_3_tradable_only(panel, factor_col=name)  # DEFERRED
    layer_4 = layer_4_sector_neutral(panel, factor_col=name)
    layer_5 = layer_5_cap_terciles(panel, factor_col=name, cap_col="log_mcap")

    rows = collect_factor_results(
        factor_name=name,
        headline=headline,
        ic=ic,
        layer_1=layer_1,
        layer_2=layer_2,
        layer_4=layer_4,
        layer_5=layer_5,
    )

    summary = {
        "name": name,
        "lookback": lookback,
        "skip": skip,
        "headline_q1q5_pct_wk": (
            (headline.get("mean_period") or 0) * 100
        ),
        "headline_t": headline.get("t_stat"),
        "ic_mean": float(ic.mean()) if len(ic) else None,
        "layer4_q1q5_pct_wk": (
            (layer_4.get("mean_period") or 0) * 100 if layer_4 else None
        ),
        "layer4_t": layer_4.get("t_stat") if layer_4 else None,
        "layer5_low_q1q5": (
            (layer_5["low"].get("mean_period") or 0) * 100
            if layer_5.get("low") else None
        ),
        "layer5_low_p": layer_5["low"].get("p_value") if layer_5.get("low") else None,
        "layer5_mid_q1q5": (
            (layer_5["mid"].get("mean_period") or 0) * 100
            if layer_5.get("mid") else None
        ),
        "layer5_mid_p": layer_5["mid"].get("p_value") if layer_5.get("mid") else None,
        "layer5_high_q1q5": (
            (layer_5["high"].get("mean_period") or 0) * 100
            if layer_5.get("high") else None
        ),
        "layer5_high_p": layer_5["high"].get("p_value") if layer_5.get("high") else None,
    }
    return summary, rows


# ─── Cross-horizon summary ──────────────────────────────────────────────

def print_cross_horizon_table(summaries: list) -> None:
    """One-screen comparison across horizons."""
    print(f"\n\n{'=' * 110}")
    print("Cross-horizon momentum summary  "
          "(sign: Q1-Q5 < 0 = continuation, > 0 = reversal)")
    print('=' * 110)

    header = (
        f"{'Horizon':<10s} | "
        f"{'Headline Q1-Q5':>16s} {'t':>6s} {'IC':>8s} | "
        f"{'Sec-neut Q1-Q5':>16s} {'t':>6s} | "
        f"{'Cap tercile Q1-Q5 (low / mid / high)':>40s}"
    )
    print(header)
    print('-' * len(header))

    for s in summaries:
        head = f"{s['headline_q1q5_pct_wk']:+.3f}%"
        head_t = f"{s['headline_t']:+.2f}" if s['headline_t'] else "n/a"
        ic = f"{s['ic_mean']:+.4f}" if s['ic_mean'] is not None else "n/a"
        sn = f"{s['layer4_q1q5_pct_wk']:+.3f}%" if s['layer4_q1q5_pct_wk'] else "n/a"
        sn_t = f"{s['layer4_t']:+.2f}" if s['layer4_t'] else "n/a"
        cap = (
            f"{s['layer5_low_q1q5']:+.2f} / "
            f"{s['layer5_mid_q1q5']:+.2f} / "
            f"{s['layer5_high_q1q5']:+.2f}"
        )
        print(f"{s['name']:<10s} | "
              f"{head:>16s} {head_t:>6s} {ic:>8s} | "
              f"{sn:>16s} {sn_t:>6s} | "
              f"{cap:>40s}")


# ─── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    panel_base = load_factor_panel()
    print(f"Panel loaded: {len(panel_base):,} rows, "
          f"{panel_base['rebalance_date'].nunique()} dates")
    print(f"Sweeping {len(HORIZON_CONFIGS)} momentum horizons "
          f"with min_coverage={MIN_COVERAGE:.0%}")

    summaries = []
    all_rows = []
    for lookback, skip in HORIZON_CONFIGS:
        summary, rows = run_one_horizon(panel_base, lookback, skip)
        summaries.append(summary)
        all_rows.extend(rows)

    print_cross_horizon_table(summaries)

    # Save combined long-format results CSV
    pd.DataFrame(all_rows).to_csv(SUMMARY_CSV, index=False)
    print(f"\nResults saved to: {SUMMARY_CSV}")

    print(f"\n{'=' * 76}")
    print("Multi-horizon momentum analysis complete.")
    print('=' * 76)