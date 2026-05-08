"""
phase1_run.py — Main driver for universe_exploration/ Phase 1.

Pipeline:
  1. Load weekly rebalance dates and pre-compute BS rolling panels.
  2. Per rebalance, per variant (A=baseline, B=baseline-no-ChiNext):
       - apply baseline filter
       - build cap_rank, tradability, RDI components, BS components
       - run RHI with 4-component RDI (default)
       - run RHI with 3-component RDI (marginal-effect diagnostic, variant A)
  3. Aggregate diagnostics across panel and four sub-windows:
       full / pre_2024 / post_2024 / gamma
  4. Bandwidth sensitivity on sample dates per sub-window.
  5. Plots: heatmap (5 sample dates × 2 variants),
            universe size, centroid drift, RDI coverage.
  6. Console summary block.

Run from universe_exploration/:
    python phase1_run.py                # full panel
    python phase1_run.py --sample 5     # only 5 rebalance dates (smoke test)
    python phase1_run.py --skip-rhi     # only build panels, no RHI
"""

from __future__ import annotations

import argparse
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import config
from baseline_filter import (
    apply_baseline_filter,
    baseline_step_counts,
    load_daily_panel,
    load_trading_calendar,
)
from panel_builders import build_cap_rank, build_tradability
from rdi_compute import (
    compute_rdi_for_date,
    compute_rdi_with_smallorder,
)
from bs_compute import prepare_returns_panel, precompute_bs_panels, compute_bs_for_date
from rhi_algorithm import identify_hotspot_universe, HotspotResult


warnings.filterwarnings("ignore", category=RuntimeWarning)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def load_rebalance_dates() -> list[pd.Timestamp]:
    df = pd.read_csv(config.WEEKLY_REBALANCE_DATES_PATH)
    dates = pd.to_datetime(df["date"]).sort_values().tolist()
    return dates


def assign_subwindow(d: pd.Timestamp) -> list[str]:
    """Each rebalance date may belong to multiple sub-windows (full +
    one of pre_2024/post_2024 + maybe gamma)."""
    keys = []
    for k, (a, b) in config.SUBWINDOWS.items():
        if (a is None or d >= a) and (b is None or d <= b):
            keys.append(k)
    return keys


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


# ═══════════════════════════════════════════════════════════════════════
# Step 1: build per-rebalance panels
# ═══════════════════════════════════════════════════════════════════════

def build_panels(rebal_dates: list[pd.Timestamp],
                 verbose: bool = True) -> dict:
    """
    Per rebalance, build (variant-A) baseline + cap_rank + tradability +
    RDI + BS, accumulate to long-format parquets. Variant-B baseline is
    built on the fly during RHI step (same daily panel) — see step 2.

    Returns dict of long-format DataFrames.
    """
    rdi_rows: list[pd.DataFrame] = []
    bs_rows: list[pd.DataFrame] = []
    cap_rows: list[pd.DataFrame] = []
    trade_rows: list[pd.DataFrame] = []
    coverage_rows: list[dict] = []

    t0 = time.time()
    for i, r in enumerate(rebal_dates, 1):
        daily = load_daily_panel(r)
        if daily is None or daily.empty:
            continue

        baseline_a = apply_baseline_filter(r, daily=daily, variant="A")
        if baseline_a.empty:
            continue

        cap_a = build_cap_rank(r, baseline_a)
        trade_a = build_tradability(r, baseline_a)
        rdi_a = compute_rdi_for_date(r, baseline_a)
        bs_a = compute_bs_for_date(r, baseline_a)

        cap_rows.append(cap_a)
        trade_rows.append(trade_a)
        rdi_rows.append(rdi_a)
        bs_rows.append(bs_a)

        # Coverage diagnostic
        if not rdi_a.empty:
            n_baseline = len(baseline_a)
            n_with_rdi = int(rdi_a["rdi_rank"].notna().sum())
            n_3plus = int((rdi_a["n_components_total_used"] >= 3).sum())
            n_4 = int((rdi_a["n_components_total_used"] == 4).sum())
            coverage_rows.append({
                "trade_date": r,
                "n_baseline": n_baseline,
                "n_with_rdi": n_with_rdi,
                "pct_with_rdi": n_with_rdi / n_baseline * 100 if n_baseline else 0,
                "pct_with_3plus_components": n_3plus / n_baseline * 100 if n_baseline else 0,
                "pct_with_4_components": n_4 / n_baseline * 100 if n_baseline else 0,
            })

        if verbose and (i % 50 == 0 or i == len(rebal_dates)):
            print(f"  [{i:>4}/{len(rebal_dates)}] {r.date()}  "
                  f"baseline={len(baseline_a)}  rdi={len(rdi_a)}  "
                  f"bs={len(bs_a)}  elapsed={time.time()-t0:.1f}s")

    out = {
        "rdi": pd.concat(rdi_rows, ignore_index=True) if rdi_rows else pd.DataFrame(),
        "bs": pd.concat(bs_rows, ignore_index=True) if bs_rows else pd.DataFrame(),
        "cap": pd.concat(cap_rows, ignore_index=True) if cap_rows else pd.DataFrame(),
        "tradability": pd.concat(trade_rows, ignore_index=True) if trade_rows else pd.DataFrame(),
        "coverage": pd.DataFrame(coverage_rows),
    }

    # Persist
    if not out["rdi"].empty:
        out["rdi"].to_parquet(config.RDI_COMPONENTS_PATH, compression="zstd")
        print(f"  wrote {config.RDI_COMPONENTS_PATH}")
    if not out["bs"].empty:
        out["bs"].to_parquet(config.BS_COMPONENTS_PATH, compression="zstd")
        print(f"  wrote {config.BS_COMPONENTS_PATH}")
    if not out["cap"].empty:
        out["cap"].to_parquet(config.CAP_RANK_PANEL_PATH, compression="zstd")
        print(f"  wrote {config.CAP_RANK_PANEL_PATH}")
    if not out["tradability"].empty:
        out["tradability"].to_parquet(config.TRADABILITY_PANEL_PATH, compression="zstd")
        print(f"  wrote {config.TRADABILITY_PANEL_PATH}")
    if not out["coverage"].empty:
        out["coverage"].to_csv(config.DATA_DIR / "rdi_coverage.csv", index=False)
        print(f"  wrote rdi_coverage.csv")

    return out


