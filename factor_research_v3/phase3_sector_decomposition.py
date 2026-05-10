"""
phase3_sector_decomposition.py — Sector tilt vs selection on canonical top-10.

For each γ rebalance period, decompose top-10 (EP and ROA) basket active
return vs universe-EW into:

  sector_tilt_effect = Σ_s (basket_w[s] - profitable_universe_w[s])
                         × profitable_universe_sector_return[s]
  selection_effect   = total_basket_return - universe_EW_return - sector_tilt_effect

The benchmark for sector tilt is what the basket COULD have picked from,
which is the profitable subset (since the factor scores only profitable
names). Universe-EW is the headline benchmark.

NOTE: Active vs universe-EW = sector_tilt + selection + (filter_effect_period).
The filter_effect (profitable_EW - universe_EW per period) is a separate
component reported alongside.

Output:
  data/phase3_sector_decomposition.csv      (one row per factor × period)
  data/phase3_sector_decomposition_agg.csv  (aggregated across γ)
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import data_loaders as dl
import fr3_config as cfg


def _basket_period_return(basket: list[str],
                          entry_date: pd.Timestamp,
                          exit_date: pd.Timestamp,
                          returns_by_code: dict[str, float] | None = None) -> float:
    """Equal-weight buy-and-hold; can pass pre-computed returns to skip lookup."""
    if not basket:
        return np.nan
    if returns_by_code is not None:
        rs = [returns_by_code[c] for c in basket if c in returns_by_code]
        if not rs:
            return np.nan
        return float(np.mean(rs))
    p_entry = dl.load_daily_open_adj(entry_date)
    p_exit = dl.load_daily_open_adj(exit_date)
    if p_entry is None or p_exit is None:
        return np.nan
    common = p_entry.index.intersection(basket).intersection(p_exit.index)
    if len(common) == 0:
        return np.nan
    rets = p_exit.loc[common] / p_entry.loc[common] - 1.0
    return float(rets.mean())


def _stock_returns_for_period(entry_date, exit_date) -> dict[str, float]:
    """Per-ts_code open-to-open return for the holding period."""
    p_entry = dl.load_daily_open_adj(entry_date)
    p_exit = dl.load_daily_open_adj(exit_date)
    if p_entry is None or p_exit is None:
        return {}
    common = p_entry.index.intersection(p_exit.index)
    rets = p_exit.loc[common] / p_entry.loc[common] - 1.0
    return rets.to_dict()


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not cfg.FACTOR_PANEL_PATH.exists():
        raise FileNotFoundError(f"missing factor panel: {cfg.FACTOR_PANEL_PATH}")
    panel = pd.read_parquet(cfg.FACTOR_PANEL_PATH)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    panel["entry_date"] = pd.to_datetime(panel["entry_date"])
    panel["exit_date"] = pd.to_datetime(panel["exit_date"])

    # We only do canonical, top-10
    canon = panel[panel["universe"] == "canonical"].copy()
    pr = pd.read_csv(cfg.PHASE2_PERIOD_RETURNS_PATH)
    pr["signal_date"] = pd.to_datetime(pr["signal_date"])
    pr["entry_date"] = pd.to_datetime(pr["entry_date"])
    pr["exit_date"] = pd.to_datetime(pr["exit_date"])
    pr_canon = pr[(pr["universe"] == "canonical")
                  & (pr["top_n"] == cfg.HEADLINE_TOP_N)
                  & (pr["cost_regime"] == "headline")].copy()

    # Recover top-10 baskets per signal by re-applying the Phase 2 logic
    # (need the actual basket members for sector weights). Reuse the
    # Phase 2 builder.
    from phase2_backtest import _build_basket as build_basket

    rows = []
    for _, prow in pr_canon.iterrows():
        s = prow["signal_date"]
        entry = prow["entry_date"]
        exit_ = prow["exit_date"]
        if pd.isna(entry) or pd.isna(exit_):
            continue

        sig_panel = canon[canon["signal_date"] == s]
        ind_map = dl.load_industry_at(s)

        # Tradability on entry day
        ent_panel = dl.load_daily_panel(entry.strftime("%Y-%m-%d"))
        if ent_panel is None:
            continue
        tradable = set(ent_panel.index[
            (ent_panel["vol"] > 0) & (ent_panel["open"] > 0)
        ])

        for factor_name, factor_col in [("ep", "z_ep_resid"), ("roa", "z_roa_resid")]:
            basket, _diag = build_basket(
                sig_panel, factor_col, cfg.HEADLINE_TOP_N, ind_map, tradable
            )
            if not basket:
                continue

            # Profitable universe at this signal (for sector benchmark)
            prof = sig_panel.dropna(subset=["ep"])
            prof_codes = list(prof["ts_code"])
            all_codes = list(sig_panel["ts_code"])

            # Per-stock returns in period
            stock_rets = _stock_returns_for_period(entry, exit_)
            if not stock_rets:
                continue

            # Compute returns
            basket_ret = float(np.mean(
                [stock_rets[c] for c in basket if c in stock_rets]
            )) if any(c in stock_rets for c in basket) else np.nan
            uni_ret = float(np.mean(
                [stock_rets[c] for c in all_codes if c in stock_rets]
            )) if any(c in stock_rets for c in all_codes) else np.nan
            prof_ret = float(np.mean(
                [stock_rets[c] for c in prof_codes if c in stock_rets]
            )) if any(c in stock_rets for c in prof_codes) else np.nan

            # Sector weights and sector returns within profitable universe
            basket_industries = pd.Series([ind_map.get(c) for c in basket]).dropna()
            prof_industries = pd.Series([ind_map.get(c) for c in prof_codes]).dropna()

            n_b = len(basket_industries)
            n_p = len(prof_industries)
            sectors_in_basket = set(basket_industries.unique())
            sectors_in_prof = set(prof_industries.unique())
            all_sectors = sectors_in_basket | sectors_in_prof

            # Sector returns in profitable universe
            sec_returns = {}
            sec_prof_w = {}
            sec_basket_w = {}
            for sec in all_sectors:
                # Members of this sector in profitable universe
                members_prof = [c for c in prof_codes if ind_map.get(c) == sec]
                rs = [stock_rets[c] for c in members_prof if c in stock_rets]
                sec_returns[sec] = float(np.mean(rs)) if rs else 0.0
                sec_prof_w[sec] = len(members_prof) / n_p if n_p else 0.0
                # Basket weight
                members_b = [c for c in basket if ind_map.get(c) == sec]
                sec_basket_w[sec] = len(members_b) / n_b if n_b else 0.0

            # sector_tilt_effect: weighting differences × sector returns (within profitable benchmark)
            sector_tilt = sum(
                (sec_basket_w[s] - sec_prof_w[s]) * sec_returns[s]
                for s in all_sectors
            )

            # Active vs universe-EW
            active_vs_uni = basket_ret - uni_ret if pd.notna(basket_ret) and pd.notna(uni_ret) else np.nan
            # Filter effect for the period
            filter_eff_period = prof_ret - uni_ret if pd.notna(prof_ret) and pd.notna(uni_ret) else np.nan
            # Selection effect = active_vs_universe - filter_effect - sector_tilt
            #   ⇔ basket - profitable - sector_tilt
            # i.e., the residual of "basket vs profitable benchmark, sector-neutral"
            selection_eff = (basket_ret - prof_ret - sector_tilt
                             if pd.notna(basket_ret) and pd.notna(prof_ret)
                             else np.nan)

            rows.append({
                "factor": factor_name,
                "signal_date": s,
                "n_basket": n_b,
                "n_profitable": n_p,
                "basket_return": basket_ret,
                "universe_EW_return": uni_ret,
                "profitable_EW_return": prof_ret,
                "active_vs_universe": active_vs_uni,
                "filter_effect_period": filter_eff_period,
                "sector_tilt_effect": sector_tilt,
                "selection_effect": selection_eff,
                "decomp_residual": (active_vs_uni - filter_eff_period
                                     - sector_tilt - selection_eff)
                                    if pd.notna(active_vs_uni) else np.nan,
            })

    out = pd.DataFrame(rows)
    out.to_csv(cfg.PHASE3_SECTOR_PERIOD_PATH, index=False)
    print(f"Saved per-period: {cfg.PHASE3_SECTOR_PERIOD_PATH}")

    # Aggregate to annualised
    agg_rows = []
    for fac, g in out.groupby("factor"):
        # Sum-of-period-returns × periods_per_year for additive components.
        # For an additive geometric-vs-arithmetic check use means × periods/yr.
        n = len(g)
        ann = lambda col: float(g[col].mean() * cfg.PERIODS_PER_YEAR)
        agg_rows.append({
            "factor": fac,
            "n_periods": n,
            "ann_active_vs_universe": ann("active_vs_universe"),
            "ann_filter_effect": ann("filter_effect_period"),
            "ann_sector_tilt_effect": ann("sector_tilt_effect"),
            "ann_selection_effect": ann("selection_effect"),
            "ann_decomp_residual": ann("decomp_residual"),
        })
    agg = pd.DataFrame(agg_rows)
    agg.to_csv(cfg.PHASE3_SECTOR_AGG_PATH, index=False)
    print(f"Saved aggregate: {cfg.PHASE3_SECTOR_AGG_PATH}")
    print("\nAggregate decomposition (canonical, top-10, headline):")
    for _, r in agg.iterrows():
        print(f"  [{r['factor']:>3s}] active_vs_universe = {r['ann_active_vs_universe']:+.3f}")
        print(f"          filter_effect      = {r['ann_filter_effect']:+.3f}")
        print(f"          sector_tilt_effect = {r['ann_sector_tilt_effect']:+.3f}")
        print(f"          selection_effect   = {r['ann_selection_effect']:+.3f}")
        print(f"          decomp_residual    = {r['ann_decomp_residual']:+.4f}")
    return out, agg


def main() -> None:
    run()


if __name__ == "__main__":
    main()
