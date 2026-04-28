"""
Project 5 Session 1 extension: liquidity diagnostic for the bottom-1000
小盘股 universe on 2024-12-31.

Goal: find where the liquidity cliff sits, so we can pick a defensible
floor (market cap floor, liquidity floor, or both) for the full 52-date
backtest universe.

Method:
  1. For every stock that passed the Session 1 filters, pull the trailing
     20 trading days of k-data ending 2024-12-31.
  2. Compute mean daily trading value (成交额 / amount) over that window.
  3. Plot the relationship between 流通市值 and trailing-20d mean 成交额.
  4. Answer the calibration question: what fraction of the bottom 1000
     has mean daily 成交额 below 3000万 RMB?
"""

import baostock as bs
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import time

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

DATA_DIR = Path("data")
TEST_DATE = "2024-12-31"
WINDOW_START = "2024-12-01"  # 20-ish trading days before end-2024

KDATA_CACHE = DATA_DIR / f"kdata_{TEST_DATE}.csv"
LIQUIDITY_CACHE = DATA_DIR / f"liquidity_20d_{TEST_DATE}.csv"


# ==========================================================
# Rebuild the filtered universe (same as plot script)
# ==========================================================

def rebuild_filtered(kdata_path):
    df = pd.read_csv(kdata_path, dtype={'code': str})
    for col in ['close', 'volume', 'amount', 'turn']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df[df['tradestatus'] == 1]
    df = df[df['isST'] == 0]
    df = df[(df['volume'] > 0) & (df['turn'] > 0)].copy()
    df['float_shares'] = df['volume'] / (df['turn'] / 100)
    df['float_mcap_yi'] = df['close'] * df['float_shares'] / 1e8
    return df.sort_values('float_mcap_yi').reset_index(drop=True)


# ==========================================================
# Pull trailing 20 days of amount data for each stock
# ==========================================================

def pull_liquidity_window(codes, start_date, end_date):
    """
    For each code, pull daily 'amount' (成交额 in RMB) from start_date to
    end_date. Returns a long-format DataFrame with code, date, amount.
    """
    if LIQUIDITY_CACHE.exists():
        print(f"[cache] Loading liquidity data from {LIQUIDITY_CACHE}")
        return pd.read_csv(LIQUIDITY_CACHE, dtype={'code': str})

    fields = "date,code,amount,tradestatus"
    rows = []
    total = len(codes)
    failed = 0

    print(f"  Pulling 20-day window for {total} stocks. Expect 10-15 minutes.")

    for i, code in enumerate(codes):
        if i > 0 and i % 300 == 0:
            print(f"    {i}/{total} done ({failed} failures so far)")
        try:
            rs = bs.query_history_k_data_plus(
                code, fields,
                start_date=start_date, end_date=end_date,
                frequency="d", adjustflag="2",
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
    df.to_csv(LIQUIDITY_CACHE, index=False)
    print(f"  Saved {len(df)} rows to {LIQUIDITY_CACHE} ({failed} stock failures)")
    return df


# ==========================================================
# Compute mean daily 成交额 per stock
# ==========================================================

def compute_mean_amount(liquidity_df):
    """
    Mean daily 成交额 over trading days only. 停牌 days (tradestatus == 0)
    have amount == 0 and would pull the mean down artificially, so we
    exclude them before averaging.
    """
    df = liquidity_df.copy()
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
    df['tradestatus'] = pd.to_numeric(df['tradestatus'], errors='coerce')
    df = df[df['tradestatus'] == 1]  # trading days only

    mean_by_code = (
        df.groupby('code')['amount']
          .agg(['mean', 'count'])
          .rename(columns={'mean': 'mean_amount', 'count': 'trading_days'})
          .reset_index()
    )
    mean_by_code['mean_amount_wan'] = mean_by_code['mean_amount'] / 1e4  # in 万 RMB
    return mean_by_code


# ==========================================================
# The diagnostic plot
# ==========================================================

def plot_liquidity_diagnostic(merged):
    """
    Three-panel figure:
      Top-left:    scatter of mcap vs mean 成交额, log-log
      Top-right:   histogram of mean 成交额 within the bottom-1000 universe
      Bottom:      mean 成交额 by market cap decile (cliff visualization)
    """
    universe = merged.iloc[:1000].copy()
    above = merged.iloc[1000:].copy()

    fig = plt.figure(figsize=(13, 10))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1], hspace=0.3, wspace=0.3)
    ax_scatter = fig.add_subplot(gs[0, 0])
    ax_hist = fig.add_subplot(gs[0, 1])
    ax_decile = fig.add_subplot(gs[1, :])

    # --- Panel 1: scatter ---
    ax_scatter.scatter(above['float_mcap_yi'], above['mean_amount_wan'],
                       s=4, color='#bbb', alpha=0.4, label='Above bottom 1000')
    ax_scatter.scatter(universe['float_mcap_yi'], universe['mean_amount_wan'],
                       s=6, color='#b45309', alpha=0.7, label='Bottom 1000')
    ax_scatter.axhline(3000, color='#dc2626', linestyle='--', linewidth=1,
                       label='3000万 threshold')
    ax_scatter.set_xscale('log')
    ax_scatter.set_yscale('log')
    ax_scatter.set_xlabel('流通市值 (亿 RMB)')
    ax_scatter.set_ylabel('Mean daily 成交额 (万 RMB)')
    ax_scatter.set_title('Market cap vs trailing-20d mean 成交额')
    ax_scatter.legend(loc='lower right', fontsize=9)
    ax_scatter.grid(True, alpha=0.3)

    # --- Panel 2: histogram within universe ---
    log_bins = np.logspace(
        np.log10(max(universe['mean_amount_wan'].min(), 1)),
        np.log10(universe['mean_amount_wan'].max()),
        50,
    )
    ax_hist.hist(universe['mean_amount_wan'], bins=log_bins,
                 color='#b45309', edgecolor='white', alpha=0.85)
    ax_hist.axvline(3000, color='#dc2626', linestyle='--', linewidth=1.2,
                    label='3000万 threshold')
    ax_hist.set_xscale('log')
    ax_hist.set_xlabel('Mean daily 成交额 (万 RMB, log scale)')
    ax_hist.set_ylabel('Number of stocks')
    ax_hist.set_title('Liquidity distribution within bottom 1000')
    ax_hist.legend(loc='upper right', fontsize=9)
    ax_hist.grid(True, alpha=0.3)

    # --- Panel 3: decile means ---
    merged_sorted = merged.sort_values('float_mcap_yi').reset_index(drop=True)
    merged_sorted['decile'] = pd.qcut(merged_sorted['float_mcap_yi'],
                                       q=20, labels=False) + 1  # 20 ventiles
    decile_stats = merged_sorted.groupby('decile').agg(
        median_mcap=('float_mcap_yi', 'median'),
        median_amount=('mean_amount_wan', 'median'),
        p25_amount=('mean_amount_wan', lambda x: x.quantile(0.25)),
        p75_amount=('mean_amount_wan', lambda x: x.quantile(0.75)),
    ).reset_index()

    ax_decile.fill_between(decile_stats['median_mcap'],
                            decile_stats['p25_amount'],
                            decile_stats['p75_amount'],
                            color='#888', alpha=0.25, label='25-75th percentile band')
    ax_decile.plot(decile_stats['median_mcap'], decile_stats['median_amount'],
                   color='#333', marker='o', markersize=5, linewidth=1.3,
                   label='Median 成交额')
    ax_decile.axhline(3000, color='#dc2626', linestyle='--', linewidth=1,
                      label='3000万 threshold')
    ax_decile.axvline(merged.iloc[999]['float_mcap_yi'], color='#b45309',
                      linestyle=':', linewidth=1.2,
                      label=f'Bottom-1000 cutoff ({merged.iloc[999]["float_mcap_yi"]:.1f}亿)')
    ax_decile.set_xscale('log')
    ax_decile.set_yscale('log')
    ax_decile.set_xlabel('Median 流通市值 per ventile (亿 RMB)')
    ax_decile.set_ylabel('Median daily 成交额 (万 RMB)')
    ax_decile.set_title('Liquidity cliff: median daily 成交额 by market-cap ventile')
    ax_decile.legend(loc='lower right', fontsize=9)
    ax_decile.grid(True, alpha=0.3)

    out_path = DATA_DIR / f"liquidity_diagnostic_{TEST_DATE}.png"
    plt.savefig(out_path, dpi=130, bbox_inches='tight')
    print(f"\nSaved figure to {out_path}")
    plt.show()


