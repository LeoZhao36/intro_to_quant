"""
data_loaders.py — Cached loaders for universe, daily panel, and sector.

Loads each source ONCE per process and returns in-memory structures.
Avoids the universe_loader's per-call disk read pattern.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import fr_config


# ─── Universe ──────────────────────────────────────────────────────────

def load_universe_dict(gamma_only: bool = True) -> dict[pd.Timestamp, set[str]]:
    """
    Returns {rebalance_date: set(ts_code)} for primary-universe membership.

    Reads universe_membership_primary.parquet directly (bypassing
    universe_loader) so cwd-shadow concerns don't apply.
    """
    df = pd.read_parquet(fr_config.UNIVERSE_PARQUET)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    if gamma_only:
        df = df[df["trade_date"] >= fr_config.GAMMA_START_DATE]
    df = df[df["in_hotspot"]]
    return {d: set(g["ts_code"]) for d, g in df.groupby("trade_date")}


def universe_full_panel() -> pd.DataFrame:
    """Full primary-universe panel (all dates) for diagnostics/sanity checks."""
    df = pd.read_parquet(fr_config.UNIVERSE_PARQUET)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


# ─── Daily panel ───────────────────────────────────────────────────────

_DAILY_COLS_DEFAULT = ("trade_date", "ts_code", "open", "close",
                       "amount", "adj_factor", "pct_chg")


def _daily_files_in_range(start: pd.Timestamp,
                          end: pd.Timestamp) -> list[Path]:
    files = []
    for fp in sorted(fr_config.DAILY_PANEL_DIR.glob("daily_*.parquet")):
        # filename: daily_YYYY-MM-DD.parquet
        try:
            d = pd.Timestamp(fp.stem.replace("daily_", ""))
        except Exception:
            continue
        if start <= d <= end:
            files.append(fp)
    return files


def load_daily_panel_long(start: pd.Timestamp,
                          end: pd.Timestamp,
                          cols: tuple[str, ...] = _DAILY_COLS_DEFAULT
                          ) -> pd.DataFrame:
    """
    Concatenate daily_<YYYY-MM-DD>.parquet files in [start, end] (calendar
    range; trading-day filtering happens implicitly via filename existence).

    Returns long-format DataFrame with float64 numeric cols and a
    datetime64[ns] `trade_date`. Sorted by (ts_code, trade_date).
    """
    files = _daily_files_in_range(start, end)
    if not files:
        raise FileNotFoundError(
            f"No daily panel files in [{start.date()}, {end.date()}] under "
            f"{fr_config.DAILY_PANEL_DIR}"
        )
    frames = []
    for fp in files:
        df = pd.read_parquet(fp, columns=list(cols))
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    # trade_date arrives as YYYYMMDD string
    out["trade_date"] = pd.to_datetime(out["trade_date"], format="%Y%m%d")
    # Upcast all numeric to float64 (parquet stores float32)
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].astype(np.float64)
    out = out.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return out


def pivot_wide(long_df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """
    Pivot long → wide: index=trade_date, columns=ts_code, values=value_col.
    """
    return long_df.pivot(index="trade_date",
                         columns="ts_code",
                         values=value_col).sort_index()


# ─── Sector (PIT from sw_l1_membership) ────────────────────────────────

def attach_sector(panel: pd.DataFrame,
                  date_col: str = "rebalance_date",
                  ticker_col: str = "ts_code",
                  out_col: str = "industry_name") -> pd.DataFrame:
    """
    Attach point-in-time SW L1 industry_name for each (date, ticker).

    Rule: pick the membership row where in_date ≤ date_int < out_date,
    treating NaN out_date as +inf.
    """
    sw = pd.read_parquet(fr_config.SW_L1_MEMBERSHIP)
    sw["in_date_int"] = sw["in_date"].astype(int)
    sw["out_date_int"] = pd.to_numeric(sw["out_date"], errors="coerce")
    sw["out_date_int"] = sw["out_date_int"].fillna(99_999_999).astype(np.int64)

    df = panel.copy()
    df["_date_int"] = df[date_col].dt.strftime("%Y%m%d").astype(int)

    # Merge on ts_code, then filter for valid PIT window. There are typically
    # few rows per stock so a merge + filter is fine.
    merged = df.merge(
        sw[[ticker_col, "in_date_int", "out_date_int", "industry_name"]],
        on=ticker_col, how="left"
    )
    valid = (
        (merged["in_date_int"] <= merged["_date_int"])
        & (merged["_date_int"] < merged["out_date_int"])
    )
    merged = merged[valid | merged["in_date_int"].isna()]

    # Some (ts_code, date) may match multiple rows due to overlapping
    # windows; keep the most recent in_date.
    merged = (
        merged.sort_values([ticker_col, date_col, "in_date_int"])
        .drop_duplicates(subset=[ticker_col, date_col], keep="last")
    )

    result = df.merge(
        merged[[ticker_col, date_col, "industry_name"]].rename(
            columns={"industry_name": out_col}
        ),
        on=[ticker_col, date_col], how="left"
    )
    result = result.drop(columns=["_date_int"])
    return result


if __name__ == "__main__":
    # Quick smoke
    print("Loading universe (γ only)...")
    udict = load_universe_dict(gamma_only=True)
    print(f"  {len(udict)} γ rebalance dates, "
          f"first {min(udict.keys()).date()}, last {max(udict.keys()).date()}")
    sizes = [len(v) for v in udict.values()]
    print(f"  size mean {np.mean(sizes):.0f} ± {np.std(sizes):.0f}")

    print("Loading 1-week sample of daily panel...")
    end = max(udict.keys())
    start = end - pd.Timedelta(days=7)
    dp = load_daily_panel_long(start, end)
    print(f"  rows: {len(dp):,}, cols: {list(dp.columns)}, "
          f"dtypes: {dp.dtypes.to_dict()}")
    print(f"  date range in panel: "
          f"{dp['trade_date'].min().date()} .. {dp['trade_date'].max().date()}")
