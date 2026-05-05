"""
combination_analysis.py — turnover + reversal multi-factor combination.

Tests three weighting schemes for combining z_turnover_resid and
z_reversal_resid_15d into a single combined score, then evaluates the
combined score under the same top_700 long-only T+1 deployment as the
turnover baseline.

The L=15 reversal lookback is locked in from the earlier sweep; this
script does not re-test other lookbacks. The point of this run is to
answer: does adding reversal to turnover make the COMBINED tradeable
strategy better, comparable, or worse?

Five strategies tested:
  turnover_only   z_turnover_resid alone (should reproduce IR ~+0.39 net γ
                   and serves as the baseline)
  reversal_only   z_reversal_resid_15d alone (single-factor reversal at top_700)
  combo_equal     0.5 * z_turnover + 0.5 * z_reversal_15d
  combo_ic        rolling-IC weighted (weights ∝ recent mean IC of each factor)
  combo_fmb       Fama-MacBeth weighted (weights ∝ recent mean OLS coef of
                   forward-return on each factor)

Real-time weight discipline
---------------------------
For combo_ic and combo_fmb, weights at rebalance t use ONLY data from
rebalances [t - W, t - 1] where W = 52 weeks. This avoids look-ahead
since forward_return[s] is only observable after rebalance s+1. For the
first 12 rebalances (or whenever rolling weights aren't well-defined),
falls back to equal-weight. Negative coefficients/ICs are floored at 0
(don't bet against a factor whose recent IC turned negative; treat that
as a model-breakdown signal rather than as alpha).

Three regimes
-------------
  alpha_all         2019-01-09 to 2026-04-29  (full panel)
  beta_pre_NNA      2019-01-09 to 2024-04-11  (pre 新国九条)
  gamma_post_NNA    2024-04-12 to 2026-04-29  (post 新国九条, the deployment regime)

Same baskets are built once on the full panel; regimes are implemented
by filtering trade dates in the daily backtest. Real-time weight
estimates carry across regime boundaries naturally, which is the honest
deployment behavior.

Contribution diagnostics (per regime × combo scheme)
----------------------------------------------------
  basket_overlap_with_turnover    fraction of combo top_700 also in
                                  turnover-only top_700, time-series mean
  basket_overlap_with_reversal    same vs reversal-only
  mean_w_turnover, mean_w_reversal  realised weights, time-series mean
  std_w_turnover, std_w_reversal    weight stability
  marginal_IR_from_turnover    IR_combo - IR_reversal_only
                                "what turnover adds to the combination"
  marginal_IR_from_reversal    IR_combo - IR_turnover_only
                                "what reversal adds to the combination"

Cost model
----------
Matches turnover_concentration_sweep convention. 0.18% roundtrip cost
applied as `churn × 0.18%` on each entry day (Thursday after Wednesday
rebalance). Components: 0.015% × 2 commissions + 0.05% stamp duty
+ 0.05% × 2 slippage = 0.18%. Stamp duty is sell-side only in China but
we charge as roundtrip for simplicity to match turnover_neutralized.

Outputs
-------
  data/combination_summary.csv          regime × scheme × convention × ret_kind
  data/combination_contribution.csv     regime × combo_scheme
  data/combination_realtime_weights.csv per-rebalance weights for ic/fmb
  data/combination_phase2_daily_<label>.csv  daily P&L per scheme
  graphs/combination_comparison.png

Usage
-----
    python combination_analysis.py run        # full pipeline, all regimes
    python combination_analysis.py status     # inspect cached outputs only
"""

import argparse
import bisect
import logging
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
    THREE_REGIME_WINDOWS,
    TRADING_CALENDAR_PATH,
    TRADING_DAYS_PER_YEAR,
)
from factor_utils import (
    cross_sectional_zscore,
    residualise_factor_per_date,
)
from hypothesis_testing import block_bootstrap_ci

from reversal_analysis import (
    compute_past_returns_panel,
    add_z_reversal_resid,
    _read_daily_prices,
    _basket_for_date,
)
from turnover_neutralized import (
    load_panel_with_sector,
    add_z_turnover_resid,
)


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
GRAPHS_DIR.mkdir(exist_ok=True)

SUMMARY_OUT = DATA_DIR / "combination_summary.csv"
CONTRIBUTION_OUT = DATA_DIR / "combination_contribution.csv"
WEIGHTS_OUT = DATA_DIR / "combination_realtime_weights.csv"
PLOT_OUT = GRAPHS_DIR / "combination_comparison.png"
ERROR_LOG = DATA_DIR / "errors_combination.log"

