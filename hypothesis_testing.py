"""
Hypothesis-testing toolkit consolidated from Project 4 Sessions 1–4.

Framework: every test answers the same question — how often would data this
extreme arise if there were no real effect? t-tests answer parametrically.
Permutation tests answer by relabeling. Bootstrap inverts the question into a
CI on the estimate. Bonferroni corrects for a family of tests.

Conventions encoded here (see Project_4_Closeout.md):
- n_iter / n_boot default 10_000 for permutation and bootstrap CIs.
- block_size default 20 for daily-returns block bootstrap (≈ 1 month).
- ci default 0.95 for all CI functions.
- A-share trading-days = 242 for annualization in cost_adjusted_sharpe.

Design choice: permutation and bootstrap helpers are vectorized over the
iteration axis so a 10_000-iteration run on 250 daily returns finishes in
well under a second. The user-supplied ``statistic`` callable is called once
on a (n_boot, n) matrix with axis=1, falling back to np.apply_along_axis if
the callable does not accept an axis argument.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
from scipy import stats


TRADING_DAYS_A_SHARE = 242


# ─── P-value helpers ───────────────────────────────────────

def p_value_two_tailed(null_stats, observed):
    """Fraction of null statistics at least as extreme (in absolute value) as observed."""
    null_stats = np.asarray(null_stats)
    return float(np.mean(np.abs(null_stats) >= abs(observed)))


# ─── Permutation tests (vectorized) ─────────────────────────

def _pearson_rowwise(x, Y):
    """Pearson correlation between 1-D x and each row of 2-D Y. Vectorized."""
    x = np.asarray(x, dtype=float)
    Y = np.asarray(Y, dtype=float)
    x_c = x - x.mean()
    Y_c = Y - Y.mean(axis=1, keepdims=True)
    num = Y_c @ x_c
    denom = np.sqrt((Y_c ** 2).sum(axis=1) * (x_c ** 2).sum())
    return num / denom


def permutation_correlation(x, y, n_iter=10_000, seed=42):
    """
    Permutation test for Pearson correlation between x and y.

    Null hypothesis: x and y are independent (equivalently, y-values are
    exchangeable with respect to x-positions).

    Returns (null_corrs, p_two_tailed).
        null_corrs: array of shape (n_iter,) — null distribution.
        p_two_tailed: fraction of null |corr| ≥ |observed|.

    Vectorized: permutes y's index in one shot and computes all correlations
    in a single matrix operation. ~50–100× faster than the loop version at
    n_iter=10_000.
    """
    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if len(y) != n:
        raise ValueError(f"x and y must have equal length (got {n} vs {len(y)})")

    Y_perm = np.tile(y, (n_iter, 1))
    rng.permuted(Y_perm, axis=1, out=Y_perm)

    null_corrs = _pearson_rowwise(x, Y_perm)
    observed = float(np.corrcoef(x, y)[0, 1])
    p = p_value_two_tailed(null_corrs, observed)
    return null_corrs, p


def permutation_mean_diff(group_a, group_b, n_iter=10_000, seed=42):
    """
    Permutation test for the difference in means between two independent groups.

    Null hypothesis: the two groups come from the same distribution.

    Returns (null_diffs, p_two_tailed).

    Vectorized: pools once, permutes in a (n_iter, n_total) index matrix, then
    computes group means along axis=1. ~30–50× faster than the loop version.
    """
    rng = np.random.default_rng(seed)
    a = np.asarray(group_a, dtype=float)
    b = np.asarray(group_b, dtype=float)
    n_a = len(a)
    pooled = np.concatenate([a, b])
    n_total = len(pooled)

    idx = np.tile(np.arange(n_total), (n_iter, 1))
    rng.permuted(idx, axis=1, out=idx)
    shuffled = pooled[idx]

    null_diffs = shuffled[:, n_a:].mean(axis=1) - shuffled[:, :n_a].mean(axis=1)
    observed = float(a.mean() - b.mean())
    p = p_value_two_tailed(null_diffs, observed)
    return null_diffs, p


# ─── t-test wrappers ───────────────────────────────────────

def _t_ci(t, df, mean_est, se, ci):
    alpha = 1 - ci
    crit = stats.t.ppf(1 - alpha / 2, df)
    return float(mean_est - crit * se), float(mean_est + crit * se)


def t_test_one_sample(data, mu=0, ci=0.95):
    """
    One-sample t-test against ``mu``.

    Returns {'t', 'p', 'df', 'ci_lower', 'ci_upper'} where the CI is on the
    sample mean (not on mean - mu).
    """
    x = np.asarray(data, dtype=float)
    n = len(x)
    res = stats.ttest_1samp(x, mu)
    df = n - 1
    se = x.std(ddof=1) / np.sqrt(n)
    lo, hi = _t_ci(res.statistic, df, x.mean(), se, ci)
    return {
        "t": float(res.statistic),
        "p": float(res.pvalue),
        "df": float(df),
        "ci_lower": lo,
        "ci_upper": hi,
    }


def t_test_two_sample(a, b, equal_var=False, ci=0.95):
    """
    Two-sample t-test for mean(a) vs mean(b). Welch by default (equal_var=False).

    Returns {'t', 'p', 'df', 'ci_lower', 'ci_upper'} where the CI is on the
    difference mean(a) - mean(b).
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    res = stats.ttest_ind(a, b, equal_var=equal_var)
    na, nb = len(a), len(b)
    va, vb = a.var(ddof=1), b.var(ddof=1)
    if equal_var:
        df = na + nb - 2
        pooled_var = ((na - 1) * va + (nb - 1) * vb) / df
        se = np.sqrt(pooled_var * (1 / na + 1 / nb))
    else:
        se = np.sqrt(va / na + vb / nb)
        df = (va / na + vb / nb) ** 2 / (
            (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
        )
    lo, hi = _t_ci(res.statistic, df, a.mean() - b.mean(), se, ci)
    return {
        "t": float(res.statistic),
        "p": float(res.pvalue),
        "df": float(df),
        "ci_lower": lo,
        "ci_upper": hi,
    }


def t_test_paired(a, b, ci=0.95):
    """
    Paired t-test on matched observations (a[i] with b[i]).

    Returns {'t', 'p', 'df', 'ci_lower', 'ci_upper'} where the CI is on the
    mean of the within-pair differences (a - b).
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) != len(b):
        raise ValueError(f"paired t-test needs equal lengths (got {len(a)} vs {len(b)})")
    d = a - b
    n = len(d)
    res = stats.ttest_rel(a, b)
    df = n - 1
    se = d.std(ddof=1) / np.sqrt(n)
    lo, hi = _t_ci(res.statistic, df, d.mean(), se, ci)
    return {
        "t": float(res.statistic),
        "p": float(res.pvalue),
        "df": float(df),
        "ci_lower": lo,
        "ci_upper": hi,
    }


# ─── Multiple-testing corrections ──────────────────────────

def bonferroni_threshold(alpha, n_tests):
    """Per-test threshold for family-wise α under Bonferroni: α / n_tests."""
    if n_tests <= 0:
        raise ValueError("n_tests must be a positive integer")
    return alpha / n_tests


def acf_band(n_obs, n_tests, family_alpha=0.05):
    """
    Bonferroni-corrected ACF confidence band (lower, upper) half-widths.

    Under the null of white noise and large-sample normality, the sampling
    standard error of each sample autocorrelation is 1/√n_obs. The band half-
    width at per-test α' = family_alpha / n_tests is z_{1-α'/2} / √n_obs.
    """
    per_test_alpha = family_alpha / n_tests
    z_critical = stats.norm.ppf(1 - per_test_alpha / 2)
    half_width = z_critical / np.sqrt(n_obs)
    return -half_width, half_width


# ─── Cost-adjusted Sharpe ───────────────────────────────────

def cost_adjusted_sharpe(returns, cost_per_trade, turnover,
                         trading_days=TRADING_DAYS_A_SHARE):
    """
    Annualized gross and net Sharpe for a daily return series.

    cost_per_trade: round-trip cost as a fraction (e.g. 0.003 = 30 bp).
    turnover:       annualized turnover as a fraction of NAV (e.g. 5.0 = full
                    portfolio rotated five times per year).

    Applies cost as a constant daily bleed: daily_cost = cost * turnover / trading_days.
    This matches the Session 2 convention (震元 2024 gross 1.81, net 0.54 at
    0.30% round-trip cost).

    Returns {'gross_sharpe', 'net_sharpe', 'daily_cost'}.
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    mu = r.mean()
    sigma = r.std(ddof=1)
    if sigma == 0:
        raise ValueError("Cannot compute Sharpe: zero return std")

    ann_factor = np.sqrt(trading_days)
    gross = mu / sigma * ann_factor

    daily_cost = cost_per_trade * turnover / trading_days
    net = (mu - daily_cost) / sigma * ann_factor

    return {
        "gross_sharpe": float(gross),
        "net_sharpe": float(net),
        "daily_cost": float(daily_cost),
    }


