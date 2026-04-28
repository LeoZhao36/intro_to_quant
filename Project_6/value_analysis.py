"""
value_analysis.py

Project 6 Session 3: value-factor analysis pipeline (TEMPLATE — incomplete).

Same structure as size_analysis.py with two value-specific differences:
  - Factor: EP (earnings yield = TTM_net_profit / market_cap)
  - Negative-earnings handling: exclude E<0 firms before quintile sort
    (EP is undefined for E<0; setting ep=NaN causes those rows to drop
    naturally inside compute_quintile_series via duplicates="drop" and
    pd.qcut's NaN handling).

The data-sourcing step is marked NotImplementedError until Session 3
work wires up the EP join. Running this script before then will fail
loudly at add_ep_to_panel(), which is intentional.

Run from Project_6/ as: `python value_analysis.py`

Session 3 outline (~3-4 hours total):
  1. Source TTM net profit from Tushare (pro.fina_indicator) or akshare
     for all stocks in the universe across 2022-2026.
  2. Compute EP = TTM_net_profit / circ_mv_yi (both already on the same
     market-cap basis).
  3. Apply disclosure-lag buffer: only use TTM earnings whose
     ann_date + 30 days <= rebalance_date.
  4. Set ep=NaN for E<=0 (excludes from quintile sort but keeps the row
     in the panel for other factor analyses).
  5. Merge on ts_code + nearest-prior reporting period.
  6. Run this script and compare to predictions.

Predictions logged for value (from prior calibration discussion):
  Q1-Q5 in [-0.5%, +1.0%]/month at t in [-1.0, +2.0]; CIs likely contain
  zero but plausibly narrower than size if value has lower month-to-month
  variability. Direction is genuinely uncertain in our universe due to
  shell-value contamination in the bottom segment of A-shares.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from factor_utils import (
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
FACTOR_COL = "ep"
FACTOR_LABEL = "earnings yield (E/P)"
OUTPUT_PREFIX = "value"


def add_ep_to_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """
    TODO Session 3: source EP from Tushare or akshare and join into the
    panel by ts_code with disclosure-lag buffer.

    Steps to implement:
      1. Pull TTM net profit and announcement dates (ann_date) from
         tushare's fina_indicator or akshare equivalent for all ts_code
         in the universe across 2022-2026.
      2. For each (ts_code, rebalance_date), find the most recent
         financial period whose ann_date + 30 days <= rebalance_date.
         The 30-day buffer protects against using earnings before they
         are publicly available (look-ahead bias).
      3. Compute EP = TTM_net_profit / (circ_mv_yi * 1e8). The 1e8 is
         because circ_mv_yi is in 亿 (100 million), and net profit will
         likely come back in 元 (yuan).
      4. Set ep = NaN where TTM_net_profit <= 0 (negative-earnings
         exclusion per CH-3 logic). NaN rows are dropped naturally by
         pd.qcut and the IC calculation.
      5. Return the panel with the new 'ep' column.

    Sanity checks for the implementation:
      - EP values should mostly fall in [0, 0.20]; values outside
        [-0.5, 0.5] suggest a units bug.
      - Coverage: expect ~80-90% of rows to have non-NaN ep after
        excluding E<=0. If much less, the lag buffer or join is wrong.
      - Cross-section dispersion: std of ep within each date should be
        on the order of 0.03-0.08; near-zero std would indicate the
        factor is degenerate.
    """
    raise NotImplementedError(
        "EP data sourcing is pending. See the docstring above for the "
        "Session 3 implementation outline. Run size_analysis.py until "
        "this is wired up."
    )


if __name__ == "__main__":
    # Load and prepare ---------------------------------------------------
    panel = load_panel()
    print(
        f"Panel loaded: {len(panel):,} rows, "
        f"{panel['rebalance_date'].nunique()} dates"
    )

    # Value-specific data prep -------------------------------------------
    panel = add_ep_to_panel(panel)
    n_with_ep = panel["ep"].notna().sum()
    n_total = len(panel)
    print(
        f"  EP available on {n_with_ep:,} of {n_total:,} rows "
        f"({n_with_ep / n_total * 100:.1f}%)"
    )

    # Headline -----------------------------------------------------------
    print("\n" + "=" * 72)
    print("Headline")
    print("=" * 72)
    quintiles = compute_quintile_series(panel, sort_col=FACTOR_COL)
    headline = summarise_long_short(quintiles, "headline Q1-Q5")
    ic = compute_ic_series(panel, sort_col=FACTOR_COL)
    print(f"  IC: mean={ic.mean():+.4f}, std={ic.std():.4f}, n={len(ic)}")

    # Plots --------------------------------------------------------------
    plot_cumulative_quintiles(
        quintiles, FACTOR_LABEL,
        save_path=Path(f"{OUTPUT_PREFIX}_quintile_cumulative_returns.png"),
    )
    plot_ic_series(
        ic, FACTOR_LABEL,
        save_path=Path(f"{OUTPUT_PREFIX}_ic_time_series.png"),
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
    print("Value-factor analysis complete.")
    print("=" * 72)
