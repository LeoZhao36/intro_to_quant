"""
factor_panel_builder.py — Build the rebalance-frequency factor panel.

Reads the three universe-rebuild artifacts:
  - candidate_history_panel.parquet (daily history for ~3,985 stocks)
  - universe_membership_X75_Y3000.parquet (per-rebalance in_universe flag)
  - weekly_rebalance_dates.csv (381 Wednesdays)

Produces a single parquet keyed on (rebalance_date, ts_code) carrying
everything per-factor and FMB scripts need:

    rebalance_date, ts_code, in_universe,
    close, adj_factor, adj_close, amount,
    circ_mv_yi, log_mcap,
    pe_ttm, ep,
    l1_name, l2_name, l3_name,
    forward_return

Forward return convention
-------------------------
forward_return[t] = adj_close[t+1] / adj_close[t] - 1
where adj_close = close * adj_factor (前复权).

The shift-then-validate pattern enforces that t and t+1 are CONSECUTIVE
rebalance dates. A stock suspended on the next rebalance gets NaN, not
a 2-week return, because the trade we are pricing is "buy at week t
close, sell at week t+1 close". Suspended-on-t+1 means we cannot realize
that exact trade; later trading-window returns require a different
strategy assumption (passive hold) that we are not modeling here.

Last rebalance date carries NaN forward_return by construction (no t+1
in the panel). This is burn-in, not a bug.

EP convention
-------------
ep = 1 / pe_ttm where pe_ttm > 0
   = NaN where pe_ttm <= 0 or NaN
This is the CH-3 negative-earnings exclusion. The 23% of rows with NaN
pe_ttm in the daily panel are precisely the rows we want to drop.

Universe-turnover architecture
------------------------------
Every (rebalance_date, candidate_stock) pair appears in the output, with
in_universe set True/False per the membership panel. Factor scripts
compute signals on the full panel (so 52-week formation windows have
valid data even for stocks transitioning into the universe), then
filter to in_universe=True at the cross-sectional sort step.

This is the architectural fix for the universe-turnover bias from the
original Project 6 panel that produced 19.9% FMB coverage.

Usage
-----
    python factor_panel_builder.py smoke   # first 60 weeks, verbose
    python factor_panel_builder.py full    # all 381 weeks
    python factor_panel_builder.py status  # inspect cached panel
"""

import sys
import time

import numpy as np
import pandas as pd

from config import (
    CANDIDATE_HISTORY_PATH,
    FACTOR_PANEL_PATH,
    REBALANCE_DATES_PATH,
    UNIVERSE_MEMBERSHIP_PATH,
)


# ─── Inputs ─────────────────────────────────────────────────────────────

def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, list]:
    """Load the three input artifacts; coerce dates to pd.Timestamp."""
    if not CANDIDATE_HISTORY_PATH.exists():
        raise FileNotFoundError(
            f"{CANDIDATE_HISTORY_PATH} not found. Run Stage 5 first."
        )
    if not UNIVERSE_MEMBERSHIP_PATH.exists():
        raise FileNotFoundError(
            f"{UNIVERSE_MEMBERSHIP_PATH} not found. Run Stage 3 first."
        )
    if not REBALANCE_DATES_PATH.exists():
        raise FileNotFoundError(
            f"{REBALANCE_DATES_PATH} not found. Run Stage 1 first."
        )

    print("Loading candidate_history_panel...")
    panel = pd.read_parquet(CANDIDATE_HISTORY_PATH)
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], format="%Y%m%d")
    print(f"  {len(panel):,} rows, {panel['ts_code'].nunique():,} stocks, "
          f"{panel['trade_date'].nunique()} trading days")

    print("Loading universe_membership...")
    membership = pd.read_parquet(
        UNIVERSE_MEMBERSHIP_PATH,
        columns=["rebalance_date", "ts_code", "in_universe"],
    )
    membership["rebalance_date"] = pd.to_datetime(membership["rebalance_date"])
    print(f"  {len(membership):,} rows")

    print("Loading rebalance_dates...")
    rebal_dates = pd.to_datetime(pd.read_csv(REBALANCE_DATES_PATH)["date"])
    rebalance_dates = rebal_dates.tolist()
    print(f"  {len(rebalance_dates)} weekly rebalance dates")

    return panel, membership, rebalance_dates


