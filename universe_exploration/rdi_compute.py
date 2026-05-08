"""
rdi_compute.py — Per-rebalance Retail Dominance Index components.

Three core components plus one optional:
  - RDI_holders     : invert(total_mv / holder_num) at most-recent ann_date ≤ t
  - RDI_funds       : invert(fund_holding_pct) at most-recent end_date ≤ t
  - RDI_north       : invert(hk_hold ratio) at t (eligible names only)
  - RDI_smallorder  : rank((buy_sm+sell_sm)/total) over a 20-day window
                      ending at t (replaces spec's avg-trade-size proxy)

Each component is cross-sectionally rank-transformed within the post-baseline
universe at t and normalised to [0,1]. Rank is INVERTED so high score =
retail-dominant. Composite = mean of available component scores; requires
≥ RDI_MIN_CORE_COMPONENTS (default 2) of the three core components.

Outputs:
  data/rdi_components.parquet
  data/rdi_coverage.csv     (per rebalance: count and pct with ≥k components)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

import config
from baseline_filter import load_trading_calendar


# ═══════════════════════════════════════════════════════════════════════
# Cached data loaders
# ═══════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=1)
def load_holdernumber() -> pd.DataFrame:
    """Sorted by (ts_code, ann_date)."""
    if not config.HOLDERNUMBER_PATH.exists():
        print(f"  [WARN] {config.HOLDERNUMBER_PATH} not found")
        return pd.DataFrame(columns=["ts_code", "ann_date", "end_date", "holder_num"])
    df = pd.read_parquet(config.HOLDERNUMBER_PATH)
    df["ann_date"] = pd.to_datetime(df["ann_date"], format="%Y%m%d", errors="coerce")
    df["end_date"] = pd.to_datetime(df["end_date"], format="%Y%m%d", errors="coerce")
    df["holder_num"] = pd.to_numeric(df["holder_num"], errors="coerce")
    df = df.dropna(subset=["ann_date", "holder_num"])
    df = df[df["holder_num"] > 0]
    df = df.sort_values(["ts_code", "ann_date"]).reset_index(drop=True)
    return df


@lru_cache(maxsize=1)
def load_fund_aggregate() -> pd.DataFrame:
    if not config.FUND_PORTFOLIO_AGGREGATE_PATH.exists():
        print(f"  [WARN] {config.FUND_PORTFOLIO_AGGREGATE_PATH} not found")
        return pd.DataFrame(columns=[
            "ts_code", "end_date", "fund_total_mkv", "ann_date_max", "n_funds"
        ])
    df = pd.read_parquet(config.FUND_PORTFOLIO_AGGREGATE_PATH)
    df["end_date"] = pd.to_datetime(df["end_date"], format="%Y%m%d", errors="coerce")
    df["ann_date_max"] = pd.to_datetime(
        df["ann_date_max"], format="%Y%m%d", errors="coerce"
    )
    df["fund_total_mkv"] = pd.to_numeric(df["fund_total_mkv"], errors="coerce")
    df = df.dropna(subset=["end_date", "ann_date_max", "fund_total_mkv"])
    df = df.sort_values(["ts_code", "end_date"]).reset_index(drop=True)
    return df


_HK_HOLD_PER_DAY_DATES_CACHE: list[str] = []


def _hk_hold_available_dates() -> list[str]:
    """Sorted list of YYYYMMDD strings for which a per-day hk_hold parquet
    exists. Cached after first call."""
    global _HK_HOLD_PER_DAY_DATES_CACHE
    if _HK_HOLD_PER_DAY_DATES_CACHE:
        return _HK_HOLD_PER_DAY_DATES_CACHE
    files = config.HK_HOLD_DIR.glob("hk_hold_*.parquet")
    dates = sorted(f.stem.replace("hk_hold_", "") for f in files)
    _HK_HOLD_PER_DAY_DATES_CACHE = dates
    return dates


# Daily Northbound disclosure was discontinued in mid-Aug 2024 — only
# quarter-end snapshots are published thereafter. Look back up to ~95
# calendar days (≈ one quarter) for a usable observation. For dates in
# the daily-disclosure regime (pre-Aug 2024) the most recent prior file
# will typically be 1 trading day back, so the wider window does no harm.
HK_HOLD_LOOKBACK_DAYS = 100


def load_hk_hold_for_date(rebalance_date: pd.Timestamp) -> pd.DataFrame:
    """
    Returns ts_code, ratio at the most recent hk_hold snapshot with
    trade_date <= rebalance_date, within HK_HOLD_LOOKBACK_DAYS calendar
    days. Empty if no snapshot found in that window.

    Design note: the snapshot we use can be up to a quarter old in the
    post-Aug-2024 regime. That is intentional — Northbound holdings are
    sticky on monthly/quarterly horizons, so a quarter-old snapshot is a
    reasonable proxy for current cross-sectional ranks.
    """
    rebal_yyyymmdd = rebalance_date.strftime("%Y%m%d")
    available = _hk_hold_available_dates()
    if not available:
        return pd.DataFrame(columns=["ts_code", "ratio"])

    # Most recent date <= rebalance_date.
    candidates = [d for d in available if d <= rebal_yyyymmdd]
    if not candidates:
        return pd.DataFrame(columns=["ts_code", "ratio"])
    chosen = candidates[-1]

    # Enforce look-back window
    chosen_ts = pd.to_datetime(chosen, format="%Y%m%d")
    if (rebalance_date - chosen_ts).days > HK_HOLD_LOOKBACK_DAYS:
        return pd.DataFrame(columns=["ts_code", "ratio"])

    path = config.HK_HOLD_DIR / f"hk_hold_{chosen}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["ts_code", "ratio"])
    df = pd.read_parquet(path)
    if "ts_code" not in df.columns or "ratio" not in df.columns:
        return pd.DataFrame(columns=["ts_code", "ratio"])
    df = df.dropna(subset=["ts_code", "ratio"])
    df["ratio"] = pd.to_numeric(df["ratio"], errors="coerce")
    df = df.dropna(subset=["ratio"])
    return df[["ts_code", "ratio"]].copy()


def load_moneyflow_window(
    rebalance_date: pd.Timestamp,
    universe: set[str],
    window: int = config.RDI_SMALLORDER_WINDOW,
) -> pd.DataFrame:
    """
    Mean small-order share over [t - window, t - 1] for each ts_code in
    universe. Returns ts_code, small_share_mean, n_obs.

    small_share = (buy_sm_amount + sell_sm_amount) /
                   (buy_sm + buy_md + buy_lg + buy_elg
                    + sell_sm + sell_md + sell_lg + sell_elg)
    """
    cal = load_trading_calendar()
    rebal_str = rebalance_date.strftime("%Y-%m-%d")
    if rebal_str not in cal:
        return pd.DataFrame(columns=["ts_code", "small_share_mean", "n_obs"])
    end_idx = cal.index(rebal_str)
    start_idx = max(0, end_idx - window)
    window_dates = cal[start_idx:end_idx]  # exclusive of rebalance day

    sums = {"buy_sm_amount": 0.0, "sell_sm_amount": 0.0}
    obs: list[pd.DataFrame] = []
    for d in window_dates:
        d_yyyymmdd = d.replace("-", "")
        path = config.MONEYFLOW_DIR / f"moneyflow_{d_yyyymmdd}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if "ts_code" not in df.columns:
            continue
        df = df[df["ts_code"].isin(universe)]
        if df.empty:
            continue
        sm = ["buy_sm_amount", "sell_sm_amount"]
        md = ["buy_md_amount", "sell_md_amount"]
        lg = ["buy_lg_amount", "sell_lg_amount"]
        elg = ["buy_elg_amount", "sell_elg_amount"]
        all_cols = sm + md + lg + elg
        for c in all_cols:
            if c not in df.columns:
                df[c] = 0.0
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        df["sm_total"] = df[sm].sum(axis=1)
        df["all_total"] = df[all_cols].sum(axis=1)
        df["small_share"] = np.where(
            df["all_total"] > 0,
            df["sm_total"] / df["all_total"],
            np.nan,
        )
        obs.append(df[["ts_code", "small_share"]].dropna())

    if not obs:
        return pd.DataFrame(columns=["ts_code", "small_share_mean", "n_obs"])

    long = pd.concat(obs, ignore_index=True)
    agg = (
        long.groupby("ts_code", as_index=False)
        .agg(small_share_mean=("small_share", "mean"),
             n_obs=("small_share", "size"))
    )
    return agg


# ═══════════════════════════════════════════════════════════════════════
# Per-rebalance component construction
# ═══════════════════════════════════════════════════════════════════════

def _holder_num_pit(rebalance_date: pd.Timestamp,
                    universe: set[str]) -> pd.Series:
    """Most-recent holder_num for each ts_code with ann_date <= t."""
    df = load_holdernumber()
    if df.empty:
        return pd.Series(dtype=float)
    sub = df[(df["ann_date"] <= rebalance_date) & (df["ts_code"].isin(universe))]
    if sub.empty:
        return pd.Series(dtype=float)
    sub = sub.sort_values(["ts_code", "ann_date"])
    most_recent = sub.groupby("ts_code")["holder_num"].last()
    return most_recent


def _fund_pct_pit(rebalance_date: pd.Timestamp,
                  universe: set[str],
                  total_mv_at_t: pd.Series) -> pd.Series:
    """
    fund_holding_pct = fund_total_mkv / total_mv_at_t.
    Uses most-recent end_date with ann_date_max <= t per held stock.

    Note: fund_total_mkv from Tushare is in 元; total_mv from daily_basic
    is in 万元. Convert total_mv ×1e4 to 元 before dividing.
    """
    df = load_fund_aggregate()
    if df.empty:
        return pd.Series(dtype=float)
    sub = df[
        (df["ann_date_max"] <= rebalance_date)
        & (df["ts_code"].isin(universe))
    ]
    if sub.empty:
        return pd.Series(dtype=float)
    sub = sub.sort_values(["ts_code", "end_date"])
    most_recent = sub.groupby("ts_code")[["fund_total_mkv"]].last()

    # total_mv in 万元 → 元
    total_mv_yuan = total_mv_at_t.astype(float) * 1e4
    aligned = total_mv_yuan.reindex(most_recent.index)
    pct = (most_recent["fund_total_mkv"] / aligned).where(aligned > 0)
    return pct.dropna()


def _rank_invert(s: pd.Series) -> pd.Series:
    """Cross-sectional rank → [0,1]; invert so SMALL raw value → HIGH score."""
    if s.empty:
        return s
    r = s.rank(pct=True, method="average")
    return 1.0 - r


def _rank_keep_sign(s: pd.Series) -> pd.Series:
    """Cross-sectional rank → [0,1] without inverting. For RDI_smallorder:
    HIGH small-order share → HIGH retail score, no inversion."""
    if s.empty:
        return s
    return s.rank(pct=True, method="average")


def compute_rdi_for_date(
    rebalance_date: pd.Timestamp,
    baseline: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build the four RDI components for one rebalance date.

    Returns DataFrame with one row per ts_code in baseline:
        trade_date, ts_code, rdi_holders, rdi_funds, rdi_north,
        rdi_smallorder, rdi_rank, n_components_used,
        has_smallorder (bool)
    """
    if baseline.empty:
        return pd.DataFrame()

    universe = set(baseline["ts_code"])
    total_mv = pd.Series(
        pd.to_numeric(baseline.set_index("ts_code")["total_mv"], errors="coerce"),
        name="total_mv",
    )

    # Component 1: per-account-mkv → INVERTED rank (small per-account = retail)
    holder_num = _holder_num_pit(rebalance_date, universe)
    common = total_mv.index.intersection(holder_num.index)
    per_account = (total_mv.loc[common].astype(float) * 1e4) / holder_num.loc[common]
    rdi_holders = _rank_invert(per_account.dropna())

    # Component 2: fund_holding_pct → INVERTED rank (low fund share = retail)
    fund_pct = _fund_pct_pit(rebalance_date, universe, total_mv)
    rdi_funds = _rank_invert(fund_pct)

    # Component 3: hk_hold ratio → INVERTED rank (low foreign = retail)
    hk = load_hk_hold_for_date(rebalance_date)
    hk = hk[hk["ts_code"].isin(universe)].copy()
    if not hk.empty:
        ratio = hk.groupby("ts_code")["ratio"].first()
        rdi_north = _rank_invert(ratio)
    else:
        rdi_north = pd.Series(dtype=float)

    # Component 4: small-order share → KEEP-SIGN rank (high small share = retail)
    mf = load_moneyflow_window(rebalance_date, universe)
    if not mf.empty:
        small = mf.set_index("ts_code")["small_share_mean"].dropna()
        rdi_small = _rank_keep_sign(small)
    else:
        rdi_small = pd.Series(dtype=float)

    # Assemble
    out = pd.DataFrame(index=sorted(universe))
    out["rdi_holders"] = rdi_holders.reindex(out.index)
    out["rdi_funds"] = rdi_funds.reindex(out.index)
    out["rdi_north"] = rdi_north.reindex(out.index)
    out["rdi_smallorder"] = rdi_small.reindex(out.index)

    # ── Composite definitions ────────────────────────────────────────
    # As of 2026-05-08 (per user instruction), the DEFAULT composite is
    # the 3-component institutional-detection mean:
    #     rdi_rank = mean({rdi_holders, rdi_funds, rdi_north}) when
    #                ≥ RDI_MIN_CORE_COMPONENTS (default 2) are non-NaN.
    # The 4-component version including rdi_smallorder is preserved as
    # a diagnostic in `rdi_rank_with_smallorder`. The marginal-effect
    # block in phase1_run uses the difference between these two to show
    # the impact of including the small-order-flow proxy.
    core = ["rdi_holders", "rdi_funds", "rdi_north"]
    all_four = core + ["rdi_smallorder"]
    n_core = out[core].notna().sum(axis=1)
    n_total = out[all_four].notna().sum(axis=1)

    has_min_core = n_core >= config.RDI_MIN_CORE_COMPONENTS

    rdi_rank_3 = out[core].mean(axis=1, skipna=True)
    rdi_rank_3 = rdi_rank_3.where(has_min_core)

    rdi_rank_4 = out[all_four].mean(axis=1, skipna=True)
    rdi_rank_4 = rdi_rank_4.where(has_min_core)

    out["rdi_rank"] = rdi_rank_3                       # DEFAULT (3-comp)
    out["rdi_rank_with_smallorder"] = rdi_rank_4       # diagnostic (4-comp)
    out["n_components_core_used"] = n_core
    out["n_components_total_used"] = n_total
    out["has_smallorder"] = out["rdi_smallorder"].notna()

    out = out.reset_index().rename(columns={"index": "ts_code"})
    out["trade_date"] = rebalance_date
    return out[[
        "trade_date", "ts_code",
        "rdi_holders", "rdi_funds", "rdi_north", "rdi_smallorder",
        "rdi_rank", "rdi_rank_with_smallorder",
        "n_components_core_used", "n_components_total_used", "has_smallorder",
    ]]


# ═══════════════════════════════════════════════════════════════════════
# Three-component variant (for marginal-effect diagnostic)
# ═══════════════════════════════════════════════════════════════════════

def compute_rdi_with_smallorder(rdi_full: pd.DataFrame) -> pd.DataFrame:
    """
    Helper for the marginal-effect diagnostic: surface the 4-component
    `rdi_rank_with_smallorder` column under the alias `rdi_rank_alt` so
    phase1_run can swap RDI versions cleanly.

    Default `rdi_rank` is 3-component (institutional). This adds the
    small-order-flow proxy as the 4th component.
    """
    out = rdi_full.copy()
    out["rdi_rank_alt"] = out["rdi_rank_with_smallorder"]
    return out


# Back-compat shim — older callers expected `rdi_rank_3comp`. The default
# rdi_rank is now already 3-component, so just alias.
def compute_rdi_three_component_only(rdi_full: pd.DataFrame) -> pd.DataFrame:
    out = rdi_full.copy()
    out["rdi_rank_3comp"] = out["rdi_rank"]
    return out
