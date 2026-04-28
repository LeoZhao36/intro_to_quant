"""
hypothesis_testing.py

Statistical-test toolkit for Project 6 factor research. Centralises the seven
core functions developed across Project 4 sessions:

  Two-sample tests (Block 1):
    - t_test_two_sample    : Welch's t-test wrapper with CI
    - permutation_mean_diff: non-parametric two-sample mean-difference test

  Correlation test (Block 2):
    - permutation_correlation : non-parametric correlation test

  Bootstrap CIs (Block 3):
    - bootstrap_ci       : i.i.d. bootstrap CI for any 1-D statistic
    - block_bootstrap_ci : moving-block bootstrap for time-series statistics

  Standalone utilities (Block 4):
    - acf_band             : Bonferroni-adjusted ACF band half-width
    - cost_adjusted_sharpe : annualised gross and net Sharpe with linear cost

Multi-test correction policy (locked at Project 6 Session 1):
  - Headline factor tests (does factor F predict returns?): Holm-Bonferroni
    on the family of 4-5 factors. Same family-wise error guarantee as plain
    Bonferroni but uniformly more powerful.
  - Robustness follow-ups (does factor F survive sector neutralization,
    cap conditioning, regime split?): Benjamini-Hochberg on the per-factor
    family of 4-6 robustness variants. Controls false discovery rate
    rather than FWER, accepting that ~5% of accepted findings may be
    false alarms in exchange for not throwing out real effects that
    barely missed an FWER cut.
  Note: acf_band uses plain Bonferroni internally because it produces a
  single horizontal threshold for plotting, not a sorted-p-value procedure.

Design notes:
  - Functions return dicts of named results, not bare scalars. This makes
    downstream notebook code read what each value means without indexing.
  - Random-number generation uses np.random.default_rng(seed). The legacy
    np.random.seed global is avoided to make function calls reproducible
    in isolation.
  - NaN values are dropped at the function boundary, not silently
    propagated. Empty-after-drop inputs raise ValueError rather than
    returning NaN p-values that hide bugs.
"""

from typing import Callable, Optional, Sequence

import numpy as np
from scipy import stats


# ─── Block 1: Two-sample tests ──────────────────────────────


def t_test_two_sample(
    a: Sequence[float],
    b: Sequence[float],
    confidence: float = 0.95,
    equal_var: bool = False,
) -> dict:
    """
    Welch's two-sample t-test for the difference of means.

    Tests H0: mean(a) == mean(b) against the two-sided alternative.
    Welch's correction (equal_var=False, default) does not assume the
    two populations share variance. Use equal_var=True only when you
    have a substantive reason to assume equal variance.

    Parameters
    ----------
    a, b : array-like
        The two samples. NaN values are dropped before the test.
    confidence : float, default 0.95
        Confidence level for the CI on the mean difference.
    equal_var : bool, default False
        If True, run the original Student's t-test (assumes equal variance).

    Returns
    -------
    dict with keys:
        t          : t-statistic
        p_value    : two-sided p-value
        mean_diff  : mean(a) - mean(b)
        ci_low,
        ci_high    : confidence interval for mean_diff
        n_a, n_b   : sample sizes after NaN-drop
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]

    if len(a) < 2 or len(b) < 2:
        raise ValueError(
            f"each sample needs at least 2 non-NaN observations; got n_a={len(a)}, n_b={len(b)}"
        )
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1); got {confidence}")

    result = stats.ttest_ind(a, b, equal_var=equal_var)
    ci = result.confidence_interval(confidence_level=confidence)

    return {
        "t": float(result.statistic),
        "p_value": float(result.pvalue),
        "mean_diff": float(a.mean() - b.mean()),
        "ci_low": float(ci.low),
        "ci_high": float(ci.high),
        "n_a": int(len(a)),
        "n_b": int(len(b)),
    }


def permutation_mean_diff(
    a: Sequence[float],
    b: Sequence[float],
    n_iter: int = 10_000,
    seed: Optional[int] = None,
) -> dict:
    """
    Two-sample mean-difference permutation test.

    Tests H0: a and b are drawn from the same distribution against the
    two-sided alternative that the means differ. Builds the null
    distribution by repeatedly shuffling pooled labels and recomputing
    the mean difference. Makes no parametric assumption beyond
    exchangeability under the null.

    Parameters
    ----------
    a, b : array-like
        The two samples. NaN values are dropped.
    n_iter : int, default 10_000
        Number of label permutations. Below 100 the p-value estimate
        is too noisy to use; below 1000 expect ±0.01 jitter.
    seed : int or None, default None
        Seed for the np.random.default_rng() instance. Pass an int for
        reproducible smoke tests; leave None for production use.

    Returns
    -------
    dict with keys:
        observed_diff      : mean(a) - mean(b)
        p_value            : two-sided permutation p-value
        null_distribution  : np.ndarray of n_iter shuffled mean-differences
        n_iter             : echoed back for clarity
        n_a, n_b           : sample sizes after NaN-drop
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]

    if len(a) < 1 or len(b) < 1:
        raise ValueError(
            f"each sample needs at least 1 non-NaN observation; got n_a={len(a)}, n_b={len(b)}"
        )
    if n_iter < 100:
        raise ValueError(f"n_iter < 100 produces unstable p-value estimates; got {n_iter}")

    rng = np.random.default_rng(seed)
    observed_diff = a.mean() - b.mean()

    pooled = np.concatenate([a, b])
    n_a = len(a)
    null_diffs = np.empty(n_iter)
    for i in range(n_iter):
        rng.shuffle(pooled)
        null_diffs[i] = pooled[:n_a].mean() - pooled[n_a:].mean()

    p_two_sided = float(np.mean(np.abs(null_diffs) >= np.abs(observed_diff)))

    return {
        "observed_diff": float(observed_diff),
        "p_value": p_two_sided,
        "null_distribution": null_diffs,
        "n_iter": int(n_iter),
        "n_a": int(len(a)),
        "n_b": int(len(b)),
    }


