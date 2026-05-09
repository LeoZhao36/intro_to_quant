"""
phase2_backtest.py — Period-level buy-and-hold backtest sweep (40 cells).

For each (L, rank_type, N) ∈ L_VALUES × RANK_TYPES × N_VALUES (5×2×4=40):
  - For each γ rebalance Wednesday t:
      • Filter universe by liquidity floor (amount[t] ≥ 50000 千元)
      • Drop limit-locked at entry (close[entry] ≥ 0.998 × upper_limit proxy
        via pct_chg ≥ +9.8%)
      • Top-N by z_volrev_<L>_<rank> (in-universe, in-filter)
      • Compute period buy-and-hold open-to-open T+1 → T+1 next week
      • Compute churn vs prior basket; cost = churn × 0.0018
      • Net = gross − cost
      • Benchmark = liquidity-floor-filtered universe-EW
  - Annualize gross/net, compute IR, max DD, mean churn, mean basket size,
    mean unique L1 sectors, mean_max_sector_pct.
  - Block-bootstrap 95% CI on net IR (block_size=12, n_boot=10000) over
    per-period active returns.

Outputs:
  data/volume_reversal_phase2_summary.csv (40 rows)
  data/volume_reversal_phase2_period_returns.csv (~4280 rows)
  data/volume_reversal_basket_diagnostics.csv (~4280 rows)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import fr_config
from hypothesis_testing import block_bootstrap_ci


def _ir_statistic(active: np.ndarray) -> float:
    if len(active) < 2:
        return np.nan
    s = float(active.std())
    if s <= 0:
        return np.nan
    return float(active.mean() / s * np.sqrt(fr_config.PERIODS_PER_YEAR))


def _build_open_wide(daily_long: pd.DataFrame) -> pd.DataFrame:
    long = daily_long.copy()
    long["adj_open"] = long["open"] * long["adj_factor"]
    return long.pivot(index="trade_date", columns="ts_code",
                       values="adj_open").sort_index()


def _build_amount_wide(daily_long: pd.DataFrame) -> pd.DataFrame:
    return daily_long.pivot(index="trade_date", columns="ts_code",
                              values="amount").sort_index()


def _build_pctchg_wide(daily_long: pd.DataFrame) -> pd.DataFrame:
    return daily_long.pivot(index="trade_date", columns="ts_code",
                              values="pct_chg").sort_index()


def _max_drawdown(period_returns: np.ndarray) -> float:
    cum = np.cumprod(1.0 + period_returns)
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1.0
    return float(dd.min())


def _attach_sector_to_basket(basket: list[str],
                              sector_lookup: dict[str, str]) -> dict:
    sectors = [sector_lookup.get(t, "Unknown") for t in basket]
    if not sectors:
        return {"n_unique": 0, "max_sector_pct": np.nan}
    counts = pd.Series(sectors).value_counts()
    return {"n_unique": int(counts.size),
            "max_sector_pct": float(counts.iloc[0] / len(sectors))}


def run(panel: pd.DataFrame,
        universe_dict: dict[pd.Timestamp, set[str]],
        daily_long: pd.DataFrame,
        sector_lookup: dict[str, str] | None = None) -> dict:
    print("\n=== Phase 2: Backtest sweep (40 cells) ===")

    # Pre-build wide series (these are reused across cells)
    open_w = _build_open_wide(daily_long)
    amount_w = _build_amount_wide(daily_long)
    pctchg_w = _build_pctchg_wide(daily_long)
    trading_dates = open_w.index

    if sector_lookup is None:
        # Build a non-PIT lookup from current panel (we only need it for
        # basket diagnostics, not for residualisation; here a flat
        # date-blind lookup is fine since SW L1 changes rarely).
        latest_date = panel["rebalance_date"].max()
        latest = panel[panel["rebalance_date"] == latest_date]
        sector_lookup = dict(zip(latest["ts_code"], latest["industry_name"]))

    rebs = sorted(panel["rebalance_date"].unique())

    # For each rebalance date, pre-compute:
    #   - tradeable set after liquidity + entry-day limit-lock filter
    #   - entry/exit dates
    #   - benchmark (EW of filtered set) period return
    pre = {}
    for t in rebs:
        u = universe_dict.get(t, set())
        if not u:
            continue

        # Liquidity floor on rebalance day t
        if t not in amount_w.index:
            continue
        amt_t = amount_w.loc[t]
        liquid = amt_t[(amt_t >= fr_config.ENTRY_LIQUIDITY_FLOOR_QIANYUAN)
                       & amt_t.notna()].index
        liquid_in_u = sorted(set(liquid) & u)

        # Entry = next trading day after t, exit = entry + 5 trading days
        idx = trading_dates.searchsorted(t, side="right")
        if idx + 5 >= len(trading_dates):
            continue
        entry = trading_dates[idx]
        exit = trading_dates[idx + 5]

        # Limit-lock at entry: drop if pct_chg[entry] ≥ +9.8%
        if entry in pctchg_w.index:
            pct_entry = pctchg_w.loc[entry]
            limit_locked = set(pct_entry[pct_entry >= 9.8].dropna().index)
        else:
            limit_locked = set()
        tradeable = [t_ for t_ in liquid_in_u if t_ not in limit_locked]

        # Period buy-and-hold returns (per stock, vector over tradeable)
        if entry not in open_w.index or exit not in open_w.index:
            continue
        entry_p = open_w.loc[entry]
        exit_p = open_w.loc[exit]
        per_stock_ret = exit_p / entry_p - 1.0   # Series indexed by ts_code

        # Benchmark: EW of liquid_in_u (NOT limit-lock filtered) per spec §6.3
        bench_ret = per_stock_ret.loc[
            per_stock_ret.index.isin(liquid_in_u)
        ].dropna().mean()

        pre[t] = {
            "entry": entry,
            "exit": exit,
            "tradeable": tradeable,
            "liquid_in_u": liquid_in_u,
            "n_dropped_limitlock": len(liquid_in_u) - len(tradeable),
            "per_stock_ret": per_stock_ret,
            "bench_ret": float(bench_ret),
        }

    valid_rebs = [t for t in rebs if t in pre]
    print(f"  valid rebalance dates: {len(valid_rebs)}")
    bench_series = np.array([pre[t]["bench_ret"] for t in valid_rebs])
    pry = fr_config.PERIODS_PER_YEAR
    print(f"  universe-EW benchmark (period-level open-to-open T+1):")
    print(f"    ann_ret = {bench_series.mean()*pry:+.3f}, "
          f"ann_vol = {bench_series.std()*np.sqrt(pry):.3f}, "
          f"ann_sharpe = {bench_series.mean()/bench_series.std()*np.sqrt(pry):+.2f}")

    summary_rows = []
    period_rows = []
    diag_rows = []

    for L in fr_config.L_VALUES:
        for r in fr_config.RANK_TYPES:
            z_col = f"z_volrev_{L}_{r}"
            for N in fr_config.N_VALUES:
                prev_basket: set[str] = set()
                cell_period_ret_gross = []
                cell_period_ret_net = []
                cell_period_active_net = []
                cell_basket_sizes = []
                cell_churn = []
                cell_n_dropped = []
                cell_n_unique_sec = []
                cell_max_sec_pct = []

                for t in valid_rebs:
                    info = pre[t]
                    sub = panel[(panel["rebalance_date"] == t) &
                                (panel["ts_code"].isin(info["tradeable"]))
                                ].dropna(subset=[z_col])
                    if len(sub) == 0:
                        continue
                    top_n = sub.nlargest(min(N, len(sub)), z_col)
                    basket = top_n["ts_code"].tolist()
                    basket_set = set(basket)

                    rets = info["per_stock_ret"].loc[
                        info["per_stock_ret"].index.isin(basket)
                    ].dropna()
                    if len(rets) == 0:
                        continue
                    gross = float(rets.mean())

                    # Churn = fraction of basket replaced (new members) per spec §6.1.
                    # 0.0 if basket is unchanged from prior, 1.0 if fully replaced.
                    if prev_basket:
                        churn = len(basket_set - prev_basket) / max(
                            len(basket_set), 1
                        )
                    else:
                        churn = 1.0   # first period: everything is new
                    cost = churn * fr_config.COST_PER_TURNOVER
                    net = gross - cost
                    bench = info["bench_ret"]
                    active_net = net - bench

                    sec_diag = _attach_sector_to_basket(basket, sector_lookup)

                    cell_period_ret_gross.append(gross)
                    cell_period_ret_net.append(net)
                    cell_period_active_net.append(active_net)
                    cell_basket_sizes.append(len(basket))
                    cell_churn.append(churn)
                    cell_n_dropped.append(info["n_dropped_limitlock"])
                    cell_n_unique_sec.append(sec_diag["n_unique"])
                    cell_max_sec_pct.append(sec_diag["max_sector_pct"])

                    period_rows.append({
                        "period_start": info["entry"],
                        "period_end": info["exit"],
                        "rebalance_date": t,
                        "L": L, "N": N, "rank_type": r,
                        "basket_ret": gross,
                        "basket_ret_net": net,
                        "benchmark_ret": bench,
                        "churn": churn,
                        "active_net": active_net,
                        "basket_size": len(basket),
                    })

                    diag_rows.append({
                        "rebalance_date": t,
                        "L": L, "N": N, "rank_type": r,
                        "basket_size": len(basket),
                        "mean_score": float(top_n[z_col].mean()),
                        "top_5_tickers": ",".join(basket[:5]),
                        "max_sector_pct": sec_diag["max_sector_pct"],
                        "n_unique_sectors": sec_diag["n_unique"],
                        "n_dropped_limitlock": info["n_dropped_limitlock"],
                    })

                    prev_basket = basket_set

                # Aggregate cell stats
                if len(cell_period_ret_net) < 10:
                    continue
                pry = fr_config.PERIODS_PER_YEAR
                ann_gross = float(np.mean(cell_period_ret_gross) * pry)
                ann_net = float(np.mean(cell_period_ret_net) * pry)
                ann_vol = float(np.std(cell_period_ret_net) * np.sqrt(pry))
                sharpe_net = ann_net / ann_vol if ann_vol > 0 else np.nan
                active_arr = np.array(cell_period_active_net)
                ir_net = _ir_statistic(active_arr)
                te = float(active_arr.std() * np.sqrt(pry))
                ar_net = float(active_arr.mean() * pry)
                max_dd_net = _max_drawdown(np.array(cell_period_ret_net))

                if len(active_arr) >= 2 * fr_config.WEEKLY_BLOCK_SIZE:
                    boot = block_bootstrap_ci(
                        active_arr, _ir_statistic,
                        block_size=fr_config.WEEKLY_BLOCK_SIZE,
                        n_boot=fr_config.BOOT_N,
                        ci=0.95,
                        seed=fr_config.BOOT_SEED,
                    )
                    ir_lo = boot["ci_low"]
                    ir_hi = boot["ci_high"]
                else:
                    ir_lo = ir_hi = np.nan

                row = {
                    "L": L, "N": N, "rank_type": r,
                    "n_periods": len(cell_period_ret_net),
                    "ann_ret_gross": ann_gross,
                    "ann_ret_net": ann_net,
                    "ann_vol": ann_vol,
                    "sharpe_net": sharpe_net,
                    "active_ret_net": ar_net,
                    "tracking_error": te,
                    "ir_net": ir_net,
                    "ir_ci_low": ir_lo,
                    "ir_ci_high": ir_hi,
                    "max_dd_net": max_dd_net,
                    "mean_churn": float(np.mean(cell_churn)),
                    "mean_basket_size": float(np.mean(cell_basket_sizes)),
                    "mean_unique_sectors": float(np.mean(cell_n_unique_sec)),
                    "mean_max_sector_pct": float(
                        np.nanmean(cell_max_sec_pct)
                    ),
                    "mean_n_dropped_limitlock": float(
                        np.mean(cell_n_dropped)
                    ),
                }
                summary_rows.append(row)
                print(f"  L={L:2d} N={N:3d} {r:>2s}  "
                      f"ann_net={ann_net:+.3f}  IR={ir_net:+.2f}  "
                      f"CI=[{ir_lo:+.2f},{ir_hi:+.2f}]  "
                      f"DD={max_dd_net:+.2%}  churn={np.mean(cell_churn):.2f}")

    summary = pd.DataFrame(summary_rows)
    period_returns = pd.DataFrame(period_rows)
    diagnostics = pd.DataFrame(diag_rows)

    fr_config.DATA_OUT.mkdir(parents=True, exist_ok=True)
    summary.to_csv(
        fr_config.DATA_OUT / "volume_reversal_phase2_summary.csv",
        index=False,
    )
    period_returns.to_csv(
        fr_config.DATA_OUT / "volume_reversal_phase2_period_returns.csv",
        index=False,
    )
    diagnostics.to_csv(
        fr_config.DATA_OUT / "volume_reversal_basket_diagnostics.csv",
        index=False,
    )
    print(f"\n  → wrote 3 phase 2 CSVs to {fr_config.DATA_OUT}")
    return {"summary": summary, "period_returns": period_returns,
            "diagnostics": diagnostics}
