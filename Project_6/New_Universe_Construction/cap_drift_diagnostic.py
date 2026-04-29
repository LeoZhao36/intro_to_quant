"""
cap_drift_diagnostic.py — Investigate the late-panel universe cap drift.

The Stage 3 diagnostic plot showed universe-mean circ_mv_yi rising from
~20亿 in 2019 to ~35亿 in 2026, with the 95th percentile climbing from
~33亿 to ~50亿. Two possible mechanisms:

  A. Market-wide cap inflation: the whole A-share market got more
     expensive, so the bottom-1000 stocks by cap are absolutely larger
     even though they remain the smallest cohort of their period.
     Benign; universe construction is regime-stable.

  B. Liquidity-driven drift: the X=75 percentile gate became more
     selective in absolute terms in high-liquidity regimes, pushing out
     smaller stocks and leaving a sample with relatively larger caps.
     Means (X, Y) is regime-sensitive.

Test
----
For each rebalance date, compute:
  - universe_mean_cap:  mean circ_mv_yi of in_universe rows
  - base_mean_cap:      mean circ_mv_yi of all valid candidates
                        (full A-share base, no filters except basic edge cases)
  - cap_ratio = universe_mean_cap / base_mean_cap

Reading the result:
  - cap_ratio stable over time            -> mechanism A (benign)
  - cap_ratio rises in late panel         -> mechanism B (parameter-driven)
  - cap_ratio falls in late panel         -> our universe got relatively
                                              smaller within an inflating market
                                              (also benign, just unexpected)

Output
------
data/cap_drift_diagnostic.png

Usage
-----
    python cap_drift_diagnostic.py
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

try:
    import Project_6.New_Universe_Construction.plot_setup as plot_setup  # noqa: F401
except ImportError:
    pass


DATA_DIR = Path("data")
PANEL_DIR = DATA_DIR / "daily_panel"
UNIVERSE_PATH = DATA_DIR / "universe_membership_X75_Y3000.parquet"
REBALANCE_DATES_PATH = DATA_DIR / "weekly_rebalance_dates.csv"
OUTPUT_PLOT = DATA_DIR / "cap_drift_diagnostic.png"


def main():
    if not UNIVERSE_PATH.exists():
        print(f"ERROR: {UNIVERSE_PATH} not found. Run Stage 3 full first.")
        sys.exit(1)

    print(f"Loading universe membership...")
    universe = pd.read_parquet(UNIVERSE_PATH)
    rebalance_dates = pd.read_csv(REBALANCE_DATES_PATH)["date"].tolist()
    print(f"  {len(rebalance_dates)} weekly rebalance dates")

    # For each date, compute universe-mean cap from the membership file
    # and base-mean cap from the daily panel for that date.
    records = []
    for i, date in enumerate(rebalance_dates, 1):
        # Universe-mean cap: rows where in_universe is True
        u = universe[(universe["rebalance_date"] == date) & universe["in_universe"]]
        if len(u) == 0:
            continue
        universe_mean = u["circ_mv_yi"].mean()
        universe_p95 = u["circ_mv_yi"].quantile(0.95)

        # Base-mean cap: read daily panel parquet, take mean of all
        # circ_mv_yi (excluding NaN and zero, which are not real values).
        # circ_mv in panel is in 万元; divide by 10,000 to get 亿元.
        panel_path = PANEL_DIR / f"daily_{date}.parquet"
        if not panel_path.exists():
            continue
        panel = pd.read_parquet(panel_path, columns=["circ_mv"])
        panel = panel.dropna(subset=["circ_mv"])
        panel = panel[panel["circ_mv"] > 0]
        panel["circ_mv_yi"] = panel["circ_mv"] / 10_000.0
        base_mean = panel["circ_mv_yi"].mean()
        base_p95 = panel["circ_mv_yi"].quantile(0.95)

        records.append({
            "rebalance_date": date,
            "universe_mean": universe_mean,
            "universe_p95": universe_p95,
            "base_mean": base_mean,
            "base_p95": base_p95,
            "ratio_mean": universe_mean / base_mean,
            "ratio_p95": universe_p95 / base_p95,
        })

        if i % 50 == 0 or i == len(rebalance_dates):
            print(f"  [{i}/{len(rebalance_dates)}] {date}: "
                  f"universe_mean={universe_mean:.1f}亿, base_mean={base_mean:.1f}亿, "
                  f"ratio={universe_mean / base_mean:.4f}")

    df = pd.DataFrame(records)
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"])

    # Build 2-panel plot: absolute caps over time, then ratio over time.
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)

    # Panel 1: absolute mean caps
    ax = axes[0]
    ax.plot(df["rebalance_date"], df["universe_mean"],
            label="Universe mean cap", color="C0", linewidth=1.5)
    ax.plot(df["rebalance_date"], df["base_mean"],
            label="Full A-share base mean cap", color="C2", linewidth=1.5)
    ax.set_ylabel("Mean circulating market cap (亿 RMB)")
    ax.set_title("Universe-cap vs A-share base-cap over time")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)

    # Panel 2: the ratio (the actual diagnostic)
    ax = axes[1]
    ax.plot(df["rebalance_date"], df["ratio_mean"],
            label="Mean ratio (universe / base)", color="C0", linewidth=1.5)
    ax.plot(df["rebalance_date"], df["ratio_p95"],
            label="95th pct ratio (universe / base)", color="C2", linewidth=1.5,
            alpha=0.6)

    # Reference lines: ratio at panel start vs end
    start_ratio = df["ratio_mean"].iloc[:5].mean()  # avg over first 5 weeks
    end_ratio = df["ratio_mean"].iloc[-5:].mean()  # avg over last 5 weeks
    ax.axhline(start_ratio, color="gray", linestyle=":", linewidth=1, alpha=0.5,
               label=f"Panel start avg: {start_ratio:.4f}")
    ax.axhline(end_ratio, color="black", linestyle=":", linewidth=1, alpha=0.5,
               label=f"Panel end avg: {end_ratio:.4f}")
    ax.set_xlabel("Rebalance date")
    ax.set_ylabel("Universe cap / Base cap")
    ax.set_title("Ratio diagnostic: stable = benign drift, rising = parameter-driven")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(OUTPUT_PLOT, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"\nWrote diagnostic plot -> {OUTPUT_PLOT}")

    # Headline diagnostic
    pct_change = 100 * (end_ratio - start_ratio) / start_ratio
    print(f"\n=== Diagnostic verdict ===")
    print(f"  Panel-start mean ratio:  {start_ratio:.4f}")
    print(f"  Panel-end mean ratio:    {end_ratio:.4f}")
    print(f"  Change:                  {pct_change:+.1f}%")
    if abs(pct_change) < 10:
        print(f"  Verdict: BENIGN (mechanism A) — cap drift is market-wide;")
        print(f"           the universe maintains its relative size cohort.")
    elif pct_change > 10:
        print(f"  Verdict: PARAMETER-DRIVEN (mechanism B) — universe got")
        print(f"           relatively LARGER over the panel; (X, Y) tuple")
        print(f"           is regime-sensitive in the high-liquidity regime.")
    else:
        print(f"  Verdict: REVERSE DRIFT — universe got relatively SMALLER")
        print(f"           over the panel, opposite of expected. Investigate.")


if __name__ == "__main__":
    main()