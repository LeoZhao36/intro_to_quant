"""
size_analysis.py

Project 6: complete size-factor analysis pipeline. Replaces the original
size_pipeline.py + size_robustness.py + size_robustness_pass2.py with a
single thin script that delegates all logic to factor_utils.py.

Run from Project_6/ as: `python size_analysis.py`

Verification: this should reproduce the size-factor numbers from the
Project 6 Session 2 closeout exactly. If outputs differ, the refactor
introduced a behaviour change that needs investigating before proceeding
to other factors.

Expected numbers (from closeout):
  Headline Q1-Q5: -0.181%/month, IC mean: +0.0153
  Layer 1: Q1-Q5 95% CI [-0.895%, +0.616%]
           IC    95% CI [-0.0088, +0.0377]
  Layer 2: pre  -0.260%/month (n=32)
           post -0.049%/month (n=19)
  Layer 3: tradable Q1-Q5 -0.160%/month, CI [-0.873%, +0.642%]
  Layer 4: sector-neutral Q1-Q5 -0.136%/month, CI [-0.847%, +0.656%]
  Layer 5: low p=0.878, mid p=0.080, high p=0.674
"""

from pathlib import Path

import matplotlib.pyplot as plt

from factor_utils import (
    GRAPHS_DIR,
    load_panel,
    compute_quintile_series,
    compute_ic_series,
    summarise_long_short,
    layer_1_bootstrap_ci,
    layer_2_regime_split,
    layer_3_tradable_only,
    layer_4_sector_neutral,
    layer_5_cap_terciles,
    plot_cumulative_quintiles,
    plot_ic_series,
)


# Factor configuration ----------------------------------------------------
FACTOR_COL = "log_mcap"
FACTOR_LABEL = "log market cap"
OUTPUT_PREFIX = "size"


if __name__ == "__main__":
    # Load and prepare ---------------------------------------------------
    panel = load_panel()
    print(
        f"Panel loaded: {len(panel):,} rows, "
        f"{panel['rebalance_date'].nunique()} dates"
    )
    # log_mcap is added by load_panel(), so size needs no further factor prep.

    # Headline -----------------------------------------------------------
    print("\n" + "=" * 72)
    print("Headline (Session 1 baseline)")
    print("=" * 72)
    quintiles = compute_quintile_series(panel, sort_col=FACTOR_COL)
    headline = summarise_long_short(quintiles, "headline Q1-Q5")
    ic = compute_ic_series(panel, sort_col=FACTOR_COL)
    print(f"  IC: mean={ic.mean():+.4f}, std={ic.std():.4f}, n={len(ic)}")

    # Plots --------------------------------------------------------------
    plot_cumulative_quintiles(
        quintiles, FACTOR_LABEL,
        save_path=GRAPHS_DIR / f"{OUTPUT_PREFIX}_quintile_cumulative_returns.png",
    )
    plot_ic_series(
        ic, FACTOR_LABEL,
        save_path=GRAPHS_DIR / f"{OUTPUT_PREFIX}_ic_time_series.png",
    )

    # Pass 1 robustness --------------------------------------------------
    layer_1 = layer_1_bootstrap_ci(panel, factor_col=FACTOR_COL)
    layer_2 = layer_2_regime_split(panel, factor_col=FACTOR_COL)
    layer_3 = layer_3_tradable_only(panel, factor_col=FACTOR_COL)

    # Pass 2 robustness --------------------------------------------------
    layer_4 = layer_4_sector_neutral(panel, factor_col=FACTOR_COL)
    layer_5 = layer_5_cap_terciles(
        panel, factor_col=FACTOR_COL, cap_col="log_mcap",
    )

    print("\n" + "=" * 72)
    print("Size-factor analysis complete.")
    print("=" * 72)

    # plt.show() commented out so the script can run unattended; uncomment
    # if you want the matplotlib windows to pop up interactively.
    # plt.show()