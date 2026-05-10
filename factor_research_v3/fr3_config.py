"""
fr3_config.py — Shared constants for factor_research_v3.

Named fr3_config (not config.py) to avoid shadowing other config.py files
on sys.path when imports cross workspace boundaries. Run all v3 scripts
from factor_research_v3/ so relative paths resolve.

Scope: Phase 1 EP / ROA factor test on the canonical retail-dominance
small-cap universe (universe_exploration Variant B) with CSI300 as a
falsification comparator. Window is the γ regime (新国九条 onward).
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


# ─── Paths ──────────────────────────────────────────────────────────────

THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data"
GRAPHS_DIR = THIS_DIR / "graphs"
DATA_DIR.mkdir(exist_ok=True)
GRAPHS_DIR.mkdir(exist_ok=True)

REPO_ROOT = THIS_DIR.parent

# Read-only inputs from sibling workspaces
MULTI_FACTOR_X1_DIR = REPO_ROOT / "multi_factor_x1"
DAILY_PANEL_DIR = MULTI_FACTOR_X1_DIR / "daily_panel"
INDEX_CONSTITUENTS_DIR = MULTI_FACTOR_X1_DIR / "data" / "index_constituents"
SW_MEMBERSHIP_PATH = MULTI_FACTOR_X1_DIR / "data" / "sw_l1_membership.parquet"

UNIVERSE_EXPLORATION_DIR = REPO_ROOT / "universe_exploration"
PRIMARY_UNIVERSE_PATH = (
    UNIVERSE_EXPLORATION_DIR / "data" / "universe_membership_primary.parquet"
)

PROJECT_6_DATA_DIR = REPO_ROOT / "Project_6" / "data"
TRADING_CALENDAR_PATH = PROJECT_6_DATA_DIR / "trading_calendar.csv"
STOCK_BASIC_PATH = PROJECT_6_DATA_DIR / "stock_basic.csv"
HISTORICAL_NAMES_PATH = PROJECT_6_DATA_DIR / "historical_names.csv"

# v3 outputs
FINA_INDICATOR_CACHE_DIR = DATA_DIR / "fina_indicator_raw"
FINA_INDICATOR_CACHE_DIR.mkdir(exist_ok=True)
FINA_INDICATOR_PANEL_PATH = DATA_DIR / "fina_indicator_panel.parquet"
PIT_FUNDAMENTAL_PANEL_PATH = DATA_DIR / "pit_fundamental_panel.parquet"
CSI300_UNIVERSE_PANEL_PATH = DATA_DIR / "csi300_universe.parquet"
FACTOR_PANEL_PATH = DATA_DIR / "factor_panel.parquet"

# Phase outputs
PHASE1_IC_SUMMARY_PATH = DATA_DIR / "phase1_ic_summary.csv"
PHASE1_IC_PER_DATE_PATH = DATA_DIR / "phase1_ic_per_date.csv"
PHASE2_SUMMARY_PATH = DATA_DIR / "phase2_summary.csv"
PHASE2_PERIOD_RETURNS_PATH = DATA_DIR / "phase2_period_returns.csv"
PHASE2_BASKET_DIAGNOSTICS_PATH = DATA_DIR / "phase2_basket_diagnostics.csv"
FLIGHT_TO_QUALITY_PATH = DATA_DIR / "flight_to_quality.csv"
CSI300_COMPARATOR_PATH = DATA_DIR / "csi300_comparator.csv"
SELF_CHECK_RESULTS_PATH = DATA_DIR / "self_check_results.csv"
VERDICTS_PATH = DATA_DIR / "verdicts.txt"
RUN_LOG_PATH = DATA_DIR / "run_log.txt"


# ─── Window: γ regime ──────────────────────────────────────────────────

# 新国九条. State Council high-quality capital-markets opinion. Regime
# break for delisting rules. Mirror of multi_factor_x1.NEW_NINE_ARTICLES_DATE.
GAMMA_START = pd.Timestamp("2024-04-12")
GAMMA_END = pd.Timestamp("2026-04-29")


# ─── Cadence ───────────────────────────────────────────────────────────

# Monthly: signal at last trading day of each calendar month, entry at
# the next trading day (open), exit at next signal_date's next trading
# day (open). Approximately 25 monthly periods over γ.
PERIODS_PER_YEAR = 12  # monthly
TRADING_DAYS_PER_YEAR = 250


# ─── Cost regimes ──────────────────────────────────────────────────────
# Both expressed as round-trip costs (per turnover unit). Applied as
# net = gross - turnover × cost_rt where turnover ∈ [0, 2] per period
# (full sell + full buy = 2.0 turnover).
#
# Headline: realistic A-share retail desk
#   commission 0.030% × 2 (both sides)
#   stamp duty 0.05% (sell-side only; halved Aug-2023 by MoF)
#   slippage 0.20% RT
#   ----
#   = 0.06% + 0.05% + 0.20% = 0.31% RT  (rounded to 0.28% conservative
#                                         per spec; we use 0.28% headline)
# Stress: punitive deployment
#   commission + stamp + slippage 2.00% RT
#   ----
#   = 0.06% + 0.05% + 2.00% = 2.11% RT
#
# Per-side breakdown for diagnostics:
COMMISSION_PER_SIDE = 0.00030
STAMP_DUTY_SELL = 0.00050  # halved 2023-08-28 from 0.10%
SLIPPAGE_RT_HEADLINE = 0.00200
SLIPPAGE_RT_STRESS = 0.02000

COST_RT_HEADLINE = 2 * COMMISSION_PER_SIDE + STAMP_DUTY_SELL + SLIPPAGE_RT_HEADLINE  # 0.0028
COST_RT_STRESS = 2 * COMMISSION_PER_SIDE + STAMP_DUTY_SELL + SLIPPAGE_RT_STRESS  # 0.0211

COST_REGIMES = {
    "headline": COST_RT_HEADLINE,
    "stress": COST_RT_STRESS,
}


# ─── Universes ─────────────────────────────────────────────────────────

UNIVERSE_KEYS = ["canonical", "csi300"]
UNIVERSE_LABELS = {
    "canonical": "Variant B (universe_exploration primary)",
    "csi300":    "CSI300 (000300.SH, monthly snapshots)",
}

CSI300_TS_CODE = "000300.SH"


# ─── A-share constants ─────────────────────────────────────────────────

A_SHARE_PATTERN = r"^(60|68)\d{4}\.SH$|^(00|30)\d{4}\.SZ$"
SUB_NEW_THRESHOLD_TRADING_DAYS = 120


# ─── Top-N sweep ───────────────────────────────────────────────────────

TOP_N_SWEEP = [10, 20, 50, 100, 200]
HEADLINE_TOP_N = 10

# Hard 20% sector cap. At top_n=10 → 2 names per SW L1 sector.
SECTOR_CAP_PCT = 0.20

def sector_cap_k(top_n: int) -> int:
    """Max basket members per SW L1 sector at given top_n."""
    return max(1, int(SECTOR_CAP_PCT * top_n))


# ─── Bootstrap ─────────────────────────────────────────────────────────

# Monthly cadence → block_size=3 (one quarter of monthly observations).
# n_boot=10000 per spec section 14.
BOOT_BLOCK_SIZE = 3
BOOT_N = 10_000


# ─── Pre-committed verdict thresholds ──────────────────────────────────
# Section 11 of CC_SPEC_factor_research_v3_phase1.md, evaluated
# programmatically before any results are reviewed. Headline cell only.

@dataclass(frozen=True)
class EPVerdictThresholds:
    """EP at top-10 on canonical universe under headline cost."""
    ir_validated_min: float = 0.5     # ir_vs_benchmark_net >= 0.5
    ir_falsified_max: float = 0.0     # ir_vs_benchmark_net < 0.0
    require_ci_low_above: float = 0.0  # AND ci_low > 0 for VALIDATED
    require_ci_high_below: float = 0.0  # AND ci_high < 0 for FALSIFIED


@dataclass(frozen=True)
class ROAVerdictThresholds:
    """ROA at top-10 on canonical universe under headline cost."""
    drawdown_validated_ratio: float = 0.7  # max_dd <= 0.7 × bench_max_dd
    drawdown_falsified_ratio: float = 1.0  # max_dd > 1.0 × bench_max_dd
    sharpe_min_relative: float = 0.0       # sharpe >= bench_sharpe (delta=0)


EP_THRESHOLDS = EPVerdictThresholds()
ROA_THRESHOLDS = ROAVerdictThresholds()


# ─── Risk-flag thresholds (printed at run start) ───────────────────────

# pe_ttm coverage calibration:
#   Tushare returns NaN pe_ttm when TTM net income <= 0 (no negative pe_ttm
#   convention). For small-cap retail-dominated universes a 30-50% NaN rate
#   is expected and matches the "drop negatives" Q1 decision.
#   The threshold below is the floor for the *positive-EP* tradable
#   coverage. Below 30% would mean fewer than ~150 EP-tradable names in a
#   ~500-stock universe — at that point even top-50 risks under-fill from
#   sector cap. We warn but do not gate the run.
#
#   For CSI300 (mostly profitable large caps), > 95% is expected.
PE_TTM_TRADABLE_MIN_CANONICAL = 0.30  # canonical: warn if positive-EP < 30%
PE_TTM_TRADABLE_MIN_CSI300 = 0.95     # CSI300: fall back to manual EP if below
COVERAGE_GAP_DAYS_MAX = 45            # CSI300 most-recent-snapshot gap warning
NEGATIVE_EP_FRACTION_FLAG = 0.40      # research diagnostic; non-blocking


# ─── Tushare fetch settings ────────────────────────────────────────────

TUSHARE_MAX_CALLS_PER_MIN = 180
TUSHARE_MAX_RETRIES = 4
COMPRESSION = "zstd"


# ─── Diagnostic output flags ───────────────────────────────────────────

DELISTING_FRACTION_FLAG = 0.05     # flag if >5% of basket delists in any period


# ─── Phase 3 thresholds (filter-vs-sort decomposition) ─────────────────
# Per CC_SPEC_factor_research_v3_phase2.md section 5. Magnitude checks,
# not statistical tests — with ~23 monthly periods the SE on annualised
# return differences is ~5-6pp, so these are informativeness flags.

PHASE3_FILTER_THRESHOLD_PP = 0.03   # 3pp annual: A or C verdict trigger
PHASE3_SORT_THRESHOLD_PP = 0.05     # 5pp annual: B verdict requires sort < -5pp

# Phase 3 outputs
PHASE3_DECOMPOSITION_PATH = DATA_DIR / "phase3_decomposition_summary.csv"
PHASE3_QUINTILE_PATH = DATA_DIR / "phase3_quintile_summary.csv"
PHASE3_SECTOR_PERIOD_PATH = DATA_DIR / "phase3_sector_decomposition.csv"
PHASE3_SECTOR_AGG_PATH = DATA_DIR / "phase3_sector_decomposition_agg.csv"
PHASE3_VERDICTS_PATH = DATA_DIR / "phase3_verdicts.txt"
