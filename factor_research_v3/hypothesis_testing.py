"""
hypothesis_testing.py — v3-local block bootstrap.

Trimmed local port of multi_factor_x1/hypothesis_testing.py.

For monthly-cadence stats over a γ window of ~25 periods, use
block_size=3 (≈ one quarter of monthly observations) and n_boot=10000.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

import numpy as np


def bootstrap_ci(
    data: Sequence[float],
    statistic: Callable[[np.ndarray], float],
    n_boot: int = 10_000,
    ci: float = 0.95,
    seed: Optional[int] = None,
) -> dict:
    """i.i.d. percentile bootstrap CI."""
    data = np.asarray(data, dtype=float)
    if data.ndim != 1:
        raise ValueError(f"data must be 1-D; got shape {data.shape}")
    data = data[~np.isnan(data)]
    n = len(data)
    if n < 2:
        raise ValueError(f"need ≥2 non-NaN obs; got {n}")
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
    block_size: int = 3,
    n_boot: int = 10_000,
    ci: float = 0.95,
    seed: Optional[int] = None,
) -> dict:
    """
    Moving-block percentile bootstrap CI for time-series statistics.

    block_size guidance:
      - daily:   20 (~1 month)
      - weekly:  12 (~1 quarter)
      - monthly: 3  (~1 quarter)
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 1:
        raise ValueError(f"data must be 1-D; got shape {data.shape}")
    data = data[~np.isnan(data)]
    n = len(data)
    if block_size < 1:
        raise ValueError(f"block_size must be ≥1; got {block_size}")
    if n < 2 * block_size:
        raise ValueError(f"need ≥{2 * block_size} obs; got {n}")
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