# ─── Bootstrap ─────────────────────────────────────────────

def _apply_statistic(samples, statistic):
    """Apply ``statistic`` to each row of a 2-D sample matrix.

    Tries vectorized ``statistic(samples, axis=1)`` first; falls back to
    np.apply_along_axis when the callable does not accept an axis argument.
    """
    try:
        out = statistic(samples, axis=1)
        out = np.asarray(out)
        if out.shape[0] != samples.shape[0]:
            raise ValueError
        return out
    except (TypeError, ValueError):
        return np.apply_along_axis(statistic, 1, samples)


def bootstrap_ci(data, statistic=np.mean, n_boot=10_000, ci=0.95, seed=None):
    """
    General-purpose bootstrap confidence interval for any 1-D statistic.

    data: 1-D array-like.
    statistic: callable(array) -> scalar, or callable(matrix, axis=1) -> array.
               Defaults to np.mean. For Sharpe, drawdown, correlation, etc.,
               pass your own callable.
    n_boot:  number of bootstrap resamples (10_000 standard).
    ci:      confidence level (0.95 → 95% CI).
    seed:    random seed for reproducibility.

    Returns {'estimate', 'ci_lower', 'ci_upper', 'boot_distribution'}.

    Note: naive bootstrap silently understates uncertainty on serially-
    correlated data. For time series use block_bootstrap_ci.
    """
    rng = np.random.default_rng(seed)
    arr = np.asarray(data)
    n = len(arr)
    if n == 0:
        raise ValueError("data is empty")

    idx = rng.integers(0, n, size=(n_boot, n))
    samples = arr[idx]
    boot_stats = _apply_statistic(samples, statistic)

    alpha = 1 - ci
    lo = float(np.quantile(boot_stats, alpha / 2))
    hi = float(np.quantile(boot_stats, 1 - alpha / 2))

    try:
        est = float(statistic(arr))
    except TypeError:
        est = float(statistic(arr[np.newaxis, :], axis=1)[0])

    return {
        "estimate": est,
        "ci_lower": lo,
        "ci_upper": hi,
        "boot_distribution": boot_stats,
    }


