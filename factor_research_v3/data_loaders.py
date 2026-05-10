"""
data_loaders.py — Universe, daily panel, sector, calendar, name-history.

All loaders are read-only and resolve paths via fr3_config. Run from
factor_research_v3/.

Public API:
    load_trading_calendar()                     -> list[pd.Timestamp]
    monthly_signal_dates(start, end, cal)       -> list[pd.Timestamp]
    next_trading_day(d, cal)                    -> pd.Timestamp
    load_primary_universe()                     -> DataFrame
    get_canonical_universe_at(signal_date, cal) -> set[str]
    load_daily_panel(date)                      -> DataFrame indexed by ts_code
    load_daily_open_adj(date)                   -> Series indexed by ts_code
    load_daily_close_adj(date)                  -> Series indexed by ts_code
    load_pe_ttm(date)                           -> Series indexed by ts_code
    load_circ_mv(date)                          -> Series indexed by ts_code
    load_total_mv(date)                         -> Series indexed by ts_code
    load_sw_l1_membership()                     -> DataFrame
    load_industry_at(asof)                      -> Series ts_code -> industry_code (PIT)
    load_stock_basic()                          -> DataFrame [ts_code, list_date, name]
    load_historical_names()                     -> DataFrame [ts_code, name, start_date, ...]
    is_st_at(name_history, ts_code, asof)       -> bool
"""

from __future__ import annotations

import bisect
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

import fr3_config as cfg


# ─── Trading calendar ──────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_trading_calendar() -> tuple:
    """Return tuple of pd.Timestamp from Project_6/data/trading_calendar.csv."""
    df = pd.read_csv(cfg.TRADING_CALENDAR_PATH, parse_dates=["date"])
    cal = sorted(df["date"].unique())
    return tuple(pd.Timestamp(d) for d in cal)


def monthly_signal_dates(
    start: pd.Timestamp, end: pd.Timestamp, cal: tuple | None = None
) -> list[pd.Timestamp]:
    """Last trading day of each calendar month within [start, end]."""
    if cal is None:
        cal = load_trading_calendar()
    cal_in_range = [d for d in cal if start <= d <= end]
    if not cal_in_range:
        return []
    df = pd.DataFrame({"d": cal_in_range})
    df["ym"] = df["d"].dt.to_period("M")
    last = df.groupby("ym")["d"].max().sort_values()
    return [pd.Timestamp(d) for d in last.values]


def next_trading_day(d: pd.Timestamp, cal: tuple | None = None) -> pd.Timestamp | None:
    """Next trading day strictly after d. None if d is at or past the end."""
    if cal is None:
        cal = load_trading_calendar()
    idx = bisect.bisect_right(cal, d)
    if idx >= len(cal):
        return None
    return cal[idx]


def trading_days_between(
    a: pd.Timestamp, b: pd.Timestamp, cal: tuple | None = None
) -> int:
    """
    Number of trading days strictly between a and b (a exclusive, b exclusive).
    Used for sub-new check: trading_days_between(list_date, signal_date).
    """
    if cal is None:
        cal = load_trading_calendar()
    lo = bisect.bisect_right(cal, a)
    hi = bisect.bisect_left(cal, b)
    return max(0, hi - lo)


# ─── Universe (canonical) ──────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_primary_universe() -> pd.DataFrame:
    """Load universe_exploration's locked Variant B membership panel."""
    df = pd.read_parquet(cfg.PRIMARY_UNIVERSE_PATH)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def get_canonical_universe_at(
    signal_date: pd.Timestamp, cal: tuple | None = None
) -> set[str]:
    """
    Universe membership at a monthly signal_date.

    Source is weekly-Wednesday rebalances. We take the most-recent weekly
    rebalance with rebalance_date <= signal_date.
    """
    df = load_primary_universe()
    weekly_dates = sorted(df["trade_date"].unique())
    weekly_dates_ts = [pd.Timestamp(d) for d in weekly_dates]
    idx = bisect.bisect_right(weekly_dates_ts, signal_date) - 1
    if idx < 0:
        return set()
    asof = weekly_dates_ts[idx]
    mask = (df["trade_date"] == asof) & df["in_hotspot"]
    return set(df.loc[mask, "ts_code"])


