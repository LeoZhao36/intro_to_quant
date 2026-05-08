"""
config.py — Shared constants for universe_exploration/ Phase 1.

Mirrors the conventions of multi_factor_x1/config.py with additions:
  - STAR / MAIN_BOARD / CHINEXT regex constants for variant filtering
  - Sub-window dates for the four-window regime comparison
  - RHI hyperparameters (bandwidth, target size, grid resolution)

Run all scripts from universe_exploration/ so relative paths resolve.
"""

from pathlib import Path
from dataclasses import dataclass

import pandas as pd


# ─── Paths ──────────────────────────────────────────────────────────────

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

RAW_DIR = DATA_DIR / "raw"
RAW_DIR.mkdir(exist_ok=True)
HK_HOLD_DIR = RAW_DIR / "hk_hold"
HK_HOLD_DIR.mkdir(exist_ok=True)
MONEYFLOW_DIR = RAW_DIR / "moneyflow"
MONEYFLOW_DIR.mkdir(exist_ok=True)

GRAPHS_DIR = Path("graphs")
GRAPHS_DIR.mkdir(exist_ok=True)

# Inputs from sibling workspaces. Read-only.
DAILY_PANEL_DIR = Path("..") / "multi_factor_x1" / "daily_panel"
PROJECT_6_DATA_DIR = Path("..") / "Project_6" / "data"
WEEKLY_REBALANCE_DATES_PATH = PROJECT_6_DATA_DIR / "weekly_rebalance_dates.csv"
TRADING_CALENDAR_PATH = PROJECT_6_DATA_DIR / "trading_calendar.csv"
STOCK_BASIC_PATH = PROJECT_6_DATA_DIR / "stock_basic.csv"
HISTORICAL_NAMES_PATH = PROJECT_6_DATA_DIR / "historical_names.csv"

# Per-endpoint cache locations.
HOLDERNUMBER_PATH = RAW_DIR / "holdernumber.parquet"
FUND_PORTFOLIO_AGGREGATE_PATH = DATA_DIR / "fund_holding_aggregate.parquet"
FUND_PORTFOLIO_RAW_DIR = RAW_DIR / "fund_portfolio"
FUND_PORTFOLIO_RAW_DIR.mkdir(exist_ok=True)

# Pipeline outputs.
RDI_COMPONENTS_PATH = DATA_DIR / "rdi_components.parquet"
BS_COMPONENTS_PATH = DATA_DIR / "bs_components.parquet"
CAP_RANK_PANEL_PATH = DATA_DIR / "cap_rank_panel.parquet"
TRADABILITY_PANEL_PATH = DATA_DIR / "tradability_panel.parquet"
UNIVERSE_VARIANT_A_PATH = DATA_DIR / "universe_membership_variantA.parquet"
UNIVERSE_VARIANT_B_PATH = DATA_DIR / "universe_membership_variantB.parquet"

# Primary universe = Variant B (主板-only). Locked as the canonical
# downstream universe on 2026-05-08 after Phase 1 results showed:
#   - Variant B universe size much more stable than A (σ=8 vs σ=10
#     full panel; σ=8 vs σ=9 in γ regime).
#   - Mean BS / RDI / cap centroids materially equivalent between A
#     and B (Δ < 0.04 on each axis).
#   - ChiNext composition (Variant A's distinguishing feature) drives
#     Variant A's larger size variability without lifting BS or RDI;
#     including ChiNext does not improve the retail-behavioural
#     identification but adds noise.
# Variant A remains as a diagnostic to substantiate the exclusion choice.
UNIVERSE_PRIMARY_PATH = DATA_DIR / "universe_membership_primary.parquet"


# ─── Date ranges ───────────────────────────────────────────────────────

PANEL_START = pd.Timestamp("2019-01-09")
PANEL_END = pd.Timestamp("2026-04-29")

NEW_NINE_ARTICLES_DATE = pd.Timestamp("2024-04-12")
PBOC_STIMULUS_DATE = pd.Timestamp("2024-09-24")

# User-requested four-window regime comparison.
SUBWINDOWS = {
    "full":      (PANEL_START, PANEL_END),
    "pre_2024":  (PANEL_START, pd.Timestamp("2023-12-31")),
    "post_2024": (pd.Timestamp("2024-01-03"), PANEL_END),
    "gamma":     (PBOC_STIMULUS_DATE, PANEL_END),
}

SUBWINDOW_LABELS = {
    "full":      "Full panel (2019-01-09 to 2026-04-29)",
    "pre_2024":  "Pre 2024 (2019-01-09 to 2023-12-31)",
    "post_2024": "2024-01-01 onward",
    "gamma":     "γ regime (post PBoC stimulus 2024-09-24)",
}


# ─── A-share regex constants ───────────────────────────────────────────

# Valid A-share equity prefixes. Excludes 北交所 (8x/4x/920) by design.
A_SHARE_PATTERN = r"^(60|68)\d{4}\.SH$|^(00|30)\d{4}\.SZ$"
MAIN_BOARD_PATTERN = r"^60\d{4}\.SH$|^00\d{4}\.SZ$"
CHINEXT_PATTERN = r"^30\d{4}\.SZ$"
STAR_PATTERN = r"^68\d{4}\.SH$"


# ─── Universe construction parameters ──────────────────────────────────

SUBNEW_TRADING_DAYS = 120  # ~6 months IPO settle-down

# Tradability liquidity floor. Per spec §1: 0.5亿 RMB = 5000万 RMB
# 60-day median amount.
LIQ_FLOOR_AMOUNT_YI = 0.5
LIQ_FLOOR_WINDOW = 60
LIQ_FLOOR_MIN_DAYS = 20

# RHI hyperparameters.
RHI_BANDWIDTHS = (0.10, 0.15, 0.25)
RHI_DEFAULT_BANDWIDTH = 0.15
RHI_TARGET_SIZE = 500
RHI_GRID_N = 100

# At least this many of {RDI_holders, RDI_funds, RDI_north} required to
# count a stock as having a defined RDI composite. RDI_smallorder is a
# bonus 4th if present.
RDI_MIN_CORE_COMPONENTS = 2

# Behavioural Score component windows.
BS_IDIOVOL_WINDOW = 60   # days for residual std
BS_IDIOVOL_MIN_OBS = 40
BS_MAX_WINDOW = 30       # days for MAX
BS_SKEW_WINDOW = 60      # days for skewness
BS_SKEW_MIN_OBS = 30

# RDI smallorder smoothing window. 20 trading days mirrors
# multi_factor_x1's mean_turnover_20d convention.
RDI_SMALLORDER_WINDOW = 20

# Beta computation for synthetic-EW residualization.
BETA_WINDOW = 60
BETA_MIN_OBS = 40


# ─── Trade-statistics conventions ──────────────────────────────────────

TRADING_DAYS_PER_YEAR = 250

# Tushare amount unit conversions.
AMOUNT_QIANYUAN_TO_WAN = 0.1
AMOUNT_QIANYUAN_TO_YI = 1e-5
CIRC_MV_WAN_TO_YI = 1e-4


# ─── Tushare endpoint pacing ───────────────────────────────────────────

# Conservative under Tushare's 500/min limit. Mirrors Project_6.
TUSHARE_MAX_CALLS_PER_MIN = 400
TUSHARE_RATE_LIMIT_WINDOW = 60.0


# ─── Stock Connect coverage anchors (informational) ────────────────────

SHHK_CONNECT_LAUNCH = pd.Timestamp("2014-11-17")
SZHK_CONNECT_LAUNCH = pd.Timestamp("2016-12-05")
