"""
turnover_concentration_sweep.py — top-N concentration sweep on residualized
turnover, with realistic retail A-share trading costs.

Question
========
After sector + size residualization, the turnover factor's Q5 (top-quintile,
~700 names) showed Sharpe 1.46 / IR +0.43 vs the universe_EW benchmark on
the post-NNA window. Does concentrating further into the deep tail
(top-300, top-100, top-50, top-20) sharpen the signal, or does noise +
turnover cost eat the gain?

Two competing forces
====================
1. Sharper signal at the tail. If the deepest-residualized-turnover stocks
   carry stronger forward-return predictability than the average Q5 name,
   concentration extracts more alpha.
2. Reduced breadth. Grinold-Kahn fundamental law: IR ≈ IC × √breadth.
   Cutting breadth by 35x (700 -> 20) reduces IR by √35 ≈ 5.9x at constant
   IC. AND smaller baskets have higher idiosyncratic vol, AND higher churn
   rates, so realized costs scale up.

The sweep tells us which force dominates EMPIRICALLY in this universe.

Cost model
==========
A-share retail trading costs (conservative, applies to weekly rebalance):
  - Commission  (佣金):     0.015% (万分之1.5), both sides. Discount-broker
                            standard 2025-26; many waive minimum.
  - Stamp duty (印花税):    0.05%, sell-side only. Halved from 0.10% on
                            2023-08-28.
  - Slippage proxy:         0.05%, both sides. Lower bound for liquid names;
                            optimistic for the deep tail of our universe
                            where daily turnover may be 1-3M RMB. Flag this
                            in interpretation; smaller baskets concentrating
                            in illiquid names will face higher actual slippage.

Round-trip cost = 2 × 0.015% + 0.05% + 2 × 0.05% = 0.18%

Per rebalance, applied as (churn_rate × 0.18%) charged on the entry day.
For the very first rebalance, only the buy-side leg applies (no prior
basket to liquidate): churn × (commission + slippage) = churn × 0.065%.

Convention
==========
open_t1 only. We established this is the realistic execution convention
under T+1 for retail. c2c numbers are reported in the summary for
sanity-check comparison but headline interpretation uses open_t1.

Inputs
======
  - data/factor_panel_a.parquet
  - data/sw_l1_membership.parquet (run fetch_sw_industry.py first)
  - daily_panel/daily_<DATE>.parquet
  - ../Project_6/data/trading_calendar.csv

Outputs
=======
  data/turnover_concentration_summary.csv  - one row per N, gross + net
  data/turnover_concentration_daily.csv    - daily P&L for each top-N basket
  data/turnover_concentration_churn.csv    - per-rebalance churn rates
  graphs/turnover_concentration_sweep.png  - 4-panel headline figure

Usage
=====
    python turnover_concentration_sweep.py --start 2024-04-12
    python turnover_concentration_sweep.py --start 2024-04-12 --end 2026-04-29
    python turnover_concentration_sweep.py --levels 700,300,100,50,20
"""

import argparse
import bisect
import logging
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    A_SHARE_PATTERN,
    DAILY_PANEL_DIR,
    GRAPHS_DIR,
    NEW_NINE_ARTICLES_DATE,
    PBOC_STIMULUS_DATE,
    TRADING_CALENDAR_PATH,
    TRADING_DAYS_PER_YEAR,
)
from factor_utils import (
    cross_sectional_zscore,
    residualise_factor_per_date,
)
from hypothesis_testing import block_bootstrap_ci
# Import fetch_sw_industry LAST so its sys.path manipulation does not
# shadow same-named modules at the repo root.
from fetch_sw_industry import load_current_industry


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
GRAPHS_DIR.mkdir(exist_ok=True)

FACTOR_PANEL_PATH = DATA_DIR / "factor_panel_a.parquet"
SUMMARY_PATH = DATA_DIR / "turnover_concentration_summary.csv"
DAILY_PATH = DATA_DIR / "turnover_concentration_daily.csv"
CHURN_PATH = DATA_DIR / "turnover_concentration_churn.csv"
ERROR_LOG = DATA_DIR / "errors_concentration.log"