# ═══════════════════════════════════════════════════════════════════════
# Step 2: per-rebalance RHI
# ═══════════════════════════════════════════════════════════════════════

def assemble_rhi_input(
    rebalance_date: pd.Timestamp,
    variant: str,
    daily: pd.DataFrame,
    rdi_panel: pd.DataFrame,
    bs_panel: pd.DataFrame,
    cap_panel: pd.DataFrame,
    trade_panel: pd.DataFrame,
    use_smallorder: bool = False,
) -> pd.DataFrame:
    """
    Build the per-rebalance RHI input frame for given variant.

    Default `rdi_rank` (use_smallorder=False): 3-component institutional
    composite (holders + funds + north). This is the production default
    as of 2026-05-08 — small-order-flow was demoted from the composite
    after the marginal-effect diagnostic showed it caused excess universe
    turnover (Jaccard 0.42 in γ regime) without independent justification.

    `use_smallorder=True` swaps in the 4-component composite for the
    marginal-effect diagnostic only.
    """
    baseline = apply_baseline_filter(rebalance_date, daily=daily, variant=variant)
    if baseline.empty:
        return pd.DataFrame()

    if variant == "B":
        # Re-derive cap_rank/tradability/RDI/BS within Variant-B baseline
        # because cap_rank is rank within the cohort.
        cap = build_cap_rank(rebalance_date, baseline)
        trade = build_tradability(rebalance_date, baseline)
        rdi_full = compute_rdi_for_date(rebalance_date, baseline)
        bs_full = compute_bs_for_date(rebalance_date, baseline)
    else:
        # Variant A — reuse pre-computed long panels.
        mask = (cap_panel["trade_date"] == rebalance_date)
        cap = cap_panel.loc[mask, ["ts_code", "cap_rank"]]
        mask = (trade_panel["trade_date"] == rebalance_date)
        trade = trade_panel.loc[mask, ["ts_code", "tradable"]]
        mask = (rdi_panel["trade_date"] == rebalance_date)
        rdi_full = rdi_panel.loc[mask].copy()
        mask = (bs_panel["trade_date"] == rebalance_date)
        bs_full = bs_panel.loc[mask, ["ts_code", "bs_score"]]

    # Pick RDI version
    if use_smallorder:
        rdi_col = "rdi_rank_with_smallorder"
    else:
        rdi_col = "rdi_rank"

    df = baseline[["ts_code", "board"]].copy()
    df = df.merge(cap[["ts_code", "cap_rank"]], on="ts_code", how="left")
    df = df.merge(trade[["ts_code", "tradable"]], on="ts_code", how="left")
    df = df.merge(rdi_full[["ts_code", rdi_col]].rename(columns={rdi_col: "rdi_rank"}),
                   on="ts_code", how="left")
    df = df.merge(bs_full[["ts_code", "bs_score"]], on="ts_code", how="left")
    df["tradable"] = df["tradable"].fillna(False).astype(bool)
    return df