# ─── Daily panel ───────────────────────────────────────────────────────

def _daily_panel_path(date: pd.Timestamp) -> Path:
    return cfg.DAILY_PANEL_DIR / f"daily_{date.strftime('%Y-%m-%d')}.parquet"


@lru_cache(maxsize=512)
def load_daily_panel(date_str: str) -> pd.DataFrame | None:
    """
    Load one trade_date's daily panel. Returns None if missing.

    Float64 upcast on numeric columns to avoid float32 precision drift in
    downstream FWL residualisation (May 7 lesson).
    """
    path = cfg.DAILY_PANEL_DIR / f"daily_{date_str}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    numeric_cols = [
        "open", "high", "low", "close", "pre_close", "change", "pct_chg",
        "vol", "amount", "turnover_rate", "turnover_rate_f", "volume_ratio",
        "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm",
        "total_share", "float_share", "free_share", "total_mv", "circ_mv",
        "adj_factor",
    ]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    df = df.set_index("ts_code")
    return df


def load_daily_open_adj(date: pd.Timestamp) -> pd.Series | None:
    """Adjusted open price (open × adj_factor) indexed by ts_code."""
    df = load_daily_panel(date.strftime("%Y-%m-%d"))
    if df is None:
        return None
    s = df["open"] * df["adj_factor"]
    s = s[(df["open"] > 0) & (df["adj_factor"] > 0)]
    s.name = "adj_open"
    return s


def load_daily_close_adj(date: pd.Timestamp) -> pd.Series | None:
    """Adjusted close price (close × adj_factor) indexed by ts_code."""
    df = load_daily_panel(date.strftime("%Y-%m-%d"))
    if df is None:
        return None
    s = df["close"] * df["adj_factor"]
    s = s[(df["close"] > 0) & (df["adj_factor"] > 0)]
    s.name = "adj_close"
    return s


def load_pe_ttm(date: pd.Timestamp) -> pd.Series | None:
    df = load_daily_panel(date.strftime("%Y-%m-%d"))
    if df is None:
        return None
    return df["pe_ttm"]


def load_circ_mv(date: pd.Timestamp) -> pd.Series | None:
    """Free-float market cap in 万元."""
    df = load_daily_panel(date.strftime("%Y-%m-%d"))
    if df is None:
        return None
    return df["circ_mv"]


def load_total_mv(date: pd.Timestamp) -> pd.Series | None:
    """Total market cap in 万元. EP denominator per spec uses total_mv."""
    df = load_daily_panel(date.strftime("%Y-%m-%d"))
    if df is None:
        return None
    return df["total_mv"]


def load_volume(date: pd.Timestamp) -> pd.Series | None:
    df = load_daily_panel(date.strftime("%Y-%m-%d"))
    if df is None:
        return None
    return df["vol"]


def is_tradable_on(date: pd.Timestamp, ts_code: str) -> bool:
    """Stock has a row with vol > 0 on the given date."""
    df = load_daily_panel(date.strftime("%Y-%m-%d"))
    if df is None or ts_code not in df.index:
        return False
    return bool(df.loc[ts_code, "vol"] > 0 and df.loc[ts_code, "open"] > 0)


# ─── SW L1 industry (PIT) ──────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_sw_l1_membership() -> pd.DataFrame:
    """SW L1 (申万一级, 31 industries) membership with in_date / out_date."""
    df = pd.read_parquet(cfg.SW_MEMBERSHIP_PATH)
    df["in_date"] = pd.to_datetime(df["in_date"], format="%Y%m%d", errors="coerce")
    df["out_date"] = pd.to_datetime(df["out_date"], format="%Y%m%d", errors="coerce")
    return df