# Locked-in choices
LOOKBACK_REVERSAL = 15           # winning L from the multi-regime sweep
TOP_N = 700                      # matches turnover_neutralized deployment
ROLLING_WINDOW_WEEKS = 52        # 1 year of past data for weights
MIN_WINDOW_WEEKS = 12            # min before rolling weights kick in
DAILY_BLOCK_SIZE = 20
SEED = 42
BOOT_N = 5000

# Cost model: 0.18% roundtrip, charged as churn × 0.18% on entry day
COST_PER_ROUNDTRIP = 0.0018

REVERSAL_COL = f"z_reversal_resid_{LOOKBACK_REVERSAL}d"

SCHEMES = ["turnover_only", "reversal_only", "combo_equal", "combo_ic", "combo_fmb"]
COMBO_SCHEMES = ["combo_equal", "combo_ic", "combo_fmb"]
SCHEME_TO_SCORE = {
    "turnover_only": "z_turnover_resid",
    "reversal_only": REVERSAL_COL,
    "combo_equal": "combo_equal",
    "combo_ic": "combo_ic",
    "combo_fmb": "combo_fmb",
}


_logger = logging.getLogger("combination_analysis")
_logger.setLevel(logging.WARNING)
if not _logger.handlers:
    _h = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _logger.addHandler(_h)


# ═══════════════════════════════════════════════════════════════════════
# Step 1: build the two factor columns (turnover + reversal_15d)
# ═══════════════════════════════════════════════════════════════════════

def build_factor_columns(panel: pd.DataFrame) -> pd.DataFrame:
    """Add z_turnover_resid and z_reversal_resid_15d to panel."""
    print("\n" + "=" * 76)
    print("STEP 1: BUILDING FACTOR COLUMNS")
    print("=" * 76)

    panel = add_z_turnover_resid(panel, with_beta=False)
    iu = panel[panel["in_universe"]]
    cov_t = iu["z_turnover_resid"].notna().mean() * 100
    print(f"  z_turnover_resid coverage on in_universe: {cov_t:.1f}%")

    panel, _ = add_z_reversal_resid(
        panel, lookback=LOOKBACK_REVERSAL, orthog_to_turnover=False,
    )
    iu = panel[panel["in_universe"]]
    cov_r = iu[REVERSAL_COL].notna().mean() * 100
    print(f"  {REVERSAL_COL} coverage on in_universe: {cov_r:.1f}%")
    return panel


# ═══════════════════════════════════════════════════════════════════════
# Step 2: real-time weight estimation for IC and FMB schemes
# ═══════════════════════════════════════════════════════════════════════