def run_rhi_per_rebalance(
    rebal_dates: list[pd.Timestamp],
    panels: dict,
    target_size: int = config.RHI_TARGET_SIZE,
    bandwidth: float = config.RHI_DEFAULT_BANDWIDTH,
    verbose: bool = True,
) -> dict:
    """
    Per rebalance, run RHI for variants A/B and (variant A) the 3-component
    RDI version for the marginal-effect diagnostic.
    """
    rdi_panel = panels["rdi"]
    bs_panel = panels["bs"]
    cap_panel = panels["cap"]
    trade_panel = panels["tradability"]

    a_membership: list[pd.DataFrame] = []
    b_membership: list[pd.DataFrame] = []
    summary_rows: list[dict] = []
    marginal_rows: list[dict] = []

    t0 = time.time()
    for i, r in enumerate(rebal_dates, 1):
        daily = load_daily_panel(r)
        if daily is None or daily.empty:
            continue

        # Variant A — default 3-component RDI
        res_a = None
        try:
            df_a = assemble_rhi_input(r, "A", daily, rdi_panel, bs_panel,
                                        cap_panel, trade_panel, use_smallorder=False)
            if df_a.empty:
                continue
            res_a = identify_hotspot_universe(
                df_a, bandwidth=bandwidth, target_size=target_size,
            )
            mem_a = res_a.df_with_hotspot[
                ["ts_code", "rho_at_stock", "in_hotspot", "board",
                 "cap_rank", "rdi_rank", "bs_score"]
            ].copy()
            mem_a["trade_date"] = r
            a_membership.append(mem_a)
            uni_a = mem_a[mem_a["in_hotspot"]]
            summary_rows.append({
                "variant": "A", "trade_date": r, "bandwidth": bandwidth,
                "centroid_cap": res_a.centroid[0],
                "centroid_rdi": res_a.centroid[1],
                "n_components": res_a.n_components,
                "n_in_universe": res_a.n_in_hotspot,
                "tau": res_a.tau,
                "mean_bs": float(uni_a["bs_score"].mean()) if len(uni_a) else float("nan"),
                "mean_rdi": float(uni_a["rdi_rank"].mean()) if len(uni_a) else float("nan"),
                "mean_cap": float(uni_a["cap_rank"].mean()) if len(uni_a) else float("nan"),
            })
        except Exception as exc:
            print(f"  [variant A] {r.date()} FAIL: {exc!r}")
            res_a = None

        # Variant A with 4-component RDI (smallorder added). Marginal-effect
        # diagnostic: how much does adding RDI_smallorder to the default
        # 3-component composite move the recovered hotspot? Sign convention:
        # delta = (with smallorder) - (default 3-comp).
        if res_a is not None:
            try:
                df_a_so = assemble_rhi_input(
                    r, "A", daily, rdi_panel, bs_panel,
                    cap_panel, trade_panel, use_smallorder=True,
                )
                res_a_so = identify_hotspot_universe(
                    df_a_so, bandwidth=bandwidth, target_size=target_size,
                )
                uni_default = set(res_a.df_with_hotspot.loc[
                    res_a.df_with_hotspot["in_hotspot"], "ts_code"])
                uni_with_so = set(res_a_so.df_with_hotspot.loc[
                    res_a_so.df_with_hotspot["in_hotspot"], "ts_code"])
                uni_so_df = res_a_so.df_with_hotspot.loc[
                    res_a_so.df_with_hotspot["in_hotspot"]]
                mean_bs_default = summary_rows[-1]["mean_bs"]
                marginal_rows.append({
                    "trade_date": r,
                    "centroid_cap_default": res_a.centroid[0],
                    "centroid_rdi_default": res_a.centroid[1],
                    "centroid_cap_with_so": res_a_so.centroid[0],
                    "centroid_rdi_with_so": res_a_so.centroid[1],
                    "delta_centroid_cap": res_a_so.centroid[0] - res_a.centroid[0],
                    "delta_centroid_rdi": res_a_so.centroid[1] - res_a.centroid[1],
                    "delta_size": res_a_so.n_in_hotspot - res_a.n_in_hotspot,
                    "jaccard_default_vs_with_so": jaccard(uni_default, uni_with_so),
                    "mean_bs_default": mean_bs_default,
                    "mean_bs_with_so": (
                        float(uni_so_df["bs_score"].mean()) if len(uni_so_df) else float("nan")
                    ),
                })
            except Exception as exc:
                print(f"  [variant A with-smallorder] {r.date()} FAIL: {exc!r}")

        # Variant B (default 3-component RDI)
        try:
            df_b = assemble_rhi_input(r, "B", daily, rdi_panel, bs_panel,
                                        cap_panel, trade_panel, use_smallorder=False)
            if df_b.empty:
                continue
            res_b = identify_hotspot_universe(
                df_b, bandwidth=bandwidth, target_size=target_size,
            )
            mem_b = res_b.df_with_hotspot[
                ["ts_code", "rho_at_stock", "in_hotspot", "board",
                 "cap_rank", "rdi_rank", "bs_score"]
            ].copy()
            mem_b["trade_date"] = r
            b_membership.append(mem_b)
            uni_b = mem_b[mem_b["in_hotspot"]]
            summary_rows.append({
                "variant": "B", "trade_date": r, "bandwidth": bandwidth,
                "centroid_cap": res_b.centroid[0],
                "centroid_rdi": res_b.centroid[1],
                "n_components": res_b.n_components,
                "n_in_universe": res_b.n_in_hotspot,
                "tau": res_b.tau,
                "mean_bs": float(uni_b["bs_score"].mean()) if len(uni_b) else float("nan"),
                "mean_rdi": float(uni_b["rdi_rank"].mean()) if len(uni_b) else float("nan"),
                "mean_cap": float(uni_b["cap_rank"].mean()) if len(uni_b) else float("nan"),
            })
        except Exception as exc:
            print(f"  [variant B] {r.date()} FAIL: {exc!r}")

        if verbose and (i % 25 == 0 or i == len(rebal_dates)):
            print(f"  [{i:>4}/{len(rebal_dates)}] {r.date()}  "
                  f"elapsed={time.time()-t0:.1f}s")

    # Persist
    if a_membership:
        a_df = pd.concat(a_membership, ignore_index=True)
        a_df.to_parquet(config.UNIVERSE_VARIANT_A_PATH, compression="zstd")
        print(f"  wrote {config.UNIVERSE_VARIANT_A_PATH}")
    if b_membership:
        b_df = pd.concat(b_membership, ignore_index=True)
        b_df.to_parquet(config.UNIVERSE_VARIANT_B_PATH, compression="zstd")
        print(f"  wrote {config.UNIVERSE_VARIANT_B_PATH}")

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(config.DATA_DIR / "hotspot_summary.csv", index=False)
    print(f"  wrote hotspot_summary.csv ({len(summary)} rows)")

    marginal = pd.DataFrame(marginal_rows)
    marginal.to_csv(config.DATA_DIR / "smallorder_marginal_effect.csv", index=False)
    print(f"  wrote smallorder_marginal_effect.csv ({len(marginal)} rows)")

    return {
        "a_membership": pd.concat(a_membership, ignore_index=True) if a_membership else pd.DataFrame(),
        "b_membership": pd.concat(b_membership, ignore_index=True) if b_membership else pd.DataFrame(),
        "summary": summary,
        "marginal": marginal,
    }