def load_industry_at(asof: pd.Timestamp) -> pd.Series:
    """
    PIT industry mapping ts_code -> industry_code at asof.

    Active at asof iff in_date <= asof AND (out_date is NaN OR out_date > asof).
    Drops duplicate ts_code keeping first (rare reclassifications).
    """
    df = load_sw_l1_membership()
    m = (df["in_date"] <= asof) & (df["out_date"].isna() | (df["out_date"] > asof))
    sub = df.loc[m, ["ts_code", "industry_code"]].drop_duplicates(
        subset="ts_code", keep="first"
    )
    return sub.set_index("ts_code")["industry_code"]


# ─── Stock basic / name history ────────────────────────────────────────

@lru_cache(maxsize=1)
def load_stock_basic() -> pd.DataFrame:
    """ts_code, name, list_date (parsed), industry."""
    df = pd.read_csv(cfg.STOCK_BASIC_PATH, dtype={"list_date": str})
    df["list_date"] = pd.to_datetime(df["list_date"], format="%Y%m%d", errors="coerce")
    return df


@lru_cache(maxsize=1)
def load_historical_names() -> pd.DataFrame:
    """Historical name changes for ST/退市 detection."""
    df = pd.read_csv(cfg.HISTORICAL_NAMES_PATH)
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
    return df


def is_st_or_delisting_at(ts_code: str, asof: pd.Timestamp,
                          name_history: pd.DataFrame | None = None) -> bool:
    """
    Returns True if ts_code carried an ST / *ST / 退市 name at asof.

    Active name = start_date <= asof < (end_date or +inf). If multiple match,
    any with ST/退市 marker triggers True.
    """
    if name_history is None:
        name_history = load_historical_names()
    sub = name_history[name_history["ts_code"] == ts_code]
    active = sub[
        (sub["start_date"] <= asof)
        & (sub["end_date"].isna() | (sub["end_date"] > asof))
    ]
    if active.empty:
        return False
    for nm in active["name"].astype(str):
        if "ST" in nm or "退" in nm:
            return True
    return False


# ─── Universe filters ──────────────────────────────────────────────────

def passes_a_share_pattern(ts_code: str) -> bool:
    import re
    return bool(re.match(cfg.A_SHARE_PATTERN, ts_code))


def is_sub_new(ts_code: str, signal_date: pd.Timestamp,
               stock_basic: pd.DataFrame | None = None,
               cal: tuple | None = None) -> bool:
    """
    True if (signal_date - list_date) < 120 trading days.

    Trading days, not calendar days. Uses Project_6 trading calendar.
    """
    if stock_basic is None:
        stock_basic = load_stock_basic()
    row = stock_basic[stock_basic["ts_code"] == ts_code]
    if row.empty or pd.isna(row["list_date"].iloc[0]):
        return False  # don't penalise unknown list_date; let other filters catch
    list_date = row["list_date"].iloc[0]
    return trading_days_between(list_date, signal_date, cal) < cfg.SUB_NEW_THRESHOLD_TRADING_DAYS


# ─── Smoke ─────────────────────────────────────────────────────────────

def _smoke() -> None:
    cal = load_trading_calendar()
    print(f"calendar: {len(cal)} days, {cal[0].date()} to {cal[-1].date()}")

    sigs = monthly_signal_dates(cfg.GAMMA_START, cfg.GAMMA_END, cal)
    print(f"γ monthly signals: {len(sigs)}")
    for d in sigs[:3]:
        print(f"  {d.date()}")
    print(f"  ...{sigs[-1].date()}")

    df = load_primary_universe()
    print(f"primary universe panel: {len(df):,} rows, "
          f"{df['trade_date'].nunique()} rebalances")

    last_sig = sigs[-2] if len(sigs) >= 2 else sigs[-1]
    canon = get_canonical_universe_at(last_sig, cal)
    print(f"canonical universe at {last_sig.date()}: {len(canon)} names")

    nxt = next_trading_day(last_sig, cal)
    op = load_daily_open_adj(nxt)
    print(f"daily open at {nxt.date()}: {len(op)} stocks")

    ind = load_industry_at(last_sig)
    print(f"SW L1 industry map at {last_sig.date()}: {len(ind)} stocks, "
          f"{ind.nunique()} industries")


if __name__ == "__main__":
    _smoke()
