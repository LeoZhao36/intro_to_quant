"""
source_ep_data.py

Project 6 Session 3: source EP (earnings yield) data for value-factor
analysis from Tushare's daily_basic endpoint, save to data/ep_panel.csv.

Approach
--------
daily_basic returns daily fundamental ratios per stock, including pe_ttm
(P/E ratio, trailing twelve months). One API call per rebalance date
(~52 calls total) returns all stocks' pe_ttm for that date, far faster
than per-stock calls. EP = 1 / pe_ttm.

Disclosure-lag handling
-----------------------
Tushare's pe_ttm uses TTM earnings from the most recent DISCLOSED
quarterly report as of the trade_date. So pe_ttm[2024-09-18] reflects
whichever quarter had been disclosed by 2024-09-18, not the period
currently being reported. The disclosure cutoff is built into the data,
no additional buffer is required.

Negative-earnings handling (per CH-3)
-------------------------------------
Stocks with TTM net profit <= 0 have pe_ttm <= 0. We set EP=NaN for
these, excluding them from the value sort but keeping the rows in the
panel for other factor analyses. NaN propagates correctly through
pd.qcut and the IC calculation.

Setup
-----
Token is loaded via the project-level tushare_setup.py, which lives at
Intro_to_Quant/tushare_setup.py (one level above this script) and reads
TUSHARE_TOKEN from .env at the same location. No per-project token
configuration is needed; just make sure .env contains your token and
that python-dotenv and tushare are installed.

If you prefer to keep tushare_setup.py in Project_5/ instead, change
PARENT_IMPORT_DIR below to point there.

Run
---
From Project_6/: `python source_ep_data.py`

Output
------
data/ep_panel.csv with columns:
  rebalance_date, ts_code, trade_date, pe, pe_ttm, pb, ps, ps_ttm,
  total_mv, circ_mv, ep
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

# Make the parent directory (Intro_to_Quant/) importable so we can use
# the shared tushare_client.py. Resolving from __file__ rather than cwd
# means this works no matter which directory you invoke the script from.
# To use a sibling project's copy instead, point PARENT_IMPORT_DIR at it
# (e.g. Path(__file__).resolve().parent.parent / "Project_5").
PARENT_IMPORT_DIR = Path(__file__).resolve().parent.parent
if str(PARENT_IMPORT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_IMPORT_DIR))

try:
    from tushare_setup import pro
except ImportError as e:
    raise ImportError(
        f"Could not import tushare_client from {PARENT_IMPORT_DIR}.\n"
        "Expected layout: tushare_client.py at the Intro_to_Quant/ root,\n"
        "exposing a module-level `pro` singleton (ts.pro_api(token)).\n"
        f"Original error: {e}"
    )

DATA_DIR = Path("data")
UNIVERSE_PATH = DATA_DIR / "universe_membership.csv"
EP_OUTPUT_PATH = DATA_DIR / "ep_panel.csv"

FIELDS = "ts_code,trade_date,pe,pe_ttm,pb,ps,ps_ttm,total_mv,circ_mv"

# Rate limit: Tushare free tier is ~120 calls/min for daily_basic. Sleep
# 0.6s between calls = 100 calls/min, comfortable headroom.
SLEEP_BETWEEN_CALLS = 0.6
RETRY_BACKOFF = 5.0  # seconds to wait before retrying after a failure


def main() -> None:
    # Pull rebalance dates from the universe -----------------------------
    universe = pd.read_csv(
        UNIVERSE_PATH,
        parse_dates=["rebalance_date"],
        dtype={"ts_code": str, "in_universe": bool},
    )
    rebalance_dates = (
        universe["rebalance_date"].drop_duplicates().sort_values().tolist()
    )
    print(f"Pulling daily_basic for {len(rebalance_dates)} rebalance dates...")
    print(
        f"  Range: {rebalance_dates[0].date()} to {rebalance_dates[-1].date()}"
    )
    print(f"  Estimated time: ~{len(rebalance_dates) * SLEEP_BETWEEN_CALLS / 60:.1f} min")
    print()

    # One API call per date ---------------------------------------------
    all_chunks = []
    for i, date in enumerate(rebalance_dates, start=1):
        date_str = date.strftime("%Y%m%d")
        try:
            df = pro.daily_basic(trade_date=date_str, fields=FIELDS)
        except Exception as e:
            print(
                f"  [{i:2d}/{len(rebalance_dates)}] {date_str}: ERROR ({e}); "
                f"retrying in {RETRY_BACKOFF}s..."
            )
            time.sleep(RETRY_BACKOFF)
            try:
                df = pro.daily_basic(trade_date=date_str, fields=FIELDS)
            except Exception as e2:
                print(f"      retry failed: {e2}; skipping this date.")
                time.sleep(SLEEP_BETWEEN_CALLS)
                continue

        if df is None or len(df) == 0:
            print(f"  [{i:2d}/{len(rebalance_dates)}] {date_str}: empty (holiday?), skipping")
            time.sleep(SLEEP_BETWEEN_CALLS)
            continue

        df["rebalance_date"] = date
        all_chunks.append(df)

        if i % 10 == 0 or i == len(rebalance_dates):
            print(f"  [{i:2d}/{len(rebalance_dates)}] {date_str}: {len(df):,} stocks")

        time.sleep(SLEEP_BETWEEN_CALLS)

    if not all_chunks:
        raise RuntimeError("No data returned for any rebalance date.")

    ep_panel = pd.concat(all_chunks, ignore_index=True)
    print(f"\nTotal rows pulled: {len(ep_panel):,}")
    print(f"Unique ts_codes:    {ep_panel['ts_code'].nunique():,}")
    print(f"Unique dates:       {ep_panel['rebalance_date'].nunique()}")

    # Compute EP, mark E<=0 as NaN per CH-3 negative-earnings exclusion --
    n_pe_missing = ep_panel["pe_ttm"].isna().sum()
    n_pe_negative = (ep_panel["pe_ttm"] <= 0).sum()
    ep_panel["ep"] = 1.0 / ep_panel["pe_ttm"]
    ep_panel.loc[ep_panel["pe_ttm"] <= 0, "ep"] = pd.NA

    n_with_ep = ep_panel["ep"].notna().sum()
    pct_with_ep = n_with_ep / len(ep_panel) * 100
    print(
        f"\nEP coverage: {n_with_ep:,} of {len(ep_panel):,} rows have ep ({pct_with_ep:.1f}%)"
    )
    print(
        f"  Excluded due to missing pe_ttm:    {n_pe_missing:,} "
        f"({n_pe_missing / len(ep_panel) * 100:.1f}%)"
    )
    print(
        f"  Excluded due to E<=0 (CH-3 rule):  {n_pe_negative:,} "
        f"({n_pe_negative / len(ep_panel) * 100:.1f}%)"
    )

    # Sanity checks ------------------------------------------------------
    ep_clean = ep_panel["ep"].dropna()
    print(f"\nEP distribution sanity checks:")
    print(f"  count:           {len(ep_clean):,}")
    print(f"  mean:            {ep_clean.mean():+.4f}")
    print(f"  median:          {ep_clean.median():+.4f}")
    print(f"  std:             {ep_clean.std():.4f}")
    print(f"  pct in [0, 0.20]:        {((ep_clean >= 0) & (ep_clean <= 0.20)).mean()*100:.1f}%")
    print(f"  pct outside [-0.5, 0.5]: {((ep_clean < -0.5) | (ep_clean > 0.5)).mean()*100:.2f}%")

    cs_std_per_date = ep_panel.groupby("rebalance_date")["ep"].std()
    print(
        f"\nCross-sectional std per date: "
        f"min {cs_std_per_date.min():.4f}, "
        f"median {cs_std_per_date.median():.4f}, "
        f"max {cs_std_per_date.max():.4f}"
    )

    # Save ---------------------------------------------------------------
    DATA_DIR.mkdir(exist_ok=True)
    ep_panel.to_csv(EP_OUTPUT_PATH, index=False)
    print(f"\nSaved to {EP_OUTPUT_PATH}")

    print("\nNext step: run `python value_analysis.py`.")


if __name__ == "__main__":
    main()