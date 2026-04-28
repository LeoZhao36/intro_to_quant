"""
Project 5 Session 1: construct the 小盘股 universe for a single historical date.

Target date: 2024-12-31 (calibration run before scaling to the 52-date loop).

Universe definition:
  - A-share equities from Shanghai and Shenzhen exchanges only
  - Excludes 北交所 (Beijing Exchange)
  - Excludes B-shares, ETFs, LOFs, indexes
  - Excludes ST and *ST stocks (风险警示板)
  - Excludes stocks that were 停牌 on the date
  - Ranked ascending by 流通市值 (free-float market cap)
  - Take the bottom 1000
"""

import baostock as bs
import pandas as pd
import numpy as np
from pathlib import Path
import time

# ==========================================================
# Configuration
# ==========================================================

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

TEST_DATE = "2024-12-31"

LISTINGS_CACHE = DATA_DIR / f"all_listings_{TEST_DATE}.csv"
KDATA_CACHE = DATA_DIR / f"kdata_{TEST_DATE}.csv"
UNIVERSE_CACHE = DATA_DIR / f"universe_bottom1000_{TEST_DATE}.csv"


# ==========================================================
# Step 1: get all listings on the target date
# ==========================================================

def get_all_listings(date):
    """
    Pull every code listed on `date` from baostock.
    Returns a DataFrame with columns: code, tradeStatus, code_name.
    """
    if LISTINGS_CACHE.exists():
        print(f"[cache] Loading listings from {LISTINGS_CACHE}")
        return pd.read_csv(LISTINGS_CACHE, dtype=str)

    rs = bs.query_all_stock(day=date)
    if rs.error_code != '0':
        raise RuntimeError(f"query_all_stock failed: {rs.error_msg}")

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    df = pd.DataFrame(rows, columns=rs.fields)
    df.to_csv(LISTINGS_CACHE, index=False)
    print(f"  Pulled {len(df)} listings, saved to {LISTINGS_CACHE}")
    return df


# ==========================================================
# Step 2: filter to A-share equities only
# ==========================================================

def filter_a_shares(listings_df):
    """
    Keep only A-share equity codes. Drops B-shares, ETFs, LOFs, indexes, 北交所.

    A-share prefixes:
      sh.60, sh.68   Shanghai main board + 科创板 (STAR Market)
      sz.00, sz.30   Shenzhen main board + SME + 创业板 (ChiNext)

    Everything else is excluded: sh.51x (ETFs), sh.90x (B-shares),
    sz.15x (ETFs), sz.20x (B-shares), sz.39x (indexes), bj.* (北交所).
    """
    a_share_prefixes = ('sh.60', 'sh.68', 'sz.00', 'sz.30')
    mask = listings_df['code'].str.startswith(a_share_prefixes)
    return listings_df[mask].copy()


# ==========================================================
# Step 3: pull one day of k-data for each A-share
# ==========================================================

def pull_daily_kdata(codes, date):
    """
    For each code, pull a single day of k-data with the fields needed to
    derive 流通市值.

    Fields: code, close, volume, amount, turn, tradestatus, isST
      close        closing price in RMB
      volume       number of shares traded (股)
      amount       trading value in RMB
      turn         turnover rate (%) computed against 流通股本
      tradestatus  1=normal trading, 0=suspended
      isST         1=ST or *ST, 0=normal
    """
    if KDATA_CACHE.exists():
        print(f"[cache] Loading k-data from {KDATA_CACHE}")
        return pd.read_csv(KDATA_CACHE, dtype={'code': str})

    fields = "code,close,volume,amount,turn,tradestatus,isST"
    rows = []
    total = len(codes)
    failed = 0

    print(f"  Pulling k-data for {total} stocks. This takes ~15-25 minutes.")

    for i, code in enumerate(codes):
        if i > 0 and i % 200 == 0:
            print(f"    {i}/{total} done ({failed} failures so far)")

        try:
            rs = bs.query_history_k_data_plus(
                code,
                fields,
                start_date=date,
                end_date=date,
                frequency="d",
                adjustflag="2",  # 前复权 (forward-adjusted)
            )
            if rs.error_code != '0':
                failed += 1
                continue
            while rs.next():
                rows.append(rs.get_row_data())
        except Exception:
            failed += 1
            time.sleep(0.2)
            continue

    df = pd.DataFrame(rows, columns=fields.split(','))
    df.to_csv(KDATA_CACHE, index=False)
    print(f"  Got k-data for {len(df)} stocks ({failed} failures). Saved to {KDATA_CACHE}")
    return df


