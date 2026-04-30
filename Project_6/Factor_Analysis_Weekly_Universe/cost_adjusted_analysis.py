"""
cost_adjusted_analysis.py — Net-of-cost analysis of the six strategy
panels with limit-state filter on entries and limit-down sell penalty.

Three transformations applied to gross returns:

1. BUY-SIDE FILTER. Drop stocks that closed at limit-up on the
   rebalance date when entering a position. You couldn't have bought
   them at a price worth accepting. Information: only week-t close,
   no foresight.

2. LIMIT-DOWN SELL PENALTY. For positions held over a week where the
   stock closed at limit-down on the SELL date (week t+1), apply an
   additional drag to the realized return. This costs you below-close
   slippage from queue contention; in extreme cases you may have only
   gotten partial fills. Reported at three penalty levels: 1%, 2%
   (headline), 3%, and 10% (stress) — all applied to stocks that
   actually limit-downed on exit, no foresight.

3. ROUND-TRIP COST. Subtract turnover * round_trip_cost from each
   weekly return. Reported at two cost levels:
     - realistic-retail: 0.32% RT (commission 0.05% + stamp 0.05%
       + transfer 0.001% + slippage 0.16% per side x 2 = 0.32%)
     - aggressive-retail: 0.92% RT (slippage at 0.40% per side
       reflecting small-cap thin-book reality on weeks of high turnover)

Turnover measurement
--------------------
Per-strategy weekly turnover = fraction of capital that changes hands
from one rebalance to the next. Computed empirically from the actual
holdings: |new_weights - old_weights|.sum() / 2. Range:
  - baseline:  ~1-3%/wk (just IPO entries and delistings)
  - mom_only:  ~60-80%/wk (4-week formation churns names fast)
  - segmented: ~30-50%/wk (mix of slow value/lowvol and fast mom legs)

Output panels
-------------
For each gate state (off / on), six metric tables under different
penalty assumptions and cost levels — total 6 strategies × 4 penalty
levels × 2 cost levels = 48 net Sharpe numbers, presented in a way
that lets you read down a column to compare strategies and across a
row to see penalty/cost sensitivity.

Run from Project_6/:
    python Factor_Analysis_Weekly_Universe/cost_adjusted_analysis.py

Prerequisites
-------------
  - data/factor_panel_weekly.parquet (factor_panel_builder.py full)
  - data/limit_state_panel.parquet (limit_state_filter.py full)
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    ANNUAL_FACTOR_SQRT,
    DATA_DIR,
    PERIODS_PER_YEAR,
    REGIME_EVENTS,
)
from factor_utils import load_factor_panel
from multifactor_utils import add_all_factors
from composite_segmented import (
    GATE_LOOKBACK,
    GATE_THRESHOLD,
    apply_gate,
    compute_gate_signal,
)


# ─── Configuration ─────────────────────────────────────────────────────

LIMIT_STATE_PATH = DATA_DIR / "limit_state_panel.parquet"

# Cost levels (round-trip, applied as drag = turnover * RT_cost).
COST_LEVELS = {
    "realistic": 0.0032,   # 0.32% RT
    "aggressive": 0.0092,  # 0.92% RT
}

# Limit-down sell penalty levels. Applied multiplicatively only to
# the stocks that closed at limit-down on the sell date, scaled by
# their portfolio weight in the strategy's holdings that week.
PENALTY_LEVELS = {
    "1%": 0.01,
    "2%": 0.02,    # headline
    "3%": 0.03,
    "10%": 0.10,   # stress
}
HEADLINE_PENALTY = "2%"

GRAPHS_OUT = Path("graphs")
OUTPUT_PREFIX = "cost_adjusted"


# ─── Limit state loading ───────────────────────────────────────────────

def load_limit_state() -> pd.DataFrame:
    """Load the limit-state panel and convert trade_date to datetime."""
    if not LIMIT_STATE_PATH.exists():
        raise FileNotFoundError(
            f"{LIMIT_STATE_PATH} not found. "
            f"Run `python limit_state_filter.py full` first."
        )
    ls = pd.read_parquet(LIMIT_STATE_PATH)
    ls["trade_date"] = pd.to_datetime(ls["trade_date"])
    return ls[["trade_date", "ts_code", "at_limit_up", "at_limit_down"]]


def merge_limit_state_to_panel(
    panel: pd.DataFrame, limit_state: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge limit-state flags into the factor panel on (rebalance_date, ts_code).
    Adds: at_limit_up_t, at_limit_down_t (the date's own state).
    Also computes at_limit_down_tp1: True if the stock was at limit-down
    on the NEXT rebalance date (the sell date for that week's position).
    """
    p = panel.merge(
        limit_state.rename(columns={
            "trade_date": "rebalance_date",
            "at_limit_up": "at_limit_up_t",
            "at_limit_down": "at_limit_down_t",
        }),
        on=["rebalance_date", "ts_code"], how="left",
    )
    p["at_limit_up_t"] = p["at_limit_up_t"].fillna(False)
    p["at_limit_down_t"] = p["at_limit_down_t"].fillna(False)

    # at_limit_down_tp1: did this stock limit-down on its NEXT rebalance?
    # We get this by sorting (ts_code, rebalance_date) and shifting -1.
    p = p.sort_values(["ts_code", "rebalance_date"]).reset_index(drop=True)
    p["at_limit_down_tp1"] = (
        p.groupby("ts_code")["at_limit_down_t"].shift(-1)
    )
    p["at_limit_down_tp1"] = p["at_limit_down_tp1"].fillna(False).astype(bool)
    return p


