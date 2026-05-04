"""
config.py — Shared constants for the universe-inspection pipeline.

Lives at the multi_factor_x1/ root, alongside daily_panel/. Every script
in this folder imports from here so paths, regime breakpoints, and
universe parameters are defined once.

Run all scripts from multi_factor_x1/ so that DATA_DIR resolves correctly.
"""

from pathlib import Path

import pandas as pd


# ─── Paths ──────────────────────────────────────────────────────────────

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# Daily-panel parquet files staged by Project 6's daily_panel_pull.py;
# they live one level up next to the per-day data inside multi_factor_x1/.
DAILY_PANEL_DIR = Path("daily_panel")

# Index constituent monthly snapshots from pro.index_weight, cached per
# (index, year-month) so re-runs do not re-pull.
INDEX_CONSTITUENTS_DIR = DATA_DIR / "index_constituents"
INDEX_CONSTITUENTS_DIR.mkdir(parents=True, exist_ok=True)

# Project 6 inputs: weekly rebalance dates, trading calendar, the existing
# Project 6 universe. We read these read-only.
PROJECT_6_DATA_DIR = Path("..") / "Project_6" / "data"
WEEKLY_REBALANCE_DATES_PATH = PROJECT_6_DATA_DIR / "weekly_rebalance_dates.csv"
TRADING_CALENDAR_PATH = PROJECT_6_DATA_DIR / "trading_calendar.csv"
PROJ6_UNIVERSE_PATH = (
    PROJECT_6_DATA_DIR / "universe_membership_X75_Y3000.parquet"
)
LIMIT_STATE_PANEL_PATH = PROJECT_6_DATA_DIR / "limit_state_panel.parquet"

# Outputs of this folder.
UNIVERSE_PANEL_PATH = DATA_DIR / "universe_membership_seven.parquet"
DAILY_METRICS_PATH = DATA_DIR / "daily_universe_metrics.parquet"
SUMMARY_TABLE_PATH = DATA_DIR / "universe_inspection_summary.csv"

GRAPHS_DIR = Path("graphs")
GRAPHS_DIR.mkdir(exist_ok=True)


# ─── Regime windows ────────────────────────────────────────────────────
# Four windows. W2 + W3 are disjoint and partition W4; we keep W4 for
# convenience as "everything from 新国九条 onward."

# 新国九条 (April 12, 2024) State Council "若干意见 on the high-quality
# development of capital markets". The regime break for delisting rules
# and small-cap risk model. Source: 新华社, 2024-04-12.
NEW_NINE_ARTICLES_DATE = pd.Timestamp("2024-04-12")

# PBoC stimulus press conference (September 24, 2024). Pan Gongsheng
# joint announcement of rate cut + RRR cut + SLF stock-support facility.
# The regime break for liquidity / risk-on flows. Source: 央行新闻发布会.
PBOC_STIMULUS_DATE = pd.Timestamp("2024-09-24")

# Panel start. Project 6's weekly rebalance dates start 2019-01-09.
PANEL_START = pd.Timestamp("2019-01-09")

# Panel end. Latest daily panel parquet present.
PANEL_END = pd.Timestamp("2026-04-29")

REGIME_WINDOWS = {
    "W1_pre_NNA":      (PANEL_START,            NEW_NINE_ARTICLES_DATE - pd.Timedelta(days=1)),
    "W2_NNA_to_PBoC":  (NEW_NINE_ARTICLES_DATE, PBOC_STIMULUS_DATE - pd.Timedelta(days=1)),
    "W3_post_PBoC":    (PBOC_STIMULUS_DATE,     PANEL_END),
    "W4_post_NNA":     (NEW_NINE_ARTICLES_DATE, PANEL_END),
}

# Friendly labels for plot legends and tables.
REGIME_LABELS = {
    "W1_pre_NNA":      "Pre 新国九条 (2019-01 to 2024-04-11)",
    "W2_NNA_to_PBoC":  "新国九条 to PBoC stimulus (2024-04-12 to 2024-09-23)",
    "W3_post_PBoC":    "Post PBoC stimulus (2024-09-24 to today)",
    "W4_post_NNA":     "All post 新国九条 (2024-04-12 to today)",
}


