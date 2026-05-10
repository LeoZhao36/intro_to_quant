"""
phase2_backtest.py — Period-level buy-and-hold backtest with all v3 conventions.

Per (factor ∈ {ep, roa}, universe ∈ {canonical, csi300}, top_n, cost_regime):

  At each monthly signal_date:
  1. Rank universe candidates by residualised factor (descending).
  2. Greedy fill respecting:
     - Hard 20% sector cap (max floor(0.20 × top_n) per SW L1)
     - Tradability check on entry_date (vol > 0)
     If under-filled, accept and log (Q6 decision).
  3. Equal-weight buy-and-hold from entry_date open to next entry_date open.
  4. Forward return = (open[exit] × adj[exit]) / (open[entry] × adj[entry]) - 1.
  5. Delisting handling: if exit-day adj_open is missing, walk back through
     the holding period to find the most recent adj_close for that ts_code;
     use that as the realized exit price (Q4 decision: cash out at last
     available close).
  6. Cost: round-trip × turnover_rate per period. Turnover = 2 × (1 - overlap_with_prior).
     (Initial period has churn=0; first entry's setup cost is reported separately
      but applied in the same way: turnover=1.0 = full buy.)

Outputs:
  data/phase2_summary.csv             — one row per cell
  data/phase2_period_returns.csv      — period-level basket+benchmark+churn
  data/phase2_basket_diagnostics.csv  — per-period basket composition stats
"""

from __future__ import annotations

import sys
from collections import Counter

import numpy as np
import pandas as pd

import data_loaders as dl
import fr3_config as cfg
from hypothesis_testing import block_bootstrap_ci

FACTORS = [
    ("ep", "z_ep_resid"),
    ("roa", "z_roa_resid"),
]


# ─── Basket construction ───────────────────────────────────────────────

def _build_basket(panel_at_signal: pd.DataFrame,
                  factor_col: str,
                  top_n: int,
                  industry_map: pd.Series,
                  tradable_codes: set[str]) -> tuple[list[str], dict]:
    """
    Greedy fill respecting hard sector cap + entry-day tradability.

    Returns (basket_list, diagnostics) where diagnostics has:
      n_eligible, n_basket, max_sector_pct, cap_bind, sector_counts (dict)
    """
    cap_k = cfg.sector_cap_k(top_n)
    eligible = panel_at_signal.dropna(subset=[factor_col]).copy()
    eligible = eligible[eligible["ts_code"].isin(tradable_codes)]
    eligible = eligible.sort_values(factor_col, ascending=False)

    basket: list[str] = []
    sector_count: Counter = Counter()
    n_replacements = 0  # count of skips due to cap
    for _, row in eligible.iterrows():
        ts = row["ts_code"]
        sec = industry_map.get(ts)
        if pd.isna(sec):
            continue
        if sector_count[sec] >= cap_k:
            n_replacements += 1
            continue
        basket.append(ts)
        sector_count[sec] += 1
        if len(basket) >= top_n:
            break

    n_basket = len(basket)
    max_pct = (max(sector_count.values()) / n_basket) if n_basket else 0.0
    diagnostics = {
        "n_eligible": int(len(eligible)),
        "n_basket": n_basket,
        "max_sector_pct": float(max_pct),
        "cap_bind": int(any(v >= cap_k for v in sector_count.values())),
        "sector_count": dict(sector_count),
        "n_replacements_cap": n_replacements,
    }
    return basket, diagnostics


# ─── Buy-and-hold with delisting cash-out ──────────────────────────────

def _basket_period_return(basket: list[str],
                          entry_date: pd.Timestamp,
                          exit_date: pd.Timestamp,
                          cal: tuple) -> dict:
    """
    Compute equal-weight basket period return with delisting cash-out.

    For each ts_code in basket:
      adj_open[entry] is required (skipped at basket-build if not tradable)
      adj_open[exit]:
        - if present: realized return = exit/entry - 1
        - if missing: scan back through holding period for last adj_close;
          realized return = last_close/entry - 1 (cash from delisting to exit)
        - if no adj_close anywhere in window: drop from average

    Returns {ret, n_held, n_delisted, mean_delisting_loss}.
    """
    if not basket:
        return {"ret": np.nan, "n_held": 0, "n_delisted": 0,
                "mean_delisting_loss": np.nan}

    p_entry = dl.load_daily_open_adj(entry_date)
    p_exit = dl.load_daily_open_adj(exit_date)
    if p_entry is None:
        return {"ret": np.nan, "n_held": 0, "n_delisted": 0,
                "mean_delisting_loss": np.nan}

    rets: list[float] = []
    delisted: list[float] = []  # realized losses for delisted names

    # Pre-compute holding-period dates for delisting walk-back
    cal_list = list(cal)
    import bisect
    lo = bisect.bisect_left(cal_list, entry_date)
    hi = bisect.bisect_left(cal_list, exit_date)
    hold_dates = cal_list[lo:hi]  # entry_date inclusive, exit_date exclusive

    for ts in basket:
        if ts not in p_entry.index:
            # Shouldn't happen given tradable check; defensive skip
            continue
        e = p_entry.loc[ts]
        if p_exit is not None and ts in p_exit.index:
            r = float(p_exit.loc[ts] / e - 1.0)
            rets.append(r)
        else:
            # Delisting case: walk back through hold_dates for last adj_close
            last_close = None
            for d in reversed(hold_dates):
                cs = dl.load_daily_close_adj(d)
                if cs is not None and ts in cs.index:
                    last_close = float(cs.loc[ts])
                    break
            if last_close is None:
                # No close in window — drop entirely
                continue
            r = float(last_close / e - 1.0)
            rets.append(r)
            delisted.append(r)

    if not rets:
        return {"ret": np.nan, "n_held": 0, "n_delisted": 0,
                "mean_delisting_loss": np.nan}
    return {
        "ret": float(np.mean(rets)),
        "n_held": len(rets),
        "n_delisted": len(delisted),
        "mean_delisting_loss": float(np.mean(delisted)) if delisted else np.nan,
    }