# Sweep levels: log-spaced from quintile baseline down to thin tail.
DEFAULT_LEVELS = [700, 300, 100, 50, 20]

# Cost constants (see module docstring for derivation)
COMMISSION_RATE = 0.00015   # 万分之1.5
STAMP_DUTY_RATE = 0.0005    # 0.05% sell-side
SLIPPAGE_RATE = 0.0005      # 万分之5 proxy
COST_BUY_SIDE = COMMISSION_RATE + SLIPPAGE_RATE                    # 0.065%
COST_SELL_SIDE = COMMISSION_RATE + STAMP_DUTY_RATE + SLIPPAGE_RATE  # 0.115%
COST_ROUNDTRIP = COST_BUY_SIDE + COST_SELL_SIDE                     # 0.18%

DAILY_BLOCK_SIZE = 20
SEED = 42
BOOT_N = 5000


_logger = logging.getLogger("concentration_sweep")
_logger.setLevel(logging.WARNING)
if not _logger.handlers:
    _h = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _logger.addHandler(_h)


# ═══════════════════════════════════════════════════════════════════════
# Setup: residualize panel
# ═══════════════════════════════════════════════════════════════════════

def load_residualized_panel() -> pd.DataFrame:
    """
    Load factor panel, attach sector, residualize on (sector + log_mcap),
    z-score and sign-flip. Same procedure as turnover_neutralized.py
    without --with-beta.
    """
    if not FACTOR_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"{FACTOR_PANEL_PATH} not found. "
            f"Run `python build_factor_panel.py full` first."
        )
    panel = pd.read_parquet(FACTOR_PANEL_PATH)
    panel["rebalance_date"] = panel["rebalance_date"].astype(str)
    print(f"Factor panel: {len(panel):,} rows, "
          f"{panel['rebalance_date'].nunique()} dates")

    sectors = load_current_industry()
    panel = panel.merge(
        sectors[["ts_code", "industry_name"]], on="ts_code", how="left"
    )
    panel = panel.rename(columns={"industry_name": "sector_l1"})

    print("\nResidualizing mean_turnover_20d on sector_l1 + log_mcap...")
    panel = residualise_factor_per_date(
        panel,
        factor_col="mean_turnover_20d",
        out_col="turnover_resid",
        numeric_controls=["log_mcap"],
        categorical_control="sector_l1",
    )
    panel = cross_sectional_zscore(
        panel, factor_col="turnover_resid", out_col="z_turn_resid_raw"
    )
    panel["z_turnover_resid"] = -panel["z_turn_resid_raw"]

    iu = panel[panel["in_universe"]]
    n_with = int(iu["z_turnover_resid"].notna().sum())
    print(f"  in_universe rows with z_turnover_resid: {n_with:,} of "
          f"{len(iu):,} ({100*n_with/len(iu):.1f}%)")
    return panel


# ═══════════════════════════════════════════════════════════════════════
# Top-N basket construction + churn
# ═══════════════════════════════════════════════════════════════════════

def build_topn_baskets(panel: pd.DataFrame, levels: list) -> dict:
    """
    For each rebalance date, identify top-N baskets at each level in `levels`.

    Returns:
      baskets[rebal_date] = {
          "universe": set of all in_universe ts_codes that date,
          n: set of top-n ts_codes by z_turnover_resid (highest = predicted
             to outperform = LOWEST raw residualized turnover),
          ... for each n in levels
      }

    Stocks with NaN z_turnover_resid are excluded from sorting.
    """
    print(f"\nBuilding top-N baskets at levels: {levels}")
    iu = panel[panel["in_universe"]].copy()
    iu = iu.dropna(subset=["z_turnover_resid"])

    baskets: dict = {}
    sample_sizes = {n: [] for n in levels}
    for date, g in iu.groupby("rebalance_date"):
        sorted_g = g.sort_values("z_turnover_resid", ascending=False)
        baskets[date] = {"universe": set(g["ts_code"])}
        for n in levels:
            actual_n = min(n, len(sorted_g))
            baskets[date][n] = set(sorted_g.head(actual_n)["ts_code"])
            sample_sizes[n].append(actual_n)

    print(f"  basket sizes (median across {len(baskets)} dates):")
    for n in levels:
        sizes = sample_sizes[n]
        print(f"    top_{n:>3}: median {int(np.median(sizes))}, "
              f"min {min(sizes)}, max {max(sizes)}")
    print(f"    universe: median "
          f"{int(np.median([len(baskets[d]['universe']) for d in baskets]))}")
    return baskets


