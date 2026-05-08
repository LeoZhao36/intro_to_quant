"""
hypothesis_testing.py — bootstrap CI utilities for factor research.

Trimmed port of Project_6/Factor_Analysis_Weekly_Universe/hypothesis_testing.py.
This version keeps only what the multi_factor_x1 pipeline needs:
  - bootstrap_ci:        i.i.d. bootstrap percentile CI for any 1-D statistic
  - block_bootstrap_ci:  moving-block bootstrap for time-series statistics

Why block bootstrap matters
---------------------------
A naive i.i.d. bootstrap on autocorrelated data (daily returns, IC time
series, factor returns) gives CIs that are too narrow because it
implicitly assumes independence. Block bootstrap resamples blocks of
consecutive observations, preserving the local autocorrelation structure.
Block size is chosen to be at least as large as the autocorrelation
horizon you care about. For daily returns: 20 (~1 month). For weekly: 12.

Multi-test correction policy (locked in Project 6)
--------------------------------------------------
- Headline factor tests: Holm-Bonferroni on the family of factors.
- Within-factor robustness: Benjamini-Hochberg.
We don't apply either here; this module just builds the per-test CIs.
The downstream factor analysis script handles the family-wise correction.
"""

from typing import Callable, Optional, Sequence

import numpy as np


def bootstrap_ci(
    data: Sequence[float],
    statistic: Callable[[np.ndarray], float],
    n_boot: int = 10_000,
    ci: float = 0.95,
    seed: Optional[int] = None,
) -> dict:
    """
    Percentile-method bootstrap CI for a 1-D statistic.

    Resamples `data` with replacement `n_boot` times, computes `statistic`
    on each resample, returns the (alpha/2, 1-alpha/2) quantiles as the CI.
    Assumes observations are i.i.d.

    Returns dict: estimate, ci_low, ci_high, ci_level, boot_distribution,
                  n_boot, n_obs.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 1:
        raise ValueError(f"data must be 1-D; got shape {data.shape}")
    data = data[~np.isnan(data)]

    n = len(data)
    if n < 2:
        raise ValueError(f"need ≥2 non-NaN obs; got {n}")
    if n_boot < 100:
        raise ValueError(f"n_boot < 100 unstable; got {n_boot}")
    if not 0 < ci < 1:
        raise ValueError(f"ci must be in (0,1); got {ci}")

    rng = np.random.default_rng(seed)
    estimate = float(statistic(data))

    boot = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boot[b] = statistic(data[idx])

    alpha = 1.0 - ci
    low, high = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    return {
        "estimate": estimate,
        "ci_low": float(low),
        "ci_high": float(high),
        "ci_level": float(ci),
        "boot_distribution": boot,
        "n_boot": int(n_boot),
        "n_obs": int(n),
    }


def block_bootstrap_ci(
    data: Sequence[float],
    statistic: Callable[[np.ndarray], float],
    block_size: int = 20,
    n_boot: int = 5_000,
    ci: float = 0.95,
    seed: Optional[int] = None,
) -> dict:
    """
    Moving-block bootstrap for time-series statistics.

    Resamples blocks of `block_size` consecutive observations, concatenates
    to length n, computes `statistic`. Preserves local autocorrelation up
    to lag block_size - 1.

    block_size guidance:
      - daily returns or IC: 20 (~1 month)
      - weekly returns or IC: 12 (~1 quarter)

    Returns: same keys as bootstrap_ci, plus block_size.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 1:
        raise ValueError(f"data must be 1-D; got shape {data.shape}")
    data = data[~np.isnan(data)]

    n = len(data)
    if block_size < 1:
        raise ValueError(f"block_size must be ≥1; got {block_size}")
    if n < 2 * block_size:
        raise ValueError(
            f"need ≥{2 * block_size} obs (2 * block_size); got {n}"
        )
    if n_boot < 100:
        raise ValueError(f"n_boot < 100 unstable; got {n_boot}")
    if not 0 < ci < 1:
        raise ValueError(f"ci must be in (0,1); got {ci}")

    rng = np.random.default_rng(seed)
    estimate = float(statistic(data))

    n_blocks = (n + block_size - 1) // block_size
    max_start = n - block_size
    offsets = np.arange(block_size)

    boot = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        idx = (starts[:, None] + offsets[None, :]).ravel()[:n]
        boot[b] = statistic(data[idx])

    alpha = 1.0 - ci
    low, high = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    return {
        "estimate": estimate,
        "ci_low": float(low),
        "ci_high": float(high),
        "ci_level": float(ci),
        "boot_distribution": boot,
        "n_boot": int(n_boot),
        "n_obs": int(n),
        "block_size": int(block_size),
    }


# ─── Smoke tests ────────────────────────────────────────────────────────

def _smoke() -> None:
    rng = np.random.default_rng(42)

    # i.i.d. mean CI contains true mean
    x = rng.normal(0, 1, 500)
    r = bootstrap_ci(x, np.mean, n_boot=2000, seed=0)
    assert r["ci_low"] < 0 < r["ci_high"], "iid CI should contain 0"
    print(f"  bootstrap_ci on N(0,1): estimate={r['estimate']:.3f}, "
          f"CI=[{r['ci_low']:.3f}, {r['ci_high']:.3f}]")

    # Block bootstrap on AR(1) gives wider CI than iid
    rho = 0.5
    n = 1000
    eps = rng.normal(0, 1, n)
    ar = np.zeros(n)
    ar[0] = eps[0]
    for t in range(1, n):
        ar[t] = rho * ar[t - 1] + eps[t]
    iid = bootstrap_ci(ar, np.mean, n_boot=2000, seed=0)
    blk = block_bootstrap_ci(ar, np.mean, block_size=20, n_boot=2000, seed=0)
    iid_w = iid["ci_high"] - iid["ci_low"]
    blk_w = blk["ci_high"] - blk["ci_low"]
    assert blk_w > iid_w, "block bootstrap should give wider CI for autocorr data"
    print(f"  AR(1) ρ={rho}: iid width={iid_w:.3f}, "
          f"block width={blk_w:.3f}, ratio={blk_w/iid_w:.2f}x")
    print("hypothesis_testing smoke: OK")


if __name__ == "__main__":
    _smoke()