# ─── Block 2: Correlation test ──────────────────────────────


def permutation_correlation(
    x: Sequence[float],
    y: Sequence[float],
    n_iter: int = 10_000,
    method: str = "spearman",
    seed: Optional[int] = None,
) -> dict:
    """
    Permutation test for the correlation between paired samples x and y.

    Tests H0: x and y are independent against the two-sided alternative
    that they are correlated. Shuffles y while x stays fixed and
    recomputes the correlation under each shuffle. Makes no parametric
    assumption beyond independent observations under the null.

    Parameters
    ----------
    x, y : array-like, same length
        Paired observations. NaN-pairs are dropped.
    n_iter : int, default 10_000
        Number of label permutations.
    method : {"spearman", "pearson"}, default "spearman"
        Spearman is the factor-IC default (rank-based, robust to fat
        tails and monotone-but-nonlinear relationships). Pearson assumes
        a linear relationship and is more sensitive to outliers.
    seed : int or None, default None

    Returns
    -------
    dict with keys:
        observed_corr      : the correlation in the original pairing
        p_value            : two-sided permutation p-value
        null_distribution  : np.ndarray of n_iter shuffled correlations
        method             : echoed back
        n_iter             : echoed back
        n_obs              : pairs after NaN-drop

    Notes
    -----
    The implementation pre-computes the centred x, the centred y, and
    their L2 norms once. Shuffling y preserves both mean(y) and
    ||y_centred||, so the correlation denominator is invariant across
    iterations and only the numerator (the cross-product sum) needs
    recomputing each iteration.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.shape != y.shape:
        raise ValueError(f"x and y must have the same shape; got {x.shape} vs {y.shape}")

    valid = ~(np.isnan(x) | np.isnan(y))
    x = x[valid]
    y = y[valid]

    if len(x) < 3:
        raise ValueError(f"need at least 3 non-NaN paired observations; got {len(x)}")
    if n_iter < 100:
        raise ValueError(f"n_iter < 100 produces unstable p-value estimates; got {n_iter}")
    if method not in ("spearman", "pearson"):
        raise ValueError(f"method must be 'spearman' or 'pearson'; got {method!r}")

    if method == "spearman":
        x = stats.rankdata(x)
        y = stats.rankdata(y)

    # Pre-compute pieces invariant under shuffling of y.
    x_centred = x - x.mean()
    y_centred = y - y.mean()
    x_norm = np.sqrt((x_centred ** 2).sum())
    y_norm = np.sqrt((y_centred ** 2).sum())
    if x_norm == 0 or y_norm == 0:
        raise ValueError("zero variance in x or y; correlation undefined")
    denom = x_norm * y_norm

    observed_corr = float((x_centred * y_centred).sum() / denom)

    rng = np.random.default_rng(seed)
    y_shuffled = y_centred.copy()
    null_corrs = np.empty(n_iter)
    for i in range(n_iter):
        rng.shuffle(y_shuffled)
        null_corrs[i] = (x_centred * y_shuffled).sum() / denom

    p_two_sided = float(np.mean(np.abs(null_corrs) >= np.abs(observed_corr)))

    return {
        "observed_corr": observed_corr,
        "p_value": p_two_sided,
        "null_distribution": null_corrs,
        "method": method,
        "n_iter": int(n_iter),
        "n_obs": int(len(x)),
    }


# ─── Block 3: Bootstrap CIs ─────────────────────────────────


def bootstrap_ci(
    data: Sequence[float],
    statistic: Callable[[np.ndarray], float],
    n_boot: int = 10_000,
    ci: float = 0.95,
    seed: Optional[int] = None,
) -> dict:
    """
    Percentile-method bootstrap CI for a 1-D statistic.

    Resamples `data` with replacement `n_boot` times, computes
    `statistic` on each resample, and returns the (alpha/2, 1-alpha/2)
    quantiles of the bootstrap distribution as the CI. Assumes
    observations are i.i.d.; for serially correlated data use
    block_bootstrap_ci.

    Parameters
    ----------
    data : 1-D array-like
        Observations. NaN values are dropped.
    statistic : callable
        Function f(np.ndarray) -> float. Must accept an array and
        return a scalar (the statistic computed on that array).
    n_boot : int, default 10_000
    ci : float, default 0.95
        Confidence level.
    seed : int or None, default None

    Returns
    -------
    dict with keys:
        estimate           : statistic(data) (the point estimate)
        ci_low, ci_high    : percentile-method confidence interval
        ci_level           : echoed back
        boot_distribution  : np.ndarray of n_boot resampled statistics
        n_boot             : echoed back
        n_obs              : sample size after NaN-drop
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 1:
        raise ValueError(f"data must be 1-D; got shape {data.shape}")
    data = data[~np.isnan(data)]

    n = len(data)
    if n < 2:
        raise ValueError(f"need at least 2 non-NaN observations; got {n}")
    if n_boot < 100:
        raise ValueError(f"n_boot < 100 is unstable; got {n_boot}")
    if not 0 < ci < 1:
        raise ValueError(f"ci must be in (0, 1); got {ci}")

    rng = np.random.default_rng(seed)
    estimate = float(statistic(data))

    boot_stats = np.empty(n_boot)
    for b in range(n_boot):
        indices = rng.integers(0, n, size=n)
        boot_stats[b] = statistic(data[indices])

    alpha = 1.0 - ci
    low, high = np.quantile(boot_stats, [alpha / 2, 1 - alpha / 2])

    return {
        "estimate": estimate,
        "ci_low": float(low),
        "ci_high": float(high),
        "ci_level": float(ci),
        "boot_distribution": boot_stats,
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
    Moving-block bootstrap CI for a 1-D time-series statistic.

    Resamples blocks of `block_size` consecutive observations with
    replacement, concatenates them to length n, computes `statistic`
    on each resampled series. Preserves local autocorrelation up to
    lag block_size - 1.

    Parameters
    ----------
    data : 1-D array-like
        Time-ordered observations. NaN values are dropped (this can
        break the time ordering if NaN gaps are non-trivial; for
        long gaps consider imputation upstream).
    statistic : callable
        f(np.ndarray) -> float.
    block_size : int, default 20
        Block length. 20 is the Project 4 default for daily data
        (~4 trading weeks). For monthly data use 3 (~quarterly).
    n_boot : int, default 5_000
        Lower default than bootstrap_ci because per-iteration cost is
        higher. Increase if CI quantiles look unstable across reruns.
    ci : float, default 0.95
    seed : int or None, default None

    Returns
    -------
    dict with keys:
        estimate, ci_low, ci_high, ci_level, boot_distribution,
        n_boot, n_obs, block_size
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 1:
        raise ValueError(f"data must be 1-D; got shape {data.shape}")
    data = data[~np.isnan(data)]

    n = len(data)
    if block_size < 1:
        raise ValueError(f"block_size must be >= 1; got {block_size}")
    if n < 2 * block_size:
        raise ValueError(
            f"need at least 2 * block_size = {2 * block_size} observations; got {n}"
        )
    if n_boot < 100:
        raise ValueError(f"n_boot < 100 is unstable; got {n_boot}")
    if not 0 < ci < 1:
        raise ValueError(f"ci must be in (0, 1); got {ci}")

    rng = np.random.default_rng(seed)
    estimate = float(statistic(data))

    n_blocks = (n + block_size - 1) // block_size  # ceil(n / block_size)
    max_block_start = n - block_size  # inclusive
    offsets = np.arange(block_size)

    boot_stats = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, max_block_start + 1, size=n_blocks)
        # Build the resampled index array: each row of (n_blocks, block_size)
        # is one block; flatten and trim to length n.
        indices = (starts[:, None] + offsets[None, :]).ravel()[:n]
        boot_stats[b] = statistic(data[indices])

    alpha = 1.0 - ci
    low, high = np.quantile(boot_stats, [alpha / 2, 1 - alpha / 2])

    return {
        "estimate": estimate,
        "ci_low": float(low),
        "ci_high": float(high),
        "ci_level": float(ci),
        "boot_distribution": boot_stats,
        "n_boot": int(n_boot),
        "n_obs": int(n),
        "block_size": int(block_size),
    }


