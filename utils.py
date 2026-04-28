"""
utils.py — Shared utilities.

Currently houses:
    limit_state — detect whether an A-share daily close is at the price limit
                  (涨停 / 跌停), board-aware and ST-aware.

This module is the consolidation point for helpers that started in Project 1
and are reused across later projects. New helpers land here when they have
at least two consumers; one-off utilities stay near their caller.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal


# ---------------------------------------------------------------------------
# Rounding helper
# ---------------------------------------------------------------------------

def _round_half_up(x: float, ndigits: int = 2) -> float:
    """
    Round half away from zero (四舍五入), matching the Chinese exchange's
    price-limit rounding convention.

    Why not Python's built-in round()? Two reasons combine. First, Python's
    round() uses banker's rounding (half-to-even), which differs from
    四舍五入 on exact .5 cases. Second, IEEE-754 floats cannot represent
    decimal values like 9.295 exactly, so even when the mathematics would
    give a clean halfway value, the actual stored float drifts by a few
    units in the last place, and Python's round() picks up the drift.
    The combined effect: round(8.45 * 1.10, 2) returns 9.29 in Python,
    but the exchange's rule gives 9.30 — and stocks do close at 9.30 on
    9.30-as-ceiling days. Using Decimal with ROUND_HALF_UP sidesteps both
    issues. `repr(x)` is used (not `str(x)`) to round-trip the float
    losslessly into Decimal.
    """
    quant = Decimal("0.1") ** ndigits
    return float(Decimal(repr(x)).quantize(quant, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Board classification
# ---------------------------------------------------------------------------

def _classify_board(ts_code: str, name: str) -> str:
    """
    Classify a stock by trading board and ST status.

    Returns one of:
        "main_normal", "main_st",
        "chinext_normal", "chinext_st",
        "star_normal", "star_st",
        "bse"

    The ST check inspects `name` for prefixes "ST" or "*ST". The caller is
    responsible for passing a `name` appropriate to the date in question.
    Project 5 universe construction (Stage 1) used present-day names from
    `pro.stock_basic`, so passing present-day names here is consistent with
    that filter. The point-in-time correction via `pro.namechange()` is a
    documented carry-forward.
    """
    is_st = isinstance(name, str) and (name.startswith("ST") or name.startswith("*ST"))
    code = ts_code.split(".")[0]

    if code.startswith("688"):                  # 科创板
        return "star_st" if is_st else "star_normal"
    if code.startswith("30"):                   # 创业板
        return "chinext_st" if is_st else "chinext_normal"
    if code.startswith(("60", "00")):           # 沪深主板
        return "main_st" if is_st else "main_normal"
    if code.startswith(("8", "4")):             # 北交所
        return "bse"
    raise ValueError(f"Unrecognized ts_code: {ts_code!r}")


# ---------------------------------------------------------------------------
# Daily price-limit table
# ---------------------------------------------------------------------------
# Matches 沪深 rules in effect during the 2022-01 to 2026-04 sample window.
# 主板 ST limit (5%) is scheduled to flip to 10% pending formal regulatory
# promulgation (征求意见稿 issued 2025-06-27, effective date pending as of
# 2026-04). When an effective date lands, this table either gains a date
# parameter or callers gain a date-aware wrapper. For the current universe
# this is moot because Stage 1 filtered out ST stocks by present-day name.

_LIMIT_PCT = {
    "main_normal":    0.10,
    "main_st":        0.05,
    "chinext_normal": 0.20,
    "chinext_st":     0.20,
    "star_normal":    0.20,
    "star_st":        0.20,
    "bse":            0.30,
}