def compute_realtime_weights(panel: pd.DataFrame) -> pd.DataFrame:
    """
    For each rebalance date t, compute weights for the IC and FMB schemes
    using ONLY data from rebalances [t - W, t - 1] (W = 52 weeks).

    IC scheme:
        per-rebalance Spearman IC of each factor with weekly_forward_return
        rolling mean, normalized to sum to 1 (negative IC floored at 0)

    FMB scheme:
        per-rebalance OLS coefficient of forward_return on (z_turn, z_rev)
        rolling mean, normalized as relative weights (negative coefs floored at 0)

    Returns weights_df with columns
    [rebalance_date, scheme, w_turnover, w_reversal, fallback].
    Equal-weight (0.5, 0.5) is used as a fallback for early rebalances
    or when both rolling estimates are non-positive.
    """
    print("\n" + "=" * 76)
    print("STEP 2: REAL-TIME WEIGHT ESTIMATION")
    print("=" * 76)

    iu = panel[panel["in_universe"]].dropna(
        subset=["z_turnover_resid", REVERSAL_COL, "weekly_forward_return"]
    ).copy()

    rebal_dates = sorted(iu["rebalance_date"].unique())

    # Per-rebalance IC for each factor
    print("  computing per-rebalance Spearman IC ...")
    ic_turn = (
        iu.groupby("rebalance_date")
        .apply(
            lambda g: g["z_turnover_resid"].corr(
                g["weekly_forward_return"], method="spearman"
            ),
            include_groups=False,
        )
    )
    ic_rev = (
        iu.groupby("rebalance_date")
        .apply(
            lambda g: g[REVERSAL_COL].corr(
                g["weekly_forward_return"], method="spearman"
            ),
            include_groups=False,
        )
    )

    # Per-rebalance OLS coefficients for FMB
    print("  computing per-rebalance Fama-MacBeth coefficients ...")
    coef_rows = []
    for date, g in iu.groupby("rebalance_date"):
        X = np.column_stack([
            np.ones(len(g)),
            g["z_turnover_resid"].values,
            g[REVERSAL_COL].values,
        ])
        y = g["weekly_forward_return"].values
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            coef_rows.append({
                "rebalance_date": date,
                "coef_turn": float(beta[1]),
                "coef_rev": float(beta[2]),
            })
        except np.linalg.LinAlgError:
            coef_rows.append({
                "rebalance_date": date,
                "coef_turn": np.nan,
                "coef_rev": np.nan,
            })
    coef_df = pd.DataFrame(coef_rows).set_index("rebalance_date")

    # Rolling weights at each rebalance using past W weeks
    weights_rows = []
    for i, t in enumerate(rebal_dates):
        if i < MIN_WINDOW_WEEKS:
            for scheme in ("ic", "fmb"):
                weights_rows.append({
                    "rebalance_date": t, "scheme": scheme,
                    "w_turnover": 0.5, "w_reversal": 0.5,
                    "fallback": True,
                })
            continue

        start_idx = max(0, i - ROLLING_WINDOW_WEEKS)
        window_dates = rebal_dates[start_idx:i]  # excludes t

        # IC scheme
        ic_t_mean = ic_turn.reindex(window_dates).mean()
        ic_r_mean = ic_rev.reindex(window_dates).mean()
        w_t_pos = max(float(ic_t_mean) if pd.notna(ic_t_mean) else 0.0, 0.0)
        w_r_pos = max(float(ic_r_mean) if pd.notna(ic_r_mean) else 0.0, 0.0)
        if w_t_pos + w_r_pos > 1e-9:
            w_t = w_t_pos / (w_t_pos + w_r_pos)
            w_r = w_r_pos / (w_t_pos + w_r_pos)
            ic_fb = False
        else:
            w_t, w_r, ic_fb = 0.5, 0.5, True
        weights_rows.append({
            "rebalance_date": t, "scheme": "ic",
            "w_turnover": w_t, "w_reversal": w_r,
            "fallback": ic_fb,
        })

        # FMB scheme
        c_t_mean = coef_df.loc[window_dates, "coef_turn"].mean()
        c_r_mean = coef_df.loc[window_dates, "coef_rev"].mean()
        w_t_pos = max(float(c_t_mean) if pd.notna(c_t_mean) else 0.0, 0.0)
        w_r_pos = max(float(c_r_mean) if pd.notna(c_r_mean) else 0.0, 0.0)
        if w_t_pos + w_r_pos > 1e-9:
            w_t = w_t_pos / (w_t_pos + w_r_pos)
            w_r = w_r_pos / (w_t_pos + w_r_pos)
            fmb_fb = False
        else:
            w_t, w_r, fmb_fb = 0.5, 0.5, True
        weights_rows.append({
            "rebalance_date": t, "scheme": "fmb",
            "w_turnover": w_t, "w_reversal": w_r,
            "fallback": fmb_fb,
        })

    weights_df = pd.DataFrame(weights_rows)
    weights_df.to_csv(WEIGHTS_OUT, index=False)
    print(f"  saved per-rebalance weights to {WEIGHTS_OUT}")

    # Diagnostic summary
    for scheme in ("ic", "fmb"):
        sub = weights_df[weights_df["scheme"] == scheme]
        non_fb = sub[~sub["fallback"]]
        print(f"\n  {scheme}-weighted scheme:")
        print(f"    {len(non_fb)} of {len(sub)} dates have non-fallback weights")
        if len(non_fb) > 0:
            print(f"    mean w_turnover = {non_fb['w_turnover'].mean():.3f}, "
                  f"std = {non_fb['w_turnover'].std():.3f}")
            print(f"    mean w_reversal = {non_fb['w_reversal'].mean():.3f}, "
                  f"std = {non_fb['w_reversal'].std():.3f}")

    return weights_df


# ═══════════════════════════════════════════════════════════════════════
# Step 3: build combined scores
# ═══════════════════════════════════════════════════════════════════════

