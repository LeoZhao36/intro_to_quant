"""
run_full_sweep.py — Orchestrator for the volume-amplified reversal Phase 1.

Pipeline:
  1. Load universe, daily panel, factor_panel_a, sector
  2. Build factor panel (10 cells of z_volrev)
  3. Run 8 self-checks → CSV; abort on FAIL
  4. Phase 1: IC analysis → 4 CSVs
  5. Phase 2: backtest sweep (40 cells) → 3 CSVs
  6. Plots → 5 PNGs
  7. Print headline verdict

Run from this directory: `python run_full_sweep.py`
"""
from __future__ import annotations

import sys
import time
import warnings

import matplotlib
matplotlib.use("Agg")  # no display in script context
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import fr_config
from data_loaders import (
    load_universe_dict, load_daily_panel_long, attach_sector,
)
from factor_volume_reversal import build_factor_panel
import self_checks
import phase1_ic
import phase2_backtest
from plot_setup import setup_chinese_font


def make_plots(p1: dict, p2: dict) -> list:
    setup_chinese_font()
    fr_config.GRAPHS_OUT.mkdir(parents=True, exist_ok=True)
    out_paths = []

    # 1. Phase 1 IC heatmap (5 L × 2 rank_type)
    summary1 = p1["summary"]
    pivot_ic = summary1.pivot(index="L", columns="rank_type",
                                values="ic_mean")
    pivot_t = summary1.pivot(index="L", columns="rank_type",
                                values="ic_t")
    fig, ax = plt.subplots(figsize=(5, 5))
    im = ax.imshow(pivot_ic.values, cmap="RdBu_r",
                    vmin=-abs(pivot_ic.values).max(),
                    vmax=abs(pivot_ic.values).max(),
                    aspect="auto")
    ax.set_xticks(range(len(pivot_ic.columns)))
    ax.set_xticklabels(pivot_ic.columns)
    ax.set_yticks(range(len(pivot_ic.index)))
    ax.set_yticklabels([f"L={l}" for l in pivot_ic.index])
    for i in range(pivot_ic.shape[0]):
        for j in range(pivot_ic.shape[1]):
            ax.text(j, i,
                    f"IC={pivot_ic.values[i, j]:+.4f}\n"
                    f"t={pivot_t.values[i, j]:+.2f}",
                    ha="center", va="center", fontsize=9,
                    color="black" if abs(pivot_ic.values[i, j]) <
                    abs(pivot_ic.values).max()/2 else "white")
    ax.set_title("Phase 1 IC heatmap (γ regime)")
    plt.colorbar(im, ax=ax, label="IC mean")
    fig.tight_layout()
    p = fr_config.GRAPHS_OUT / "phase1_ic_heatmap.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    out_paths.append(p)

    # 2. Phase 1 IC quarterly (5 panels by L, 2 lines per panel)
    qdf = p1["quarterly"]
    fig, axes = plt.subplots(1, 5, figsize=(20, 4), sharey=True)
    for ax, L in zip(axes, fr_config.L_VALUES):
        for r in fr_config.RANK_TYPES:
            sub = qdf[(qdf["L"] == L) & (qdf["rank_type"] == r)]
            ax.plot(sub["quarter"].astype(str), sub["ic_mean"],
                    marker="o", label=r)
        ax.axhline(0, color="grey", lw=0.5)
        ax.set_title(f"L={L}")
        ax.tick_params(axis="x", rotation=45)
    axes[0].set_ylabel("IC mean")
    axes[-1].legend(title="rank_type")
    fig.suptitle("Phase 1 IC by quarter (γ regime)")
    fig.tight_layout()
    p = fr_config.GRAPHS_OUT / "phase1_ic_quarterly.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    out_paths.append(p)

    # 3. Phase 2 IR by N
    summary2 = p2["summary"]
    fig, ax = plt.subplots(figsize=(8, 5))
    for L in fr_config.L_VALUES:
        for r in fr_config.RANK_TYPES:
            sub = summary2[(summary2["L"] == L) & (summary2["rank_type"] == r)
                            ].sort_values("N")
            label = f"L={L} {r}"
            line, = ax.plot(sub["N"], sub["ir_net"], marker="o", label=label)
            ax.fill_between(sub["N"], sub["ir_ci_low"], sub["ir_ci_high"],
                             color=line.get_color(), alpha=0.10)
    ax.axhline(0, color="grey", lw=0.5)
    ax.axhline(fr_config.HEADLINE_IR_VALIDATE, color="green", lw=0.5,
               linestyle="--", label=f"validate ≥ {fr_config.HEADLINE_IR_VALIDATE}")
    ax.set_xscale("log")
    ax.set_xlabel("N (top-N basket)")
    ax.set_ylabel("Net IR vs universe-EW")
    ax.set_title("Phase 2 net IR by N (γ regime, 95% block-bootstrap CI)")
    ax.legend(loc="best", fontsize=8, ncol=2)
    fig.tight_layout()
    p = fr_config.GRAPHS_OUT / "phase2_ir_by_n.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    out_paths.append(p)

    # 4. Phase 2 headline cumulative
    pr = p2["period_returns"]
    head = pr[(pr["L"] == fr_config.HEADLINE_L) &
              (pr["N"] == fr_config.HEADLINE_N) &
              (pr["rank_type"] == fr_config.HEADLINE_RANK)
              ].sort_values("period_start")
    if len(head) > 0:
        cum_gross = (1 + head["basket_ret"]).cumprod()
        cum_net = (1 + head["basket_ret_net"]).cumprod()
        cum_bench = (1 + head["benchmark_ret"]).cumprod()
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(head["period_start"], cum_gross, label="basket gross")
        ax.plot(head["period_start"], cum_net, label="basket net")
        ax.plot(head["period_start"], cum_bench, label="universe-EW",
                 color="black", linewidth=1)
        ax.axhline(1, color="grey", lw=0.5)
        ax.set_title(f"Headline cumulative — L={fr_config.HEADLINE_L}, "
                      f"N={fr_config.HEADLINE_N}, "
                      f"rank={fr_config.HEADLINE_RANK} (γ regime)")
        ax.legend()
        fig.tight_layout()
        p = fr_config.GRAPHS_OUT / "phase2_headline_cumulative.png"
        fig.savefig(p, dpi=120)
        plt.close(fig)
        out_paths.append(p)

    # 5. ts vs cs ranking comparison
    cmp = p1["rank_cmp"]
    fig, ax = plt.subplots(figsize=(8, 5))
    for L in fr_config.L_VALUES:
        sub = cmp[cmp["L"] == L]
        ax.hist(sub["ts_cs_spearman_corr"], bins=20, alpha=0.4,
                 label=f"L={L}", density=True)
    ax.set_xlabel("per-date Spearman(z_ts, z_cs)")
    ax.set_ylabel("density")
    ax.set_title("ts vs cs ranking agreement (γ regime)")
    ax.legend()
    fig.tight_layout()
    p = fr_config.GRAPHS_OUT / "ranking_comparison_distribution.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    out_paths.append(p)

    return out_paths


