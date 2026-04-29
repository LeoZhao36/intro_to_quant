"""
value_analysis.py

Project 6 Session 3: value-factor analysis pipeline.

Same structure as size_analysis.py with two value-specific differences:
  - Factor: EP (earnings yield) loaded from data/ep_panel.csv, which is
    produced by source_ep_data.py from Tushare's daily_basic endpoint.
    EP = 1 / pe_ttm.
  - Negative-earnings exclusion: source_ep_data.py already sets ep=NaN
    for stocks with pe_ttm <= 0. Those rows pass through the panel and
    are dropped naturally inside compute_quintile_series (via pd.qcut's
    NaN handling) and inside compute_ic_series (via dropna).

Run from Project_6/ as: `python value_analysis.py`
Prerequisite: run `python source_ep_data.py` first to produce
data/ep_panel.csv. If the file is missing, this script raises a
FileNotFoundError with instructions.

Predictions logged for value
----------------------------
Q1-Q5 in [-0.5%, +1.0%]/month at t in [-1.0, +2.0]. CIs likely contain
zero but plausibly narrower than size if value has lower month-to-month
variability. Direction is genuinely uncertain in our universe due to
shell-value contamination in the bottom segment of A-shares.
"""

from pathlib import Path

import pandas as pd

from Project_6.Factor_Analysis_Monthly_Universe.factor_utils import (
    EP_PANEL_PATH,
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
FACTOR_COL = "ep"
FACTOR_LABEL = "earnings yield (E/P)"
OUTPUT_PREFIX = "value"


def add_ep_to_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Load EP from data/ep_panel.csv (produced by source_ep_data.py) and
    merge it into the panel by (rebalance_date, ts_code).

    Stocks with no EP data (missing pe_ttm in Tushare, or excluded for
    E<=0) get ep=NaN. These rows remain in the panel for other factor
    analyses; they're dropped inside compute_quintile_series and
    compute_ic_series via their NaN handling.
    """
    if not EP_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"EP panel not found at {EP_PANEL_PATH}.\n"
            "Run `python source_ep_data.py` first to generate it."
        )

    ep_data = pd.read_csv(
        EP_PANEL_PATH,
        parse_dates=["rebalance_date"],
        dtype={"ts_code": str},
    )

    # Keep only the columns we need, to avoid polluting the panel namespace.
    ep_data = ep_data[["rebalance_date", "ts_code", "pe_ttm", "ep"]]

    panel_with_ep = panel.merge(
        ep_data,
        on=["rebalance_date", "ts_code"],
        how="left",
    )
    return panel_with_ep


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

    # Sanity check: EP coverage per date should be reasonably stable.
    coverage_per_date = (
        panel.groupby("rebalance_date")["ep"].apply(lambda s: s.notna().mean())
    )
    print(
        f"  EP coverage per date: "
        f"min {coverage_per_date.min()*100:.1f}%, "
        f"median {coverage_per_date.median()*100:.1f}%, "
        f"max {coverage_per_date.max()*100:.1f}%"
    )

    # Headline -----------------------------------------------------------
    print("\n" + "=" * 72)
    print("Headline (value: EP)")
    print("=" * 72)
    quintiles = compute_quintile_series(panel, sort_col=FACTOR_COL)
    headline = summarise_long_short(quintiles, "headline Q1-Q5")
    ic = compute_ic_series(panel, sort_col=FACTOR_COL)
    print(f"  IC: mean={ic.mean():+.4f}, std={ic.std():.4f}, n={len(ic)}")
    print(
        "  (Note: for EP, Q1 = LOW EP = expensive stocks; "
        "Q5 = HIGH EP = cheap stocks. "
        "Direction-of-effect for value premium: Q5 > Q1, i.e. Q1-Q5 < 0.)"
    )

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
    print("Value-factor analysis complete.")
    print("=" * 72)