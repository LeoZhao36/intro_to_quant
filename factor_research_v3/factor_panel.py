"""
factor_panel.py — Build the integrated factor panel.

For each (signal_date, universe ∈ {canonical, csi300}, ts_code):
  - ep                 raw EP from daily_basic.pe_ttm
  - roa                raw ROA from PIT TTM panel
  - log_total_mv       log of total market cap at signal_date (FWL control)
  - industry_code      SW L1 industry at signal_date (FWL control)
  - tradable_entry     True if vol > 0 on entry_date (signal+1 trading day)
  - fwd_open_to_open   forward return (open[exit] × adj[exit]) /
                       (open[entry] × adj[entry]) - 1, where exit is the
                       entry of the NEXT signal's monthly period.
  - z_ep_resid         per-(date, universe) FWL residualised + z-scored EP
  - z_roa_resid        per-(date, universe) FWL residualised + z-scored ROA

CRITICAL conventions honored:
  - float64 upcast on factor inputs before FWL (May 7 lesson)
  - fresh open-to-open T+1 forward returns (NOT panel close-to-close)
  - residualisation FWL controls = log_total_mv (numeric) +
    industry_code (categorical)

Output: data/factor_panel.parquet
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import data_loaders as dl
import factor_ep
import factor_roa
import fr3_config as cfg
from factor_utils import residualise_factor_per_date


def _entry_exit_dates(signals: list[pd.Timestamp],
                      cal: tuple) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """
    For each consecutive (s_i, s_{i+1}) pair, return (signal=s_i, entry, exit)
    where entry = next trading day after s_i, exit = next trading day after s_{i+1}.

    The last signal has no s_{i+1}, so it produces no period.
    """
    out = []
    for i in range(len(signals) - 1):
        s = signals[i]
        s_next = signals[i + 1]
        entry = dl.next_trading_day(s, cal)
        exit_ = dl.next_trading_day(s_next, cal)
        if entry is None or exit_ is None:
            continue
        out.append((s, entry, exit_))
    return out


def _load_universe_panel() -> pd.DataFrame:
    """
    Long DataFrame with columns [signal_date, ts_code, universe].
    """
    cal = dl.load_trading_calendar()
    signals = dl.monthly_signal_dates(cfg.GAMMA_START, cfg.GAMMA_END, cal)

    rows = []
    # canonical
    for s in signals:
        for ts in dl.get_canonical_universe_at(s, cal):
            rows.append({"signal_date": s, "ts_code": ts, "universe": "canonical"})
    # csi300 (already filtered for sub-new + ST in the panel)
    if cfg.CSI300_UNIVERSE_PANEL_PATH.exists():
        csi = pd.read_parquet(cfg.CSI300_UNIVERSE_PANEL_PATH)
        for _, r in csi.iterrows():
            rows.append({"signal_date": r["signal_date"], "ts_code": r["ts_code"],
                         "universe": "csi300"})
    df = pd.DataFrame(rows)
    df["signal_date"] = pd.to_datetime(df["signal_date"])
    return df


def _attach_basics(panel: pd.DataFrame, pit_panel: pd.DataFrame) -> pd.DataFrame:
    """Add ep, roa, log_total_mv, industry_code per (signal_date, ts_code)."""
    out_rows = []
    signals = sorted(panel["signal_date"].unique())
    for s in signals:
        s_ts = pd.Timestamp(s)
        sub = panel[panel["signal_date"] == s_ts]
        codes = sub["ts_code"].unique().tolist()

        ep = factor_ep.compute_raw_ep(s_ts)
        roa = factor_roa.compute_raw_roa(s_ts, pit_panel)
        tmv = dl.load_total_mv(s_ts)
        ind = dl.load_industry_at(s_ts)

        ep_v = ep.reindex(codes) if ep is not None else pd.Series(np.nan, index=codes)
        roa_v = roa.reindex(codes) if not roa.empty else pd.Series(np.nan, index=codes)
        tmv_v = tmv.reindex(codes) if tmv is not None else pd.Series(np.nan, index=codes)
        log_tmv = np.log(tmv_v.where(tmv_v > 0))
        ind_v = ind.reindex(codes) if not ind.empty else pd.Series(pd.NA, index=codes)

        for ts in codes:
            out_rows.append({
                "signal_date": s_ts,
                "ts_code": ts,
                "ep": float(ep_v.loc[ts]) if pd.notna(ep_v.loc[ts]) else np.nan,
                "roa": float(roa_v.loc[ts]) if pd.notna(roa_v.loc[ts]) else np.nan,
                "log_total_mv": float(log_tmv.loc[ts]) if pd.notna(log_tmv.loc[ts]) else np.nan,
                "industry_code": ind_v.loc[ts] if pd.notna(ind_v.loc[ts]) else pd.NA,
            })

    attrs = pd.DataFrame(out_rows)
    return panel.merge(attrs, on=["signal_date", "ts_code"], how="left")


def _attach_forward_returns(panel: pd.DataFrame, cal: tuple) -> pd.DataFrame:
    """
    Add fwd_open_to_open: open[exit] × adj[exit] / open[entry] × adj[entry] - 1.

    Pre-load all entry/exit dates' adj_open Series into a wide DataFrame
    for vectorized lookup (May 7 lesson).
    """
    signals = sorted(panel["signal_date"].unique())
    triples = _entry_exit_dates([pd.Timestamp(s) for s in signals], cal)

    # Pre-load adj_open per date
    needed_dates = sorted(set([t[1] for t in triples] + [t[2] for t in triples]))
    print(f"  pre-loading adj_open for {len(needed_dates)} dates...")
    by_date: dict[pd.Timestamp, pd.Series] = {}
    for d in needed_dates:
        s = dl.load_daily_open_adj(d)
        if s is not None:
            by_date[d] = s

    fwd_rows = []
    for s, entry, exit_ in triples:
        ent = by_date.get(entry)
        ext = by_date.get(exit_)
        if ent is None or ext is None:
            continue
        common = ent.index.intersection(ext.index)
        ret = ext.reindex(common) / ent.reindex(common) - 1.0
        for ts, r in ret.items():
            fwd_rows.append({
                "signal_date": s,
                "ts_code": ts,
                "entry_date": entry,
                "exit_date": exit_,
                "fwd_open_to_open": float(r) if pd.notna(r) else np.nan,
            })
        # Tradability flag: did the stock exist (vol > 0) on entry_date?
        # Implicit in being in `ent.index` after the daily-open filter (>0).

    fwd = pd.DataFrame(fwd_rows)
    if fwd.empty:
        return panel
    fwd["signal_date"] = pd.to_datetime(fwd["signal_date"])
    fwd["entry_date"] = pd.to_datetime(fwd["entry_date"])
    fwd["exit_date"] = pd.to_datetime(fwd["exit_date"])
    return panel.merge(fwd, on=["signal_date", "ts_code"], how="left")


def _residualise(panel: pd.DataFrame, factor_col: str, out_col: str,
                 universe: str) -> pd.DataFrame:
    """
    FWL residualise factor_col on log_total_mv + industry_code per
    signal_date, within universe-only rows. Then z-score the residuals.
    """
    sub = panel[panel["universe"] == universe].copy()
    # Float64 upcast (May 7 lesson)
    for c in [factor_col, "log_total_mv"]:
        sub[c] = pd.to_numeric(sub[c], errors="coerce").astype("float64")

    sub = residualise_factor_per_date(
        sub,
        factor_col=factor_col,
        out_col=f"_{factor_col}_resid",
        numeric_controls=["log_total_mv"],
        categorical_control="industry_code",
        date_col="signal_date",
        min_obs=30,
    )
    # Z-score the residuals per signal_date
    def _z(s: pd.Series) -> pd.Series:
        m = s.mean()
        sd = s.std()
        if sd == 0 or pd.isna(sd):
            return pd.Series(np.nan, index=s.index)
        return (s - m) / sd

    sub[out_col] = sub.groupby("signal_date")[f"_{factor_col}_resid"].transform(_z)
    sub = sub.drop(columns=[f"_{factor_col}_resid"])

    # Merge back into panel for this universe slice
    keep_cols = ["signal_date", "ts_code", out_col]
    panel = panel.merge(
        sub[keep_cols + ["universe"]],
        on=["signal_date", "ts_code", "universe"],
        how="left",
        suffixes=("", "_dup"),
    )
    if f"{out_col}_dup" in panel.columns:
        panel[out_col] = panel[out_col].fillna(panel[f"{out_col}_dup"])
        panel = panel.drop(columns=[f"{out_col}_dup"])
    return panel


def build_and_save() -> None:
    cal = dl.load_trading_calendar()

    print("=" * 60)
    print("BUILD FACTOR PANEL")
    print("=" * 60)

    print("\n[1/4] Loading universe panel...")
    panel = _load_universe_panel()
    print(f"  rows: {len(panel):,}")
    print(f"  signals: {panel['signal_date'].nunique()}")
    print(f"  universes: {panel['universe'].value_counts().to_dict()}")

    print("\n[2/4] Loading PIT fundamental panel...")
    if not cfg.PIT_FUNDAMENTAL_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"PIT panel missing: {cfg.PIT_FUNDAMENTAL_PANEL_PATH}. "
            f"Run pit_panel_builder.py first."
        )
    pit = pd.read_parquet(cfg.PIT_FUNDAMENTAL_PANEL_PATH)
    pit["signal_date"] = pd.to_datetime(pit["signal_date"])
    print(f"  rows: {len(pit):,}")

    print("\n[3/4] Attaching basics (ep, roa, log_total_mv, industry)...")
    panel = _attach_basics(panel, pit)

    print("\n[4/4] Attaching forward returns (fresh open-to-open T+1)...")
    panel = _attach_forward_returns(panel, cal)
    n_fwd = panel["fwd_open_to_open"].notna().sum() if "fwd_open_to_open" in panel.columns else 0
    print(f"  rows with forward return: {n_fwd:,}/{len(panel):,}")

    print("\n[5/4] Residualising EP and ROA per (signal, universe)...")
    panel["z_ep_resid"] = np.nan
    panel["z_roa_resid"] = np.nan
    for universe in ("canonical", "csi300"):
        print(f"  -- universe={universe}, factor=ep --")
        panel = _residualise(panel, "ep", "z_ep_resid", universe)
        print(f"  -- universe={universe}, factor=roa --")
        panel = _residualise(panel, "roa", "z_roa_resid", universe)

    panel.to_parquet(cfg.FACTOR_PANEL_PATH,
                     compression=cfg.COMPRESSION, index=False)
    print(f"\nSaved: {cfg.FACTOR_PANEL_PATH}")
    print(f"  rows: {len(panel):,}")
    print(f"  z_ep_resid coverage: {panel['z_ep_resid'].notna().sum():,}")
    print(f"  z_roa_resid coverage: {panel['z_roa_resid'].notna().sum():,}")


def status() -> None:
    if not cfg.FACTOR_PANEL_PATH.exists():
        print(f"Factor panel not built: {cfg.FACTOR_PANEL_PATH}")
        return
    df = pd.read_parquet(cfg.FACTOR_PANEL_PATH)
    print(f"Factor panel: {cfg.FACTOR_PANEL_PATH}")
    print(f"  rows: {len(df):,}")
    print(f"  columns: {list(df.columns)}")
    for u in df["universe"].unique():
        sub = df[df["universe"] == u]
        print(f"  universe={u}: {len(sub):,} rows, "
              f"signals={sub['signal_date'].nunique()}, "
              f"z_ep_resid non-null={sub['z_ep_resid'].notna().sum():,}, "
              f"z_roa_resid non-null={sub['z_roa_resid'].notna().sum():,}")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "build":
        build_and_save()
    elif mode == "status":
        status()
    else:
        print("Usage: python factor_panel.py [build|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