def add_combined_scores(
    panel: pd.DataFrame, weights_df: pd.DataFrame,
) -> pd.DataFrame:
    """Add combo_equal, combo_ic, combo_fmb columns to panel."""
    print("\n" + "=" * 76)
    print("STEP 3: BUILDING COMBINED SCORES")
    print("=" * 76)

    panel = panel.copy()
    panel["combo_equal"] = (
        0.5 * panel["z_turnover_resid"] + 0.5 * panel[REVERSAL_COL]
    )

    for scheme in ("ic", "fmb"):
        scheme_w = (
            weights_df[weights_df["scheme"] == scheme]
            .set_index("rebalance_date")
        )
        w_t = panel["rebalance_date"].map(scheme_w["w_turnover"])
        w_r = panel["rebalance_date"].map(scheme_w["w_reversal"])
        panel[f"combo_{scheme}"] = (
            w_t * panel["z_turnover_resid"] + w_r * panel[REVERSAL_COL]
        )

    for col in ("combo_equal", "combo_ic", "combo_fmb"):
        cov = panel[panel["in_universe"]][col].notna().mean() * 100
        print(f"  {col} coverage on in_universe: {cov:.1f}%")
    return panel


# ═══════════════════════════════════════════════════════════════════════
# Step 4: top_N basket construction
# ═══════════════════════════════════════════════════════════════════════

def build_top_n_baskets(panel: pd.DataFrame, score_col: str, n: int = TOP_N) -> dict:
    """Per-rebalance top_N long-only baskets, sorted descending on score_col."""
    iu = panel[panel["in_universe"]].copy()
    iu = iu.dropna(subset=[score_col])
    baskets = {}
    for date, g in iu.groupby("rebalance_date"):
        sorted_g = g.sort_values(score_col, ascending=False)
        baskets[date] = {
            "top_n": set(sorted_g.head(n)["ts_code"]),
            "universe": set(g["ts_code"]),
        }
    return baskets


def compute_basket_overlap_per_date(
    baskets_a: dict, baskets_b: dict,
) -> pd.Series:
    """Per-date Jaccard-like overlap |A ∩ B| / max(|A|, |B|) of top_n sets."""
    common_dates = sorted(set(baskets_a.keys()) & set(baskets_b.keys()))
    rows = []
    for d in common_dates:
        a = baskets_a[d]["top_n"]
        b = baskets_b[d]["top_n"]
        if len(a) == 0 or len(b) == 0:
            rows.append((d, np.nan))
            continue
        rows.append((d, len(a & b) / max(len(a), len(b))))
    return pd.Series(
        [r[1] for r in rows],
        index=[r[0] for r in rows],
        name="overlap",
    )


def compute_basket_churn(baskets: dict) -> pd.Series:
    """One-sided churn: |basket[t] \\ basket[t-1]| / |basket[t-1]| per rebalance."""
    dates = sorted(baskets.keys())
    rows = []
    prev = None
    for d in dates:
        curr = baskets[d]["top_n"]
        if prev is None or len(prev) == 0:
            rows.append((d, 1.0))
        else:
            rows.append((d, len(curr - prev) / len(prev)))
        prev = curr
    return pd.Series(
        [r[1] for r in rows],
        index=[r[0] for r in rows],
        name="churn",
    )


# ═══════════════════════════════════════════════════════════════════════
# Step 5: top_N daily backtest with cost charging
# ═══════════════════════════════════════════════════════════════════════

