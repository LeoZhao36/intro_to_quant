"""
Bottom-N liquidity diagnostic.

Reads Stage 1 candidate sets and Stage 2 liquidity panel, restricts to the
N smallest stocks by 流通市值 on each rebalance date, and produces a two-panel
diagnostic comparable to the full-universe one but focused on the actual
operating point of Stage 3 (the bottom-N by circ_mv_yi).

Top panel:    pass-rate-over-time for full universe vs bottom-N (overlay).
Bottom panel: pooled distribution of mean trailing-20-day amount within the
              bottom-N, with floor and quartile lines annotated.

Usage:
    python bottom1000_liquidity_diagnostic.py        # default N=1000
    python bottom1000_liquidity_diagnostic.py 500
"""

import sys
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


DATA_DIR = Path("data")
CANDIDATES_DIR = DATA_DIR / "candidates"
LIQUIDITY_PANEL = DATA_DIR / "liquidity_panel.csv"

LIQUIDITY_FLOOR_WAN = 3000


def load_bottom_n_per_date(n):
    """
    For each candidate CSV, take the N smallest by circ_mv_yi.
    Returns a long-format DataFrame: (rebalance_date, ts_code, circ_mv_yi).
    """
    rows = []
    for path in sorted(CANDIDATES_DIR.glob("candidates_*.csv")):
        date = path.stem.replace("candidates_", "")
        df = pd.read_csv(path, dtype={"ts_code": str})
        df = df.sort_values("circ_mv_yi").head(n)
        rows.append(pd.DataFrame({
            "rebalance_date": date,
            "ts_code": df["ts_code"].values,
            "circ_mv_yi": df["circ_mv_yi"].values,
        }))
    return pd.concat(rows, ignore_index=True)


def main(n):
    output_plot = DATA_DIR / f"liquidity_panel_bottom{n}_diagnostic.png"

    print(f"Bottom-{n} liquidity diagnostic")
    print("=" * 60)

    panel = pd.read_csv(LIQUIDITY_PANEL, dtype={"ts_code": str})
    print(f"  liquidity panel: {len(panel):,} (date, stock) rows")

    bottom = load_bottom_n_per_date(n)
    print(f"  bottom-{n} sets: {len(bottom):,} (date, stock) rows "
          f"across {bottom['rebalance_date'].nunique()} dates")

    # Left-join: keep every bottom-N stock even if it has no liquidity row
    # (full-window suspensions). Stocks without a row count as not passing.
    merged = bottom.merge(
        panel[["rebalance_date", "ts_code",
               "mean_amount_wan", "passes_3000_floor"]],
        on=["rebalance_date", "ts_code"],
        how="left",
    )
    merged["passes"] = merged["passes_3000_floor"].fillna(False)

    n_in_panel = int(merged["mean_amount_wan"].notna().sum())
    n_missing = int(merged["mean_amount_wan"].isna().sum())
    print(f"  in liquidity panel: {n_in_panel:,}")
    print(f"  full-window suspended (treated as not passing): {n_missing:,}")

    # Pass rate per date: full universe vs bottom-N
    full_pass = panel.groupby("rebalance_date")["passes_3000_floor"].mean() * 100
    bottom_pass = merged.groupby("rebalance_date")["passes"].mean() * 100

    # Plot
    fig, axes = plt.subplots(2, 1, figsize=(11, 8))

    axes[0].plot(
        pd.to_datetime(full_pass.index), full_pass.values,
        marker="o", markersize=3, linewidth=1,
        label="Full candidate universe",
    )
    axes[0].plot(
        pd.to_datetime(bottom_pass.index), bottom_pass.values,
        marker="o", markersize=3, linewidth=1,
        label=f"Bottom {n} by circ_mv",
    )
    axes[0].set_ylabel(f"% passing {LIQUIDITY_FLOOR_WAN}万 floor")
    axes[0].set_xlabel("Rebalance date")
    axes[0].set_title(
        f"Liquidity floor pass rate: full universe vs bottom-{n} "
        f"(floor = {LIQUIDITY_FLOOR_WAN}万 RMB/day, trailing 20-day mean)"
    )
    axes[0].legend(loc="lower right")
    axes[0].grid(True, alpha=0.3)
    axes[0].set_ylim(0, 100)

    # Bottom: distribution within bottom-N, log x-scale
    bottom_amounts = merged["mean_amount_wan"].dropna()
    p10 = bottom_amounts.quantile(0.10)
    p25 = bottom_amounts.quantile(0.25)
    p50 = bottom_amounts.quantile(0.50)
    p75 = bottom_amounts.quantile(0.75)

    axes[1].hist(
        bottom_amounts.clip(lower=1), bins=100,
        log=True, edgecolor="none",
    )
    axes[1].axvline(
        LIQUIDITY_FLOOR_WAN, color="red", linestyle="--",
        linewidth=1.5, label=f"{LIQUIDITY_FLOOR_WAN}万 floor",
    )
    axes[1].axvline(
        p50, color="green", linestyle=":", linewidth=1,
        label=f"P50 = {p50:,.0f}万",
    )
    axes[1].axvline(
        p25, color="orange", linestyle=":", linewidth=1,
        label=f"P25 = {p25:,.0f}万",
    )
    axes[1].axvline(
        p10, color="purple", linestyle=":", linewidth=1,
        label=f"P10 = {p10:,.0f}万",
    )
    axes[1].set_xscale("log")
    axes[1].set_xlabel("Mean trailing-20-day amount (万 RMB)")
    axes[1].set_ylabel("Count (log scale)")
    axes[1].set_title(
        f"Distribution of mean amount, bottom-{n} pooled across all dates"
    )
    axes[1].legend(loc="upper right")
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_plot, dpi=120)
    plt.close(fig)
    print(f"\n  plot saved to {output_plot}")

    # Summary
    print(f"\nBottom-{n} pass rate summary:")
    print(f"  min:    {bottom_pass.min():>5.1f}% ({bottom_pass.idxmin()})")
    print(f"  P25:    {bottom_pass.quantile(0.25):>5.1f}%")
    print(f"  median: {bottom_pass.median():>5.1f}%")
    print(f"  P75:    {bottom_pass.quantile(0.75):>5.1f}%")
    print(f"  max:    {bottom_pass.max():>5.1f}% ({bottom_pass.idxmax()})")

    print(f"\nFull-universe pass rate (for comparison):")
    print(f"  min:    {full_pass.min():>5.1f}% ({full_pass.idxmin()})")
    print(f"  median: {full_pass.median():>5.1f}%")
    print(f"  max:    {full_pass.max():>5.1f}% ({full_pass.idxmax()})")

    print(f"\nBottom-{n} mean_amount_wan distribution (pooled):")
    print(f"  P10: {p10:>10,.0f}")
    print(f"  P25: {p25:>10,.0f}")
    print(f"  P50: {p50:>10,.0f}")
    print(f"  P75: {p75:>10,.0f}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    main(n)