# ─── Core build ─────────────────────────────────────────────────────────

def build_factor_panel(verbose: bool = False,
                       n_dates_limit: int | None = None) -> pd.DataFrame:
    """
    Produce the rebalance-frequency factor panel.

    Strategy: filter daily history to rebalance dates only, giving one row
    per (rebalance_date, candidate_stock) where the stock had a daily row
    on that date. Then compute forward_return per stock by shifting
    adj_close one position forward within ts_code groups, validating
    that the shifted date is the immediate-next rebalance date.

    Stocks with no daily row on a rebalance date (suspended, pre-IPO,
    delisted) simply don't appear at that date. This is correct: they
    can't be sorted on a missing-data date anyway.
    """
    panel, membership, rebalance_dates = load_inputs()

    if n_dates_limit is not None:
        rebalance_dates = rebalance_dates[:n_dates_limit]
        print(f"\nSmoke mode: limiting to first {n_dates_limit} rebalance dates")

    # --- 1. Filter daily history to rebalance dates only --------------
    print(f"\nFiltering daily history to {len(rebalance_dates)} rebalance dates...")
    rebal_idx = pd.DatetimeIndex(rebalance_dates)
    rebal_panel = panel[panel["trade_date"].isin(rebal_idx)].copy()
    print(f"  {len(rebal_panel):,} rows survive the date filter")

    # --- 2. adj_close = close * adj_factor (前复权) --------------------
    rebal_panel["adj_close"] = (
        rebal_panel["close"].astype(float) * rebal_panel["adj_factor"].astype(float)
    )

    # --- 3. Forward return via consecutive-rebalance shift ------------
    # Sort by (ts_code, trade_date) so shift(-1) within ts_code group
    # gives the chronologically next row for that stock.
    print(f"\nComputing forward returns...")
    rebal_panel = (
        rebal_panel.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    )
    rebal_panel["next_adj_close"] = (
        rebal_panel.groupby("ts_code")["adj_close"].shift(-1)
    )
    rebal_panel["next_trade_date"] = (
        rebal_panel.groupby("ts_code")["trade_date"].shift(-1)
    )
    rebal_panel["forward_return"] = (
        rebal_panel["next_adj_close"] / rebal_panel["adj_close"] - 1
    )

    # Validate: next_trade_date must equal the consecutive-next rebalance.
    # If a stock missed week 3 (suspended), its week-2 row's next_trade_date
    # would point to week 4, NOT week 3. We invalidate that case rather than
    # treat it as a 2-week return (which would model a passive hold through
    # the suspension that this analysis does not assume).
    rebal_sorted = sorted(rebalance_dates)
    next_rebal_map = dict(zip(rebal_sorted[:-1], rebal_sorted[1:]))
    rebal_panel["expected_next_date"] = rebal_panel["trade_date"].map(next_rebal_map)

    valid_mask = rebal_panel["next_trade_date"] == rebal_panel["expected_next_date"]
    rebal_panel.loc[~valid_mask, "forward_return"] = np.nan

    if verbose:
        n_valid = int(valid_mask.sum())
        n_total = len(rebal_panel)
        n_last_date = int(
            (rebal_panel["trade_date"] == rebal_sorted[-1]).sum()
        )
        n_invalidated = n_total - n_valid - n_last_date  # last-date NaNs are by design
        print(f"  forward_return valid:           {n_valid:,} of {n_total:,} "
              f"({100*n_valid/n_total:.1f}%)")
        print(f"  invalidated (suspension gap):   {n_invalidated:,} "
              f"({100*n_invalidated/n_total:.2f}%)")
        print(f"  last-date rows (NaN by design): {n_last_date:,}")

    # --- 4. log_mcap and ep -------------------------------------------
    rebal_panel["log_mcap"] = np.log(rebal_panel["circ_mv_yi"].astype(float))

    pe_ttm = rebal_panel["pe_ttm"].astype(float)
    rebal_panel["ep"] = np.where(
        (pe_ttm > 0) & pe_ttm.notna(),
        1.0 / pe_ttm,
        np.nan,
    )
    if verbose:
        n_ep = int(rebal_panel["ep"].notna().sum())
        n_pe_pos = int((pe_ttm > 0).sum())
        n_pe_nonpos = int(((pe_ttm <= 0)).sum())
        n_pe_nan = int(pe_ttm.isna().sum())
        print(f"  ep coverage: {n_ep:,} of {len(rebal_panel):,} rows "
              f"({100*n_ep/len(rebal_panel):.1f}%)")
        print(f"    pe_ttm > 0:   {n_pe_pos:,}  (kept)")
        print(f"    pe_ttm <= 0:  {n_pe_nonpos:,}  (CH-3 exclusion)")
        print(f"    pe_ttm NaN:   {n_pe_nan:,}  (no fundamental data)")

    # --- 5. Merge in_universe flag ------------------------------------
    membership_renamed = membership.rename(columns={"rebalance_date": "trade_date"})
    rebal_panel = rebal_panel.merge(
        membership_renamed, on=["trade_date", "ts_code"], how="left"
    )
    rebal_panel["in_universe"] = rebal_panel["in_universe"].fillna(False)
    if verbose:
        n_iu = int(rebal_panel["in_universe"].sum())
        print(f"  in_universe rows: {n_iu:,} of {len(rebal_panel):,} "
              f"({100*n_iu/len(rebal_panel):.1f}%)")

    # --- 6. Final shape -----------------------------------------------
    out = rebal_panel.rename(columns={"trade_date": "rebalance_date"})
    keep_cols = [
        "rebalance_date", "ts_code", "in_universe",
        "close", "adj_factor", "adj_close", "amount",
        "circ_mv_yi", "log_mcap",
        "pe_ttm", "ep",
        "l1_name", "l2_name", "l3_name",
        "forward_return",
    ]
    out = out[keep_cols].copy()

    # Downcast numeric columns to save space.
    for c in ["close", "adj_factor", "adj_close", "amount", "circ_mv_yi",
              "log_mcap", "pe_ttm", "ep", "forward_return"]:
        out[c] = out[c].astype("float32")

    return out


