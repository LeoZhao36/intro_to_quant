"""
verify_imports.py

Smoke-tests that hypothesis_testing.py is importable as a module and that each
of the seven exported functions runs on toy data without error. This is the
"verify imports work from Project_6/" check from the Project 5 closeout bridge.

Run from the Project_6/ directory: `python verify_imports.py`
"""

import numpy as np

from hypothesis_testing import (
    t_test_two_sample,
    permutation_mean_diff,
    permutation_correlation,
    bootstrap_ci,
    block_bootstrap_ci,
    acf_band,
    cost_adjusted_sharpe,
)

rng = np.random.default_rng(42)

# Two-sample tests ----------------------------------------------------------
a = rng.normal(0, 1, 100)
b = rng.normal(0.3, 1, 100)
t_res = t_test_two_sample(a, b)
print(f"t_test:           t={t_res['t']:+.3f}, p={t_res['p_value']:.4f}, "
      f"CI=[{t_res['ci_low']:+.3f}, {t_res['ci_high']:+.3f}]")

p_res = permutation_mean_diff(a, b, n_iter=2000, seed=0)
print(f"perm_mean_diff:   diff={p_res['observed_diff']:+.3f}, p={p_res['p_value']:.4f}")

# Correlation test ----------------------------------------------------------
x = rng.normal(0, 1, 200)
y = 0.5 * x + rng.normal(0, 1, 200)
corr_res = permutation_correlation(x, y, n_iter=2000, seed=0)
print(f"perm_correlation: rho={corr_res['observed_corr']:+.3f}, p={corr_res['p_value']:.4f}")

# Bootstrap CIs -------------------------------------------------------------
data = rng.normal(0.005, 0.02, 252)  # daily-ish returns
boot = bootstrap_ci(data, np.mean, n_boot=2000, seed=0)
print(f"bootstrap_ci:     mean={boot['estimate']:+.4f}, "
      f"CI=[{boot['ci_low']:+.4f}, {boot['ci_high']:+.4f}]")

block_boot = block_bootstrap_ci(data, np.mean, block_size=20, n_boot=2000, seed=0)
print(f"block_bootstrap:  mean={block_boot['estimate']:+.4f}, "
      f"CI=[{block_boot['ci_low']:+.4f}, {block_boot['ci_high']:+.4f}]")

# Standalone utilities ------------------------------------------------------
band = acf_band(n_obs=500, n_tests=20, family_alpha=0.05)
print(f"acf_band:         half-width={band:.4f} for n=500, k=20, alpha=0.05")

sharpe = cost_adjusted_sharpe(
    rng.normal(0.012, 0.04, 60),
    cost_per_trade=0.0020,
    turnover=0.80,
    periods_per_year=12,
)
print(f"cost_adj_sharpe:  gross={sharpe['gross_sharpe']:+.3f}, "
      f"net={sharpe['net_sharpe']:+.3f}, "
      f"drag={sharpe['cost_drag_annualised']:+.3f}")

print("\nAll seven functions imported and ran successfully.")