def compute_churn_panel(baskets: dict, levels: list) -> pd.DataFrame:
    """
    Per-rebalance, per-N churn rate.

    churn = (names entering basket + names leaving basket) / 2 / n

    Equivalent to fraction of basket positions that change. churn = 0 means
    identical basket week-over-week; churn = 1 means complete turnover.

    Returns long-format DataFrame: rebalance_date, n, churn_rate.
    First rebalance date for each N has churn = 1.0 (fresh entry).
    """
    rebal_dates = sorted(baskets.keys())
    rows = []
    for n in levels:
        # First rebalance: fresh entry (all positions are "new")
        rows.append({
            "rebalance_date": rebal_dates[0], "n": n, "churn_rate": 1.0,
            "is_first": True,
        })
        for i in range(1, len(rebal_dates)):
            prev = baskets[rebal_dates[i - 1]][n]
            curr = baskets[rebal_dates[i]][n]
            common = len(prev & curr)
            entered = len(curr - prev)
            left = len(prev - curr)
            actual_n = max(len(prev), len(curr))
            if actual_n == 0:
                churn = np.nan
            else:
                churn = (entered + left) / (2 * actual_n)
            rows.append({
                "rebalance_date": rebal_dates[i], "n": n,
                "churn_rate": churn, "is_first": False,
            })
    out = pd.DataFrame(rows)
    out.to_csv(CHURN_PATH, index=False)
    print(f"\nChurn panel written to {CHURN_PATH}")

    # Print median churn per N
    print(f"\n  Median weekly churn per basket size (excluding first rebalance):")
    for n in levels:
        med = out.loc[(out["n"] == n) & (~out["is_first"]), "churn_rate"].median()
        print(f"    top_{n:>3}: {med*100:.1f}%/week")
    return out


# ═══════════════════════════════════════════════════════════════════════
# Daily T+1 backtest
# ═══════════════════════════════════════════════════════════════════════

