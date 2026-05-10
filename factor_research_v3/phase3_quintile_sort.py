"""
phase3_quintile_sort.py — Quintile sort within profitable subset.

For each (factor, universe), at each signal_date:
  - Take the profitable subset (ep is non-NaN)
  - Sort by z_{factor}_resid into 5 quintiles (Q1=lowest factor, Q5=highest)
  - Equal-weight each quintile, NO sector cap (per spec section 7 Q2 — pure
    factor signal; sector concentration in extremes is itself diagnostic)
  - Buy-and-hold open-to-open T+1, headline cost regime

For each (factor, universe, quintile):
  - ann_return_net, ann_vol, sharpe
  - IR vs universe_EW (full universe benchmark)
  - IR vs profitable_EW (cleaner factor attribution)

Plus the Q5-Q1 spread for each (factor, universe).

Interpretation:
  Q5 > Q4 > ... > Q1 monotonic & positive   → factor signal exists; top-10 may
                                                be hurt by sector concentration
  Q5-Q1 ≈ 0                                  → no signal at all
  Q5-Q1 < 0                                  → factor signal INVERTED in γ
"""

from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np
import pandas as pd

import data_loaders as dl
import fr3_config as cfg

FACTORS = [("ep", "z_ep_resid"), ("roa", "z_roa_resid")]
N_QUINTILES = 5


def _basket_period_return(basket: list[str],
                          entry_date: pd.Timestamp,
                          exit_date: pd.Timestamp) -> float:
    if not basket:
        return np.nan
    p_entry = dl.load_daily_open_adj(entry_date)
    p_exit = dl.load_daily_open_adj(exit_date)
    if p_entry is None or p_exit is None:
        return np.nan
    common = p_entry.index.intersection(basket).intersection(p_exit.index)
    if len(common) == 0:
        return np.nan
    rets = p_exit.loc[common] / p_entry.loc[common] - 1.0
    return float(rets.mean())


def _annualize(pr: np.ndarray) -> dict:
    pr = pr[~np.isnan(pr)]
    if len(pr) < 2:
        return {"ann_return": np.nan, "ann_vol": np.nan, "sharpe": np.nan,
                "max_dd": np.nan, "n_periods": int(len(pr))}
    ann_ret = float(np.mean(pr) * cfg.PERIODS_PER_YEAR)
    ann_vol = float(np.std(pr, ddof=1) * np.sqrt(cfg.PERIODS_PER_YEAR))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    cum = np.cumprod(1 + pr)
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1.0
    return {"ann_return": ann_ret, "ann_vol": ann_vol,
            "sharpe": sharpe, "max_dd": float(dd.min()),
            "n_periods": int(len(pr))}


def _ir(active_returns: np.ndarray) -> float:
    a = active_returns[~np.isnan(active_returns)]
    if len(a) < 2 or np.std(a, ddof=1) == 0:
        return np.nan
    return float(np.mean(a) / np.std(a, ddof=1) * np.sqrt(cfg.PERIODS_PER_YEAR))


def _churn(prev: set[str], curr: set[str]) -> float:
    if not prev:
        return 1.0
    return 1 - len(curr & prev) / max(len(curr), 1)


