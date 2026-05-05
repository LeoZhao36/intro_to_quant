"""
top_n_filtered.py — Stage 1 of the deployable top-N prototype.

Adds two filters to the naive concentration sweep:

  1. Liquidity floor: candidates must have rebalance-day amount_yi ≥ 0.5
     (5000万 RMB ≈ 50M RMB). Drops illiquid micro-caps that would have
     execution drift at retail position sizes.

  2. Sector cap: no single SW L1 industry exceeds 20% of the basket.
     At N=20 this means max 4 names per sector (forces ≥5 sectors).
     At N=50 max 10 per sector. At N=100 max 20 per sector.

Tests three variants per N:
  - unfiltered:     reproduces concentration_sweep results
  - liq_only:       liquidity floor alone
  - full_filtered:  liquidity floor + sector cap (the Stage 1 deployable)

Dual benchmark
--------------
Each strategy is evaluated against TWO benchmarks:
  - 'broad':  in_universe equal-weight (no filters applied to benchmark)
  - 'liquid': in_universe ∩ liquidity-floor equal-weight (matched filter)

Vs broad universe answers "how does the strategy compare to holding the
whole small-cap universe equal-weight?" Includes any tilt benefit from
filtering toward liquid names (rotation alpha).

Vs liquid universe answers "how does the strategy compare to holding the
liquid sub-universe equal-weight?" Isolates factor contribution beyond
the rotation. Cleaner attribution for evaluating whether the factor
itself adds value or whether the IR is just from being in liquid names.

For deployment, broad-vs is the relevant metric since you ARE holding
liquid stocks unconditionally; rotation alpha is captured for free.
For factor attribution, liquid-vs is the metric.

Why three variants
------------------
Decomposes which filter contributes IR. If liq_only ≈ unfiltered,
illiquidity is not the binding problem. If full_filtered is much
better than liq_only, sector cap is doing the work.

Sector cap implementation
-------------------------
Equivalent to greedy top-down with per-sector counter, but vectorized.
For each rebalance date:
  1. Apply liquidity floor and drop NaN sector
  2. Per sector, take the top max_per_sector names by score
  3. From the union of those candidates, take top N by score
This produces the same result as walking the global sorted list and
skipping names whose sector is already at cap.

Liquidity floor caveat
----------------------
Uses single-day amount on the rebalance Wednesday, not a trailing
average. A stock that had a quiet Wednesday but is normally liquid would
be excluded. Trailing-60d would be more rigorous; cheap to add later.
For now this is conservative, which is the right side to err on.

Cost model unchanged at 0.18% roundtrip × churn. Note this overstates
retail cost by ~0.04% per roundtrip; results understate deployable IR
by ~0.05-0.10 in absolute terms.

Usage
-----
    python top_n_filtered.py run
    python top_n_filtered.py status
"""

import argparse
import bisect
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
    COST_PER_ROUNDTRIP,
    _basket_for_date,
    _read_daily_prices,
    compute_basket_churn,
)
from concentration_sweep import (
    BOOT_N,
    DAILY_BLOCK_SIZE,
    SEED,
    compute_basket_diagnostics,
)
from turnover_neutralized import load_panel_with_sector, add_z_turnover_resid


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
GRAPHS_DIR.mkdir(exist_ok=True)

SUMMARY_OUT = DATA_DIR / "top_n_filtered_summary.csv"
DIAG_OUT = DATA_DIR / "top_n_filtered_basket_diagnostics.csv"
PLOT_OUT = GRAPHS_DIR / "top_n_filtered_comparison.png"

TOP_N_VALUES = [20, 50, 100, 200, 500, 700]
SCORE_COL = "z_turnover_resid"
SECTOR_COL = "sector_l1"

# Filter parameters
MAX_SECTOR_PCT = 0.20
LIQUIDITY_FLOOR_YI = 0.5  # 5000万 RMB; amount_yi is in 亿元

