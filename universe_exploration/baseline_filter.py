"""
baseline_filter.py — Per-rebalance baseline universe filter for variants A and B.

Applies, in order:
  1. A_SHARE_PATTERN: drop 北交所, B-shares, indexes, ETFs
  2. STAR_PATTERN: drop 科创板 (50万 RMB retail entry barrier)
  3. Sub-new: <120 trading days since list_date
  4. ST / 退 in name at t (PIT via historical_names.csv)
  5. Did not trade on t (missing from daily_panel/daily_<t>.parquet)

Variant A: above filter only.
Variant B: above + drop CHINEXT_PATTERN matches.
"""

from __future__ import annotations

import re
from pathlib import Path
from functools import lru_cache

import pandas as pd

import config


_A_SHARE_RE = re.compile(config.A_SHARE_PATTERN)
_STAR_RE = re.compile(config.STAR_PATTERN)
_CHINEXT_RE = re.compile(config.CHINEXT_PATTERN)
_ST_OR_DELIST = re.compile(r"ST|退")


@lru_cache(maxsize=1)
def load_trading_calendar() -> list[str]:
    df = pd.read_csv(config.TRADING_CALENDAR_PATH)
    return df["date"].astype(str).tolist()


@lru_cache(maxsize=1)
def load_stock_basic() -> pd.DataFrame:
    """ts_code, list_date (YYYYMMDD string)."""
    df = pd.read_csv(config.STOCK_BASIC_PATH, dtype={"list_date": str})
    df["list_date"] = df["list_date"].str.replace("-", "", regex=False)
    return df[["ts_code", "list_date"]].copy()


@lru_cache(maxsize=1)
def load_historical_names() -> pd.DataFrame:
    """ts_code, name, start_date, end_date (str YYYY-MM-DD)."""
    df = pd.read_csv(config.HISTORICAL_NAMES_PATH)
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
    return df[["ts_code", "name", "start_date", "end_date"]].copy()


def _trading_days_since_list(
    ts_code: str,
    list_date_yyyymmdd: str,
    rebalance_date: pd.Timestamp,
    cal: list[str],
    cal_index: dict[str, int],
) -> int:
    """
    Trading days between list_date and rebalance_date (inclusive of
    list_date, exclusive of rebalance_date).

    Sentinels:
      -1  : list_date or rebalance_date malformed.
      9999: list_date is before the trading_calendar starts (any such stock
            has been listed >> 120 trading days by definition; pass).
      Otherwise: the actual trading-day count.
    """
    if not isinstance(list_date_yyyymmdd, str) or len(list_date_yyyymmdd) != 8:
        return -1
    list_str = (
        f"{list_date_yyyymmdd[0:4]}-{list_date_yyyymmdd[4:6]}-"
        f"{list_date_yyyymmdd[6:8]}"
    )
    rebal_str = rebalance_date.strftime("%Y-%m-%d")
    ri = cal_index.get(rebal_str)
    if ri is None:
        return -1
    li = cal_index.get(list_str)
    if li is None:
        # list_date not in calendar. If it's before the first calendar day,
        # the stock is much older than 120 trading days; pass.
        if list_str < cal[0]:
            return 9999
        # If it's after the last calendar day or genuinely unknown, fail.
        if list_str > cal[-1]:
            return -1
        # Inside calendar but missing (likely a non-trading day): step
        # forward to the next trading day.
        for j in range(len(cal)):
            if cal[j] >= list_str:
                li = j
                break
        if li is None:
            return -1
    return ri - li


def get_pit_names(rebalance_date: pd.Timestamp) -> pd.DataFrame:
    """
    PIT name lookup at rebalance_date. Returns ts_code, name where
    start_date <= rebalance_date < end_date (or end_date is NaT).
    """
    df = load_historical_names()
    mask = (df["start_date"] <= rebalance_date) & (
        df["end_date"].isna() | (df["end_date"] > rebalance_date)
    )
    out = df.loc[mask, ["ts_code", "name"]].copy()
    # If a stock has multiple matching rows (name change overlap), take the
    # most-recent start_date.
    out["__rank"] = df.loc[mask].groupby("ts_code")["start_date"].rank(
        method="first", ascending=False
    )
    out = out[out["__rank"] == 1].drop(columns="__rank")
    return out


def daily_panel_path(rebalance_date: pd.Timestamp) -> Path:
    return config.DAILY_PANEL_DIR / f"daily_{rebalance_date.strftime('%Y-%m-%d')}.parquet"


def load_daily_panel(rebalance_date: pd.Timestamp) -> pd.DataFrame | None:
    p = daily_panel_path(rebalance_date)
    if not p.exists():
        return None
    return pd.read_parquet(p)