# ─── Strategy construction with filter and penalties ───────────────────

def filtered_baseline_returns(panel: pd.DataFrame) -> tuple:
    """
    Universe-EW, filtering buy-side limit-up.

    Returns (returns_series, holdings_dict_of_sets):
      - returns: weekly forward_return mean of qualifying stocks
      - holdings: per-week set of ts_codes held (for turnover)
    """
    df = panel[panel["in_universe"]].copy()
    df = df[~df["at_limit_up_t"]]  # drop limit-up on entry
    df = df.dropna(subset=["forward_return"])

    holdings = {
        date: set(group["ts_code"]) for date, group in df.groupby("rebalance_date")
    }
    returns = df.groupby("rebalance_date")["forward_return"].mean()
    return returns, holdings


def filtered_mom_only_returns(panel: pd.DataFrame) -> tuple:
    """z_mom Q5 with buy-side filter. Returns (returns, holdings)."""
    df = panel[panel["in_universe"]].copy()
    df = df.dropna(subset=["z_mom", "forward_return"])
    df["q"] = df.groupby("rebalance_date")["z_mom"].transform(
        lambda s: pd.qcut(s, 5, labels=False, duplicates="drop")
    )
    q5 = df[df["q"] == 4].copy()
    q5 = q5[~q5["at_limit_up_t"]]  # drop limit-up entries

    holdings = {
        date: set(group["ts_code"]) for date, group in q5.groupby("rebalance_date")
    }
    returns = q5.groupby("rebalance_date")["forward_return"].mean()
    return returns, holdings


