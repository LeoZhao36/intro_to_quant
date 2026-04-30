"""
composite_segmented.py — Six-panel strategy comparison on the rebuilt
weekly panel.

Strategies
----------
1. baseline:    universe-equal-weight (all 1000 in-universe stocks).
2. mom_only:    long the worst recent performers (z_mom Q5).
3. segmented:   value-Q5 in low/mid cap (66% of universe by stock count)
                + lowvol-Q1 in high-cap (33%)
                + z_mom Q5 universe-wide
                Three legs equal-weighted; weights set so each leg is
                33% of capital, regardless of how many stocks each leg
                holds. So the segmented portfolio's gross exposure is 1.0
                with three sub-portfolios at 0.33 each.

Each strategy is run twice: gate off (always invested) and gate on
(in cash on weeks where 12-week trailing Sharpe of baseline > +1.5
annualized). Six panels total.

Sign convention
---------------
z_value  = +z(ep)                 cheap = high z_value
z_lowvol = -z(vol_52_4)           low vol = high z_lowvol
z_mom    = -z(mom_4_1)            recent loser = high z_mom

For all three z-factors, "high z_X" = predicted outperform per Phase B/C.
Therefore Q5 (top quintile of z) = expected winners for each.

Stimulus gate
-------------
Trigger: 12-week trailing Sharpe of universe-EW baseline > +1.5 annualized.
Action: hold cash (zero return) that week.
Re-entry: when trigger drops below threshold the next week, re-enter.
Cash assumption: zero return. Conservative reading of the gate; adding
realistic short-term rates wouldn't change the qualitative comparison.

The gate is computed in-sample on the entire panel; this is not a
forecast, just a regime indicator. A real implementation would use
information available only up to the rebalance date (which the trailing
window already does, since trailing-12 ends at week t-1 for the week-t
position).

Cost
----
GROSS ONLY at this stage. Phase D adds proper cost-adjustment with
the limit-state filter; this script is for understanding factor
behavior, not for quoting tradable returns.

Strategy selection logic
------------------------
Phase B/C results drove these choices:
  - Pure mom is the simplest viable strategy; mom_4_1 was universal
    BH-rejection in single-factor and dominated FMB. The honest baseline.
  - Segmented composite isolates each factor in the cap segment where
    multivariate FMB found independent signal (z_value in mid-cap,
    z_lowvol in high-cap, z_mom universal). Linear z-score composites
    of the kind the old monthly code used were dropped because Phase B
    showed value's signal is non-linear (lives in tail) and lowvol works
    only in high-cap, so equal-weighted pooling dilutes both.
  - Universe-EW baseline applied with the gate too — without this
    control, any "gate improves performance" finding could just be
    "cash beats stocks during stimulus regimes" and not strategy-specific.

Run from Project_6/:
    python Factor_Analysis_Weekly_Universe/composite_segmented.py
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


# ─── Configuration ─────────────────────────────────────────────────────

GATE_LOOKBACK = 12     # weeks of trailing Sharpe
GATE_THRESHOLD = 1.5   # annualized Sharpe trigger
SEGMENTED_LEG_WEIGHT = 1.0 / 3.0  # equal-weight three legs

# Plot output goes to broad Project_6 graphs/ directory, not subfolder.
GRAPHS_OUT = Path("graphs")
GRAPHS_OUT.mkdir(exist_ok=True)

OUTPUT_PREFIX = "composite_segmented"


# ─── Strategy construction ─────────────────────────────────────────────

def compute_baseline_returns(panel: pd.DataFrame) -> pd.Series:
    """Universe equal-weight: all in-universe stocks, equal-weighted, weekly."""
    return (
        panel[panel["in_universe"]]
        .dropna(subset=["forward_return"])
        .groupby("rebalance_date")["forward_return"]
        .mean()
    )


def compute_mom_only_returns(panel: pd.DataFrame) -> pd.Series:
    """z_mom Q5 portfolio: top quintile of -mom_4_1 = worst recent performers."""
    df = panel[panel["in_universe"]].dropna(
        subset=["z_mom", "forward_return"]
    ).copy()
    df["q"] = df.groupby("rebalance_date")["z_mom"].transform(
        lambda s: pd.qcut(s, 5, labels=False, duplicates="drop")
    )
    return (
        df[df["q"] == 4]
        .groupby("rebalance_date")["forward_return"]
        .mean()
    )


def compute_segmented_returns(panel: pd.DataFrame) -> tuple:
    """
    Segmented composite: three legs, equal capital weight per leg.
      Leg 1: value Q5 within low-cap and mid-cap stocks combined
      Leg 2: lowvol Q5 within high-cap stocks (= bottom vol within high-cap)
      Leg 3: z_mom Q5 universe-wide

    Returns (combined_return_series, per_leg_dict_of_series).
    """
    df = panel[panel["in_universe"]].copy()
    df["cap_tercile"] = (
        df.groupby("rebalance_date")["log_mcap"]
        .transform(
            lambda s: pd.qcut(s, 3, labels=["low", "mid", "high"],
                              duplicates="drop")
        )
    )

    # Leg 1: value Q5 in (low + mid) cap. Sort EP within (low+mid) per date.
    low_mid = df[df["cap_tercile"].isin(["low", "mid"])].copy()
    low_mid["q"] = low_mid.groupby("rebalance_date")["z_value"].transform(
        lambda s: pd.qcut(s, 5, labels=False, duplicates="drop")
    )
    leg_value = (
        low_mid[low_mid["q"] == 4]
        .dropna(subset=["forward_return"])
        .groupby("rebalance_date")["forward_return"]
        .mean()
    )

    # Leg 2: lowvol Q5 in high-cap. Sort z_lowvol within high-cap per date.
    high = df[df["cap_tercile"] == "high"].copy()
    high["q"] = high.groupby("rebalance_date")["z_lowvol"].transform(
        lambda s: pd.qcut(s, 5, labels=False, duplicates="drop")
    )
    leg_lowvol = (
        high[high["q"] == 4]
        .dropna(subset=["forward_return"])
        .groupby("rebalance_date")["forward_return"]
        .mean()
    )

    # Leg 3: z_mom Q5 universe-wide
    leg_mom = compute_mom_only_returns(panel)

    # Equal-weight combination across legs that have data on each date
    legs = pd.DataFrame({
        "leg_value": leg_value,
        "leg_lowvol": leg_lowvol,
        "leg_mom": leg_mom,
    })
    combined = legs.mean(axis=1, skipna=True)
    return combined, {
        "leg_value": leg_value,
        "leg_lowvol": leg_lowvol,
        "leg_mom": leg_mom,
    }


# ─── Stimulus gate ─────────────────────────────────────────────────────

def compute_gate_signal(
    baseline_returns: pd.Series,
    lookback: int = GATE_LOOKBACK,
    threshold: float = GATE_THRESHOLD,
) -> pd.Series:
    """
    Boolean series: True where 12-week trailing Sharpe of baseline > 1.5 ann.
    Trailing means uses returns up to and including week t-1 to gate week t.
    Use shift(1) so the gate value at date t is computed only from prior weeks.

    Note: at the start of the panel, the trailing window has insufficient
    data; gate defaults to False (do not exit) for those early weeks.
    """
    rolling = baseline_returns.rolling(window=lookback, min_periods=lookback)
    trailing_sharpe = (rolling.mean() / rolling.std()) * ANNUAL_FACTOR_SQRT
    # Shift forward so the indicator at date t reflects info up to t-1
    gate = (trailing_sharpe.shift(1) > threshold).fillna(False)
    return gate


def apply_gate(returns: pd.Series, gate: pd.Series) -> pd.Series:
    """Where gate is True, return is zero (cash). Aligns on date index."""
    aligned = returns.copy()
    aligned_gate = gate.reindex(aligned.index, fill_value=False)
    return aligned.where(~aligned_gate, 0.0)


# ─── Metrics ───────────────────────────────────────────────────────────

def compute_metrics(returns: pd.Series, label: str) -> dict:
    """
    Standard rubric for each panel:
      - n weeks active (non-NaN)
      - gross annualized return (geometric)
      - gross annualized Sharpe
      - cumulative return at end
      - max drawdown
      - fraction of weeks in cash (for gated panels)
    """
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return {"label": label}

    # Geometric ann return
    cum = (1 + r).cumprod()
    final = float(cum.iloc[-1])
    years = n / PERIODS_PER_YEAR
    ann_geom = final ** (1 / years) - 1 if years > 0 else np.nan

    # Sharpe
    mean = float(r.mean())
    std = float(r.std())
    sharpe_ann = mean / std * ANNUAL_FACTOR_SQRT if std > 0 else np.nan

    # Max drawdown
    rolling_max = cum.cummax()
    drawdown = (cum / rolling_max) - 1
    max_dd = float(drawdown.min())

    # Cash weeks
    n_cash = int((r == 0).sum())

    return {
        "label": label,
        "n_weeks": n,
        "ann_return_pct": ann_geom * 100,
        "ann_sharpe": sharpe_ann,
        "cumulative_pct": (final - 1) * 100,
        "max_drawdown_pct": max_dd * 100,
        "n_cash_weeks": n_cash,
        "frac_cash": n_cash / n,
        "weekly_mean_pct": mean * 100,
        "weekly_std_pct": std * 100,
    }


def alpha_vs_baseline(
    strat: pd.Series, baseline: pd.Series, label: str,
) -> dict:
    """
    Mean weekly alpha (strat - baseline), t-stat, annualized alpha.
    Uses the intersection of dates so cash weeks contribute (strat=0,
    baseline=whatever), reflecting the gate's actual cost when baseline
    rallied while strat was in cash.
    """
    aligned = pd.concat([strat.rename("s"), baseline.rename("b")], axis=1, sort=True).dropna()
    diff = aligned["s"] - aligned["b"]
    n = len(diff)
    if n == 0:
        return {"label": label}
    mean = float(diff.mean())
    std = float(diff.std())
    t_stat = mean / (std / np.sqrt(n)) if std > 0 else np.nan
    return {
        "label": label,
        "n": n,
        "alpha_pct_wk": mean * 100,
        "alpha_ann_pct": mean * PERIODS_PER_YEAR * 100,
        "alpha_t_stat": t_stat,
    }


def print_metrics_table(panels: dict) -> None:
    """6-panel comparison output."""
    print(f"\n{'=' * 110}")
    print("Six-panel strategy comparison (gross, no costs)")
    print('=' * 110)
    header = (
        f"{'Strategy':<28s} {'NWeeks':>6s} "
        f"{'AnnRet%':>9s} {'AnnSh':>8s} {'Cum%':>9s} "
        f"{'MaxDD%':>9s} {'Cash%':>8s} {'WkMean%':>9s} {'WkStd%':>8s}"
    )
    print(header)
    print('-' * len(header))
    for label, m in panels.items():
        print(
            f"{label:<28s} {m['n_weeks']:>6d} "
            f"{m['ann_return_pct']:>+8.2f} {m['ann_sharpe']:>+8.2f} "
            f"{m['cumulative_pct']:>+8.1f} {m['max_drawdown_pct']:>+8.1f} "
            f"{m['frac_cash']*100:>7.1f} {m['weekly_mean_pct']:>+8.3f} "
            f"{m['weekly_std_pct']:>7.3f}"
        )


def print_alpha_table(alphas: dict) -> None:
    """Alpha vs baseline (gate-off baseline as the universal reference)."""
    print(f"\n{'=' * 80}")
    print("Alpha vs gate-off baseline (the most conservative reference)")
    print('=' * 80)
    header = (
        f"{'Strategy':<28s} {'N':>5s} "
        f"{'Alpha%/wk':>11s} {'Alpha ann%':>11s} {'AlphaT':>9s}"
    )
    print(header)
    print('-' * len(header))
    for label, a in alphas.items():
        print(
            f"{label:<28s} {a['n']:>5d} "
            f"{a['alpha_pct_wk']:>+10.4f} "
            f"{a['alpha_ann_pct']:>+10.2f} {a['alpha_t_stat']:>+9.2f}"
        )


# ─── Plotting ──────────────────────────────────────────────────────────

def plot_cumulative_returns(panels_returns: dict, save_path: Path) -> None:
    """All six cumulative-return lines on one chart with regime markers."""
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

    ax.set_title("Six-panel strategy comparison — cumulative gross returns")
    ax.set_xlabel("Rebalance date")
    ax.set_ylabel("Cumulative return (×)")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_drawdowns(panels_returns: dict, save_path: Path) -> None:
    """Drawdown time series for each strategy."""
    fig, ax = plt.subplots(figsize=(13, 6))
    style = {
        "baseline (gate off)":    ("#888888", 1.2, "-"),
        "baseline (gate on)":     ("#888888", 1.2, "--"),
        "mom_only (gate off)":    ("#1f77b4", 1.5, "-"),
        "mom_only (gate on)":     ("#1f77b4", 1.5, "--"),
        "segmented (gate off)":   ("#d62728", 1.5, "-"),
        "segmented (gate on)":    ("#d62728", 1.5, "--"),
    }
    for label, returns in panels_returns.items():
        cum = (1 + returns.fillna(0)).cumprod()
        rolling_max = cum.cummax()
        dd = (cum / rolling_max - 1) * 100
        c, lw, ls = style.get(label, ("black", 1.0, "-"))
        ax.plot(dd.index, dd.values, label=label,
                color=c, linewidth=lw, linestyle=ls)

    for label, event_date in REGIME_EVENTS.items():
        ax.axvline(event_date, color="grey", linestyle="--",
                   alpha=0.55, linewidth=0.9)
    ax.set_title("Drawdowns by strategy")
    ax.set_xlabel("Rebalance date")
    ax.set_ylabel("Drawdown (%)")
    ax.legend(loc="lower left", fontsize=9, framealpha=0.85)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_gate_signal(
    baseline_returns: pd.Series, gate: pd.Series, save_path: Path,
) -> None:
    """Trailing Sharpe, threshold, and gate-on shading. Diagnostic plot."""
    rolling = baseline_returns.rolling(GATE_LOOKBACK, min_periods=GATE_LOOKBACK)
    trailing_sharpe = (rolling.mean() / rolling.std()) * ANNUAL_FACTOR_SQRT

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(trailing_sharpe.index, trailing_sharpe.values,
            color="steelblue", linewidth=1.2,
            label=f"Trailing {GATE_LOOKBACK}-week ann. Sharpe of baseline")
    ax.axhline(GATE_THRESHOLD, color="firebrick", linestyle="--",
               linewidth=1, label=f"Gate threshold = +{GATE_THRESHOLD}")
    ax.axhline(0, color="black", linewidth=0.5)

    # Shade gate-on weeks
    for date in gate[gate].index:
        ax.axvspan(date, date + pd.Timedelta(days=7),
                   color="firebrick", alpha=0.15)

    for label, event_date in REGIME_EVENTS.items():
        ax.axvline(event_date, color="grey", linestyle="--",
                   alpha=0.55, linewidth=0.9)
        ax.text(event_date, ax.get_ylim()[1] * 0.95, label,
                rotation=90, verticalalignment="top",
                fontsize=8, color="dimgrey")

    n_gated = int(gate.sum())
    n_total = int(gate.shape[0])
    ax.set_title(
        f"Stimulus gate diagnostic — {n_gated} of {n_total} weeks gated "
        f"({100*n_gated/n_total:.1f}%); cash on red-shaded weeks"
    )
    ax.set_xlabel("Rebalance date")
    ax.set_ylabel("Annualized Sharpe")
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
    print(f"  in-universe rows: {int(panel['in_universe'].sum()):,}")

    panel = add_all_factors(panel)

    # Compute the three gross strategies
    print("\nComputing gross strategies...")
    baseline = compute_baseline_returns(panel)
    print(f"  baseline:  {len(baseline)} weeks active")
    mom_only = compute_mom_only_returns(panel)
    print(f"  mom_only:  {len(mom_only)} weeks active")
    segmented, legs = compute_segmented_returns(panel)
    print(f"  segmented: {len(segmented)} weeks active "
          f"(leg_value: {len(legs['leg_value'])}, "
          f"leg_lowvol: {len(legs['leg_lowvol'])}, "
          f"leg_mom: {len(legs['leg_mom'])})")

    # Build the gate from baseline
    print(f"\nComputing stimulus gate "
          f"(lookback={GATE_LOOKBACK}, threshold=+{GATE_THRESHOLD} ann)...")
    gate = compute_gate_signal(baseline)
    n_gated = int(gate.sum())
    n_total = int(gate.shape[0])
    print(f"  {n_gated} of {n_total} weeks gated "
          f"({100*n_gated/n_total:.1f}%)")
    if n_gated > 0:
        first_gate = gate[gate].index.min()
        last_gate = gate[gate].index.max()
        print(f"  first gated week: {first_gate.date()}")
        print(f"  last gated week:  {last_gate.date()}")

    # Apply gate to all three strategies
    print("\nApplying gate uniformly across strategies...")
    panels = {
        "baseline (gate off)":  baseline,
        "baseline (gate on)":   apply_gate(baseline, gate),
        "mom_only (gate off)":  mom_only,
        "mom_only (gate on)":   apply_gate(mom_only, gate),
        "segmented (gate off)": segmented,
        "segmented (gate on)":  apply_gate(segmented, gate),
    }

    # Metrics for each panel
    metrics = {label: compute_metrics(r, label) for label, r in panels.items()}
    print_metrics_table(metrics)

    # Alpha vs gate-off baseline (consistent reference)
    alphas = {
        label: alpha_vs_baseline(r, baseline, label)
        for label, r in panels.items()
        if label != "baseline (gate off)"  # skip self-vs-self
    }
    print_alpha_table(alphas)

    # Save numerical results
    metrics_df = pd.DataFrame(metrics).T
    out_metrics = DATA_DIR / f"{OUTPUT_PREFIX}_metrics.csv"
    metrics_df.to_csv(out_metrics)
    print(f"\nMetrics saved to: {out_metrics}")

    returns_df = pd.DataFrame(panels)
    out_returns = DATA_DIR / f"{OUTPUT_PREFIX}_returns.csv"
    returns_df.to_csv(out_returns)
    print(f"Returns saved to: {out_returns}")

    # Plots — to broad Project_6/graphs/
    plot_cumulative_returns(
        panels, GRAPHS_OUT / f"{OUTPUT_PREFIX}_cumulative.png"
    )
    plot_drawdowns(
        panels, GRAPHS_OUT / f"{OUTPUT_PREFIX}_drawdowns.png"
    )
    plot_gate_signal(
        baseline, gate, GRAPHS_OUT / f"{OUTPUT_PREFIX}_gate_diagnostic.png"
    )
    print(f"Plots saved to:   {GRAPHS_OUT}/")

    print(f"\n{'=' * 76}")
    print("Composite + segmented analysis complete.")
    print('=' * 76)