def apply_baseline_filter(
    rebalance_date: pd.Timestamp,
    daily: pd.DataFrame | None = None,
    variant: str = "A",
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Return a DataFrame with columns ts_code, total_mv, circ_mv, close, amount,
    board, plus pass-through fields from the daily panel, restricted to the
    post-baseline universe at rebalance_date.

    Parameters
    ----------
    rebalance_date : pd.Timestamp
    daily : optional pre-loaded daily panel for this date (if None, loads).
    variant : "A" (default, ChiNext kept) or "B" (ChiNext excluded).
    verbose : print step-by-step counts.
    """
    if variant not in ("A", "B"):
        raise ValueError(f"variant must be 'A' or 'B', got {variant!r}")

    if daily is None:
        daily = load_daily_panel(rebalance_date)
    if daily is None or daily.empty:
        if verbose:
            print(f"  [baseline] no daily panel for {rebalance_date.date()}")
        return pd.DataFrame()

    df = daily.copy()
    df["ts_code"] = df["ts_code"].astype(str)
    n0 = len(df)

    # 1. A_SHARE_PATTERN
    mask_a = df["ts_code"].str.match(config.A_SHARE_PATTERN)
    df = df[mask_a].copy()
    n1 = len(df)

    # 2. STAR exclusion
    mask_star = df["ts_code"].str.match(config.STAR_PATTERN)
    df = df[~mask_star].copy()
    n2 = len(df)

    # 2b. Variant B: also drop ChiNext
    if variant == "B":
        mask_chinext = df["ts_code"].str.match(config.CHINEXT_PATTERN)
        df = df[~mask_chinext].copy()
    n2b = len(df)

    # 3. Sub-new
    cal = load_trading_calendar()
    cal_index = {d: i for i, d in enumerate(cal)}
    basic = load_stock_basic()
    df = df.merge(basic, on="ts_code", how="left")
    days_since = df.apply(
        lambda r: _trading_days_since_list(
            r["ts_code"], r["list_date"], rebalance_date, cal, cal_index
        ),
        axis=1,
    )
    df = df[days_since >= config.SUBNEW_TRADING_DAYS].copy()
    n3 = len(df)

    # 4. ST / 退 in PIT name
    pit_names = get_pit_names(rebalance_date)
    df = df.merge(pit_names, on="ts_code", how="left")
    name_str = df["name"].fillna("").astype(str)
    has_st = name_str.str.contains(_ST_OR_DELIST, na=False)
    df = df[~has_st].copy()
    n4 = len(df)

    # 5. Traded on t: implicitly satisfied by being in the daily panel.
    # We additionally require positive amount and non-NaN close.
    close_num = pd.to_numeric(df["close"], errors="coerce")
    amount_num = pd.to_numeric(df["amount"], errors="coerce")
    df = df[(close_num > 0) & (amount_num > 0)].copy()
    n5 = len(df)

    # Board labelling for diagnostics
    def _board(code: str) -> str:
        if _CHINEXT_RE.match(code):
            return "ChiNext"
        if _STAR_RE.match(code):
            return "STAR"
        if code.endswith(".SH"):
            return "Main_SH"
        if code.endswith(".SZ"):
            return "Main_SZ"
        return "Other"

    df["board"] = df["ts_code"].map(_board)

    if verbose:
        print(
            f"  [baseline {variant}] {rebalance_date.date()}: "
            f"daily={n0} → A_share={n1} → no_STAR={n2} "
            f"→ no_ChiNext={n2b} → no_subnew={n3} → no_ST={n4} → traded={n5}"
        )

    keep_cols = [
        "ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
        "vol", "amount", "total_mv", "circ_mv", "adj_factor", "board",
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]
    return df[keep_cols].reset_index(drop=True)


def baseline_step_counts(
    rebalance_date: pd.Timestamp, variant: str = "A"
) -> dict:
    """For self-check: return per-step counts as a dict."""
    daily = load_daily_panel(rebalance_date)
    if daily is None or daily.empty:
        return {"daily": 0}

    counts: dict[str, int] = {}
    df = daily.copy()
    df["ts_code"] = df["ts_code"].astype(str)
    counts["daily"] = len(df)

    df = df[df["ts_code"].str.match(config.A_SHARE_PATTERN)].copy()
    counts["after_A_share"] = len(df)

    df = df[~df["ts_code"].str.match(config.STAR_PATTERN)].copy()
    counts["after_no_STAR"] = len(df)

    if variant == "B":
        df = df[~df["ts_code"].str.match(config.CHINEXT_PATTERN)].copy()
        counts["after_no_ChiNext"] = len(df)

    cal = load_trading_calendar()
    cal_index = {d: i for i, d in enumerate(cal)}
    basic = load_stock_basic()
    df = df.merge(basic, on="ts_code", how="left")
    days = df.apply(
        lambda r: _trading_days_since_list(
            r["ts_code"], r["list_date"], rebalance_date, cal, cal_index
        ),
        axis=1,
    )
    df = df[days >= config.SUBNEW_TRADING_DAYS].copy()
    counts["after_no_subnew"] = len(df)

    pit = get_pit_names(rebalance_date)
    df = df.merge(pit, on="ts_code", how="left")
    name_str = df["name"].fillna("").astype(str)
    df = df[~name_str.str.contains(_ST_OR_DELIST, na=False)].copy()
    counts["after_no_ST"] = len(df)

    close_num = pd.to_numeric(df["close"], errors="coerce")
    amount_num = pd.to_numeric(df["amount"], errors="coerce")
    df = df[(close_num > 0) & (amount_num > 0)].copy()
    counts["after_traded"] = len(df)

    return counts
