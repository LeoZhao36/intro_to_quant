"""
pit_panel_builder.py — Construct PIT TTM net income + avg total assets per
(signal_date, ts_code).

Inputs:
  - data/fina_indicator_raw/income_per_stock/<ts_code>.parquet
  - data/fina_indicator_raw/balancesheet_per_stock/<ts_code>.parquet

Output:
  - data/pit_fundamental_panel.parquet
    Columns: signal_date, ts_code, ttm_ni, avg_total_assets,
             latest_end_date, latest_ann_date

Convention: n_income_attr_p is CUMULATIVE within fiscal year. We compute
TTM via the year-end + diff trick:

  TTM_at_end_date_t = ni_cum_t + (ni_cum_prior_year_end - ni_cum_same_period_prior_year)

Examples:
  end_date_t = 2025-03-31 (Q1 2025)
    TTM = ni_2025Q1 + ni_2024_full - ni_2024Q1
  end_date_t = 2025-06-30 (Q2 / H1 2025)
    TTM = ni_2025H1 + ni_2024_full - ni_2024H1
  end_date_t = 2024-12-31 (year-end)
    TTM = ni_2024_full
        = ni_2024_full + ni_2023_full - ni_2023_full

For total_assets: it's a snapshot, not a flow. We use the average of the
end-of-period total_assets at end_date_t and the same end_date one year
prior. Falls back to latest-only if prior-year balance sheet is missing.

PIT activation: only use rows where ann_date <= signal_date. If multiple
revisions exist for an end_date (different ann_dates), the per-stock
fetch already deduped to keep the latest revision; that revision's
ann_date is what we filter on here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

import data_loaders as dl
import fr3_config as cfg
from tushare_fundamentals_fetch import (
    load_balancesheet_panel,
    load_income_panel,
)


def _quarter_ends_for(end_date: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """
    Given an end_date (a quarter end), return:
      - same_period_prior_year: end_date - 1 year
      - prior_year_end: most recent Dec-31 strictly before end_date.year
    """
    same_prior = pd.Timestamp(year=end_date.year - 1,
                              month=end_date.month, day=end_date.day)
    prior_year_end = pd.Timestamp(year=end_date.year - 1, month=12, day=31)
    return end_date, same_prior, prior_year_end


def _compute_ttm_ni_for_stock(stock_income: pd.DataFrame,
                              signal_date: pd.Timestamp) -> dict | None:
    """
    Returns {ttm_ni, latest_end_date, latest_ann_date} or None if can't compute.
    """
    df = stock_income[stock_income["ann_date"] <= signal_date]
    df = df.dropna(subset=["n_income_attr_p", "end_date"])
    if df.empty:
        return None

    # Latest end_date with ann_date <= signal_date
    df = df.sort_values("end_date")
    latest = df.iloc[-1]
    end_date = latest["end_date"]
    cum_t = latest["n_income_attr_p"]

    # Look up same-period prior year and prior year-end
    same_prior_end = pd.Timestamp(year=end_date.year - 1,
                                  month=end_date.month, day=end_date.day)
    prior_year_end = pd.Timestamp(year=end_date.year - 1, month=12, day=31)

    by_end = df.set_index("end_date")["n_income_attr_p"]

    if end_date.month == 12 and end_date.day == 31:
        # Year-end: TTM is just the full-year cumulative
        ttm = cum_t
    else:
        if (same_prior_end not in by_end.index
                or prior_year_end not in by_end.index):
            return None
        cum_same_prior = by_end[same_prior_end]
        cum_prior_year = by_end[prior_year_end]
        # If duplicate index (shouldn't happen post-dedup), take last
        if isinstance(cum_same_prior, pd.Series):
            cum_same_prior = cum_same_prior.iloc[-1]
        if isinstance(cum_prior_year, pd.Series):
            cum_prior_year = cum_prior_year.iloc[-1]
        ttm = cum_t + cum_prior_year - cum_same_prior

    if pd.isna(ttm):
        return None
    return {
        "ttm_ni": float(ttm),
        "latest_end_date": end_date,
        "latest_ann_date": pd.Timestamp(latest["ann_date"]),
    }


def _compute_avg_total_assets_for_stock(stock_balance: pd.DataFrame,
                                        end_date: pd.Timestamp,
                                        signal_date: pd.Timestamp
                                        ) -> float | None:
    """
    Average total_assets at end_date and same end_date one year prior,
    using only rows with ann_date <= signal_date.
    """
    df = stock_balance[stock_balance["ann_date"] <= signal_date]
    df = df.dropna(subset=["total_assets", "end_date"])
    if df.empty:
        return None
    by_end = df.set_index("end_date")["total_assets"]
    if isinstance(by_end, pd.Series):
        # may have duplicates from amendments; drop_duplicates keep last
        by_end = by_end[~by_end.index.duplicated(keep="last")]

    if end_date not in by_end.index:
        return None
    ta_end = by_end[end_date]

    same_prior = pd.Timestamp(year=end_date.year - 1,
                              month=end_date.month, day=end_date.day)
    if same_prior in by_end.index:
        ta_start = by_end[same_prior]
        return float((ta_end + ta_start) / 2.0)
    # Fall back to end-only
    return float(ta_end)


def build_pit_panel(ts_codes: list[str],
                    signal_dates: list[pd.Timestamp]) -> pd.DataFrame:
    """
    Build PIT TTM panel for the union of ts_codes × signal_dates.
    """
    print(f"Loading income/balancesheet panels for {len(ts_codes):,} stocks...")
    inc_all = load_income_panel(ts_codes)
    bs_all = load_balancesheet_panel(ts_codes)
    print(f"  income rows: {len(inc_all):,}")
    print(f"  balancesheet rows: {len(bs_all):,}")
    if inc_all.empty:
        return pd.DataFrame()

    # Group by ts_code for fast per-stock lookup
    inc_by = {ts: g.copy() for ts, g in inc_all.groupby("ts_code")}
    bs_by = {ts: g.copy() for ts, g in bs_all.groupby("ts_code")}

    rows = []
    n_sig = len(signal_dates)
    for i, s in enumerate(signal_dates, 1):
        if i % 5 == 0 or i == n_sig:
            print(f"  signal {i}/{n_sig}: {s.date()}")
        for ts in ts_codes:
            stock_inc = inc_by.get(ts)
            if stock_inc is None or stock_inc.empty:
                continue
            ttm_res = _compute_ttm_ni_for_stock(stock_inc, s)
            if ttm_res is None:
                continue
            stock_bs = bs_by.get(ts)
            if stock_bs is None or stock_bs.empty:
                avg_ta = None
            else:
                avg_ta = _compute_avg_total_assets_for_stock(
                    stock_bs, ttm_res["latest_end_date"], s
                )
            rows.append({
                "signal_date": s,
                "ts_code": ts,
                "ttm_ni": ttm_res["ttm_ni"],
                "avg_total_assets": avg_ta,
                "latest_end_date": ttm_res["latest_end_date"],
                "latest_ann_date": ttm_res["latest_ann_date"],
            })

    out = pd.DataFrame(rows)
    if not out.empty:
        out["signal_date"] = pd.to_datetime(out["signal_date"])
        out["latest_end_date"] = pd.to_datetime(out["latest_end_date"])
        out["latest_ann_date"] = pd.to_datetime(out["latest_ann_date"])
        # PIT sanity: latest_ann_date <= signal_date for every row
        viol = (out["latest_ann_date"] > out["signal_date"]).sum()
        if viol:
            raise RuntimeError(
                f"PIT VIOLATION: {viol} rows have latest_ann_date > signal_date"
            )
    return out


def build_and_save() -> None:
    """Build for the γ universe union and save."""
    cal = dl.load_trading_calendar()
    signals = dl.monthly_signal_dates(cfg.GAMMA_START, cfg.GAMMA_END, cal)

    # Union universe = canonical ∪ CSI300
    canonical_union = set()
    for s in signals:
        canonical_union |= dl.get_canonical_universe_at(s, cal)

    if cfg.CSI300_UNIVERSE_PANEL_PATH.exists():
        csi = pd.read_parquet(cfg.CSI300_UNIVERSE_PANEL_PATH)
        csi300_union = set(csi["ts_code"].astype(str))
    else:
        csi300_union = set()
        print("WARN: CSI300 universe panel not built; only canonical names will be in PIT panel")

    union = sorted(canonical_union | csi300_union)
    print(f"Building PIT TTM panel: {len(union):,} stocks × {len(signals)} signals")

    panel = build_pit_panel(union, signals)
    panel.to_parquet(cfg.PIT_FUNDAMENTAL_PANEL_PATH,
                     compression=cfg.COMPRESSION, index=False)

    # Coverage summary
    if not panel.empty:
        cov_per_signal = panel.groupby("signal_date")["ts_code"].size()
        print(f"\nPIT panel:")
        print(f"  rows: {len(panel):,}")
        print(f"  signals: {panel['signal_date'].nunique()}")
        print(f"  per-signal stock count: mean={cov_per_signal.mean():.0f}, "
              f"min={cov_per_signal.min()}, max={cov_per_signal.max()}")
        print(f"  TTM coverage in canonical (last γ signal):")
        last = panel[panel["signal_date"] == panel["signal_date"].max()]
        last_canon = canonical_union & set(last["ts_code"].astype(str))
        canonical_at_last = dl.get_canonical_universe_at(panel["signal_date"].max(), cal)
        if canonical_at_last:
            print(f"    {len(last_canon)}/{len(canonical_at_last)} = "
                  f"{100*len(last_canon)/len(canonical_at_last):.1f}%")
    print(f"\nSaved: {cfg.PIT_FUNDAMENTAL_PANEL_PATH}")


def status() -> None:
    if not cfg.PIT_FUNDAMENTAL_PANEL_PATH.exists():
        print(f"PIT panel not built: {cfg.PIT_FUNDAMENTAL_PANEL_PATH}")
        return
    df = pd.read_parquet(cfg.PIT_FUNDAMENTAL_PANEL_PATH)
    print(f"PIT panel: {cfg.PIT_FUNDAMENTAL_PANEL_PATH}")
    print(f"  rows: {len(df):,}")
    print(f"  signals: {df['signal_date'].nunique()} "
          f"({df['signal_date'].min().date()}..{df['signal_date'].max().date()})")
    print(f"  stocks: {df['ts_code'].nunique()}")
    print(f"  ttm_ni non-null: {df['ttm_ni'].notna().sum():,} / {len(df):,}")
    print(f"  avg_total_assets non-null: {df['avg_total_assets'].notna().sum():,} / {len(df):,}")
    print(f"  rows with negative ttm_ni: "
          f"{(df['ttm_ni'] < 0).sum():,} ({100*(df['ttm_ni']<0).sum()/len(df):.1f}%)")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "build":
        build_and_save()
    elif mode == "status":
        status()
    else:
        print("Usage: python pit_panel_builder.py [build|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