def block_bootstrap_ci(data, statistic=np.mean, block_size=20,
                       n_boot=5_000, ci=0.95, seed=None):
    """
    Moving-block bootstrap CI for a time-series statistic.

    Draws contiguous blocks of length ``block_size`` (with replacement) and
    concatenates them to form each bootstrap replicate. Preserves intra-block
    correlation; between-block correlation is lost.

    block_size default 20 ≈ one trading month for daily A-share data (see
    Project 4 Session 4). Use ~3 for monthly series.

    Returns {'estimate', 'ci_lower', 'ci_upper', 'boot_distribution'}.
    """
    rng = np.random.default_rng(seed)
    arr = np.asarray(data)
    n = len(arr)
    if n == 0:
        raise ValueError("data is empty")
    if block_size <= 0 or block_size > n:
        raise ValueError(f"block_size must be in [1, {n}]; got {block_size}")

    n_blocks = int(np.ceil(n / block_size))
    max_start = n - block_size
    block_starts = rng.integers(0, max_start + 1, size=(n_boot, n_blocks))

    # Fancy-index to gather contiguous blocks in one shot.
    offsets = np.arange(block_size)
    gather_idx = block_starts[:, :, None] + offsets[None, None, :]
    samples = arr[gather_idx].reshape(n_boot, n_blocks * block_size)[:, :n]

    boot_stats = _apply_statistic(samples, statistic)

    alpha = 1 - ci
    lo = float(np.quantile(boot_stats, alpha / 2))
    hi = float(np.quantile(boot_stats, 1 - alpha / 2))

    try:
        est = float(statistic(arr))
    except TypeError:
        est = float(statistic(arr[np.newaxis, :], axis=1)[0])

    return {
        "estimate": est,
        "ci_lower": lo,
        "ci_upper": hi,
        "boot_distribution": boot_stats,
    }


# ─── Smoke tests ────────────────────────────────────────────