# ═══════════════════════════════════════════════════════════════════════
# Step 3: bandwidth sensitivity
# ═══════════════════════════════════════════════════════════════════════

def bandwidth_sensitivity(
    rebal_dates: list[pd.Timestamp],
    panels: dict,
    n_per_window: int = 3,
) -> pd.DataFrame:
    """
    Pick `n_per_window` evenly-spaced sample dates per sub-window, run RHI
    at h ∈ {0.10, 0.15, 0.25} on variant A, report centroid, n_in,
    and Jaccard against the h=0.15 reference.
    """
    rdi_panel = panels["rdi"]
    bs_panel = panels["bs"]
    cap_panel = panels["cap"]
    trade_panel = panels["tradability"]

    sample_dates: list[tuple[str, pd.Timestamp]] = []
    for k, (a, b) in config.SUBWINDOWS.items():
        if k == "full":
            continue  # avoid duplication; full is union of others
        in_window = [
            d for d in rebal_dates
            if (a is None or d >= a) and (b is None or d <= b)
        ]
        if len(in_window) < n_per_window:
            picks = in_window
        else:
            idxs = np.linspace(0, len(in_window) - 1, n_per_window).astype(int)
            picks = [in_window[i] for i in idxs]
        for d in picks:
            sample_dates.append((k, d))

    rows: list[dict] = []
    for k, r in sample_dates:
        daily = load_daily_panel(r)
        if daily is None or daily.empty:
            continue
        df_in = assemble_rhi_input(r, "A", daily, rdi_panel, bs_panel,
                                     cap_panel, trade_panel, use_smallorder=False)
        if df_in.empty:
            continue
        ref = identify_hotspot_universe(df_in, bandwidth=0.15)
        ref_set = set(ref.df_with_hotspot.loc[ref.df_with_hotspot["in_hotspot"], "ts_code"])
        for h in config.RHI_BANDWIDTHS:
            try:
                res = identify_hotspot_universe(df_in, bandwidth=h)
            except Exception as exc:
                print(f"  [bandwidth {h} on {r.date()}] FAIL: {exc!r}")
                continue
            this_set = set(res.df_with_hotspot.loc[res.df_with_hotspot["in_hotspot"], "ts_code"])
            rows.append({
                "subwindow": k, "trade_date": r, "bandwidth": h,
                "centroid_cap": res.centroid[0],
                "centroid_rdi": res.centroid[1],
                "n_in_universe": res.n_in_hotspot,
                "jaccard_vs_h015": jaccard(this_set, ref_set),
            })

    out = pd.DataFrame(rows)
    out.to_csv(config.DATA_DIR / "bandwidth_sensitivity.csv", index=False)
    print(f"  wrote bandwidth_sensitivity.csv ({len(out)} rows)")
    return out


# ═══════════════════════════════════════════════════════════════════════
# Step 4: diagnostic aggregates
# ═══════════════════════════════════════════════════════════════════════