def _benchmark_period_return(universe_codes: set[str],
                             entry_date: pd.Timestamp,
                             exit_date: pd.Timestamp,
                             cal: tuple) -> float:
    """Equal-weight benchmark return using same buy-and-hold engine."""
    res = _basket_period_return(list(universe_codes), entry_date, exit_date, cal)
    return res["ret"]


# ─── Run ───────────────────────────────────────────────────────────────

def _annualize(period_returns: np.ndarray) -> dict:
    """Compute annualized stats from monthly period returns."""
    pr = period_returns[~np.isnan(period_returns)]
    if len(pr) < 2:
        return {"ann_return": np.nan, "ann_vol": np.nan, "sharpe": np.nan,
                "max_dd": np.nan}
    ann_ret = float(np.mean(pr) * cfg.PERIODS_PER_YEAR)
    ann_vol = float(np.std(pr, ddof=1) * np.sqrt(cfg.PERIODS_PER_YEAR))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    cum = np.cumprod(1 + pr)
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1.0
    max_dd = float(dd.min())
    return {"ann_return": ann_ret, "ann_vol": ann_vol,
            "sharpe": sharpe, "max_dd": max_dd}


def run() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the full Phase 2 sweep."""
    if not cfg.FACTOR_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"Factor panel missing: {cfg.FACTOR_PANEL_PATH}. Run factor_panel.py first."
        )
    panel = pd.read_parquet(cfg.FACTOR_PANEL_PATH)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    panel["entry_date"] = pd.to_datetime(panel["entry_date"])
    panel["exit_date"] = pd.to_datetime(panel["exit_date"])

    cal = dl.load_trading_calendar()
    summaries = []
    period_rows = []
    diag_rows = []

    for factor_name, factor_col in FACTORS:
        for u in panel["universe"].unique():
            sub = panel[panel["universe"] == u].copy()
            for top_n in cfg.TOP_N_SWEEP:
                for regime, cost_rt in cfg.COST_REGIMES.items():
                    cell = f"{factor_name} × {u} × top{top_n} × {regime}"
                    print(f"  {cell}...", end=" ", flush=True)
                    period_returns_g = []
                    period_returns_n = []
                    bench_returns = []

                    prev_basket: set[str] = set()
                    triples = (sub[["signal_date", "entry_date", "exit_date"]]
                               .drop_duplicates().sort_values("signal_date"))

                    for _, t in triples.iterrows():
                        s = t["signal_date"]
                        e = t["entry_date"]
                        x = t["exit_date"]
                        if pd.isna(e) or pd.isna(x):
                            continue
                        sig_panel = sub[sub["signal_date"] == s]
                        universe_codes = set(sig_panel["ts_code"])
                        ind_map = dl.load_industry_at(s)
                        # tradability on entry day
                        ent_panel = dl.load_daily_panel(e.strftime("%Y-%m-%d"))
                        if ent_panel is None:
                            continue
                        tradable = set(ent_panel.index[
                            (ent_panel["vol"] > 0) & (ent_panel["open"] > 0)
                        ])

                        basket, diag = _build_basket(
                            sig_panel, factor_col, top_n,
                            ind_map, tradable,
                        )
                        if not basket:
                            continue

                        bres = _basket_period_return(basket, e, x, cal)
                        gross = bres["ret"]
                        if pd.isna(gross):
                            continue

                        # Churn / turnover
                        cur = set(basket)
                        if not prev_basket:
                            churn = 1.0  # full buy
                        else:
                            overlap = len(cur & prev_basket) / max(len(cur), 1)
                            churn = 1 - overlap
                        prev_basket = cur

                        # Round-trip cost: full sell + full buy = 2 × churn
                        # (turnover ratio = 2 × churn)
                        turnover = 2 * churn
                        cost = turnover * cost_rt
                        net = gross - cost

                        bench = _benchmark_period_return(universe_codes, e, x, cal)

                        period_returns_g.append(gross)
                        period_returns_n.append(net)
                        bench_returns.append(bench)

                        period_rows.append({
                            "factor": factor_name,
                            "universe": u,
                            "top_n": top_n,
                            "cost_regime": regime,
                            "signal_date": s,
                            "entry_date": e,
                            "exit_date": x,
                            "basket_return_gross": gross,
                            "basket_return_net": net,
                            "benchmark_return": bench,
                            "churn": churn,
                            "turnover": turnover,
                            "cost": cost,
                            "n_held": bres["n_held"],
                            "n_basket": diag["n_basket"],
                            "max_sector_pct": diag["max_sector_pct"],
                            "cap_bind": diag["cap_bind"],
                            "n_delisted": bres["n_delisted"],
                            "mean_delisting_loss": bres["mean_delisting_loss"],
                            "n_eligible": diag["n_eligible"],
                        })
                        diag_rows.append({
                            "factor": factor_name,
                            "universe": u,
                            "top_n": top_n,
                            "cost_regime": regime,
                            "signal_date": s,
                            "n_basket": diag["n_basket"],
                            "max_sector_pct": diag["max_sector_pct"],
                            "cap_bind": diag["cap_bind"],
                            "n_replacements_cap": diag["n_replacements_cap"],
                            "top_3_sectors": ", ".join(
                                f"{k}:{v}"
                                for k, v in sorted(
                                    diag["sector_count"].items(),
                                    key=lambda kv: -kv[1]
                                )[:3]
                            ),
                        })

                    pr_g = np.array(period_returns_g, dtype=float)
                    pr_n = np.array(period_returns_n, dtype=float)
                    pr_b = np.array(bench_returns, dtype=float)
                    active_n = pr_n - pr_b

                    stats_n = _annualize(pr_n)
                    stats_b = _annualize(pr_b)
                    n_periods = len(pr_n)

                    if n_periods >= 2 * cfg.BOOT_BLOCK_SIZE and len(active_n) > 0:
                        ir_boot = block_bootstrap_ci(
                            active_n,
                            lambda v: (np.mean(v) / np.std(v, ddof=1) *
                                       np.sqrt(cfg.PERIODS_PER_YEAR))
                            if np.std(v, ddof=1) > 0 else np.nan,
                            block_size=cfg.BOOT_BLOCK_SIZE,
                            n_boot=cfg.BOOT_N,
                            seed=42,
                        )
                        ir_low = ir_boot["ci_low"]
                        ir_high = ir_boot["ci_high"]
                    else:
                        ir_low = np.nan
                        ir_high = np.nan

                    if np.std(active_n, ddof=1) > 0 and len(active_n) > 1:
                        ir_vs_bench = float(
                            np.mean(active_n) / np.std(active_n, ddof=1)
                            * np.sqrt(cfg.PERIODS_PER_YEAR)
                        )
                    else:
                        ir_vs_bench = np.nan

                    summaries.append({
                        "factor": factor_name,
                        "universe": u,
                        "top_n": top_n,
                        "cost_regime": regime,
                        "n_periods": n_periods,
                        "ann_return_gross": _annualize(pr_g)["ann_return"],
                        "ann_return_net": stats_n["ann_return"],
                        "ann_vol": stats_n["ann_vol"],
                        "sharpe": stats_n["sharpe"],
                        "max_drawdown": stats_n["max_dd"],
                        "ir_vs_benchmark": ir_vs_bench,
                        "ir_ci_low": ir_low,
                        "ir_ci_high": ir_high,
                        "benchmark_ann_return": stats_b["ann_return"],
                        "benchmark_ann_vol": stats_b["ann_vol"],
                        "benchmark_sharpe": stats_b["sharpe"],
                        "benchmark_max_dd": stats_b["max_dd"],
                        "mean_churn": float(np.mean([r["churn"] for r in period_rows
                                                      if r["factor"] == factor_name
                                                      and r["universe"] == u
                                                      and r["top_n"] == top_n
                                                      and r["cost_regime"] == regime]))
                                       if period_rows else np.nan,
                    })
                    print(f"n={n_periods}, sharpe={stats_n['sharpe']:.2f}, "
                          f"IR={ir_vs_bench:.2f}, mdd={stats_n['max_dd']:.1%}")

    summary_df = pd.DataFrame(summaries)
    period_df = pd.DataFrame(period_rows)
    diag_df = pd.DataFrame(diag_rows)

    summary_df.to_csv(cfg.PHASE2_SUMMARY_PATH, index=False)
    period_df.to_csv(cfg.PHASE2_PERIOD_RETURNS_PATH, index=False)
    diag_df.to_csv(cfg.PHASE2_BASKET_DIAGNOSTICS_PATH, index=False)
    print(f"\nSaved: {cfg.PHASE2_SUMMARY_PATH}")
    print(f"Saved: {cfg.PHASE2_PERIOD_RETURNS_PATH}")
    print(f"Saved: {cfg.PHASE2_BASKET_DIAGNOSTICS_PATH}")
    return summary_df, period_df, diag_df


def main() -> None:
    run()


if __name__ == "__main__":
    main()
