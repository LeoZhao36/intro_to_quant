"""
late_panel_coverage.py — Per-rebalance RDI component coverage from 2026-02 onward.

Purpose: distinguish whether the universe-size collapse on the last 1–2
rebalances is a coverage artifact (some component data not yet available
for very-recent dates) or a real regime change (RDI cross-section truly
collapsed because eligibility shifted).

Reads rdi_components.parquet, hotspot_summary.csv (variant A and B), and
universe_membership_variantA/B.parquet.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np

import config


CUTOFF = pd.Timestamp("2026-02-01")


def main():
    rdi = pd.read_parquet(config.RDI_COMPONENTS_PATH)
    rdi["trade_date"] = pd.to_datetime(rdi["trade_date"])
    rdi = rdi[rdi["trade_date"] >= CUTOFF].copy()

    summary = pd.read_csv(config.DATA_DIR / "hotspot_summary.csv")
    summary["trade_date"] = pd.to_datetime(summary["trade_date"])
    summary = summary[summary["trade_date"] >= CUTOFF]

    # Per-rebalance stats
    rows: list[dict] = []
    for d, group in rdi.groupby("trade_date"):
        n_baseline = len(group)
        n_holders = int(group["rdi_holders"].notna().sum())
        n_funds = int(group["rdi_funds"].notna().sum())
        n_north = int(group["rdi_north"].notna().sum())
        n_smallorder = int(group["rdi_smallorder"].notna().sum())
        n_rdi = int(group["rdi_rank"].notna().sum())
        rows.append({
            "trade_date": d,
            "n_baseline": n_baseline,
            "n_holders": n_holders,
            "pct_holders": n_holders / n_baseline * 100,
            "n_funds": n_funds,
            "pct_funds": n_funds / n_baseline * 100,
            "n_north": n_north,
            "pct_north": n_north / n_baseline * 100,
            "n_smallorder": n_smallorder,
            "pct_smallorder": n_smallorder / n_baseline * 100,
            "n_rdi_rank": n_rdi,
            "pct_rdi_rank": n_rdi / n_baseline * 100,
        })
    cov = pd.DataFrame(rows).sort_values("trade_date")
    cov_path = config.DATA_DIR / "late_panel_coverage.csv"
    cov.to_csv(cov_path, index=False)
    print(f"wrote {cov_path}")

    # Print formatted table
    print(f"\n=== LATE-PANEL COVERAGE (rebalances from {CUTOFF.date()} onward) ===\n")
    print(f"{'date':>12} {'baseline':>9} "
          f"{'holders':>17} {'funds':>17} "
          f"{'north':>17} {'smallorder':>17} {'rdi_rank':>17}")
    for _, r in cov.iterrows():
        print(
            f"{r['trade_date'].strftime('%Y-%m-%d'):>12} "
            f"{r['n_baseline']:>9} "
            f"{r['n_holders']:>5} ({r['pct_holders']:>5.1f}%)   "
            f"{r['n_funds']:>5} ({r['pct_funds']:>5.1f}%)   "
            f"{r['n_north']:>5} ({r['pct_north']:>5.1f}%)   "
            f"{r['n_smallorder']:>5} ({r['pct_smallorder']:>5.1f}%)   "
            f"{r['n_rdi_rank']:>5} ({r['pct_rdi_rank']:>5.1f}%)"
        )

    print()
    print(f"{'date':>12} {'variant':>8} {'n_uni':>6} "
          f"{'centroid_cap':>14} {'centroid_rdi':>14}")
    for _, r in summary.sort_values(["trade_date", "variant"]).iterrows():
        print(
            f"{r['trade_date'].strftime('%Y-%m-%d'):>12} "
            f"{r['variant']:>8} "
            f"{int(r['n_in_universe']):>6} "
            f"{r['centroid_cap']:>14.3f} "
            f"{r['centroid_rdi']:>14.3f}"
        )

    # Diagnostic: identify which component drives the universe-size variation.
    print(f"\n=== COMPONENT-vs-UNIVERSE-SIZE ===")
    last_n = 8  # last ~8 rebalances
    cov_recent = cov.tail(last_n).copy()
    summA = summary[summary["variant"] == "A"].set_index("trade_date")
    summB = summary[summary["variant"] == "B"].set_index("trade_date")
    cov_recent = cov_recent.set_index("trade_date")
    cov_recent["n_uni_A"] = summA["n_in_universe"].reindex(cov_recent.index)
    cov_recent["n_uni_B"] = summB["n_in_universe"].reindex(cov_recent.index)
    print(cov_recent[[
        "n_baseline", "pct_holders", "pct_funds", "pct_north",
        "pct_smallorder", "n_uni_A", "n_uni_B",
    ]].round(1).to_string())

    # Conclusion criteria
    print(f"\n=== CONCLUSION ===")
    last_2 = cov.tail(2)
    earlier = cov.iloc[:-2] if len(cov) > 2 else cov
    if len(last_2) >= 1 and len(earlier) >= 1:
        for col in ("pct_holders", "pct_funds", "pct_north", "pct_smallorder"):
            mean_earlier = earlier[col].mean()
            last_2_min = last_2[col].min()
            drop = mean_earlier - last_2_min
            verdict = "SUSPECT" if drop > 5 else "STABLE"
            print(f"  {col:>16}: mean(earlier)={mean_earlier:5.1f}%  "
                  f"min(last 2)={last_2_min:5.1f}%  drop={drop:+.1f}pp  [{verdict}]")
    else:
        print(f"  insufficient rebalances since {CUTOFF.date()} for compare")


if __name__ == "__main__":
    main()