# ─── Block 4: Standalone utilities ──────────────────────────


def acf_band(
    n_obs: int,
    n_tests: int,
    family_alpha: float = 0.05,
) -> float:
    """
    Bonferroni-adjusted half-width for the autocorrelation confidence band.

    For a series of n_obs i.i.d. observations, the standard 95% ACF band
    at any single lag is +/- 1.96 / sqrt(n_obs). When you check n_tests
    lags simultaneously, the family-wise false-alarm rate inflates above
    5%. Bonferroni tightens the per-lag threshold to family_alpha / n_tests
    so the overall family-wise false-alarm rate stays at family_alpha.

    Returns the half-width of the widened band (positive scalar). Plot
    horizontal lines at +/- this value on the ACF chart.

    Parameters
    ----------
    n_obs : int
        Number of observations in the time series.
    n_tests : int
        Number of lags being tested simultaneously.
    family_alpha : float, default 0.05
        Family-wise alpha (the overall false-alarm rate target).

    Returns
    -------
    float
        Half-width of the Bonferroni-adjusted ACF confidence band.

    Notes
    -----
    Uses plain Bonferroni rather than Holm-Bonferroni because the band
    is a single horizontal threshold, not a sorted-p-value procedure.
    See the module docstring's lock-in decision for the family-level
    factor-testing correction policy.
    """
    if n_obs < 2:
        raise ValueError(f"n_obs must be >= 2; got {n_obs}")
    if n_tests < 1:
        raise ValueError(f"n_tests must be >= 1; got {n_tests}")
    if not 0 < family_alpha < 1:
        raise ValueError(f"family_alpha must be in (0, 1); got {family_alpha}")

    per_test_alpha = family_alpha / n_tests
    z = stats.norm.ppf(1 - per_test_alpha / 2)
    return float(z / np.sqrt(n_obs))


