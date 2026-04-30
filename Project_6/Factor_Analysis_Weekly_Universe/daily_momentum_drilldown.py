"""
daily_momentum_drilldown.py — Daily-formation momentum drill-down (Version A).

Tests whether using daily-frequency data in the momentum formation
window improves on the weekly-frequency mom_4_1 baseline. The portfolio
still rebalances every Wednesday (same cadence, same turnover, same
costs), only the signal construction changes.

Horizons swept
--------------
  mom_5d_0d:  5-day formation, NO skip (last day included)
  mom_5d_1d:  5-day formation, skip=1 day (conventional)
  mom_10d_1d: 10-day formation, skip=1 day
  mom_20d_1d: 20-day formation, skip=1 day  ≈ mom_4_1 weekly baseline

The 5d_0d vs 5d_1d comparison directly tests whether bid-ask bounce
matters in our universe. If 5d_0d substantially outperforms 5d_1d, the
"include the most recent return" wins and we should skip the skip
parameter for A-share daily strategies. If similar, the convention
doesn't bind here.

Why this is the cheap test
--------------------------
Same weekly Wednesday rebalance as Phase D. Same in_universe filter.
Same cost model. Same gate. The only difference: the signal is
computed from N daily returns ending at (Wed - skip days) instead of
4 weekly returns ending 1 week ago. So gross numbers are directly
comparable to the existing mom_4_1; cost numbers should be similar
because turnover is determined by the rebalance cadence and the
size of the Q5 quintile, both unchanged.

Sign convention
---------------
Q5 = HIGH past return = recent winners. With z_mom = -mom_X_Y,
positive z_mom means recent loser. Universe sort on z_mom: Q5 of z_mom
= worst recent performers = expected outperformers if reversal works.
Same as mom_4_1.

Run from Project_6/:
    python Factor_Analysis_Weekly_Universe/daily_momentum_drilldown.py

Prerequisites
-------------
  - data/candidate_history_panel.parquet (Stage 5)
  - data/factor_panel_weekly.parquet (factor_panel_builder.py)
  - data/limit_state_panel.parquet (limit_state_filter.py)
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    ANNUAL_FACTOR_SQRT,
    CANDIDATE_HISTORY_PATH,
    DATA_DIR,
    PERIODS_PER_YEAR,
    REGIME_EVENTS,
)
from factor_utils import load_factor_panel
from composite_segmented import (
    GATE_LOOKBACK,
    GATE_THRESHOLD,
    apply_gate,
    compute_gate_signal,
)
from cost_adjusted_analysis import (
    COST_LEVELS,
    HEADLINE_PENALTY,
    PENALTY_LEVELS,
    apply_costs,
    apply_limit_down_penalty,
    compute_metrics,
    compute_turnover,
    load_limit_state,
    merge_limit_state_to_panel,
    print_panel_table,
)


# ─── Configuration ─────────────────────────────────────────────────────

# Each tuple: (lookback_days, skip_days, label)
DAILY_HORIZONS = [
    (5, 0,  "mom_5d_0d"),
    (5, 1,  "mom_5d_1d"),
    (10, 1, "mom_10d_1d"),
    (20, 1, "mom_20d_1d"),
]

GRAPHS_OUT = Path("graphs")
OUTPUT_PREFIX = "daily_mom_drilldown"


# ─── Daily formation momentum ──────────────────────────────────────────

def compute_daily_momentum_signals(
    rebalance_dates: list,
    horizons: list,
    candidate_history: pd.DataFrame,
) -> dict:
    """
    For each (lookback, skip, label) horizon, compute a wide table of
    momentum signals indexed by (rebalance_date, ts_code).

    Mechanic: build the daily adj_close matrix once. For each rebalance
    date W, find the daily date W-skip (the formation-window endpoint).
    Cumulative return = adj_close[W-skip] / adj_close[W-skip-lookback] - 1.

    No imputation: if either endpoint is missing, the signal is NaN.
    pandas DatetimeIndex makes the lookup vectorized.

    Returns dict: label -> DataFrame with columns
        rebalance_date, ts_code, <label>
    """
    print("\nBuilding daily adj_close matrix...")
    df = candidate_history.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df["adj_close"] = (
        df["close"].astype(float) * df["adj_factor"].astype(float)
    )
    adj_matrix = df.pivot_table(
        index="trade_date", columns="ts_code",
        values="adj_close", aggfunc="last",
    ).sort_index()
    print(f"  adj_close matrix: {adj_matrix.shape[0]} days × "
          f"{adj_matrix.shape[1]} stocks")

    # Calendar of trading days. We need to find the Nth trading day before
    # any rebalance date W, which means working with positional indexing
    # on the adj_matrix.index (which IS a sorted DatetimeIndex of trading days).
    cal_idx = adj_matrix.index
    cal_lookup = {d: i for i, d in enumerate(cal_idx)}

    rebal_ts = pd.to_datetime(rebalance_dates)

    out = {}
    for lookback, skip, label in horizons:
        print(f"  Computing {label}...")
        rows = []
        for w in rebal_ts:
            # Find positional index of rebalance date in calendar.
            if w not in cal_lookup:
                continue
            w_idx = cal_lookup[w]
            end_idx = w_idx - skip          # formation-window end
            start_idx = end_idx - lookback  # formation-window start
            if start_idx < 0:
                continue
            end_date = cal_idx[end_idx]
            start_date = cal_idx[start_idx]
            cum = (
                adj_matrix.loc[end_date] / adj_matrix.loc[start_date] - 1
            )
            cum.name = label
            sub = cum.reset_index()
            sub.columns = ["ts_code", label]
            sub["rebalance_date"] = w
            rows.append(sub)

        out_df = pd.concat(rows, ignore_index=True)
        out[label] = out_df[["rebalance_date", "ts_code", label]]

    return out


def attach_daily_momentum(
    panel: pd.DataFrame, momentum_signals: dict,
) -> pd.DataFrame:
    """
    Merge each daily momentum signal into the factor panel, then create
    z-scored versions for the strategy.

    For each label, adds:
        <label>     raw cumulative return over the formation window
        z_<label>   per-date cross-sectional z-score (winsorized at 1/99)
    """
    from factor_utils import cross_sectional_zscore

    out = panel
    for label, sig in momentum_signals.items():
        out = out.merge(sig, on=["rebalance_date", "ts_code"], how="left")
        # Z-score the raw signal, then sign-flip for "high z = predicted winner"
        z_raw_col = f"z_{label}_raw"
        z_signed_col = f"z_{label}_signed"
        out = cross_sectional_zscore(out, label, z_raw_col)
        out[z_signed_col] = -out[z_raw_col]  # negate: low return = high z (reversal)
    return out


# ─── Strategy construction ─────────────────────────────────────────────

def filtered_baseline_returns(panel: pd.DataFrame) -> tuple:
    """Universe-EW with buy-side limit-up filter."""
    df = panel[panel["in_universe"]].copy()
    df = df[~df["at_limit_up_t"]]
    df = df.dropna(subset=["forward_return"])
    holdings = {
        date: set(group["ts_code"]) for date, group in df.groupby("rebalance_date")
    }
    returns = df.groupby("rebalance_date")["forward_return"].mean()
    return returns, holdings


def filtered_mom_q5_returns(
    panel: pd.DataFrame, signal_col: str,
) -> tuple:
    """
    Q5 of the signed daily momentum (so Q5 = recent loser = predicted winner).
    Buy-side limit-up filter applied.
    """
    df = panel[panel["in_universe"]].copy()
    df = df.dropna(subset=[signal_col, "forward_return"])
    df["q"] = df.groupby("rebalance_date")[signal_col].transform(
        lambda s: pd.qcut(s, 5, labels=False, duplicates="drop")
    )
    q5 = df[df["q"] == 4].copy()
    q5 = q5[~q5["at_limit_up_t"]]
    holdings = {
        date: set(group["ts_code"]) for date, group in q5.groupby("rebalance_date")
    }
    returns = q5.groupby("rebalance_date")["forward_return"].mean()
    return returns, holdings


# ─── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    panel = load_factor_panel()
    print(f"Panel loaded: {len(panel):,} rows, "
          f"{panel['rebalance_date'].nunique()} dates")

    print("\nLoading limit-state panel...")
    limit_state = load_limit_state()
    panel = merge_limit_state_to_panel(panel, limit_state)
    print(f"  panel + limit-state merged")

    print("\nLoading candidate history panel for daily prices...")
    candidate_history = pd.read_parquet(
        CANDIDATE_HISTORY_PATH,
        columns=["trade_date", "ts_code", "close", "adj_factor"],
    )
    print(f"  {len(candidate_history):,} daily rows, "
          f"{candidate_history['ts_code'].nunique():,} stocks")

    # Compute all daily-formation momentum signals
    rebalance_dates = sorted(panel["rebalance_date"].unique())
    momentum_signals = compute_daily_momentum_signals(
        rebalance_dates, DAILY_HORIZONS, candidate_history,
    )
    panel = attach_daily_momentum(panel, momentum_signals)

    # Coverage diagnostic per signal
    print(f"\nCoverage per daily-momentum signal (in-universe rows):")
    iu = panel[panel["in_universe"]]
    for _, _, label in DAILY_HORIZONS:
        n_with = int(iu[label].notna().sum())
        n = len(iu)
        print(f"  {label:<14s} {100*n_with/n:>5.1f}%  ({n_with:,}/{n:,})")

    # Build filtered baseline once; gate from baseline
    print(f"\nBuilding baseline and gate...")
    baseline_r, baseline_h = filtered_baseline_returns(panel)
    gate = compute_gate_signal(baseline_r)
    print(f"  baseline weeks: {len(baseline_r)}")
    print(f"  gate: {int(gate.sum())} of {len(gate)} weeks gated "
          f"({100*gate.mean():.1f}%)")

    # For each horizon, build mom_only(daily) and store
    horizon_returns = {"baseline": baseline_r}
    horizon_holdings = {"baseline": baseline_h}
    for _, _, label in DAILY_HORIZONS:
        signal_col = f"z_{label}_signed"
        r, h = filtered_mom_q5_returns(panel, signal_col)
        horizon_returns[label] = r
        horizon_holdings[label] = h

    # Turnover diagnostic
    print(f"\nWeekly turnover per strategy:")
    for label, holdings in horizon_holdings.items():
        t = compute_turnover(holdings)
        print(f"  {label:<14s} mean {t.mean()*100:>5.1f}%  "
              f"(median {t.median()*100:.1f}%, max {t.max()*100:.1f}%)")

    # Build six-panel-style table per horizon: gross-filtered metrics for
    # gate-off and gate-on. Compare against weekly mom_4_1 reference.
    print(f"\n{'=' * 100}")
    print("GROSS (filtered, no penalty, no cost) — daily-formation momentum sweep")
    print(f"{'=' * 100}")
    gross_metrics = []
    for label in ["baseline"] + [h[2] for h in DAILY_HORIZONS]:
        r = horizon_returns[label]
        gross_metrics.append(compute_metrics(r, f"{label} (gate off)"))
        gross_metrics.append(
            compute_metrics(apply_gate(r, gate), f"{label} (gate on)")
        )
    print_panel_table(gross_metrics, "Gross-filtered, six-row sweep")

    # Headline net (penalty=2%, cost=realistic) per horizon
    print(f"\n{'=' * 100}")
    print(f"HEADLINE NET: penalty={HEADLINE_PENALTY}, cost=realistic (0.32% RT)")
    print(f"{'=' * 100}")
    headline_metrics = []
    headline_panels = {}
    for label in ["baseline"] + [h[2] for h in DAILY_HORIZONS]:
        r = horizon_returns[label]
        h_holdings = horizon_holdings[label]
        for gate_state, returns_to_use in [
            ("gate off", r),
            ("gate on", apply_gate(r, gate)),
        ]:
            penalized = apply_limit_down_penalty(
                returns_to_use, h_holdings, panel,
                PENALTY_LEVELS[HEADLINE_PENALTY],
            )
            net = apply_costs(penalized, h_holdings, COST_LEVELS["realistic"])
            full_label = f"{label} ({gate_state})"
            headline_panels[full_label] = net
            headline_metrics.append(compute_metrics(net, full_label))
    print_panel_table(headline_metrics, "Headline net (per horizon)")

    # Stress net (penalty=10%, cost=aggressive) per horizon
    print(f"\n{'=' * 100}")
    print(f"STRESS NET: penalty=10%, cost=aggressive (0.92% RT)")
    print(f"{'=' * 100}")
    stress_metrics = []
    stress_panels = {}
    for label in ["baseline"] + [h[2] for h in DAILY_HORIZONS]:
        r = horizon_returns[label]
        h_holdings = horizon_holdings[label]
        for gate_state, returns_to_use in [
            ("gate off", r),
            ("gate on", apply_gate(r, gate)),
        ]:
            penalized = apply_limit_down_penalty(
                returns_to_use, h_holdings, panel,
                PENALTY_LEVELS["10%"],
            )
            net = apply_costs(penalized, h_holdings, COST_LEVELS["aggressive"])
            full_label = f"{label} ({gate_state})"
            stress_panels[full_label] = net
            stress_metrics.append(compute_metrics(net, full_label))
    print_panel_table(stress_metrics, "Stress net (per horizon)")

    # Save outputs
    metrics_csv = DATA_DIR / f"{OUTPUT_PREFIX}_metrics.csv"
    pd.concat([
        pd.DataFrame(gross_metrics).assign(scenario="gross"),
        pd.DataFrame(headline_metrics).assign(scenario="headline"),
        pd.DataFrame(stress_metrics).assign(scenario="stress"),
    ]).to_csv(metrics_csv, index=False)
    print(f"\nMetrics saved to: {metrics_csv}")

    # Compact comparison table: all horizons × scenarios, side-by-side
    print(f"\n{'=' * 100}")
    print("COMPACT COMPARISON: Sharpe across all horizons × scenarios")
    print(f"{'=' * 100}")
    df_comp = pd.DataFrame({
        "horizon_gate": [m["label"] for m in gross_metrics],
        "gross_Sh": [m["ann_sharpe"] for m in gross_metrics],
        "headline_Sh": [m["ann_sharpe"] for m in headline_metrics],
        "stress_Sh": [m["ann_sharpe"] for m in stress_metrics],
    })
    print(df_comp.round(3).to_string(index=False))

    out_compact = DATA_DIR / f"{OUTPUT_PREFIX}_compact.csv"
    df_comp.to_csv(out_compact, index=False)
    print(f"\nCompact table saved to: {out_compact}")

    # Plot: cumulative returns at headline scenario, all horizons
    fig, ax = plt.subplots(figsize=(13, 7))
    colors = {
        "baseline (gate off)":        "#888888",
        "baseline (gate on)":         "#888888",
        "mom_5d_0d (gate off)":       "#1f77b4",
        "mom_5d_0d (gate on)":        "#1f77b4",
        "mom_5d_1d (gate off)":       "#ff7f0e",
        "mom_5d_1d (gate on)":        "#ff7f0e",
        "mom_10d_1d (gate off)":      "#2ca02c",
        "mom_10d_1d (gate on)":       "#2ca02c",
        "mom_20d_1d (gate off)":      "#d62728",
        "mom_20d_1d (gate on)":       "#d62728",
    }
    for label, returns in headline_panels.items():
        cum = (1 + returns.fillna(0)).cumprod()
        ls = "-" if "off" in label else "--"
        c = colors.get(label, "black")
        lw = 1.2 if "baseline" in label else 1.6
        ax.plot(cum.index, cum.values, label=label,
                color=c, linewidth=lw, linestyle=ls)

    ymax = ax.get_ylim()[1]
    for label, event_date in REGIME_EVENTS.items():
        ax.axvline(event_date, color="grey", linestyle="--",
                   alpha=0.55, linewidth=0.9)
        ax.text(event_date, ymax * 0.985, label,
                rotation=90, verticalalignment="top",
                fontsize=8, color="dimgrey")
    ax.set_title(
        "Daily-formation momentum drill-down: net cumulative returns "
        "(headline: 2% penalty, realistic cost)"
    )
    ax.set_xlabel("Rebalance date")
    ax.set_ylabel("Cumulative return (×)")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    plot_path = GRAPHS_OUT / f"{OUTPUT_PREFIX}_cumulative.png"
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
    print(f"Plot saved to: {plot_path}")

    print(f"\n{'=' * 76}")
    print("Daily momentum drill-down complete.")
    print('=' * 76)