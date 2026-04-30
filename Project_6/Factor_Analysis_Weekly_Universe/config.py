"""
config.py — Shared constants for Factor_Analysis_Weekly_Universe.

Cadence is weekly (Wednesday rebalances, 381 dates spanning 2019-01-02
to 2026-04-29). All annualization, bootstrap-window, and label choices
flow from PERIODS_PER_YEAR=52 so a single change here propagates
throughout the per-factor and FMB pipelines.

Reference
---------
Project 6 Universe Rebuild Handoff (2026-04-29) for the architectural
context behind this configuration.
"""

from pathlib import Path

import numpy as np
import pandas as pd


# ─── Paths ──────────────────────────────────────────────────────────────
# Run all scripts from Project_6/ so that DATA_DIR resolves correctly.

DATA_DIR = Path("data")
GRAPHS_DIR = Path("graphs")
GRAPHS_DIR.mkdir(exist_ok=True)

# Inputs from the universe rebuild (Stages 1, 3, 5).
CANDIDATE_HISTORY_PATH = DATA_DIR / "candidate_history_panel.parquet"
UNIVERSE_MEMBERSHIP_PATH = DATA_DIR / "universe_membership_X75_Y3000.parquet"
REBALANCE_DATES_PATH = DATA_DIR / "weekly_rebalance_dates.csv"

# Output of factor_panel_builder; consumed by every per-factor script.
FACTOR_PANEL_PATH = DATA_DIR / "factor_panel_weekly.parquet"


# ─── Cadence ────────────────────────────────────────────────────────────

PERIODS_PER_YEAR = 52
ANNUAL_FACTOR_SQRT = float(np.sqrt(PERIODS_PER_YEAR))  # for Sharpe annualization
RETURN_LABEL = "wk"  # used in print formatting throughout


# ─── Factor formation defaults ──────────────────────────────────────────

# Minimum fraction of formation-window observations required for factor
# eligibility. A stock with mom_52_4 needs >=39 observed weekly returns
# in its 52-week formation window. No imputation: stocks below the
# threshold get NaN. The architectural fix in candidate_history_panel
# means this threshold rarely bites except for IPOs and long suspensions.
MIN_COVERAGE = 0.75


# ─── Statistical inference ─────────────────────────────────────────────

SEED = 42
BOOT_N = 10_000
# Block size 12 weeks (~quarterly) preserves serial correlation in weekly
# factor-return time series. The old monthly code used block_size=3 which
# was also ~quarterly. The autocorrelation horizon being preserved is the
# same; only the cadence has changed.
BOOT_BLOCK_SIZE = 12

# Sectors with fewer than this many stocks at a given date get collapsed
# into 'other' before sector-dummy regression. Avoids singular dummy
# matrices in narrow cross-sections.
MIN_STOCKS_PER_SECTOR = 5


# ─── Regime markers ─────────────────────────────────────────────────────
# Drawn on plots and used as candidate split dates for Layer 2.
# Layer 2 runs the regression on each candidate split and reports all,
# rather than pre-committing to one. The "best" split is read off the
# regression results, not pre-fixed in this config.

REGIME_EVENTS = {
    "COVID lockdown":   pd.Timestamp("2020-01-23"),  # Wuhan lockdown begins
    "COVID reopening":  pd.Timestamp("2022-12-07"),  # 新十条 zero-COVID exit
    "雪球 meltdown":     pd.Timestamp("2024-01-15"),
    "新国九条":          pd.Timestamp("2024-03-15"),
    "PBoC stimulus":    pd.Timestamp("2024-09-18"),
}

# Layer 2 candidates: the regime breakpoints with the strongest a priori
# case for being structural breaks. Each runs as a separate pre/post
# analysis. The other markers in REGIME_EVENTS are plotted but not split.
CANDIDATE_SPLITS = [
    ("COVID lockdown",   pd.Timestamp("2020-01-23")),
    ("COVID reopening",  pd.Timestamp("2022-12-07")),
    ("PBoC stimulus",    pd.Timestamp("2024-09-18")),
]