# ==========================================================
# Summary numbers
# ==========================================================

def print_summary(merged):
    universe = merged.iloc[:1000]
    thresholds_wan = [1000, 3000, 5000, 10000]
    print("\n" + "=" * 60)
    print("LIQUIDITY SUMMARY FOR BOTTOM-1000 UNIVERSE")
    print("=" * 60)
    print(f"N = {len(universe)} stocks with trailing-20d mean 成交额 available\n")
    print("Fraction below each liquidity threshold:")
    for t in thresholds_wan:
        frac = (universe['mean_amount_wan'] < t).mean()
        count = (universe['mean_amount_wan'] < t).sum()
        print(f"  < {t:>5d}万 RMB/day:  {count:>4d} stocks ({frac*100:>5.1f}%)")

    print(f"\nWithin bottom-1000 universe, mean 成交额 percentiles:")
    for q in [0.1, 0.25, 0.5, 0.75, 0.9]:
        val = universe['mean_amount_wan'].quantile(q)
        print(f"  {int(q*100):>2d}th percentile:  {val:>8.0f} 万 RMB/day")

    print(f"\nContrast: same percentiles OUTSIDE bottom-1000:")
    above = merged.iloc[1000:]
    for q in [0.1, 0.25, 0.5, 0.75, 0.9]:
        val = above['mean_amount_wan'].quantile(q)
        print(f"  {int(q*100):>2d}th percentile:  {val:>8.0f} 万 RMB/day")


# ==========================================================
# Main
# ==========================================================

def main():
    filtered = rebuild_filtered(KDATA_CACHE)
    print(f"Filtered universe: {len(filtered)} stocks")

    lg = bs.login()
    if lg.error_code != '0':
        raise RuntimeError(f"Login failed: {lg.error_msg}")

    try:
        liquidity = pull_liquidity_window(
            filtered['code'].tolist(), WINDOW_START, TEST_DATE
        )
    finally:
        bs.logout()

    liquidity_stats = compute_mean_amount(liquidity)
    merged = filtered.merge(liquidity_stats, on='code', how='left')
    merged = merged.dropna(subset=['mean_amount_wan']).reset_index(drop=True)
    merged = merged.sort_values('float_mcap_yi').reset_index(drop=True)

    print(f"Merged frame: {len(merged)} stocks have both mcap and liquidity")

    print_summary(merged)
    plot_liquidity_diagnostic(merged)


if __name__ == "__main__":
    main()