def run_top_n_backtest(
    baskets: dict,
    label: str,
    cal: list[str],
) -> pd.DataFrame:
    """
    Daily backtest for one scheme. Walks every trade day from the first
    rebalance to the end of the panel, returning daily gross and net
    returns for top_n and universe under both c2c and open_t1.
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

    print(f"\n  [{label}] backtesting {trade_dates[0]} → {trade_dates[-1]} "
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

        for strat, members in [
            ("top_n", basket["top_n"]),
            ("universe", basket["universe"]),
        ]:
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
    daily_path = DATA_DIR / f"combination_phase2_daily_{label}.csv"
    daily.to_csv(daily_path, index=False)
    print(f"  saved daily P&L to {daily_path}")
    return daily


# ═══════════════════════════════════════════════════════════════════════
# Step 6: per-regime summary (IR vs universe, Sharpe, max DD, churn)
# ═══════════════════════════════════════════════════════════════════════

def summarise_regime(
    daily: pd.DataFrame,
    label: str,
    regime_label: str,
    start: str,
    end: str,
    churn_in_regime_mean: float,
) -> pd.DataFrame:
    """
    Slice daily P&L to the regime, then for each (convention, ret_kind)
    compute IR, Sharpe, max DD, etc.
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

            n = len(ts)
            ann_ret_tn = (1 + tn).prod() ** (TRADING_DAYS_PER_YEAR / n) - 1
            ann_ret_un = (1 + un).prod() ** (TRADING_DAYS_PER_YEAR / n) - 1
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
            cum = (1 + tn).cumprod()
            max_dd = (cum / cum.cummax() - 1).min()

            rows.append({
                "regime": regime_label,
                "label": label,
                "convention": conv,
                "ret_kind": ret_kind,
                "n_days": n,
                "ann_ret_top_n_pct": ann_ret_tn * 100,
                "ann_ret_universe_pct": ann_ret_un * 100,
                "active_ret_pct": ann_active * 100,
                "tracking_err_pct": ann_te * 100,
                "ir": ir,
                "sharpe_top_n": sharpe_tn,
                "max_dd_pct": max_dd * 100,
                "mean_churn_pct": (
                    churn_in_regime_mean * 100
                    if churn_in_regime_mean is not None else np.nan
                ),
            })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════
# Step 7: orchestrator
# ═══════════════════════════════════════════════════════════════════════