def cost_adjusted_sharpe(
    returns: Sequence[float],
    cost_per_trade: float,
    turnover,
    periods_per_year: int = 252,
) -> dict:
    """
    Annualised gross and net Sharpe ratios with linear cost adjustment.

    Net return per period = gross return per period - turnover * cost_per_trade.
    Sharpe = mean / std, scaled by sqrt(periods_per_year).

    Parameters
    ----------
    returns : 1-D array-like
        Per-period gross returns (e.g., daily or monthly). Must not
        contain NaN; impute or drop upstream if needed.
    cost_per_trade : float
        Round-trip transaction cost as a decimal (0.0020 = 20 bps).
        Must be non-negative.
    turnover : float or 1-D array-like
        Fraction of the portfolio replaced per period (0.5 = 50%).
        Scalar applies to all periods. Array must match returns length.
    periods_per_year : int, default 252
        Annualisation factor. 252 for daily, 12 for monthly, 52 for
        weekly, 1 for already-annualised returns.

    Returns
    -------
    dict with keys:
        gross_sharpe, net_sharpe         : annualised
        gross_mean_per_period,
        net_mean_per_period              : per-period means
        gross_std_per_period,
        net_std_per_period               : per-period std (ddof=1)
        cost_drag_annualised             : (gross - net) Sharpe gap
        n_obs, periods_per_year
    """
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 1:
        raise ValueError(f"returns must be 1-D; got shape {returns.shape}")
    if np.any(np.isnan(returns)):
        raise ValueError("returns contains NaN; impute or drop upstream")
    if len(returns) < 2:
        raise ValueError(f"need at least 2 observations; got {len(returns)}")
    if cost_per_trade < 0:
        raise ValueError(f"cost_per_trade must be non-negative; got {cost_per_trade}")
    if periods_per_year < 1:
        raise ValueError(f"periods_per_year must be >= 1; got {periods_per_year}")

    turnover_arr = np.asarray(turnover, dtype=float)
    if turnover_arr.ndim == 0:
        net_returns = returns - float(turnover_arr) * cost_per_trade
    elif turnover_arr.ndim == 1:
        if len(turnover_arr) != len(returns):
            raise ValueError(
                f"turnover length {len(turnover_arr)} != returns length {len(returns)}"
            )
        net_returns = returns - turnover_arr * cost_per_trade
    else:
        raise ValueError(f"turnover must be scalar or 1-D; got shape {turnover_arr.shape}")
    if np.any(turnover_arr < 0):
        raise ValueError("turnover must be non-negative")

    sqrt_periods = np.sqrt(periods_per_year)
    gross_mean = float(returns.mean())
    gross_std = float(returns.std(ddof=1))
    net_mean = float(net_returns.mean())
    net_std = float(net_returns.std(ddof=1))

    if gross_std == 0 or net_std == 0:
        raise ValueError("zero return variance; Sharpe undefined")

    gross_sharpe = gross_mean / gross_std * sqrt_periods
    net_sharpe = net_mean / net_std * sqrt_periods

    return {
        "gross_sharpe": gross_sharpe,
        "net_sharpe": net_sharpe,
        "gross_mean_per_period": gross_mean,
        "net_mean_per_period": net_mean,
        "gross_std_per_period": gross_std,
        "net_std_per_period": net_std,
        "cost_drag_annualised": gross_sharpe - net_sharpe,
        "n_obs": int(len(returns)),
        "periods_per_year": int(periods_per_year),
    }


