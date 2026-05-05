"""
concentration_sweep.py — How does z_turnover_resid scale with basket size?

Tests deployment at TOP_N for N in {20, 50, 100, 200, 500, 700} on Universe
A across the three regimes (alpha_all, beta_pre_NNA, gamma_post_NNA).

Same factor (z_turnover_resid). Same cost model (0.18% roundtrip × churn).
The only thing that varies is the basket size.

Why this run exists
-------------------
Top-700 is the right concentration for FACTOR RESEARCH (large enough to
average out idiosyncratic risk and produce stable cross-sectional reads).
Top-700 is the wrong concentration for RETAIL DEPLOYMENT (no realistic
retail account holds 700 names). The deployable target is 10-20 names.

The point of this run is to find out how far the IR you measured at
top-700 actually scales as you compress the basket. Concretely:
  - At what N does the IR estimate become statistically indistinguishable
    from zero (its bootstrap CI crosses zero)?
  - At what N does max drawdown become unacceptable?
  - At what N does sector concentration spike to a level where one
    industry can take down the whole portfolio?

Metrics that become important at low N
--------------------------------------
  - net IR with block bootstrap 95% CI on the IR ITSELF (not Sharpe),
    because at low N the IR point estimate has standard error ~0.5-0.8
  - max drawdown
  - max_sector_pct: peak share of basket in single SW L1 industry
                    (time-series mean across rebalances in the regime)
  - n_unique_sectors: average number of distinct sectors represented
  - sortino: downside-std variant of Sharpe; relevant when fat-tail
             single-stock blow-ups skew returns
  - monthly hit rate: % of months where basket beat universe_ew
  - worst weekly active return: tail risk diagnostic

Costs caveat
------------
The 0.18% roundtrip is institutional/conservative. At retail manual
trading, realistic roundtrip is closer to 0.10-0.14% (commission ~0.025%
per side, stamp duty 0.05% sell-side only, slippage near zero on liquid
small-caps at retail size). Net IR figures here probably understate
deployable IR by ~0.05-0.10 points in absolute terms. Kept at 0.18% for
consistency with prior runs in this project; sensitivity-test separately.

Usage
-----
    python concentration_sweep.py run    # full sweep, all regimes
    python concentration_sweep.py status # check cached outputs
"""

import argparse
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    GRAPHS_DIR,
    THREE_REGIME_WINDOWS,
    TRADING_CALENDAR_PATH,
    TRADING_DAYS_PER_YEAR,
)
from hypothesis_testing import block_bootstrap_ci
from combination_analysis import (
    build_top_n_baskets,
    compute_basket_churn,
    run_top_n_backtest,
)
from turnover_neutralized import load_panel_with_sector, add_z_turnover_resid


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
GRAPHS_DIR.mkdir(exist_ok=True)

SUMMARY_OUT = DATA_DIR / "concentration_sweep_summary.csv"
BASKET_DIAG_OUT = DATA_DIR / "concentration_sweep_basket_diagnostics.csv"
PLOT_OUT = GRAPHS_DIR / "concentration_sweep.png"

# Sweep grid. 20 is the realistic deployment target. 50, 100, 200 buy
# back diversification at intermediate cost. 500 and 700 anchor against
# the prior research-stage runs so we can confirm reproduction.
TOP_N_VALUES = [20, 50, 100, 200, 500, 700]
SCORE_COL = "z_turnover_resid"

# Bootstrap parameters
DAILY_BLOCK_SIZE = 20
BOOT_N = 5000
SEED = 42


# ═══════════════════════════════════════════════════════════════════════
# Basket-level diagnostics
# ═══════════════════════════════════════════════════════════════════════