def filtered_segmented_returns(panel: pd.DataFrame) -> tuple:
    """Segmented composite with buy-side filter applied to each leg."""
    df = panel[panel["in_universe"]].copy()
    df["cap_tercile"] = (
        df.groupby("rebalance_date")["log_mcap"]
        .transform(
            lambda s: pd.qcut(s, 3, labels=["low", "mid", "high"],
                              duplicates="drop")
        )
    )

    legs = {}
    leg_holdings = {}

    # Leg 1: value Q5 in (low + mid)
    low_mid = df[df["cap_tercile"].isin(["low", "mid"])].copy()
    low_mid["q"] = low_mid.groupby("rebalance_date")["z_value"].transform(
        lambda s: pd.qcut(s, 5, labels=False, duplicates="drop")
    )
    leg_value = low_mid[(low_mid["q"] == 4) & (~low_mid["at_limit_up_t"])]
    leg_value = leg_value.dropna(subset=["forward_return"])
    legs["leg_value"] = leg_value.groupby("rebalance_date")["forward_return"].mean()
    leg_holdings["leg_value"] = {
        d: set(g["ts_code"]) for d, g in leg_value.groupby("rebalance_date")
    }

    # Leg 2: lowvol Q5 in high-cap
    high = df[df["cap_tercile"] == "high"].copy()
    high["q"] = high.groupby("rebalance_date")["z_lowvol"].transform(
        lambda s: pd.qcut(s, 5, labels=False, duplicates="drop")
    )
    leg_lowvol = high[(high["q"] == 4) & (~high["at_limit_up_t"])]
    leg_lowvol = leg_lowvol.dropna(subset=["forward_return"])
    legs["leg_lowvol"] = leg_lowvol.groupby("rebalance_date")["forward_return"].mean()
    leg_holdings["leg_lowvol"] = {
        d: set(g["ts_code"]) for d, g in leg_lowvol.groupby("rebalance_date")
    }

    # Leg 3: z_mom Q5 universe-wide
    leg_mom = df.dropna(subset=["z_mom", "forward_return"]).copy()
    leg_mom["q"] = leg_mom.groupby("rebalance_date")["z_mom"].transform(
        lambda s: pd.qcut(s, 5, labels=False, duplicates="drop")
    )
    leg_mom = leg_mom[(leg_mom["q"] == 4) & (~leg_mom["at_limit_up_t"])]
    legs["leg_mom"] = leg_mom.groupby("rebalance_date")["forward_return"].mean()
    leg_holdings["leg_mom"] = {
        d: set(g["ts_code"]) for d, g in leg_mom.groupby("rebalance_date")
    }

    legs_df = pd.DataFrame(legs)
    combined = legs_df.mean(axis=1, skipna=True)

    # Combined holdings: union of leg holdings (for turnover calculation,
    # treats stocks held in two legs as held once at higher weight; small
    # approximation but correct in turnover terms because two-leg stocks
    # don't churn between rebalances any faster than single-leg).
    combined_holdings = {}
    all_dates = set()
    for h in leg_holdings.values():
        all_dates.update(h.keys())
    for d in all_dates:
        combined_holdings[d] = set()
        for leg_name, h in leg_holdings.items():
            combined_holdings[d].update(h.get(d, set()))
    return combined, combined_holdings


def apply_limit_down_penalty(
    returns: pd.Series,
    holdings: dict,
    panel: pd.DataFrame,
    penalty: float,
) -> pd.Series:
    """
    Apply a flat percentage penalty to the weighted fraction of holdings
    that closed at limit-down on the sell date (week t+1).

    Mechanic: for each rebalance date, find the set of held stocks. Of
    those, count how many had at_limit_down_tp1 = True (limit-down on
    their next rebalance). The fraction of the portfolio at limit-down
    on exit is `n_stuck / n_held`. The penalty applied to that week's
    return is `(n_stuck / n_held) * penalty`. Subtract from gross return.

    No foresight: at_limit_down_tp1 is week-t+1 information used only to
    record what actually happened, not to inform the week-t entry decision.
    """
    # Build a (date, ts_code) -> at_limit_down_tp1 lookup
    lookup_df = panel[["rebalance_date", "ts_code", "at_limit_down_tp1"]]
    lookup = (
        lookup_df.set_index(["rebalance_date", "ts_code"])
        ["at_limit_down_tp1"].to_dict()
    )

    adjusted = returns.copy()
    for date, held in holdings.items():
        if not held:
            continue
        n_stuck = sum(1 for tc in held if lookup.get((date, tc), False))
        if n_stuck == 0:
            continue
        frac_stuck = n_stuck / len(held)
        if date in adjusted.index:
            adjusted.loc[date] -= frac_stuck * penalty
    return adjusted


def compute_turnover(holdings_by_date: dict) -> pd.Series:
    """
    One-sided turnover per rebalance date: (entries + exits) / 2 / current_size.

    Equivalent to: (1 - jaccard_overlap(prev, curr)) at the limit
    where positions are equal-weighted. We compute as:
      turnover[t] = |new_weights - old_weights|.sum() / 2
                  = (n_entries + n_exits) / 2 / n_held_average
    """
    sorted_dates = sorted(holdings_by_date.keys())
    turnover = {}
    for i, date in enumerate(sorted_dates):
        if i == 0:
            turnover[date] = 1.0  # full position at first
            continue
        prev_held = holdings_by_date[sorted_dates[i - 1]]
        curr_held = holdings_by_date[date]
        if not prev_held or not curr_held:
            turnover[date] = np.nan
            continue
        entries = curr_held - prev_held
        exits = prev_held - curr_held
        n_avg = (len(prev_held) + len(curr_held)) / 2
        turnover[date] = (len(entries) + len(exits)) / 2 / n_avg
    return pd.Series(turnover).sort_index()


