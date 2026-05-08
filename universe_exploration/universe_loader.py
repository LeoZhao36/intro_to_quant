"""
universe_loader.py — Canonical loader for the primary universe.

The primary universe is Variant B (主板-only A-share equities, ChiNext
excluded), built with the default 3-component RDI composite (holders +
funds + north). Locked 2026-05-08 after Phase 1 showed Variant B was
materially equivalent to Variant A on BS/RDI/cap centroids while having
roughly 10% lower universe-size variability.

Downstream factor research should use the helpers in this file as the
single source of truth for universe membership, and treat Variant A as
diagnostic-only.

Public API:
    load_primary_universe()  → DataFrame [trade_date, ts_code, in_hotspot,
                                          rho_at_stock, board, cap_rank,
                                          rdi_rank, bs_score]
    get_universe_at(date)    → set of ts_codes in the primary universe
                               at the given rebalance date
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

import config


def lock_primary() -> Path:
    """
    Copy universe_membership_variantB.parquet to universe_membership_primary
    .parquet so downstream callers depend on the locked alias rather than the
    variant name. Idempotent: re-running overwrites.
    """
    src = config.UNIVERSE_VARIANT_B_PATH
    dst = config.UNIVERSE_PRIMARY_PATH
    if not src.exists():
        raise FileNotFoundError(
            f"Variant B universe not built yet ({src}). Run phase1_run.py first."
        )
    shutil.copyfile(src, dst)
    return dst


def load_primary_universe() -> pd.DataFrame:
    """Load the primary universe membership panel."""
    if not config.UNIVERSE_PRIMARY_PATH.exists():
        raise FileNotFoundError(
            f"Primary universe not locked yet ({config.UNIVERSE_PRIMARY_PATH}). "
            f"Run universe_loader.lock_primary() or "
            f"`python universe_loader.py` to lock."
        )
    df = pd.read_parquet(config.UNIVERSE_PRIMARY_PATH)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def get_universe_at(date: pd.Timestamp) -> set[str]:
    """ts_codes in the primary universe at the given rebalance date."""
    df = load_primary_universe()
    mask = (df["trade_date"] == pd.Timestamp(date)) & df["in_hotspot"]
    return set(df.loc[mask, "ts_code"])


def _summary() -> None:
    df = load_primary_universe()
    in_uni = df[df["in_hotspot"]]
    n_dates = df["trade_date"].nunique()
    sizes = in_uni.groupby("trade_date")["ts_code"].size()
    print(f"primary universe: {n_dates} rebalances, "
          f"size {sizes.mean():.0f} ± {sizes.std():.0f} "
          f"(min {sizes.min()}, max {sizes.max()})")
    print(f"date range: {df['trade_date'].min().date()} .. "
          f"{df['trade_date'].max().date()}")
    print(f"unique ts_codes ever in universe: {in_uni['ts_code'].nunique()}")
    boards = in_uni["board"].value_counts()
    print(f"board mix (membership-rebalances):")
    for b, c in boards.items():
        print(f"  {b:>10}: {c:>7,} ({100*c/len(in_uni):.1f}%)")


if __name__ == "__main__":
    print("Locking primary universe (Variant B) ...")
    dst = lock_primary()
    print(f"  wrote {dst}\n")
    _summary()