# (variant_name, liq_floor, sec_cap_pct)
VARIANTS = [
    ("unfiltered",    None,                None),
    ("liq_only",      LIQUIDITY_FLOOR_YI,  None),
    ("full_filtered", LIQUIDITY_FLOOR_YI,  MAX_SECTOR_PCT),
]


# ═══════════════════════════════════════════════════════════════════════
# Capped basket builder
# ═══════════════════════════════════════════════════════════════════════

def build_capped_top_n_baskets(
    panel: pd.DataFrame,
    score_col: str,
    n: int,
    sector_col: str = SECTOR_COL,
    max_sector_pct: float | None = None,
    amount_floor_yi: float | None = None,
):
    """
    Build top-N baskets with optional liquidity and sector cap filters.

    Each basket entry has three sets:
      - top_n:           the strategy basket (filtered, capped, top N by score)
      - universe:        broad in-universe set (BEFORE liquidity filter)
                          → use for vs-broad benchmark
      - liquid_universe: in-universe set AFTER liquidity filter, BEFORE
                          sector cap → use for vs-liquid benchmark
                          (identical to broad if no liquidity filter applied)

    Why two universes
    -----------------
    Vs-broad universe answers "how does the strategy compare to holding
    the whole small-cap universe equal-weight?" This includes any tilt
    benefit from filtering toward liquid names (rotation alpha).

    Vs-liquid universe answers "how does the strategy compare to holding
    the liquid sub-universe equal-weight?" This isolates the factor's
    contribution beyond the rotation, since the benchmark is already
    liquidity-matched. Cleaner attribution.
    """
    iu_mask = panel["in_universe"]
    iu = panel[iu_mask].copy()
    iu = iu.dropna(subset=[score_col])

    # Broad universe: in_universe + valid score, BEFORE liquidity filter.
    universe_per_date_broad = (
        iu.groupby("rebalance_date")["ts_code"].apply(set).to_dict()
    )

    n_dropped_by_liq = 0
    if amount_floor_yi is not None:
        if "amount_yi" not in iu.columns:
            raise ValueError("amount_yi column not found in panel")
        before = len(iu)
        iu = iu[iu["amount_yi"] >= amount_floor_yi]
        n_dropped_by_liq = before - len(iu)
        # Liquid universe: AFTER liquidity filter, BEFORE sector cap.
        universe_per_date_liquid = (
            iu.groupby("rebalance_date")["ts_code"].apply(set).to_dict()
        )
    else:
        # No liquidity filter: liquid_universe identical to broad.
        universe_per_date_liquid = universe_per_date_broad

    apply_sector_cap = max_sector_pct is not None
    max_per_sector = (
        max(1, int(np.floor(n * max_sector_pct)))
        if apply_sector_cap else None
    )
    if apply_sector_cap:
        iu = iu.dropna(subset=[sector_col])

    baskets = {}
    chosen_sizes = []
    for date, g in iu.groupby("rebalance_date"):
        if len(g) == 0:
            baskets[date] = {
                "top_n": set(),
                "universe": universe_per_date_broad.get(date, set()),
                "liquid_universe": universe_per_date_liquid.get(date, set()),
            }
            chosen_sizes.append(0)
            continue

        if apply_sector_cap:
            # Per-sector top-K, then global top-N
            candidates = (
                g.groupby(sector_col, group_keys=False)
                .apply(lambda s: s.nlargest(max_per_sector, score_col))
            )
            chosen = candidates.nlargest(n, score_col)
        else:
            chosen = g.nlargest(n, score_col)

        baskets[date] = {
            "top_n": set(chosen["ts_code"]),
            "universe": universe_per_date_broad.get(date, set()),
            "liquid_universe": universe_per_date_liquid.get(date, set()),
        }
        chosen_sizes.append(len(chosen))

    return baskets, chosen_sizes, n_dropped_by_liq