# ─── Smoke tests ────────────────────────────────────────────


def _smoke_test_t_test_two_sample() -> None:
    rng = np.random.default_rng(42)

    # Same distribution: p-value should be large
    a = rng.normal(0, 1, 200)
    b = rng.normal(0, 1, 200)
    res = t_test_two_sample(a, b)
    assert res["p_value"] > 0.05, f"same-dist p={res['p_value']:.3f}, expected > 0.05"
    assert res["ci_low"] <= res["mean_diff"] <= res["ci_high"], "CI must contain mean_diff"
    assert res["n_a"] == 200 and res["n_b"] == 200

    # Strongly different means: p-value should be tiny
    a = rng.normal(0, 1, 200)
    b = rng.normal(0.5, 1, 200)
    res = t_test_two_sample(a, b)
    assert res["p_value"] < 0.01, f"diff-mean p={res['p_value']:.4f}, expected < 0.01"

    # NaN handling
    a = np.array([1.0, 2.0, np.nan, 3.0, 4.0])
    b = np.array([np.nan, 5.0, 6.0, 7.0])
    res = t_test_two_sample(a, b)
    assert res["n_a"] == 4 and res["n_b"] == 3

    # Empty after NaN-drop should raise
    try:
        t_test_two_sample([np.nan, np.nan], [1.0, 2.0])
        raise RuntimeError("should have raised on all-NaN input")
    except ValueError:
        pass

    # Bad confidence level should raise
    try:
        t_test_two_sample([1.0, 2.0], [3.0, 4.0], confidence=1.5)
        raise RuntimeError("should have raised on confidence > 1")
    except ValueError:
        pass

    print("t_test_two_sample: OK")


def _smoke_test_permutation_mean_diff() -> None:
    rng = np.random.default_rng(42)

    # Same distribution: p-value should be large
    a = rng.normal(0, 1, 100)
    b = rng.normal(0, 1, 100)
    res = permutation_mean_diff(a, b, n_iter=2000, seed=0)
    assert res["p_value"] > 0.05, f"same-dist p={res['p_value']:.3f}, expected > 0.05"
    assert len(res["null_distribution"]) == 2000

    # Strongly different means: p-value should be small
    a = rng.normal(0, 1, 100)
    b = rng.normal(0.5, 1, 100)
    res = permutation_mean_diff(a, b, n_iter=2000, seed=0)
    assert res["p_value"] < 0.05, f"diff-mean p={res['p_value']:.4f}, expected < 0.05"

    # observed_diff should match a.mean() - b.mean() exactly
    expected = a.mean() - b.mean()
    assert abs(res["observed_diff"] - expected) < 1e-12

    # Reproducibility with seed
    res1 = permutation_mean_diff(a, b, n_iter=2000, seed=123)
    res2 = permutation_mean_diff(a, b, n_iter=2000, seed=123)
    assert res1["p_value"] == res2["p_value"]

    # n_iter too small should raise
    try:
        permutation_mean_diff(a, b, n_iter=50)
        raise RuntimeError("should have raised on n_iter < 100")
    except ValueError:
        pass

    print("permutation_mean_diff: OK")