def apply_costs(
    returns: pd.Series,
    holdings: dict,
    cost_rt: float,
) -> pd.Series:
    """Subtract turnover * cost_rt from each weekly return."""
    turnover = compute_turnover(holdings)
    aligned = returns.copy()
    for date, t in turnover.items():
        if pd.notna(t) and date in aligned.index:
            aligned.loc[date] -= t * cost_rt
    return aligned


# ─── Metrics ───────────────────────────────────────────────────────────

def compute_metrics(returns: pd.Series, label: str) -> dict:
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return {"label": label, "n_weeks": 0}
    cum = (1 + r).cumprod()
    final = float(cum.iloc[-1])
    years = n / PERIODS_PER_YEAR
    ann_geom = final ** (1 / years) - 1 if years > 0 else np.nan
    mean = float(r.mean())
    std = float(r.std())
    sharpe = mean / std * ANNUAL_FACTOR_SQRT if std > 0 else np.nan
    rolling_max = cum.cummax()
    max_dd = float(((cum / rolling_max) - 1).min())
    return {
        "label": label,
        "n_weeks": n,
        "ann_return_pct": ann_geom * 100,
        "ann_sharpe": sharpe,
        "cumulative_pct": (final - 1) * 100,
        "max_drawdown_pct": max_dd * 100,
        "weekly_mean_pct": mean * 100,
    }


def print_panel_table(rows: list[dict], title: str) -> None:
    print(f"\n{'=' * 100}")
    print(title)
    print('=' * 100)
    header = (
        f"{'Strategy':<28s} {'NWk':>5s} "
        f"{'AnnRet%':>9s} {'AnnSh':>8s} {'Cum%':>9s} "
        f"{'MaxDD%':>9s} {'WkMean%':>9s}"
    )
    print(header)
    print('-' * len(header))
    for m in rows:
        print(
            f"{m['label']:<28s} {m['n_weeks']:>5d} "
            f"{m['ann_return_pct']:>+8.2f} {m['ann_sharpe']:>+8.2f} "
            f"{m['cumulative_pct']:>+8.1f} {m['max_drawdown_pct']:>+8.1f} "
            f"{m['weekly_mean_pct']:>+8.3f}"
        )