def headline_verdict(p2_summary: pd.DataFrame) -> str:
    head = p2_summary[
        (p2_summary["L"] == fr_config.HEADLINE_L)
        & (p2_summary["N"] == fr_config.HEADLINE_N)
        & (p2_summary["rank_type"] == fr_config.HEADLINE_RANK)
    ]
    if len(head) == 0:
        return "NO_DATA"
    row = head.iloc[0]
    ir = row["ir_net"]
    lo = row["ir_ci_low"]
    hi = row["ir_ci_high"]
    contains_zero = lo <= 0 <= hi
    if ir < 0 or contains_zero:
        verdict = "FALSIFIED"
    elif ir >= fr_config.HEADLINE_IR_VALIDATE and not contains_zero:
        verdict = "VALIDATED"
    else:
        verdict = "AMBIGUOUS"
    print("\n" + "=" * 72)
    print("HEADLINE: L=%d, N=%d, rank_type=%s, γ regime" % (
        fr_config.HEADLINE_L, fr_config.HEADLINE_N, fr_config.HEADLINE_RANK,
    ))
    print(f"  net IR  = {ir:+.3f}     95% CI = [{lo:+.3f}, {hi:+.3f}]")
    print(f"  thresholds:  validate iff IR ≥ {fr_config.HEADLINE_IR_VALIDATE} "
          f"AND CI excludes 0")
    print(f"               falsify  if  IR < 0  OR  CI contains 0")
    print(f"               else AMBIGUOUS")
    print(f"  VERDICT: {verdict}")
    print("=" * 72)
    return verdict


def main():
    t0 = time.time()
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)

    print("[1/6] Loading universe + daily panel + factor_panel_a...")
    udict = load_universe_dict(gamma_only=True)
    g_dates = sorted(udict.keys())
    print(f"  γ rebalance dates: {len(g_dates)} "
          f"({g_dates[0].date()} .. {g_dates[-1].date()})")

    end = max(g_dates)
    start = min(g_dates) - pd.Timedelta(days=120)
    dp = load_daily_panel_long(start, end)
    print(f"  daily panel: {len(dp):,} rows over "
          f"{dp['trade_date'].nunique()} trading dates")

    fpa = pd.read_parquet(fr_config.FACTOR_PANEL_A)
    fpa["rebalance_date"] = pd.to_datetime(fpa["rebalance_date"])
    fpa = fpa[fpa["rebalance_date"].isin(g_dates)]
    fpa = attach_sector(fpa)
    print(f"  factor_panel_a (γ subset): {len(fpa):,} rows, "
          f"industry coverage {fpa['industry_name'].notna().mean()*100:.1f}%")

    print("\n[2/6] Building factor panel (10 z_volrev cells)...")
    panel = build_factor_panel(g_dates, udict, dp, fpa, verbose=False)
    print(f"  panel rows: {len(panel):,}")

    print("\n[3/6] Self-checks...")
    sc = self_checks.run_all(panel, udict, dp)
    if (sc["status"] == "FAIL").any():
        print("\nABORTING due to FAIL self-checks.")
        sys.exit(1)

    print("\n[4/6] Phase 1 IC analysis...")
    p1 = phase1_ic.run(panel)

    print("\n[5/6] Phase 2 backtest sweep...")
    sector_lookup = dict(zip(fpa["ts_code"], fpa["industry_name"]))
    p2 = phase2_backtest.run(panel, udict, dp, sector_lookup=sector_lookup)

    print("\n[6/6] Plots...")
    plot_paths = make_plots(p1, p2)
    for p in plot_paths:
        print(f"  → {p}")

    headline_verdict(p2["summary"])

    elapsed = time.time() - t0
    print(f"\nElapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