def run() -> pd.DataFrame:
    if not cfg.FACTOR_PANEL_PATH.exists():
        raise FileNotFoundError(f"missing factor panel: {cfg.FACTOR_PANEL_PATH}")
    panel = pd.read_parquet(cfg.FACTOR_PANEL_PATH)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    panel["entry_date"] = pd.to_datetime(panel["entry_date"])
    panel["exit_date"] = pd.to_datetime(panel["exit_date"])

    # Load Phase 3 decomposition for benchmarks
    dec = pd.read_csv(cfg.PHASE3_DECOMPOSITION_PATH)
    bench_universe = {
        u: dec[(dec["universe"] == u) & (dec["basket_type"] == "universe_EW")]["ann_return"].iloc[0]
        for u in ("canonical", "csi300")
    }

    # Build period-return time series for universe_EW and profitable_EW
    # so we can compute IR vs each
    print("Re-computing universe_EW and profitable_EW per-period series for IR...")
    period_universe: dict[tuple, list] = defaultdict(list)
    period_profitable: dict[tuple, list] = defaultdict(list)
    universe_signals: dict[str, list[pd.Timestamp]] = defaultdict(list)

    for u in ("canonical", "csi300"):
        sub = panel[panel["universe"] == u]
        prev_u: set[str] = set()
        prev_p: set[str] = set()
        for s, g in sub.groupby("signal_date"):
            if g["entry_date"].isna().all():
                continue
            entry = g["entry_date"].iloc[0]
            exit_ = g["exit_date"].iloc[0]
            if pd.isna(entry) or pd.isna(exit_):
                continue
            all_codes = list(g["ts_code"])
            prof_codes = list(g.loc[g["ep"].notna(), "ts_code"])

            ru = _basket_period_return(all_codes, entry, exit_)
            rp = _basket_period_return(prof_codes, entry, exit_)
            if pd.isna(ru) or pd.isna(rp):
                continue

            cu = _churn(prev_u, set(all_codes))
            cp = _churn(prev_p, set(prof_codes))
            prev_u = set(all_codes)
            prev_p = set(prof_codes)

            period_universe[(u, s)] = ru - 2 * cu * cfg.COST_RT_HEADLINE
            period_profitable[(u, s)] = rp - 2 * cp * cfg.COST_RT_HEADLINE
            universe_signals[u].append(s)

    rows = []
    for factor_name, factor_col in FACTORS:
        for u in ("canonical", "csi300"):
            print(f"\n[{factor_name} × {u}] quintile sort within profitable subset")
            sub = panel[panel["universe"] == u].copy()

            # Per-quintile basket churn tracking
            prev_baskets: dict[int, set[str]] = {q: set() for q in range(N_QUINTILES)}
            quintile_returns: dict[int, list[float]] = {q: [] for q in range(N_QUINTILES)}
            quintile_signal_dates: dict[int, list[pd.Timestamp]] = {q: [] for q in range(N_QUINTILES)}
            quintile_sizes: dict[int, list[int]] = {q: [] for q in range(N_QUINTILES)}

            for s, g in sub.groupby("signal_date"):
                if g["entry_date"].isna().all():
                    continue
                entry = g["entry_date"].iloc[0]
                exit_ = g["exit_date"].iloc[0]
                if pd.isna(entry) or pd.isna(exit_):
                    continue

                # Profitable subset only
                p = g.dropna(subset=[factor_col, "ep"]).copy()
                if len(p) < N_QUINTILES * 5:
                    continue

                # Quintile by factor
                p["quintile"] = pd.qcut(
                    p[factor_col], N_QUINTILES, labels=False, duplicates="drop"
                )

                for q in range(N_QUINTILES):
                    members = list(p.loc[p["quintile"] == q, "ts_code"])
                    if not members:
                        continue
                    gross = _basket_period_return(members, entry, exit_)
                    if pd.isna(gross):
                        continue
                    cur = set(members)
                    churn = _churn(prev_baskets[q], cur)
                    prev_baskets[q] = cur
                    cost = 2 * churn * cfg.COST_RT_HEADLINE
                    net = gross - cost
                    quintile_returns[q].append(net)
                    quintile_signal_dates[q].append(s)
                    quintile_sizes[q].append(len(members))

            # Aggregate per quintile
            for q in range(N_QUINTILES):
                pr = np.array(quintile_returns[q], dtype=float)
                stats = _annualize(pr)
                # IR vs universe_EW: align signals
                u_aligned = np.array(
                    [period_universe[(u, s)] for s in quintile_signal_dates[q]
                     if (u, s) in period_universe],
                    dtype=float,
                )
                p_aligned = np.array(
                    [period_profitable[(u, s)] for s in quintile_signal_dates[q]
                     if (u, s) in period_profitable],
                    dtype=float,
                )
                if len(u_aligned) == len(pr):
                    ir_vs_universe = _ir(pr - u_aligned)
                else:
                    ir_vs_universe = np.nan
                if len(p_aligned) == len(pr):
                    ir_vs_profitable = _ir(pr - p_aligned)
                else:
                    ir_vs_profitable = np.nan

                rows.append({
                    "factor": factor_name,
                    "universe": u,
                    "quintile": f"Q{q+1}",  # Q1 = lowest factor; Q5 = highest
                    "ann_return": stats["ann_return"],
                    "ann_vol": stats["ann_vol"],
                    "sharpe": stats["sharpe"],
                    "max_dd": stats["max_dd"],
                    "n_periods": stats["n_periods"],
                    "mean_size": float(np.mean(quintile_sizes[q])) if quintile_sizes[q] else np.nan,
                    "ir_vs_universe": ir_vs_universe,
                    "ir_vs_profitable": ir_vs_profitable,
                })
                print(f"    Q{q+1}: ann={stats['ann_return']:+.3f}, "
                      f"sharpe={stats['sharpe']:+.2f}, "
                      f"size={np.mean(quintile_sizes[q]):.0f}, "
                      f"IR_vs_uni={ir_vs_universe:+.2f}, "
                      f"IR_vs_prof={ir_vs_profitable:+.2f}")

            # Q5-Q1 spread
            q1_pr = np.array(quintile_returns[0], dtype=float)
            q5_pr = np.array(quintile_returns[4], dtype=float)
            if len(q1_pr) == len(q5_pr) and len(q1_pr) > 1:
                spread = q5_pr - q1_pr
                spread_ann = float(np.mean(spread) * cfg.PERIODS_PER_YEAR)
                spread_sharpe = (spread_ann
                                 / (np.std(spread, ddof=1) * np.sqrt(cfg.PERIODS_PER_YEAR))
                                 if np.std(spread, ddof=1) > 0 else np.nan)
                rows.append({
                    "factor": factor_name,
                    "universe": u,
                    "quintile": "Q5-Q1",
                    "ann_return": spread_ann,
                    "ann_vol": float(np.std(spread, ddof=1) * np.sqrt(cfg.PERIODS_PER_YEAR)),
                    "sharpe": spread_sharpe,
                    "max_dd": np.nan,
                    "n_periods": len(spread),
                    "mean_size": np.nan,
                    "ir_vs_universe": np.nan,
                    "ir_vs_profitable": np.nan,
                })
                print(f"    Q5-Q1: ann_spread={spread_ann:+.3f}, "
                      f"sharpe={spread_sharpe:+.2f}")

    out = pd.DataFrame(rows)
    out.to_csv(cfg.PHASE3_QUINTILE_PATH, index=False)
    print(f"\nSaved: {cfg.PHASE3_QUINTILE_PATH}")
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
