"""
Project 5 Session 1, closeout plot: the distribution of 流通市值 across
all filtered A-share stocks, with the bottom-1000 universe highlighted.

Runs against the cached filtered universe from build_universe_single_date.py.
No baostock calls, reads from cached CSVs only.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

# ==========================================================
# Chinese font setup, needed for axis labels and legend text
# ==========================================================

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

DATA_DIR = Path("data")
TEST_DATE = "2024-12-31"
KDATA_CACHE = DATA_DIR / f"kdata_{TEST_DATE}.csv"


# ==========================================================
# Rebuild the filtered universe from cached k-data
# ==========================================================

def rebuild_filtered(kdata_path):
    """
    Re-apply the same filters and market cap derivation used in
    build_universe_single_date.py, so we get the full filtered
    frame of 4984 stocks, not just the bottom 1000.
    """
    df = pd.read_csv(kdata_path, dtype={'code': str})

    for col in ['close', 'volume', 'amount', 'turn']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df[df['tradestatus'] == 1]
    df = df[df['isST'] == 0]
    df = df[(df['volume'] > 0) & (df['turn'] > 0)].copy()

    df['float_shares'] = df['volume'] / (df['turn'] / 100)
    df['float_mcap'] = df['close'] * df['float_shares']
    df['float_mcap_yi'] = df['float_mcap'] / 1e8
    df = df.sort_values('float_mcap_yi', ascending=True).reset_index(drop=True)
    return df


# ==========================================================
# The plot
# ==========================================================

def plot_distribution(filtered_df):
    """
    Two-panel figure:
      Top:     histogram of 流通市值 across all filtered stocks, log x-axis
      Bottom:  ECDF (cumulative distribution) with key quantiles marked
    """
    mcap = filtered_df['float_mcap_yi'].values
    cutoff = mcap[999]  # the 1000th smallest = boundary of our universe

    # Bin edges on log scale, because mcap spans roughly 3 orders of magnitude
    bins = np.logspace(np.log10(mcap.min()), np.log10(mcap.max()), 60)

    fig, (ax_hist, ax_ecdf) = plt.subplots(
        2, 1, figsize=(11, 9), gridspec_kw={'height_ratios': [1.2, 1]}
    )

    # --- Top panel: histogram with universe shading ---
    ax_hist.hist(mcap, bins=bins, color='#888888', edgecolor='white',
                 linewidth=0.4, alpha=0.85, label='All filtered A-shares')

    in_universe = mcap[mcap <= cutoff]
    ax_hist.hist(in_universe, bins=bins, color='#b45309', edgecolor='white',
                 linewidth=0.4, alpha=0.9, label=f'Bottom 1000 (our universe)')

    ax_hist.axvline(cutoff, color='#b45309', linestyle='--', linewidth=1.2)
    ax_hist.text(cutoff * 1.05, ax_hist.get_ylim()[1] * 0.9,
                 f'cutoff = {cutoff:.2f}亿',
                 fontsize=10, color='#b45309')

    ax_hist.axvline(50, color='#1d4ed8', linestyle=':', linewidth=1.2)
    ax_hist.text(50 * 1.05, ax_hist.get_ylim()[1] * 0.75,
                 'your prediction = 50亿',
                 fontsize=10, color='#1d4ed8')

    ax_hist.set_xscale('log')
    ax_hist.set_xlabel('流通市值 (亿 RMB, log scale)')
    ax_hist.set_ylabel('Number of stocks')
    ax_hist.set_title(f'A-share 流通市值 distribution on {TEST_DATE} '
                      f'(N = {len(mcap)} stocks after filters)')
    ax_hist.legend(loc='upper right')
    ax_hist.grid(True, alpha=0.3)

    # --- Bottom panel: ECDF ---
    n = len(mcap)
    ecdf_y = np.arange(1, n + 1) / n
    ax_ecdf.plot(mcap, ecdf_y, color='#333333', linewidth=1.2)

    # Shade the universe region
    ax_ecdf.axvspan(mcap.min(), cutoff, color='#b45309', alpha=0.15)
    ax_ecdf.axvline(cutoff, color='#b45309', linestyle='--', linewidth=1.2)
    ax_ecdf.axvline(50, color='#1d4ed8', linestyle=':', linewidth=1.2)

    # Mark key quantiles
    quantiles_to_mark = [0.1, 0.2, 0.5, 0.8]
    for q in quantiles_to_mark:
        val = np.quantile(mcap, q)
        ax_ecdf.plot([val, val], [0, q], color='#666', linestyle=':', linewidth=0.6)
        ax_ecdf.plot([mcap.min(), val], [q, q], color='#666', linestyle=':', linewidth=0.6)
        ax_ecdf.text(val * 1.05, q + 0.015, f'{int(q*100)}%ile = {val:.1f}亿',
                     fontsize=9, color='#333')

    ax_ecdf.set_xscale('log')
    ax_ecdf.set_xlabel('流通市值 (亿 RMB, log scale)')
    ax_ecdf.set_ylabel('Cumulative fraction of stocks')
    ax_ecdf.set_title('Empirical CDF: what fraction of A-shares fall below each 流通市值 level?')
    ax_ecdf.set_ylim(0, 1.02)
    ax_ecdf.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = DATA_DIR / f"mcap_distribution_{TEST_DATE}.png"
    plt.savefig(out_path, dpi=130, bbox_inches='tight')
    print(f"Saved figure to {out_path}")
    plt.show()


# ==========================================================
# Print summary stats used in the interpretation
# ==========================================================

def print_distribution_summary(filtered_df):
    mcap = filtered_df['float_mcap_yi'].values
    print("\n流通市值 distribution summary (亿 RMB):")
    print(f"  Count:              {len(mcap)}")
    print(f"  Minimum:            {mcap.min():.2f}")
    print(f"  10th percentile:    {np.quantile(mcap, 0.10):.2f}")
    print(f"  20th percentile:    {np.quantile(mcap, 0.20):.2f}")
    print(f"  50th percentile:    {np.quantile(mcap, 0.50):.2f}")
    print(f"  80th percentile:    {np.quantile(mcap, 0.80):.2f}")
    print(f"  90th percentile:    {np.quantile(mcap, 0.90):.2f}")
    print(f"  Maximum:            {mcap.max():.2f}")
    print(f"\n  How many stocks under 50亿 (your prediction):  "
          f"{int((mcap < 50).sum())} of {len(mcap)} "
          f"({(mcap < 50).mean()*100:.1f}%)")
    print(f"  How many stocks under 20亿:                   "
          f"{int((mcap < 20).sum())} of {len(mcap)} "
          f"({(mcap < 20).mean()*100:.1f}%)")


# ==========================================================
# Main
# ==========================================================

if __name__ == "__main__":
    filtered = rebuild_filtered(KDATA_CACHE)
    print_distribution_summary(filtered)
    plot_distribution(filtered)