# ─── Drivers ────────────────────────────────────────────────────────────

def smoke_test() -> None:
    """Build a panel for the first 60 weeks; print diagnostics."""
    print("=" * 60)
    print("FACTOR PANEL BUILDER — SMOKE (first 60 weeks)")
    print("=" * 60)

    t0 = time.time()
    out = build_factor_panel(verbose=True, n_dates_limit=60)
    elapsed = time.time() - t0

    print(f"\nSmoke result:")
    print(f"  rows:                {len(out):,}")
    print(f"  unique stocks:       {out['ts_code'].nunique():,}")
    print(f"  unique dates:        {out['rebalance_date'].nunique()}")
    print(f"  date range:          {out['rebalance_date'].min().date()} to "
          f"{out['rebalance_date'].max().date()}")
    print(f"  in_universe rows:    {int(out['in_universe'].sum()):,}")
    print(f"  elapsed:             {elapsed:.1f}s")

    # Field coverage on the full smoke panel
    print(f"\n  Field coverage (non-null, all candidates):")
    for col in ["close", "adj_close", "log_mcap", "ep", "pe_ttm",
                "l1_name", "forward_return"]:
        cov = out[col].notna().mean() * 100
        print(f"    {col:<18s} {cov:>5.1f}%")

    # Per-date in-universe count (should be 1000 except for first weeks
    # where we may not yet have 1000 eligible stocks — diagnostic).
    iu_per_date = out[out["in_universe"]].groupby("rebalance_date").size()
    print(f"\n  in_universe count per date:")
    print(f"    min={iu_per_date.min()}, median={int(iu_per_date.median())}, "
          f"max={iu_per_date.max()}")

    # Forward-return sanity (universe-equal-weight baseline)
    fr_in_univ = (
        out[out["in_universe"]].dropna(subset=["forward_return"])
        ["forward_return"]
    )
    if len(fr_in_univ) > 0:
        ann = fr_in_univ.mean() * 52 * 100
        print(f"\n  forward_return sanity (in-universe rows, all dates):")
        print(f"    n           {len(fr_in_univ):,}")
        print(f"    mean        {fr_in_univ.mean()*100:+.3f}%/wk  "
              f"(annualized ~{ann:+.1f}%)")
        print(f"    std         {fr_in_univ.std()*100:.3f}%/wk")
        print(f"    p1, p99     {fr_in_univ.quantile(0.01)*100:+.2f}%, "
              f"{fr_in_univ.quantile(0.99)*100:+.2f}%")

    print(f"\nSmoke complete. If numbers look right, run with `full`.")