def compute_basket_diagnostics(
    panel: pd.DataFrame, baskets: dict,
) -> pd.DataFrame:
    """
    For each rebalance, compute sector concentration metrics of the
    top_n basket. Returns one row per rebalance_date.
    """
    panel_lookup = (
        panel[["rebalance_date", "ts_code", "sector_l1"]]
        .dropna(subset=["sector_l1"])
    )
    rows = []
    for date, basket_dict in baskets.items():
        members = basket_dict["top_n"]
        if not members:
            continue
        sub = panel_lookup[
            (panel_lookup["rebalance_date"] == date)
            & (panel_lookup["ts_code"].isin(members))
        ]
        if len(sub) == 0:
            continue
        sec_counts = sub["sector_l1"].value_counts()
        sec_shares = sec_counts / len(sub)
        rows.append({
            "rebalance_date": date,
            "n_held": len(sub),
            "n_unique_sectors": int(len(sec_counts)),
            "max_sector_pct": float(sec_shares.max()),
            "hhi": float((sec_shares ** 2).sum()),
            "top_sector": str(sec_counts.index[0]),
        })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════
# Per-regime summary with extra metrics for low-N regime
# ═══════════════════════════════════════════════════════════════════════

def summarise_regime_with_extras(
    daily: pd.DataFrame,
    label: str,
    regime_label: str,
    start: str,
    end: str,
    churn_in_regime_mean: float,
    basket_diag_in_regime: pd.DataFrame,
    n_top: int,
) -> pd.DataFrame:
    """
    Per-regime backtest summary with bootstrap IR CI, monthly hit rate,
    worst weekly active return, Sortino, and basket-level concentration
    metrics aggregated over the regime.
    """
    rows = []
    sub_daily = daily[
        (daily["trade_date"] >= start) & (daily["trade_date"] <= end)
    ]
    for conv in ("c2c", "open_t1"):
        g_conv = sub_daily[sub_daily["convention"] == conv]
        if len(g_conv) == 0:
            continue
        for ret_kind in ("gross", "net"):
            ret_col = f"daily_return_{ret_kind}"
            wide = g_conv.pivot_table(
                index="trade_date", columns="strategy", values=ret_col,
            )
            if "top_n" not in wide.columns or "universe" not in wide.columns:
                continue
            ts = wide[["top_n", "universe"]].dropna()
            if len(ts) < 20:
                continue
            tn = ts["top_n"]
            un = ts["universe"]
            active = tn - un

            n_days = len(ts)
            ann_ret_tn = (1 + tn).prod() ** (TRADING_DAYS_PER_YEAR / n_days) - 1
            ann_ret_un = (1 + un).prod() ** (TRADING_DAYS_PER_YEAR / n_days) - 1
            ann_active = active.mean() * TRADING_DAYS_PER_YEAR
            ann_te = active.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
            ir = (
                active.mean() / active.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
                if active.std() > 0 else np.nan
            )
            sharpe_tn = (
                tn.mean() / tn.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
                if tn.std() > 0 else np.nan
            )
            # Sortino (downside-std variant)
            tn_neg = tn[tn < 0]
            downside_std = tn_neg.std() if len(tn_neg) > 1 else np.nan
            sortino = (
                tn.mean() / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR)
                if downside_std and downside_std > 0 else np.nan
            )
            cum = (1 + tn).cumprod()
            max_dd = (cum / cum.cummax() - 1).min()

            # Bootstrap IR CI (the headline at low N)
            if n_days >= 2 * DAILY_BLOCK_SIZE:
                def _ir(a):
                    s = a.std()
                    return (
                        a.mean() / s * np.sqrt(TRADING_DAYS_PER_YEAR)
                        if s > 0 else np.nan
                    )
                ir_ci = block_bootstrap_ci(
                    active.values, _ir, block_size=DAILY_BLOCK_SIZE,
                    n_boot=BOOT_N, seed=SEED,
                )
                ir_ci_low = ir_ci["ci_low"]
                ir_ci_high = ir_ci["ci_high"]
            else:
                ir_ci_low = ir_ci_high = np.nan

            # Monthly hit rate
            month_active = active.copy()
            month_active.index = pd.to_datetime(month_active.index)
            monthly = month_active.resample("ME").sum()
            hit_rate = float((monthly > 0).mean()) if len(monthly) else np.nan

            # Worst weekly active
            week_active = active.copy()
            week_active.index = pd.to_datetime(week_active.index)
            weekly = week_active.resample("W").sum()
            worst_week = float(weekly.min()) if len(weekly) else np.nan

            rows.append({
                "regime": regime_label,
                "n_top": n_top,
                "label": label,
                "convention": conv,
                "ret_kind": ret_kind,
                "n_days": n_days,
                "ann_ret_top_n_pct": ann_ret_tn * 100,
                "ann_ret_universe_pct": ann_ret_un * 100,
                "active_ret_pct": ann_active * 100,
                "tracking_err_pct": ann_te * 100,
                "ir": ir,
                "ir_ci_low": ir_ci_low,
                "ir_ci_high": ir_ci_high,
                "sharpe_top_n": sharpe_tn,
                "sortino_top_n": sortino,
                "max_dd_pct": max_dd * 100,
                "monthly_hit_rate_pct": (
                    hit_rate * 100 if pd.notna(hit_rate) else np.nan
                ),
                "worst_week_active_pct": (
                    worst_week * 100 if pd.notna(worst_week) else np.nan
                ),
                "mean_churn_pct": (
                    churn_in_regime_mean * 100
                    if churn_in_regime_mean is not None else np.nan
                ),
                "mean_max_sector_pct": (
                    basket_diag_in_regime["max_sector_pct"].mean() * 100
                    if len(basket_diag_in_regime) > 0 else np.nan
                ),
                "mean_n_unique_sectors": (
                    basket_diag_in_regime["n_unique_sectors"].mean()
                    if len(basket_diag_in_regime) > 0 else np.nan
                ),
            })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════

