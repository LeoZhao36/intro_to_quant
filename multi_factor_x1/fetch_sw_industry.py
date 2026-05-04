"""
fetch_sw_industry.py — fetch 申万一级行业 (Shenwan Level 1 Industry) classifications.

Pulls SW L1 industry membership from Tushare and saves a stock-to-industry
lookup table to data/sw_l1_membership.parquet.

Method
------
Tushare exposes industry classification through two endpoints:
  - pro.index_classify(level='L1', src='SW2021'): returns the 31 SW L1
    indices with index_code, industry_name, parent_code, level
  - pro.index_member(index_code='801010.SI'): returns each index's member
    stocks with ts_code, in_date (when stock joined), out_date (when it
    left, NaN if still active)

For our residualization we want a CURRENT snapshot: which industry is
each stock in TODAY. We don't need full history because:
  1. Industry reclassifications are rare (~1-2% of names per year)
  2. The residualization is a control regressor, not the primary signal
  3. Using current-snapshot for historical regressions introduces a tiny
     forward-looking bias, smaller than the noise from beta estimation

If you wanted strict point-in-time, you'd build a per-date lookup using
in_date and out_date. We'll start with current-snapshot and revisit
if results suggest the bias matters.

SW2021 vs SW2014
----------------
Tushare hosts the 申万 industry classifications under two versions:
  - src='SW2014': legacy SW classification (28 L1 industries)
  - src='SW2021': updated SW classification effective 2021-12-13
    (31 L1 industries, several reorganizations: 食品饮料 split,
     国防军工 promoted from L2, etc.)
We use SW2021 because it's the active classification for current dates.
For historical backtests pre-2022, the membership snapshot is "as if"
SW2021 had been in effect, which is the cleanest available approximation.

Output schema (data/sw_l1_membership.parquet):
  ts_code        str   stock code (xxxxxx.SH/SZ/BJ)
  industry_code  str   801010.SI etc
  industry_name  str   农林牧渔, 银行, ...
  in_date        str   YYYYMMDD when stock joined this industry
  out_date       str   YYYYMMDD or NaN if currently in industry

Caller helper: load_current_industry() returns ts_code -> industry_name
for currently-active membership only.

Usage
-----
    python fetch_sw_industry.py             # fetch and save
    python fetch_sw_industry.py status      # inspect cached data

Rate limits
-----------
index_member is a basic-tier endpoint (200 calls/min). With ~31 calls
total this is well under the limit.
"""

import os
import sys
import time
from pathlib import Path

import pandas as pd

# tushare_setup.py lives at the repo root.
# We use append (not insert(0, ...)) so that the multi_factor_x1 directory
# stays first in sys.path. Otherwise modules with the same name in repo_root
# (e.g. an older Project 6 hypothesis_testing.py) would shadow the local
# multi_factor_x1 versions when fetch_sw_industry is imported by other
# scripts in this folder.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)

from tushare_setup import pro


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
SW_MEMBERSHIP_PATH = DATA_DIR / "sw_l1_membership.parquet"
SW_INDUSTRIES_PATH = DATA_DIR / "sw_l1_industries.parquet"

COMPRESSION = "zstd"


def fetch_sw_l1_industries() -> pd.DataFrame:
    """Pull the list of 31 SW L1 industries (SW2021)."""
    print("Fetching SW L1 industry list (SW2021)...")
    df = pro.index_classify(level="L1", src="SW2021")
    print(f"  found {len(df)} industries")
    if len(df) == 0:
        raise RuntimeError("No industries returned. Check your Tushare permissions.")
    print(f"\n  sample:")
    print(df[["index_code", "industry_name"]].head(5).to_string(index=False))
    return df


def fetch_sw_l1_membership(industries: pd.DataFrame) -> pd.DataFrame:
    """For each SW L1 industry, pull its member stocks."""
    rows = []
    print(f"\nFetching members for {len(industries)} industries...")
    t0 = time.time()
    for i, row in industries.iterrows():
        idx_code = row["index_code"]
        ind_name = row["industry_name"]
        try:
            members = pro.index_member(index_code=idx_code)
        except Exception as e:
            print(f"  [{i+1:>2}/{len(industries)}] {idx_code} {ind_name}: ERROR {e}")
            continue
        members["industry_code"] = idx_code
        members["industry_name"] = ind_name
        rows.append(members)
        print(f"  [{i+1:>2}/{len(industries)}] {idx_code} {ind_name:<8s} "
              f"{len(members):>5} members")
        time.sleep(0.4)  # gentle rate limiting

    out = pd.concat(rows, ignore_index=True)
    print(f"\n  total membership rows: {len(out):,}")
    print(f"  unique stocks:         {out['con_code'].nunique():,}")
    print(f"  elapsed:               {time.time()-t0:.1f}s")

    # Standardize column names: con_code -> ts_code
    out = out.rename(columns={"con_code": "ts_code"})
    keep = ["ts_code", "industry_code", "industry_name", "in_date", "out_date"]
    out = out[keep]
    return out


def load_current_industry() -> pd.DataFrame:
    """
    Return ts_code -> industry mapping for currently-active members.

    Returns a DataFrame with columns: ts_code, industry_code, industry_name.
    Stocks belonging to multiple SW L1 industries (rare, due to historical
    reclassification) get the most recent assignment.
    """
    if not SW_MEMBERSHIP_PATH.exists():
        raise FileNotFoundError(
            f"{SW_MEMBERSHIP_PATH} not found. Run fetch_sw_industry.py first."
        )
    df = pd.read_parquet(SW_MEMBERSHIP_PATH)
    # Active = out_date is NaN or empty
    active = df[df["out_date"].isna() | (df["out_date"] == "")]
    # If a stock has multiple active rows (shouldn't happen but defensive),
    # take the most recent in_date
    active = active.sort_values("in_date").drop_duplicates(
        "ts_code", keep="last"
    )
    return active[["ts_code", "industry_code", "industry_name"]].reset_index(
        drop=True
    )


def status() -> None:
    if not SW_MEMBERSHIP_PATH.exists():
        print(f"No SW L1 membership cached. Run `python fetch_sw_industry.py`.")
        return

    df = pd.read_parquet(SW_MEMBERSHIP_PATH)
    print(f"SW L1 membership: {SW_MEMBERSHIP_PATH}")
    print(f"  total rows:        {len(df):,}")
    print(f"  unique stocks:     {df['ts_code'].nunique():,}")
    print(f"  unique industries: {df['industry_code'].nunique()}")
    print(f"  size:              {SW_MEMBERSHIP_PATH.stat().st_size/1024:.1f} KB")

    print(f"\n  Industry distribution (current members only):")
    active = load_current_industry()
    counts = active["industry_name"].value_counts().sort_values(ascending=False)
    for name, n in counts.items():
        print(f"    {name:<10s} {n:>5}")
    print(f"\n  Total currently-active stocks: {len(active):,}")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if mode == "status":
        status()
        return

    industries = fetch_sw_l1_industries()
    industries.to_parquet(SW_INDUSTRIES_PATH, compression=COMPRESSION, index=False)
    print(f"\nSaved industries -> {SW_INDUSTRIES_PATH}")

    membership = fetch_sw_l1_membership(industries)
    membership.to_parquet(SW_MEMBERSHIP_PATH, compression=COMPRESSION, index=False)
    print(f"\nSaved membership -> {SW_MEMBERSHIP_PATH}")

    print(f"\nDone. Run `python fetch_sw_industry.py status` to inspect.")


if __name__ == "__main__":
    main()