# ═══════════════════════════════════════════════════════════════════════
# Local backtest with arbitrary basket benchmarks
# ═══════════════════════════════════════════════════════════════════════

def run_top_n_backtest_with_liq_benchmark(
    baskets: dict,
    label: str,
    cal: list[str],
) -> pd.DataFrame:
    """
    Like combination_analysis.run_top_n_backtest but iterates over all
    keys in basket dict rather than hardcoding ('top_n', 'universe').
    Treats anything not named 'top_n' as a costless benchmark.

    Daily P&L written to data/top_n_filtered_daily_<label>.csv with rows
    for every (trade_date, strategy, convention) combination including
    liquid_universe.
    """
    rebal_dates_sorted = sorted(baskets.keys())
    first_idx = cal.index(rebal_dates_sorted[0]) + 1
    last_idx = min(cal.index(rebal_dates_sorted[-1]) + 5, len(cal) - 1)
    trade_dates = cal[first_idx:last_idx + 1]

    first_day_of_period = {}
    for r in rebal_dates_sorted:
        if r in cal:
            ridx = cal.index(r)
            if ridx + 1 < len(cal):
                first_day_of_period[cal[ridx + 1]] = True

    churn_series = compute_basket_churn(baskets)

    print(f"\n  [{label}] backtest with broad + liquid benchmarks: "
          f"{trade_dates[0]} → {trade_dates[-1]} "
          f"({len(trade_dates)} days)")

    rows = []
    prev_prices = None
    n_failed = 0
    t0 = time.time()
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

        idx = bisect.bisect_right(rebal_dates_sorted, td) - 1
        rebal_date = rebal_dates_sorted[idx] if idx >= 0 else None
        cost_today = 0.0
        if is_first and rebal_date is not None:
            cost_today = (
                float(churn_series.get(rebal_date, 0.0))
                * COST_PER_ROUNDTRIP
            )

        # Iterate over EVERY key in basket dict. Cost only on top_n.
        for strat, members in basket.items():
            if not members:
                continue
            present = prices.index.intersection(members)
            if len(present) == 0:
                continue
            sub = prices.loc[present]
            cost_for_strat = cost_today if strat == "top_n" else 0.0

            # c2c
            if prev_prices is not None:
                pp = prev_prices.index.intersection(present)
                if len(pp) > 0:
                    p_prev = prev_prices.loc[pp, "adj_close"]
                    p_curr = sub.loc[pp, "adj_close"]
                    ret = float((p_curr / p_prev - 1).mean())
                    rows.append({
                        "trade_date": td, "strategy": strat,
                        "convention": "c2c",
                        "daily_return_gross": ret,
                        "daily_return_net": ret - cost_for_strat,
                        "n_held": int(len(pp)),
                        "is_entry_day": is_first,
                    })

            # open_t1
            if "adj_open" in sub.columns:
                if is_first:
                    valid = sub["adj_open"].notna() & (sub["adj_open"] > 0)
                    if valid.sum() > 0:
                        sv = sub[valid]
                        ret = float(
                            (sv["adj_close"] / sv["adj_open"] - 1).mean()
                        )
                        rows.append({
                            "trade_date": td, "strategy": strat,
                            "convention": "open_t1",
                            "daily_return_gross": ret,
                            "daily_return_net": ret - cost_for_strat,
                            "n_held": int(valid.sum()),
                            "is_entry_day": True,
                        })
                else:
                    if prev_prices is not None:
                        pp = prev_prices.index.intersection(present)
                        if len(pp) > 0:
                            p_prev = prev_prices.loc[pp, "adj_close"]
                            p_curr = sub.loc[pp, "adj_close"]
                            ret = float((p_curr / p_prev - 1).mean())
                            rows.append({
                                "trade_date": td, "strategy": strat,
                                "convention": "open_t1",
                                "daily_return_gross": ret,
                                "daily_return_net": ret,
                                "n_held": int(len(pp)),
                                "is_entry_day": False,
                            })
        prev_prices = prices

        if i % 200 == 0 or i == len(trade_dates):
            print(f"    [{i:>4}/{len(trade_dates)}] failed={n_failed} "
                  f"elapsed={time.time()-t0:.1f}s")

    daily = pd.DataFrame(rows)
    daily["label"] = label
    daily_path = DATA_DIR / f"top_n_filtered_daily_{label}.csv"
    daily.to_csv(daily_path, index=False)
    print(f"  saved daily P&L (top_n + universe + liquid_universe) to "
          f"{daily_path}")
    return daily