def _smoke_test_permutation_correlation() -> None:
    rng = np.random.default_rng(42)

    # Independent series: p-value should be large
    x = rng.normal(0, 1, 200)
    y = rng.normal(0, 1, 200)
    res = permutation_correlation(x, y, n_iter=2000, seed=0)
    assert res["p_value"] > 0.05, f"independent p={res['p_value']:.3f}, expected > 0.05"
    assert len(res["null_distribution"]) == 2000

    # Strongly correlated: p should be tiny
    x = rng.normal(0, 1, 200)
    y = 2 * x + rng.normal(0, 0.5, 200)
    res = permutation_correlation(x, y, n_iter=2000, seed=0)
    assert res["p_value"] < 0.01, f"correlated p={res['p_value']:.4f}, expected < 0.01"
    assert res["observed_corr"] > 0.8, f"observed_corr={res['observed_corr']:.3f}"

    # Spearman should match scipy.stats.spearmanr on the observed correlation
    x = rng.normal(0, 1, 100)
    y = rng.normal(0, 1, 100)
    res = permutation_correlation(x, y, n_iter=200, method="spearman", seed=0)
    scipy_rho = stats.spearmanr(x, y).statistic
    assert abs(res["observed_corr"] - scipy_rho) < 1e-10, (
        f"observed={res['observed_corr']}, scipy={scipy_rho}"
    )

    # Pearson should match np.corrcoef on the observed correlation
    res = permutation_correlation(x, y, n_iter=200, method="pearson", seed=0)
    np_r = float(np.corrcoef(x, y)[0, 1])
    assert abs(res["observed_corr"] - np_r) < 1e-10

    # Reproducibility with seed
    r1 = permutation_correlation(x, y, n_iter=500, seed=99)
    r2 = permutation_correlation(x, y, n_iter=500, seed=99)
    assert r1["p_value"] == r2["p_value"]

    # Length mismatch should raise
    try:
        permutation_correlation([1.0, 2.0, 3.0], [1.0, 2.0])
        raise RuntimeError("should have raised on shape mismatch")
    except ValueError:
        pass

    # Invalid method should raise
    try:
        permutation_correlation(x, y, method="kendall")
        raise RuntimeError("should have raised on invalid method")
    except ValueError:
        pass

    # Constant x should raise (zero variance)
    try:
        permutation_correlation(np.zeros(10), np.arange(10), method="pearson")
        raise RuntimeError("should have raised on zero-variance input")
    except ValueError:
        pass

    print("permutation_correlation: OK")


def _smoke_test_bootstrap_ci() -> None:
    rng = np.random.default_rng(42)

    # CI on the mean of a normal sample: should contain the true mean
    n = 500
    true_mean = 0.0
    x = rng.normal(true_mean, 1.0, n)
    res = bootstrap_ci(x, np.mean, n_boot=2000, seed=0)
    assert res["ci_low"] < true_mean < res["ci_high"], (
        f"95% CI ({res['ci_low']:.3f}, {res['ci_high']:.3f}) misses true mean {true_mean}"
    )
    assert res["n_obs"] == n
    assert len(res["boot_distribution"]) == 2000

    # CI shrinks as n grows: standard-error scaling
    x_small = rng.normal(0, 1, 50)
    x_large = rng.normal(0, 1, 5000)
    width_small = (
        bootstrap_ci(x_small, np.mean, n_boot=1000, seed=1)["ci_high"]
        - bootstrap_ci(x_small, np.mean, n_boot=1000, seed=1)["ci_low"]
    )
    width_large = (
        bootstrap_ci(x_large, np.mean, n_boot=1000, seed=1)["ci_high"]
        - bootstrap_ci(x_large, np.mean, n_boot=1000, seed=1)["ci_low"]
    )
    assert width_small > 5 * width_large, (
        f"large-n CI width {width_large:.3f} should be much smaller than small-n {width_small:.3f}"
    )

    # Custom statistic: median
    x = rng.normal(0, 1, 200)
    res = bootstrap_ci(x, np.median, n_boot=1000, seed=0)
    assert res["ci_low"] < 0 < res["ci_high"]

    # Reproducibility with seed
    r1 = bootstrap_ci(x, np.mean, n_boot=500, seed=99)
    r2 = bootstrap_ci(x, np.mean, n_boot=500, seed=99)
    assert r1["ci_low"] == r2["ci_low"] and r1["ci_high"] == r2["ci_high"]

    # 99% CI is wider than 90% CI
    r90 = bootstrap_ci(x, np.mean, n_boot=2000, ci=0.90, seed=0)
    r99 = bootstrap_ci(x, np.mean, n_boot=2000, ci=0.99, seed=0)
    assert (r99["ci_high"] - r99["ci_low"]) > (r90["ci_high"] - r90["ci_low"])

    # Edge cases
    try:
        bootstrap_ci([1.0], np.mean)
        raise RuntimeError("should have raised on n < 2")
    except ValueError:
        pass
    try:
        bootstrap_ci(np.zeros((10, 2)), np.mean)
        raise RuntimeError("should have raised on 2-D input")
    except ValueError:
        pass

    print("bootstrap_ci: OK")