def _read_daily_prices(date_str: str):
    path = DAILY_PANEL_DIR / f"daily_{date_str}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df = df[df["ts_code"].str.match(A_SHARE_PATTERN)]
    keep = ["ts_code", "open", "close", "pre_close", "adj_factor"]
    df = df[[c for c in keep if c in df.columns]].copy()
    for c in ("open", "close", "pre_close", "adj_factor"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close", "adj_factor"])
    df = df[df["close"] > 0]
    df["adj_close"] = df["close"] * df["adj_factor"]
    if "open" in df.columns:
        df["adj_open"] = df["open"] * df["adj_factor"]
    return df.set_index("ts_code")


def run_concentration_backtest(
    panel: pd.DataFrame, levels: list, start_date=None, end_date=None,
) -> tuple:
    """
    T+1 daily backtest at each N level plus universe_ew benchmark.
    Returns (daily_df, baskets_dict).
    """
    print("\n" + "=" * 76)
    print("CONCENTRATION SWEEP: T+1 daily backtest")
    print("=" * 76)

    baskets = build_topn_baskets(panel, levels)
    rebal_dates_sorted = sorted(baskets.keys())

    cal = pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()
    first_idx = cal.index(rebal_dates_sorted[0]) + 1
    last_idx = min(cal.index(rebal_dates_sorted[-1]) + 5, len(cal) - 1)
    trade_dates = cal[first_idx:last_idx + 1]
    if start_date:
        trade_dates = [d for d in trade_dates if d >= start_date]
    if end_date:
        trade_dates = [d for d in trade_dates if d <= end_date]
    print(f"\nBacktest range: {trade_dates[0]} to {trade_dates[-1]} "
          f"({len(trade_dates)} trading days)")

    # Map trade_date -> True if first trading day after a rebalance
    first_day_of_period = {}
    for r in rebal_dates_sorted:
        if r not in cal:
            continue
        ridx = cal.index(r)
        if ridx + 1 < len(cal):
            first_day_of_period[cal[ridx + 1]] = True

    # Map trade_date (entry day) -> rebalance_date that just opened
    entry_day_to_rebal = {}
    for r in rebal_dates_sorted:
        if r not in cal:
            continue
        ridx = cal.index(r)
        if ridx + 1 < len(cal):
            entry_day_to_rebal[cal[ridx + 1]] = r

    print(f"\nIterating over trading days...")
    rows = []
    n_failed = 0
    t0 = time.time()
    prev_prices = None
    rebal_dates_idx = {d: i for i, d in enumerate(rebal_dates_sorted)}

    for i, td in enumerate(trade_dates, 1):
        prices = _read_daily_prices(td)
        if prices is None:
            n_failed += 1
            prev_prices = None
            continue

        # Find which basket is currently held (most recent rebalance ≤ td)
        idx = bisect.bisect_right(rebal_dates_sorted, td) - 1
        if idx < 0:
            prev_prices = prices
            continue
        held_rebal = rebal_dates_sorted[idx]
        basket = baskets[held_rebal]
        is_first = first_day_of_period.get(td, False)

        # On entry days, compute churn-driven cost adjustment per N
        cost_per_n = {n: 0.0 for n in levels}
        if is_first and td in entry_day_to_rebal:
            this_rebal = entry_day_to_rebal[td]
            this_idx = rebal_dates_idx[this_rebal]
            for n in levels:
                if this_idx == 0:
                    # First rebalance ever: just buy-side cost on full basket
                    cost_per_n[n] = COST_BUY_SIDE
                else:
                    prev_rebal = rebal_dates_sorted[this_idx - 1]
                    prev_set = baskets[prev_rebal][n]
                    curr_set = baskets[this_rebal][n]
                    actual_n = max(len(prev_set), len(curr_set))
                    if actual_n == 0:
                        churn = 0.0
                    else:
                        entered = len(curr_set - prev_set)
                        left = len(prev_set - curr_set)
                        churn = (entered + left) / (2 * actual_n)
                    cost_per_n[n] = churn * COST_ROUNDTRIP

        # Compute returns for each strategy under open_t1 convention
        strategies = [(f"top_{n}", basket[n], cost_per_n[n]) for n in levels]
        strategies.append(("universe_ew", basket["universe"], 0.0))

        for strat, members, cost_today in strategies:
            if not members:
                continue
            present = prices.index.intersection(members)
            if len(present) == 0:
                continue
            sub = prices.loc[present]

            if is_first:
                # Entry day: open-to-close return, minus cost
                if "adj_open" not in sub.columns:
                    continue
                valid = sub["adj_open"].notna() & (sub["adj_open"] > 0)
                if valid.sum() == 0:
                    continue
                sv = sub[valid]
                gross = (sv["adj_close"] / sv["adj_open"] - 1).mean()
                rows.append({
                    "trade_date": td, "strategy": strat,
                    "daily_return_gross": float(gross),
                    "cost_today": float(cost_today),
                    "daily_return_net": float(gross) - float(cost_today),
                    "n_held": int(valid.sum()),
                    "is_entry_day": True,
                })
            else:
                # Holding day: close-to-close return, no cost
                if prev_prices is None:
                    continue
                pp = prev_prices.index.intersection(present)
                if len(pp) == 0:
                    continue
                p_prev = prev_prices.loc[pp, "adj_close"]
                p_curr = sub.loc[pp, "adj_close"]
                gross = (p_curr / p_prev - 1).mean()
                rows.append({
                    "trade_date": td, "strategy": strat,
                    "daily_return_gross": float(gross),
                    "cost_today": 0.0,
                    "daily_return_net": float(gross),
                    "n_held": int(len(pp)),
                    "is_entry_day": False,
                })

        prev_prices = prices

        if i % 200 == 0 or i == len(trade_dates):
            print(f"  [{i:>4}/{len(trade_dates)}] failed={n_failed} "
                  f"rows={len(rows):,} elapsed={time.time()-t0:.1f}s")

    daily = pd.DataFrame(rows)
    daily.to_csv(DAILY_PATH, index=False)
    print(f"\nDaily P&L: {len(daily):,} rows, saved to {DAILY_PATH}")
    return daily, baskets


# ═══════════════════════════════════════════════════════════════════════
# Summary metrics: gross vs net per N
# ═══════════════════════════════════════════════════════════════════════

def _summary_metrics(returns: pd.Series) -> dict:
    """Standard metrics for a daily return series."""
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return {"n_days": 0}
    cum = (1 + r).cumprod()
    years = n / TRADING_DAYS_PER_YEAR
    ann_ret = cum.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    std = r.std()
    sharpe = (r.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR)
              if std > 0 else np.nan)
    running_max = cum.cummax()
    max_dd = float((cum / running_max - 1).min())
    hit = float((r > 0).mean())
    return {
        "n_days": n,
        "ann_return_pct": ann_ret * 100,
        "ann_vol_pct": std * np.sqrt(TRADING_DAYS_PER_YEAR) * 100,
        "sharpe": sharpe,
        "cumulative_pct": (cum.iloc[-1] - 1) * 100,
        "max_dd_pct": max_dd * 100,
        "hit_rate_pct": hit * 100,
    }