def diagnostics(panels: dict, rhi_results: dict) -> dict:
    out: dict = {}

    # RDI / BS correlations (Pearson and Spearman)
    rdi = panels["rdi"]
    if not rdi.empty:
        comps = ["rdi_holders", "rdi_funds", "rdi_north", "rdi_smallorder"]
        comp = rdi[comps]
        pearson = comp.corr(method="pearson")
        spearman = comp.corr(method="spearman")
        pearson.to_csv(config.DATA_DIR / "rdi_correlation_pearson.csv")
        spearman.to_csv(config.DATA_DIR / "rdi_correlation_spearman.csv")
        # Combined wide format
        combined = pd.concat({"pearson": pearson, "spearman": spearman})
        combined.to_csv(config.DATA_DIR / "rdi_correlation.csv")
        print(f"  wrote rdi_correlation.csv (pearson + spearman)")
        out["rdi_corr_pearson"] = pearson
        out["rdi_corr_spearman"] = spearman

    bs = panels["bs"]
    if not bs.empty:
        comps = ["bs_idiovol", "bs_max", "bs_skew", "bs_lowprice"]
        comp = bs[comps]
        pearson = comp.corr(method="pearson")
        spearman = comp.corr(method="spearman")
        pearson.to_csv(config.DATA_DIR / "bs_correlation_pearson.csv")
        spearman.to_csv(config.DATA_DIR / "bs_correlation_spearman.csv")
        combined = pd.concat({"pearson": pearson, "spearman": spearman})
        combined.to_csv(config.DATA_DIR / "bs_correlation.csv")
        print(f"  wrote bs_correlation.csv (pearson + spearman)")
        out["bs_corr_pearson"] = pearson
        out["bs_corr_spearman"] = spearman

    # Variant A vs B comparison per rebalance
    summary = rhi_results.get("summary", pd.DataFrame())
    if not summary.empty:
        a = summary[summary["variant"] == "A"].set_index("trade_date")
        b = summary[summary["variant"] == "B"].set_index("trade_date")
        common = a.index.intersection(b.index)
        rows: list[dict] = []
        a_mem = rhi_results["a_membership"]
        b_mem = rhi_results["b_membership"]
        for d in common:
            uni_a = set(
                a_mem.loc[(a_mem["trade_date"] == d) & a_mem["in_hotspot"], "ts_code"]
            )
            uni_b = set(
                b_mem.loc[(b_mem["trade_date"] == d) & b_mem["in_hotspot"], "ts_code"]
            )
            uni_a_no_chinext = {
                c for c in uni_a if not c.startswith("30") or not c.endswith(".SZ")
            }
            rows.append({
                "trade_date": d,
                "n_a": len(uni_a), "n_b": len(uni_b),
                "jaccard_A_no_chinext_vs_B": jaccard(uni_a_no_chinext, uni_b),
                "mean_bs_diff": a.loc[d, "mean_bs"] - b.loc[d, "mean_bs"],
                "mean_rdi_diff": a.loc[d, "mean_rdi"] - b.loc[d, "mean_rdi"],
                "mean_cap_diff": a.loc[d, "mean_cap"] - b.loc[d, "mean_cap"],
            })
        var_cmp = pd.DataFrame(rows)
        var_cmp.to_csv(config.DATA_DIR / "variant_comparison.csv", index=False)
        print(f"  wrote variant_comparison.csv ({len(var_cmp)} rows)")
        out["variant_comparison"] = var_cmp

    # Regime comparison
    coverage = panels.get("coverage", pd.DataFrame())
    if not summary.empty:
        regime_rows: list[dict] = []
        for k, (a, b) in config.SUBWINDOWS.items():
            sub = summary[
                ((a is None) | (summary["trade_date"] >= a))
                & ((b is None) | (summary["trade_date"] <= b))
            ]
            for v in ["A", "B"]:
                s = sub[sub["variant"] == v]
                if len(s) == 0:
                    continue
                cov = pd.DataFrame()
                if not coverage.empty:
                    cov = coverage[
                        ((a is None) | (coverage["trade_date"] >= a))
                        & ((b is None) | (coverage["trade_date"] <= b))
                    ]
                regime_rows.append({
                    "subwindow": k, "variant": v,
                    "n_rebalances": len(s),
                    "mean_universe_size": s["n_in_universe"].mean(),
                    "std_universe_size": s["n_in_universe"].std(),
                    "mean_centroid_cap": s["centroid_cap"].mean(),
                    "mean_centroid_rdi": s["centroid_rdi"].mean(),
                    "mean_bs": s["mean_bs"].mean(),
                    "mean_rdi": s["mean_rdi"].mean(),
                    "mean_cap": s["mean_cap"].mean(),
                    "rdi_coverage_pct_3plus": cov["pct_with_3plus_components"].mean()
                        if not cov.empty else float("nan"),
                    "rdi_coverage_pct_4": cov["pct_with_4_components"].mean()
                        if not cov.empty else float("nan"),
                })
        regime_df = pd.DataFrame(regime_rows)
        regime_df.to_csv(config.DATA_DIR / "regime_comparison.csv", index=False)
        print(f"  wrote regime_comparison.csv ({len(regime_df)} rows)")
        out["regime_comparison"] = regime_df

    return out