def _smoke_test():
    """Correctness checks that do not require network access."""
    rng = np.random.default_rng(0)

    # p_value_two_tailed: symmetric null around 0, observed at 0 → p ≈ 1
    null = rng.standard_normal(5000)
    assert 0.8 < p_value_two_tailed(null, 0.0) <= 1.0

    # Permutation correlation: uncorrelated → p ≫ 0.05; correlated → p ≪ 0.05
    x = rng.standard_normal(200)
    y_indep = rng.standard_normal(200)
    y_linked = x + 0.3 * rng.standard_normal(200)
    _, p_indep = permutation_correlation(x, y_indep, n_iter=1000, seed=1)
    _, p_linked = permutation_correlation(x, y_linked, n_iter=1000, seed=1)
    assert p_indep > 0.05, f"uncorrelated pair should not be significant, got p={p_indep}"
    assert p_linked < 0.01, f"correlated pair should be significant, got p={p_linked}"

    # Permutation mean diff: equal-mean → p ≫ 0.05; shifted → p ≪ 0.05
    a = rng.standard_normal(150)
    b_same = rng.standard_normal(150)
    b_shift = rng.standard_normal(150) + 0.5
    _, p_same = permutation_mean_diff(a, b_same, n_iter=1000, seed=2)
    _, p_shift = permutation_mean_diff(a, b_shift, n_iter=1000, seed=2)
    assert p_same > 0.05
    assert p_shift < 0.01

    # t-tests agree with scipy on the statistic and p-value
    a = rng.standard_normal(50)
    b = rng.standard_normal(50) + 0.3
    mine = t_test_two_sample(a, b)
    ref = stats.ttest_ind(a, b, equal_var=False)
    assert abs(mine["t"] - ref.statistic) < 1e-10
    assert abs(mine["p"] - ref.pvalue) < 1e-10

    one = t_test_one_sample(a, mu=0)
    ref1 = stats.ttest_1samp(a, 0)
    assert abs(one["t"] - ref1.statistic) < 1e-10

    pair = t_test_paired(a, b[: len(a)])
    refp = stats.ttest_rel(a, b[: len(a)])
    assert abs(pair["t"] - refp.statistic) < 1e-10

    # Bonferroni and ACF band
    assert abs(bonferroni_threshold(0.05, 20) - 0.0025) < 1e-15
    lo, hi = acf_band(n_obs=1000, n_tests=20, family_alpha=0.05)
    assert lo < 0 < hi
    assert abs(lo + hi) < 1e-12  # symmetric
    # z_{1 - 0.0025/2} / sqrt(1000) ≈ 3.0233 / 31.623 ≈ 0.0956
    assert 0.09 < hi < 0.10

    # bootstrap_ci
    data = rng.standard_normal(500)
    boot = bootstrap_ci(data, n_boot=1000, seed=3)
    assert set(boot) == {"estimate", "ci_lower", "ci_upper", "boot_distribution"}
    assert boot["ci_lower"] < boot["estimate"] < boot["ci_upper"]
    assert len(boot["boot_distribution"]) == 1000

    # block_bootstrap_ci on AR(1) data — should give a wider CI than naive
    eps = rng.standard_normal(500)
    ar1 = np.empty(500)
    ar1[0] = eps[0]
    for i in range(1, 500):
        ar1[i] = 0.5 * ar1[i - 1] + eps[i]
    naive = bootstrap_ci(ar1, n_boot=1000, seed=4)
    block = block_bootstrap_ci(ar1, block_size=20, n_boot=1000, seed=4)
    naive_width = naive["ci_upper"] - naive["ci_lower"]
    block_width = block["ci_upper"] - block["ci_lower"]
    assert block_width > naive_width, (
        f"block bootstrap should be wider on AR(1); naive={naive_width:.4f} "
        f"block={block_width:.4f}"
    )

    # Cost-adjusted Sharpe
    r = rng.standard_normal(500) * 0.01 + 0.0005
    s_free = cost_adjusted_sharpe(r, cost_per_trade=0.0, turnover=5.0)
    assert abs(s_free["gross_sharpe"] - s_free["net_sharpe"]) < 1e-12
    s_costly = cost_adjusted_sharpe(r, cost_per_trade=0.003, turnover=5.0)
    assert s_costly["gross_sharpe"] > s_costly["net_sharpe"]
    assert s_costly["daily_cost"] > 0

    print("hypothesis_testing smoke test: OK")


if __name__ == "__main__":
    _smoke_test()