def _ir_vs_benchmark(strat_returns: pd.Series,
                      bench_returns: pd.Series) -> dict:
    """Information ratio: active return / tracking error."""
    aligned = pd.concat([strat_returns, bench_returns], axis=1,
                         keys=["strat", "bench"]).dropna()
    if len(aligned) < 30:
        return {"active_return_pct": np.nan, "tracking_error_pct": np.nan,
                "ir": np.nan}
    active = aligned["strat"] - aligned["bench"]
    active_mean = active.mean()
    active_std = active.std()
    ir = (active_mean / active_std * np.sqrt(TRADING_DAYS_PER_YEAR)
          if active_std > 0 else np.nan)
    # Active return annualized
    active_ann = (1 + active_mean) ** TRADING_DAYS_PER_YEAR - 1
    return {
        "active_return_pct": active_ann * 100,
        "tracking_error_pct": active_std * np.sqrt(TRADING_DAYS_PER_YEAR) * 100,
        "ir": float(ir),
    }


def summarise_concentration(daily: pd.DataFrame, levels: list) -> pd.DataFrame:
    print("\n" + "=" * 76)
    print("CONCENTRATION SWEEP: per-N summary metrics")
    print("=" * 76)

    # Pivot to wide format for per-strategy series
    bench = daily[daily["strategy"] == "universe_ew"].set_index("trade_date")
    bench_gross = bench["daily_return_gross"]
    bench_net = bench["daily_return_net"]

    rows = []
    for n in levels:
        strat_name = f"top_{n}"
        sub = daily[daily["strategy"] == strat_name].set_index("trade_date")
        if len(sub) == 0:
            continue
        gr_metrics = _summary_metrics(sub["daily_return_gross"])
        nt_metrics = _summary_metrics(sub["daily_return_net"])
        ir_gr = _ir_vs_benchmark(sub["daily_return_gross"], bench_gross)
        ir_nt = _ir_vs_benchmark(sub["daily_return_net"], bench_net)
        rows.append({
            "n": n,
            "ann_ret_gross_pct": gr_metrics["ann_return_pct"],
            "ann_ret_net_pct": nt_metrics["ann_return_pct"],
            "ann_vol_pct": gr_metrics["ann_vol_pct"],
            "sharpe_gross": gr_metrics["sharpe"],
            "sharpe_net": nt_metrics["sharpe"],
            "active_ret_gross_pct": ir_gr["active_return_pct"],
            "active_ret_net_pct": ir_nt["active_return_pct"],
            "tracking_error_pct": ir_gr["tracking_error_pct"],
            "ir_gross": ir_gr["ir"],
            "ir_net": ir_nt["ir"],
            "max_dd_gross_pct": gr_metrics["max_dd_pct"],
            "max_dd_net_pct": nt_metrics["max_dd_pct"],
            "n_days": gr_metrics["n_days"],
        })

    # Add universe_ew baseline
    bench_metrics = _summary_metrics(bench_gross)
    rows.append({
        "n": "benchmark",
        "ann_ret_gross_pct": bench_metrics["ann_return_pct"],
        "ann_ret_net_pct": bench_metrics["ann_return_pct"],
        "ann_vol_pct": bench_metrics["ann_vol_pct"],
        "sharpe_gross": bench_metrics["sharpe"],
        "sharpe_net": bench_metrics["sharpe"],
        "active_ret_gross_pct": 0.0, "active_ret_net_pct": 0.0,
        "tracking_error_pct": 0.0, "ir_gross": np.nan, "ir_net": np.nan,
        "max_dd_gross_pct": bench_metrics["max_dd_pct"],
        "max_dd_net_pct": bench_metrics["max_dd_pct"],
        "n_days": bench_metrics["n_days"],
    })

    out = pd.DataFrame(rows)
    out.to_csv(SUMMARY_PATH, index=False)

    # Pretty print
    pretty = out.copy()
    for col in pretty.columns:
        if pretty[col].dtype == "float64":
            pretty[col] = pretty[col].round(3)
    print("\n" + pretty.to_string(index=False))
    print(f"\nSaved to {SUMMARY_PATH}")
    return out