def run_pipeline() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build factors, weights, scores, baskets, backtests, and diagnostics."""
    # Load and build factors
    panel = load_panel_with_sector()
    past = compute_past_returns_panel(panel, lookbacks=(LOOKBACK_REVERSAL,))
    panel = panel.merge(past, on=["rebalance_date", "ts_code"], how="left")
    panel = build_factor_columns(panel)

    # Real-time weights
    weights_df = compute_realtime_weights(panel)
    panel = add_combined_scores(panel, weights_df)

    # Build baskets
    print("\n" + "=" * 76)
    print(f"STEP 4: BUILDING TOP-{TOP_N} BASKETS PER SCHEME")
    print("=" * 76)
    all_baskets = {}
    for scheme in SCHEMES:
        col = SCHEME_TO_SCORE[scheme]
        all_baskets[scheme] = build_top_n_baskets(panel, col, n=TOP_N)
        sizes = [len(all_baskets[scheme][d]["top_n"])
                 for d in all_baskets[scheme]]
        print(f"  {scheme}: median basket size = {int(np.median(sizes))}")

    # Backtests once each on full trade-date span
    print("\n" + "=" * 76)
    print(f"STEP 5: TOP-{TOP_N} DAILY BACKTESTS")
    print("=" * 76)
    cal = pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()
    daily_per_scheme = {}
    for scheme in SCHEMES:
        daily_per_scheme[scheme] = run_top_n_backtest(
            all_baskets[scheme], scheme, cal,
        )

    # Per-regime summary
    print("\n" + "=" * 76)
    print("STEP 6: PER-REGIME SUMMARIES")
    print("=" * 76)
    summary_rows = []
    for regime_label, (start, end) in THREE_REGIME_WINDOWS.items():
        start_str = (
            start.strftime("%Y-%m-%d") if hasattr(start, "strftime") else str(start)
        )
        end_str = (
            end.strftime("%Y-%m-%d") if hasattr(end, "strftime") else str(end)
        )
        for scheme in SCHEMES:
            churn = compute_basket_churn(all_baskets[scheme])
            churn_dates_ts = pd.to_datetime(churn.index)
            mask = (
                (churn_dates_ts >= pd.to_datetime(start))
                & (churn_dates_ts <= pd.to_datetime(end))
            )
            churn_filtered = churn[mask]
            churn_mean = (
                float(churn_filtered.iloc[1:].mean())
                if len(churn_filtered) > 1 else np.nan
            )
            sub = summarise_regime(
                daily_per_scheme[scheme], scheme,
                regime_label, start_str, end_str, churn_mean,
            )
            summary_rows.append(sub)

    summary_df = pd.concat(summary_rows, ignore_index=True)
    summary_df.to_csv(SUMMARY_OUT, index=False)
    print(f"\n  saved summary to {SUMMARY_OUT}")

    # Contribution diagnostics
    print("\n" + "=" * 76)
    print("STEP 7: CONTRIBUTION DIAGNOSTICS")
    print("=" * 76)

    # Per-date overlaps for each combo scheme vs single-factor baselines
    overlap_with_turn = {}
    overlap_with_rev = {}
    for scheme in COMBO_SCHEMES:
        overlap_with_turn[scheme] = compute_basket_overlap_per_date(
            all_baskets[scheme], all_baskets["turnover_only"],
        )
        overlap_with_rev[scheme] = compute_basket_overlap_per_date(
            all_baskets[scheme], all_baskets["reversal_only"],
        )

    contribution_rows = []
    for regime_label, (start, end) in THREE_REGIME_WINDOWS.items():
        for scheme in COMBO_SCHEMES:
            # Basket overlaps in regime
            ov_t = overlap_with_turn[scheme]
            ov_r = overlap_with_rev[scheme]
            ov_t_dates = pd.to_datetime(ov_t.index)
            ov_r_dates = pd.to_datetime(ov_r.index)
            mask_t = (ov_t_dates >= pd.to_datetime(start)) & (ov_t_dates <= pd.to_datetime(end))
            mask_r = (ov_r_dates >= pd.to_datetime(start)) & (ov_r_dates <= pd.to_datetime(end))
            mean_ov_t = float(ov_t[mask_t].mean()) if mask_t.any() else np.nan
            mean_ov_r = float(ov_r[mask_r].mean()) if mask_r.any() else np.nan

            # Realised weights in regime (only ic / fmb have non-trivial weights)
            mean_w_t = mean_w_r = std_w_t = std_w_r = np.nan
            if scheme in ("combo_ic", "combo_fmb"):
                scheme_short = scheme.replace("combo_", "")
                ws = weights_df[weights_df["scheme"] == scheme_short].copy()
                ws["rebalance_date_ts"] = pd.to_datetime(ws["rebalance_date"])
                ws_in = ws[
                    (ws["rebalance_date_ts"] >= pd.to_datetime(start))
                    & (ws["rebalance_date_ts"] <= pd.to_datetime(end))
                    & (~ws["fallback"])
                ]
                if len(ws_in) > 0:
                    mean_w_t = float(ws_in["w_turnover"].mean())
                    std_w_t = float(ws_in["w_turnover"].std())
                    mean_w_r = float(ws_in["w_reversal"].mean())
                    std_w_r = float(ws_in["w_reversal"].std())
            elif scheme == "combo_equal":
                mean_w_t = mean_w_r = 0.5
                std_w_t = std_w_r = 0.0

            # Marginal IR contributions (open_t1 net)
            def get_ir(label_):
                m = (
                    (summary_df["regime"] == regime_label)
                    & (summary_df["label"] == label_)
                    & (summary_df["convention"] == "open_t1")
                    & (summary_df["ret_kind"] == "net")
                )
                rows = summary_df[m]
                return float(rows["ir"].iloc[0]) if len(rows) else np.nan

            ir_combo = get_ir(scheme)
            ir_turn = get_ir("turnover_only")
            ir_rev = get_ir("reversal_only")
            margin_from_turn = (
                ir_combo - ir_rev
                if not pd.isna(ir_combo) and not pd.isna(ir_rev) else np.nan
            )
            margin_from_rev = (
                ir_combo - ir_turn
                if not pd.isna(ir_combo) and not pd.isna(ir_turn) else np.nan
            )

            contribution_rows.append({
                "regime": regime_label,
                "scheme": scheme,
                "mean_basket_overlap_with_turnover": mean_ov_t,
                "mean_basket_overlap_with_reversal": mean_ov_r,
                "mean_w_turnover": mean_w_t,
                "std_w_turnover": std_w_t,
                "mean_w_reversal": mean_w_r,
                "std_w_reversal": std_w_r,
                "ir_combined_net_open_t1": ir_combo,
                "ir_turnover_only_net_open_t1": ir_turn,
                "ir_reversal_only_net_open_t1": ir_rev,
                "marginal_IR_from_turnover": margin_from_turn,
                "marginal_IR_from_reversal": margin_from_rev,
            })

    contribution_df = pd.DataFrame(contribution_rows)
    contribution_df.to_csv(CONTRIBUTION_OUT, index=False)
    print(f"\n  saved contribution diagnostics to {CONTRIBUTION_OUT}")

    # Print headlines
    print("\n" + "=" * 76)
    print("HEADLINE: NET OPEN_T1 IR vs UNIVERSE_EW BY REGIME × SCHEME")
    print("=" * 76)
    head = summary_df[
        (summary_df["convention"] == "open_t1")
        & (summary_df["ret_kind"] == "net")
    ].copy()
    cols = [
        "regime", "label", "n_days", "ann_ret_top_n_pct",
        "active_ret_pct", "tracking_err_pct", "ir",
        "sharpe_top_n", "max_dd_pct", "mean_churn_pct",
    ]
    print("\n" + head[cols].round(3).to_string(index=False))

    print("\n" + "=" * 76)
    print("CONTRIBUTION DIAGNOSTICS")
    print("=" * 76)
    print("\n" + contribution_df.round(3).to_string(index=False))

    plot_combination(summary_df, contribution_df)
    return summary_df, contribution_df


# ═══════════════════════════════════════════════════════════════════════
# Plot
# ═══════════════════════════════════════════════════════════════════════

def plot_combination(
    summary: pd.DataFrame, contribution: pd.DataFrame,
) -> None:
    """
    Two panels.
      (a) Net IR by scheme × regime, open_t1.
      (b) Mean basket overlap of each combo with turnover-only and
          reversal-only, by regime.
    """
    head = summary[
        (summary["convention"] == "open_t1")
        & (summary["ret_kind"] == "net")
    ].copy()
    schemes = SCHEMES
    regimes = list(THREE_REGIME_WINDOWS.keys())

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    # Left: IR by scheme × regime
    ax = axes[0]
    width = 0.27
    x = np.arange(len(schemes))
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]
    for j, regime in enumerate(regimes):
        vals = []
        for s in schemes:
            r = head[(head["regime"] == regime) & (head["label"] == s)]
            vals.append(float(r["ir"].iloc[0]) if len(r) else np.nan)
        ax.bar(
            x + (j - 1) * width, vals, width,
            label=regime, color=colors[j],
        )
    ax.set_xticks(x)
    ax.set_xticklabels(schemes, rotation=30, ha="right")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_ylabel("Net IR (open_t1, vs universe_ew)")
    ax.set_title("Top-700 long-only net IR by scheme × regime")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3, axis="y")

    # Right: basket overlap of combos with each baseline
    ax = axes[1]
    combo_schemes = COMBO_SCHEMES
    width = 0.18
    x = np.arange(len(combo_schemes))
    for j, regime in enumerate(regimes):
        ov_t_vals = []
        ov_r_vals = []
        for s in combo_schemes:
            r = contribution[
                (contribution["regime"] == regime)
                & (contribution["scheme"] == s)
            ]
            ov_t_vals.append(
                float(r["mean_basket_overlap_with_turnover"].iloc[0])
                if len(r) else np.nan
            )
            ov_r_vals.append(
                float(r["mean_basket_overlap_with_reversal"].iloc[0])
                if len(r) else np.nan
            )
        offset = (j - 1) * 2 * width
        ax.bar(
            x + offset, ov_t_vals, width,
            label=f"{regime} (vs turnover)",
            color=colors[j], alpha=0.95,
        )
        ax.bar(
            x + offset + width, ov_r_vals, width,
            label=f"{regime} (vs reversal)",
            color=colors[j], alpha=0.45,
            hatch="//",
        )
    ax.set_xticks(x)
    ax.set_xticklabels(combo_schemes, rotation=20, ha="right")
    ax.set_ylabel("Mean top-700 basket overlap")
    ax.set_title("Combo basket overlap with single-factor baselines")
    ax.set_ylim(0, 1.0)
    ax.legend(fontsize=8, ncol=1, loc="upper right")
    ax.grid(alpha=0.3, axis="y")

    fig.suptitle(
        f"Multi-factor combination: turnover + reversal "
        f"(L={LOOKBACK_REVERSAL}d) at top-{TOP_N}",
        y=1.00,
    )
    fig.tight_layout()
    fig.savefig(PLOT_OUT, dpi=120)
    plt.close(fig)
    print(f"  comparison plot saved to {PLOT_OUT}")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Multi-factor combination: turnover + reversal_15d at top-700."
    )
    ap.add_argument("mode", choices=["run", "status"], default="run")
    args = ap.parse_args()

    if args.mode == "status":
        for path in (SUMMARY_OUT, CONTRIBUTION_OUT, WEIGHTS_OUT, PLOT_OUT):
            print(f"  {path}: {'EXISTS' if path.exists() else 'missing'}")
        return

    run_pipeline()
    print("\nDone.")


if __name__ == "__main__":
    main()