# ==========================================================
# Step 4: derive 流通市值 and apply universe filters
# ==========================================================

def build_filtered_universe(kdata_df):
    """
    Apply the three universe filters, then derive 流通市值.

    Formula:
      流通股本 = volume / (turn / 100)      [shares in free float]
      流通市值 = close × 流通股本            [market value in RMB]

    Filters applied in order:
      1. tradestatus == '1'  (drop 停牌 stocks)
      2. isST == '0'         (drop ST and *ST)
      3. volume > 0 and turn > 0  (cannot derive mcap without these)
    """
    df = kdata_df.copy()

    # baostock returns everything as strings, convert numerics
    for col in ['close', 'volume', 'amount', 'turn']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    print("\nFilter pipeline:")
    print(f"  Start:                 {len(df):>5d} stocks")

    n_before = len(df)
    df = df[df['tradestatus'] == '1']
    print(f"  After 停牌 filter:      {len(df):>5d} stocks  (dropped {n_before - len(df)})")

    n_before = len(df)
    df = df[df['isST'] == '0']
    print(f"  After ST filter:       {len(df):>5d} stocks  (dropped {n_before - len(df)})")

    n_before = len(df)
    df = df[(df['volume'] > 0) & (df['turn'] > 0)]
    print(f"  After volume filter:   {len(df):>5d} stocks  (dropped {n_before - len(df)})")

    df['float_shares'] = df['volume'] / (df['turn'] / 100)
    df['float_mcap'] = df['close'] * df['float_shares']
    df['float_mcap_yi'] = df['float_mcap'] / 1e8  # convert to 亿 RMB for readability

    return df


# ==========================================================
# Main
# ==========================================================

def main():
    print(f"Building 小盘股 universe for {TEST_DATE}")
    print("=" * 60)

    # baostock requires explicit login before any query
    lg = bs.login()
    if lg.error_code != '0':
        raise RuntimeError(f"Login failed: {lg.error_msg}")

    try:
        listings = get_all_listings(TEST_DATE)
        a_shares = filter_a_shares(listings)
        print(f"\nAll listings on {TEST_DATE}: {len(listings)}")
        print(f"A-share equities only:     {len(a_shares)}")

        kdata = pull_daily_kdata(a_shares['code'].tolist(), TEST_DATE)
        filtered = build_filtered_universe(kdata)

        filtered_sorted = filtered.sort_values('float_mcap', ascending=True)
        universe = filtered_sorted.head(1000).copy()
        universe.to_csv(UNIVERSE_CACHE, index=False)
        print(f"\nSaved bottom-1000 universe to {UNIVERSE_CACHE}")

    finally:
        bs.logout()

    # ======================================================
    # Report the four numbers
    # ======================================================

    total_listings_all = len(listings)
    total_a_shares = len(a_shares)
    after_filters = len(filtered)
    cutoff_yi = universe['float_mcap_yi'].iloc[-1]
    smallest_yi = universe['float_mcap_yi'].iloc[0]
    largest_yi = universe['float_mcap_yi'].iloc[-1]
    ratio = largest_yi / smallest_yi

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"1. Total listings on {TEST_DATE} (all code types):  {total_listings_all}")
    print(f"   Of which A-share equities:                       {total_a_shares}")
    print(f"2. Stocks surviving all filters:                    {after_filters}")
    print(f"3. 流通市值 cutoff at 1000th smallest:              {cutoff_yi:.2f} 亿 RMB")
    print(f"4. Within the bottom 1000:")
    print(f"     Smallest 流通市值:  {smallest_yi:.2f} 亿 RMB")
    print(f"     Largest 流通市值:   {largest_yi:.2f} 亿 RMB")
    print(f"     Ratio:               {ratio:.2f}x")


if __name__ == "__main__":
    main()