# ═══════════════════════════════════════════════════════════════════════
# Plotting
# ═══════════════════════════════════════════════════════════════════════

def plot_sweep(daily: pd.DataFrame, summary: pd.DataFrame,
                levels: list, churn: pd.DataFrame) -> None:
    """4-panel headline figure."""
    print("\nGenerating concentration sweep plot...")

    daily = daily.copy()
    daily["trade_date_ts"] = pd.to_datetime(daily["trade_date"].astype(str))

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))

    # ─── Panel 1: cumulative returns, all top-N + benchmark, NET ───
    ax = axes[0, 0]
    palette = plt.cm.viridis(np.linspace(0.05, 0.85, len(levels)))
    for color, n in zip(palette, levels):
        sub = daily[daily["strategy"] == f"top_{n}"].sort_values("trade_date_ts")
        if len(sub) == 0:
            continue
        cum = (1 + sub["daily_return_net"].fillna(0)).cumprod()
        ax.plot(sub["trade_date_ts"], cum, label=f"top_{n}",
                color=color, linewidth=1.4)
    bench_sub = daily[daily["strategy"] == "universe_ew"].sort_values("trade_date_ts")
    cum_bench = (1 + bench_sub["daily_return_gross"].fillna(0)).cumprod()
    ax.plot(bench_sub["trade_date_ts"], cum_bench, label="universe_ew",
            color="black", linewidth=1.5, linestyle="--")
    ax.axvline(NEW_NINE_ARTICLES_DATE, color="firebrick",
               linestyle="--", alpha=0.4)
    ax.axvline(PBOC_STIMULUS_DATE, color="seagreen",
               linestyle="--", alpha=0.4)
    ax.set_title("Cumulative return (net of cost)")
    ax.set_ylabel("Cumulative (×)")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
    ax.grid(alpha=0.3)

    # ─── Panel 2: IR vs N, gross vs net ───
    ax = axes[0, 1]
    s = summary[summary["n"] != "benchmark"].copy()
    s["n"] = s["n"].astype(int)
    s = s.sort_values("n")
    ax.plot(s["n"], s["ir_gross"], "o-", color="#1f77b4",
            label="IR (gross)", linewidth=2, markersize=9)
    ax.plot(s["n"], s["ir_net"], "s-", color="#d62728",
            label="IR (net of cost)", linewidth=2, markersize=9)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.axhline(0.5, color="gray", linewidth=0.5, linestyle=":",
               label="IR=0.5 (good)")
    ax.axhline(0.3, color="gray", linewidth=0.5, linestyle=":")
    ax.set_xscale("log")
    ax.set_xticks(s["n"])
    ax.set_xticklabels(s["n"].astype(str))
    ax.set_xlabel("Basket size N")
    ax.set_ylabel("Information Ratio (annualized)")
    ax.set_title("IR vs basket size (concentration sweep)")
    ax.legend(loc="best", fontsize=10)
    ax.grid(alpha=0.3)

    # ─── Panel 3: Sharpe vs N, gross vs net ───
    ax = axes[1, 0]
    ax.plot(s["n"], s["sharpe_gross"], "o-", color="#1f77b4",
            label="Sharpe (gross)", linewidth=2, markersize=9)
    ax.plot(s["n"], s["sharpe_net"], "s-", color="#d62728",
            label="Sharpe (net of cost)", linewidth=2, markersize=9)
    bench_sharpe = float(
        summary.loc[summary["n"] == "benchmark", "sharpe_gross"].iloc[0]
    )
    ax.axhline(bench_sharpe, color="black", linewidth=1, linestyle="--",
               label=f"benchmark={bench_sharpe:.2f}")
    ax.set_xscale("log")
    ax.set_xticks(s["n"])
    ax.set_xticklabels(s["n"].astype(str))
    ax.set_xlabel("Basket size N")
    ax.set_ylabel("Sharpe (annualized)")
    ax.set_title("Sharpe vs basket size")
    ax.legend(loc="best", fontsize=10)
    ax.grid(alpha=0.3)

    # ─── Panel 4: weekly churn by N (boxplot or stripplot) ───
    ax = axes[1, 1]
    churn_data = []
    for n in levels:
        c = churn.loc[(churn["n"] == n) & (~churn["is_first"]),
                       "churn_rate"].values * 100
        churn_data.append(c)
    bp = ax.boxplot(churn_data, labels=[f"top_{n}" for n in levels],
                     showmeans=True, meanline=True, widths=0.6,
                     patch_artist=True)
    for patch, color in zip(bp["boxes"], palette):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    ax.set_ylabel("Weekly churn rate (%)")
    ax.set_title("Basket churn (weekly turnover) per N\n"
                 "Higher churn -> higher cost drag")
    ax.grid(alpha=0.3, axis="y")

    fig.suptitle("Concentration sweep: residualized turnover, "
                 "open_t1 convention, post-NNA", fontsize=12, y=1.00)
    fig.tight_layout()
    out_path = GRAPHS_DIR / "turnover_concentration_sweep.png"
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved to {out_path}")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=str, default="2024-04-12",
                    help="Backtest start date (default: 新国九条 date)")
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--levels", type=str, default=None,
                    help=f"Comma-separated basket sizes "
                         f"(default: {','.join(map(str, DEFAULT_LEVELS))})")
    args = ap.parse_args()

    if args.levels:
        levels = sorted([int(x) for x in args.levels.split(",")], reverse=True)
    else:
        levels = DEFAULT_LEVELS
    print(f"Sweep levels: {levels}")
    print(f"Cost model: roundtrip = {COST_ROUNDTRIP*100:.3f}% "
          f"(commission {2*COMMISSION_RATE*100:.3f}%, "
          f"stamp {STAMP_DUTY_RATE*100:.3f}%, "
          f"slippage {2*SLIPPAGE_RATE*100:.3f}%)")

    panel = load_residualized_panel()
    daily, baskets = run_concentration_backtest(
        panel, levels, start_date=args.start, end_date=args.end
    )
    churn = compute_churn_panel(baskets, levels)
    summary = summarise_concentration(daily, levels)
    plot_sweep(daily, summary, levels, churn)
    print("\nDone.")


if __name__ == "__main__":
    main()