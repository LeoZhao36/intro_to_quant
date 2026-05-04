"""
turnover_neutralized.py — residualize z_turnover on sector + size (+ beta).

Diagnostic question: how much of the turnover factor's apparent signal
disappears after controlling for sector composition, size, and beta?

Procedure
---------
1. Load factor_panel_a.parquet (built by build_factor_panel.py).
2. Attach sector_l1 from data/sw_l1_membership.parquet.
3. Compute trailing 60d beta vs CSI Total Return (000300.SH proxy or
   any benchmark in the daily panel) per stock, per rebalance date.
4. Run residualise_factor_per_date on raw mean_turnover_20d, with
   numeric controls = (log_mcap, beta_60d) and categorical = sector_l1.
5. Sign-flip: z_turnover_resid = -zscore(residual).
6. Re-run phase 1 (quintile sort, IC, bootstrap) on z_turnover_resid.
7. Re-run phase 2 (T+1 daily backtest) on residualized Q5/Q1 baskets,
   benchmark unchanged.
8. Print side-by-side comparison: raw turnover vs residualized turnover.

Two modes
---------
The script supports running with-beta and without-beta to assess
sensitivity to noisy beta estimates:

    python turnover_neutralized.py phase1                    # without beta
    python turnover_neutralized.py phase1 --with-beta        # include beta
    python turnover_neutralized.py both --with-beta --start 2024-04-12

Decision rule on beta
---------------------
Run both. If with-beta and without-beta produce qualitatively similar
results (Sharpe within ±0.1, IR within ±0.05), report the without-beta
version. If they differ meaningfully, investigate which estimate is
more reliable. Beta on thinly-traded sub-2B-circ_mv names has wide
standard errors; controlling for noisy beta can introduce more error
than it removes.

Prerequisites
-------------
  - data/factor_panel_a.parquet
  - data/sw_l1_membership.parquet (run fetch_sw_industry.py first)
  - daily_panel/daily_<DATE>.parquet for benchmark + universe stocks
  - Project_6/data/trading_calendar.csv

Output
------
  data/turnover_neutralized_phase1_summary.csv
  data/turnover_neutralized_phase2_daily_pnl.csv
  data/turnover_neutralized_phase2_summary.csv
  graphs/turnover_neutralized_phase2_compare.png
  graphs/turnover_raw_vs_neutralized.png  (overlay plot)
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
    residualise_factor_per_date,
    summarise_long_short,
)
from hypothesis_testing import block_bootstrap_ci
# Import fetch_sw_industry LAST among local modules. It does sys.path
# manipulation at import time to find tushare_setup at the repo root,
# which can shadow same-named local modules. Importing it last ensures
# all our other local modules are already cached in sys.modules.
from fetch_sw_industry import load_current_industry


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
GRAPHS_DIR.mkdir(exist_ok=True)

FACTOR_PANEL_PATH = DATA_DIR / "factor_panel_a.parquet"
PHASE1_OUT = DATA_DIR / "turnover_neutralized_phase1_summary.csv"
PHASE2_DAILY = DATA_DIR / "turnover_neutralized_phase2_daily_pnl.csv"
PHASE2_SUMMARY = DATA_DIR / "turnover_neutralized_phase2_summary.csv"
ERROR_LOG = DATA_DIR / "errors_turnover_neutralized.log"

COMPRESSION = "zstd"

# Backtest parameters (must match turnover_analysis.py for fair comparison)
N_QUINTILES = 5
WEEKLY_BLOCK_SIZE = 12
DAILY_BLOCK_SIZE = 20
SEED = 42
BOOT_N = 5000

# Beta computation
BETA_WINDOW = 60
BETA_MIN_OBS = 40
# Benchmark for beta computation: synthetic equal-weight of all A-share
# equities present in the daily panel on each date. Reasoning: our daily
# panel only contains stock data (Tushare pro.daily), not index data
# (which would be pro.index_daily). Rather than add a separate index fetch,
# we construct a broad-market proxy from what's already on disk. This is
# also more self-consistent: beta against "the rest of the A-share market"
# is what we want for residualization in this universe, not beta against
# a narrower index like CSI 1000 that may not match our universe scope.


_logger = logging.getLogger("turnover_neutralized")
_logger.setLevel(logging.WARNING)
if not _logger.handlers:
    _h = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _logger.addHandler(_h)


# ═══════════════════════════════════════════════════════════════════════
# Setup: load panel + attach sector + (optional) compute beta
# ═══════════════════════════════════════════════════════════════════════

def load_panel_with_sector() -> pd.DataFrame:
    """Load factor panel and merge in sector_l1 from SW membership."""
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
    print(f"SW L1 sector lookup: {len(sectors):,} stocks classified")

    panel = panel.merge(
        sectors[["ts_code", "industry_name"]], on="ts_code", how="left"
    )
    panel = panel.rename(columns={"industry_name": "sector_l1"})

    iu = panel[panel["in_universe"]]
    n_with_sector = int(iu["sector_l1"].notna().sum())
    print(f"  in_universe rows with sector: "
          f"{n_with_sector:,} of {len(iu):,} "
          f"({100*n_with_sector/len(iu):.1f}%)")
    n_unclassified = int(iu["sector_l1"].isna().sum())
    if n_unclassified > 0:
        print(f"  unclassified (most likely 北交所 or newly-listed): "
              f"{n_unclassified:,}")

    return panel


def compute_beta_per_rebalance(panel: pd.DataFrame) -> pd.DataFrame:
    """
    For each (rebalance_date, ts_code) in the panel, compute trailing 60d
    beta vs a synthetic universe-EW benchmark using the 60 trading days
    ending the day BEFORE the rebalance.

    Implementation
    --------------
    Vectorized pandas rolling cov/var instead of a per-stock per-rebalance
    Python loop. The math is identical:
      beta_at_rebalance_r = cov(stock_returns, bench_returns) /
                            var(bench_returns)
      computed over days [r-60, r-1].

    Pandas rolling on a wide returns DataFrame computes this for every
    stock simultaneously in C, then we slice to the trading day before
    each rebalance to recover the (rebal_date, ts_code) panel.

    Memory: peak ~1.5 GB for ~5000 stocks × ~1800 days. Fine on 8GB+.
    Runtime: ~20-40 sec after the daily-panel read, vs ~15 min for the
    previous Python-loop implementation.

    Benchmark construction: equal-weight return of all A-share equities
    in the daily panel on each date (excluding 北交所 BJ via the
    A_SHARE_PATTERN regex which only matches .SH and .SZ codes). This
    avoids any external data dependency and is self-consistent with
    the universe.
    """
    print(f"\nComputing trailing {BETA_WINDOW}d beta vs synthetic "
          f"A-share EW benchmark...")

    rebal_dates = sorted(panel["rebalance_date"].unique())
    cal = pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()
    cal_idx = {d: i for i, d in enumerate(cal)}

    needed_dates = set()
    for r in rebal_dates:
        if r not in cal_idx:
            continue
        end_idx = cal_idx[r]
        start_idx = max(0, end_idx - BETA_WINDOW)
        for d in cal[start_idx:end_idx]:
            needed_dates.add(d)
    needed_dates = sorted(needed_dates)
    print(f"  reading {len(needed_dates)} trading days of daily panels...")

    # First pass: read each daily panel, collect (date, ts_code, ret) rows
    # for downstream pivot, plus the synthetic EW benchmark for that date.
    bench_returns = []
    all_a_frames = []
    t0 = time.time()
    for i, d in enumerate(needed_dates, 1):
        path = DAILY_PANEL_DIR / f"daily_{d}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if "pct_chg" in df.columns:
            df["ret"] = pd.to_numeric(df["pct_chg"], errors="coerce") / 100
        else:
            close = pd.to_numeric(df["close"], errors="coerce")
            pre = pd.to_numeric(df["pre_close"], errors="coerce")
            df["ret"] = close / pre - 1

        a = df[df["ts_code"].str.match(A_SHARE_PATTERN)][["ts_code", "ret"]]
        a = a.dropna()

        if len(a) > 0:
            bench_returns.append((d, float(a["ret"].mean())))
            a_with_date = a.copy()
            a_with_date["date"] = d
            all_a_frames.append(a_with_date)

        if i % 200 == 0 or i == len(needed_dates):
            print(f"  [{i:>4}/{len(needed_dates)}] elapsed={time.time()-t0:.1f}s")

    if not all_a_frames:
        raise RuntimeError(
            "No A-share equity returns found in daily panels. "
            "Check that DAILY_PANEL_DIR contains valid daily_<DATE>.parquet "
            "files with A-share rows."
        )

    # Pivot to wide returns: rows=dates, cols=ts_codes
    print(f"\n  building wide returns panel...")
    t0 = time.time()
    all_long = pd.concat(all_a_frames, ignore_index=True)
    returns_wide = (
        all_long
        .pivot(index="date", columns="ts_code", values="ret")
        .sort_index()
    )
    print(f"    shape: {returns_wide.shape}  "
          f"({returns_wide.notna().sum().sum():,} non-NaN obs)  "
          f"elapsed: {time.time()-t0:.1f}s")

    # Bench series aligned to returns_wide index
    bench_df = (
        pd.DataFrame(bench_returns, columns=["date", "ret"])
        .set_index("date")
        .sort_index()
    )
    bench_series = bench_df["ret"].reindex(returns_wide.index)
    print(f"  synthetic benchmark daily returns: "
          f"{int(bench_series.notna().sum()):,} days, "
          f"mean={bench_series.mean()*100:+.3f}%, "
          f"std={bench_series.std()*100:.3f}%")

    # Vectorized rolling cov/var. Pandas .rolling().cov(other_series) on
    # a DataFrame returns per-column rolling cov against the series, in C.
    # Pairwise complete observations: for each (stock, bench) pair within
    # the window, only days where BOTH are non-NaN contribute. Stocks
    # with fewer than BETA_MIN_OBS overlapping non-NaN days get NaN beta.
    print(f"\n  computing rolling cov/var (vectorized)...")
    t0 = time.time()
    rolling_obj = returns_wide.rolling(
        window=BETA_WINDOW, min_periods=BETA_MIN_OBS,
    )
    cov_panel = rolling_obj.cov(bench_series)
    bench_var = bench_series.rolling(
        window=BETA_WINDOW, min_periods=BETA_MIN_OBS,
    ).var()
    # Guard against divide-by-zero when the benchmark has near-zero var
    # in a quiet window
    bench_var = bench_var.where(bench_var > 1e-10, np.nan)
    beta_panel_wide = cov_panel.div(bench_var, axis=0)
    print(f"    elapsed: {time.time()-t0:.1f}s")
    print(f"    beta panel shape: {beta_panel_wide.shape}  "
          f"({int(beta_panel_wide.notna().sum().sum()):,} non-NaN betas)")

    # For each rebalance r, look up beta_panel_wide on the trading day
    # immediately before r. That row gives beta computed over [r-60, r-1].
    print(f"\n  extracting beta at day-before-each-rebalance...")
    t0 = time.time()
    long_rows = []
    n_skipped = 0
    for r in rebal_dates:
        if r not in cal_idx:
            n_skipped += 1
            continue
        end_idx = cal_idx[r]
        if end_idx == 0:
            n_skipped += 1
            continue
        prev_day = cal[end_idx - 1]
        if prev_day not in beta_panel_wide.index:
            n_skipped += 1
            continue
        row = beta_panel_wide.loc[prev_day].dropna()
        if len(row) == 0:
            n_skipped += 1
            continue
        sub = pd.DataFrame({
            "rebalance_date": r,
            "ts_code": row.index,
            "beta_60d": row.values,
        })
        long_rows.append(sub)
    if n_skipped > 0:
        print(f"    skipped {n_skipped} rebalance dates "
              f"(missing prev-day beta)")
    beta_df = pd.concat(long_rows, ignore_index=True)
    print(f"    elapsed: {time.time()-t0:.1f}s")

    print(f"  beta panel: {len(beta_df):,} rows, "
          f"mean={beta_df['beta_60d'].mean():.2f}, "
          f"median={beta_df['beta_60d'].median():.2f}, "
          f"p5={beta_df['beta_60d'].quantile(0.05):.2f}, "
          f"p95={beta_df['beta_60d'].quantile(0.95):.2f}")

    # Winsorize beta at [0.5%, 99.5%] to clip extreme estimates from
    # thinly-traded stocks
    lo, hi = beta_df["beta_60d"].quantile([0.005, 0.995])
    beta_df["beta_60d"] = beta_df["beta_60d"].clip(lo, hi)

    return beta_df


# ═══════════════════════════════════════════════════════════════════════
# Phase 1: weekly factor research on z_turnover_resid
# ═══════════════════════════════════════════════════════════════════════

def add_z_turnover_resid(panel: pd.DataFrame, with_beta: bool) -> pd.DataFrame:
    """
    Build the residualized turnover factor.

    Steps:
      1. residualise_factor_per_date(mean_turnover_20d, controls=(...))
         to produce raw_turnover_resid.
      2. cross_sectional_zscore on raw_turnover_resid -> z_turn_resid_raw
      3. Sign-flip: z_turnover_resid = -z_turn_resid_raw
         (high z = LOW residualized turnover = predicted to outperform)
    """
    print(f"\nResidualizing mean_turnover_20d on "
          f"sector_l1 + log_mcap{' + beta_60d' if with_beta else ''}...")

    numeric_controls = ["log_mcap"]
    if with_beta:
        numeric_controls.append("beta_60d")

    panel = residualise_factor_per_date(
        panel,
        factor_col="mean_turnover_20d",
        out_col="turnover_resid",
        numeric_controls=numeric_controls,
        categorical_control="sector_l1",
    )

    # Standardize residual cross-sectionally
    panel = cross_sectional_zscore(
        panel, factor_col="turnover_resid", out_col="z_turn_resid_raw",
    )
    panel["z_turnover_resid"] = -panel["z_turn_resid_raw"]

    return panel


def run_phase1(panel: pd.DataFrame, with_beta: bool) -> dict:
    print("\n" + "=" * 76)
    print(f"PHASE 1: residualized turnover factor (with_beta={with_beta})")
    print("=" * 76)

    panel = add_z_turnover_resid(panel, with_beta=with_beta)

    iu = panel[panel["in_universe"]]
    n_with = int(iu["z_turnover_resid"].notna().sum())
    print(f"\n  in_universe rows with z_turnover_resid: "
          f"{n_with:,} of {len(iu):,} ({100*n_with/len(iu):.1f}%)")

    # Quintile sort
    print(f"\n  --- Quintile sort on z_turnover_resid ---")
    qr = compute_quintile_series(panel, sort_col="z_turnover_resid")
    for q in range(5):
        if q in qr.columns:
            mean = qr[q].mean() * 100
            print(f"    Q{q+1}: {mean:+.3f}%/wk")

    summary = summarise_long_short(qr, "Q5 - Q1 (residualized)")

    if summary.get("n", 0) >= 2 * WEEKLY_BLOCK_SIZE:
        boot = block_bootstrap_ci(
            summary["ls_series"].values, np.mean,
            block_size=WEEKLY_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
        )
        print(f"\n  Block bootstrap CI on Q5-Q1 mean "
              f"(block_size={WEEKLY_BLOCK_SIZE}w):")
        print(f"    estimate: {boot['estimate']*100:+.3f}%/wk")
        print(f"    95% CI:   [{boot['ci_low']*100:+.3f}%, "
              f"{boot['ci_high']*100:+.3f}%]")
        print(f"    excludes zero: "
              f"{(boot['ci_low']>0) or (boot['ci_high']<0)}")
        summary["bootstrap_q1q5"] = boot

    print(f"\n  --- Cross-sectional Spearman IC ---")
    ic = compute_ic_series(panel, sort_col="z_turnover_resid")
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
    summary["panel"] = panel  # for downstream phase 2

    # Save
    rows = [{
        "metric": "Q5_minus_Q1_resid",
        "with_beta": with_beta,
        "n_periods": summary.get("n"),
        "mean_pct_wk": summary.get("mean_period", 0) * 100,
        "t_stat": summary.get("t_stat"),
        "naive_sharpe": summary.get("naive_sharpe"),
        "ci_low_pct_wk": summary.get("bootstrap_q1q5", {}).get("ci_low", np.nan) * 100,
        "ci_high_pct_wk": summary.get("bootstrap_q1q5", {}).get("ci_high", np.nan) * 100,
    }, {
        "metric": "ic_mean_resid",
        "with_beta": with_beta,
        "n_periods": int(len(ic)),
        "mean_pct_wk": float(ic.mean()),
        "t_stat": float(ic.mean() / (ic.std() / np.sqrt(len(ic)))) if len(ic) else np.nan,
        "naive_sharpe": np.nan,
        "ci_low_pct_wk": summary.get("bootstrap_ic", {}).get("ci_low", np.nan),
        "ci_high_pct_wk": summary.get("bootstrap_ic", {}).get("ci_high", np.nan),
    }]
    pd.DataFrame(rows).to_csv(PHASE1_OUT, index=False)
    print(f"\nPhase 1 summary saved to {PHASE1_OUT}")

    return summary


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: T+1 daily backtest on residualized baskets
#
# Implementation note: this re-uses the same logic as turnover_analysis.py
# phase 2 but with z_turnover_resid as the sort column.
# ═══════════════════════════════════════════════════════════════════════

def _read_daily_prices(date_str: str) -> pd.DataFrame | None:
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


def _build_baskets_from_residual(panel: pd.DataFrame) -> dict:
    """Quintile baskets on z_turnover_resid."""
    iu = panel[panel["in_universe"]].copy()
    iu = iu.dropna(subset=["z_turnover_resid"])
    iu["quintile"] = iu.groupby("rebalance_date")["z_turnover_resid"].transform(
        lambda s: pd.qcut(s, N_QUINTILES, labels=False, duplicates="drop")
    )
    baskets = {}
    for date, g in iu.groupby("rebalance_date"):
        baskets[date] = {
            "q5": set(g.loc[g["quintile"] == 4, "ts_code"]),
            "q1": set(g.loc[g["quintile"] == 0, "ts_code"]),
            "universe": set(g["ts_code"]),
        }
    return baskets


def _basket_for_date(trade_date, rebal_dates_sorted, baskets):
    import bisect
    idx = bisect.bisect_right(rebal_dates_sorted, trade_date) - 1
    if idx < 0:
        return None
    return baskets[rebal_dates_sorted[idx]]


def run_phase2(panel: pd.DataFrame, start_date=None, end_date=None) -> pd.DataFrame:
    print("\n" + "=" * 76)
    print("PHASE 2: T+1 daily backtest on residualized baskets")
    print("=" * 76)

    print("\nBuilding baskets on z_turnover_resid...")
    baskets = _build_baskets_from_residual(panel)
    rebal_dates_sorted = sorted(baskets.keys())
    print(f"  {len(rebal_dates_sorted)} rebalance dates with valid baskets")
    q5_sizes = [len(baskets[d]["q5"]) for d in rebal_dates_sorted]
    q1_sizes = [len(baskets[d]["q1"]) for d in rebal_dates_sorted]
    print(f"  Q5 size: median {int(np.median(q5_sizes))}, "
          f"min {min(q5_sizes)}, max {max(q5_sizes)}")
    print(f"  Q1 size: median {int(np.median(q1_sizes))}, "
          f"min {min(q1_sizes)}, max {max(q1_sizes)}")

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

    first_day_of_period = {}
    for r in rebal_dates_sorted:
        if r not in cal:
            continue
        ridx = cal.index(r)
        if ridx + 1 < len(cal):
            first_day_of_period[cal[ridx + 1]] = True

    print(f"\nIterating over trading days...")
    rows = []
    n_failed = 0
    t0 = time.time()
    prev_prices = None

    for i, td in enumerate(trade_dates, 1):
        prices = _read_daily_prices(td)
        if prices is None:
            n_failed += 1
            prev_prices = None
            continue
        basket = _basket_for_date(td, rebal_dates_sorted, baskets)
        if basket is None:
            prev_prices = prices
            continue
        is_first = first_day_of_period.get(td, False)

        for strat, members, sign in [
            ("q5_long", basket["q5"], +1),
            ("q1_short", basket["q1"], -1),
            ("universe_ew", basket["universe"], +1),
        ]:
            if not members:
                continue
            present = prices.index.intersection(members)
            if len(present) == 0:
                continue
            sub = prices.loc[present]

            # c2c
            if prev_prices is not None:
                pp = prev_prices.index.intersection(present)
                if len(pp) > 0:
                    p_prev = prev_prices.loc[pp, "adj_close"]
                    p_curr = sub.loc[pp, "adj_close"]
                    ret = (p_curr / p_prev - 1).mean() * sign
                    rows.append({
                        "trade_date": td, "strategy": strat,
                        "convention": "c2c", "daily_return": float(ret),
                        "n_held": int(len(pp)),
                    })

            # open_t1
            if "adj_open" in sub.columns:
                if is_first:
                    valid = sub["adj_open"].notna() & (sub["adj_open"] > 0)
                    if valid.sum() > 0:
                        sv = sub[valid]
                        ret = (sv["adj_close"] / sv["adj_open"] - 1).mean() * sign
                        rows.append({
                            "trade_date": td, "strategy": strat,
                            "convention": "open_t1", "daily_return": float(ret),
                            "n_held": int(valid.sum()),
                        })
                else:
                    if prev_prices is not None:
                        pp = prev_prices.index.intersection(present)
                        if len(pp) > 0:
                            p_prev = prev_prices.loc[pp, "adj_close"]
                            p_curr = sub.loc[pp, "adj_close"]
                            ret = (p_curr / p_prev - 1).mean() * sign
                            rows.append({
                                "trade_date": td, "strategy": strat,
                                "convention": "open_t1", "daily_return": float(ret),
                                "n_held": int(len(pp)),
                            })
        prev_prices = prices

        if i % 200 == 0 or i == len(trade_dates):
            print(f"  [{i:>4}/{len(trade_dates)}] failed={n_failed} "
                  f"rows={len(rows):,} elapsed={time.time()-t0:.1f}s")

    daily = pd.DataFrame(rows)
    pivot = daily.pivot_table(
        index=["trade_date", "convention"], columns="strategy",
        values="daily_return",
    ).reset_index()
    if "q5_long" in pivot.columns and "q1_short" in pivot.columns:
        pivot["long_short"] = 0.5 * pivot["q5_long"] + 0.5 * pivot["q1_short"]
    long_format = pivot.melt(
        id_vars=["trade_date", "convention"],
        value_vars=[c for c in pivot.columns
                    if c not in ("trade_date", "convention")],
        var_name="strategy", value_name="daily_return",
    ).dropna(subset=["daily_return"])

    long_format.to_csv(PHASE2_DAILY, index=False)
    print(f"\nDaily P&L: {len(long_format):,} rows, saved to {PHASE2_DAILY}")
    return long_format


def summarise_phase2(daily: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 76)
    print("PHASE 2 SUMMARY: residualized")
    print("=" * 76)
    rows = []
    for (strat, conv), g in daily.groupby(["strategy", "convention"]):
        r = g.sort_values("trade_date")["daily_return"].dropna()
        n = len(r)
        if n == 0:
            continue
        cum = (1 + r).cumprod()
        years = n / TRADING_DAYS_PER_YEAR
        ann_ret = cum.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
        std = r.std()
        sharpe = r.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR) if std > 0 else np.nan
        running_max = cum.cummax()
        max_dd = (cum / running_max - 1).min()
        hit = (r > 0).mean()

        if n >= 2 * DAILY_BLOCK_SIZE:
            def _sh(a):
                m, s = a.mean(), a.std()
                return m / s * np.sqrt(TRADING_DAYS_PER_YEAR) if s > 0 else np.nan
            boot = block_bootstrap_ci(
                r.values, _sh, block_size=DAILY_BLOCK_SIZE,
                n_boot=BOOT_N, seed=SEED,
            )
            ci_low, ci_high = boot["ci_low"], boot["ci_high"]
        else:
            ci_low = ci_high = np.nan

        rows.append({
            "strategy": strat, "convention": conv, "n_days": n,
            "ann_return_pct": ann_ret * 100,
            "ann_vol_pct": std * np.sqrt(TRADING_DAYS_PER_YEAR) * 100,
            "sharpe": sharpe,
            "sharpe_ci_low": ci_low, "sharpe_ci_high": ci_high,
            "cumulative_return_pct": (cum.iloc[-1] - 1) * 100,
            "max_drawdown_pct": max_dd * 100,
            "hit_rate_pct": hit * 100,
        })

    out = pd.DataFrame(rows).sort_values(["convention", "strategy"])
    print("\n" + out.round(3).to_string(index=False))
    out.to_csv(PHASE2_SUMMARY, index=False)
    print(f"\nSaved to {PHASE2_SUMMARY}")
    return out


# ═══════════════════════════════════════════════════════════════════════
# Comparison plot: raw vs residualized
# ═══════════════════════════════════════════════════════════════════════

def plot_comparison(daily_resid: pd.DataFrame) -> None:
    """Overlay raw turnover Q5 vs residualized Q5 vs benchmark."""
    raw_path = DATA_DIR / "turnover_phase2_daily_pnl.csv"
    if not raw_path.exists():
        print(f"  (skipping comparison plot: {raw_path} not found)")
        return

    raw = pd.read_csv(raw_path)
    # Defensive type coercion. On some pandas+pyarrow setups, daily_return
    # gets inferred as string from CSV; force numeric here. Errors='coerce'
    # turns unparseable cells into NaN rather than blowing up.
    raw["daily_return"] = pd.to_numeric(raw["daily_return"], errors="coerce")
    raw["trade_date_ts"] = pd.to_datetime(raw["trade_date"].astype(str))

    daily_resid = daily_resid.copy()
    daily_resid["daily_return"] = pd.to_numeric(
        daily_resid["daily_return"], errors="coerce"
    )
    daily_resid["trade_date_ts"] = pd.to_datetime(
        daily_resid["trade_date"].astype(str)
    )

    fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    for ax, conv, title in zip(
        axes, ["c2c", "open_t1"],
        ["Close-to-close", "Open-T+1"],
    ):
        # Raw Q5
        rsub = raw[(raw["convention"] == conv) & (raw["strategy"] == "q5_long")]
        if len(rsub):
            r = rsub.sort_values("trade_date_ts")
            cum = (1 + r["daily_return"].fillna(0)).cumprod()
            ax.plot(r["trade_date_ts"], cum, label="Q5 raw turnover",
                    color="#1f77b4", linewidth=1.5)

        # Residualized Q5
        nsub = daily_resid[(daily_resid["convention"] == conv) &
                           (daily_resid["strategy"] == "q5_long")]
        if len(nsub):
            n = nsub.sort_values("trade_date_ts")
            cum = (1 + n["daily_return"].fillna(0)).cumprod()
            ax.plot(n["trade_date_ts"], cum, label="Q5 residualized",
                    color="#ff7f0e", linewidth=1.5)

        # Benchmark
        bsub = raw[(raw["convention"] == conv) & (raw["strategy"] == "universe_ew")]
        if len(bsub):
            b = bsub.sort_values("trade_date_ts")
            cum = (1 + b["daily_return"].fillna(0)).cumprod()
            ax.plot(b["trade_date_ts"], cum, label="Universe EW",
                    color="#888888", linewidth=1.2, linestyle="--")

        ax.axvline(NEW_NINE_ARTICLES_DATE, color="firebrick",
                   linestyle="--", alpha=0.4)
        ax.axvline(PBOC_STIMULUS_DATE, color="seagreen",
                   linestyle="--", alpha=0.4)
        ax.set_title(title)
        ax.set_xlabel("Trade date")
        ax.set_ylabel("Cumulative return (×)" if ax == axes[0] else "")
        ax.legend(loc="upper left", fontsize=10)
        ax.grid(alpha=0.3)

    fig.suptitle("Turnover factor: raw vs sector+size-residualized", y=1.00)
    fig.tight_layout()
    out = GRAPHS_DIR / "turnover_raw_vs_neutralized.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"  comparison plot saved to {out}")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["phase1", "phase2", "both"])
    ap.add_argument("--with-beta", action="store_true",
                    help="Include beta_60d as a control regressor")
    ap.add_argument("--start", type=str, default=None)
    ap.add_argument("--end", type=str, default=None)
    args = ap.parse_args()

    panel = load_panel_with_sector()

    if args.with_beta:
        beta_df = compute_beta_per_rebalance(panel)
        panel = panel.merge(
            beta_df, on=["rebalance_date", "ts_code"], how="left"
        )
        beta_cov = panel[panel["in_universe"]]["beta_60d"].notna().mean() * 100
        print(f"  beta_60d coverage on in_universe rows: {beta_cov:.1f}%")

    if args.mode in ("phase1", "both"):
        summary = run_phase1(panel, with_beta=args.with_beta)
        # Pass the residualized panel forward so phase 2 doesn't redo it
        panel = summary["panel"]

    if args.mode in ("phase2", "both"):
        # If we're running phase 2 standalone (without phase 1 first),
        # we need to compute the residual ourselves
        if "z_turnover_resid" not in panel.columns:
            panel = add_z_turnover_resid(panel, with_beta=args.with_beta)
        daily = run_phase2(panel, start_date=args.start, end_date=args.end)
        summarise_phase2(daily)
        plot_comparison(daily)

    print("\nDone.")


if __name__ == "__main__":
    main()