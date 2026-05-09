"""
phase1_ic.py — IC analysis across the 10 (L, rank_type) cells.

Per cell:
  - Per-date Spearman rank IC of z_volrev vs weekly_forward_return (in-universe)
  - Aggregate: mean, std, t, pct_positive
  - Block-bootstrap 95% CI on IC mean (block_size=12, n_boot=10000)
  - Quarterly breakdown
  - Side-output: ts vs cs Spearman correlation per date per L

Outputs:
  data/volume_reversal_phase1_ic.csv
  data/volume_reversal_phase1_ic_per_date.csv
  data/volume_reversal_phase1_ic_quarterly.csv
  data/volume_reversal_ranking_comparison.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import fr_config
from hypothesis_testing import block_bootstrap_ci


def _per_date_ic(panel: pd.DataFrame, z_col: str,
                 ret_col: str = "weekly_forward_return") -> pd.Series:
    df = panel.dropna(subset=[z_col, ret_col])
    df = df[df.get("in_universe", True)]
    return (
        df.groupby("rebalance_date")
        .apply(lambda g: g[z_col].corr(g[ret_col], method="spearman"),
               include_groups=False)
        .dropna()
        .sort_index()
    )


def run(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    print("\n=== Phase 1: IC analysis ===")
    summary_rows = []
    per_date_rows = []
    quarterly_rows = []

    for L in fr_config.L_VALUES:
        for r in fr_config.RANK_TYPES:
            z_col = f"z_volrev_{L}_{r}"
            ic = _per_date_ic(panel, z_col)
            n = len(ic)
            if n < 2 * fr_config.WEEKLY_BLOCK_SIZE:
                ci_low = ci_high = np.nan
            else:
                boot = block_bootstrap_ci(
                    ic.values, np.mean,
                    block_size=fr_config.WEEKLY_BLOCK_SIZE,
                    n_boot=fr_config.BOOT_N,
                    ci=0.95,
                    seed=fr_config.BOOT_SEED,
                )
                ci_low = boot["ci_low"]
                ci_high = boot["ci_high"]

            mean = float(ic.mean())
            std = float(ic.std())
            t_stat = mean / (std / np.sqrt(n)) if std > 0 else np.nan
            pos = float((ic > 0).mean())

            summary_rows.append({
                "L": L, "rank_type": r,
                "n_dates": n,
                "ic_mean": mean,
                "ic_std": std,
                "ic_t": t_stat,
                "ic_positive_pct": pos,
                "ic_ci_low": ci_low,
                "ic_ci_high": ci_high,
            })
            print(f"  L={L:2d} rank={r:>2s} n={n:3d}  "
                  f"IC={mean:+.4f}  t={t_stat:+.2f}  "
                  f"pos%={pos*100:4.1f}  "
                  f"CI=[{ci_low:+.4f},{ci_high:+.4f}]")

            for d, v in ic.items():
                per_date_rows.append({
                    "rebalance_date": d, "L": L, "rank_type": r, "ic": v,
                })

            # Quarterly breakdown
            q_idx = pd.PeriodIndex(ic.index, freq="Q")
            for q, ic_q in ic.groupby(q_idx):
                if len(ic_q) < 2:
                    continue
                q_mean = float(ic_q.mean())
                q_std = float(ic_q.std())
                q_n = int(len(ic_q))
                q_t = q_mean / (q_std / np.sqrt(q_n)) if q_std > 0 else np.nan
                quarterly_rows.append({
                    "quarter": str(q), "L": L, "rank_type": r,
                    "n_dates": q_n,
                    "ic_mean": q_mean,
                    "ic_t": q_t,
                })

    # Side output: ts vs cs ranking comparison per date
    rank_cmp_rows = []
    for L in fr_config.L_VALUES:
        ts_col = f"z_volrev_{L}_ts"
        cs_col = f"z_volrev_{L}_cs"
        for d, g in panel.groupby("rebalance_date"):
            sub = g[[ts_col, cs_col]].dropna()
            if len(sub) < 30:
                continue
            corr = sub[ts_col].corr(sub[cs_col], method="spearman")
            rank_cmp_rows.append({
                "rebalance_date": d, "L": L,
                "ts_cs_spearman_corr": float(corr),
            })

    summary = pd.DataFrame(summary_rows)
    per_date = pd.DataFrame(per_date_rows)
    quarterly = pd.DataFrame(quarterly_rows)
    rank_cmp = pd.DataFrame(rank_cmp_rows)

    fr_config.DATA_OUT.mkdir(parents=True, exist_ok=True)
    summary.to_csv(fr_config.DATA_OUT / "volume_reversal_phase1_ic.csv",
                    index=False)
    per_date.to_csv(
        fr_config.DATA_OUT / "volume_reversal_phase1_ic_per_date.csv",
        index=False,
    )
    quarterly.to_csv(
        fr_config.DATA_OUT / "volume_reversal_phase1_ic_quarterly.csv",
        index=False,
    )
    rank_cmp.to_csv(
        fr_config.DATA_OUT / "volume_reversal_ranking_comparison.csv",
        index=False,
    )

    print(f"\n  → wrote 4 phase 1 CSVs to {fr_config.DATA_OUT}")
    return {"summary": summary, "per_date": per_date,
            "quarterly": quarterly, "rank_cmp": rank_cmp}


if __name__ == "__main__":
    from data_loaders import (load_universe_dict, load_daily_panel_long,
                                attach_sector)
    from factor_volume_reversal import build_factor_panel

    udict = load_universe_dict(gamma_only=True)
    g_dates = sorted(udict.keys())
    end = max(g_dates)
    start = min(g_dates) - pd.Timedelta(days=120)
    dp = load_daily_panel_long(start, end)

    fpa = pd.read_parquet(fr_config.FACTOR_PANEL_A)
    fpa["rebalance_date"] = pd.to_datetime(fpa["rebalance_date"])
    fpa = fpa[fpa["rebalance_date"].isin(g_dates)]
    fpa = attach_sector(fpa)

    panel = build_factor_panel(g_dates, udict, dp, fpa, verbose=False)
    run(panel)