def run_pipeline() -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = load_panel_with_sector()
    panel = add_z_turnover_resid(panel, with_beta=False)
    cal = pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()

    summary_rows = []
    diag_rows = []

    print("\n" + "=" * 76)
    print(f"CONCENTRATION SWEEP on {SCORE_COL}")
    print(f"  N values: {TOP_N_VALUES}")
    print("=" * 76)

    for n in TOP_N_VALUES:
        print(f"\n{'─' * 76}\n  TOP-{n}\n{'─' * 76}")
        baskets = build_top_n_baskets(panel, SCORE_COL, n=n)

        bd = compute_basket_diagnostics(panel, baskets)
        bd["n_top"] = n
        diag_rows.append(bd)

        # Median basket-level diagnostics across all dates (overall, then
        # per-regime stats come from summarise step).
        if len(bd) > 0:
            print(f"  basket diagnostics over all rebalances:")
            print(f"    median max_sector_pct: "
                  f"{bd['max_sector_pct'].median()*100:.1f}%")
            print(f"    median n_unique_sectors: "
                  f"{int(bd['n_unique_sectors'].median())}")
            print(f"    median HHI: {bd['hhi'].median():.3f}")

        label = f"top_{n}"
        # run_top_n_backtest writes to combination_phase2_daily_<label>.csv
        # by convention. We rename after to keep the concentration sweep
        # outputs in their own namespace.
        daily = run_top_n_backtest(baskets, label, cal)
        src = DATA_DIR / f"combination_phase2_daily_{label}.csv"
        dst = DATA_DIR / f"concentration_sweep_daily_top_{n}.csv"
        if src.exists():
            if dst.exists():
                dst.unlink()
            src.rename(dst)

        churn = compute_basket_churn(baskets)
        for regime_label, (start, end) in THREE_REGIME_WINDOWS.items():
            start_str = (
                start.strftime("%Y-%m-%d")
                if hasattr(start, "strftime") else str(start)
            )
            end_str = (
                end.strftime("%Y-%m-%d")
                if hasattr(end, "strftime") else str(end)
            )

            # Filter churn series to this regime
            churn_dates_ts = pd.to_datetime(churn.index)
            mask_churn = (
                (churn_dates_ts >= pd.to_datetime(start))
                & (churn_dates_ts <= pd.to_datetime(end))
            )
            churn_filtered = churn[mask_churn]
            churn_mean = (
                float(churn_filtered.iloc[1:].mean())
                if len(churn_filtered) > 1 else np.nan
            )

            # Filter basket diagnostics to this regime
            bd_dates_ts = pd.to_datetime(bd["rebalance_date"])
            mask_bd = (
                (bd_dates_ts >= pd.to_datetime(start))
                & (bd_dates_ts <= pd.to_datetime(end))
            )
            bd_filtered = bd[mask_bd]

            sub = summarise_regime_with_extras(
                daily, label, regime_label, start_str, end_str,
                churn_mean, bd_filtered, n,
            )
            summary_rows.append(sub)

    summary_df = pd.concat(summary_rows, ignore_index=True)
    summary_df.to_csv(SUMMARY_OUT, index=False)

    diag_df = pd.concat(diag_rows, ignore_index=True)
    diag_df.to_csv(BASKET_DIAG_OUT, index=False)

    # Headline
    print("\n" + "=" * 76)
    print("HEADLINE: NET OPEN_T1 IR BY REGIME × TOP_N (with bootstrap CI)")
    print("=" * 76)
    head = summary_df[
        (summary_df["convention"] == "open_t1")
        & (summary_df["ret_kind"] == "net")
    ].copy()
    cols = [
        "regime", "n_top", "ann_ret_top_n_pct", "active_ret_pct",
        "tracking_err_pct", "ir", "ir_ci_low", "ir_ci_high",
        "sharpe_top_n", "sortino_top_n", "max_dd_pct",
        "monthly_hit_rate_pct", "worst_week_active_pct",
        "mean_churn_pct", "mean_max_sector_pct", "mean_n_unique_sectors",
    ]
    print("\n" + head[cols].round(3).to_string(index=False))

    # Pivot views for human reading
    print("\n" + "=" * 76)
    print("PIVOT: NET OPEN_T1 IR")
    print("=" * 76)
    piv_ir = head.pivot(index="regime", columns="n_top", values="ir").round(3)
    piv_ir = piv_ir[TOP_N_VALUES]
    print(piv_ir.to_string())

    print("\n" + "=" * 76)
    print("PIVOT: IR 95% CI HALF-WIDTH (bootstrap, indicator of estimation noise)")
    print("=" * 76)
    head["ci_half_width"] = (head["ir_ci_high"] - head["ir_ci_low"]) / 2
    piv_ci = head.pivot(index="regime", columns="n_top", values="ci_half_width").round(3)
    piv_ci = piv_ci[TOP_N_VALUES]
    print(piv_ci.to_string())

    print("\n" + "=" * 76)
    print("PIVOT: MAX DD (%)")
    print("=" * 76)
    piv_dd = head.pivot(index="regime", columns="n_top", values="max_dd_pct").round(2)
    piv_dd = piv_dd[TOP_N_VALUES]
    print(piv_dd.to_string())

    print("\n" + "=" * 76)
    print("PIVOT: MEAN MAX SECTOR CONCENTRATION (%)")
    print("=" * 76)
    piv_sec = head.pivot(
        index="regime", columns="n_top", values="mean_max_sector_pct"
    ).round(1)
    piv_sec = piv_sec[TOP_N_VALUES]
    print(piv_sec.to_string())

    plot_sweep(summary_df)
    return summary_df, diag_df