def sharpe_grid(
    returns: pd.Series,
    holdings: dict,
    panel: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build a (penalty x cost) grid of net Sharpe for one strategy.
    Rows: penalty levels. Cols: cost levels.
    """
    grid = {}
    for penalty_label, penalty in PENALTY_LEVELS.items():
        penalized = apply_limit_down_penalty(
            returns, holdings, panel, penalty,
        )
        grid[penalty_label] = {}
        for cost_label, cost_rt in COST_LEVELS.items():
            net = apply_costs(penalized, holdings, cost_rt)
            r = net.dropna()
            if len(r) < 10:
                grid[penalty_label][cost_label] = np.nan
                continue
            mean = float(r.mean())
            std = float(r.std())
            sharpe = mean / std * ANNUAL_FACTOR_SQRT if std > 0 else np.nan
            grid[penalty_label][cost_label] = sharpe
    return pd.DataFrame(grid).T  # penalty rows, cost cols


def print_sharpe_grid(grid: pd.DataFrame, label: str) -> None:
    print(f"\n  {label}:")
    print(grid.round(3).to_string())


# ─── Plotting ──────────────────────────────────────────────────────────

def plot_sensitivity_matrix(
    grids: dict, save_path: Path,
) -> None:
    """
    For each strategy, plot a heatmap of (penalty x cost) net Sharpe.
    Six subplots in a 2x3 grid: rows = gate state, cols = strategy.
    """
    strategies_order = ["baseline", "mom_only", "segmented"]
    gate_order = ["gate off", "gate on"]

    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    vmin = min(g.min().min() for g in grids.values())
    vmax = max(g.max().max() for g in grids.values())
    abs_max = max(abs(vmin), abs(vmax))

    for i, gate in enumerate(gate_order):
        for j, strat in enumerate(strategies_order):
            ax = axes[i, j]
            label = f"{strat} ({gate})"
            grid = grids[label]
            im = ax.imshow(
                grid.values, cmap="RdYlGn", vmin=-abs_max, vmax=abs_max,
                aspect="auto",
            )
            ax.set_xticks(range(len(grid.columns)))
            ax.set_xticklabels(grid.columns)
            ax.set_yticks(range(len(grid.index)))
            ax.set_yticklabels(grid.index)
            ax.set_title(label)
            ax.set_xlabel("Cost level")
            ax.set_ylabel("Limit-down penalty")
            for ii in range(len(grid.index)):
                for jj in range(len(grid.columns)):
                    val = grid.iloc[ii, jj]
                    color = "white" if abs(val) > abs_max * 0.5 else "black"
                    ax.text(jj, ii, f"{val:.2f}",
                            ha="center", va="center",
                            color=color, fontsize=10)

    plt.suptitle("Net Sharpe sensitivity: penalty × cost grid by strategy",
                 fontsize=13, y=1.00)
    plt.tight_layout()
    plt.savefig(save_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def plot_cumulative_net(
    panels_returns: dict, save_path: Path, scenario_label: str,
) -> None:
    """Cumulative net returns for the six panels under one scenario."""
    fig, ax = plt.subplots(figsize=(13, 7))
    style = {
        "baseline (gate off)":    ("#888888", 1.5, "-",  1),
        "baseline (gate on)":     ("#888888", 1.5, "--", 1),
        "mom_only (gate off)":    ("#1f77b4", 2.0, "-",  3),
        "mom_only (gate on)":     ("#1f77b4", 2.0, "--", 3),
        "segmented (gate off)":   ("#d62728", 2.0, "-",  4),
        "segmented (gate on)":    ("#d62728", 2.0, "--", 4),
    }
    for label, returns in panels_returns.items():
        cum = (1 + returns.fillna(0)).cumprod()
        c, lw, ls, z = style.get(label, ("black", 1.0, "-", 1))
        ax.plot(cum.index, cum.values, label=label,
                color=c, linewidth=lw, linestyle=ls, zorder=z)

    ymax = ax.get_ylim()[1]
    for label, event_date in REGIME_EVENTS.items():
        ax.axvline(event_date, color="grey", linestyle="--",
                   alpha=0.55, linewidth=0.9)
        ax.text(event_date, ymax * 0.985, label,
                rotation=90, verticalalignment="top",
                fontsize=8, color="dimgrey")

    ax.set_title(f"Net cumulative returns: {scenario_label}")
    ax.set_xlabel("Rebalance date")
    ax.set_ylabel("Cumulative return (×)")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


# ─── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    panel = load_factor_panel()
    print(f"Panel loaded: {len(panel):,} rows, "
          f"{panel['rebalance_date'].nunique()} dates")

    panel = add_all_factors(panel)

    print("\nLoading limit-state panel...")
    limit_state = load_limit_state()
    print(f"  {len(limit_state):,} rows")

    print("Merging limit-state into factor panel...")
    panel = merge_limit_state_to_panel(panel, limit_state)
    print(f"  in-universe rows at_limit_up_t:  "
          f"{int(panel.loc[panel['in_universe'], 'at_limit_up_t'].sum()):,} "
          f"({100*panel.loc[panel['in_universe'], 'at_limit_up_t'].mean():.3f}%)")
    print(f"  in-universe rows at_limit_down_t: "
          f"{int(panel.loc[panel['in_universe'], 'at_limit_down_t'].sum()):,} "
          f"({100*panel.loc[panel['in_universe'], 'at_limit_down_t'].mean():.3f}%)")

    # Build filtered strategies
    print("\nComputing filtered gross strategies...")
    baseline_r, baseline_h = filtered_baseline_returns(panel)
    mom_r, mom_h = filtered_mom_only_returns(panel)
    seg_r, seg_h = filtered_segmented_returns(panel)

    # Turnover diagnostics
    print(f"\nWeekly turnover (mean):")
    for label, holdings in [("baseline", baseline_h),
                              ("mom_only", mom_h),
                              ("segmented", seg_h)]:
        t = compute_turnover(holdings)
        print(f"  {label:<10s} {t.mean()*100:>6.1f}%  "
              f"(median {t.median()*100:.1f}%, max {t.max()*100:.1f}%)")

    # Build gate from filtered baseline (consistent with Phase C)
    print(f"\nBuilding stimulus gate (lookback={GATE_LOOKBACK}, "
          f"threshold=+{GATE_THRESHOLD})...")
    gate = compute_gate_signal(baseline_r)
    n_gated = int(gate.sum())
    print(f"  {n_gated} of {len(gate)} weeks gated "
          f"({100*n_gated/len(gate):.1f}%)")

    # Six gross-filtered panels (no penalty, no cost)
    six_gross = {
        "baseline (gate off)":  baseline_r,
        "baseline (gate on)":   apply_gate(baseline_r, gate),
        "mom_only (gate off)":  mom_r,
        "mom_only (gate on)":   apply_gate(mom_r, gate),
        "segmented (gate off)": seg_r,
        "segmented (gate on)":  apply_gate(seg_r, gate),
    }
    six_gross_metrics = [
        compute_metrics(r, label) for label, r in six_gross.items()
    ]
    print_panel_table(
        six_gross_metrics,
        "GROSS (filtered, no penalty, no cost) — same six as Phase C, but with "
        "buy-side limit-up filter applied",
    )

    # Sensitivity grids per strategy
    print("\n" + "=" * 76)
    print("Net Sharpe sensitivity grids (penalty rows × cost cols)")
    print("=" * 76)

    holdings_by_label = {
        "baseline (gate off)":  baseline_h,
        "baseline (gate on)":   baseline_h,
        "mom_only (gate off)":  mom_h,
        "mom_only (gate on)":   mom_h,
        "segmented (gate off)": seg_h,
        "segmented (gate on)":  seg_h,
    }

    grids = {}
    for label, returns in six_gross.items():
        holdings = holdings_by_label[label]
        grid = sharpe_grid(returns, holdings, panel)
        grids[label] = grid
        print_sharpe_grid(grid, label)

    # Headline net comparison (penalty=2%, cost=realistic)
    print("\n" + "=" * 100)
    print(f"HEADLINE: net at penalty={HEADLINE_PENALTY}, cost=realistic (0.32% RT)")
    print("=" * 100)
    headline_panels = {}
    for label, returns in six_gross.items():
        holdings = holdings_by_label[label]
        penalized = apply_limit_down_penalty(
            returns, holdings, panel, PENALTY_LEVELS[HEADLINE_PENALTY],
        )
        net = apply_costs(penalized, holdings, COST_LEVELS["realistic"])
        headline_panels[label] = net

    headline_metrics = [
        compute_metrics(r, label) for label, r in headline_panels.items()
    ]
    print_panel_table(headline_metrics, "Headline net metrics")

    # Stress net comparison (penalty=10%, cost=aggressive)
    print("\n" + "=" * 100)
    print("STRESS: net at penalty=10%, cost=aggressive (0.92% RT)")
    print("=" * 100)
    stress_panels = {}
    for label, returns in six_gross.items():
        holdings = holdings_by_label[label]
        penalized = apply_limit_down_penalty(
            returns, holdings, panel, PENALTY_LEVELS["10%"],
        )
        net = apply_costs(penalized, holdings, COST_LEVELS["aggressive"])
        stress_panels[label] = net

    stress_metrics = [
        compute_metrics(r, label) for label, r in stress_panels.items()
    ]
    print_panel_table(stress_metrics, "Stress net metrics")

    # Save outputs
    out_metrics_csv = DATA_DIR / f"{OUTPUT_PREFIX}_metrics.csv"
    pd.DataFrame({
        "headline": pd.DataFrame(headline_metrics).set_index("label").to_dict(),
        "stress":   pd.DataFrame(stress_metrics).set_index("label").to_dict(),
    }).to_csv(out_metrics_csv)
    print(f"\nMetrics saved to: {out_metrics_csv}")

    out_returns_csv = DATA_DIR / f"{OUTPUT_PREFIX}_returns.csv"
    pd.DataFrame(headline_panels).to_csv(out_returns_csv)
    print(f"Returns (headline) saved to: {out_returns_csv}")

    # Plots
    plot_sensitivity_matrix(
        grids, GRAPHS_OUT / f"{OUTPUT_PREFIX}_sensitivity_matrix.png",
    )
    plot_cumulative_net(
        headline_panels, GRAPHS_OUT / f"{OUTPUT_PREFIX}_cumulative_headline.png",
        scenario_label=f"Penalty={HEADLINE_PENALTY}, cost=realistic",
    )
    plot_cumulative_net(
        stress_panels, GRAPHS_OUT / f"{OUTPUT_PREFIX}_cumulative_stress.png",
        scenario_label="Penalty=10%, cost=aggressive",
    )
    print(f"Plots saved to: {GRAPHS_OUT}/")

    print(f"\n{'=' * 76}")
    print("Cost-adjusted analysis complete.")
    print('=' * 76)