def _smoke_test_block_bootstrap_ci() -> None:
    rng = np.random.default_rng(42)

    # CI on the mean of i.i.d. data: should contain true mean
    x = rng.normal(0, 1, 500)
    res = block_bootstrap_ci(x, np.mean, block_size=20, n_boot=1000, seed=0)
    assert res["ci_low"] < 0 < res["ci_high"]
    assert res["block_size"] == 20

    # AR(1) demonstration: block bootstrap CI for the mean should be wider
    # than i.i.d. bootstrap CI, by approximately sqrt((1+rho)/(1-rho)).
    # For rho = 0.5, this factor is sqrt(3) ~= 1.73.
    rho = 0.5
    n = 1000
    eps = rng.normal(0, 1, n)
    ar1 = np.zeros(n)
    ar1[0] = eps[0]
    for t in range(1, n):
        ar1[t] = rho * ar1[t - 1] + eps[t]

    iid = bootstrap_ci(ar1, np.mean, n_boot=2000, seed=0)
    blk = block_bootstrap_ci(ar1, np.mean, block_size=20, n_boot=2000, seed=0)
    iid_width = iid["ci_high"] - iid["ci_low"]
    blk_width = blk["ci_high"] - blk["ci_low"]
    ratio = blk_width / iid_width
    # Sanity range; theoretical ratio ~1.73 for rho=0.5
    assert 1.3 < ratio < 2.2, (
        f"block/iid CI width ratio {ratio:.2f} outside expected (1.3, 2.2) for rho=0.5"
    )
    print(
        f"  AR(1) rho=0.5: i.i.d. width {iid_width:.3f}, block width {blk_width:.3f}, "
        f"ratio {ratio:.2f}x (theoretical ~1.73x)"
    )

    # Reproducibility with seed
    r1 = block_bootstrap_ci(x, np.mean, block_size=10, n_boot=500, seed=99)
    r2 = block_bootstrap_ci(x, np.mean, block_size=10, n_boot=500, seed=99)
    assert r1["ci_low"] == r2["ci_low"]

    # block_size too large should raise
    try:
        block_bootstrap_ci(np.arange(20.0), np.mean, block_size=15)
        raise RuntimeError("should have raised on block_size > n/2")
    except ValueError:
        pass

    # block_size < 1 should raise
    try:
        block_bootstrap_ci(np.arange(100.0), np.mean, block_size=0)
        raise RuntimeError("should have raised on block_size < 1")
    except ValueError:
        pass

    print("block_bootstrap_ci: OK")


def _smoke_test_acf_band() -> None:
    # Single-test case must reduce to standard 1.96 / sqrt(n)
    band = acf_band(n_obs=500, n_tests=1, family_alpha=0.05)
    expected = 1.959963984540054 / np.sqrt(500)
    assert abs(band - expected) < 1e-10, f"single-test band {band} != {expected}"

    # Larger n_tests should produce wider band (stricter threshold)
    b1 = acf_band(n_obs=500, n_tests=1)
    b20 = acf_band(n_obs=500, n_tests=20)
    assert b20 > b1, f"n_tests=20 band {b20} should exceed n_tests=1 band {b1}"

    # Larger n_obs should produce narrower band
    b_small = acf_band(n_obs=100, n_tests=20)
    b_large = acf_band(n_obs=10_000, n_tests=20)
    assert b_large < b_small

    # Tighter family_alpha gives wider band
    b05 = acf_band(n_obs=500, n_tests=20, family_alpha=0.05)
    b01 = acf_band(n_obs=500, n_tests=20, family_alpha=0.01)
    assert b01 > b05

    # Edge cases
    try:
        acf_band(n_obs=1, n_tests=5)
        raise RuntimeError("should have raised on n_obs < 2")
    except ValueError:
        pass
    try:
        acf_band(n_obs=100, n_tests=0)
        raise RuntimeError("should have raised on n_tests < 1")
    except ValueError:
        pass
    try:
        acf_band(n_obs=100, n_tests=20, family_alpha=1.5)
        raise RuntimeError("should have raised on bad family_alpha")
    except ValueError:
        pass

    print("acf_band: OK")