# ═══════════════════════════════════════════════════════════════════════
# Plot
# ═══════════════════════════════════════════════════════════════════════

def plot_sweep(summary: pd.DataFrame) -> None:
    head = summary[
        (summary["convention"] == "open_t1")
        & (summary["ret_kind"] == "net")
    ].copy()
    regimes = list(THREE_REGIME_WINDOWS.keys())
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]

    fig, axes = plt.subplots(2, 2, figsize=(13, 10))

    # Top-left: IR with CI
    ax = axes[0, 0]
    for regime, color in zip(regimes, colors):
        sub = head[head["regime"] == regime].sort_values("n_top")
        if len(sub) == 0:
            continue
        ax.errorbar(
            sub["n_top"], sub["ir"],
            yerr=[
                sub["ir"] - sub["ir_ci_low"],
                sub["ir_ci_high"] - sub["ir"],
            ],
            fmt="o-", color=color, label=regime, capsize=4, linewidth=1.5,
        )
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xscale("log")
    ax.set_xticks(TOP_N_VALUES)
    ax.set_xticklabels(TOP_N_VALUES)
    ax.set_xlabel("Top N (log scale)")
    ax.set_ylabel("Net IR (open_t1, vs universe_ew)")
    ax.set_title("Net IR by basket size, with 95% bootstrap CI")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # Top-right: max drawdown
    ax = axes[0, 1]
    for regime, color in zip(regimes, colors):
        sub = head[head["regime"] == regime].sort_values("n_top")
        if len(sub) == 0:
            continue
        ax.plot(
            sub["n_top"], sub["max_dd_pct"], "o-",
            color=color, label=regime, linewidth=1.5,
        )
    ax.set_xscale("log")
    ax.set_xticks(TOP_N_VALUES)
    ax.set_xticklabels(TOP_N_VALUES)
    ax.set_xlabel("Top N")
    ax.set_ylabel("Max drawdown of top-N basket (%)")
    ax.set_title("Max drawdown by basket size")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # Bottom-left: max sector concentration
    ax = axes[1, 0]
    for regime, color in zip(regimes, colors):
        sub = head[head["regime"] == regime].sort_values("n_top")
        if len(sub) == 0:
            continue
        ax.plot(
            sub["n_top"], sub["mean_max_sector_pct"], "o-",
            color=color, label=regime, linewidth=1.5,
        )
    ax.set_xscale("log")
    ax.set_xticks(TOP_N_VALUES)
    ax.set_xticklabels(TOP_N_VALUES)
    ax.set_xlabel("Top N")
    ax.set_ylabel("Mean max sector concentration (%)")
    ax.set_title("Sector concentration risk")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # Bottom-right: tracking error
    ax = axes[1, 1]
    for regime, color in zip(regimes, colors):
        sub = head[head["regime"] == regime].sort_values("n_top")
        if len(sub) == 0:
            continue
        ax.plot(
            sub["n_top"], sub["tracking_err_pct"], "o-",
            color=color, label=regime, linewidth=1.5,
        )
    ax.set_xscale("log")
    ax.set_xticks(TOP_N_VALUES)
    ax.set_xticklabels(TOP_N_VALUES)
    ax.set_xlabel("Top N")
    ax.set_ylabel("Annualized tracking error (%)")
    ax.set_title("Tracking error by basket size")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    fig.suptitle(
        f"Concentration sweep: {SCORE_COL} (no filters, naive top-N)",
        y=1.00,
    )
    fig.tight_layout()
    fig.savefig(PLOT_OUT, dpi=120)
    plt.close(fig)
    print(f"\n  plot saved to {PLOT_OUT}")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Naive concentration sweep on z_turnover_resid."
    )
    ap.add_argument("mode", choices=["run", "status"])
    args = ap.parse_args()

    if args.mode == "status":
        for path in (SUMMARY_OUT, BASKET_DIAG_OUT, PLOT_OUT):
            print(f"  {path}: {'EXISTS' if path.exists() else 'missing'}")
        return

    run_pipeline()
    print("\nDone.")


if __name__ == "__main__":
    main()