"""
phase3_decomposition.py — Filter-vs-sort decomposition.

Phase 1 finding: EP and ROA on canonical were FALSIFIED. With negative-EP
NaN'd at construction, factor baskets only rank the ~55% profitable subset
while the universe-EW benchmark includes all stocks. The active return
therefore confounds:

  filter_effect = profitable_EW - universe_EW       (filter on profitability)
  sort_effect   = top10_factor - profitable_EW      (rank within profitable)

This script builds three baskets per (signal_date, universe):
  1. universe_EW   — all members
  2. profitable_EW — members with ttm_ni > 0  (i.e., ep is non-NaN positive)
  3. loss_maker_EW — members with ttm_ni <= 0 / NaN ep  (canonical only)

Period returns use the same buy-and-hold engine and headline cost regime
as Phase 2. Profitable-EW has churn from membership transitions
(profit→loss flips, new entrants); we capture this as turnover×cost.

NO sector cap on profitable-EW or loss-maker-EW (per spec section 7 Q1).

Outputs:
  data/phase3_decomposition_summary.csv  — one row per (universe, basket)
  decomposition values printed to phase3_verdicts.txt by the verdict step
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import data_loaders as dl
import fr3_config as cfg


def _annualize(period_returns: np.ndarray) -> dict:
    pr = period_returns[~np.isnan(period_returns)]
    if len(pr) < 2:
        return {"ann_return": np.nan, "ann_vol": np.nan, "sharpe": np.nan,
                "max_dd": np.nan, "n_periods": int(len(pr))}
    ann_ret = float(np.mean(pr) * cfg.PERIODS_PER_YEAR)
    ann_vol = float(np.std(pr, ddof=1) * np.sqrt(cfg.PERIODS_PER_YEAR))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    cum = np.cumprod(1 + pr)
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1.0
    return {
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": float(dd.min()),
        "n_periods": int(len(pr)),
    }


def _basket_period_return_simple(basket: list[str],
                                 entry_date: pd.Timestamp,
                                 exit_date: pd.Timestamp) -> float:
    """
    Equal-weight buy-and-hold. Returns NaN if entry or exit panel missing.
    Drops names without exit-day price (matches Phase 2 simple-bench engine
    convention; for filter/sort decomposition we don't apply Phase 2's
    delisting cash-out — we want clean filter-and-sort attribution).
    """
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


def _build_baskets(panel: pd.DataFrame, universe: str) -> dict:
    """
    Per signal_date for the given universe, return three basket lists:
      universe_codes, profitable_codes, loss_codes.

    'profitable' = ep is non-null (since we NaN'd ep at construction when
    pe_ttm <= 0, ep-non-null IS the profitable subset).
    'loss' = in universe AND ep is null.

    Returns: dict[signal_date] -> {entry, exit, universe, profitable, loss}
    """
    sub = panel[panel["universe"] == universe].copy()
    out = {}
    for s, g in sub.groupby("signal_date"):
        if g["entry_date"].isna().all():
            continue
        entry = g["entry_date"].iloc[0]
        exit_ = g["exit_date"].iloc[0]
        if pd.isna(entry) or pd.isna(exit_):
            continue
        all_codes = list(g["ts_code"])
        profitable = list(g.loc[g["ep"].notna(), "ts_code"])
        loss = list(g.loc[g["ep"].isna(), "ts_code"])
        out[s] = {
            "entry": entry,
            "exit": exit_,
            "universe": all_codes,
            "profitable": profitable,
            "loss": loss,
        }
    return out


def _churn(prev: set[str], curr: set[str]) -> float:
    if not prev:
        return 1.0
    return 1 - len(curr & prev) / max(len(curr), 1)


def _basket_period_returns_with_cost(
    baskets_by_signal: dict, basket_key: str
) -> pd.DataFrame:
    """
    Compute period gross + net returns for a named basket across all signals,
    applying churn × cost. Returns DataFrame [signal_date, gross, net, churn, n].
    """
    rows = []
    prev_basket: set[str] = set()
    for s in sorted(baskets_by_signal.keys()):
        rec = baskets_by_signal[s]
        basket = rec[basket_key]
        if not basket:
            continue
        gross = _basket_period_return_simple(basket, rec["entry"], rec["exit"])
        if pd.isna(gross):
            continue
        cur_set = set(basket)
        churn = _churn(prev_basket, cur_set)
        prev_basket = cur_set
        turnover = 2 * churn
        cost = turnover * cfg.COST_RT_HEADLINE
        net = gross - cost
        rows.append({
            "signal_date": s, "gross": gross, "net": net,
            "churn": churn, "n": len(basket),
        })
    return pd.DataFrame(rows)


def _topn_period_returns_from_phase2(
    factor: str, universe: str, top_n: int = cfg.HEADLINE_TOP_N
) -> pd.DataFrame:
    """Reuse Phase 2 period returns for the top-N basket."""
    pr = pd.read_csv(cfg.PHASE2_PERIOD_RETURNS_PATH)
    sub = pr[(pr["factor"] == factor)
             & (pr["universe"] == universe)
             & (pr["top_n"] == top_n)
             & (pr["cost_regime"] == "headline")].copy()
    sub = sub[["signal_date", "basket_return_gross", "basket_return_net"]]
    sub.columns = ["signal_date", "gross", "net"]
    sub["signal_date"] = pd.to_datetime(sub["signal_date"])
    return sub.reset_index(drop=True)


def run() -> tuple[pd.DataFrame, dict]:
    if not cfg.FACTOR_PANEL_PATH.exists():
        raise FileNotFoundError(f"missing factor panel: {cfg.FACTOR_PANEL_PATH}")
    panel = pd.read_parquet(cfg.FACTOR_PANEL_PATH)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    panel["entry_date"] = pd.to_datetime(panel["entry_date"])
    panel["exit_date"] = pd.to_datetime(panel["exit_date"])

    rows = []
    decomposition_values: dict = {}

    for universe in ("canonical", "csi300"):
        print(f"\n[{universe}]")
        baskets = _build_baskets(panel, universe)
        print(f"  signals: {len(baskets)}")

        # Universe-EW (with churn — small but non-zero from member transitions)
        u_df = _basket_period_returns_with_cost(baskets, "universe")
        u_stats = _annualize(u_df["net"].values)
        u_stats["universe"] = universe
        u_stats["basket_type"] = "universe_EW"
        u_stats["mean_n"] = float(u_df["n"].mean()) if len(u_df) else np.nan
        u_stats["mean_churn"] = float(u_df["churn"].mean()) if len(u_df) else np.nan
        rows.append(u_stats)
        print(f"  universe_EW:    n={u_stats['n_periods']}, "
              f"ann={u_stats['ann_return']:+.3f}, "
              f"sharpe={u_stats['sharpe']:+.2f}, "
              f"mdd={u_stats['max_dd']:.1%}, "
              f"size={u_stats['mean_n']:.0f}, "
              f"churn={u_stats['mean_churn']:.2%}")

        # Profitable-EW
        p_df = _basket_period_returns_with_cost(baskets, "profitable")
        p_stats = _annualize(p_df["net"].values)
        p_stats["universe"] = universe
        p_stats["basket_type"] = "profitable_EW"
        p_stats["mean_n"] = float(p_df["n"].mean()) if len(p_df) else np.nan
        p_stats["mean_churn"] = float(p_df["churn"].mean()) if len(p_df) else np.nan
        rows.append(p_stats)
        print(f"  profitable_EW:  n={p_stats['n_periods']}, "
              f"ann={p_stats['ann_return']:+.3f}, "
              f"sharpe={p_stats['sharpe']:+.2f}, "
              f"mdd={p_stats['max_dd']:.1%}, "
              f"size={p_stats['mean_n']:.0f}, "
              f"churn={p_stats['mean_churn']:.2%}")

        # Loss-maker-EW (canonical only — CSI300 has too few)
        if universe == "canonical":
            l_df = _basket_period_returns_with_cost(baskets, "loss")
            l_stats = _annualize(l_df["net"].values)
            l_stats["universe"] = universe
            l_stats["basket_type"] = "loss_maker_EW"
            l_stats["mean_n"] = float(l_df["n"].mean()) if len(l_df) else np.nan
            l_stats["mean_churn"] = float(l_df["churn"].mean()) if len(l_df) else np.nan
            rows.append(l_stats)
            print(f"  loss_maker_EW:  n={l_stats['n_periods']}, "
                  f"ann={l_stats['ann_return']:+.3f}, "
                  f"sharpe={l_stats['sharpe']:+.2f}, "
                  f"mdd={l_stats['max_dd']:.1%}, "
                  f"size={l_stats['mean_n']:.0f}, "
                  f"churn={l_stats['mean_churn']:.2%}")
        else:
            l_stats = None

        # Top-10 EP and ROA: read from Phase 2
        ep_top = _topn_period_returns_from_phase2("ep", universe)
        roa_top = _topn_period_returns_from_phase2("roa", universe)
        ep_stats = _annualize(ep_top["net"].values)
        ep_stats["universe"] = universe
        ep_stats["basket_type"] = "top10_ep"
        ep_stats["mean_n"] = cfg.HEADLINE_TOP_N
        ep_stats["mean_churn"] = np.nan
        rows.append(ep_stats)
        roa_stats = _annualize(roa_top["net"].values)
        roa_stats["universe"] = universe
        roa_stats["basket_type"] = "top10_roa"
        roa_stats["mean_n"] = cfg.HEADLINE_TOP_N
        roa_stats["mean_churn"] = np.nan
        rows.append(roa_stats)
        print(f"  top10_ep:       n={ep_stats['n_periods']}, "
              f"ann={ep_stats['ann_return']:+.3f}, "
              f"sharpe={ep_stats['sharpe']:+.2f}, "
              f"mdd={ep_stats['max_dd']:.1%}")
        print(f"  top10_roa:      n={roa_stats['n_periods']}, "
              f"ann={roa_stats['ann_return']:+.3f}, "
              f"sharpe={roa_stats['sharpe']:+.2f}, "
              f"mdd={roa_stats['max_dd']:.1%}")

        # Decomposition values
        u_ann = u_stats["ann_return"]
        p_ann = p_stats["ann_return"]
        ep_ann = ep_stats["ann_return"]
        roa_ann = roa_stats["ann_return"]
        filter_eff = p_ann - u_ann
        sort_ep = ep_ann - p_ann
        sort_roa = roa_ann - p_ann

        decomposition_values[universe] = {
            "universe_EW_ann": u_ann,
            "profitable_EW_ann": p_ann,
            "loss_maker_EW_ann": (l_stats["ann_return"] if l_stats else None),
            "top10_ep_ann": ep_ann,
            "top10_roa_ann": roa_ann,
            "filter_effect": filter_eff,
            "sort_effect_ep": sort_ep,
            "sort_effect_roa": sort_roa,
            "ep_total_active": ep_ann - u_ann,
            "roa_total_active": roa_ann - u_ann,
            "ep_decomp_residual": (filter_eff + sort_ep) - (ep_ann - u_ann),
            "roa_decomp_residual": (filter_eff + sort_roa) - (roa_ann - u_ann),
        }

        print(f"  filter_effect      = {filter_eff:+.3f}  (profitable_EW - universe_EW)")
        print(f"  sort_effect_ep     = {sort_ep:+.3f}  (top10_ep - profitable_EW)")
        print(f"  sort_effect_roa    = {sort_roa:+.3f}  (top10_roa - profitable_EW)")
        print(f"  ep_total_active    = {ep_ann - u_ann:+.3f}")
        print(f"  decomp consistency = {decomposition_values[universe]['ep_decomp_residual']:+.4f} "
              f"(should be ~0 — by construction additive)")

    out = pd.DataFrame(rows)
    out.to_csv(cfg.PHASE3_DECOMPOSITION_PATH, index=False)
    print(f"\nSaved: {cfg.PHASE3_DECOMPOSITION_PATH}")
    return out, decomposition_values


def main() -> None:
    run()


if __name__ == "__main__":
    main()
