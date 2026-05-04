"""
turnover_analysis.py — 换手率因子 on Universe A.

Pipeline
========

Phase 1: factor research (weekly cadence)
-----------------------------------------
For each rebalance date and each in_universe stock:
  - raw_factor = mean_turnover_20d (already computed in factor_panel_a)
  - z_turn_raw = cross-sectional z-score of raw_factor (winsorized 1/99)
  - z_turnover = -z_turn_raw  (sign flip: high z = LOW turnover)

Then:
  - Quintile sort on z_turnover, mean weekly_forward_return per quintile
  - Q5 minus Q1 spread (top quintile minus bottom)
  - Cross-sectional Spearman IC vs weekly_forward_return per date
  - Block bootstrap CI on Q5-Q1 mean and IC mean (block_size=12 weeks)

Output of phase 1: weekly_q1q5_spread, ic_series, summary table

Phase 2: T+1 daily backtest
---------------------------
For each rebalance date `t`:
  - Q5 long basket = stocks in top quintile of z_turnover at close[t]
  - Q1 short basket = stocks in bottom quintile of z_turnover at close[t]
  - Trades fire at open[t+1] (T+1 rule)
  - Held until next rebalance signal at close[t+5], replaced at open[t+6]

Two return conventions computed in parallel:
  - close-to-close: return on each held day = close[d] / close[d-1] - 1
                    (entry priced at close[t], simpler but slightly optimistic)
  - open-T+1:       return on entry day  = close[t+1] / open[t+1] - 1
                    return on exit day   = open[t_next+1] / close[t_next] - 1
                    (correctly prices the gap from signal to execution)

Two strategy types:
  - long_only:   hold Q5, no short
  - long_short:  long Q5, short Q1, dollar-neutral (50% gross each side)

Plus benchmark:
  - universe_ew: equal-weight all in_universe stocks at each rebalance,
                 computed under both conventions for fair comparison

Output of phase 2: daily_pnl_panel.csv with one row per trading day per
strategy variant; summary metrics (Sharpe, ann return, max drawdown,
hit rate); cumulative P&L plot.

Running the script
------------------
    python turnover_analysis.py phase1            # weekly factor research only
    python turnover_analysis.py phase2 --start 2024-04-12   # T+1 backtest from γ
    python turnover_analysis.py both              # phase1 + phase2 over full panel
    python turnover_analysis.py both --start 2024-04-12     # γ-only backtest

Prerequisites
-------------
  - data/factor_panel_a.parquet (run build_factor_panel.py full)
  - daily_panel/daily_<DATE>.parquet for every trading day in the analysis range
  - ../Project_6/data/trading_calendar.csv
"""

import argparse
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
    compute_ic_series,
    compute_quintile_series,
    cross_sectional_zscore,
    summarise_long_short,
)
from hypothesis_testing import block_bootstrap_ci


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
GRAPHS_DIR.mkdir(exist_ok=True)

FACTOR_PANEL_PATH = DATA_DIR / "factor_panel_a.parquet"
PHASE1_OUT_PATH = DATA_DIR / "turnover_phase1_summary.csv"
PHASE2_DAILY_PNL_PATH = DATA_DIR / "turnover_phase2_daily_pnl.csv"
PHASE2_SUMMARY_PATH = DATA_DIR / "turnover_phase2_summary.csv"
ERROR_LOG = DATA_DIR / "errors_turnover.log"

COMPRESSION = "zstd"

# Phase 2 parameters
N_QUINTILES = 5
WEEKLY_BLOCK_SIZE = 12      # for bootstrap on weekly Q5-Q1 series
DAILY_BLOCK_SIZE = 20       # for bootstrap on daily P&L series
SEED = 42
BOOT_N = 5000


_logger = logging.getLogger("turnover_analysis")
_logger.setLevel(logging.WARNING)
if not _logger.handlers:
    _handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _logger.addHandler(_handler)