def full_run() -> None:
    """Build the full panel and write to disk."""
    print("=" * 60)
    print("FACTOR PANEL BUILDER — FULL (all 381 weeks)")
    print("=" * 60)

    t0 = time.time()
    out = build_factor_panel(verbose=True, n_dates_limit=None)
    elapsed = time.time() - t0

    print(f"\nWriting -> {FACTOR_PANEL_PATH}...")
    out.to_parquet(FACTOR_PANEL_PATH, compression="zstd", index=False)

    print(f"\nFull run complete in {elapsed:.1f}s")
    print(f"  rows:          {len(out):,}")
    print(f"  unique stocks: {out['ts_code'].nunique():,}")
    print(f"  unique dates:  {out['rebalance_date'].nunique()}")
    print(f"  in_universe:   {int(out['in_universe'].sum()):,}")
    print(f"  output:        {FACTOR_PANEL_PATH}")
    print(f"  file size:     {FACTOR_PANEL_PATH.stat().st_size / (1024*1024):.1f} MB")


def status() -> None:
    if not FACTOR_PANEL_PATH.exists():
        print(f"No factor panel at {FACTOR_PANEL_PATH}. Run with `full`.")
        return

    out = pd.read_parquet(FACTOR_PANEL_PATH)
    print(f"Factor panel: {FACTOR_PANEL_PATH}")
    print(f"  rows:           {len(out):,}")
    print(f"  unique stocks:  {out['ts_code'].nunique():,}")
    print(f"  unique dates:   {out['rebalance_date'].nunique()}")
    print(f"  date range:     {out['rebalance_date'].min().date()} to "
          f"{out['rebalance_date'].max().date()}")
    print(f"  in_universe:    {int(out['in_universe'].sum()):,}")
    print(f"  file size:      "
          f"{FACTOR_PANEL_PATH.stat().st_size / (1024*1024):.1f} MB")

    print(f"\n  Field coverage (all rows):")
    for col in ["close", "adj_close", "log_mcap", "ep", "pe_ttm",
                "l1_name", "forward_return"]:
        cov = out[col].notna().mean() * 100
        print(f"    {col:<18s} {cov:>5.1f}%")

    print(f"\n  Field coverage (in_universe rows only):")
    iu = out[out["in_universe"]]
    for col in ["log_mcap", "ep", "pe_ttm", "l1_name", "forward_return"]:
        cov = iu[col].notna().mean() * 100
        print(f"    {col:<18s} {cov:>5.1f}%")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke_test()
    elif mode == "full":
        full_run()
    elif mode == "status":
        status()
    else:
        print("Usage: python factor_panel_builder.py [smoke|full|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()