# ═══════════════════════════════════════════════════════════════════════
# Step 5: plots
# ═══════════════════════════════════════════════════════════════════════

def make_plots(panels: dict, rhi_results: dict) -> None:
    import matplotlib.pyplot as plt
    try:
        from plot_setup import setup_chinese_font
        setup_chinese_font()
    except Exception:
        pass

    summary = rhi_results.get("summary", pd.DataFrame())
    coverage = panels.get("coverage", pd.DataFrame())
    a_mem = rhi_results.get("a_membership", pd.DataFrame())
    b_mem = rhi_results.get("b_membership", pd.DataFrame())

    # Plot 1: universe size over time
    if not summary.empty:
        fig, ax = plt.subplots(figsize=(11, 4.5))
        for v, color in [("A", "tab:blue"), ("B", "tab:orange")]:
            s = summary[summary["variant"] == v].sort_values("trade_date")
            ax.plot(s["trade_date"], s["n_in_universe"],
                     label=f"Variant {v}", color=color, lw=1.0, alpha=0.85)
        ax.axhline(config.RHI_TARGET_SIZE, ls="--", color="grey", lw=0.8, label="Target")
        ax.set_ylabel("Universe size (n stocks)")
        ax.set_title("RHI universe size over time")
        ax.legend()
        fig.tight_layout()
        fig.savefig(config.GRAPHS_DIR / "universe_size_over_time.png", dpi=130)
        plt.close(fig)
        print(f"  wrote graphs/universe_size_over_time.png")

    # Plot 2: centroid drift
    if not summary.empty:
        fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
        for v, color in [("A", "tab:blue"), ("B", "tab:orange")]:
            s = summary[summary["variant"] == v].sort_values("trade_date")
            axes[0].plot(s["trade_date"], s["centroid_cap"],
                          label=f"Variant {v}", color=color, lw=1.0)
            axes[1].plot(s["trade_date"], s["centroid_rdi"],
                          label=f"Variant {v}", color=color, lw=1.0)
        axes[0].set_ylabel("Centroid cap_rank")
        axes[0].axhline(0.5, ls=":", color="grey", lw=0.6)
        axes[1].set_ylabel("Centroid rdi_rank")
        axes[1].axhline(0.5, ls=":", color="grey", lw=0.6)
        axes[1].set_xlabel("Rebalance date")
        axes[0].legend()
        axes[0].set_title("Hotspot centroid drift")
        fig.tight_layout()
        fig.savefig(config.GRAPHS_DIR / "centroid_drift.png", dpi=130)
        plt.close(fig)
        print(f"  wrote graphs/centroid_drift.png")

    # Plot 3: RDI coverage over time
    if not coverage.empty:
        fig, ax = plt.subplots(figsize=(11, 4.5))
        ax.plot(coverage["trade_date"], coverage["pct_with_3plus_components"],
                 label="≥3 components", color="tab:green", lw=1.0)
        ax.plot(coverage["trade_date"], coverage["pct_with_4_components"],
                 label="4 components (incl. moneyflow)", color="tab:purple", lw=1.0)
        ax.set_ylabel("% of baseline stocks")
        ax.set_title("RDI component coverage")
        ax.legend()
        fig.tight_layout()
        fig.savefig(config.GRAPHS_DIR / "rdi_coverage_over_time.png", dpi=130)
        plt.close(fig)
        print(f"  wrote graphs/rdi_coverage_over_time.png")

    # Plot 4: heatmap on 5 sample dates × variant A
    if not a_mem.empty:
        sample_dates = sorted(a_mem["trade_date"].unique())
        if len(sample_dates) >= 5:
            picks = [sample_dates[i] for i in
                      np.linspace(0, len(sample_dates) - 1, 5).astype(int)]
            for d in picks:
                df_d = a_mem[a_mem["trade_date"] == d]
                fig, ax = plt.subplots(figsize=(7, 6))
                sc = ax.scatter(
                    df_d["cap_rank"], df_d["rdi_rank"],
                    c=df_d["bs_score"], cmap="viridis",
                    s=8, alpha=0.6,
                )
                in_uni = df_d[df_d["in_hotspot"]]
                ax.scatter(in_uni["cap_rank"], in_uni["rdi_rank"],
                            edgecolor="red", facecolor="none", s=18, lw=0.5,
                            label=f"in universe (n={len(in_uni)})")
                ax.set_xlabel("cap_rank")
                ax.set_ylabel("rdi_rank")
                ax.set_title(f"{d.date()} — Variant A — BS heatmap")
                ax.set_xlim(-0.02, 1.02)
                ax.set_ylim(-0.02, 1.02)
                ax.legend(loc="lower right")
                fig.colorbar(sc, ax=ax, label="bs_score")
                fig.tight_layout()
                fig.savefig(
                    config.GRAPHS_DIR / f"heatmap_{d.date()}_variantA.png",
                    dpi=120,
                )
                plt.close(fig)
            print(f"  wrote 5 heatmap plots for variant A")