def _log_warn(date: str, msg: str) -> None:
    _logger.warning(f"date={date} | {msg}")


# ═══════════════════════════════════════════════════════════════════════
# PHASE 1: weekly factor research
# ═══════════════════════════════════════════════════════════════════════

def load_factor_panel() -> pd.DataFrame:
    if not FACTOR_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"{FACTOR_PANEL_PATH} not found. "
            f"Run `python build_factor_panel.py full` first."
        )
    panel = pd.read_parquet(FACTOR_PANEL_PATH)
    panel["rebalance_date"] = panel["rebalance_date"].astype(str)
    return panel


def add_z_turnover(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute z_turnover with the sign-flip baked in."""
    panel = cross_sectional_zscore(
        panel, factor_col="mean_turnover_20d", out_col="z_turn_raw",
    )
    panel["z_turnover"] = -panel["z_turn_raw"]   # high z = LOW turnover
    return panel


def run_phase1(panel: pd.DataFrame) -> dict:
    print("\n" + "=" * 76)
    print("PHASE 1: weekly factor research on z_turnover")
    print("=" * 76)

    panel = add_z_turnover(panel)

    iu = panel[panel["in_universe"]]
    n_with_factor = int(iu["z_turnover"].notna().sum())
    print(f"\n  in_universe rows with z_turnover defined: "
          f"{n_with_factor:,} of {len(iu):,} "
          f"({100*n_with_factor/len(iu):.1f}%)")

    # Distribution sanity
    z = iu["z_turnover"].dropna()
    print(f"\n  z_turnover distribution: "
          f"mean={z.mean():.3f}, std={z.std():.3f}, "
          f"min={z.min():.2f}, max={z.max():.2f}")
    print(f"  raw turnover (mean_turnover_20d) on in_universe rows:")
    raw = iu["mean_turnover_20d"].dropna()
    print(f"    mean={raw.mean():.2f}%, median={raw.median():.2f}%, "
          f"p5={raw.quantile(0.05):.2f}%, p95={raw.quantile(0.95):.2f}%")

    # Quintile sort
    print(f"\n  --- Quintile sort on z_turnover ---")
    qr = compute_quintile_series(panel, sort_col="z_turnover")
    print(f"  quintile mean weekly forward returns:")
    for q in range(5):
        mean = qr[q].mean() * 100 if q in qr.columns else np.nan
        print(f"    Q{q+1} (z_turnover {'lowest' if q==0 else 'highest' if q==4 else 'mid'}): "
              f"{mean:+.3f}%/wk")

    summary = summarise_long_short(qr, "Q5 - Q1 spread (z_turnover)")

    # Bootstrap CI on Q5-Q1
    if summary.get("n", 0) >= 2 * WEEKLY_BLOCK_SIZE:
        boot = block_bootstrap_ci(
            summary["ls_series"].values, np.mean,
            block_size=WEEKLY_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
        )
        print(f"\n  Block bootstrap CI on Q5-Q1 mean "
              f"(block_size={WEEKLY_BLOCK_SIZE} weeks, n_boot={BOOT_N}):")
        print(f"    estimate: {boot['estimate']*100:+.3f}%/wk")
        print(f"    95% CI:   [{boot['ci_low']*100:+.3f}%, "
              f"{boot['ci_high']*100:+.3f}%]")
        ci_excludes_zero = (
            (boot["ci_low"] > 0) or (boot["ci_high"] < 0)
        )
        print(f"    CI excludes zero: {ci_excludes_zero}")
        summary["bootstrap_q1q5"] = boot

    # IC time series
    print(f"\n  --- Cross-sectional Spearman IC ---")
    ic = compute_ic_series(panel, sort_col="z_turnover")
    print(f"  IC: n={len(ic)}, mean={ic.mean():+.4f}, std={ic.std():.4f}, "
          f"t-stat={ic.mean() / (ic.std() / np.sqrt(len(ic))):+.2f}")
    if len(ic) >= 2 * WEEKLY_BLOCK_SIZE:
        boot_ic = block_bootstrap_ci(
            ic.values, np.mean,
            block_size=WEEKLY_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
        )
        print(f"    95% CI on mean IC: [{boot_ic['ci_low']:+.4f}, "
              f"{boot_ic['ci_high']:+.4f}]")
        summary["bootstrap_ic"] = boot_ic
    summary["ic_series"] = ic
    summary["quintile_returns"] = qr

    # Save phase 1 output
    print(f"\nSaving phase 1 summary to {PHASE1_OUT_PATH}...")
    rows = [{
        "metric": "Q5_minus_Q1",
        "n_periods": summary.get("n"),
        "mean_pct_wk": summary.get("mean_period", 0) * 100,
        "t_stat": summary.get("t_stat"),
        "naive_sharpe": summary.get("naive_sharpe"),
        "ci_low_pct_wk": summary.get("bootstrap_q1q5", {}).get("ci_low", np.nan) * 100,
        "ci_high_pct_wk": summary.get("bootstrap_q1q5", {}).get("ci_high", np.nan) * 100,
    }, {
        "metric": "ic_mean",
        "n_periods": int(len(ic)),
        "mean_pct_wk": float(ic.mean()),
        "t_stat": float(ic.mean() / (ic.std() / np.sqrt(len(ic)))) if len(ic) else np.nan,
        "naive_sharpe": np.nan,
        "ci_low_pct_wk": summary.get("bootstrap_ic", {}).get("ci_low", np.nan),
        "ci_high_pct_wk": summary.get("bootstrap_ic", {}).get("ci_high", np.nan),
    }]
    pd.DataFrame(rows).to_csv(PHASE1_OUT_PATH, index=False)

    return summary


# ═══════════════════════════════════════════════════════════════════════
# PHASE 2: daily T+1 backtest
# ═══════════════════════════════════════════════════════════════════════

def _build_baskets(panel: pd.DataFrame) -> dict:
    """
    For each rebalance date, identify Q5 (long) and Q1 (short) baskets
    plus the universe-EW basket. Returns:
        baskets[rebal_date] = {
            "q5": set(ts_codes), "q1": set(ts_codes),
            "universe": set(ts_codes),
        }
    """
    panel = add_z_turnover(panel)
    iu = panel[panel["in_universe"]].copy()
    iu = iu.dropna(subset=["z_turnover"])
    iu["quintile"] = iu.groupby("rebalance_date")["z_turnover"].transform(
        lambda s: pd.qcut(s, N_QUINTILES, labels=False, duplicates="drop")
    )

    baskets: dict = {}
    for rebal_date, group in iu.groupby("rebalance_date"):
        baskets[rebal_date] = {
            "q5": set(group.loc[group["quintile"] == 4, "ts_code"]),
            "q1": set(group.loc[group["quintile"] == 0, "ts_code"]),
            "universe": set(group["ts_code"]),
        }
    return baskets


def _read_daily_prices(date_str: str) -> pd.DataFrame | None:
    """
    Read one day's parquet, return ts_code-indexed frame with
    open, close, pre_close, adj_factor.
    """
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
    df = df[(df["close"] > 0)]
    df["adj_close"] = df["close"] * df["adj_factor"]
    if "open" in df.columns:
        df["adj_open"] = df["open"] * df["adj_factor"]
    return df.set_index("ts_code")


def _basket_for_date(
    trade_date: str,
    rebal_dates_sorted: list,
    baskets: dict,
) -> dict | None:
    """
    Look up which basket was held on trade_date.
    Held basket = the basket established at the most recent rebalance ≤ trade_date.
    """
    import bisect
    idx = bisect.bisect_right(rebal_dates_sorted, trade_date) - 1
    if idx < 0:
        return None
    return baskets[rebal_dates_sorted[idx]]


def run_phase2(panel: pd.DataFrame, start_date: str | None = None,
               end_date: str | None = None) -> pd.DataFrame:
    """
    Daily T+1 backtest. Returns a long-format DataFrame with columns:
        trade_date, strategy, convention, daily_return
    where strategy ∈ {"q5_long", "q1_short", "long_short", "universe_ew"}
    and convention ∈ {"c2c", "open_t1"}.

    Mechanics:
      - q5_long:    held Q5 of most-recent rebalance, daily return on basket
      - q1_short:   held Q1, RETURN IS NEGATED so positive = short was profitable
      - long_short: 0.5 * q5_long_return + 0.5 * q1_short_return
                    (dollar-neutral, 50/50 gross weights; sums to 100% gross)
      - universe_ew: held all in-universe stocks at most-recent rebalance

    convention = "c2c" (close-to-close): daily return = adj_close[d] / adj_close[d-1] - 1
                                          for every held day. Entry is at
                                          close[t_rebal], exit at close[next_rebal].

    convention = "open_t1": entry day = adj_close[d] / adj_open[d] - 1
                            other held days = adj_close[d] / adj_close[d-1] - 1
                            exit day = adj_open[d] / adj_close[d-1] - 1
                            where d is open[t_rebal+1] (entry) and the
                            named exit day is open[next_rebal+1].
    """
    print("\n" + "=" * 76)
    print("PHASE 2: T+1 daily backtest")
    print("=" * 76)

    print("\nBuilding baskets per rebalance date...")
    baskets = _build_baskets(panel)
    rebal_dates_sorted = sorted(baskets.keys())
    print(f"  {len(rebal_dates_sorted)} rebalance dates with valid baskets")

    # Diagnostic: basket size distribution
    q5_sizes = [len(baskets[d]["q5"]) for d in rebal_dates_sorted]
    q1_sizes = [len(baskets[d]["q1"]) for d in rebal_dates_sorted]
    print(f"  Q5 basket size: median {int(np.median(q5_sizes))}, "
          f"min {min(q5_sizes)}, max {max(q5_sizes)}")
    print(f"  Q1 basket size: median {int(np.median(q1_sizes))}, "
          f"min {min(q1_sizes)}, max {max(q1_sizes)}")

    # Determine the trading-day range
    cal = pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()
    first_rebal = rebal_dates_sorted[0]
    last_rebal = rebal_dates_sorted[-1]
    first_idx = cal.index(first_rebal) + 1   # T+1 entry, so day after first rebal
    last_idx = min(cal.index(last_rebal) + 5, len(cal) - 1)  # 5 trading days after last rebal
    trade_dates = cal[first_idx:last_idx + 1]

    if start_date:
        trade_dates = [d for d in trade_dates if d >= start_date]
    if end_date:
        trade_dates = [d for d in trade_dates if d <= end_date]
    print(f"\nBacktest range: {trade_dates[0]} to {trade_dates[-1]} "
          f"({len(trade_dates)} trading days)")

    # Identify the "first day" of each holding period (for open-T+1 entry pricing).
    # The first day of the period starting at rebalance r is the trading day
    # immediately after r in the calendar.
    first_day_of_period = {}  # trade_date -> True if this is the entry day
    for r in rebal_dates_sorted:
        if r not in cal:
            continue
        ridx = cal.index(r)
        if ridx + 1 < len(cal):
            first_day_of_period[cal[ridx + 1]] = True

    # Core loop: for each trading day, look up basket, compute return
    print(f"\nIterating over trading days...")
    rows = []
    n_failed = 0
    t0 = time.time()
    prev_prices = None  # adj_close from previous trading day for c2c return

    for i, trade_date in enumerate(trade_dates, 1):
        prices = _read_daily_prices(trade_date)
        if prices is None:
            n_failed += 1
            _log_warn(trade_date, "daily panel missing")
            prev_prices = None
            continue

        basket = _basket_for_date(trade_date, rebal_dates_sorted, baskets)
        if basket is None:
            prev_prices = prices
            continue

        is_first_day = first_day_of_period.get(trade_date, False)

        # Compute basket returns under both conventions
        for strategy_name, members, sign in [
            ("q5_long",  basket["q5"],       +1),
            ("q1_short", basket["q1"],       -1),  # short → negate
            ("universe_ew", basket["universe"], +1),
        ]:
            if not members:
                continue
            present = prices.index.intersection(members)
            if len(present) == 0:
                continue
            sub = prices.loc[present]

            # close-to-close convention
            if prev_prices is not None:
                prev_present = prev_prices.index.intersection(present)
                if len(prev_present) > 0:
                    p_prev = prev_prices.loc[prev_present, "adj_close"]
                    p_curr = sub.loc[prev_present, "adj_close"]
                    c2c_ret = (p_curr / p_prev - 1).mean() * sign
                    rows.append({
                        "trade_date": trade_date,
                        "strategy": strategy_name,
                        "convention": "c2c",
                        "daily_return": float(c2c_ret),
                        "n_held": int(len(prev_present)),
                    })

            # open-T+1 convention
            if "adj_open" in sub.columns:
                if is_first_day:
                    # Entry day: return from adj_open to adj_close
                    valid = sub["adj_open"].notna() & (sub["adj_open"] > 0)
                    if valid.sum() > 0:
                        sv = sub[valid]
                        ret = (sv["adj_close"] / sv["adj_open"] - 1).mean() * sign
                        rows.append({
                            "trade_date": trade_date,
                            "strategy": strategy_name,
                            "convention": "open_t1",
                            "daily_return": float(ret),
                            "n_held": int(valid.sum()),
                        })
                else:
                    # Normal day: same as c2c
                    if prev_prices is not None:
                        prev_present = prev_prices.index.intersection(present)
                        if len(prev_present) > 0:
                            p_prev = prev_prices.loc[prev_present, "adj_close"]
                            p_curr = sub.loc[prev_present, "adj_close"]
                            ret = (p_curr / p_prev - 1).mean() * sign
                            rows.append({
                                "trade_date": trade_date,
                                "strategy": strategy_name,
                                "convention": "open_t1",
                                "daily_return": float(ret),
                                "n_held": int(len(prev_present)),
                            })

        prev_prices = prices

        if i % 200 == 0 or i == len(trade_dates):
            secs = time.time() - t0
            print(f"  [{i:>4}/{len(trade_dates)}] failed={n_failed} "
                  f"rows={len(rows):,} elapsed={secs:.1f}s")

    daily = pd.DataFrame(rows)

    # Build long_short return = q5_long + q1_short, weighted 50/50.
    # Note q1_short already has the sign flipped, so this is sum/2.
    print(f"\nBuilding long_short series from q5_long + q1_short / 2...")
    pivoted = daily.pivot_table(
        index=["trade_date", "convention"],
        columns="strategy", values="daily_return",
    ).reset_index()
    if "q5_long" in pivoted.columns and "q1_short" in pivoted.columns:
        pivoted["long_short"] = (
            0.5 * pivoted["q5_long"] + 0.5 * pivoted["q1_short"]
        )

    # Re-stack to long format
    long_format = pivoted.melt(
        id_vars=["trade_date", "convention"],
        value_vars=[c for c in pivoted.columns
                    if c not in ("trade_date", "convention")],
        var_name="strategy", value_name="daily_return",
    ).dropna(subset=["daily_return"])

    print(f"\nDaily P&L panel: {len(long_format):,} rows "
          f"({long_format['strategy'].nunique()} strategies × "
          f"{long_format['convention'].nunique()} conventions × "
          f"{long_format['trade_date'].nunique()} dates)")

    long_format.to_csv(PHASE2_DAILY_PNL_PATH, index=False)
    print(f"  saved to {PHASE2_DAILY_PNL_PATH}")

    return long_format


def summarise_phase2(daily: pd.DataFrame) -> pd.DataFrame:
    """Per (strategy, convention): cumulative return, Sharpe, drawdown, hit rate."""
    print("\n" + "=" * 76)
    print("PHASE 2 SUMMARY: per-strategy metrics")
    print("=" * 76)

    rows = []
    for (strat, conv), group in daily.groupby(["strategy", "convention"]):
        g = group.sort_values("trade_date").copy()
        r = g["daily_return"].dropna()
        n = len(r)
        if n == 0:
            continue
        cum = (1 + r).cumprod()
        final = float(cum.iloc[-1])
        years = n / TRADING_DAYS_PER_YEAR
        ann_ret = final ** (1 / years) - 1 if years > 0 else np.nan
        mean = float(r.mean())
        std = float(r.std())
        sharpe = mean / std * np.sqrt(TRADING_DAYS_PER_YEAR) if std > 0 else np.nan

        # Max drawdown
        running_max = cum.cummax()
        dd = (cum / running_max - 1)
        max_dd = float(dd.min())

        # Hit rate
        hit_rate = float((r > 0).mean())

        # Bootstrap CI on Sharpe (block_size=20)
        if n >= 2 * DAILY_BLOCK_SIZE:
            def _sharpe(arr):
                m = arr.mean()
                s = arr.std()
                return m / s * np.sqrt(TRADING_DAYS_PER_YEAR) if s > 0 else np.nan
            boot = block_bootstrap_ci(
                r.values, _sharpe,
                block_size=DAILY_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
            )
            sharpe_ci_low = boot["ci_low"]
            sharpe_ci_high = boot["ci_high"]
        else:
            sharpe_ci_low = np.nan
            sharpe_ci_high = np.nan

        rows.append({
            "strategy": strat, "convention": conv, "n_days": n,
            "ann_return_pct": ann_ret * 100,
            "ann_vol_pct": std * np.sqrt(TRADING_DAYS_PER_YEAR) * 100,
            "sharpe": sharpe,
            "sharpe_ci_low": sharpe_ci_low,
            "sharpe_ci_high": sharpe_ci_high,
            "cumulative_return_pct": (final - 1) * 100,
            "max_drawdown_pct": max_dd * 100,
            "hit_rate_pct": hit_rate * 100,
        })

    out = pd.DataFrame(rows)
    out = out.sort_values(["convention", "strategy"])

    print("\n" + out.round(3).to_string(index=False))
    print()
    out.to_csv(PHASE2_SUMMARY_PATH, index=False)
    print(f"Summary saved to {PHASE2_SUMMARY_PATH}")
    return out


# ═══════════════════════════════════════════════════════════════════════
# Plotting
# ═══════════════════════════════════════════════════════════════════════

def plot_phase2(daily: pd.DataFrame) -> None:
    """4-panel: cumulative returns by convention; long_only vs long_short; drawdowns."""
    print("\nGenerating phase 2 plots...")

    daily_sorted = daily.sort_values("trade_date").copy()
    daily_sorted["trade_date_ts"] = pd.to_datetime(daily_sorted["trade_date"])

    # ─── Plot 1: cumulative returns, all strategies, both conventions ───
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    colors = {
        "q5_long":     "#1f77b4",
        "q1_short":    "#d62728",
        "long_short":  "#2ca02c",
        "universe_ew": "#888888",
    }
    labels = {
        "q5_long":     "Q5 long (low turnover)",
        "q1_short":    "Q1 short (high turnover)",
        "long_short":  "Long-short (Q5 - Q1)",
        "universe_ew": "Universe EW benchmark",
    }
    for ax, conv, title in zip(
        axes,
        ["c2c", "open_t1"],
        ["Close-to-close convention", "Open-T+1 convention"],
    ):
        sub_conv = daily_sorted[daily_sorted["convention"] == conv]
        for strat in ["q5_long", "q1_short", "long_short", "universe_ew"]:
            sub = sub_conv[sub_conv["strategy"] == strat]
            if len(sub) == 0:
                continue
            r = sub["daily_return"].fillna(0)
            cum = (1 + r).cumprod()
            ax.plot(sub["trade_date_ts"], cum,
                    label=labels[strat], color=colors[strat],
                    linewidth=1.5, alpha=0.9)
        ax.axvline(NEW_NINE_ARTICLES_DATE, color="firebrick",
                   linestyle="--", linewidth=1, alpha=0.5)
        ax.axvline(PBOC_STIMULUS_DATE, color="seagreen",
                   linestyle="--", linewidth=1, alpha=0.5)
        ax.set_title(title)
        ax.set_xlabel("Trade date")
        ax.set_ylabel("Cumulative return (×)" if ax == axes[0] else "")
        ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
        ax.grid(alpha=0.3)
    fig.suptitle("Turnover factor on Universe A: T+1 backtest",
                 fontsize=12, y=1.00)
    fig.tight_layout()
    fig.savefig(GRAPHS_DIR / "turnover_phase2_cumulative.png", dpi=120)
    plt.close(fig)

    # ─── Plot 2: long-only vs long-short, open_t1 only, with drawdown ───
    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(13, 8), sharex=True,
        gridspec_kw={"height_ratios": [2, 1]},
    )
    ot1 = daily_sorted[daily_sorted["convention"] == "open_t1"]

    for strat, color in [("q5_long", "#1f77b4"),
                          ("long_short", "#2ca02c"),
                          ("universe_ew", "#888888")]:
        sub = ot1[ot1["strategy"] == strat]
        if len(sub) == 0:
            continue
        r = sub["daily_return"].fillna(0)
        cum = (1 + r).cumprod()
        running_max = cum.cummax()
        dd = (cum / running_max - 1) * 100

        ax_top.plot(sub["trade_date_ts"], cum, label=labels[strat],
                    color=color, linewidth=1.5)
        ax_bot.plot(sub["trade_date_ts"], dd, label=labels[strat],
                    color=color, linewidth=1.2)
        ax_bot.fill_between(sub["trade_date_ts"], dd, 0,
                            color=color, alpha=0.15)

    for ax in (ax_top, ax_bot):
        ax.axvline(NEW_NINE_ARTICLES_DATE, color="firebrick",
                   linestyle="--", linewidth=1, alpha=0.5)
        ax.axvline(PBOC_STIMULUS_DATE, color="seagreen",
                   linestyle="--", linewidth=1, alpha=0.5)
        ax.grid(alpha=0.3)

    ax_top.set_title("Long-only Q5 vs long-short (Q5-Q1) vs benchmark "
                     "[open-T+1 convention]")
    ax_top.set_ylabel("Cumulative return (×)")
    ax_top.legend(loc="upper left", fontsize=10, framealpha=0.85)
    ax_bot.set_title("Drawdown")
    ax_bot.set_ylabel("Drawdown (%)")
    ax_bot.set_xlabel("Trade date")
    fig.tight_layout()
    fig.savefig(GRAPHS_DIR / "turnover_phase2_compare.png", dpi=120)
    plt.close(fig)

    print(f"  plots saved to {GRAPHS_DIR}/")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["phase1", "phase2", "both"])
    ap.add_argument("--start", type=str, default=None,
                    help="Start date for phase 2 (YYYY-MM-DD)")
    ap.add_argument("--end", type=str, default=None,
                    help="End date for phase 2 (YYYY-MM-DD)")
    args = ap.parse_args()

    panel = load_factor_panel()
    print(f"Loaded factor panel: {len(panel):,} rows, "
          f"{panel['rebalance_date'].nunique()} dates")

    if args.mode in ("phase1", "both"):
        run_phase1(panel)

    if args.mode in ("phase2", "both"):
        daily = run_phase2(panel, start_date=args.start, end_date=args.end)
        summarise_phase2(daily)
        plot_phase2(daily)

    print("\nDone.")


if __name__ == "__main__":
    main()