# ═══════════════════════════════════════════════════════════════════════
# Dual-benchmark summarise
# ═══════════════════════════════════════════════════════════════════════

def summarise_with_two_benchmarks(
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
    Compute summary stats for top_n vs both 'universe' (broad) and
    'liquid_universe' benchmarks. Each (regime, n_top, conv, ret_kind)
    produces 2 rows tagged by `benchmark` column ∈ {'broad', 'liquid'}.

    Top-N path-based stats (Sharpe, Sortino, max DD) are benchmark-
    independent; we compute once and emit the same value on both rows.
    """
    rows = []
    sub_daily = daily[
        (daily["trade_date"] >= start) & (daily["trade_date"] <= end)
    ]

    benchmark_strats = [("broad", "universe"), ("liquid", "liquid_universe")]

    for conv in ("c2c", "open_t1"):
        g_conv = sub_daily[sub_daily["convention"] == conv]
        if len(g_conv) == 0:
            continue
        for ret_kind in ("gross", "net"):
            ret_col = f"daily_return_{ret_kind}"
            wide = g_conv.pivot_table(
                index="trade_date", columns="strategy", values=ret_col,
            )
            if "top_n" not in wide.columns:
                continue
            tn_full = wide["top_n"].dropna()
            if len(tn_full) < 20:
                continue

            # Path stats on top_n alone (don't depend on benchmark)
            n_days = len(tn_full)
            ann_ret_tn = (1 + tn_full).prod() ** (
                TRADING_DAYS_PER_YEAR / n_days
            ) - 1
            sharpe_tn = (
                tn_full.mean() / tn_full.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
                if tn_full.std() > 0 else np.nan
            )
            tn_neg = tn_full[tn_full < 0]
            downside_std = tn_neg.std() if len(tn_neg) > 1 else np.nan
            sortino = (
                tn_full.mean() / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR)
                if downside_std and downside_std > 0 else np.nan
            )
            cum = (1 + tn_full).cumprod()
            max_dd = (cum / cum.cummax() - 1).min()

            # Per-benchmark stats
            for bench_tag, bench_col in benchmark_strats:
                if bench_col not in wide.columns:
                    continue
                ts = wide[["top_n", bench_col]].dropna()
                if len(ts) < 20:
                    continue
                tn = ts["top_n"]
                bn = ts[bench_col]
                active = tn - bn

                ann_active = active.mean() * TRADING_DAYS_PER_YEAR
                ann_te = active.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
                ir = (
                    active.mean() / active.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
                    if active.std() > 0 else np.nan
                )
                if len(active) >= 2 * DAILY_BLOCK_SIZE:
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

                month_active = active.copy()
                month_active.index = pd.to_datetime(month_active.index)
                monthly = month_active.resample("ME").sum()
                hit_rate = (
                    float((monthly > 0).mean()) if len(monthly) else np.nan
                )

                week_active = active.copy()
                week_active.index = pd.to_datetime(week_active.index)
                weekly = week_active.resample("W").sum()
                worst_week = (
                    float(weekly.min()) if len(weekly) else np.nan
                )

                ann_ret_bench = (1 + bn).prod() ** (
                    TRADING_DAYS_PER_YEAR / len(bn)
                ) - 1

                rows.append({
                    "regime": regime_label,
                    "n_top": n_top,
                    "label": label,
                    "convention": conv,
                    "ret_kind": ret_kind,
                    "benchmark": bench_tag,
                    "n_days": len(ts),
                    "ann_ret_top_n_pct": ann_ret_tn * 100,
                    "ann_ret_benchmark_pct": ann_ret_bench * 100,
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
    print(f"TOP-N WITH FILTERS, on {SCORE_COL}")
    print(f"  N values: {TOP_N_VALUES}")
    print(f"  Liquidity floor: amount_yi >= {LIQUIDITY_FLOOR_YI} 亿元")
    print(f"  Sector cap: {MAX_SECTOR_PCT*100:.0f}% per SW L1 industry")
    print("=" * 76)

    for n in TOP_N_VALUES:
        for variant_name, liq_floor, sec_cap in VARIANTS:
            print(f"\n{'─' * 76}")
            print(f"  TOP-{n} | variant={variant_name}")
            print(f"{'─' * 76}")

            baskets, sizes, n_dropped = build_capped_top_n_baskets(
                panel, SCORE_COL, n,
                max_sector_pct=sec_cap,
                amount_floor_yi=liq_floor,
            )

            print(f"  basket sizes: median={int(np.median(sizes))}, "
                  f"min={min(sizes)}, max={max(sizes)}")
            if n_dropped > 0:
                print(f"  liquidity floor dropped {n_dropped:,} "
                      f"candidate-rows")

            bd = compute_basket_diagnostics(panel, baskets)
            bd["n_top"] = n
            bd["variant"] = variant_name
            diag_rows.append(bd)

            if len(bd) > 0:
                print(f"  basket diagnostics:")
                print(f"    median max_sector_pct: "
                      f"{bd['max_sector_pct'].median()*100:.1f}%")
                print(f"    median n_unique_sectors: "
                      f"{int(bd['n_unique_sectors'].median())}")

            label = f"top_{n}_{variant_name}"
            daily = run_top_n_backtest_with_liq_benchmark(baskets, label, cal)

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

                bd_dates_ts = pd.to_datetime(bd["rebalance_date"])
                mask_bd = (
                    (bd_dates_ts >= pd.to_datetime(start))
                    & (bd_dates_ts <= pd.to_datetime(end))
                )
                bd_filtered = bd[mask_bd]

                sub = summarise_with_two_benchmarks(
                    daily, label, regime_label, start_str, end_str,
                    churn_mean, bd_filtered, n,
                )
                sub["variant"] = variant_name
                summary_rows.append(sub)

    summary_df = pd.concat(summary_rows, ignore_index=True)
    summary_df.to_csv(SUMMARY_OUT, index=False)

    diag_df = pd.concat(diag_rows, ignore_index=True)
    diag_df.to_csv(DIAG_OUT, index=False)

    # Pivot views (γ first, since deployment regime). Now we have two
    # benchmarks: 'broad' (vs in_universe-EW, current convention) and
    # 'liquid' (vs in_universe ∩ liquidity-floor-EW, the cleaner attribution).
    head = summary_df[
        (summary_df["convention"] == "open_t1")
        & (summary_df["ret_kind"] == "net")
    ].copy()
    variant_order = [v[0] for v in VARIANTS]

    for bench_tag in ("broad", "liquid"):
        head_b = head[head["benchmark"] == bench_tag]
        print("\n" + "=" * 76)
        print(f"NET OPEN_T1 IR vs {bench_tag.upper()} BENCHMARK"
              f" by regime × variant × N")
        print("=" * 76)
        for regime in ["gamma_post_NNA", "beta_pre_NNA", "alpha_all"]:
            print(f"\n  {regime}:")
            sub = head_b[head_b["regime"] == regime]
            piv = sub.pivot(
                index="variant", columns="n_top", values="ir"
            ).round(3)
            piv = piv[TOP_N_VALUES].reindex(variant_order)
            print(piv.to_string())

    # Attribution: difference between broad-IR and liquid-IR for each
    # (regime, variant, N). Equals "rotation alpha captured by the
    # liquidity filter relative to broad universe."
    print("\n" + "=" * 76)
    print("ATTRIBUTION: IR(vs broad) - IR(vs liquid)")
    print("  positive = liquidity-rotation alpha embedded in broad-vs comparison")
    print("=" * 76)
    pivot_broad = (
        head[head["benchmark"] == "broad"]
        .pivot_table(
            index=["regime", "variant"], columns="n_top", values="ir",
        )
    )
    pivot_liquid = (
        head[head["benchmark"] == "liquid"]
        .pivot_table(
            index=["regime", "variant"], columns="n_top", values="ir",
        )
    )
    diff = (pivot_broad - pivot_liquid).round(3)
    if len(diff) > 0:
        diff = diff[TOP_N_VALUES] if all(
            c in diff.columns for c in TOP_N_VALUES
        ) else diff
        print(diff.to_string())

    # Sector concentration (benchmark-independent; pull from broad rows)
    print("\n" + "=" * 76)
    print("MAX SECTOR CONCENTRATION (%) by variant, γ regime")
    print("=" * 76)
    sub = head[
        (head["regime"] == "gamma_post_NNA")
        & (head["benchmark"] == "broad")
    ]
    piv = sub.pivot(
        index="variant", columns="n_top", values="mean_max_sector_pct"
    ).round(1)
    piv = piv[TOP_N_VALUES].reindex(variant_order)
    print(piv.to_string())

    print("\n" + "=" * 76)
    print("MAX DRAWDOWN (%) by variant, γ regime")
    print("=" * 76)
    piv = sub.pivot(
        index="variant", columns="n_top", values="max_dd_pct"
    ).round(2)
    piv = piv[TOP_N_VALUES].reindex(variant_order)
    print(piv.to_string())

    print("\n" + "=" * 76)
    print("MEAN WEEKLY CHURN (%) by variant, γ regime")
    print("=" * 76)
    piv = sub.pivot(
        index="variant", columns="n_top", values="mean_churn_pct"
    ).round(2)
    piv = piv[TOP_N_VALUES].reindex(variant_order)
    print(piv.to_string())

    print("\n" + "=" * 76)
    print("MONTHLY HIT RATE (%) vs broad benchmark, γ regime")
    print("=" * 76)
    piv = sub.pivot(
        index="variant", columns="n_top", values="monthly_hit_rate_pct"
    ).round(1)
    piv = piv[TOP_N_VALUES].reindex(variant_order)
    print(piv.to_string())

    plot_filtered_comparison(summary_df)
    return summary_df, diag_df


# ═══════════════════════════════════════════════════════════════════════
# Plot
# ═══════════════════════════════════════════════════════════════════════

def plot_filtered_comparison(summary: pd.DataFrame) -> None:
    """
    Plot vs broad benchmark by default. The CSV contains both benchmark
    rows; user can pivot for liquid-benchmark view independently.
    """
    head = summary[
        (summary["convention"] == "open_t1")
        & (summary["ret_kind"] == "net")
        & (summary["benchmark"] == "broad")
    ].copy()

    fig, axes = plt.subplots(2, 2, figsize=(13, 10))

    variant_colors = {
        "unfiltered": "#1f77b4",
        "liq_only": "#ff7f0e",
        "full_filtered": "#2ca02c",
    }
    variant_styles = {
        "unfiltered": "o-",
        "liq_only": "s--",
        "full_filtered": "^-",
    }

    gamma_data = head[head["regime"] == "gamma_post_NNA"].copy()

    # Top-left: IR with CI
    ax = axes[0, 0]
    for variant_name, _, _ in VARIANTS:
        sub = gamma_data[gamma_data["variant"] == variant_name].sort_values(
            "n_top"
        )
        if len(sub) == 0:
            continue
        ax.errorbar(
            sub["n_top"], sub["ir"],
            yerr=[
                sub["ir"] - sub["ir_ci_low"],
                sub["ir_ci_high"] - sub["ir"],
            ],
            fmt=variant_styles[variant_name],
            color=variant_colors[variant_name],
            label=variant_name, capsize=4, linewidth=1.5,
        )
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xscale("log")
    ax.set_xticks(TOP_N_VALUES)
    ax.set_xticklabels(TOP_N_VALUES)
    ax.set_xlabel("Top N (log)")
    ax.set_ylabel("Net IR (open_t1, vs universe_ew)")
    ax.set_title("γ: Net IR with 95% bootstrap CI")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # Top-right: max DD
    ax = axes[0, 1]
    for variant_name, _, _ in VARIANTS:
        sub = gamma_data[gamma_data["variant"] == variant_name].sort_values(
            "n_top"
        )
        if len(sub) == 0:
            continue
        ax.plot(
            sub["n_top"], sub["max_dd_pct"],
            variant_styles[variant_name],
            color=variant_colors[variant_name],
            label=variant_name, linewidth=1.5,
        )
    ax.set_xscale("log")
    ax.set_xticks(TOP_N_VALUES)
    ax.set_xticklabels(TOP_N_VALUES)
    ax.set_xlabel("Top N")
    ax.set_ylabel("Max drawdown (%)")
    ax.set_title("γ: Max drawdown")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # Bottom-left: max sector concentration
    ax = axes[1, 0]
    for variant_name, _, _ in VARIANTS:
        sub = gamma_data[gamma_data["variant"] == variant_name].sort_values(
            "n_top"
        )
        if len(sub) == 0:
            continue
        ax.plot(
            sub["n_top"], sub["mean_max_sector_pct"],
            variant_styles[variant_name],
            color=variant_colors[variant_name],
            label=variant_name, linewidth=1.5,
        )
    ax.axhline(
        MAX_SECTOR_PCT * 100, color="red", linewidth=0.6,
        linestyle=":", alpha=0.6,
        label=f"{MAX_SECTOR_PCT*100:.0f}% cap",
    )
    ax.set_xscale("log")
    ax.set_xticks(TOP_N_VALUES)
    ax.set_xticklabels(TOP_N_VALUES)
    ax.set_xlabel("Top N")
    ax.set_ylabel("Mean max sector concentration (%)")
    ax.set_title("γ: Sector concentration")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # Bottom-right: tracking error
    ax = axes[1, 1]
    for variant_name, _, _ in VARIANTS:
        sub = gamma_data[gamma_data["variant"] == variant_name].sort_values(
            "n_top"
        )
        if len(sub) == 0:
            continue
        ax.plot(
            sub["n_top"], sub["tracking_err_pct"],
            variant_styles[variant_name],
            color=variant_colors[variant_name],
            label=variant_name, linewidth=1.5,
        )
    ax.set_xscale("log")
    ax.set_xticks(TOP_N_VALUES)
    ax.set_xticklabels(TOP_N_VALUES)
    ax.set_xlabel("Top N")
    ax.set_ylabel("Annualized tracking error (%)")
    ax.set_title("γ: Tracking error")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    fig.suptitle(
        f"Top-N with filters: liquidity floor "
        f"= {LIQUIDITY_FLOOR_YI}亿元, sector cap "
        f"= {int(MAX_SECTOR_PCT*100)}% (γ regime)",
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
        description="Top-N with liquidity floor and sector cap on z_turnover_resid."
    )
    ap.add_argument("mode", choices=["run", "status"])
    args = ap.parse_args()

    if args.mode == "status":
        for path in (SUMMARY_OUT, DIAG_OUT, PLOT_OUT):
            print(f"  {path}: {'EXISTS' if path.exists() else 'missing'}")
        return

    run_pipeline()
    print("\nDone.")


if __name__ == "__main__":
    main()