"""
Cost-adjusted Sharpe across all strategies in segmented_returns.csv,
correctly aligned to the common testable dates.
"""

import numpy as np
import pandas as pd

df = pd.read_csv('data/segmented_returns.csv',
                 parse_dates=['rebalance_date'])

strategy_cols = ['segmented', 'value_low_leg', 'lowvol_high_leg',
                 'value_full', 'lowvol_full', 'composite_full', 'baseline']

# --- Restrict to common testable dates ---
common = df.dropna(subset=strategy_cols).reset_index(drop=True)
print(f"Common testable dates: {len(common)} "
      f"({common['rebalance_date'].min().date()} to "
      f"{common['rebalance_date'].max().date()})\n")

# --- Cost model ---
turnover  = 0.40
slip_side = 0.001
reg_rt    = 0.00113
cost_rt   = reg_rt + 2 * slip_side
drag      = turnover * cost_rt

# --- Per-strategy gross + net at the point estimate ---
print(f"{'strategy':<18} {'mean%':>8} {'std%':>8} "
      f"{'gross_Sh':>9} {'net_Sh':>8} {'degrad':>8}")
print('-' * 64)

for col in strategy_cols:
    r = common[col]
    gross_sh = np.sqrt(12) * r.mean() / r.std()
    r_net    = r - drag
    net_sh   = np.sqrt(12) * r_net.mean() / r_net.std()
    print(f"{col:<18} {r.mean()*100:>8.3f} {r.std()*100:>8.3f} "
          f"{gross_sh:>9.3f} {net_sh:>8.3f} {gross_sh - net_sh:>8.3f}")

# --- Alpha vs baseline (level differential) ---
print("\nAlpha vs baseline (gross and net at point estimate):")
print(f"{'strategy':<18} {'alpha%':>9} {'net_alpha%':>11}")
print('-' * 42)

base = common['baseline']
# Conservative assumption: baseline turnover ~10%/mo from cap-rank reordering
baseline_drag = 0.10 * cost_rt

for col in strategy_cols:
    if col == 'baseline':
        continue
    alpha_series = common[col] - base
    alpha = alpha_series.mean()
    # Differential drag: strategy turnover - baseline turnover
    diff_drag = drag - baseline_drag
    net_alpha = alpha - diff_drag
    print(f"{col:<18} {alpha*100:>9.3f} {net_alpha*100:>11.3f}")