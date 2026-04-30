"""
lowvol_analysis.py — Volatility factor (std of past returns) on the
rebuilt weekly panel. Multi-horizon sweep across vol_52_4, vol_26_4,
and vol_13_4.

The low-volatility anomaly: lower-volatility stocks tend to outperform
higher-volatility stocks on a risk-adjusted (and often absolute) basis,
contrary to CAPM. In retail-dominated markets like A-shares, the
mechanism most often cited is lottery preference: retail investors
overpay for high-vol stocks chasing tail upside, depressing their
expected returns relative to fundamentals.

Architectural note
------------------
Volatility is std of past forward returns; computing it does not require
imputation because pandas .rolling().std() with min_periods naturally
skips NaN inside the window. This was already the behavior in the old
monthly code. The rebuild's main contribution here is sample-size
expansion (380 weeks vs 51 months) and architecturally clean formation
windows for stocks transitioning into the universe.

Sign convention
---------------
Q1 = LOW volatility (least volatile recent returns).
Q5 = HIGH volatility (most volatile recent returns).

Low-vol hypothesis: Q1 > Q5, Q1-Q5 > 0 / IC < 0.
CAPM-style risk premium: Q5 > Q1, Q1-Q5 < 0 / IC > 0.

Horizons swept
--------------
vol_52_4: 52-week formation, 4-week skip ≈ 12-month / 1-month (canonical)
vol_26_4: 26-week formation, 4-week skip ≈ 6-month / 1-month
vol_13_4: 13-week formation, 4-week skip ≈ 3-month / 1-month

We do not include a vol_4_1 short-window equivalent because std on
4 observations is too noisy to be a reliable cross-sectional signal.

Reference (old monthly result on 51 months, 2022-2026)
------------------------------------------------------
vol_12_1 BH-rejected in the HIGH-cap tercile (Q1-Q5 > 0 / low-vol works).
Low and mid terciles were nulls. Headline pooled was a small effect
diluted by the cap-tercile structure.

Logged predictions for the rebuilt panel
----------------------------------------
The old high-cap finding suggests low-vol works specifically in the
larger names within the universe — likely because retail lottery
preference operates more uniformly in the smaller and mid-cap segments,
flattening the risk-return curve there. The rebuilt panel has 7.5x more
data and should tighten CIs proportionally.

  Headline Q1-Q5 (%/wk):     [+0.05, +0.20] / t in [+0.5, +2.5]
  IC mean:                   [-0.02, -0.005]
  Layer 2 candidate splits:  COVID-related splits expected interesting.
                              The 2024 雪球 meltdown specifically punished
                              high-vol names, so post-雪球 expected
                              stronger low-vol effect than pre.
  Layer 4 (sector-neutral):  modest strengthen vs headline. Vol has
                              moderate sector concentration (utilities low,
                              tech high) that residualization removes.
  Layer 5 (within-tercile):  high-cap CELL is the prediction-of-record.
                              Low-cap and mid-cap most likely null or weak.

Highest-confidence prediction: high-cap Layer 5 cell BH-rejects.
Lowest-confidence: the absolute magnitude of the headline.

Failure modes specific to vol
-----------------------------
1. Skill vs lottery: low-vol stocks may include both "well-managed
   defensive businesses" (real factor) and "stocks with no news flow
   trading thinly" (microstructure artifact). The 60-day liquidity
   floor scrubs the second class but doesn't eliminate it.
2. Volatility regimes. In high-volatility regimes (2024 雪球, 2020 COVID
   crash), high-vol stocks crash hardest, exaggerating the low-vol
   effect on raw returns even when the cross-sectional ranking is
   unchanged. The Sharpe ratio is more regime-stable than the absolute
   Q1-Q5 spread.
3. Volatility persists. A stock with high recent vol tends to have high
   future vol; the sort is partially a sort on contemporaneous risk
   exposure. This is fine for the factor question but means the strategy
   carries exposure to "low-vol stays low-vol" persistence.

Run from Project_6/:
    python Factor_Analysis_Weekly_Universe/lowvol_analysis.py
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
    (52, 4),   # vol_52_4: canonical, the BH-rejecting cell from old code
    (26, 4),   # vol_26_4: medium horizon
    (13, 4),   # vol_13_4: short horizon
]

OUTPUT_PREFIX = "lowvol"
SUMMARY_CSV = DATA_DIR / f"single_factor_{OUTPUT_PREFIX}_results.csv"


# ─── Factor construction ────────────────────────────────────────────────

def add_volatility_to_panel(
    panel: pd.DataFrame,
    lookback: int,
    skip: int,
    min_coverage: float = MIN_COVERAGE,
    vol_col: str | None = None,
) -> pd.DataFrame:
    """
    Compute realised weekly volatility from observed forward returns.

    pandas .rolling().std() with min_periods naturally skips NaN inside
    the window, so a stock with 50 observed and 2 missing weeks in its
    52-week formation gets a std on 50 observations. No imputation.
    """
    if vol_col is None:
        vol_col = f"vol_{lookback}_{skip}"

    fr_matrix = panel.pivot_table(
        index="rebalance_date",
        columns="ts_code",
        values="forward_return",
        aggfunc="mean",
    ).sort_index()

    threshold = max(2, int(np.ceil(min_coverage * lookback)))

    vol_wide = (
        fr_matrix.rolling(window=lookback, min_periods=threshold)
        .std()
        .shift(skip + 1)
    )

    vol_long = vol_wide.stack().rename(vol_col).reset_index()
    return panel.merge(
        vol_long, on=["rebalance_date", "ts_code"], how="left"
    )


# ─── Per-horizon driver ─────────────────────────────────────────────────

def run_one_horizon(
    panel_base: pd.DataFrame,
    lookback: int,
    skip: int,
) -> tuple[dict, list]:
    """Compute one horizon, run all five layers, return summary + result rows."""
    name = f"vol_{lookback}_{skip}"
    label = f"volatility {lookback}-{skip} (std of past returns)"

    print(f"\n\n{'#' * 76}")
    print(f"# Horizon: {name}  (lookback={lookback}, skip={skip}, "
          f"min_coverage={MIN_COVERAGE:.0%})")
    print(f"{'#' * 76}")

    panel = add_volatility_to_panel(panel_base, lookback=lookback, skip=skip)
    report_coverage_by_year(panel, name)

    # Volatility distribution sanity (cross-section x time)
    vol_clean = panel[panel["in_universe"]][name].dropna()
    if len(vol_clean) > 0:
        print(
            f"\n  {name} distribution (in-universe): "
            f"n={len(vol_clean):,}, "
            f"mean={vol_clean.mean()*100:.2f}%/wk, "
            f"median={vol_clean.median()*100:.2f}%/wk, "
            f"p5={vol_clean.quantile(0.05)*100:.2f}%, "
            f"p95={vol_clean.quantile(0.95)*100:.2f}%"
        )

    # Headline
    print("\n  --- Headline ---")
    quintiles = compute_quintile_series(panel, sort_col=name)
    headline = summarise_long_short(quintiles, "headline Q1-Q5")
    ic = compute_ic_series(panel, sort_col=name)
    print(f"  IC: mean={ic.mean():+.4f}, std={ic.std():.4f}, n={len(ic)}")
    print(f"  (Q1=low-vol, Q5=high-vol. Low-vol works: Q1-Q5>0 / IC<0. "
          f"CAPM risk premium: Q1-Q5<0 / IC>0.)")

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
    print("Cross-horizon low-volatility summary  "
          "(sign: Q1-Q5 > 0 = low-vol works, < 0 = CAPM risk premium)")
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
    print(f"Sweeping {len(HORIZON_CONFIGS)} volatility horizons "
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
    print("Multi-horizon low-volatility analysis complete.")
    print('=' * 76)