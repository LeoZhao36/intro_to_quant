"""
csi300_universe_builder.py — Build CSI300 monthly membership panel for γ.

Reads multi_factor_x1/data/index_constituents/csi300_*.parquet (already
populated by multi_factor_x1/fetch_index_constituents.py). For each γ
monthly signal_date t, take the snapshot with the largest snapshot_date
<= t. Apply v3's a priori exclusions for parity with the canonical path:
  - A-share prefix filter (exclude 北交所 etc.)
  - Sub-new exclusion (< 120 trading days since list_date)
  - ST / 退市 exclusion (via historical_names PIT)

Output: data/csi300_universe.parquet
Schema: signal_date, ts_code, snapshot_date

If γ-window snapshots are missing (e.g., the latest month-end after the
existing cache build), this module will refetch them via pro.index_weight
using the same pattern as multi_factor_x1/fetch_index_constituents.py.

Run: python csi300_universe_builder.py [build|status|refetch_missing]
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd

import data_loaders as dl
import fr3_config as cfg

# tushare for refetching the latest snapshots if not in cache
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)


def _csi300_snapshot_path(snap: pd.Timestamp) -> Path:
    return cfg.INDEX_CONSTITUENTS_DIR / f"csi300_{snap.strftime('%Y-%m')}.parquet"


def _required_snapshot_months(signals: list[pd.Timestamp]) -> list[pd.Timestamp]:
    """For each signal, the month-end snapshot we'd want is the same calendar month or the prior month."""
    needed: set[pd.Timestamp] = set()
    for s in signals:
        # The signal's own month-end and one prior, to ensure availability
        for m_offset in (0, -1):
            ym = (s + pd.DateOffset(months=m_offset)).to_period("M").to_timestamp("M")
            needed.add(ym)
    return sorted(needed)


def _list_csi300_snapshots() -> list[tuple[pd.Timestamp, Path]]:
    """All cached CSI300 snapshots, sorted by date."""
    items = []
    for p in cfg.INDEX_CONSTITUENTS_DIR.glob("csi300_*.parquet"):
        try:
            ymd = p.stem.split("_", 1)[1]
            yr, mo = ymd.split("-")
            ts = pd.Timestamp(year=int(yr), month=int(mo), day=1) + pd.offsets.MonthEnd(0)
            items.append((ts, p))
        except Exception:
            continue
    items.sort()
    return items


def _refetch_missing(missing: list[pd.Timestamp]) -> None:
    """Pull missing CSI300 month-end snapshots via pro.index_weight."""
    if not missing:
        return
    from tushare_setup import pro  # noqa: WPS433
    print(f"  Refetching {len(missing)} missing CSI300 snapshot(s)...")
    for snap in missing:
        period_start = snap.replace(day=1).strftime("%Y%m%d")
        period_end = snap.strftime("%Y%m%d")
        try:
            df = pro.index_weight(
                index_code=cfg.CSI300_TS_CODE,
                start_date=period_start,
                end_date=period_end,
            )
        except Exception as exc:
            print(f"    [FAIL] {snap.date()}: {exc}")
            continue
        if df is None or len(df) == 0:
            print(f"    [empty] {snap.date()}: no data returned")
            continue
        df = df.rename(columns={"con_code": "ts_code"})
        df["ts_code"] = df["ts_code"].astype(str)
        df["trade_date"] = df["trade_date"].astype(str)
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce").astype("float32")
        df = df[["ts_code", "trade_date", "weight", "index_code"]]
        out = _csi300_snapshot_path(snap)
        df.to_parquet(out, compression=cfg.COMPRESSION, index=False)
        print(f"    pulled {snap.date()}: {len(df)} stocks → {out.name}")
        time.sleep(0.4)


def _most_recent_snapshot_at(signal_date: pd.Timestamp,
                             snapshots: list[tuple[pd.Timestamp, Path]]
                             ) -> tuple[pd.Timestamp, Path] | None:
    """argmax(snap_date <= signal_date)."""
    eligible = [(d, p) for (d, p) in snapshots if d <= signal_date]
    if not eligible:
        return None
    return eligible[-1]


