"""
fr_config.py — Constants for the volume-amplified reversal factor (Phase 1).

Renamed from `config.py` to avoid shadowing universe_exploration/config.py
when universe_loader.py does `import config` internally. See plan §"Workspace
layout" rationale.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# ─── Paths (resolved relative to this file, not cwd) ───────────────────
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
MFX1 = REPO_ROOT / "multi_factor_x1"
UE = REPO_ROOT / "universe_exploration"

UNIVERSE_PARQUET = UE / "data" / "universe_membership_primary.parquet"
FACTOR_PANEL_A = MFX1 / "data" / "factor_panel_a.parquet"
SW_L1_MEMBERSHIP = MFX1 / "data" / "sw_l1_membership.parquet"
DAILY_PANEL_DIR = MFX1 / "daily_panel"

DATA_OUT = HERE / "data"
GRAPHS_OUT = HERE / "graphs"

# ─── Regime ─────────────────────────────────────────────────────────────
NEW_NINE_ARTICLES_DATE = pd.Timestamp("2024-04-12")
GAMMA_START_DATE = NEW_NINE_ARTICLES_DATE  # spec §1, §5

# ─── Factor sweep ───────────────────────────────────────────────────────
L_VALUES = [3, 5, 10, 15, 20]
RANK_TYPES = ["ts", "cs"]                 # time-series vs cross-sectional
N_VALUES = [10, 20, 50, 100]              # 40 cells = 4 × 5 × 2
HEADLINE_L = 5
HEADLINE_N = 100
HEADLINE_RANK = "ts"

# ─── Volume rank parameters ─────────────────────────────────────────────
VOL_BASELINE_DAYS = 60
VOL_WINSOR_LOW = -3.0
VOL_WINSOR_HIGH = 3.0

# ─── Bootstrap ──────────────────────────────────────────────────────────
WEEKLY_BLOCK_SIZE = 12
BOOT_N = 10_000
BOOT_SEED = 20260509
PERIODS_PER_YEAR = 52

# ─── Backtest ───────────────────────────────────────────────────────────
# Tushare amount is in 千元; 5000万 RMB liquidity floor = 50,000 千元.
ENTRY_LIQUIDITY_FLOOR_QIANYUAN = 50_000
COST_PER_TURNOVER = 0.0018                # 0.18% × churn at entry, spec §6.1
LIMIT_PROXIMITY = 0.998                   # close ≥ 0.998 × upper_limit → drop

# ─── Residualisation ────────────────────────────────────────────────────
RESIDUALISE_NUMERIC = ["log_mcap"]
RESIDUALISE_CATEGORICAL = "industry_name"
RESIDUALISE_MIN_OBS = 50

# ─── Pre-committed thresholds (spec §7) ─────────────────────────────────
# Apply ONLY to the headline cell (HEADLINE_L, HEADLINE_N, HEADLINE_RANK).
HEADLINE_IR_VALIDATE = 0.5

# ─── Self-check thresholds ──────────────────────────────────────────────
SELFCHECK_FWL_TOL = 1e-9
SELFCHECK_SYNTHETIC_MIN_IC = 0.06
SELFCHECK_FORWARD_RETURN_GAP_TOL = 0.005
SELFCHECK_COVERAGE_MIN = 0.95