# ═══════════════════════════════════════════════════════════════════════
# Step 6: console summary
# ═══════════════════════════════════════════════════════════════════════

def print_summary(panels: dict, rhi_results: dict, diag: dict,
                  bw_sens: pd.DataFrame, sample_baseline_date: pd.Timestamp) -> None:
    print("\n" + "=" * 70)
    print("=== UNIVERSE EXPLORATION PHASE 1 SUMMARY ===")
    print("=" * 70)

    summary = rhi_results.get("summary", pd.DataFrame())

    # Self-checks
    print("\nSelf-checks:")
    counts_a = baseline_step_counts(sample_baseline_date, "A")
    print(f"  [INFO] baseline_filter ({sample_baseline_date.date()} variant A):")
    for k, v in counts_a.items():
        print(f"     {k:>20}: {v:>5}")

    if "rdi_corr_pearson" in diag:
        rc = diag["rdi_corr_pearson"]
        pairs = [("rdi_holders", "rdi_funds"),
                  ("rdi_holders", "rdi_north"),
                  ("rdi_funds", "rdi_north"),
                  ("rdi_holders", "rdi_smallorder"),
                  ("rdi_funds", "rdi_smallorder"),
                  ("rdi_north", "rdi_smallorder")]
        print(f"\n  [INFO] RDI component pairwise correlations (Pearson):")
        for a, b in pairs:
            if a in rc.index and b in rc.columns:
                v = rc.loc[a, b]
                flag = "FAIL" if abs(v) > 0.95 else ("WARN" if abs(v) < 0.10 else "PASS")
                print(f"     [{flag}] {a:>17} × {b:<17}: {v:+.3f}")

    if "bs_corr_pearson" in diag:
        bc = diag["bs_corr_pearson"]
        bspairs = [("bs_idiovol", "bs_max"),
                    ("bs_idiovol", "bs_skew"),
                    ("bs_idiovol", "bs_lowprice"),
                    ("bs_max", "bs_skew"),
                    ("bs_max", "bs_lowprice"),
                    ("bs_skew", "bs_lowprice")]
        print(f"\n  [INFO] BS component pairwise correlations (Pearson):")
        for a, b in bspairs:
            if a in bc.index and b in bc.columns:
                v = bc.loc[a, b]
                print(f"     {a:>14} × {b:<14}: {v:+.3f}")

    if not summary.empty:
        size_in_range_a = (
            (summary["variant"] == "A")
            & (summary["n_in_universe"] >= config.RHI_TARGET_SIZE * 0.6)
            & (summary["n_in_universe"] <= config.RHI_TARGET_SIZE * 1.4)
        ).sum()
        n_a = (summary["variant"] == "A").sum()
        print(f"\n  [INFO] universe_size_in_range (A): "
              f"{size_in_range_a}/{n_a} dates")

    if not bw_sens.empty:
        print(f"\n  [INFO] bandwidth_sensitivity (variant A):")
        for h in config.RHI_BANDWIDTHS:
            sub = bw_sens[bw_sens["bandwidth"] == h]
            if h == 0.15:
                continue
            j = sub["jaccard_vs_h015"].mean()
            flag = "PASS" if j >= 0.7 else "WARN"
            print(f"     [{flag}] mean Jaccard(h={h} vs h=0.15) = {j:.3f}")

    # Regime comparison
    if "regime_comparison" in diag:
        rc = diag["regime_comparison"]
        for v in ("A", "B"):
            print(f"\nVariant {v}:")
            sub = rc[rc["variant"] == v].set_index("subwindow")
            for k in ["full", "pre_2024", "post_2024", "gamma"]:
                if k not in sub.index:
                    continue
                row = sub.loc[k]
                print(f"  {config.SUBWINDOW_LABELS[k]}")
                print(f"    n_rebal={int(row['n_rebalances'])}  "
                      f"size={row['mean_universe_size']:.0f}±{row['std_universe_size']:.0f}  "
                      f"centroid=({row['mean_centroid_cap']:.2f}, "
                      f"{row['mean_centroid_rdi']:.2f})")
                print(f"    mean_bs={row['mean_bs']:.3f}  "
                      f"mean_rdi={row['mean_rdi']:.3f}  "
                      f"mean_cap={row['mean_cap']:.3f}")
                print(f"    rdi_coverage_3+={row['rdi_coverage_pct_3plus']:.1f}%  "
                      f"4comp={row['rdi_coverage_pct_4']:.1f}%")

    # Variant comparison
    if "variant_comparison" in diag and not diag["variant_comparison"].empty:
        vc = diag["variant_comparison"]
        print(f"\nVariant A vs B (mean across all dates):")
        print(f"  Jaccard(A non-ChiNext, B): {vc['jaccard_A_no_chinext_vs_B'].mean():.3f}")
        print(f"  Mean BS diff (A - B):       {vc['mean_bs_diff'].mean():+.3f}")
        print(f"  Mean RDI diff (A - B):      {vc['mean_rdi_diff'].mean():+.3f}")
        print(f"  Mean cap diff (A - B):      {vc['mean_cap_diff'].mean():+.3f}")

    # Marginal effect of RDI_smallorder. Default is 3-component (institutional);
    # delta = (with smallorder) - (default 3-comp).
    marg = rhi_results.get("marginal", pd.DataFrame())
    if not marg.empty:
        print(f"\nRDI_smallorder marginal effect (Variant A: adding smallorder "
              f"to default 3-comp RDI):")
        print(f"  Mean dCentroid_cap: {marg['delta_centroid_cap'].mean():+.4f}  "
              f"(stdev {marg['delta_centroid_cap'].std():.4f})")
        print(f"  Mean dCentroid_rdi: {marg['delta_centroid_rdi'].mean():+.4f}  "
              f"(stdev {marg['delta_centroid_rdi'].std():.4f})")
        print(f"  Mean dUniverse_size: {marg['delta_size'].mean():+.1f}  "
              f"(stdev {marg['delta_size'].std():.1f})")
        print(f"  Mean Jaccard(default, with-smallorder): "
              f"{marg['jaccard_default_vs_with_so'].mean():.3f}")
        print(f"  Mean dMean_BS_of_universe: "
              f"{(marg['mean_bs_with_so'] - marg['mean_bs_default']).mean():+.4f}")

        print("  Per sub-window:")
        for k, (a, b) in config.SUBWINDOWS.items():
            sub = marg[
                ((a is None) | (marg["trade_date"] >= a))
                & ((b is None) | (marg["trade_date"] <= b))
            ]
            if len(sub) == 0:
                continue
            print(f"    {k:>10}: n={len(sub):>3}  "
                  f"dcap={sub['delta_centroid_cap'].mean():+.3f}  "
                  f"drdi={sub['delta_centroid_rdi'].mean():+.3f}  "
                  f"jacc={sub['jaccard_default_vs_with_so'].mean():.3f}")

    print("\n" + "=" * 70)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=0,
                         help="Run on only N evenly-spaced rebalances "
                              "(smoke test). 0 = full panel.")
    parser.add_argument("--skip-rhi", action="store_true")
    parser.add_argument("--skip-bandwidth", action="store_true")
    parser.add_argument("--skip-plots", action="store_true")
    args = parser.parse_args()

    print("=" * 70)
    print(f"universe_exploration/ Phase 1 — start at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    rebal_dates = load_rebalance_dates()
    if args.sample > 0:
        idxs = np.linspace(0, len(rebal_dates) - 1, args.sample).astype(int)
        rebal_dates = [rebal_dates[i] for i in idxs]
    print(f"\nRebalance dates: {len(rebal_dates)} "
          f"[{rebal_dates[0].date()} .. {rebal_dates[-1].date()}]")

    # Pre-compute BS rolling panels.
    print("\n--- Step 0: Prepare returns panel for BS ---")
    panel_start = pd.Timestamp("2018-10-01")  # buffer for 60-day rolling
    panel_end = config.PANEL_END
    prepare_returns_panel(panel_start, panel_end, verbose=True)
    precompute_bs_panels(verbose=True)

    print("\n--- Step 1: Build per-rebalance panels ---")
    panels = build_panels(rebal_dates, verbose=True)

    # If panels are empty (e.g. RDI components missing because Tushare data
    # not yet fetched), abort with clear message.
    if panels["rdi"].empty or panels["bs"].empty:
        print("\n*** ABORT: RDI or BS panel is empty. ***")
        print("    Did you run rdi_fetch.py first?")
        return

    rhi_results: dict = {}
    if not args.skip_rhi:
        print("\n--- Step 2: Per-rebalance RHI (variants A, B; 4-comp + 3-comp) ---")
        rhi_results = run_rhi_per_rebalance(rebal_dates, panels)

    bw_sens = pd.DataFrame()
    if not args.skip_bandwidth and not args.skip_rhi:
        print("\n--- Step 3: Bandwidth sensitivity ---")
        bw_sens = bandwidth_sensitivity(rebal_dates, panels)

    print("\n--- Step 4: Diagnostic aggregates ---")
    diag = diagnostics(panels, rhi_results)

    if not args.skip_plots and rhi_results:
        print("\n--- Step 5: Plots ---")
        try:
            make_plots(panels, rhi_results)
        except Exception as exc:
            print(f"  [plots] FAIL: {exc!r}")

    sample_d = rebal_dates[len(rebal_dates) // 2]
    print_summary(panels, rhi_results, diag, bw_sens, sample_d)


if __name__ == "__main__":
    main()
