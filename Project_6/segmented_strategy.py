"""
segmented_strategy.py

Project 6 multi-factor: tests whether deploying each factor in its strong
cap segment (value in low-cap, low-vol in high-cap) produces better
long-only returns than universe-wide deployment of the same factors or
their composite.

Strategies tested
-----------------
1. segmented:        50% value Q5 in low-cap + 50% lowvol Q1 in high-cap
2. value_low_leg:    value Q5 in low-cap tercile (one leg of segmented)
3. lowvol_high_leg:  lowvol Q1 in high-cap tercile (other leg of segmented)
4. value_full:       value Q5 across full universe
5. lowvol_full:      lowvol Q1 across full universe
6. composite_full:   z_value + z_lowvol composite Q5 across full universe
7. baseline:         universe-equal-weight (passive)

Hypothesis
----------
Strategy 1 outperforms 4-6 on alpha vs baseline, because single-factor
work showed each factor has signal only in one cap segment. Equal-
weighting universe-wide (composite_full) dilutes; segmenting avoids that.

Sub-tests via pairwise comparisons:
  value_low_leg vs value_full     : where does value's signal live?
  lowvol_high_leg vs lowvol_full  : where does low-vol's signal live?
  segmented vs composite_full     : segmented vs pooled multi-factor
  segmented vs each leg alone     : does combining legs add diversification?

Sign convention
---------------
EP: higher = cheaper. Q5 = cheapest = expected winners.
vol: lower = expected winners. Q1 = lowest = expected winners.
Composite (z_value + z_lowvol): higher = expected winners. Q5 = highest.

Logged predictions
------------------
Cumulative-return ranking: segmented > both legs > value_full > composite
   > lowvol_full > baseline. Most uncertain about segmented vs each leg
   alone (diversification benefit might be small if legs are correlated).

Segmented alpha vs baseline: +0.4 to +1.0%/mo (5-12%/yr arithmetic).
   t-stat in [+1.0, +2.5]. CI may still contain zero given n~40.

value_low_leg alpha > value_full alpha: yes, by ~0.3-0.7%/mo.
lowvol_high_leg alpha > lowvol_full alpha: yes, by ~0.5-1.0%/mo.

Regime: segmented works pre-stimulus, fails post-stimulus (inheriting
   low-vol's regime sensitivity from single-factor work).

Failure modes
-------------
1. Smaller portfolios (~67 stocks per leg) than universe-wide quintiles
   (~200 stocks), so monthly noise is higher. Cumulative returns will
   look rougher than headline Q1-Q5 spreads.
2. No transaction costs included. The closeout's open cost-Sharpe item
   is more important here than for single-factor because segmented
   has higher portfolio turnover at rebalance (only ~67 stocks held,
   so a name leaving the leg is a bigger fraction of the portfolio).
3. Inference still constrained by ~40 testable dates after burn-in.
4. Strategies inherit the universe-turnover problem; segmented-strategy
   coverage in each leg is whatever the underlying factor's coverage
   is in that tercile.

Run from Project_6/ as: `python segmented_strategy.py`
Prerequisites: data/ep_panel.csv (run source_ep_data.py first)
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from factor_utils import (
    DATA_DIR,
    GRAPHS_DIR,
    REGIME_EVENTS,
    SEED,
    load_panel,
)
from hypothesis_testing import block_bootstrap_ci
from value_analysis import add_ep_to_panel
from lowvol_analysis import add_volatility_to_panel
from composite_value_lowvol_analysis import cross_sectional_zscore


# Configuration ---------------------------------------------------------
LOWVOL_LOOKBACK = 12   # vol_12_1: BH-rejecting single-factor cell
LOWVOL_SKIP = 1
MIN_COVERAGE = 0.75

OUTPUT_PREFIX = "segmented"


# Helpers ---------------------------------------------------------------

def long_only_return(
    panel: pd.DataFrame,
    mask: pd.Series,
    return_col: str = "forward_return",
) -> pd.Series:
    """Equal-weighted forward return of stocks where mask is True."""
    df = panel[mask].dropna(subset=[return_col])
    return df.groupby("rebalance_date")[return_col].mean()


def per_date_count(panel: pd.DataFrame, mask: pd.Series) -> pd.Series:
    """Stocks in selection per rebalance_date (diagnostic)."""
    return panel[mask].groupby("rebalance_date").size()


# Strategy construction -------------------------------------------------

def build_strategies(panel: pd.DataFrame) -> tuple:
    """
    Compute monthly forward returns and per-date stock counts for all
    seven strategies. Returns (returns_df, counts_df).
    """
    vol_col = f"vol_{LOWVOL_LOOKBACK}_{LOWVOL_SKIP}"
    panel = panel.copy()

    # Cap tercile per date (log_mcap is never NaN in our universe).
    panel["cap_tercile"] = (
        panel.groupby("rebalance_date")["log_mcap"]
        .transform(
            lambda s: pd.qcut(s, 3, labels=["low", "mid", "high"], duplicates="drop")
        )
    )

    # Within-tercile quintiles per date.
    panel["ep_q_in_tercile"] = (
        panel.groupby(["rebalance_date", "cap_tercile"], observed=True)["ep"]
        .transform(lambda s: pd.qcut(s, 5, labels=False, duplicates="drop"))
    )
    panel["vol_q_in_tercile"] = (
        panel.groupby(["rebalance_date", "cap_tercile"], observed=True)[vol_col]
        .transform(lambda s: pd.qcut(s, 5, labels=False, duplicates="drop"))
    )

    # Universe-wide quintiles per date.
    panel["ep_q_uni"] = (
        panel.groupby("rebalance_date")["ep"]
        .transform(lambda s: pd.qcut(s, 5, labels=False, duplicates="drop"))
    )
    panel["vol_q_uni"] = (
        panel.groupby("rebalance_date")[vol_col]
        .transform(lambda s: pd.qcut(s, 5, labels=False, duplicates="drop"))
    )
    panel["comp_q_uni"] = (
        panel.groupby("rebalance_date")["z_composite_v_lv"]
        .transform(lambda s: pd.qcut(s, 5, labels=False, duplicates="drop"))
    )

    # Build masks and compute returns.
    masks = {
        "value_low_leg":   (panel["cap_tercile"] == "low")  & (panel["ep_q_in_tercile"]  == 4),
        "lowvol_high_leg": (panel["cap_tercile"] == "high") & (panel["vol_q_in_tercile"] == 0),
        "value_full":      panel["ep_q_uni"]   == 4,
        "lowvol_full":     panel["vol_q_uni"]  == 0,
        "composite_full":  panel["comp_q_uni"] == 4,
    }

    returns = {name: long_only_return(panel, m) for name, m in masks.items()}
    counts  = {name: per_date_count(panel, m)   for name, m in masks.items()}

    # Baseline: universe-equal-weight.
    returns["baseline"] = (
        panel.dropna(subset=["forward_return"])
        .groupby("rebalance_date")["forward_return"].mean()
    )
    counts["baseline"] = (
        panel.dropna(subset=["forward_return"])
        .groupby("rebalance_date").size()
    )

    returns_df = pd.DataFrame(returns)
    counts_df = pd.DataFrame(counts)

    # Segmented: 50/50 of the two legs. mean(axis=1) handles burn-in
    # gracefully (NaN if a leg is missing on that date).
    returns_df["segmented"] = (
        returns_df[["value_low_leg", "lowvol_high_leg"]].mean(axis=1)
    )
    counts_df["segmented"] = (
        counts_df[["value_low_leg", "lowvol_high_leg"]].sum(axis=1)
    )

    # Reorder for display.
    order = [
        "segmented",
        "value_low_leg", "lowvol_high_leg",
        "value_full", "lowvol_full", "composite_full",
        "baseline",
    ]
    return returns_df[order], counts_df[order]


# Reporting -------------------------------------------------------------

def report_counts(counts: pd.DataFrame) -> None:
    """Per-strategy stock-count diagnostics."""
    aligned = counts.dropna()
    print(f"\nPer-strategy stock counts per date "
          f"(aligned dates only, n={len(aligned)}):")
    summary = aligned.agg(["mean", "median", "min", "max"]).round(0).astype(int)
    print(summary.T.to_string())


def compute_strategy_metrics(returns: pd.DataFrame,
                              baseline_col: str = "baseline") -> pd.DataFrame:
    """Per-strategy mean, std, Sharpe, cum, alpha, alpha t, bootstrap CI."""
    aligned = returns.dropna()
    n = len(aligned)
    print(f"\nCommon testable dates (intersection): n={n}")
    print(f"  Date range: {aligned.index.min().date()} to "
          f"{aligned.index.max().date()}")

    rows = []
    for col in aligned.columns:
        r = aligned[col]
        mean = r.mean()
        std = r.std()
        sharpe = mean / std * np.sqrt(12) if std > 0 else np.nan
        cum = (1 + r).prod() - 1

        if col == baseline_col:
            alpha_mean = alpha_t = np.nan
            alpha_ci_low = alpha_ci_high = np.nan
        else:
            alpha = r - aligned[baseline_col]
            alpha_mean = alpha.mean()
            a_std = alpha.std()
            alpha_t = alpha_mean / (a_std / np.sqrt(n)) if a_std > 0 else np.nan
            boot = block_bootstrap_ci(
                alpha.values, np.mean,
                block_size=3, n_boot=5000, seed=SEED,
            )
            alpha_ci_low, alpha_ci_high = boot["ci_low"], boot["ci_high"]

        rows.append({
            "strategy": col,
            "mean_mo": mean,
            "std_mo": std,
            "sharpe_ann": sharpe,
            "cum": cum,
            "alpha_mo": alpha_mean,
            "alpha_t": alpha_t,
            "alpha_ci_low": alpha_ci_low,
            "alpha_ci_high": alpha_ci_high,
        })
    return pd.DataFrame(rows).set_index("strategy")


def print_metrics_table(metrics: pd.DataFrame) -> None:
    print(f"\n{'=' * 110}")
    print(f"{'Strategy':<18s} {'Mean%/mo':>9s} {'Std%/mo':>8s} "
          f"{'Sharpe':>7s} {'Cum%':>7s} | "
          f"{'Alpha%/mo':>10s} {'AlphaT':>7s} {'Alpha 95% CI':>22s}")
    print('=' * 110)
    for s, row in metrics.iterrows():
        if pd.isna(row["alpha_t"]):
            alpha_str = a_t_str = ci_str = "-"
        else:
            alpha_str = f"{row['alpha_mo']*100:+.3f}"
            a_t_str = f"{row['alpha_t']:+.2f}"
            ci_str = (f"[{row['alpha_ci_low']*100:+.2f}, "
                      f"{row['alpha_ci_high']*100:+.2f}]")
        print(
            f"{s:<18s} {row['mean_mo']*100:>+8.3f} "
            f"{row['std_mo']*100:>+7.3f} {row['sharpe_ann']:>+7.2f} "
            f"{row['cum']*100:>+6.1f} | "
            f"{alpha_str:>10s} {a_t_str:>7s} {ci_str:>22s}"
        )


def regime_split_report(returns: pd.DataFrame, split_date: pd.Timestamp) -> None:
    """Per-regime mean and Sharpe for each strategy."""
    from factor_utils import REGIME_SPLIT_DATE
    aligned = returns.dropna()
    pre = aligned[aligned.index < split_date]
    post = aligned[aligned.index >= split_date]

    print(f"\nRegime split at {split_date.date()} (PBoC stimulus):")
    print(f"  Pre n={len(pre)}, Post n={len(post)}")
    header = (
        f"  {'Strategy':<18s} "
        f"{'Pre %/mo':>9s} {'Pre Sh':>7s} {'Post %/mo':>10s} {'Post Sh':>8s}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for col in aligned.columns:
        pre_m = pre[col].mean()
        pre_s = pre_m / pre[col].std() * np.sqrt(12) if pre[col].std() > 0 else np.nan
        post_m = post[col].mean()
        post_s = post_m / post[col].std() * np.sqrt(12) if post[col].std() > 0 else np.nan
        print(
            f"  {col:<18s} "
            f"{pre_m*100:>+8.3f} {pre_s:>+7.2f} "
            f"{post_m*100:>+9.3f} {post_s:>+8.2f}"
        )


# Plotting --------------------------------------------------------------

def plot_strategies(returns: pd.DataFrame, save_path: Path) -> None:
    aligned = returns.dropna()
    cum = (1 + aligned).cumprod()

    fig, ax = plt.subplots(figsize=(13, 6.5))
    style = {
        "segmented":       ("firebrick",    2.4, "-",  5),
        "value_low_leg":   ("darkorange",   1.5, "--", 3),
        "lowvol_high_leg": ("darkviolet",   1.5, "--", 3),
        "value_full":      ("gold",         1.3, ":",  2),
        "lowvol_full":     ("mediumpurple", 1.3, ":",  2),
        "composite_full":  ("steelblue",    1.6, "-",  4),
        "baseline":        ("dimgrey",      1.4, "-.", 1),
    }
    for col in cum.columns:
        c, lw, ls, z = style.get(col, ("black", 1.0, "-", 1))
        ax.plot(cum.index, cum[col], label=col,
                color=c, linewidth=lw, linestyle=ls, zorder=z)

    ymax = ax.get_ylim()[1]
    for label, event_date in REGIME_EVENTS.items():
        ax.axvline(event_date, color="grey", linestyle="--",
                   alpha=0.5, linewidth=0.9)
        ax.text(event_date, ymax * 0.985, label,
                rotation=90, verticalalignment="top",
                fontsize=8, color="dimgrey")

    ax.set_title(
        f"Long-only strategies: cumulative returns "
        f"(vol_{LOWVOL_LOOKBACK}_{LOWVOL_SKIP})"
    )
    ax.set_xlabel("Rebalance date")
    ax.set_ylabel("Cumulative return (×)")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


# Main ------------------------------------------------------------------

if __name__ == "__main__":
    panel = load_panel()
    print(f"Panel loaded: {len(panel):,} rows, "
          f"{panel['rebalance_date'].nunique()} dates")

    # Add factor data.
    panel = add_ep_to_panel(panel)
    panel = add_volatility_to_panel(
        panel,
        lookback=LOWVOL_LOOKBACK,
        skip=LOWVOL_SKIP,
        min_coverage=MIN_COVERAGE,
    )

    # Composite z-score (for composite_full strategy).
    panel = cross_sectional_zscore(panel, "ep", "z_ep")
    panel = cross_sectional_zscore(
        panel, f"vol_{LOWVOL_LOOKBACK}_{LOWVOL_SKIP}", "z_vol",
    )
    panel["z_value"] = +panel["z_ep"]
    panel["z_lowvol"] = -panel["z_vol"]
    panel["z_composite_v_lv"] = panel["z_value"] + panel["z_lowvol"]

    print(f"\n{'=' * 76}")
    print(f"Segmented strategy analysis (vol_{LOWVOL_LOOKBACK}_{LOWVOL_SKIP})")
    print(f"{'=' * 76}")

    returns, counts = build_strategies(panel)
    report_counts(counts)

    metrics = compute_strategy_metrics(returns)
    print_metrics_table(metrics)

    from factor_utils import REGIME_SPLIT_DATE
    regime_split_report(returns, REGIME_SPLIT_DATE)

    # Save outputs.
    plot_path = GRAPHS_DIR / f"{OUTPUT_PREFIX}_cumulative_returns.png"
    plot_strategies(returns, plot_path)
    print(f"\nCumulative-return plot saved to: {plot_path}")

    csv_path = DATA_DIR / f"{OUTPUT_PREFIX}_metrics.csv"
    metrics.to_csv(csv_path)
    returns_path = DATA_DIR / f"{OUTPUT_PREFIX}_returns.csv"
    returns.to_csv(returns_path)
    print(f"Metrics saved to:    {csv_path}")
    print(f"Returns saved to:    {returns_path}")

    print(f"\n{'=' * 76}")
    print("Segmented strategy analysis complete.")
    print(f"{'=' * 76}")