# ─── Universe definitions ──────────────────────────────────────────────
# Seven universes. The boolean flags in universe_membership_seven.parquet
# follow these keys exactly.
#
# All filters apply only to A-share equities on Shanghai Main / Shenzhen
# Main / ChiNext / STAR (prefixes 60, 68, 00, 30). 北交所 (8x/4x/920) is
# excluded from every universe because BSE has ±30% limits, ¥500k retail
# suitability requirement, and its names cannot be assumed retail-tradable.

UNIVERSE_KEYS = [
    "U1_all_ashare",      # All eligible A-shares (ST/退市/北交所 excluded)
    "U2_proj6",           # Project 6: bottom 1000 by 流通市值 + hybrid floor
    "U3_csi1000",         # 中证1000 explicit constituents
    "U4_csi2000",         # 中证2000 explicit constituents (Aug 2023 onward)
    "U5_csi1000_u_csi2000",  # CSI1000 ∪ CSI2000
    "U6_outside_csi800",     # NOT in CSI300 ∪ CSI500, raw micro-cap residual
    "U7_outside_csi800_floored",  # U6 + (top 75% by 60-day amount AND ≥3000万)
]

UNIVERSE_LABELS = {
    "U1_all_ashare":           "All A-share",
    "U2_proj6":                "Project 6 (bottom 1000 + floor)",
    "U3_csi1000":              "中证1000",
    "U4_csi2000":              "中证2000",
    "U5_csi1000_u_csi2000":    "CSI1000 ∪ CSI2000",
    "U6_outside_csi800":       "Outside-CSI800 (raw)",
    "U7_outside_csi800_floored": "Outside-CSI800 + floor",
}

# Index ts_codes used by pro.index_weight.
# Confirmed via tushare.pro/document/2?doc_id=96 and standard CSI codes.
INDEX_TS_CODES = {
    "csi300":  "000300.SH",
    "csi500":  "000905.SH",
    "csi1000": "000852.SH",
    # CSI2000 launched 2023-08-11. ts_code in Tushare is 932000.CSI per
    # CSI standard; we'll handle the SH/CSI suffix variation defensively
    # in the fetch script.
    "csi2000": "932000.CSI",
}

# CSI2000 inception. Pre-this date, U4 is empty and U5 falls back to U3.
CSI2000_INCEPTION = pd.Timestamp("2023-08-11")

# Liquidity floor parameters used by U2 and U7. These match Project 6's
# Stage 3 settings exactly so U7 is comparable.
LIQUIDITY_FLOOR_PERCENTILE = 75   # X: keep top 75% by 60-day mean amount
LIQUIDITY_FLOOR_AMOUNT_WAN = 3000  # Y: absolute floor in 万元 (~30M RMB)
LIQUIDITY_MIN_DAYS = 20            # Need ≥20 observed days in 60-day window


# ─── A-share constants ─────────────────────────────────────────────────

# Valid A-share equity prefixes. Excludes 北交所 (8x/4x/920) by design.
A_SHARE_PATTERN = r"^(60|68)\d{4}\.SH$|^(00|30)\d{4}\.SZ$"

# 250 trading days per year; aligns with Project 6.
TRADING_DAYS_PER_YEAR = 250

# Tushare returns amount in 千元 (thousands of yuan); divide by 10 to get
# 万元, by 10,000 to get 亿元. Project 6 uses 万 as the canonical unit
# for liquidity floors and 亿 for market cap. We keep that convention.
AMOUNT_QIANYUAN_TO_WAN = 0.1
AMOUNT_QIANYUAN_TO_YI = 1e-5
CIRC_MV_WAN_TO_YI = 1e-4  # circ_mv is in 万元 from Tushare


# ─── Reporting conventions ─────────────────────────────────────────────

# Limit-hit detection threshold; Project 6 uses 0.998 (handles tick rounding).
LIMIT_PROXIMITY = 0.998

# Default exchange-tier limit percentages.
LIMIT_PCT_MAIN     = 0.10
LIMIT_PCT_CHINEXT  = 0.20  # post 2020-08-24; before that it was 0.10
LIMIT_PCT_STAR     = 0.20
LIMIT_PCT_ST       = 0.05  # ST/*ST on Main; rises to 10% on 2026-07-06 per CSRC
CHINEXT_REGIME_CHANGE = pd.Timestamp("2020-08-24")