def build_csi300_universe() -> pd.DataFrame:
    """Build γ CSI300 monthly membership panel.

    Returns DataFrame [signal_date, ts_code, snapshot_date, gap_days].
    """
    cal = dl.load_trading_calendar()
    signals = dl.monthly_signal_dates(cfg.GAMMA_START, cfg.GAMMA_END, cal)

    # Verify we have snapshots for each signal's month or prior month
    needed = _required_snapshot_months(signals)
    snapshots = _list_csi300_snapshots()
    have = {d for d, _ in snapshots}
    missing = [d for d in needed if d not in have]
    if missing:
        _refetch_missing(missing)
        snapshots = _list_csi300_snapshots()

    pat = re.compile(cfg.A_SHARE_PATTERN)
    name_history = dl.load_historical_names()
    stock_basic = dl.load_stock_basic()

    rows = []
    gap_warnings = 0
    for s in signals:
        sn = _most_recent_snapshot_at(s, snapshots)
        if sn is None:
            print(f"  [skip] no CSI300 snapshot at or before {s.date()}")
            continue
        snap_date, path = sn
        gap_days = (s - snap_date).days
        if gap_days > cfg.COVERAGE_GAP_DAYS_MAX:
            gap_warnings += 1
            print(f"  [gap] {s.date()}: most recent CSI300 snapshot is "
                  f"{snap_date.date()} ({gap_days}d gap)")
        df = pd.read_parquet(path)
        # pro.index_weight returns multiple trade_dates within a month
        # range (typically month-start and month-end). Use only the
        # latest trade_date in this file as the snapshot.
        if "trade_date" in df.columns and df["trade_date"].nunique() > 1:
            latest_td = df["trade_date"].astype(str).max()
            df = df[df["trade_date"].astype(str) == latest_td]
        members = df["ts_code"].astype(str).unique().tolist()

        keep = []
        for ts in members:
            if not pat.match(ts):
                continue
            # sub-new
            row = stock_basic[stock_basic["ts_code"] == ts]
            if not row.empty and pd.notna(row["list_date"].iloc[0]):
                if dl.trading_days_between(row["list_date"].iloc[0], s, cal) < cfg.SUB_NEW_THRESHOLD_TRADING_DAYS:
                    continue
            # ST / 退市
            if dl.is_st_or_delisting_at(ts, s, name_history):
                continue
            keep.append(ts)

        for ts in keep:
            rows.append({
                "signal_date": s,
                "ts_code": ts,
                "snapshot_date": snap_date,
                "gap_days": gap_days,
            })

    out = pd.DataFrame(rows)
    if not out.empty:
        out["signal_date"] = pd.to_datetime(out["signal_date"])
        out["snapshot_date"] = pd.to_datetime(out["snapshot_date"])
    print(f"\nCSI300 universe panel: {len(out):,} rows over {out['signal_date'].nunique() if len(out) else 0} signal_dates")
    if len(out):
        sizes = out.groupby("signal_date")["ts_code"].size()
        print(f"  size per signal: mean={sizes.mean():.0f}, "
              f"min={sizes.min()}, max={sizes.max()}")
        print(f"  signals with > {cfg.COVERAGE_GAP_DAYS_MAX}d snapshot gap: {gap_warnings}")
    return out


def build_and_save() -> None:
    panel = build_csi300_universe()
    panel.to_parquet(cfg.CSI300_UNIVERSE_PANEL_PATH,
                     compression=cfg.COMPRESSION, index=False)
    print(f"\nSaved: {cfg.CSI300_UNIVERSE_PANEL_PATH}")


def status() -> None:
    snapshots = _list_csi300_snapshots()
    cal = dl.load_trading_calendar()
    signals = dl.monthly_signal_dates(cfg.GAMMA_START, cfg.GAMMA_END, cal)
    print(f"γ monthly signals: {len(signals)}")
    print(f"  range: {signals[0].date()} to {signals[-1].date()}")
    needed = _required_snapshot_months(signals)
    have = {d for d, _ in snapshots}
    missing = [d for d in needed if d not in have]
    print(f"CSI300 snapshots in cache: {len(snapshots)}")
    print(f"  required for γ: {len(needed)}, missing: {len(missing)}")
    if missing:
        for d in missing[:10]:
            print(f"    missing: {d.date()}")
    if cfg.CSI300_UNIVERSE_PANEL_PATH.exists():
        df = pd.read_parquet(cfg.CSI300_UNIVERSE_PANEL_PATH)
        print(f"Panel built: {len(df):,} rows, "
              f"{df['signal_date'].nunique() if len(df) else 0} signals")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "build":
        build_and_save()
    elif mode == "status":
        status()
    elif mode == "refetch_missing":
        cal = dl.load_trading_calendar()
        signals = dl.monthly_signal_dates(cfg.GAMMA_START, cfg.GAMMA_END, cal)
        needed = _required_snapshot_months(signals)
        snapshots = _list_csi300_snapshots()
        have = {d for d, _ in snapshots}
        _refetch_missing([d for d in needed if d not in have])
    else:
        print("Usage: python csi300_universe_builder.py [build|status|refetch_missing]")
        sys.exit(1)


if __name__ == "__main__":
    main()