def _smoke_test_cost_adjusted_sharpe() -> None:
    rng = np.random.default_rng(42)

    # Zero costs: gross Sharpe == net Sharpe
    returns = rng.normal(0.0005, 0.01, 252)  # daily-ish
    res = cost_adjusted_sharpe(returns, cost_per_trade=0.0, turnover=1.0)
    assert abs(res["gross_sharpe"] - res["net_sharpe"]) < 1e-10
    assert res["cost_drag_annualised"] == 0.0

    # Zero turnover: same
    res = cost_adjusted_sharpe(returns, cost_per_trade=0.001, turnover=0.0)
    assert abs(res["gross_sharpe"] - res["net_sharpe"]) < 1e-10

    # Positive cost AND turnover: net < gross
    res = cost_adjusted_sharpe(returns, cost_per_trade=0.002, turnover=0.5)
    assert res["net_sharpe"] < res["gross_sharpe"]
    assert res["cost_drag_annualised"] > 0

    # Worked example: monthly factor strategy
    # gross mean 1.5%, std 4%, cost 20bp, turnover 80% -> Sharpe gap ~0.14
    rng2 = np.random.default_rng(0)
    monthly_returns = rng2.normal(0.015, 0.04, 60)
    res = cost_adjusted_sharpe(
        monthly_returns,
        cost_per_trade=0.0020,
        turnover=0.80,
        periods_per_year=12,
    )
    # Annualised gross Sharpe should be roughly (0.015 / 0.04) * sqrt(12) ~ 1.30
    # exact value depends on the realized sample; just sanity-check the gap
    sharpe_gap = res["gross_sharpe"] - res["net_sharpe"]
    # Cost drag per month = 0.80 * 0.0020 = 0.0016; gap in Sharpe ~ 0.0016 / std * sqrt(12)
    expected_gap = 0.0016 / res["gross_std_per_period"] * np.sqrt(12)
    assert abs(sharpe_gap - expected_gap) < 0.01, (
        f"sharpe_gap {sharpe_gap:.3f} vs expected ~{expected_gap:.3f}"
    )

    # Per-period turnover array
    n = 60
    turnover_arr = rng.uniform(0.3, 0.9, n)
    monthly_returns = rng.normal(0.01, 0.03, n)
    res = cost_adjusted_sharpe(
        monthly_returns,
        cost_per_trade=0.0015,
        turnover=turnover_arr,
        periods_per_year=12,
    )
    assert res["net_sharpe"] < res["gross_sharpe"]

    # Edge cases
    try:
        cost_adjusted_sharpe(monthly_returns, cost_per_trade=-0.001, turnover=0.5)
        raise RuntimeError("should have raised on negative cost")
    except ValueError:
        pass
    try:
        cost_adjusted_sharpe(np.array([1.0, np.nan, 2.0]), 0.001, 0.5)
        raise RuntimeError("should have raised on NaN")
    except ValueError:
        pass
    try:
        # turnover array length mismatch
        cost_adjusted_sharpe(monthly_returns, 0.001, np.array([0.5, 0.5]))
        raise RuntimeError("should have raised on length mismatch")
    except ValueError:
        pass

    print("cost_adjusted_sharpe: OK")


def _smoke_test_all() -> None:
    _smoke_test_t_test_two_sample()
    _smoke_test_permutation_mean_diff()
    _smoke_test_permutation_correlation()
    _smoke_test_bootstrap_ci()
    _smoke_test_block_bootstrap_ci()
    _smoke_test_acf_band()
    _smoke_test_cost_adjusted_sharpe()
    print("hypothesis_testing smoke test: OK")


if __name__ == "__main__":
    _smoke_test_all()